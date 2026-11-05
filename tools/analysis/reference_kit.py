"""Link (or file) -> remake kit for a Persian version.

One call turns a YouTube video (Shorts or long), an Instagram reel, a TikTok
or any yt-dlp URL into everything the agent needs to plan a Persian remake:

    projects/_reference/<slug>/
      source.mp4            the video (<= 720p), verified against its length
      transcript.json       segments [{start, end, text}] in the source language
      outline.json          section outline of the whole video (bulk tier)
      style/                edit_style_extractor output; card in styles/editing/learned/
      gemini_analysis.json  story beats, hook, visual style (first 8 min of long videos)
      transcript_fa_draft.txt  worker-tier translation draft (raw material only)
      claims.json           checkable claims to verify before any script
      remake_brief.json     facts + structure + recommendation + cost estimate
      REMAKE_fa.md          Persian summary for the owner

Free first: captions from the platform before paid speech-to-text; scene
detection and frame differences before vision. Paid steps are estimated
first and skipped (reported) when the estimate is over `budget_usd`.

Network from Iran: every call tries direct once and the local proxy once,
with timeouts; a download whose length does not match the metadata is
retried once with resume (truncated downloads happen silently here).
Instagram needs a logged-in session: pass `cookies_file` (exported by the
owner) or download the reel yourself and pass `input_path`.

Modes: `transcreate` (default) keeps structure, pacing and hook technique but
nothing of the source's footage, audio or wording. `dub` keeps the video and
replaces the voice; it needs rights (`rights`: own / licensed / permission)
and hands over to scripts/fa_dub.py.
"""

from __future__ import annotations

import contextlib
import datetime
import json
import os
import re
import shutil
import subprocess
import time
from pathlib import Path
from typing import Any, Callable, Optional

from tools.base_tool import (
    BaseTool,
    Determinism,
    ExecutionMode,
    ResourceProfile,
    ToolResult,
    ToolRuntime,
    ToolStability,
    ToolStatus,
    ToolTier,
)

REPO_ROOT = Path(__file__).resolve().parents[2]
PROXY = os.environ.get("OPENMONTAGE_LOCAL_PROXY", "http://127.0.0.1:10808")
MAX_SECONDS = 3 * 3600
GEMINI_WINDOW = 480  # long videos: Gemini watches the first 8 minutes
SHORT_SECONDS = 180
RIGHTS_OK = {"own", "licensed", "permission"}
STT_MODEL = "whisper-1"  # segment timestamps through AvalAI
STT_PRICE = 0.0001       # USD / second (tools/analysis/avalai_stt.py)
VISION_PER_FRAME = 0.00036  # measured 2026-11-04 (40 frames, $0.0143)
GEMINI_PER_SECOND = 0.00011  # AvalAI, measured 2026-11-05: 39 s $0.0084, 480 s $0.0562


# -- URLs -----------------------------------------------------------------------

def classify_url(url: str) -> dict[str, Optional[str]]:
    """{platform, kind, id}; kind is short / long / reel / post / video / unknown."""
    u = url.strip()
    m = re.search(r"youtube\.com/shorts/([\w-]{6,})", u)
    if m:
        return {"platform": "youtube", "kind": "short", "id": m.group(1)}
    m = re.search(r"(?:youtube\.com/(?:watch\?(?:.*&)?v=|live/|embed/)|youtu\.be/)([\w-]{6,})", u)
    if m:
        return {"platform": "youtube", "kind": "long", "id": m.group(1)}
    m = re.search(r"instagram\.com/(?:[\w.]+/)?(reels?|p|tv)/([\w-]+)", u)
    if m:
        return {"platform": "instagram", "kind": "reel" if m.group(1).startswith("reel") else "post",
                "id": m.group(2)}
    m = re.search(r"tiktok\.com/.*/video/(\d+)", u)
    if m:
        return {"platform": "tiktok", "kind": "short", "id": m.group(1)}
    if re.search(r"(?:twitter|x)\.com/.+/status/(\d+)", u):
        return {"platform": "x", "kind": "video", "id": re.search(r"/status/(\d+)", u).group(1)}
    return {"platform": "other", "kind": "unknown", "id": None}


def slugify(text: str, fallback: str = "reference") -> str:
    s = re.sub(r"[^a-z0-9]+", "-", text.lower()).strip("-")
    return (s[:48].strip("-") or fallback)


# -- transcript helpers (pure) ---------------------------------------------------

_TS = re.compile(r"(\d+):(\d{2}):(\d{2})[.,](\d{3})|(\d{2}):(\d{2})[.,](\d{3})")


