"""Studio FA server — FastAPI app behind the Persian control panel.

Everything heavy runs through the existing tools (tts_selector, subtitle_gen,
video_compose) so the panel exercises the same code a pipeline does. Output
goes to .studio_fa/ at the repo root, never into projects/.
"""

from __future__ import annotations

import asyncio
import json
import os
import re
import shutil
import subprocess
import sys
import threading
import time
import urllib.request
import uuid
from pathlib import Path
from typing import Literal, Optional

from fastapi import Depends, FastAPI, HTTPException, Request
from fastapi.middleware.trustedhost import TrustedHostMiddleware
from fastapi.responses import FileResponse, HTMLResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

REPO_ROOT = Path(__file__).resolve().parent.parent
UI_DIR = Path(__file__).resolve().parent / "ui"
STATE_DIR = REPO_ROOT / ".studio_fa"
ENV_PATH = REPO_ROOT / ".env"

# Keys the panel may read (as set/unset) and write. Values are never sent back.
EDITABLE_ENV = {
    "GOOGLE_API_KEY": "secret",
    "AVALAI_API_KEY": "secret",
    "OPENAI_API_KEY": "secret",
    "ELEVENLABS_API_KEY": "secret",
    "MOONSHOT_API_KEY": "secret",
    "OPENROUTER_API_KEY": "secret",
    "OPENAI_BASE_URL": "plain",
    "SUBTITLE_FONTS_DIR": "plain",
}
PERSIAN_TESTS = [
    "tests/tools/test_persian_localization.py",
    "tests/tools/test_avalai_gemini_tts.py",
    "tests/tools/test_subtitle_fonts_dir.py",
    "tests/tools/test_studio_fa.py",
]
# Gemini input is capped at 8,192 tokens; this keeps one audition well under
# that and well under a cent.
MAX_TTS_CHARS = 3000
VOICE_CACHE_SECONDS = 7 * 24 * 3600
FALLBACK_VOICES = [
    "Kore", "Puck", "Charon", "Fenrir", "Aoede", "Leda", "Orus", "Zephyr",
    "Achernar", "Achird", "Algenib", "Algieba", "Alnilam", "Autonoe",
    "Callirrhoe", "Despina", "Enceladus", "Erinome", "Gacrux", "Iapetus",
    "Laomedeia", "Pulcherrima", "Rasalgethi", "Sadachbia", "Sadaltager",
    "Schedar", "Sulafat", "Umbriel", "Vindemiatrix", "Zubenelgenubi",
]

_tests_lock = threading.Lock()


def _require_panel(request: Request) -> None:
    # A custom header forces a CORS preflight, which this server never
    # answers, so another site open in the browser cannot trigger paid calls.
    if request.headers.get("x-studio-fa") != "1":
        raise HTTPException(status_code=403, detail="missing x-studio-fa header")


# ---- .env ------------------------------------------------------------------

def _write_env(name: str, value: str) -> None:
    lines = ENV_PATH.read_text(encoding="utf-8").splitlines() if ENV_PATH.exists() else []
    pattern = re.compile(rf"^\s*{re.escape(name)}\s*=")
    for i, line in enumerate(lines):
        if pattern.match(line):
            lines[i] = f"{name}={value}"
            break
    else:
        lines.append(f"{name}={value}")
    ENV_PATH.write_text("\n".join(lines) + "\n", encoding="utf-8")
    if value:
        os.environ[name] = value
    else:
        os.environ.pop(name, None)


def _env_summary() -> dict:
    summary = {}
    for name, kind in EDITABLE_ENV.items():
        value = os.environ.get(name, "")
        summary[name] = {"set": bool(value), "value": value if kind == "plain" else None}
    return summary


# ---- status ----------------------------------------------------------------

def find_vazirmatn() -> Optional[Path]:
    candidates = [os.environ.get("SUBTITLE_FONTS_DIR")]
    if os.environ.get("LOCALAPPDATA"):
        candidates.append(str(Path(os.environ["LOCALAPPDATA"]) / "Microsoft/Windows/Fonts"))
    candidates += [
        "C:/Windows/Fonts",
        "/usr/share/fonts/truetype/vazirmatn",
        "/usr/share/fonts/truetype",
        str(Path.home() / ".local/share/fonts"),
    ]
    for folder in filter(None, candidates):
        hit = next(Path(folder).glob("Vazirmatn*-Regular.ttf"), None) if Path(folder).is_dir() else None
        if hit:
            return hit.parent
    return None


