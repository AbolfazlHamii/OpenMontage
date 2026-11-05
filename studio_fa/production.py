"""Studio FA production pages: new-video wizard, stage timeline with
approve/reject, cost dashboard, provider health, style gallery + learning,
and LLM routing.

Read endpoints are open (loopback only); every endpoint that writes or may
spend money sits behind the panel header check. Keys never leave the server:
they are entered only through the existing /api/env, and every error passes
through `redact`.
"""

from __future__ import annotations

import asyncio
import datetime
import json
import re
import threading
import time
import uuid
from pathlib import Path
from typing import Any, Literal, Optional

import yaml
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field

REPO_ROOT = Path(__file__).resolve().parent.parent
PIPELINE = "animated-explainer"
SLUG = re.compile(r"^[a-z0-9][a-z0-9-]{2,60}$")
MODEL_ID = re.compile(r"^[A-Za-z0-9._:/-]{2,80}$")
PROTECTED_PROJECTS = {"samsung-history-fa"}  # waiting for the owner; the panel never writes there

WRAPPERS = {"image_selector", "tts_selector", "video_selector", "llm_selector", "fa_image"}

_jobs: dict[str, dict[str, Any]] = {}
_jobs_lock = threading.Lock()


# ---- errors in plain Persian -----------------------------------------------------

def fa_error(status: int, message: str, fix: str = "") -> HTTPException:
    from tools.text.openai_compat_llm import redact

    detail = redact(message) + (f" — راه‌حل: {redact(fix)}" if fix else "")
    return HTTPException(status_code=status, detail=detail)


def explain(error: Any) -> str:
    """Turn a provider error into one Persian sentence with a fix."""
    from tools.text.openai_compat_llm import redact

    text = redact(str(error))
    low = text.lower()
    if "403" in text or "permission" in low or "forbidden" in low:
        return "سرویس از این شبکه دسترسی نمی‌ده (۴۰۳). راه‌حل: VPN را عوض کنید یا مسیر AvalAI را انتخاب کنید."
    if "401" in text or "invalid key" in low or "api key" in low or "unauthorized" in low:
        return "کلید API قبول نشد. راه‌حل: کلید را در «کلیدها و تنظیمات» دوباره وارد کنید."
    if "not set" in low:
        return f"کلید این سرویس تنظیم نشده ({text}). راه‌حل: در «کلیدها و تنظیمات» واردش کنید."
    if "timeout" in low or "timed out" in low:
        return "سرویس جواب نداد (timeout). راه‌حل: چند دقیقه بعد دوباره امتحان کنید یا VPN را بررسی کنید."
    if "429" in text or "rate" in low:
        return "سقف درخواست سرویس پر شده. راه‌حل: کمی صبر کنید و دوباره امتحان کنید."
    return f"خطا: {text[:200]}"


def projects_dir() -> Path:
    from lib import paths

    return Path(paths.PROJECTS_DIR)


def _project(project_id: str) -> Path:
    if not SLUG.match(project_id):
        raise fa_error(400, "شناسه‌ی پروژه نامعتبر است.", "فقط حروف کوچک انگلیسی، عدد و خط تیره.")
    path = projects_dir() / project_id
    if not path.is_dir():
        raise fa_error(404, "پروژه پیدا نشد.")
    return path


def _read_json(path: Path, default: Any = None) -> Any:
    if not path.exists():
        return default
    return json.loads(path.read_text(encoding="utf-8"))


# ---- wizard ------------------------------------------------------------------------

class Wizard(BaseModel):
    project_id: str
    topic: str = Field(min_length=3, max_length=300)
    format: Literal["landscape", "vertical"] = "landscape"
    duration_seconds: int = Field(ge=15, le=1200)
    edit_style: str
    voice: str = Field(default="Kore", max_length=40)
    voice_style: str = Field(default="", max_length=300)
    budget_usd: float = Field(ge=0, le=50)
    draft_rounds: int = Field(default=1, ge=0, le=5)
    reference_kit: Optional[str] = Field(default=None, max_length=80)


