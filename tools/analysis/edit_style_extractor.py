"""Learn an edit style card from a reference video.

Free first: shots come from scene_detect, motion from frame differences,
cut/onset sync from the audio track, words per minute from a transcript, and
shot labels from local CLIP (video_understand classify) when it is installed.
Only frames CLIP is unsure about (or all sampled frames, when CLIP is not
installed) go to the vision_bulk tier through llm_selector, and the hook
structure is drafted by the worker tier for the agent to finish. Costs are
reported.

operation "extract": video (or URL) -> styles/editing/learned/<name>.yaml +
report.json in the work dir.
operation "compare": render -> ASL / cuts-per-minute / words-per-minute /
subtitles vs a card, for the reviewer's style-compliance check.

Videos over `chunk_seconds` (600, the analyzer limit) are analysed in chunks.
Keyframes, chunks and downloads stay in the work dir, which must be
git-ignored (default: projects/_reference/<name>/style_analysis/).
"""

from __future__ import annotations

import datetime
import json
import os
import shutil
import statistics
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
SYNC_WINDOW = 0.08  # seconds either side of an onset

LABEL_GROUPS = {
    "shot_size": ["extreme wide shot", "wide shot", "medium shot", "close-up", "extreme close-up"],
    "camera_angle": ["eye-level shot", "low-angle shot", "high-angle shot", "top-down overhead shot", "dutch angle shot"],
    "content": ["cartoon illustration", "photograph", "live-action video frame", "map", "chart or diagram", "text on screen"],
}
VISION_SCHEMA = {
    "type": "object",
    "required": ["shot_size", "camera_angle", "content", "has_text"],
    "properties": {
        "shot_size": {"type": "string", "enum": ["extreme_wide", "wide", "medium", "close_up", "extreme_close_up"]},
        "camera_angle": {"type": "string", "enum": ["eye_level", "low", "high", "top_down", "dutch"]},
        "content": {"type": "string", "enum": ["illustration", "photo", "live_action", "map", "chart", "text"]},
        "has_text": {"type": "boolean"},
    },
}
CLIP_TO_LABEL = {
    "extreme wide shot": "extreme_wide", "wide shot": "wide", "medium shot": "medium",
    "close-up": "close_up", "extreme close-up": "extreme_close_up",
    "eye-level shot": "eye_level", "low-angle shot": "low", "high-angle shot": "high",
    "top-down overhead shot": "top_down", "dutch angle shot": "dutch",
    "cartoon illustration": "illustration", "photograph": "photo",
    "live-action video frame": "live_action", "map": "map", "chart or diagram": "chart",
    "text on screen": "text",
}
CLIP_REPO = "openai/clip-vit-base-patch32"


def clip_weights_cached() -> bool:
    """True only when the CLIP weights themselves are in the local HF cache."""
    try:
        from huggingface_hub import try_to_load_from_cache
    except ImportError:
        return False
    for name in ("model.safetensors", "pytorch_model.bin"):
        path = try_to_load_from_cache(CLIP_REPO, name)
        if isinstance(path, str) and Path(path).exists():
            return True
    return False


RTL_NOTES = [
    "Captions and labels are HTML in the composition, right-aligned, dir=rtl, Vazirmatn; never baked into generated images.",
    "Slides and reveals that mean 'forward in time' move right to left.",
]


def _ffmpeg() -> str:
    return shutil.which("ffmpeg") or "ffmpeg"


def _ffprobe() -> str:
    return shutil.which("ffprobe") or "ffprobe"


def probe_duration(path: Path) -> float:
    out = subprocess.run(
        [_ffprobe(), "-v", "error", "-show_entries", "format=duration", "-of", "csv=p=0", str(path)],
        capture_output=True, text=True, encoding="utf-8", timeout=60, check=True,
    ).stdout.strip()
    return float(out)


# -- pure measurements (unit-tested) -------------------------------------------