def _ts(text: str) -> float:
    m = _TS.search(text)
    if not m:
        raise ValueError(text)
    if m.group(1):
        h, mi, s, ms = (int(x) for x in m.group(1, 2, 3, 4))
    else:
        h, (mi, s, ms) = 0, (int(x) for x in m.group(5, 6, 7))
    return h * 3600 + mi * 60 + s + ms / 1000


def parse_vtt(text: str) -> list[dict[str, Any]]:
    """WebVTT -> segments. YouTube auto-captions repeat the previous line in each
    cue (rolling captions); keep only the new words."""
    segs: list[dict[str, Any]] = []
    for block in re.split(r"\n\s*\n", text.replace("\r\n", "\n")):
        lines = [l for l in block.strip().split("\n") if l.strip()]
        timing = next((l for l in lines if "-->" in l), None)
        if not timing:
            continue
        a, b = timing.split("-->")
        body = " ".join(re.sub(r"<[^>]+>", "", l).strip() for l in lines[lines.index(timing) + 1:])
        body = re.sub(r"\s+", " ", body).strip()
        if not body:
            continue
        prev = segs[-1]["text"] if segs else ""
        if prev and body.startswith(prev):
            body = body[len(prev):].strip()
        elif prev and prev in body:
            body = body.split(prev, 1)[1].strip()
        if not body or (segs and body == segs[-1]["text"]):
            continue
        segs.append({"start": round(_ts(a), 3), "end": round(_ts(b), 3), "text": body})
    return segs


def chunk_transcript(segs: list[dict[str, Any]], seconds: float = 90.0) -> list[dict[str, Any]]:
    chunks: list[dict[str, Any]] = []
    for s in segs:
        if not chunks or s["start"] - chunks[-1]["start"] >= seconds:
            chunks.append({"start": s["start"], "end": s["end"], "text": s["text"]})
        else:
            chunks[-1]["end"] = s["end"]
            chunks[-1]["text"] += " " + s["text"]
    return chunks


def words_per_minute(segs: list[dict[str, Any]]) -> Optional[float]:
    if not segs:
        return None
    words = sum(len(s["text"].split()) for s in segs)
    span = segs[-1]["end"] - segs[0]["start"]
    return round(words / (span / 60), 1) if span > 0 else None


def mmss(seconds: float) -> str:
    seconds = int(round(seconds))
    return f"{seconds // 60:02d}:{seconds % 60:02d}"


# -- the tool --------------------------------------------------------------------