def _estimate(w: Wizard) -> dict[str, Any]:
    from lib.fa_cost_estimate import estimate, load_pricing, plan_from_brief

    pricing = load_pricing()
    plan = plan_from_brief({"target_duration_seconds": w.duration_seconds},
                           pricing["assumptions"]["seconds_per_image"])
    draft = estimate(plan, pricing, "draft").to_dict()
    final = estimate(plan, pricing, "final", draft_rounds=w.draft_rounds).to_dict()
    return {"draft": draft, "final": final, "within_budget": final["total_usd"] <= w.budget_usd,
            "budget_usd": w.budget_usd, "prices_updated": str(pricing["updated"]),
            "warnings": final["warnings"]}


def _create(w: Wizard) -> dict[str, Any]:
    from lib.checkpoint import init_project
    from styles.edit_style_loader import load_edit_style

    if not SLUG.match(w.project_id):
        raise fa_error(400, "شناسه‌ی پروژه نامعتبر است.", "مثل samsung-history: حروف کوچک انگلیسی و خط تیره.")
    if w.project_id in PROTECTED_PROJECTS or (projects_dir() / w.project_id).exists():
        raise fa_error(409, "پروژه‌ای با این شناسه وجود دارد.", "یک شناسه‌ی دیگر انتخاب کنید.")
    try:
        card = load_edit_style(w.edit_style)
    except FileNotFoundError:
        raise fa_error(400, "کارت سبک تدوین پیدا نشد.", "یکی از کارت‌های گالری سبک را انتخاب کنید.")
    kit = None
    if w.reference_kit:
        if not SLUG.match(w.reference_kit) or not (projects_dir() / "_reference" / w.reference_kit
                                                   / "remake_brief.json").exists():
            raise fa_error(400, "کیت لینک پیدا نشد.", "اول «تحلیل لینک» را اجرا کنید.")
        kit = _read_json(projects_dir() / "_reference" / w.reference_kit / "remake_brief.json")
    est = _estimate(w)
    if not est["within_budget"]:
        raise fa_error(400, f"تخمین هزینه‌ی نهایی (${est['final']['total_usd']:.2f}) از بودجه بیشتر است.",
                       "بودجه را بالا ببرید، مدت را کوتاه کنید یا دورهای پیش‌نویس را کم کنید.")
    brief = {
        "version": "1.0",
        "title": w.topic,
        "hook": "(hook lab: scripts/fa_editorial.py hooks)",
        "key_points": [w.topic],
        "tone": "colloquial Persian, energetic, accurate",
        "style": f"edit style card: {card['name']}",
        "target_platform": "youtube",
        "target_duration_seconds": w.duration_seconds,
        "metadata": {
            "language": "fa", "format": w.format, "edit_style": card["name"],
            "voice": {"name": w.voice, "style": w.voice_style},
            "budget_usd": w.budget_usd, "draft_rounds": w.draft_rounds,
            "created_by": "studio_fa wizard", "created_at": datetime.datetime.now(datetime.timezone.utc).isoformat(),
        },
    }
    if kit:
        brief["reference_material"] = [{
            "type": "reference_video", "url": kit["source"]["url"], "title": kit["source"].get("title"),
            "kit": f"projects/_reference/{w.reference_kit}",
            "use": "structure, pacing and hook technique only" if kit["mode"] == "transcreate"
            else f"dub, rights: {kit['rights']['status']}",
        }]
        brief["metadata"]["remake"] = {"kit": w.reference_kit, "mode": kit["mode"],
                                       "rights": kit["rights"]["status"]}
    import jsonschema

    # Validate before creating anything, so a bad brief leaves no half-made project.
    jsonschema.validate(brief, json.loads((REPO_ROOT / "schemas/artifacts/brief.schema.json").read_text(encoding="utf-8")))
    project = init_project(w.project_id, title=w.topic, pipeline_type=PIPELINE, pipeline_dir=projects_dir())
    (project / "artifacts" / "brief.json").write_text(json.dumps(brief, ensure_ascii=False, indent=2), encoding="utf-8")
    (project / "artifacts" / "estimate.json").write_text(json.dumps(est, ensure_ascii=False, indent=2), encoding="utf-8")
    return {"project_id": w.project_id, "path": str(project), "estimate": est,
            "next": "در Claude Code بنویسید: «پروژه‌ی <id> را از مرحله‌ی research شروع کن».".replace("<id>", w.project_id)}