def shot_lengths(shots: list[dict[str, float]]) -> list[float]:
    return [s["end_seconds"] - s["start_seconds"] for s in shots if s["end_seconds"] > s["start_seconds"]]


def section_bounds(duration: float) -> dict[str, tuple[float, float]]:
    hook = min(30.0, max(10.0, duration * 0.1))
    outro = min(30.0, max(5.0, duration * 0.08))
    if hook + outro >= duration:
        hook, outro = duration * 0.3, duration * 0.2
    return {"hook": (0.0, hook), "body": (hook, duration - outro), "outro": (duration - outro, duration)}


def section_pacing(shots: list[dict[str, float]], duration: float) -> dict[str, dict[str, float]]:
    out = {}
    for name, (a, b) in section_bounds(duration).items():
        inside = [s for s in shots if a <= (s["start_seconds"] + s["end_seconds"]) / 2 < b]
        lengths = shot_lengths(inside) or [b - a]
        asl = statistics.mean(lengths)
        cuts = sum(1 for s in shots if a < s["start_seconds"] < b)
        minutes = max((b - a) / 60, 1e-6)
        out[name] = {"asl_seconds": round(asl, 2), "cuts_per_minute": round(cuts / minutes, 1),
                     "duration_seconds": round(b - a, 1)}
    return out


def cut_rate_curve(cut_times: list[float], duration: float, window: float = 30.0) -> list[dict[str, float]]:
    curve, t = [], 0.0
    while t < duration:
        end = min(duration, t + window)
        n = sum(1 for c in cut_times if t <= c < end)
        curve.append({"start": round(t, 1), "cuts_per_minute": round(n / max((end - t) / 60, 1e-6), 1)})
        t = end
    return curve


def onset_sync(cut_times: list[float], onsets: list[float], window: float = SYNC_WINDOW,
               duration: Optional[float] = None) -> dict[str, Optional[float]]:
    if not cut_times or not onsets:
        return {"ratio": None, "chance": None}
    import bisect

    hits = 0
    for c in cut_times:
        i = bisect.bisect_left(onsets, c)
        near = [onsets[j] for j in (i - 1, i) if 0 <= j < len(onsets)]
        if any(abs(c - o) <= window for o in near):
            hits += 1
    chance = None
    if duration:
        chance = round(min(1.0, len(onsets) * 2 * window / duration), 3)
    return {"ratio": round(hits / len(cut_times), 3), "chance": chance}


def words_per_minute(segments: list[dict[str, Any]], start: float = 0.0,
                     end: Optional[float] = None) -> Optional[float]:
    words, first, last = 0, None, None
    for seg in segments:
        s = float(seg.get("start", 0))
        e = float(seg["end"]) if "end" in seg else s + float(seg.get("duration", 0))
        if s < start or (end is not None and s >= end):
            continue
        words += len(str(seg.get("text", "")).split())
        first = s if first is None else min(first, s)
        last = e if last is None else max(last, e)
    if not words or first is None or last is None or last <= first:
        return None
    return round(words / ((last - first) / 60), 1)


def motion_label(diff: float) -> str:
    """Mean absolute pixel difference (0-255) between two frames of one shot."""
    if diff < 2.0:
        return "static"
    if diff < 12.0:
        return "ken_burns"
    return "fast_motion"


def detect_onsets(samples, rate: int) -> list[float]:
    """Energy-rise onsets (seconds) from mono samples; crude but free."""
    import numpy as np

    hop = int(rate * 0.01)
    if len(samples) < hop * 4:
        return []
    frames = len(samples) // hop
    energy = np.sqrt(np.mean(samples[: frames * hop].reshape(frames, hop) ** 2, axis=1))
    flux = np.maximum(np.diff(energy, prepend=energy[0]), 0)
    threshold = flux.mean() + 1.5 * flux.std()
    onsets, last = [], -1.0
    for i in range(1, len(flux) - 1):
        t = i * hop / rate
        if flux[i] > threshold and flux[i] >= flux[i - 1] and flux[i] >= flux[i + 1] and t - last > 0.1:
            onsets.append(round(t, 3))
            last = t
    return onsets


