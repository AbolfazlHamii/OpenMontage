"""Quality gate for Persian renders: one call, JSON + a short Persian summary.

Checks (each: pass / warn / fail / skipped, with evidence):
- loudness: -14 LUFS ±1, true peak <= -1 dBTP (loudness_normalize measure)
- black frames (blackdetect) and frozen stretches (freezedetect)
- streams: resolution/duration/audio (visual_qa probe), audio-video sync
  (stream start/length difference)
- duration vs script (script artifact total or sections)
- captions (SRT or caption JSON): overlaps, cues past the end, reading speed,
  RLM/RTL marking, safe area when a layout is given
- RTL in an HTML workspace (lang/dir on the document or caption container)
- no text in generated images (vision_bulk, paid, cents; opt-in)
- edit craft, when an edit plan is given (lib/fa_edit_qa.py): cut rhythm vs
  the style card, hook, SFX density and cut accents, caption on-screen time,
  beat sync, music ducking and ending, end screen

Reuses visual_qa (probe + review frames) and loudness_normalize; the
workspace check reads composition HTML only.
"""

from __future__ import annotations

import json
import re
import shutil
import subprocess
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any, Callable, Optional

PERSIAN = re.compile(r"[؀-ۿ]")
RLM = "‏"
TARGET_LUFS, LUFS_TOL, MAX_TP = -14.0, 1.0, -1.0


@dataclass
class Check:
    name: str
    status: str  # pass | warn | fail | skipped
    detail: str
    evidence: dict[str, Any] = field(default_factory=dict)


def _ffmpeg() -> str:
    return shutil.which("ffmpeg") or "ffmpeg"


def _run_filter(path: Path, vf: Optional[str] = None, af: Optional[str] = None) -> str:
    cmd = [_ffmpeg(), "-hide_banner", "-nostats", "-i", str(path)]
    cmd += ["-vf", vf, "-an"] if vf else ["-af", af, "-vn"]
    cmd += ["-f", "null", "-"]
    proc = subprocess.run(cmd, capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=1800)
    return proc.stderr or ""


# -- parsers (unit-tested) ---------------------------------------------------------

def parse_blackdetect(stderr: str) -> list[dict[str, float]]:
    return [{"start": float(a), "end": float(b), "duration": float(c)}
            for a, b, c in re.findall(r"black_start:([\d.]+) black_end:([\d.]+) black_duration:([\d.]+)", stderr)]


def parse_freezedetect(stderr: str) -> list[dict[str, float]]:
    starts = [float(x) for x in re.findall(r"freeze_start: ([\d.]+)", stderr)]
    durs = [float(x) for x in re.findall(r"freeze_duration: ([\d.]+)", stderr)]
    return [{"start": s, "duration": d} for s, d in zip(starts, durs)]


def parse_srt(text: str) -> list[dict[str, Any]]:
    def secs(ts: str) -> float:
        h, m, rest = ts.replace(",", ".").split(":")
        return int(h) * 3600 + int(m) * 60 + float(rest)

    cues = []
    for block in re.split(r"\n\s*\n", text.strip().replace("\r\n", "\n")):
        lines = block.strip().split("\n")
        timing = next((l for l in lines if "-->" in l), None)
        if not timing:
            continue
        a, b = [t.strip() for t in timing.split("-->")]
        body = lines[lines.index(timing) + 1:]
        cues.append({"start": secs(a), "end": secs(b.split()[0]), "lines": body})
    return cues


# -- checks -------------------------------------------------------------------------

def check_loudness(measured: dict[str, float]) -> Check:
    i, tp = measured["integrated_lufs"], measured["true_peak_dbtp"]
    problems = []
    if abs(i - TARGET_LUFS) > LUFS_TOL:
        problems.append(f"integrated {i:.1f} LUFS (target {TARGET_LUFS:.0f} ±{LUFS_TOL:.0f})")
    if tp > MAX_TP:
        problems.append(f"true peak {tp:.1f} dBTP (max {MAX_TP:.0f})")
    if problems:
        return Check("loudness", "fail", "; ".join(problems) +
                     " — fix: loudness_normalize (defaults -14 / -1)", measured)
    return Check("loudness", "pass", f"{i:.1f} LUFS, true peak {tp:.1f} dBTP", measured)


