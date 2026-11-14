"""Lay sound effects on an edit: whoosh on cuts, hit on punches, pop on text.

Input is a list of edit events (`at`, `sfx`, optional `priority`, `volume`,
`lead`, `duration`) — from a scene plan, from `fa_edit_pass`, or read out of
a HyperFrames workspace by `events_from_hyperframes` (scene starts on track
0 are cuts; any element with `data-sfx` is a mark; emphasis runs written by
`word_captions`, class `em` with `data-ws`, are pops).

Each cue is placed so the sound's loudest moment (`peak_s` in the library
manifest) lands on the event, the way an editor lines up a whoosh. Beds
(`lead`, e.g. fire crackle that starts before its picture) start `lead` s
early instead — a J-cut on sound. Density rules: at most
`max_per_minute` cues and `min_gap` s between peaks; lower-priority cues
are dropped first (hit/explicit > cut > emphasis). SFX that land under
speech are turned down (`under_speech`, about -3 dB).

Outputs: cue list, HyperFrames `<audio>` tags (one track per overlapping
cue, so `hyperframes lint` stays clean), or an FFmpeg-mixed stem.
"""

from __future__ import annotations

import json
import shutil
import subprocess
from html.parser import HTMLParser
from pathlib import Path
from typing import Any, Optional, Sequence

from tools.base_tool import (
    BaseTool,
    Determinism,
    ExecutionMode,
    ResourceProfile,
    ToolResult,
    ToolStability,
    ToolTier,
)

# Default level per sound family (HyperFrames data-volume, 0-1); SFX sit
# under the voice. Names match the library keys or their prefix.
VOLUME = {"whoosh": 0.32, "swish": 0.3, "pop": 0.26, "hit": 0.5, "impact": 0.5, "riser": 0.28,
          "crackle": 0.3, "click": 0.22}
PRIORITY = {"mark": 3, "cut": 2, "emphasis": 1}


def load_library(folder: Path) -> dict[str, dict[str, Any]]:
    """`library.json` in the SFX folder: {name: {file, duration, peak_s, licence, ...}}."""
    data = json.loads((folder / "library.json").read_text(encoding="utf-8"))
    return data.get("files", data)


def _family(name: str) -> str:
    return next((k for k in VOLUME if name.startswith(k)), name)


class _Collector(HTMLParser):
    def __init__(self) -> None:
        super().__init__()
        self.tags: list[tuple[str, dict[str, str]]] = []

    def handle_starttag(self, tag, attrs):
        self.tags.append((tag, {k: v or "" for k, v in attrs}))


def events_from_hyperframes(html: str, cut_sfx: str = "whoosh", emphasis_sfx: Optional[str] = "pop") -> list[dict]:
    parser = _Collector()
    parser.feed(html)
    events = []
    for tag, a in parser.tags:
        classes = a.get("class", "").split()
        if "data-sfx" in a:
            if a["data-sfx"] in ("", "none"):
                continue
            at = a.get("data-sfx-at") or a.get("data-start")
            if at is None:
                continue
            ev = {"at": float(at), "sfx": a["data-sfx"], "kind": "mark", "source": a.get("id", tag)}
            for key, field in (("data-sfx-lead", "lead"), ("data-sfx-dur", "duration"), ("data-sfx-volume", "volume")):
                if key in a:
                    ev[field] = float(a[key])
            events.append(ev)
        elif tag != "audio" and a.get("data-track-index") == "0" and "data-start" in a:
            start = float(a["data-start"])
            if start > 0:
                events.append({"at": start, "sfx": cut_sfx, "kind": "cut", "source": a.get("id", tag)})
        elif emphasis_sfx and "em" in classes and "data-ws" in a:
            events.append({"at": float(a["data-ws"]), "sfx": emphasis_sfx, "kind": "emphasis",
                           "source": a.get("id", "word")})
    return sorted(events, key=lambda e: e["at"])


def _inside(t: float, spans: Sequence[Sequence[float]]) -> bool:
    return any(a <= t < b for a, b in spans)