# ---- timeline -------------------------------------------------------------------------

def _timeline(project_id: str) -> dict[str, Any]:
    project = _project(project_id)
    meta = _read_json(project / "project.json", {})
    manifest = yaml.safe_load((REPO_ROOT / "pipeline_defs" / f"{meta.get('pipeline_type', PIPELINE)}.yaml")
                              .read_text(encoding="utf-8"))
    decisions = (_read_json(project / "decision_log.json", {}) or {}).get("decisions", [])
    stages = []
    for st in manifest["stages"]:
        cp = _read_json(project / f"checkpoint_{st['name']}.json")
        reviews = [d for d in decisions if d.get("subject") == f"Checkpoint review: {st['name']}"]
        stages.append({
            "name": st["name"], "gated": bool(st.get("human_approval_default")),
            "status": (cp or {}).get("status", "pending"),
            "timestamp": (cp or {}).get("timestamp"),
            "review": reviews[-1]["selected"] if reviews else None,
        })
    return {"project_id": project_id, "title": meta.get("title"), "pipeline": meta.get("pipeline_type"),
            "stages": stages, "protected": project_id in PROTECTED_PROJECTS}


class Review(BaseModel):
    stage: str = Field(max_length=40)
    action: Literal["approve", "reject"]
    note: str = Field(default="", max_length=1000)


def _review(project_id: str, r: Review) -> dict[str, Any]:
    from lib.fa_editorial import append_decision

    project = _project(project_id)
    if project_id in PROTECTED_PROJECTS:
        raise fa_error(403, "این پروژه قفل است و از پنل تغییر نمی‌کند.",
                       "تأیید یا رد را در گفت‌وگو با ایجنت بنویسید.")
    stages = [s["name"] for s in _timeline(project_id)["stages"]]
    if r.stage not in stages:
        raise fa_error(400, "مرحله‌ی نامعتبر.")
    entry = append_decision(project / "decision_log.json", {
        "stage": r.stage, "category": "approval_policy", "subject": f"Checkpoint review: {r.stage}",
        "options_considered": [
            {"option_id": "approve", "label": "تأیید", "score": 1.0 if r.action == "approve" else 0.0,
             "reason": "owner approves the checkpoint"},
            {"option_id": "reject", "label": "رد", "score": 1.0 if r.action == "reject" else 0.0,
             "reason": "owner asks for a revision"}],
        "selected": r.action,
        "reason": r.note or ("Owner approved in Studio FA" if r.action == "approve" else "Owner rejected in Studio FA"),
        "user_visible": True, "user_approved": r.action == "approve",
    }, project_id)
    return {"logged": entry["decision_id"], "timeline": _timeline(project_id)}


# ---- costs -------------------------------------------------------------------------------