def check_black(spans: list[dict[str, float]], duration: float) -> Check:
    inner = [s for s in spans if s["start"] > 0.05 and s["end"] < duration - 0.05]
    edges = [s for s in spans if s not in inner]
    if inner:
        return Check("black_frames", "fail", f"{len(inner)} black span(s) inside the video", {"spans": spans})
    if edges:
        return Check("black_frames", "warn", "black only at the start/end (fade?)", {"spans": spans})
    return Check("black_frames", "pass", "no black frames", {})


def check_freeze(spans: list[dict[str, float]], max_hold: float) -> Check:
    long = [s for s in spans if s["duration"] > max_hold]
    if long:
        return Check("frozen_frames", "warn",
                     f"{len(long)} still stretch(es) over {max_hold:.0f} s — pattern interrupt?", {"spans": long})
    return Check("frozen_frames", "pass", f"no hold over {max_hold:.0f} s", {"spans": spans})


def check_av_sync(streams: list[dict[str, Any]]) -> Check:
    v = next((s for s in streams if s.get("codec_type") == "video"), None)
    a = next((s for s in streams if s.get("codec_type") == "audio"), None)
    if not v or not a:
        return Check("av_sync", "fail" if v and not a else "skipped", "missing audio or video stream", {})
    vs, as_ = float(v.get("start_time") or 0), float(a.get("start_time") or 0)
    vd, ad = float(v.get("duration") or 0), float(a.get("duration") or 0)
    ev = {"video_start": vs, "audio_start": as_, "video_duration": vd, "audio_duration": ad}
    if abs(vs - as_) > 0.05:
        return Check("av_sync", "fail", f"audio starts {as_ - vs:+.3f} s from video", ev)
    if abs(vd - ad) > 0.25:
        return Check("av_sync", "warn", f"audio and video lengths differ by {ad - vd:+.2f} s", ev)
    return Check("av_sync", "pass", "streams start together and end within 0.25 s", ev)


def check_duration(duration: float, script: Optional[dict[str, Any]], tol: float = 0.05) -> Check:
    if not script:
        return Check("duration_vs_script", "skipped", "no script given", {})
    target = script.get("total_duration_seconds")
    if not target and script.get("sections"):
        target = max(s["end_seconds"] for s in script["sections"])
    if not target:
        return Check("duration_vs_script", "skipped", "script has no duration", {})
    d = (duration - target) / target
    ev = {"render": round(duration, 2), "script": target, "deviation": round(d, 3)}
    status = "pass" if abs(d) <= tol else "fail"
    return Check("duration_vs_script", status, f"render {duration:.1f} s vs script {target} s ({d:+.0%})", ev)


def check_captions(cues: list[dict[str, Any]], duration: float, max_cps: float = 20.0,
                   layout: Optional[dict[str, Any]] = None) -> list[Check]:
    if not cues:
        return [Check("captions", "skipped", "no captions given", {})]
    out = []
    overlaps = [(i, i + 1) for i in range(len(cues) - 1) if cues[i + 1]["start"] < cues[i]["end"] - 0.01]
    past = [i for i, c in enumerate(cues) if c["end"] > duration + 0.05]
    out.append(Check("caption_timing", "fail" if overlaps or past else "pass",
                     f"{len(overlaps)} overlap(s), {len(past)} cue(s) past the end",
                     {"overlaps": overlaps, "past_end": past}))
    fast = []
    for i, c in enumerate(cues):
        chars = sum(len(PERSIAN.findall(l)) for l in c["lines"])
        span = max(c["end"] - c["start"], 0.01)
        if chars / span > max_cps:
            fast.append({"cue": i, "cps": round(chars / span, 1)})
    out.append(Check("caption_reading_speed", "warn" if fast else "pass",
                     f"{len(fast)} cue(s) faster than {max_cps:.0f} letters/s", {"fast": fast}))
    unmarked = [i for i, c in enumerate(cues)
                if any(PERSIAN.search(l) and not l.startswith(RLM) for l in c["lines"])]
    out.append(Check("caption_rtl", "warn" if unmarked else "pass",
                     "Persian lines without a leading RLM (punctuation may jump to the wrong side)"
                     if unmarked else "every Persian line starts with RLM", {"cues": unmarked[:20]}))
    if layout:
        sx, sy = layout.get("safe_x", 0.05), layout.get("safe_y", 0.05)
        bad = [b for b in layout.get("boxes", [])
               if b["x"] < sx or b["y"] < sy or b["x"] + b["w"] > 1 - sx or b["y"] + b["h"] > 1 - sy]
        out.append(Check("caption_safe_area", "fail" if bad else "pass",
                         f"{len(bad)} caption box(es) outside the safe area", {"boxes": bad}))
    else:
        out.append(Check("caption_safe_area", "skipped", "no caption layout given; see review frames", {}))
    return out