def energy_curve(samples, points: int = 6) -> list[dict[str, float]]:
    import numpy as np

    if len(samples) == 0:
        return [{"at": 0.0, "energy": 0.5}, {"at": 1.0, "energy": 0.5}]
    chunks = np.array_split(samples, points)
    rms = [float(np.sqrt(np.mean(c ** 2))) if len(c) else 0.0 for c in chunks]
    top = max(rms) or 1.0
    return [{"at": round(i / (points - 1), 2), "energy": round(r / top, 2)} for i, r in enumerate(rms)]


def weighted(counts: dict[str, int], note: str = "") -> list[dict[str, Any]]:
    total = sum(counts.values())
    if not total:
        return [{"name": "not_measured", "weight": 0, "note": note or "no data"}]
    out = [{"name": k, "weight": round(v / total, 2)} for k, v in sorted(counts.items(), key=lambda kv: -kv[1])]
    if note:
        out[0]["note"] = note
    return out


def compare_metrics(measured: dict[str, Any], card: dict[str, Any], tolerance: float = 0.25) -> dict[str, Any]:
    """Style-compliance check: render measurements vs a card."""
    checks = []
    body = card["pacing"]["sections"]["body"]

    def rel(a, b):
        return abs(a - b) / b if b else 0.0

    if measured.get("asl_seconds"):
        d = rel(measured["asl_seconds"], body["asl_seconds"])
        checks.append({"check": "asl_seconds", "render": measured["asl_seconds"],
                       "card": body["asl_seconds"], "deviation": round(d, 3), "pass": d <= tolerance})
    if measured.get("cuts_per_minute") is not None:
        d = rel(measured["cuts_per_minute"], body["cuts_per_minute"])
        checks.append({"check": "cuts_per_minute", "render": measured["cuts_per_minute"],
                       "card": body["cuts_per_minute"], "deviation": round(d, 3), "pass": d <= tolerance})
    if measured.get("words_per_minute"):
        target = card["pacing"]["words_per_minute"]
        d = rel(measured["words_per_minute"], target)
        checks.append({"check": "words_per_minute", "render": measured["words_per_minute"],
                       "card": target, "deviation": round(d, 3), "pass": d <= tolerance})
    if "subtitles_present" in measured:
        wanted = card["subtitles"]["style"] != "none"
        checks.append({"check": "subtitles", "render": measured["subtitles_present"],
                       "card": card["subtitles"]["style"], "pass": measured["subtitles_present"] == wanted})
    if measured.get("longest_static_seconds") is not None:
        limit = card["pattern_interrupt_seconds"]["max"]
        checks.append({"check": "pattern_interrupt", "render": measured["longest_static_seconds"],
                       "card": limit, "pass": measured["longest_static_seconds"] <= limit * 1.5})
    return {"pass": all(c["pass"] for c in checks), "checks": checks, "tolerance": tolerance}


# -- the tool -------------------------------------------------------------------

