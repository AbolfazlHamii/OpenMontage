"""Pre-production cost and time estimate for Persian productions.

Reads prices from config/fa_pricing.yaml and a production plan from one of:
a scene_plan (+ optional script) artifact, a brief, or a small plan JSON:

    {"scenes": [{"id": "s1", "narration": "...", "images": 1}, ...],
     "mode": "final", "image_model": "gemini-3.1-flash-image", "resolution": "1K"}

Text work is priced at zero: in interactive mode the agent writes it, and
headless LLM costs are added by the LLM router once it exists. Rendering and
music from a library are local and free.
"""

from __future__ import annotations

import datetime
import json
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Optional

import yaml

from lib.parallel_runner import plan_makespan

REPO_ROOT = Path(__file__).resolve().parent.parent
PRICING_PATH = REPO_ROOT / "config" / "fa_pricing.yaml"

DEFAULTS = {
    "draft": {"image_model": "gemini-3.1-flash-lite-image", "resolution": "1K"},
    "final": {"image_model": "gemini-3.1-flash-image", "resolution": "2K"},
}
DEFAULT_TTS_MODEL = "gemini-3.8-flash-tts"
PERSIAN_LETTER = re.compile(r"[؀-ۿ]")
IMAGE_ASSET_TYPES = {"image", "still", "illustration", "photo", "background"}
GENERATED_SCENE_TYPES = {"broll", "animation", "generated", "diagram", "character_scene"}


def load_pricing(path: Path = PRICING_PATH, today: Optional[datetime.date] = None) -> dict[str, Any]:
    with open(path, encoding="utf-8") as f:
        table = yaml.safe_load(f)
    updated = datetime.date.fromisoformat(str(table["updated"]))
    age = ((today or datetime.date.today()) - updated).days
    table["age_days"] = age
    table["stale"] = age > int(table.get("max_age_days", 14))
    return table


@dataclass
class Line:
    stage: str
    provider: str
    model: str
    quantity: float
    unit: str
    cost_usd: float
    note: str = ""


@dataclass
class Estimate:
    mode: str
    lines: list[Line] = field(default_factory=list)
    narration_seconds: float = 0.0
    images: int = 0
    seconds_serial: float = 0.0
    seconds_parallel: float = 0.0
    warnings: list[str] = field(default_factory=list)

    @property
    def total_usd(self) -> float:
        return round(sum(l.cost_usd for l in self.lines), 4)

    def by(self, key: str) -> dict[str, float]:
        out: dict[str, float] = {}
        for line in self.lines:
            k = getattr(line, key)
            out[k] = round(out.get(k, 0.0) + line.cost_usd, 6)
        return out

    def to_dict(self) -> dict[str, Any]:
        return {
            "mode": self.mode,
            "total_usd": self.total_usd,
            "by_stage": self.by("stage"),
            "by_provider": self.by("provider"),
            "narration_seconds": round(self.narration_seconds, 1),
            "images": self.images,
            "generation_seconds_serial": round(self.seconds_serial, 1),
            "generation_seconds_parallel": round(self.seconds_parallel, 1),
            "lines": [vars(l) for l in self.lines],
            "warnings": self.warnings,
        }


def plan_from_scene_plan(scene_plan: dict[str, Any], script: Optional[dict[str, Any]] = None) -> dict[str, Any]:
    texts = {s["id"]: s.get("text", "") for s in (script or {}).get("sections", [])}
    scenes = []
    for scene in scene_plan.get("scenes", []):
        assets = scene.get("required_assets") or []
        images = sum(
            1 for a in assets
            if a.get("source") == "generate" and a.get("type", "").lower() in IMAGE_ASSET_TYPES
        )
        if not assets and scene.get("type") in GENERATED_SCENE_TYPES:
            images = 1
        scenes.append({
            "id": scene["id"],
            "images": images,
            "narration": texts.get(scene.get("script_section_id", ""), ""),
        })
    # Narration belongs to script sections; count each section once.
    seen = set()
    for scene, src in zip(scenes, scene_plan.get("scenes", [])):
        sid = src.get("script_section_id")
        if sid in seen:
            scene["narration"] = ""
        seen.add(sid)
    plan = {"scenes": scenes}
    if script and not any(s["narration"] for s in scenes):
        plan["narration_text"] = " ".join(texts.values())
    return plan


def plan_from_brief(brief: dict[str, Any], seconds_per_image: float) -> dict[str, Any]:
    duration = float(brief.get("target_duration_seconds", 60))
    return {
        "narration_seconds": duration,
        "scenes": [{"id": f"s{i+1}", "images": 1}
                   for i in range(max(1, round(duration / seconds_per_image)))],
    }