def check_workspace_rtl(html: str) -> Check:
    has_fa = bool(PERSIAN.search(html))
    if not has_fa:
        return Check("workspace_rtl", "skipped", "no Persian text in the workspace", {})
    lang = bool(re.search(r"<html[^>]*\blang=[\"']fa", html))
    dir_rtl = bool(re.search(r"\bdir=[\"']rtl[\"']", html)) or "direction: rtl" in html or "direction:rtl" in html
    ev = {"lang_fa": lang, "dir_rtl": dir_rtl}
    if dir_rtl:
        return Check("workspace_rtl", "pass", "Persian text with RTL direction set", ev)
    return Check("workspace_rtl", "warn", "Persian text but no dir=\"rtl\" / direction: rtl in the workspace "
                 "(text may still render right-aligned by script, but punctuation and mixed runs can flip)", ev)


def check_images_text(results: list[dict[str, Any]]) -> Check:
    if not results:
        return Check("image_text", "skipped", "no images checked", {})
    flagged = [r for r in results if r.get("has_text")]
    persian = [r for r in flagged if r.get("script") == "persian"]
    if persian:
        return Check("image_text", "fail", f"{len(persian)} generated image(s) contain Persian text", {"images": flagged})
    if flagged:
        return Check("image_text", "warn", f"{len(flagged)} generated image(s) contain text", {"images": flagged})
    return Check("image_text", "pass", f"no text in {len(results)} generated image(s)", {"images": results})


# -- runner -----------------------------------------------------------------------

IMAGE_TEXT_SCHEMA = {
    "type": "object", "required": ["has_text", "script"],
    "properties": {"has_text": {"type": "boolean"},
                   "script": {"type": "string", "enum": ["none", "persian", "latin", "other"]}},
}


def image_text_vision(paths: list[Path], llm=None) -> tuple[list[dict[str, Any]], float]:
    if llm is None:
        from tools.text.llm_selector import LLMSelector
        llm = LLMSelector()
    prompt = ('Does this image contain any readable letters, words or numbers? Reply with JSON only: '
              '{"has_text": true|false, "script": "none"|"persian"|"latin"|"other"}')
    items = [{"id": str(i), "task": "frame_labels", "prompt": prompt, "images": [str(p)],
              "json_schema": IMAGE_TEXT_SCHEMA, "temperature": 0, "max_tokens": 60}
             for i, p in enumerate(paths)]
    r = llm.execute({"operation": "batch", "items": items})
    out = []
    for i, p in enumerate(paths):
        data = (r.data.get("results") or {}).get(str(i)) or {}
        j = data.get("json") or {}
        out.append({"image": str(p), "has_text": j.get("has_text"), "script": j.get("script"),
                    "error": None if j else "no answer"})
    return out, r.cost_usd or 0.0