def _costs() -> dict[str, Any]:
    projects, months, providers = [], {}, {}
    root = projects_dir()
    for project in sorted(p for p in root.iterdir() if p.is_dir() and not p.name.startswith("_")) if root.exists() else []:
        total, by_tool = 0.0, {}
        events = project / "events.jsonl"
        if events.exists():
            for line in events.read_text(encoding="utf-8").splitlines():
                try:
                    e = json.loads(line)
                except json.JSONDecodeError:
                    continue
                # Count each call once, at the provider: selectors and wrappers
                # re-report their child's cost.
                if e.get("event") != "finish" or not e.get("cost_usd") or e.get("tool") in WRAPPERS:
                    continue
                cost = float(e["cost_usd"])
                tool = e.get("tool", "?")
                total += cost
                by_tool[tool] = by_tool.get(tool, 0.0) + cost
                month = str(e.get("ts", ""))[:7]
                months[month] = months.get(month, 0.0) + cost
                providers[tool] = providers.get(tool, 0.0) + cost
        log = _read_json(project / "cost_log.json", {}) or {}
        for entry in log.get("entries", []):
            if entry.get("actual_usd"):
                cost = float(entry["actual_usd"])
                total += cost
                by_tool[entry.get("tool", "?")] = by_tool.get(entry.get("tool", "?"), 0.0) + cost
                month = str(entry.get("timestamp", ""))[:7]
                months[month] = months.get(month, 0.0) + cost
        projects.append({"project_id": project.name, "total_usd": round(total, 4),
                         "by_tool": {k: round(v, 4) for k, v in sorted(by_tool.items(), key=lambda kv: -kv[1])}})
    return {"projects": projects,
            "months": {k: round(v, 4) for k, v in sorted(months.items()) if k},
            "by_tool": {k: round(v, 4) for k, v in sorted(providers.items(), key=lambda kv: -kv[1])},
            "note": "از events.jsonl (هزینه‌ی هر فراخوانی ابزار) و cost_log.json (مسیریاب LLM) هر پروژه."}


# ---- provider health ------------------------------------------------------------------------

def _health(ping: bool = False) -> dict[str, Any]:
    from tools.audio.tts_selector import PERSIAN_TTS_PRIORITY
    from tools.base_tool import ToolStatus
    from tools.text.openai_compat_llm import OpenAICompatLLM, redact
    from tools.tool_registry import registry

    registry.ensure_discovered()

    def tool_row(name):
        tool = registry.get(name)
        return {"name": name, "available": bool(tool) and tool.get_status() == ToolStatus.AVAILABLE,
                "provider": tool.provider if tool else None}

    tts = [tool_row(n) for n in PERSIAN_TTS_PRIORITY]
    images = [tool_row(n) for n in ("google_imagen", "avalai_gemini_image")]
    llm = OpenAICompatLLM()
    profiles = []
    for name, cfg in llm.routing.get("profiles", {}).items():
        ok, why = llm.profile_status(name)
        row = {"name": name, "available": ok, "reason": None if ok else why, "latency_ms": None, "reachable": None}
        if ping and ok:
            row.update(_ping_profile(cfg, name))
        profiles.append(row)
    return {"tts": tts, "images": images, "llm_profiles": profiles,
            "pinged": ping, "checked_at": datetime.datetime.now().isoformat(timespec="seconds"),
            "note": redact("ping = GET <base_url>/models (free, no tokens)")}


def _ping_profile(cfg: dict[str, Any], name: str) -> dict[str, Any]:
    import os

    import httpx

    from tools.text.openai_compat_llm import redact

    key = os.environ.get(cfg.get("key_env") or "", "")
    headers = {"Authorization": f"Bearer {key}"} if key else {}
    started = time.monotonic()
    try:
        with httpx.Client(timeout=8, trust_env=cfg.get("proxy", "env") == "env") as client:
            resp = client.get(cfg["base_url"].rstrip("/") + "/models", headers=headers)
        ms = round((time.monotonic() - started) * 1000)
        ok = resp.status_code < 400
        return {"reachable": ok, "latency_ms": ms, "http": resp.status_code,
                "error": None if ok else explain(f"HTTP {resp.status_code}")}
    except Exception as exc:  # one try, no retry: report and move on
        return {"reachable": False, "latency_ms": None, "error": explain(redact(f"{type(exc).__name__}: {exc}", [key]))}


# ---- styles ------------------------------------------------------------------------------------

