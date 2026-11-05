"""Volume automation for a music bed: duck under the voice, swell in pauses.

The Samsung sample ran the bed at one level (0.18) with a single lift on the
punch; the voice then fought the music in every phrase and the pauses felt
empty. This tool turns the narration's speech segments into a volume curve:

- under speech: `under` (about 18-20 dB below the voice with the usual TTS level)
- pauses of at least `min_gap` s: back up to `gaps`; shorter ones stay ducked
  so the bed does not pump between words
- events: `drop` (silence before a key line), `set` (a level for a stretch,
  e.g. a lift on the punch), `fade_out` (end the bed, ideally on a beat)

Output is a list of (time, gain) keyframes. HyperFrames reads volume tweens
from the timeline, so `gsap_lines` writes them as `tl.to("#bgm", {volume})`
calls; `render` bakes the curve into a WAV for Remotion/FFmpeg paths.
Speech segments come from ffmpeg silencedetect (local, free).
"""

from __future__ import annotations

import re
import shutil
import subprocess
import wave
from pathlib import Path
from typing import Any, Iterable, Optional, Sequence

import numpy as np

from tools.base_tool import (
    BaseTool,
    Determinism,
    ExecutionMode,
    ResourceProfile,
    ToolResult,
    ToolStability,
    ToolTier,
)

STEP = 0.01  # curve resolution in seconds


def parse_silencedetect(stderr: str, duration: float) -> list[tuple[float, float]]:
    """Speech = everything between silences, from ffmpeg silencedetect output."""
    starts = [float(x) for x in re.findall(r"silence_start: (-?[\d.]+)", stderr)]
    ends = [float(x) for x in re.findall(r"silence_end: ([\d.]+)", stderr)]
    speech, cursor = [], 0.0
    for k, s in enumerate(starts):
        s = max(0.0, s)
        if s > cursor + 0.02:
            speech.append((round(cursor, 3), round(s, 3)))
        cursor = ends[k] if k < len(ends) else duration
    if cursor < duration - 0.02:
        speech.append((round(cursor, 3), round(duration, 3)))
    return speech


def speech_segments(path: Path, noise_db: float = -35.0, min_silence: float = 0.1,
                    offset: float = 0.0) -> list[tuple[float, float]]:
    ffmpeg = shutil.which("ffmpeg") or "ffmpeg"
    probe = subprocess.run([shutil.which("ffprobe") or "ffprobe", "-v", "error", "-show_entries",
                            "format=duration", "-of", "csv=p=0", str(path)],
                           capture_output=True, text=True, encoding="utf-8", timeout=60)
    duration = float(probe.stdout.strip() or 0)
    proc = subprocess.run([ffmpeg, "-hide_banner", "-nostats", "-i", str(path), "-af",
                           f"silencedetect=noise={noise_db}dB:d={min_silence}", "-f", "null", "-"],
                          capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=600)
    return [(round(a + offset, 3), round(b + offset, 3)) for a, b in parse_silencedetect(proc.stderr, duration)]


def merge_close(segments: Iterable[Sequence[float]], min_gap: float) -> list[tuple[float, float]]:
    out: list[list[float]] = []
    for a, b in sorted((float(a), float(b)) for a, b in segments):
        if out and a - out[-1][1] < min_gap:
            out[-1][1] = max(out[-1][1], b)
        else:
            out.append([a, b])
    return [(a, b) for a, b in out]


def _curve(speech, duration, under, gaps, attack, release, min_gap, fade_in, events) -> np.ndarray:
    t = np.arange(0, duration + STEP / 2, STEP)
    # A zero ramp means "instant": one curve step, not a division by zero.
    attack, release = max(float(attack), STEP), max(float(release), STEP)
    gain = np.full(len(t), float(gaps))
    for a, b in merge_close(speech, min_gap):
        down = np.clip((t - (a - attack)) / attack, 0, 1)
        up = np.clip(1 - (t - b) / release, 0, 1)
        depth = np.minimum(down, up)
        gain = np.minimum(gain, gaps - (gaps - under) * depth)
    if fade_in:
        gain *= np.clip(t / fade_in, 0, 1)
    for ev in events:
        kind = ev["kind"]
        if kind == "drop":
            fade = max(float(ev.get("fade", 0.15)), STEP)
            ramp = np.clip((ev["start"] + fade - t) / fade, 0, 1)
            inside = (t >= ev["start"]) & (t < ev["end"])
            gain = np.where(inside, gain * ramp, gain)
        elif kind == "set":
            inside = (t >= ev["start"]) & (t < ev["end"])
            gain = np.where(inside, float(ev["level"]), gain)
        elif kind == "fade_out":
            ramp = np.clip((ev["end"] - t) / max(ev["end"] - ev["start"], STEP), 0, 1)
            gain = np.where(t >= ev["start"], gain * ramp, gain)
        else:
            raise ValueError(f"unknown music event: {kind}")
    return gain