class ReferenceKit(BaseTool):
    name = "reference_kit"
    version = "0.1.0"
    tier = ToolTier.SOURCE
    capability = "source_ingest"
    provider = "openmontage"
    stability = ToolStability.EXPERIMENTAL
    execution_mode = ExecutionMode.SYNC
    determinism = Determinism.STOCHASTIC
    runtime = ToolRuntime.HYBRID

    dependencies = ["cmd:ffmpeg", "python:yt_dlp"]
    install_instructions = "pip install yt-dlp; FFmpeg on PATH. AVALAI_API_KEY for paid steps."
    agent_skills = ["video-download", "video-understand"]
    capabilities = ["link_ingest", "remake_kit"]
    best_for = ["'make a Persian version of this video' from a YouTube/Instagram/TikTok link"]
    resource_profile = ResourceProfile(cpu_cores=2, ram_mb=1024, disk_mb=3000, network_required=True)

    input_schema = {
        "type": "object",
        "properties": {
            "url": {"type": "string"},
            "input_path": {"type": "string", "description": "a local video instead of a URL"},
            "slug": {"type": "string"},
            "mode": {"type": "string", "enum": ["transcreate", "dub"], "default": "transcreate"},
            "rights": {"type": "string", "enum": ["unknown", "own", "licensed", "permission"],
                       "default": "unknown"},
            "target_seconds": {"type": "number", "description": "Persian version length (default: same)"},
            "budget_usd": {"type": "number", "default": 0.10,
                           "description": "paid analysis steps above this estimate are skipped"},
            "cookies_file": {"type": "string", "description": "Netscape cookies.txt (Instagram)"},
            "language": {"type": "string", "description": "source language (default: from metadata, else en)"},
            "steps": {"type": "array", "items": {"type": "string"},
                      "description": "subset of: style, gemini, outline, translate, claims"},
            "out_root": {"type": "string"},
        },
    }
    side_effects = ["downloads the video", "paid analysis calls within budget_usd",
                    "writes projects/_reference/<slug>/ and a learned edit style card"]

    ALL_STEPS = ("style", "gemini", "outline", "translate", "claims")

    def __init__(self, llm=None, runner: Optional[Callable[..., Any]] = None):
        self._llm = llm
        self._runner = runner  # tests replace yt-dlp/ffmpeg/tool calls
        self._route = "direct"
        self._direct_ok = True

    def get_status(self) -> ToolStatus:
        try:
            import yt_dlp  # noqa: F401
        except ImportError:
            return ToolStatus.UNAVAILABLE
        return ToolStatus.AVAILABLE if shutil.which("ffmpeg") else ToolStatus.UNAVAILABLE

    @property
    def llm(self):
        if self._llm is None:
            from tools.text.llm_selector import LLMSelector
            self._llm = LLMSelector()
        return self._llm

    # -- network (direct once, proxy once) ------------------------------------

    def _ydl_opts(self, proxy: Optional[str], cookies: Optional[str], **extra) -> dict[str, Any]:
        opts = {"quiet": True, "no_warnings": True, "socket_timeout": 30, "retries": 3,
                "fragment_retries": 3, "continuedl": True, "noprogress": True}
        if proxy:
            opts["proxy"] = proxy
        if cookies:
            opts["cookiefile"] = cookies
        opts.update(extra)
        return opts

    def _with_routes(self, fn: Callable[[Optional[str]], Any]) -> tuple[Any, str, list[str]]:
        # The route that worked last goes first: when YouTube is blocked on
        # the direct route, each later step would otherwise wait out its
        # retries there again.
        errors = []
        if not self._direct_ok:
            routes: tuple[Optional[str], ...] = (PROXY,)
        else:
            routes = (PROXY, None) if self._route == "proxy" else (None, PROXY)
        for proxy in routes:
            try:
                result = fn(proxy)
            except Exception as exc:  # one try per route; no loops
                errors.append(f"{'proxy' if proxy else 'direct'}: {short(exc)}")
                continue
            self._route = "proxy" if proxy else "direct"
            return result, self._route, errors
        raise RuntimeError("; ".join(errors))

    def direct_reachable(self, url: str) -> bool:
        """One quick request on the direct route (environment proxies apply,
        as they do for yt-dlp). Any HTTP answer counts; a refused or silent
        connection does not. Studio FA runs without HTTPS_PROXY, and there
        YouTube refuses the direct route: yt-dlp needs ~3 min to give up."""
        import requests

        host = re.match(r"https?://([^/?#]+)", url)
        if not host:
            return True
        try:
            requests.head(f"https://{host.group(1)}/", timeout=6, allow_redirects=False)
            return True
        except Exception:
            return False

    def metadata(self, url: str, cookies: Optional[str]) -> tuple[dict[str, Any], str]:
        import yt_dlp

        def get(proxy):
            with yt_dlp.YoutubeDL(self._ydl_opts(proxy, cookies, skip_download=True)) as y:
                return y.extract_info(url, download=False)

        info, route, _ = self._with_routes(get)
        keep = ("id", "title", "uploader", "channel", "duration", "width", "height", "view_count",
                "like_count", "upload_date", "description", "language", "webpage_url", "chapters", "tags")
        meta = {k: info.get(k) for k in keep}
        meta["has_subtitles"] = sorted((info.get("subtitles") or {}).keys())
        meta["has_auto_captions"] = sorted((info.get("automatic_captions") or {}).keys())[:50]
        return meta, route

    def download(self, url: str, folder: Path, cookies: Optional[str], expected: Optional[float]) -> tuple[Path, str]:
        import yt_dlp

        target = folder / "source.mp4"
        fmt = ("bv*[height<=720][ext=mp4]+ba[ext=m4a]/bv*[height<=720]+ba/"
               "b[height<=720]/bv*[width<=720]+ba/b")

        def get(proxy):
            opts = self._ydl_opts(proxy, cookies, format=fmt, merge_output_format="mp4",
                                  outtmpl=str(folder / "source.%(ext)s"))
            with yt_dlp.YoutubeDL(opts) as y:
                y.download([url])
            got = next((p for p in folder.glob("source.*") if p.suffix in (".mp4", ".mkv", ".webm")), None)
            if got is None:
                raise RuntimeError("no video file after download")
            if got != target:
                got.replace(target)
            length = probe_seconds(target)
            if expected and length < 0.97 * expected:
                raise RuntimeError(f"truncated download: {length:.1f} s of {expected:.1f} s")
            return target

        path, route, _ = self._with_routes(get)
        return path, route

    def captions(self, url: str, folder: Path, cookies: Optional[str], meta: dict, lang: str) -> list[dict]:
        """Platform captions, manual before automatic; [] when there are none."""
        import yt_dlp

        manual = [l for l in meta.get("has_subtitles", []) if l.split("-")[0] == lang]
        auto = [l for l in meta.get("has_auto_captions", []) if l == lang or l == f"{lang}-orig"]
        if not manual and not auto:
            return []

        def get(proxy):
            opts = self._ydl_opts(proxy, cookies, skip_download=True, writesubtitles=bool(manual),
                                  writeautomaticsub=not manual, subtitleslangs=(manual or auto)[:1],
                                  subtitlesformat="vtt", outtmpl=str(folder / "captions.%(ext)s"))
            with yt_dlp.YoutubeDL(opts) as y:
                y.download([url])
            vtt = next(folder.glob("captions*.vtt"), None)
            if vtt is None:
                raise RuntimeError("no caption file")
            return parse_vtt(vtt.read_text(encoding="utf-8"))

        segs, _, _ = self._with_routes(get)
        return segs

    def transcribe(self, video: Path, folder: Path, language: Optional[str] = None) -> tuple[list[dict], float]:
        from tools.analysis.avalai_stt import AvalAISTT

        audio = folder / "audio_16k.mp3"
        subprocess.run([ffmpeg(), "-v", "error", "-y", "-i", str(video), "-vn", "-ac", "1", "-ar", "16000",
                        "-b:a", "32k", str(audio)], check=True, timeout=1800)
        # avalai_stt defaults to Persian (it checks our own TTS); give it the
        # source language, or "" to let the model detect it.
        request = {"audio_path": str(audio), "model": STT_MODEL, "timestamps": True, "language": language or ""}
        r = AvalAISTT().execute(request)
        if not r.success and re.search(r"Timeout|ConnectionError|SSLError", r.error or ""):
            r = AvalAISTT().execute(request)  # one retry: broken connections are common here
        if not r.success:
            raise RuntimeError(f"speech-to-text failed: {r.error}")
        segs = [{"start": round(float(s["start"]), 3), "end": round(float(s["end"]), 3), "text": s["text"].strip()}
                for s in (r.data.get("segments") or []) if s.get("text", "").strip()]
        return segs, r.cost_usd or 0.0

    # -- plan and costs ----------------------------------------------------------

    def plan_costs(self, duration: float, has_captions: bool, steps: tuple[str, ...]) -> dict[str, float]:
        frames = min(40, max(8, int(duration / 4)))
        gem_seconds = min(duration, GEMINI_WINDOW)
        words = duration / 60 * 160
        costs = {
            "transcript": 0.0 if has_captions else round(duration * STT_PRICE, 4),
            "style": round(frames * VISION_PER_FRAME + 0.0005, 4) if "style" in steps else 0.0,
            "gemini": round(gem_seconds * GEMINI_PER_SECOND + 0.004, 4) if "gemini" in steps else 0.0,
            "outline": round(words * 1.5 * 0.25 / 1e6 + 0.0005, 4) if "outline" in steps else 0.0,
            "translate": round(words * 1.5 * (0.15 + 0.6 * 2) / 1e6, 4) if "translate" in steps else 0.0,
            "claims": round(words * 1.5 * 0.25 / 1e6 + 0.0005, 4) if "claims" in steps else 0.0,
        }
        costs["total"] = round(sum(costs.values()), 4)
        return costs

    # -- steps ------------------------------------------------------------------

    def _gemini(self, video: Path, duration: float, out: Path) -> tuple[Optional[dict], float, Optional[str]]:
        from tools.analysis.gemini_video_analyze import GeminiVideoAnalyze

        inputs = {"source": str(video), "route": "auto", "fallback_local": False,
                  "duration_hint_seconds": min(duration, GEMINI_WINDOW), "output_path": str(out)}
        if duration > GEMINI_WINDOW:
            inputs.update({"start_offset": 0, "end_offset": GEMINI_WINDOW})
        r = GeminiVideoAnalyze().execute(inputs)
        if not r.success:
            return None, r.cost_usd or 0.0, short(r.error)
        data = r.data.get("analysis") or r.data
        return data, r.cost_usd or 0.0, None

    def _outline(self, segs: list[dict]) -> tuple[list[dict], float, Optional[str]]:
        chunks = chunk_transcript(segs, 90.0)
        items = [{"id": str(i), "task": "transcript_chunk_summary", "temperature": 0, "max_tokens": 200,
                  "prompt": ("Summarise this part of a video narration in one or two English sentences: "
                             "what it covers and how it keeps attention (question, twist, number...).\n\n"
                             + c["text"][:6000])} for i, c in enumerate(chunks)]
        r = self.llm.execute({"operation": "batch", "items": items})
        results = r.data.get("results") or {}
        out = [{"start": mmss(c["start"]), "end": mmss(c["end"]),
                "summary": ((results.get(str(i)) or {}).get("text") or "").strip()}
               for i, c in enumerate(chunks)]
        return out, r.cost_usd or 0.0, r.error

    def _translate(self, segs: list[dict], lang: str) -> tuple[str, float, Optional[str]]:
        text = "\n".join(s["text"] for s in segs)
        parts = [text[i:i + 6000] for i in range(0, len(text), 6000)] or [""]
        items = [{"id": str(i), "task": "translation_draft_en_fa", "temperature": 0.3, "max_tokens": 3000,
                  "prompt": (f"Translate this {lang} video narration into natural colloquial Persian. "
                             "Keep facts and numbers exact; no preamble, output only the translation.\n\n" + p)}
                 for i, p in enumerate(parts)]
        r = self.llm.execute({"operation": "batch", "items": items})
        res = r.data.get("results") or {}
        fa = "\n".join(((res.get(str(i)) or {}).get("text") or "").strip() for i in range(len(parts)))
        return fa, r.cost_usd or 0.0, r.error

    def _claims(self, segs: list[dict]) -> tuple[list[dict], float, Optional[str]]:
        text = " ".join(s["text"] for s in segs)[:12000]
        schema = {"type": "object", "required": ["claims"], "properties": {"claims": {"type": "array", "items": {
            "type": "object", "required": ["claim", "kind"],
            "properties": {"claim": {"type": "string"},
                           "kind": {"type": "string", "enum": ["date", "number", "name", "event", "quote", "other"]}}}}}}
        r = self.llm.execute({"task": "claim_extraction", "json_schema": schema, "temperature": 0,
                              "prompt": "List every checkable factual claim in this narration (dates, numbers, "
                                        "names, events, quotes), one short item each. Return JSON "
                                        '{"claims": [{"claim": "...", "kind": "date"}]}\n\n' + text})
        claims = ((r.data or {}).get("json") or {}).get("claims", [])
        return [{**c, "verdict": "unverified", "source": None} for c in claims], r.cost_usd or 0.0, \
            None if r.success else r.error

    def _style(self, video: Path, slug: str, folder: Path, transcript: Path, duration: float):
        from tools.analysis.edit_style_extractor import EditStyleExtractor

        r = EditStyleExtractor(llm_selector=self._llm).execute({
            "input_path": str(video), "name": f"{slug}-learned", "work_dir": str(folder / "style"),
            "transcript_path": str(transcript) if transcript.exists() else None,
            "max_frames": min(40, max(8, int(duration / 4))), "draft_hook": True,
            "title": f"Learned from {slug}"})
        return (r.data if r.success else None), r.cost_usd or 0.0, None if r.success else short(r.error)

    # -- execute -------------------------------------------------------------------

    def execute(self, inputs: dict[str, Any]) -> ToolResult:
        # AvalAI answers direct from Iran and breaks through the VPN proxy
        # (config/llm_routing.yaml, profile avalai). The STT and Gemini tools
        # use plain requests, which read HTTPS_PROXY; keep Google on the proxy.
        with avalai_direct():
            return self._execute(inputs)

    def _execute(self, inputs: dict[str, Any]) -> ToolResult:
        started = time.time()
        url = (inputs.get("url") or "").strip()
        local = inputs.get("input_path")
        if not url and not local:
            return ToolResult(success=False, error="url or input_path is required")
        mode = inputs.get("mode", "transcreate")
        rights = inputs.get("rights", "unknown")
        if mode == "dub" and rights not in RIGHTS_OK:
            return ToolResult(success=False, data={"needs": "rights"},
                              error="dub mode needs rights: own, licensed or permission. "
                                    "For someone else's video use mode=transcreate.")
        cookies = inputs.get("cookies_file") or os.environ.get("OPENMONTAGE_COOKIES_FILE") or None
        steps = tuple(inputs.get("steps") or self.ALL_STEPS)
        budget = float(inputs.get("budget_usd", 0.10))
        info = classify_url(url) if url else {"platform": "local", "kind": "video", "id": None}
        notes: list[str] = []
        spent = 0.0
        actual: dict[str, float] = {}
        timings: dict[str, float] = {}
        mark = time.time()

        def tick(name: str) -> None:
            nonlocal mark
            now = time.time()
            timings[name] = round(now - mark, 1)
            mark = now

        if url:
            self._direct_ok = self.direct_reachable(url)
            if not self._direct_ok:
                notes.append("direct route does not reach the site; proxy only")
        try:
            meta, route = (self.metadata(url, cookies) if url else ({"title": Path(local).stem}, "local"))
        except Exception as exc:
            hint = ""
            if info["platform"] == "instagram":
                hint = (" Instagram needs a logged-in session: export cookies.txt from your browser and "
                        "pass cookies_file, or download the reel and pass input_path.")
            return ToolResult(success=False, data={"platform": info["platform"], "needs": "access"},
                              error=f"could not read the link ({short(exc)}).{hint}")
        tick("metadata")
        duration = float(meta.get("duration") or 0)
        if duration > MAX_SECONDS:
            return ToolResult(success=False, error=f"video is {duration / 60:.0f} min; the limit is 3 h")
        slug = inputs.get("slug") or slugify(meta.get("title") or info.get("id") or "reference")
        root = Path(inputs.get("out_root") or REPO_ROOT / "projects" / "_reference")
        folder = root / slug
        folder.mkdir(parents=True, exist_ok=True)

        if url:
            try:
                video, dl_route = self.download(url, folder, cookies, duration or None)
            except Exception as exc:
                return ToolResult(success=False, data={"metadata": meta, "folder": str(folder)},
                                  error=f"download failed ({short(exc)})")
            notes.append(f"downloaded via {dl_route}")
            tick("download")
        else:
            video = Path(local)
        duration = probe_seconds(video) or duration
        width, height = probe_size(video)
        vertical = bool(height and width and height > width)
        kind = info["kind"]
        if info["platform"] == "youtube" and kind == "long" and duration <= SHORT_SECONDS and vertical:
            kind = "short"
        known_lang = inputs.get("language") or meta.get("language")
        lang = (known_lang or "en").split("-")[0]

        # Transcript: platform captions first (free), then speech-to-text (paid, cents).
        segs: list[dict] = []
        if url:
            try:
                segs = self.captions(url, folder, cookies, meta, lang)
                if segs:
                    notes.append("transcript from platform captions (free)")
            except Exception as exc:
                notes.append(f"captions unavailable ({short(exc)})")
        tick("captions")
        costs = self.plan_costs(duration, bool(segs), steps)
        if not segs:
            if costs["transcript"] <= budget:
                try:
                    segs, c = self.transcribe(video, folder, known_lang.split("-")[0] if known_lang else None)
                    spent += c
                    actual["transcript"] = round(c, 4)
                    notes.append(f"transcript from AvalAI {STT_MODEL} (${c:.4f})")
                except Exception as exc:
                    notes.append(f"no transcript: {short(exc)}")
            else:
                notes.append(f"no transcript: speech-to-text would cost ${costs['transcript']} (budget ${budget})")
        tick("transcript")
        transcript_path = folder / "transcript.json"
        transcript_path.write_text(json.dumps({"language": lang, "segments": segs}, ensure_ascii=False, indent=1),
                                   encoding="utf-8")

        results: dict[str, Any] = {}
        order = [s for s in ("style", "gemini", "outline", "claims", "translate") if s in steps]
        for step in order:
            need_text = step in ("outline", "claims", "translate")
            if need_text and not segs:
                notes.append(f"{step}: skipped (no transcript)")
                continue
            if spent + costs[step] > budget:
                notes.append(f"{step}: skipped, estimate ${costs[step]} would pass the budget "
                             f"(${spent:.4f} spent of ${budget})")
                continue
            try:
                if step == "style":
                    data, c, err = self._style(video, slug, folder, transcript_path, duration)
                elif step == "gemini":
                    data, c, err = self._gemini(video, duration, folder / "gemini_analysis.json")
                elif step == "outline":
                    data, c, err = self._outline(segs)
                elif step == "claims":
                    data, c, err = self._claims(segs)
                else:
                    data, c, err = self._translate(segs, lang)
            except Exception as exc:
                data, c, err = None, 0.0, short(exc)
            spent += c
            actual[step] = round(c, 4)
            tick(step)
            results[step] = data
            if err:
                notes.append(f"{step}: {err}")

        if results.get("outline"):
            (folder / "outline.json").write_text(json.dumps(results["outline"], ensure_ascii=False, indent=1),
                                                 encoding="utf-8")
        if results.get("claims") is not None and "claims" in results:
            (folder / "claims.json").write_text(json.dumps({"status": "to_verify", "claims": results["claims"]},
                                                           ensure_ascii=False, indent=1), encoding="utf-8")
        if results.get("translate"):
            (folder / "transcript_fa_draft.txt").write_text(
                "# Worker-tier draft. Raw material for the agent; never the final Persian text.\n\n"
                + results["translate"], encoding="utf-8")

        brief = build_brief(url or str(video), info["platform"], kind, meta, duration, vertical, lang, segs,
                            results, mode, rights, inputs.get("target_seconds"), slug)
        brief["cost"] = {"spent_usd": round(spent, 4), "plan": costs, "actual": actual, "budget_usd": budget}
        brief["notes"] = notes
        brief["timings_seconds"] = timings
        (folder / "remake_brief.json").write_text(json.dumps(brief, ensure_ascii=False, indent=1), encoding="utf-8")
        (folder / "REMAKE_fa.md").write_text(persian_summary(brief), encoding="utf-8")
        return ToolResult(
            success=True,
            data={"folder": str(folder), "brief": brief, "seconds": round(time.time() - started, 1)},
            artifacts=[str(folder / "remake_brief.json"), str(folder / "REMAKE_fa.md")],
            cost_usd=round(spent, 6),
        )