def run_qa(render: Path, *, script: Optional[dict] = None, captions: Optional[list[dict]] = None,
           caption_layout: Optional[dict] = None, workspace_html: Optional[str] = None,
           images: Optional[list[Path]] = None, freeze_max: float = 6.0,
           frames_dir: Optional[Path] = None,
           image_checker: Optional[Callable[[list[Path]], tuple[list[dict], float]]] = None,
           edit_plan: Optional[dict] = None, card: Optional[dict] = None) -> dict[str, Any]:
    from tools.analysis.visual_qa import VisualQA
    from tools.audio.loudness_normalize import LoudnessNormalize

    checks: list[Check] = []
    cost = 0.0

    probe = VisualQA().execute({"operation": "probe", "input_path": str(render)})
    info = probe.data if probe.success else {}
    duration = float(info.get("duration") or info.get("duration_seconds") or 0)
    streams = json.loads(subprocess.run(
        [shutil.which("ffprobe") or "ffprobe", "-v", "error", "-show_entries",
         "stream=codec_type,start_time,duration,width,height", "-of", "json", str(render)],
        capture_output=True, text=True, encoding="utf-8", timeout=60).stdout or "{}").get("streams", [])
    if not duration:
        duration = max((float(s.get("duration") or 0) for s in streams), default=0.0)
    checks.append(Check("probe", "pass" if probe.success else "fail",
                        f"{duration:.2f} s" if probe.success else str(probe.error), info))

    loud = LoudnessNormalize().execute({"input_path": str(render), "operation": "measure"})
    checks.append(check_loudness(loud.data["before"]) if loud.success
                  else Check("loudness", "fail", f"could not measure: {loud.error}", {}))
    checks.append(check_black(parse_blackdetect(_run_filter(render, vf="blackdetect=d=0.1:pix_th=0.10")), duration))
    checks.append(check_freeze(parse_freezedetect(_run_filter(render, vf="freezedetect=n=-60dB:d=2")), freeze_max))
    checks.append(check_av_sync(streams))
    checks.append(check_duration(duration, script))
    if captions is None and edit_plan:
        captions = edit_plan.get("caption_cues")
    checks += check_captions(captions or [], duration, layout=caption_layout or (edit_plan or {}).get("caption_layout"))
    if edit_plan is not None:
        from lib.fa_edit_qa import edit_checks
        checks += edit_checks({**edit_plan, "duration": duration}, card)
    if workspace_html is not None:
        checks.append(check_workspace_rtl(workspace_html))
    if images:
        results, c = (image_checker or image_text_vision)(images)
        cost += c
        checks.append(check_images_text(results))
    else:
        checks.append(check_images_text([]))

    review = {}
    if frames_dir is not None and duration:
        stamps = [round(duration * k / 6, 2) for k in range(1, 6)]
        r = VisualQA().execute({"operation": "review", "input_path": str(render), "timestamps": stamps,
                                "output_dir": str(frames_dir)})
        review = {"frames": (r.data or {}).get("frames", []), "timestamps": stamps}

    worst = "pass"
    for c in checks:
        if c.status == "fail":
            worst = "fail"
        elif c.status == "warn" and worst == "pass":
            worst = "warn"
    return {"render": str(render), "duration_seconds": duration, "status": worst,
            "checks": [asdict(c) for c in checks], "review_frames": review, "cost_usd": round(cost, 6)}


FA_NAMES = {
    "probe": "مشخصات فایل", "loudness": "بلندی صدا", "black_frames": "فریم سیاه",
    "frozen_frames": "تصویر ثابت طولانی", "av_sync": "هم‌زمانی صدا و تصویر",
    "duration_vs_script": "مدت در برابر متن", "caption_timing": "زمان‌بندی زیرنویس",
    "caption_reading_speed": "سرعت خواندن زیرنویس", "caption_rtl": "جهت راست‌به‌چپ زیرنویس",
    "caption_safe_area": "محدوده امن زیرنویس", "workspace_rtl": "راست‌به‌چپ در کامپوزیشن",
    "image_text": "متن داخل تصویرهای تولیدی", "captions": "زیرنویس",
}
FA_STATUS = {"pass": "✅ درست", "warn": "⚠️ هشدار", "fail": "❌ مشکل", "skipped": "— بررسی نشد"}


def persian_summary(report: dict[str, Any]) -> str:
    from lib.fa_edit_qa import FA_NAMES as EDIT_FA_NAMES

    lines = [f"بررسی کیفیت: {Path(report['render']).name} — نتیجه کلی: {FA_STATUS[report['status']]}"]
    for c in report["checks"]:
        name = FA_NAMES.get(c["name"]) or EDIT_FA_NAMES.get(c["name"], c["name"])
        lines.append(f"- {name}: {FA_STATUS[c['status']]} ({c['detail']})")
    if report.get("cost_usd"):
        lines.append(f"هزینه این بررسی: ${report['cost_usd']:.4f}")
    return "\n".join(lines)