def _simplify(gain: np.ndarray, tolerance: float) -> list[int]:
    """Douglas-Peucker on the sampled curve: indices of the points to keep."""
    keep = {0, len(gain) - 1}
    stack = [(0, len(gain) - 1)]
    while stack:
        a, b = stack.pop()
        if b - a < 2:
            continue
        line = np.interp(np.arange(a, b + 1), [a, b], [gain[a], gain[b]])
        err = np.abs(gain[a:b + 1] - line)
        k = int(np.argmax(err))
        if err[k] > tolerance:
            keep.add(a + k)
            stack += [(a, a + k), (a + k, b)]
    return sorted(keep)


def duck_keyframes(speech: Sequence[Sequence[float]], duration: float, *, under: float = 0.14,
                   gaps: float = 0.24, attack: float = 0.08, release: float = 0.3,
                   min_gap: float = 0.45, fade_in: float = 0.3,
                   events: Sequence[dict[str, Any]] = (), tolerance: float = 0.003) -> list[tuple[float, float]]:
    """(time, gain) keyframes, linear between points, within `tolerance` of the curve."""
    if min_gap < attack + release:
        min_gap = attack + release
    gain = _curve(speech, duration, under, gaps, attack, release, min_gap, fade_in, events)
    return [(round(i * STEP, 3), round(float(gain[i]), 4)) for i in _simplify(gain, tolerance)]


def level_at(keyframes: Sequence[Sequence[float]], t: float) -> float:
    times = [k[0] for k in keyframes]
    return float(np.interp(t, times, [k[1] for k in keyframes]))


def gsap_lines(keyframes: Sequence[Sequence[float]], selector: str = "#bgm") -> list[str]:
    """Timeline calls for HyperFrames: a set at the start, then one linear
    tween per ramp (holds need no tween)."""
    t0, v0 = keyframes[0]
    lines = [f'tl.set("{selector}", {{ volume: {v0:g} }}, {t0:g});']
    for (a, va), (b, vb) in zip(keyframes, keyframes[1:]):
        if abs(vb - va) > 1e-4:
            lines.append(f'tl.to("{selector}", {{ volume: {vb:g}, duration: {b - a:.3f}, ease: "none" }}, {a:g});')
    return lines


def apply_envelope(samples: np.ndarray, rate: int, keyframes: Sequence[Sequence[float]],
                   start: float = 0.0) -> np.ndarray:
    """Multiply (frames, channels) samples that play from timeline time `start`."""
    t = start + np.arange(len(samples)) / rate
    env = np.interp(t, [k[0] for k in keyframes], [k[1] for k in keyframes], right=keyframes[-1][1])
    return samples * env[:, None] if samples.ndim == 2 else samples * env


def render(music: Path, keyframes: Sequence[Sequence[float]], out: Path, duration: float,
           media_start: float = 0.0, rate: int = 48000) -> Path:
    ffmpeg = shutil.which("ffmpeg") or "ffmpeg"
    proc = subprocess.run([ffmpeg, "-v", "error", "-ss", f"{media_start:.3f}", "-i", str(music),
                           "-t", f"{duration:.3f}", "-ac", "2", "-ar", str(rate), "-f", "f32le", "-"],
                          capture_output=True, timeout=600)
    if proc.returncode != 0:
        raise RuntimeError(proc.stderr.decode("utf-8", "replace")[-300:])
    samples = np.frombuffer(proc.stdout, dtype=np.float32).reshape(-1, 2)
    shaped = apply_envelope(samples, rate, keyframes)
    out.parent.mkdir(parents=True, exist_ok=True)
    with wave.open(str(out), "wb") as w:
        w.setnchannels(2)
        w.setsampwidth(2)
        w.setframerate(rate)
        w.writeframes((np.clip(shaped, -1, 1) * 32767).astype("<i2").tobytes())
    return out