# -- brief + summary ----------------------------------------------------------------

def build_brief(source: str, platform: str, kind: str, meta: dict, duration: float, vertical: bool,
                lang: str, segs: list[dict], results: dict, mode: str, rights: str,
                target: Optional[float], slug: str) -> dict[str, Any]:
    style = results.get("style") or {}
    gem = results.get("gemini") or {}
    target = float(target or round(duration))
    if mode == "dub":
        pipeline = "localization-dub (scripts/fa_dub.py)"
    elif any(w in (gem.get("visual_style") or {}).get("medium", "").lower()
             for w in ("live", "footage", "talking", "vlog", "camera", "real")):
        pipeline = "animated-explainer with stills (live footage of the source is never reused)"
    else:
        pipeline = "animated-explainer"
    estimate = None
    try:
        from lib.fa_cost_estimate import estimate as fa_estimate, load_pricing, plan_from_brief

        pricing = load_pricing()
        plan = plan_from_brief({"target_duration_seconds": target}, pricing["assumptions"]["seconds_per_image"])
        estimate = {"draft_usd": fa_estimate(plan, pricing, "draft").total_usd,
                    "final_usd": fa_estimate(plan, pricing, "final", draft_rounds=1).total_usd}
    except Exception:
        pass
    return {
        "version": "1.0",
        "created_at": datetime.datetime.now(datetime.timezone.utc).isoformat(timespec="seconds"),
        "slug": slug,
        "source": {"url": source, "platform": platform, "kind": kind, "title": meta.get("title"),
                   "uploader": meta.get("uploader") or meta.get("channel"), "duration_seconds": round(duration, 1),
                   "views": meta.get("view_count"), "language": lang, "vertical": vertical,
                   "chapters": meta.get("chapters")},
        "mode": mode,
        "rights": {"status": rights,
                   "rule": ("dub: the source video is reused; rights confirmed as " + rights) if mode == "dub" else
                   "transcreate: reuse structure, pacing and hook technique only; never the source's footage, "
                   "audio, images or wording. New research with sources, own script, own visuals."},
        "format": {"aspect": "9:16" if vertical else "16:9", "target_seconds": target,
                   "profile": "youtube_shorts" if vertical else "youtube_landscape"},
        "transcript": {"segments": len(segs), "words_per_minute": words_per_minute(segs)},
        "hook": {"gemini": gem.get("hook"), "learned_beats": None},
        "story_beats": gem.get("story_beats"),
        "visual_style": gem.get("visual_style"),
        "pacing": {"asl_seconds": style.get("asl_seconds"), "shots": style.get("shots"),
                   "edit_style_card": Path(style["card_path"]).stem if style.get("card_path") else None},
        "outline": results.get("outline"),
        "claims_to_verify": len(results.get("claims") or []),
        "recommendation": {"pipeline": pipeline, "runtime": "hyperframes (atelier) — present both runtimes",
                           "edit_style_card": Path(style["card_path"]).stem if style.get("card_path") else
                           "full-history-in-n-minutes"},
        "estimate": estimate,
        "next_steps": [
            "agent: read REMAKE_fa.md, the outline and gemini_analysis.json; present 2-3 Persian concepts "
            "(skills/meta/remake-from-link.md)",
            "owner: pick a concept, voice and budget",
            "research with sources -> fact-check claims.json -> script -> fa_script_lint -> TTS -> stills -> render -> fa_render_qa",
        ] if mode == "transcreate" else [
            "python scripts/fa_dub.py prepare --project projects/<id> --source <kit>/source.mp4 --rights " + rights,
        ],
    }