def _status() -> dict:
    from tools.audio.tts_selector import PERSIAN_TTS_PRIORITY
    from tools.base_tool import ToolStatus
    from tools.tool_registry import registry

    registry.ensure_discovered()
    providers = []
    for name in PERSIAN_TTS_PRIORITY:
        tool = registry.get(name)
        providers.append({
            "name": name,
            "provider": tool.provider if tool else None,
            "available": bool(tool) and tool.get_status() == ToolStatus.AVAILABLE,
            "install": tool.install_instructions if tool else "",
        })
    fonts = find_vazirmatn()
    return {
        "providers": providers,
        "ffmpeg": shutil.which("ffmpeg") is not None,
        "font_dir": str(fonts) if fonts else None,
        "env": _env_summary(),
    }


# ---- voices ----------------------------------------------------------------

def _voices() -> dict:
    cache = STATE_DIR / "voices.json"
    if cache.exists() and time.time() - cache.stat().st_mtime < VOICE_CACHE_SECONDS:
        return json.loads(cache.read_text(encoding="utf-8"))

    key = os.environ.get("GOOGLE_API_KEY") or os.environ.get("GEMINI_API_KEY")
    fallback = {"source": "builtin", "voices": [{"id": v} for v in FALLBACK_VOICES]}
    if not key:
        return fallback
    from tools.provider_jobs import request_json

    voices, token = [], None
    try:
        while True:
            url = "https://generativelanguage.googleapis.com/v1beta/voices?pageSize=200"
            if token:
                url += f"&pageToken={token}"
            page = request_json("GET", url, headers={"x-goog-api-key": key})
            voices += page.get("voices", [])
            token = page.get("next_page_token") or page.get("nextPageToken")
            if not token:
                break
    except Exception:
        return fallback

    # The library repeats each base voice per locale; one entry per name is
    # enough here (Persian has no locale of its own), preferring en-US text.
    by_name: dict[str, dict] = {}
    for v in sorted(voices, key=lambda v: v.get("language_code") != "en-US"):
        name = v.get("display_name") or v.get("id")
        if name and name not in by_name:
            by_name[name] = {
                "id": name,
                "gender": v.get("gender"),
                "pitch": v.get("pitch"),
                "persona": v.get("persona"),
                "description": v.get("description"),
            }
    result = {"source": "gemini", "voices": sorted(by_name.values(), key=lambda v: v["id"])}
    STATE_DIR.mkdir(parents=True, exist_ok=True)
    cache.write_text(json.dumps(result, ensure_ascii=False), encoding="utf-8")
    return result


# ---- TTS -------------------------------------------------------------------

class TTSRequest(BaseModel):
    text: str = Field(min_length=1, max_length=MAX_TTS_CHARS)
    voice_id: str = Field(default="Kore", pattern=r"^[A-Za-z][A-Za-z0-9_-]{0,40}$")
    style: str = Field(default="", max_length=500)
    model_id: Literal["gemini-3.8-flash-lite-tts", "gemini-3.8-flash-tts"] = "gemini-3.8-flash-lite-tts"
    provider: Literal["auto", "gemini", "avalai"] = "auto"


def _history_path() -> Path:
    return STATE_DIR / "tts_history.jsonl"


def _read_history(limit: int = 50) -> list[dict]:
    path = _history_path()
    if not path.exists():
        return []
    rows = [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]
    return rows[::-1][:limit]


def _synthesize(req: TTSRequest) -> dict:
    from tools.audio.tts_selector import TTSSelector

    out_dir = STATE_DIR / "tts"
    out_dir.mkdir(parents=True, exist_ok=True)
    clip_id = time.strftime("%Y%m%d-%H%M%S-") + uuid.uuid4().hex[:6]
    path = out_dir / f"{clip_id}.wav"

    inputs = {
        "text": req.text.strip(),
        "voice_id": req.voice_id,
        "model_id": req.model_id,
        "language_code": "fa",
        "output_path": str(path),
    }
    if req.style.strip():
        inputs["style"] = req.style.strip()
    if req.provider != "auto":
        inputs["preferred_provider"] = req.provider

    started = time.time()
    result = TTSSelector().execute(inputs)
    if not result.success:
        raise HTTPException(status_code=502, detail=result.error or "TTS failed")

    duration = result.data.get("audio_duration_seconds")
    entry = {
        "id": clip_id,
        "created": time.time(),
        "text": inputs["text"],
        "voice_id": req.voice_id,
        "style": req.style.strip(),
        "model_id": req.model_id,
        "requested_provider": req.provider,
        "selected_tool": result.data.get("selected_tool"),
        "duration": duration,
        "cps": round(len(inputs["text"]) / duration, 1) if duration else None,
        "cost_usd": result.cost_usd,
        "fallback_from": result.data.get("fallback_from", []),
        "elapsed": round(time.time() - started, 1),
        "url": f"/media/tts/{path.name}",
    }
    with _history_path().open("a", encoding="utf-8") as f:
        f.write(json.dumps(entry, ensure_ascii=False) + "\n")
    return entry