def ducking_depth_db(keyframes: Sequence[Sequence[float]], speech: Sequence[Sequence[float]],
                     duration: float, min_gap: float = 0.45) -> Optional[float]:
    """How far the bed comes up in the real pauses (inner pauses of at least
    `min_gap`, peak level) over its usual level under speech (median, so a
    silence drop does not count), in dB. None when there is nothing to compare."""
    times, values = [k[0] for k in keyframes], [k[1] for k in keyframes]
    t = np.arange(0, duration, 0.02)
    gain = np.interp(t, times, values)
    talking = np.zeros(len(t), dtype=bool)
    for a, b in speech:
        talking |= (t >= a) & (t < b)
    merged = merge_close(speech, 0.0)
    pauses = [(b, a2) for (_, b), (a2, _) in zip(merged, merged[1:]) if a2 - b >= min_gap]
    if not talking.any() or not pauses:
        return None
    under = float(np.median(gain[talking]))
    peaks = [float(gain[(t >= a) & (t < b)].max()) for a, b in pauses]
    if under <= 0 or min(peaks) <= 0:
        return None
    return round(20 * np.log10(float(np.mean(peaks)) / under), 1)


class MusicDuck(BaseTool):
    name = "music_duck"
    version = "0.1.0"
    tier = ToolTier.CORE
    capability = "audio_processing"
    provider = "ffmpeg"
    stability = ToolStability.EXPERIMENTAL
    execution_mode = ExecutionMode.SYNC
    determinism = Determinism.DETERMINISTIC

    dependencies = ["cmd:ffmpeg", "python:numpy"]
    install_instructions = "Install FFmpeg: https://ffmpeg.org/download.html (numpy is in requirements.txt)"
    agent_skills = ["ffmpeg"]
    capabilities = ["music_ducking", "volume_automation"]
    best_for = [
        "ducking a music bed under narration with swells in the pauses",
        "silence drop before a key line, lift on a punch",
        "HyperFrames volume tweens or a baked WAV bed",
    ]
    input_schema = {
        "type": "object",
        "required": ["duration"],
        "properties": {
            "operation": {"type": "string", "enum": ["plan", "render"], "default": "plan"},
            "duration": {"type": "number"},
            "narration": {
                "type": "array",
                "description": "[{path, start}] clips on the timeline; speech found by silencedetect",
            },
            "speech": {"type": "array", "description": "[[start, end]] timeline speech, instead of narration"},
            "under": {"type": "number", "default": 0.14},
            "gaps": {"type": "number", "default": 0.24},
            "attack": {"type": "number", "default": 0.08},
            "release": {"type": "number", "default": 0.3},
            "min_gap": {"type": "number", "default": 0.45},
            "fade_in": {"type": "number", "default": 0.3},
            "events": {"type": "array", "description": "drop / set / fade_out, see module doc"},
            "selector": {"type": "string", "default": "#bgm"},
            "music_path": {"type": "string", "description": "render: the bed"},
            "media_start": {"type": "number", "default": 0},
            "output_path": {"type": "string", "description": "render: WAV out"},
        },
    }
    resource_profile = ResourceProfile(cpu_cores=1, ram_mb=256, vram_mb=0, disk_mb=100)
    side_effects = ["render writes a WAV"]

    def execute(self, inputs: dict[str, Any]) -> ToolResult:
        duration = float(inputs["duration"])
        try:
            speech = inputs.get("speech")
            if speech is None:
                speech = []
                for clip in inputs.get("narration", []):
                    speech += speech_segments(Path(clip["path"]), offset=float(clip.get("start", 0)))
            keys = duck_keyframes(
                speech, duration, under=float(inputs.get("under", 0.14)), gaps=float(inputs.get("gaps", 0.24)),
                attack=float(inputs.get("attack", 0.08)), release=float(inputs.get("release", 0.3)),
                min_gap=float(inputs.get("min_gap", 0.45)), fade_in=float(inputs.get("fade_in", 0.3)),
                events=inputs.get("events", []))
            data = {"speech": speech, "keyframes": keys,
                    "gsap": gsap_lines(keys, inputs.get("selector", "#bgm")),
                    "ducking_db": ducking_depth_db(keys, speech, duration)}
            artifacts = []
            if inputs.get("operation", "plan") == "render":
                out = render(Path(inputs["music_path"]), keys, Path(inputs["output_path"]), duration,
                             float(inputs.get("media_start", 0)))
                data["output"] = str(out)
                artifacts.append(str(out))
            return ToolResult(success=True, data=data, artifacts=artifacts)
        except (KeyError, ValueError, RuntimeError, subprocess.SubprocessError) as exc:
            return ToolResult(success=False, error=f"{type(exc).__name__}: {exc}")