def _styles() -> list[dict[str, Any]]:
    from styles.edit_style_loader import card_summary, list_edit_styles, load_edit_style

    out = []
    for name in list_edit_styles():
        try:
            card = load_edit_style(name)
        except Exception as exc:
            out.append({"name": name, "error": str(exc)[:200]})
            continue
        out.append({**card_summary(card), "description": card["description"],
                    "kind": card["source"]["kind"], "best_for": card.get("best_for", []),
                    "palette": card["color_type"]["palette"], "hook_beats": card["hook_formula"]["beats"]})
    return out


class LearnStyle(BaseModel):
    url: str = Field(default="", max_length=500)
    input_path: str = Field(default="", max_length=500)
    name: str
    duration_seconds: float = Field(default=180, ge=10, le=7200)
    max_frames: int = Field(default=40, ge=5, le=120)


def _learn_estimate(req: LearnStyle) -> dict[str, Any]:
    from tools.analysis.edit_style_extractor import clip_weights_cached
    from tools.analysis.video_understand import VideoUnderstand
    from tools.base_tool import ToolStatus

    clip = VideoUnderstand().get_status() == ToolStatus.AVAILABLE and clip_weights_cached()
    frames = min(req.max_frames, max(1, int(req.duration_seconds / 3.75)))
    per_frame = 0.00036  # measured: gemini-3.1-flash-lite, 40 frames for $0.0143 (2026-11-04)
    vision = round(frames * per_frame * (0.2 if clip else 1.0), 4)
    return {"frames": frames, "local_clip": clip, "vision_usd": vision, "hook_usd": 0.0005,
            "total_usd": round(vision + 0.0005, 4),
            "note": "با CLIP محلی فقط فریم‌های نامطمئن پولی‌اند." if clip
            else "CLIP محلی نصب نیست؛ همه‌ی فریم‌ها با مدل ارزان برچسب می‌خورند."}


def _learn_start(req: LearnStyle) -> dict[str, Any]:
    if not SLUG.match(req.name):
        raise fa_error(400, "نام کارت نامعتبر است.", "فقط حروف کوچک انگلیسی، عدد و خط تیره.")
    if not req.url and not req.input_path:
        raise fa_error(400, "لینک یا فایل ویدیو لازم است.")
    if req.url and not re.match(r"^https?://", req.url):
        raise fa_error(400, "لینک باید با http یا https شروع شود.")
    est = _learn_estimate(req)
    if est["total_usd"] > 0.5:
        raise fa_error(400, f"هزینه‌ی تخمینی ${est['total_usd']} بیشتر از ۰.۵ دلار است.",
                       "تعداد فریم را کم کنید یا اول از ایجنت اجازه بگیرید.")
    job_id = uuid.uuid4().hex[:10]
    work = projects_dir() / "_reference" / req.name / "style_analysis"
    with _jobs_lock:
        _jobs[job_id] = {"id": job_id, "status": "running", "name": req.name, "estimate": est, "started": time.time()}

    def run():
        from tools.analysis.edit_style_extractor import EditStyleExtractor

        inputs = {"name": req.name, "work_dir": str(work), "max_frames": req.max_frames}
        inputs.update({"url": req.url} if req.url else {"input_path": req.input_path})
        try:
            r = EditStyleExtractor().execute(inputs)
            result = {"status": "done" if r.success else "failed",
                      "result": r.data if r.success else None,
                      "error": None if r.success else explain(r.error)}
        except Exception as exc:
            result = {"status": "failed", "error": explain(exc)}
        with _jobs_lock:
            _jobs[job_id].update(result)

    threading.Thread(target=run, daemon=True).start()
    return _jobs[job_id]


# ---- remake from a link -------------------------------------------------------------------------------

class RemakeLink(BaseModel):
    url: str = Field(min_length=8, max_length=500)
    mode: Literal["transcreate", "dub"] = "transcreate"
    rights: Literal["unknown", "own", "licensed", "permission"] = "unknown"
    target_seconds: Optional[float] = Field(default=None, ge=10, le=3600)
    budget_usd: float = Field(default=0.10, ge=0, le=0.5)