FA_KIND = {"short": "شورتس/ویدیوی کوتاه عمودی", "long": "ویدیوی بلند", "reel": "ریلز اینستاگرام",
           "post": "پست ویدیویی اینستاگرام", "video": "ویدیو", "unknown": "ویدیو"}


def persian_summary(b: dict[str, Any]) -> str:
    s, f, p, c = b["source"], b["format"], b["pacing"], b["cost"]
    lines = [
        f"# کیت بازتولید: {s.get('title') or b['slug']}",
        "",
        f"- منبع: {s['platform']} — {FA_KIND.get(s['kind'], s['kind'])}، {s['duration_seconds'] / 60:.1f} دقیقه"
        + (f"، {s['views']:,} بازدید" if s.get("views") else "") + (f"، کانال {s['uploader']}" if s.get("uploader") else ""),
        f"- حالت: {'بازتولید با متن و تصویر خودمون' if b['mode'] == 'transcreate' else 'دوبله (حقوق: ' + b['rights']['status'] + ')'}",
        f"- قالب نسخه‌ی فارسی: {f['aspect']}، حدود {f['target_seconds']:.0f} ثانیه",
        f"- متن منبع: {b['transcript']['segments']} تکه" + (f"، {b['transcript']['words_per_minute']} کلمه در دقیقه"
                                                           if b["transcript"]["words_per_minute"] else ""),
    ]
    if p.get("asl_seconds"):
        lines.append(f"- ریتم تدوین: هر نما حدود {p['asl_seconds']} ثانیه ({p['shots']} نما)؛ کارت سبک: `{p['edit_style_card']}`")
    hook = (b.get("hook") or {}).get("gemini") or {}
    if hook:
        lines.append(f"- هوک منبع: {hook.get('technique', '')} — {hook.get('why_it_works', '')}")
    vs = b.get("visual_style") or {}
    if vs:
        lines.append(f"- سبک بصری منبع: {vs.get('medium', '')}؛ دوربین: {vs.get('camera', '')}")
    if b.get("outline"):
        lines += ["", "## ساختار منبع"] + [f"- {o['start']}–{o['end']}: {o['summary']}" for o in b["outline"][:20]]
    if b.get("claims_to_verify"):
        lines.append(f"\n- {b['claims_to_verify']} ادعای قابل‌بررسی پیدا شد (`claims.json`)؛ قبل از متن باید با منبع چک بشن.")
    if b.get("estimate"):
        lines.append(f"- تخمین هزینه‌ی نسخه‌ی فارسی: پیش‌نویس ${b['estimate']['draft_usd']:.2f}، نهایی ${b['estimate']['final_usd']:.2f}")
    lines += ["", f"هزینه‌ی همین تحلیل: ${c['spent_usd']:.4f} (سقف ${c['budget_usd']})",
              "", "## قانون", b["rights"]["rule"], "", "## قدم بعدی"] + [f"- {n}" for n in b["next_steps"]]
    if b.get("notes"):
        lines += ["", "## یادداشت‌ها"] + [f"- {n}" for n in b["notes"]]
    return "\n".join(lines) + "\n"