def plan_cues(events: Sequence[dict], library: dict[str, dict], *, speech: Sequence[Sequence[float]] = (),
              max_per_minute: float = 36.0, min_gap: float = 0.3, under_speech: float = 0.7,
              duration: Optional[float] = None) -> dict[str, Any]:
    """Return {"cues": [...], "dropped": [...]} with times in seconds."""
    candidates, dropped = [], []
    for ev in events:
        name = ev.get("sfx")
        if not name:
            continue
        if name not in library:
            dropped.append({**ev, "reason": f"no '{name}' in the library"})
            continue
        item = library[name]
        length = float(ev["duration"] if ev.get("duration") is not None else item["duration"])
        offset = float(ev["lead"]) if "lead" in ev else float(item.get("peak_s", 0))
        start = ev["at"] - offset
        media_start = 0.0
        if start < 0:
            media_start, start = -start, 0.0
            length -= media_start
        if duration is not None:
            length = min(length, duration - start)
        if length <= 0.02:
            dropped.append({**ev, "reason": "falls outside the video"})
            continue
        volume = float(ev["volume"] if ev.get("volume") is not None else VOLUME.get(_family(name), 0.3))
        if "lead" not in ev and _inside(ev["at"], speech):
            volume *= under_speech
        candidates.append({"sfx": name, "file": item["file"], "at": round(ev["at"], 3), "start": round(start, 3),
                           "duration": round(length, 3), "media_start": round(media_start, 3),
                           "volume": round(volume, 3), "kind": ev.get("kind", "mark"),
                           "priority": ev.get("priority", PRIORITY.get(ev.get("kind", "mark"), 1)),
                           "bed": "lead" in ev, "source": ev.get("source")})

    kept: list[dict] = []
    for cue in sorted(candidates, key=lambda c: (-c["priority"], c["at"])):
        clash = next((k for k in kept if not k["bed"] and not cue["bed"] and abs(k["at"] - cue["at"]) < min_gap), None)
        if clash:
            dropped.append({**cue, "reason": f"within {min_gap}s of {clash['sfx']} at {clash['at']}"})
        else:
            kept.append(cue)
    kept.sort(key=lambda c: c["at"])
    accents = [c for c in kept if not c["bed"]]
    limit = max(1, int(max_per_minute * duration / 60)) if duration else len(accents)
    while len(accents) > limit:
        worst = min(accents, key=lambda c: (c["priority"], -c["at"]))
        accents.remove(worst)
        kept.remove(worst)
        dropped.append({**worst, "reason": f"over {max_per_minute:g} per minute"})
    return {"cues": assign_tracks(kept), "dropped": dropped}


def assign_tracks(cues: list[dict], first: int = 20) -> list[dict]:
    ends: list[float] = []
    for cue in sorted(cues, key=lambda c: c["start"]):
        for i, end in enumerate(ends):
            if end <= cue["start"] + 1e-6:
                ends[i] = cue["start"] + cue["duration"]
                cue["track"] = first + i
                break
        else:
            ends.append(cue["start"] + cue["duration"])
            cue["track"] = first + len(ends) - 1
    return cues


def audio_tags(cues: Sequence[dict], src_dir: str = "assets/sfx", id_prefix: str = "sfx") -> str:
    lines = []
    for i, c in enumerate(cues):
        media = f' data-media-start="{c["media_start"]:g}"' if c.get("media_start") else ""
        lines.append(f'<audio id="{id_prefix}-{i}" src="{src_dir}/{c["file"]}" data-start="{c["start"]:g}" '
                     f'data-duration="{c["duration"]:g}"{media} data-track-index="{c["track"]}" '
                     f'data-volume="{c["volume"]:g}"></audio>')
    return "\n".join(lines)