class EditStyleExtractor(BaseTool):
    name = "edit_style_extractor"
    version = "0.1.0"
    tier = ToolTier.CORE
    capability = "analysis"
    provider = "openmontage"
    stability = ToolStability.EXPERIMENTAL
    execution_mode = ExecutionMode.SYNC
    determinism = Determinism.STOCHASTIC
    runtime = ToolRuntime.HYBRID

    dependencies = ["cmd:ffmpeg", "python:scenedetect", "python:numpy", "python:PIL"]
    install_instructions = (
        "FFmpeg + `pip install scenedetect[opencv]`. Optional: transformers + torch for free "
        "local CLIP labels; otherwise frames are labelled by the vision_bulk tier (paid, cents)."
    )
    agent_skills = ["video-understand"]
    capabilities = ["edit_style_learning", "style_compliance"]
    best_for = ["turning a reference video into an edit style card", "checking a render against a card"]
    resource_profile = ResourceProfile(cpu_cores=2, ram_mb=1024, vram_mb=0, disk_mb=2000)

    input_schema = {
        "type": "object",
        "properties": {
            "operation": {"type": "string", "enum": ["extract", "compare"], "default": "extract"},
            "input_path": {"type": "string"},
            "url": {"type": "string"},
            "name": {"type": "string", "description": "Card name (kebab-case)."},
            "title": {"type": "string"},
            "work_dir": {"type": "string", "description": "git-ignored scratch dir for frames/chunks"},
            "transcript_path": {"type": "string",
                                "description": "JSON with segments [{text, start, end|duration}]"},
            "chunk_seconds": {"type": "number", "default": 600},
            "max_frames": {"type": "integer", "default": 40},
            "clip_confidence": {"type": "number", "default": 0.45},
            "use_vision_bulk": {"type": "boolean", "default": True},
            "draft_hook": {"type": "boolean", "default": True},
            "card": {"type": "string", "description": "compare: card name"},
            "edit_decisions_path": {"type": "string", "description": "compare: to check subtitles"},
            "tolerance": {"type": "number", "default": 0.25},
            "editing_dir": {"type": "string"},
        },
    }
    side_effects = ["writes a learned card and a report", "may call paid vision/worker tiers (cents)"]

    def __init__(self, llm_selector: Optional[BaseTool] = None,
                 scene_detector: Optional[Callable[[Path, float], list[dict]]] = None,
                 clip_labeler: Optional[Callable[[list[Path]], Optional[list[dict]]]] = None):
        self._llm = llm_selector
        self._scene_detector = scene_detector
        self._clip_labeler = clip_labeler

    def get_status(self) -> ToolStatus:
        return ToolStatus.AVAILABLE if shutil.which("ffmpeg") else ToolStatus.UNAVAILABLE

    @property
    def llm(self) -> BaseTool:
        if self._llm is None:
            from tools.text.llm_selector import LLMSelector
            self._llm = LLMSelector()
        return self._llm

    # -- steps ------------------------------------------------------------

    def detect_shots(self, video: Path, duration: float, chunk_seconds: float, work: Path) -> list[dict]:
        detect = self._scene_detector or self._scene_detect
        if duration <= chunk_seconds:
            return detect(video, 0.0)
        shots: list[dict] = []
        start = 0.0
        while start < duration:
            chunk = work / "chunks" / f"chunk_{int(start):05d}.mp4"
            chunk.parent.mkdir(parents=True, exist_ok=True)
            if not chunk.exists():
                subprocess.run([_ffmpeg(), "-v", "error", "-y", "-ss", str(start), "-i", str(video),
                                "-t", str(chunk_seconds), "-c", "copy", str(chunk)],
                               check=True, timeout=600)
            shots += detect(chunk, start)
            start += chunk_seconds
        return shots

    @staticmethod
    def _scene_detect(path: Path, offset: float) -> list[dict]:
        from tools.analysis.scene_detect import SceneDetect

        r = SceneDetect().execute({"input_path": str(path), "min_scene_length_seconds": 0.5})
        if not r.success:
            raise RuntimeError(r.error)
        return [{"start_seconds": s["start_seconds"] + offset, "end_seconds": s["end_seconds"] + offset}
                for s in r.data.get("scenes", [])]

    @staticmethod
    def _frame(video: Path, t: float, out: Path, width: int = 384) -> Path:
        out.parent.mkdir(parents=True, exist_ok=True)
        subprocess.run([_ffmpeg(), "-v", "error", "-y", "-ss", f"{t:.3f}", "-i", str(video),
                        "-frames:v", "1", "-vf", f"scale={width}:-2", str(out)], check=True, timeout=120)
        return out

    def sample_frames(self, video: Path, shots: list[dict], work: Path, max_frames: int) -> list[dict]:
        import numpy as np
        from PIL import Image

        step = max(1, len(shots) // max_frames) if max_frames else 1
        picked = shots[::step][:max_frames]
        frames = []
        for i, shot in enumerate(picked):
            a, b = shot["start_seconds"], shot["end_seconds"]
            mid = self._frame(video, (a + b) / 2, work / "keyframes" / f"shot_{i:03d}.jpg")
            early = self._frame(video, a + (b - a) * 0.2, work / "motion" / f"shot_{i:03d}_a.jpg", 160)
            late = self._frame(video, a + (b - a) * 0.8, work / "motion" / f"shot_{i:03d}_b.jpg", 160)
            x = np.asarray(Image.open(early).convert("L"), dtype=np.float32)
            y = np.asarray(Image.open(late).convert("L"), dtype=np.float32)
            diff = float(np.abs(x - y).mean()) if x.shape == y.shape else 99.0
            frames.append({"shot": shot, "path": mid, "motion_diff": round(diff, 2), "motion": motion_label(diff)})
        return frames

    def clip_labels(self, paths: list[Path]) -> Optional[list[dict]]:
        """{group: (label, confidence)} per frame, or None when CLIP is not installed."""
        if self._clip_labeler is not None:
            return self._clip_labeler(paths)
        from tools.analysis.video_understand import VideoUnderstand

        tool = VideoUnderstand()
        # transformers being installed is not enough: from Iran the weights
        # download from huggingface.co times out, and a half-finished download
        # made every run hang. Use CLIP only when the weights are on disk, offline.
        if tool.get_status() != ToolStatus.AVAILABLE or not clip_weights_cached():
            return None
        out = [dict() for _ in paths]
        previous = os.environ.get("HF_HUB_OFFLINE")
        os.environ["HF_HUB_OFFLINE"] = "1"
        try:
            for group, labels in LABEL_GROUPS.items():
                for i, p in enumerate(paths):
                    r = tool.execute({"input_path": str(p), "mode": "classify", "model": "clip", "labels": labels})
                    if not r.success:
                        return None
                    top = r.data["frames"][0]
                    out[i][group] = (CLIP_TO_LABEL.get(top["top_category"], top["top_category"]), top["confidence"])
        finally:
            if previous is None:
                os.environ.pop("HF_HUB_OFFLINE", None)
            else:
                os.environ["HF_HUB_OFFLINE"] = previous
        return out

    def vision_labels(self, frames: list[dict], ids: list[int]) -> tuple[dict[int, dict], float, list[str]]:
        if not ids:
            return {}, 0.0, []
        props = VISION_SCHEMA["properties"]
        prompt = (
            "Label this video frame for an editor. Reply with JSON only, exactly these keys:\n"
            + "\n".join(f'- "{k}": one of {props[k]["enum"]}' for k in ("shot_size", "camera_angle", "content"))
            + '\n- "has_text": true if readable text is on screen, else false'
        )
        items = [{"id": str(i), "task": "frame_labels", "prompt": prompt,
                  "images": [str(frames[i]["path"])], "json_schema": VISION_SCHEMA,
                  "temperature": 0, "max_tokens": 120} for i in ids]
        r = self.llm.execute({"operation": "batch", "items": items})
        labels, errors = {}, []
        for key, data in (r.data.get("results") or {}).items():
            if data and data.get("json"):
                labels[int(key)] = data["json"]
            else:
                errors.append(key)
        return labels, r.cost_usd or 0.0, errors

    def draft_hook(self, segments: list[dict], hook_end: float) -> tuple[Optional[dict], float, Optional[str]]:
        text = " ".join(str(s.get("text", "")) for s in segments if float(s.get("start", 0)) < hook_end)
        if not text.strip():
            return None, 0.0, "no transcript for the hook"
        prompt = (
            "Here is the opening narration of a YouTube video. Describe its hook as a reusable "
            "formula: 2-4 beats (what each beat does, not its content) and one sentence naming the "
            'formula. JSON: {"beats": ["..."], "formula": "..."}\n\n' + text[:3000]
        )
        r = self.llm.execute({"task": "hook_structure", "prompt": prompt, "temperature": 0})
        if not r.success:
            return None, r.cost_usd or 0.0, r.error
        return r.data.get("json"), r.cost_usd or 0.0, None

    @staticmethod
    def audio_samples(video: Path, rate: int = 8000):
        import numpy as np

        proc = subprocess.run([_ffmpeg(), "-v", "error", "-i", str(video), "-vn", "-ac", "1", "-ar", str(rate),
                               "-f", "s16le", "-"], capture_output=True, timeout=900)
        if proc.returncode != 0 or not proc.stdout:
            return np.zeros(0, dtype=np.float32)
        return np.frombuffer(proc.stdout, dtype=np.int16).astype(np.float32) / 32768.0

    @staticmethod
    def palette(paths: list[Path], n: int = 4) -> list[str]:
        from PIL import Image

        if not paths:
            return ["#000000"]
        strip = Image.new("RGB", (64 * len(paths), 36))
        for i, p in enumerate(paths):
            strip.paste(Image.open(p).convert("RGB").resize((64, 36)), (64 * i, 0))
        quant = strip.quantize(colors=n, method=Image.Quantize.MEDIANCUT)
        pal = quant.getpalette()[: n * 3]
        counts = sorted(quant.getcolors(), reverse=True)
        return ["#%02x%02x%02x" % tuple(pal[idx * 3: idx * 3 + 3]) for _, idx in counts[:n]]

    # -- operations ---------------------------------------------------------

    def _resolve_video(self, inputs: dict[str, Any], work: Path) -> Path:
        if inputs.get("input_path"):
            return Path(inputs["input_path"])
        if inputs.get("url"):
            from tools.analysis.video_downloader import VideoDownloader

            r = VideoDownloader().execute({"url": inputs["url"], "output_dir": str(work / "download")})
            if not r.success:
                raise RuntimeError(f"download failed: {r.error}")
            files = [Path(a) for a in r.artifacts if Path(a).suffix.lower() in {".mp4", ".mkv", ".webm", ".mov"}]
            if not files:
                raise RuntimeError("download produced no video file")
            return files[0]
        raise ValueError("input_path or url is required")

    def _extract(self, inputs: dict[str, Any]) -> ToolResult:
        from styles.edit_style_loader import save_edit_style

        started = time.time()
        name = inputs.get("name") or "learned-style"
        work = Path(inputs.get("work_dir") or REPO_ROOT / "projects" / "_reference" / name / "style_analysis")
        work.mkdir(parents=True, exist_ok=True)
        video = self._resolve_video(inputs, work)
        duration = probe_duration(video)
        notes: list[str] = []
        cost = 0.0

        shots = sorted(self.detect_shots(video, duration, float(inputs.get("chunk_seconds", 600)), work),
                       key=lambda s: s["start_seconds"])
        lengths = shot_lengths(shots)
        cut_times = [s["start_seconds"] for s in shots[1:]]
        pacing = section_pacing(shots, duration)

        segments: list[dict] = []
        if inputs.get("transcript_path"):
            raw = json.loads(Path(inputs["transcript_path"]).read_text(encoding="utf-8"))
            nt = raw.get("narration_transcript", raw) if isinstance(raw, dict) else raw
            segments = nt.get("segments", nt) if isinstance(nt, dict) else nt
            segments = [s for s in segments if float(s.get("start", 0)) < duration]
        else:
            notes.append("no transcript given: words per minute not measured")
        wpm = words_per_minute(segments, 0, duration) if segments else None

        samples = self.audio_samples(video)
        rate = 8000
        onsets = detect_onsets(samples, rate) if len(samples) else []
        sync = onset_sync(cut_times, onsets, duration=duration)

        frames = self.sample_frames(video, shots, work, int(inputs.get("max_frames", 40)))
        threshold = float(inputs.get("clip_confidence", 0.45))
        clip = self.clip_labels([f["path"] for f in frames])
        unsure: list[int] = []
        if clip is None:
            notes.append("local CLIP not available (not installed or weights not downloaded): "
                         "every sampled frame labelled by vision_bulk")
            unsure = list(range(len(frames)))
        else:
            for i, lab in enumerate(clip):
                frames[i]["labels"] = {g: v[0] for g, v in lab.items()}
                frames[i]["clip_confidence"] = {g: v[1] for g, v in lab.items()}
                if min(v[1] for v in lab.values()) < threshold:
                    unsure.append(i)
        vision_errors: list[str] = []
        if inputs.get("use_vision_bulk", True) and unsure:
            labels, vcost, vision_errors = self.vision_labels(frames, unsure)
            cost += vcost
            for i, lab in labels.items():
                frames[i]["labels"] = {"shot_size": lab["shot_size"], "camera_angle": lab["camera_angle"],
                                       "content": lab["content"]}
                frames[i]["has_text"] = lab["has_text"]
                frames[i]["labelled_by"] = "vision_bulk"
        elif unsure:
            notes.append(f"{len(unsure)} frames left unlabelled (vision_bulk disabled)")

        hook = None
        if inputs.get("draft_hook", True) and segments:
            hook, hcost, herr = self.draft_hook(segments, section_bounds(duration)["hook"][1])
            cost += hcost
            if herr:
                notes.append(f"hook draft failed: {herr}")

        def count(key):
            out: dict[str, int] = {}
            for f in frames:
                value = (f.get("labels") or {}).get(key) if key != "motion" else f["motion"]
                if value:
                    out[value] = out.get(value, 0) + 1
            return out

        text_share = (sum(1 for f in frames if f.get("has_text")) / len(frames)) if frames else 0.0
        asl = round(statistics.mean(lengths), 2) if lengths else duration
        sorted_len = sorted(lengths) or [duration]
        p = lambda q: sorted_len[min(len(sorted_len) - 1, int(q * len(sorted_len)))]  # noqa: E731
        hook_bounds = section_bounds(duration)["hook"]
        motion_counts = count("motion")
        card = {
            "name": name,
            "title": inputs.get("title") or name.replace("-", " ").title(),
            "description": "Learned from a reference video by edit_style_extractor. Measured pacing; "
                           "transitions, SFX and fonts are not measured and should be set by hand.",
            "source": {
                "kind": "learned",
                "reference": inputs.get("url") or str(video),
                "date": datetime.date.today().isoformat(),
                "measured": {
                    "duration_seconds": round(duration, 1), "shots": len(shots), "asl_seconds": asl,
                    "shot_length_range": [round(sorted_len[0], 2), round(sorted_len[-1], 2)],
                    "cuts_per_minute": round(len(cut_times) / (duration / 60), 1),
                    "words_per_minute": wpm, "onset_sync": sync,
                    "cut_rate_curve": cut_rate_curve(cut_times, duration),
                    "shot_size": count("shot_size"), "camera_angle": count("camera_angle"),
                    "content": count("content"), "motion": motion_counts,
                    "text_on_screen_share": round(text_share, 2),
                },
            },
            "pacing": {
                "sections": pacing,
                "words_per_minute": wpm or 150,
                **({"beat_sync_ratio": sync["ratio"]} if sync["ratio"] is not None else {}),
            },
            "hook_formula": {
                "duration_seconds": round(hook_bounds[1], 1),
                "beats": (hook or {}).get("beats") or ["not drafted: add the hook beats by hand"],
            },
            "transitions": [{"name": "hard_cut", "weight": 1.0,
                             "note": "detector sees cuts only; dissolves/wipes not classified"}],
            "camera_moves": weighted(motion_counts, "from frame differences inside each sampled shot"),
            "subtitles": {"style": "plain" if text_share >= 0.5 else "none", "words_per_card": [3, 7],
                          "position": "bottom"},
            "sfx_palette": [{"name": "not_measured", "weight": 0, "note": "listen to the reference and fill in"}],
            "music_energy_curve": energy_curve(samples),
            "pattern_interrupt_seconds": {"min": round(p(0.25), 1), "max": round(max(p(0.9), p(0.25) + 0.1), 1)},
            "color_type": {"palette": self.palette([f["path"] for f in frames][:12]), "fonts": ["Vazirmatn"]},
            "rtl_notes": RTL_NOTES,
        }
        if hook and hook.get("formula"):
            card["description"] += f" Hook (worker draft, agent to finalise): {hook['formula']}"

        editing_dir = Path(inputs["editing_dir"]) if inputs.get("editing_dir") else None
        card_path = save_edit_style(card, editing_dir=editing_dir, learned=True)
        report = {
            "card": str(card_path), "video": str(video), "duration_seconds": duration,
            "shots": shots, "frames": [{k: (str(v) if isinstance(v, Path) else v) for k, v in f.items()}
                                       for f in frames],
            "onsets": len(onsets), "vision_bulk_frames": len(unsure), "vision_errors": vision_errors,
            "hook_draft": hook, "hook_status": "draft_for_agent_review" if hook else None,
            "cost_usd": round(cost, 6), "notes": notes, "seconds": round(time.time() - started, 1),
        }
        (work / "report.json").write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
        return ToolResult(
            success=True,
            data={"card_path": str(card_path), "report_path": str(work / "report.json"),
                  "asl_seconds": asl, "shots": len(shots), "words_per_minute": wpm,
                  "cost_usd": round(cost, 6), "notes": notes},
            artifacts=[str(card_path), str(work / "report.json")],
            cost_usd=round(cost, 6),
        )

    def _compare(self, inputs: dict[str, Any]) -> ToolResult:
        from styles.edit_style_loader import load_edit_style

        card = load_edit_style(inputs["card"], Path(inputs["editing_dir"]) if inputs.get("editing_dir") else None)
        video = Path(inputs["input_path"])
        duration = probe_duration(video)
        work = Path(inputs.get("work_dir") or video.parent / ".style_compare")
        shots = sorted(self.detect_shots(video, duration, float(inputs.get("chunk_seconds", 600)), work),
                       key=lambda s: s["start_seconds"])
        lengths = shot_lengths(shots)
        measured: dict[str, Any] = {
            "asl_seconds": round(statistics.mean(lengths), 2) if lengths else round(duration, 2),
            "cuts_per_minute": round(max(len(shots) - 1, 0) / (duration / 60), 1),
            "longest_static_seconds": round(max(lengths), 2) if lengths else round(duration, 2),
        }
        if inputs.get("transcript_path"):
            raw = json.loads(Path(inputs["transcript_path"]).read_text(encoding="utf-8"))
            segs = raw.get("segments", raw) if isinstance(raw, dict) else raw
            measured["words_per_minute"] = words_per_minute(segs)
        if inputs.get("edit_decisions_path"):
            ed = json.loads(Path(inputs["edit_decisions_path"]).read_text(encoding="utf-8"))
            subs = ed.get("subtitles") or {}
            measured["subtitles_present"] = bool(subs.get("enabled", bool(subs)))
        result = compare_metrics(measured, card, float(inputs.get("tolerance", 0.25)))
        return ToolResult(success=True, data={"card": card["name"], "measured": measured, **result})

    def execute(self, inputs: dict[str, Any]) -> ToolResult:
        try:
            if inputs.get("operation", "extract") == "compare":
                return self._compare(inputs)
            return self._extract(inputs)
        except (ValueError, RuntimeError, FileNotFoundError, subprocess.SubprocessError) as exc:
            return ToolResult(success=False, error=f"{type(exc).__name__}: {exc}")