# -- small helpers --------------------------------------------------------------------

@contextlib.contextmanager
def avalai_direct():
    host = os.environ.get("AVALAI_BASE_URL", "https://api.avalai.ir").split("//")[-1].split("/")[0]
    before = os.environ.get("NO_PROXY")
    entries = [e for e in (before or "").split(",") if e.strip()]
    if host not in entries:
        os.environ["NO_PROXY"] = ",".join(entries + [host])
    try:
        yield
    finally:
        if before is None:
            os.environ.pop("NO_PROXY", None)
        else:
            os.environ["NO_PROXY"] = before


def ffmpeg() -> str:
    return shutil.which("ffmpeg") or "ffmpeg"


def probe_seconds(path: Path) -> float:
    out = subprocess.run([shutil.which("ffprobe") or "ffprobe", "-v", "error", "-show_entries",
                          "format=duration", "-of", "csv=p=0", str(path)],
                         capture_output=True, text=True, encoding="utf-8", timeout=60).stdout.strip()
    try:
        return float(out)
    except ValueError:
        return 0.0


def probe_size(path: Path) -> tuple[int, int]:
    out = subprocess.run([shutil.which("ffprobe") or "ffprobe", "-v", "error", "-select_streams", "v:0",
                          "-show_entries", "stream=width,height", "-of", "csv=p=0", str(path)],
                         capture_output=True, text=True, encoding="utf-8", timeout=60).stdout.strip()
    try:
        w, h = (int(x) for x in out.split(",")[:2])
        return w, h
    except ValueError:
        return 0, 0


def short(error: Any) -> str:
    from tools.provider_routing import short_error
    from tools.text.openai_compat_llm import redact

    text = re.sub(r"\x1b\[[0-9;]*m", "", str(error))
    return redact(short_error(text, 240))