def _remake_start(req: RemakeLink) -> dict[str, Any]:
    from tools.analysis.reference_kit import RIGHTS_OK, classify_url

    if not re.match(r"^https?://", req.url):
        raise fa_error(400, "لینک باید با http یا https شروع شود.")
    if req.mode == "dub" and req.rights not in RIGHTS_OK:
        raise fa_error(400, "دوبله‌ی ویدیوی دیگران بدون اجازه مشکل حق نشر دارد.",
                       "اگر ویدیو مال خودتان است یا اجازه دارید، همان را انتخاب کنید؛ وگرنه «بازتولید» را بزنید.")
    info = classify_url(req.url)
    job_id = uuid.uuid4().hex[:10]
    with _jobs_lock:
        _jobs[job_id] = {"id": job_id, "kind": "remake", "status": "running", "platform": info["platform"],
                         "video_kind": info["kind"], "started": time.time()}

    def run():
        from tools.analysis.reference_kit import ReferenceKit

        inputs = {"url": req.url, "mode": req.mode, "rights": req.rights, "budget_usd": req.budget_usd,
                  "out_root": str(projects_dir() / "_reference")}
        if req.target_seconds:
            inputs["target_seconds"] = req.target_seconds
        try:
            r = ReferenceKit().execute(inputs)
            if r.success:
                folder = Path(r.data["folder"])
                b = r.data["brief"]
                result = {"status": "done", "kit": folder.name, "cost_usd": r.cost_usd,
                          "summary_fa": (folder / "REMAKE_fa.md").read_text(encoding="utf-8"),
                          "prefill": {
                              "topic": f"نسخه‌ی فارسی: {b['source'].get('title') or folder.name}"[:300],
                              "project_id": (folder.name[:52] + "-fa").strip("-"),
                              "format": "vertical" if b["format"]["aspect"] == "9:16" else "landscape",
                              "duration_seconds": int(max(15, min(1200, b["format"]["target_seconds"]))),
                              "edit_style": b["recommendation"]["edit_style_card"],
                              "reference_kit": folder.name}}
            else:
                result = {"status": "failed", "error": explain(r.error)
                          + (" راه‌حل: فایل cookies.txt یا خود فایل ویدیو." if info["platform"] == "instagram" else "")}
        except Exception as exc:
            result = {"status": "failed", "error": explain(exc)}
        with _jobs_lock:
            _jobs[job_id].update(result)

    threading.Thread(target=run, daemon=True).start()
    return dict(_jobs[job_id])


# ---- LLM routing ----------------------------------------------------------------------------------

def _routing_path() -> Path:
    from tools.text import openai_compat_llm

    return openai_compat_llm.ROUTING_PATH


def _routing() -> dict[str, Any]:
    from tools.text.openai_compat_llm import OpenAICompatLLM

    llm = OpenAICompatLLM(routing_path=_routing_path())
    cfg = llm.routing
    profiles = {name: {"available": llm.profile_status(name)[0], "base_url": p["base_url"],
                       "key_env": p.get("key_env")} for name, p in cfg.get("profiles", {}).items()}
    pricing = yaml.safe_load((REPO_ROOT / "config" / "fa_pricing.yaml").read_text(encoding="utf-8"))
    return {"mode": cfg.get("mode"), "profiles": profiles, "tiers": cfg.get("tiers", {}),
            "tasks": cfg.get("tasks", {}), "prices": pricing.get("llm", {}),
            "bakeoff": "docs/fa/llm_bakeoff/report.html"}


class TierUpdate(BaseModel):
    tier: Literal["bulk", "worker", "vision_bulk", "premium"]
    entries: list[dict[str, str]] = Field(min_length=1, max_length=6)