def narration_seconds(text: str, letters_per_second: float) -> float:
    return len(PERSIAN_LETTER.findall(text)) / letters_per_second


def estimate(plan: dict[str, Any], pricing: dict[str, Any], mode: Optional[str] = None,
             draft_rounds: int = 0) -> Estimate:
    """Cost of one pass at `mode`, plus `draft_rounds` draft passes over the images."""
    mode = mode or plan.get("mode", "final")
    a = pricing["assumptions"]
    est = Estimate(mode=mode)
    if pricing.get("stale"):
        est.warnings.append(
            f"prices are {pricing['age_days']} days old; run scripts/fa_pricing_update.py"
        )

    image_model = plan.get("image_model") or DEFAULTS[mode]["image_model"]
    resolution = plan.get("resolution") or DEFAULTS[mode]["resolution"]
    image_prices = pricing["images"]["avalai"]
    tts_model = plan.get("tts_model", DEFAULT_TTS_MODEL)
    tts = pricing["tts"]["avalai"][tts_model]

    durations: list[tuple[str, float]] = []
    scenes = plan.get("scenes", [])
    lines_text = [s.get("narration", "") for s in scenes if s.get("narration")]

    # Narration: one TTS call per line.
    if lines_text:
        seconds = [narration_seconds(t, a["persian_letters_per_second"]) for t in lines_text]
        in_tokens = sum(len(t) / 2 + a["tts_prompt_overhead_tokens"] for t in lines_text)
        calls = len(lines_text)
    elif plan.get("narration_text"):
        seconds = [narration_seconds(plan["narration_text"], a["persian_letters_per_second"])]
        in_tokens = len(plan["narration_text"]) / 2 + a["tts_prompt_overhead_tokens"]
        calls = 1
    elif plan.get("narration_seconds"):
        seconds = [float(plan["narration_seconds"])]
        in_tokens = seconds[0] * a["persian_letters_per_second"] / 2 + a["tts_prompt_overhead_tokens"]
        calls = max(1, round(seconds[0] / 8))
    else:
        seconds, in_tokens, calls = [], 0.0, 0
    if seconds:
        total = sum(seconds)
        out_tokens = total * a["tts_audio_tokens_per_second"]
        cost = (in_tokens * tts["input"] + out_tokens * tts["output"]) / 1_000_000
        est.narration_seconds = total
        est.lines.append(Line("narration", "avalai", tts_model, round(total, 1), "audio seconds",
                              round(cost, 6), f"{calls} TTS call(s)"))
        durations += [("avalai_tts", a["tts_seconds_per_line"])] * calls

    # Images.
    n_images = sum(int(s.get("images", 0)) for s in scenes)
    est.images = n_images
    if n_images:
        price = image_prices[image_model][resolution]
        est.lines.append(Line("images", "avalai", f"{image_model} {resolution}", n_images, "images",
                              round(price * n_images, 6), mode))
        durations += [("avalai_image", a["image_seconds_avalai"])] * n_images
        if draft_rounds:
            d = DEFAULTS["draft"]
            dprice = image_prices[d["image_model"]][d["resolution"]]
            est.lines.append(Line("images", "avalai", f"{d['image_model']} {d['resolution']}",
                                  n_images * draft_rounds, "images",
                                  round(dprice * n_images * draft_rounds, 6),
                                  f"{draft_rounds} draft round(s)"))
            durations += [("avalai_image", a["image_seconds_avalai"])] * n_images * draft_rounds

    est.lines.append(Line("render", "local", "hyperframes/ffmpeg", 1, "render", 0.0, "local"))
    est.lines.append(Line("text", "agent", "interactive session", 1, "run", 0.0,
                          "interactive mode: written by the agent, no API call"))

    est.seconds_serial = sum(d for _, d in durations)
    est.seconds_parallel = plan_makespan(durations, limits={"avalai_image": 3, "avalai_tts": 3})
    return est


def load_plan(args_plan: Optional[str] = None, scene_plan: Optional[str] = None,
              script: Optional[str] = None, brief: Optional[str] = None,
              seconds_per_image: float = 6) -> dict[str, Any]:
    def read(p):
        return json.loads(Path(p).read_text(encoding="utf-8"))

    if args_plan:
        return read(args_plan)
    if scene_plan:
        return plan_from_scene_plan(read(scene_plan), read(script) if script else None)
    if brief:
        return plan_from_brief(read(brief), seconds_per_image)
    raise ValueError("give --plan, --scene-plan or --brief")