def render_stem(cues: Sequence[dict], folder: Path, out: Path, duration: float, rate: int = 48000) -> Path:
    """Mix every cue into one WAV (for runtimes without <audio> clips).

    Each sound file is decoded once and the cues are summed in memory: one
    ffmpeg input per cue overflows the Windows command line on a long video
    (a 14-minute cut has a few hundred cues)."""
    import wave

    import numpy as np

    ffmpeg = shutil.which("ffmpeg") or "ffmpeg"
    decoded: dict[str, np.ndarray] = {}
    for name in {c["file"] for c in cues}:
        proc = subprocess.run([ffmpeg, "-v", "error", "-i", str(folder / name), "-ac", "2", "-ar", str(rate),
                               "-f", "f32le", "-"], capture_output=True, timeout=120)
        if proc.returncode != 0:
            raise RuntimeError(proc.stderr.decode("utf-8", "replace")[-400:])
        decoded[name] = np.frombuffer(proc.stdout, dtype=np.float32).reshape(-1, 2)
    bed = np.zeros((int(round(duration * rate)), 2), dtype=np.float32)
    for c in cues:
        sound = decoded[c["file"]]
        a = int(round(c["media_start"] * rate))
        piece = sound[a:a + int(round(c["duration"] * rate))] * float(c["volume"])
        at = int(round(c["start"] * rate))
        piece = piece[:max(0, len(bed) - at)]
        bed[at:at + len(piece)] += piece
    out.parent.mkdir(parents=True, exist_ok=True)
    with wave.open(str(out), "wb") as w:
        w.setnchannels(2)
        w.setsampwidth(2)
        w.setframerate(rate)
        w.writeframes((np.clip(bed, -1, 1) * 32767).astype("<i2").tobytes())
    return out


class SfxPlacer(BaseTool):
    name = "sfx_placer"
    version = "0.1.0"
    tier = ToolTier.CORE
    capability = "audio_processing"
    provider = "openmontage"
    stability = ToolStability.EXPERIMENTAL
    execution_mode = ExecutionMode.SYNC
    determinism = Determinism.DETERMINISTIC

    dependencies = ["cmd:ffmpeg"]
    install_instructions = "Install FFmpeg: https://ffmpeg.org/download.html (only render_stem needs it)"
    agent_skills = ["ffmpeg", "hyperframes-media"]
    capabilities = ["sfx_placement"]
    best_for = [
        "whoosh/hit/pop cues placed on cuts, punches and caption pops",
        "SFX density and spacing rules before render",
        "HyperFrames <audio> tags or one mixed SFX stem",
    ]
    input_schema = {
        "type": "object",
        "required": ["library_dir"],
        "properties": {
            "operation": {"type": "string", "enum": ["plan", "render_stem"], "default": "plan"},
            "library_dir": {"type": "string", "description": "folder with library.json and the files"},
            "events": {"type": "array", "description": "[{at, sfx, kind?, priority?, volume?, lead?, duration?}]"},
            "workspace_html": {"type": "string", "description": "read events from this HyperFrames index.html"},
            "speech": {"type": "array", "description": "[[start, end]] narration on the timeline"},
            "duration": {"type": "number"},
            "max_per_minute": {"type": "number", "default": 36},
            "min_gap": {"type": "number", "default": 0.3},
            "src_dir": {"type": "string", "default": "assets/sfx"},
            "output_path": {"type": "string", "description": "render_stem: WAV out; plan: cue JSON out"},
        },
    }
    resource_profile = ResourceProfile(cpu_cores=1, ram_mb=256, vram_mb=0, disk_mb=50)
    side_effects = ["writes a cue JSON or a WAV stem when output_path is given"]

    def execute(self, inputs: dict[str, Any]) -> ToolResult:
        folder = Path(inputs["library_dir"])
        try:
            library = load_library(folder)
            events = list(inputs.get("events") or [])
            if inputs.get("workspace_html"):
                events += events_from_hyperframes(Path(inputs["workspace_html"]).read_text(encoding="utf-8"))
            plan = plan_cues(events, library, speech=inputs.get("speech", []),
                             max_per_minute=float(inputs.get("max_per_minute", 36)),
                             min_gap=float(inputs.get("min_gap", 0.3)), duration=inputs.get("duration"))
            plan["audio_tags"] = audio_tags(plan["cues"], inputs.get("src_dir", "assets/sfx"))
            artifacts = []
            out = inputs.get("output_path")
            if inputs.get("operation", "plan") == "render_stem":
                render_stem(plan["cues"], folder, Path(out), float(inputs["duration"]))
                artifacts.append(out)
            elif out:
                Path(out).parent.mkdir(parents=True, exist_ok=True)
                Path(out).write_text(json.dumps(plan, ensure_ascii=False, indent=2), encoding="utf-8")
                artifacts.append(out)
            return ToolResult(success=True, data=plan, artifacts=artifacts)
        except (KeyError, ValueError, FileNotFoundError, RuntimeError, subprocess.SubprocessError) as exc:
            return ToolResult(success=False, error=f"{type(exc).__name__}: {exc}")