def _set_tier(update: TierUpdate) -> dict[str, Any]:
    path = _routing_path()
    text = path.read_text(encoding="utf-8")
    cfg = yaml.safe_load(text)
    profiles = cfg.get("profiles", {})
    clean = []
    for e in update.entries:
        profile, model = e.get("profile", ""), e.get("model", "")
        if profile not in profiles:
            raise fa_error(400, f"پروفایل «{profile}» تعریف نشده.")
        if not MODEL_ID.match(model):
            raise fa_error(400, f"شناسه‌ی مدل «{model}» نامعتبر است.")
        clean.append({"profile": profile, "model": model})
    cfg["tiers"][update.tier] = clean
    start, end = text.index("\ntiers:\n") + 1, text.index("\nescalation:")
    lines = ["tiers:"]
    for tier, entries in cfg["tiers"].items():
        if not entries:
            lines.append(f"  {tier}: []")
            continue
        lines.append(f"  {tier}:")
        for e in entries:
            extra = ""
            if e.get("price"):
                extra = f", price: {{input: {e['price']['input']}, output: {e['price']['output']}}}"
            lines.append(f"    - {{profile: {e['profile']}, model: {e['model']}{extra}}}")
    new_text = text[:start] + "\n".join(lines) + "\n" + text[end:]
    yaml.safe_load(new_text)  # never write a file that does not parse
    path.write_text(new_text, encoding="utf-8")
    return _routing()


# ---- router -------------------------------------------------------------------------------------------

def install_error_handler(app) -> None:
    """Unexpected errors reach the page as one Persian sentence, never a traceback or a key."""
    from fastapi.responses import JSONResponse

    @app.exception_handler(Exception)
    async def unexpected(request, exc):  # noqa: ARG001
        return JSONResponse(status_code=500, content={
            "detail": "خطای پیش‌بینی‌نشده در سرور. " + explain(f"{type(exc).__name__}: {exc}")
            + " — اگر تکرار شد، متن خطا را برای ایجنت بفرستید."})


def build_router(panel: list) -> APIRouter:
    router = APIRouter(prefix="/api/fa")

    @router.post("/estimate", dependencies=panel)
    async def estimate(w: Wizard) -> dict:
        return await asyncio.to_thread(_estimate, w)

    @router.post("/projects", dependencies=panel)
    async def create(w: Wizard) -> dict:
        return await asyncio.to_thread(_create, w)

    @router.get("/projects/{project_id}/timeline")
    async def timeline(project_id: str) -> dict:
        return await asyncio.to_thread(_timeline, project_id)

    @router.post("/projects/{project_id}/review", dependencies=panel)
    async def review(project_id: str, r: Review) -> dict:
        return await asyncio.to_thread(_review, project_id, r)

    @router.get("/costs")
    async def costs() -> dict:
        return await asyncio.to_thread(_costs)

    @router.get("/health")
    async def health() -> dict:
        return await asyncio.to_thread(_health, False)

    @router.post("/health/ping", dependencies=panel)
    async def health_ping() -> dict:
        return await asyncio.to_thread(_health, True)

    @router.get("/styles")
    async def styles() -> list:
        return await asyncio.to_thread(_styles)

    @router.post("/styles/learn/estimate", dependencies=panel)
    async def learn_estimate(req: LearnStyle) -> dict:
        return await asyncio.to_thread(_learn_estimate, req)

    @router.post("/styles/learn", dependencies=panel)
    async def learn(req: LearnStyle) -> dict:
        return await asyncio.to_thread(_learn_start, req)

    @router.post("/remake", dependencies=panel)
    async def remake(req: RemakeLink) -> dict:
        return await asyncio.to_thread(_remake_start, req)

    @router.get("/jobs/{job_id}")
    async def job(job_id: str) -> dict:
        with _jobs_lock:
            if job_id not in _jobs:
                raise fa_error(404, "کار پیدا نشد.")
            return dict(_jobs[job_id])

    @router.get("/llm-routing")
    async def routing() -> dict:
        return await asyncio.to_thread(_routing)

    @router.post("/llm-routing", dependencies=panel)
    async def set_routing(update: TierUpdate) -> dict:
        return await asyncio.to_thread(_set_tier, update)

    return router