# ---- subtitles -------------------------------------------------------------

class SubtitleRequest(BaseModel):
    lines: list[str] = Field(min_length=1, max_length=4)
    font_size: int = Field(default=36, ge=16, le=96)


def _subtitle_frames(req: SubtitleRequest) -> dict:
    from tools.subtitle.subtitle_gen import SubtitleGen
    from tools.video.video_compose import VideoCompose

    if not shutil.which("ffmpeg"):
        raise HTTPException(status_code=500, detail="ffmpeg is not on PATH")
    lines = [line.strip()[:160] for line in req.lines if line.strip()]
    if not lines:
        raise HTTPException(status_code=400, detail="no subtitle text")

    run_id = uuid.uuid4().hex[:8]
    work = STATE_DIR / "frames" / run_id
    work.mkdir(parents=True, exist_ok=True)
    segments = [{"start": i * 2.0, "end": i * 2.0 + 2.0, "text": t} for i, t in enumerate(lines)]
    srt = work / "preview.srt"
    gen = SubtitleGen().execute({"segments": segments, "output_path": str(srt)})
    if not gen.success:
        raise HTTPException(status_code=500, detail=gen.error)

    background = work / "background.mp4"
    subprocess.run(
        ["ffmpeg", "-y", "-loglevel", "error", "-f", "lavfi",
         "-i", f"color=c=0x1e293b:s=1280x720:d={len(lines) * 2}:r=25", str(background)],
        check=True, capture_output=True,
    )
    style = {"font": "Vazirmatn", "font_size": req.font_size}
    fonts = find_vazirmatn()
    if fonts:
        style["fonts_dir"] = str(fonts)
    burned = work / "burned.mp4"
    compose = VideoCompose().execute({
        "operation": "burn_subtitles",
        "input_path": str(background),
        "subtitle_path": str(srt),
        "output_path": str(burned),
        "subtitle_style": style,
    })
    if not compose.success:
        raise HTTPException(status_code=500, detail=compose.error)

    frames = []
    for i in range(len(lines)):
        frame = work / f"line{i + 1}.png"
        # -ss after -i: decode-accurate seek, so the cue timing is respected.
        subprocess.run(
            ["ffmpeg", "-y", "-loglevel", "error", "-i", str(burned),
             "-ss", f"{i * 2 + 1}", "-frames:v", "1", str(frame)],
            check=True, capture_output=True,
        )
        frames.append(f"/media/frames/{run_id}/{frame.name}")
    return {
        "direction": gen.data["direction"],
        "font_dir": style.get("fonts_dir"),
        "frames": frames,
    }


# ---- projects / Backlot / tests --------------------------------------------

def _projects() -> list[dict]:
    from backlot.state import list_projects

    keep = ("project_id", "title", "pipeline_type", "live", "last_activity",
            "active_stage", "awaiting_human", "completed_count", "render_count", "scene_count")
    return [{k: p.get(k) for k in keep} for p in list_projects()]


def _backlot_alive(port: int) -> bool:
    # Never through HTTP(S)_PROXY: a stalled VPN client would make a running
    # board look dead.
    opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
    try:
        with opener.open(f"http://127.0.0.1:{port}/api/health", timeout=1.5) as resp:
            return resp.status == 200
    except OSError:
        return False


def _open_backlot(project_id: Optional[str]) -> dict:
    if project_id and (any(c in project_id for c in "/\\:") or project_id in (".", "..")):
        raise HTTPException(status_code=400, detail="invalid project id")
    from backlot import DEFAULT_PORT

    port = int(os.environ.get("BACKLOT_PORT", DEFAULT_PORT))
    if not _backlot_alive(port):
        # Start only the server: the page opens the URL itself, and
        # `backlot open` would open a second tab.
        flags = 0
        if os.name == "nt":
            flags = subprocess.CREATE_NEW_PROCESS_GROUP | subprocess.DETACHED_PROCESS
        try:
            subprocess.Popen(
                [sys.executable, "-m", "backlot", "serve", "--port", str(port)],
                cwd=REPO_ROOT, stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL, creationflags=flags, start_new_session=os.name != "nt",
            )
        except OSError as exc:
            raise HTTPException(status_code=502, detail=f"could not start Backlot: {exc}")
        deadline = time.time() + 15
        while not _backlot_alive(port):
            if time.time() > deadline:
                raise HTTPException(
                    status_code=502, detail=f"Backlot did not answer on port {port} within 15 s"
                )
            time.sleep(0.4)
    url = f"http://127.0.0.1:{port}/"
    return {"url": f"{url}p/{project_id}" if project_id else url}


def _run_tests() -> dict:
    if not _tests_lock.acquire(blocking=False):
        raise HTTPException(status_code=409, detail="tests are already running")
    try:
        run = subprocess.run(
            [sys.executable, "-m", "pytest", *PERSIAN_TESTS, "-q", "-p", "no:warnings", "--color=no"],
            cwd=REPO_ROOT, capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=600,
        )
    finally:
        _tests_lock.release()
    lines = [line for line in run.stdout.splitlines() if line.strip()]
    return {
        "ok": run.returncode == 0,
        "summary": lines[-1] if lines else "no output",
        "output": "\n".join(lines[-60:]) + ("\n" + run.stderr[-2000:] if run.stderr.strip() else ""),
    }


# ---- app -------------------------------------------------------------------

class EnvUpdate(BaseModel):
    name: str
    value: str = Field(default="", max_length=500)


class BacklotOpen(BaseModel):
    project_id: Optional[str] = None


def create_app() -> FastAPI:
    import tools.base_tool  # noqa: F401  (loads .env into os.environ)

    app = FastAPI(title="Studio FA", docs_url=None, redoc_url=None)
    panel = [Depends(_require_panel)]

    @app.get("/api/health")
    async def health() -> dict:
        return {"ok": True, "app": "studio_fa"}

    @app.get("/api/status")
    async def status() -> dict:
        return await asyncio.to_thread(_status)

    @app.post("/api/env", dependencies=panel)
    async def set_env(update: EnvUpdate) -> dict:
        if update.name not in EDITABLE_ENV:
            raise HTTPException(status_code=400, detail=f"{update.name} is not editable here")
        value = update.value.strip()
        if any(c in value for c in "\r\n"):
            raise HTTPException(status_code=400, detail="value must be one line")
        await asyncio.to_thread(_write_env, update.name, value)
        return await asyncio.to_thread(_status)

    @app.get("/api/voices")
    async def voices() -> dict:
        return await asyncio.to_thread(_voices)

    @app.post("/api/tts", dependencies=panel)
    async def tts(req: TTSRequest) -> dict:
        return await asyncio.to_thread(_synthesize, req)

    @app.get("/api/tts/history")
    async def tts_history() -> list:
        return await asyncio.to_thread(_read_history)

    @app.post("/api/subtitles/preview", dependencies=panel)
    async def subtitle_preview(req: SubtitleRequest) -> dict:
        return await asyncio.to_thread(_subtitle_frames, req)

    @app.get("/api/projects")
    async def projects() -> list:
        return await asyncio.to_thread(_projects)

    @app.post("/api/backlot/open", dependencies=panel)
    async def backlot_open(req: BacklotOpen) -> dict:
        return await asyncio.to_thread(_open_backlot, req.project_id)

    @app.post("/api/tests/run", dependencies=panel)
    async def tests_run() -> dict:
        return await asyncio.to_thread(_run_tests)

    from studio_fa.production import build_router, install_error_handler

    app.include_router(build_router(panel))
    install_error_handler(app)

    @app.get("/media/{kind}/{file_path:path}")
    async def media(kind: str, file_path: str) -> FileResponse:
        if kind not in ("tts", "frames"):
            raise HTTPException(status_code=404)
        root = (STATE_DIR / kind).resolve()
        target = (root / file_path).resolve()
        if not target.is_relative_to(root) or not target.is_file():
            raise HTTPException(status_code=404)
        return FileResponse(target)

    @app.get("/fonts/{name}")
    async def font(name: str) -> FileResponse:
        folder = find_vazirmatn()
        if not folder or not re.fullmatch(r"Vazirmatn-[A-Za-z]+\.ttf", name) or not (folder / name).is_file():
            raise HTTPException(status_code=404)
        return FileResponse(folder / name, media_type="font/ttf")

    @app.get("/")
    async def index() -> HTMLResponse:
        html = (UI_DIR / "index.html").read_text(encoding="utf-8")
        for asset in ("app.css", "app.js", "production.js"):
            version = int((UI_DIR / asset).stat().st_mtime)
            html = html.replace(f"/ui/{asset}", f"/ui/{asset}?v={version}")
        return HTMLResponse(html, headers={"Cache-Control": "no-cache"})

    app.mount("/ui", StaticFiles(directory=UI_DIR), name="ui")
    # Loopback binding alone does not stop DNS-rebinding requests.
    app.add_middleware(
        TrustedHostMiddleware, allowed_hosts=["127.0.0.1", "localhost"], www_redirect=False,
    )
    return app


app = create_app()
