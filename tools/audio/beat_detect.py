"""Beat grid for a music bed, and helpers to cut on it.

Local and free: ffmpeg decodes, numpy does the rest (librosa is not
installed on the owner's laptop). Onsets are log-spectral flux, the tempo
comes from the onset autocorrelation with a prior around 120 BPM, and beats
are tracked with the dynamic-programming method of Ellis (2007). Downbeats
are a guess: the beat phase (in 4/4) with the strongest low-band onsets.

Operations:
- analyze: music file -> bpm, beats, downbeats (seconds into the file)
- snap: cut times -> nearest beat within a tolerance, never leaving the
  allowed window of each cut (e.g. the speech pause it sits in)
- align: music offset (data-media-start) that puts a downbeat on an anchor
  (the punch line) and as many cuts as possible on beats
"""

from __future__ import annotations

import bisect
import json
import shutil
import subprocess
from pathlib import Path
from typing import Any, Optional, Sequence

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

RATE = 22050
N_FFT = 1024
HOP = 256
FPS = RATE / HOP
# Spectral flux first rises in the frame whose window just reaches the onset,
# so frame start times run early by (N_FFT - HOP) samples (~35 ms, measured on
# click tracks at 99 and 120 BPM).
LATENCY = (N_FFT - HOP) / RATE


def decode_mono(path: Path, rate: int = RATE, start: float = 0.0,
                duration: Optional[float] = None) -> np.ndarray:
    cmd = [shutil.which("ffmpeg") or "ffmpeg", "-v", "error", "-ss", f"{start:.3f}", "-i", str(path)]
    if duration:
        cmd += ["-t", f"{duration:.3f}"]
    cmd += ["-vn", "-ac", "1", "-ar", str(rate), "-f", "f32le", "-"]
    proc = subprocess.run(cmd, capture_output=True, timeout=600)
    if proc.returncode != 0:
        raise RuntimeError(f"ffmpeg could not decode {path}: {proc.stderr.decode('utf-8', 'replace')[-300:]}")
    return np.frombuffer(proc.stdout, dtype=np.float32)


def onset_envelope(samples: np.ndarray, rate: int = RATE, max_hz: Optional[float] = None) -> np.ndarray:
    """Half-wave rectified log-spectral flux, one value per hop."""
    if len(samples) < N_FFT:
        samples = np.pad(samples, (0, N_FFT - len(samples)))
    frames = 1 + (len(samples) - N_FFT) // HOP
    window = np.hanning(N_FFT).astype(np.float32)
    bins = N_FFT // 2 + 1 if max_hz is None else max(2, int(max_hz / rate * N_FFT) + 1)
    out = np.zeros(frames, dtype=np.float64)
    prev = None
    for first in range(0, frames, 2048):
        idx = np.arange(N_FFT)[None, :] + HOP * np.arange(first, min(frames, first + 2048))[:, None]
        spec = np.log1p(100 * np.abs(np.fft.rfft(samples[idx] * window, axis=1))[:, :bins])
        if prev is not None:
            spec = np.vstack([prev, spec])
        flux = np.maximum(np.diff(spec, axis=0), 0).sum(axis=1)
        # Row k of flux is the change into frame first+k (first chunk: first+k+1).
        start = first if prev is not None else first + 1
        out[start:start + len(flux)] = flux
        prev = spec[-1:]
    return out


def estimate_tempo(env: np.ndarray, fps: float = FPS, bpm_range: tuple[float, float] = (60, 200),
                   prior_bpm: float = 120.0) -> float:
    x = env - env.mean()
    n = 1 << int(np.ceil(np.log2(2 * len(x))))
    spec = np.fft.rfft(x, n)
    ac = np.fft.irfft(spec * np.conj(spec), n)[: len(x)]
    lags = np.arange(1, len(ac))
    bpm = 60 * fps / lags
    keep = (bpm >= bpm_range[0]) & (bpm <= bpm_range[1])
    if not keep.any():
        return prior_bpm
    weight = np.exp(-0.5 * np.log2(bpm[keep] / prior_bpm) ** 2)
    score = ac[1:][keep] * weight
    k = int(np.argmax(score))
    lag = float(lags[keep][k])
    i = int(lags[keep][k])
    if 1 <= i < len(ac) - 1:
        a, b, c = ac[i - 1], ac[i], ac[i + 1]
        denom = a - 2 * b + c
        if denom:
            lag += 0.5 * (a - c) / denom
    return round(60 * fps / lag, 2)


def track_beats(env: np.ndarray, bpm: float, fps: float = FPS, tightness: float = 100.0) -> list[int]:
    """Beat frames by dynamic programming (Ellis 2007), strongest path to the end."""
    if not len(env) or env.max() <= 0:
        return []
    period = 60 * fps / bpm
    half = int(round(period))
    gauss = np.exp(-0.5 * (np.arange(-half, half + 1) * 32 / period) ** 2)
    local = np.convolve(env / (env.std() or 1.0), gauss, "same")
    offsets = np.arange(-int(round(2 * period)), -int(round(period / 2)) + 1)
    txcost = -tightness * np.log(-offsets / period) ** 2
    cum = local.copy()
    back = np.full(len(local), -1)
    for i in range(len(local)):
        z = i + offsets
        ok = z >= 0
        if not ok.any():
            continue
        cand = txcost[ok] + cum[z[ok]]
        k = int(np.argmax(cand))
        if cand[k] > 0:
            cum[i] = local[i] + cand[k]
            back[i] = z[ok][k]
    peaks = [i for i in range(1, len(cum) - 1) if cum[i] >= cum[i - 1] and cum[i] >= cum[i + 1]]
    if not peaks:
        return []
    floor = 0.5 * float(np.median(cum[peaks]))
    last = max(i for i in peaks if cum[i] >= floor)
    beats = [last]
    while back[beats[-1]] >= 0:
        beats.append(int(back[beats[-1]]))
    beats.reverse()
    # The path extrapolates beats into silence before the music starts and
    # after it ends; drop end beats with no real onset under them.
    def strength(b: int) -> float:
        return float(env[max(0, b - 2): b + 3].max())

    # Log-spectral flux has a noise floor well above zero, so measure from it
    # (click tracks: floor ~130, beats ~300, extrapolated beats ~150).
    floor = float(np.median(env))
    typical = float(np.median([strength(b) for b in beats]))
    cut = floor + 0.35 * (typical - floor)
    while beats and strength(beats[0]) < cut:
        beats.pop(0)
    while beats and strength(beats[-1]) < cut:
        beats.pop()
    return beats


def pick_downbeats(beat_frames: Sequence[int], low_env: np.ndarray, meter: int = 4) -> list[int]:
    if len(beat_frames) < meter:
        return list(beat_frames[:1])
    strength = [float(np.mean([low_env[f] for f in beat_frames[p::meter]])) for p in range(meter)]
    phase = int(np.argmax(strength))
    return list(beat_frames[phase::meter])


def analyze(path: Path, start: float = 0.0, duration: Optional[float] = None,
            bpm_range: tuple[float, float] = (60, 200)) -> dict[str, Any]:
    samples = decode_mono(path, start=start, duration=duration)
    env = onset_envelope(samples)
    bpm = estimate_tempo(env, bpm_range=bpm_range)
    frames = track_beats(env, bpm)
    downs = pick_downbeats(frames, onset_envelope(samples, max_hz=200))
    to_s = lambda f: round(start + f / FPS + LATENCY, 3)  # noqa: E731
    beats = [to_s(f) for f in frames]
    if len(beats) > 2:
        bpm = round(60 / float(np.median(np.diff(beats))), 2)
    return {"bpm": bpm, "beats": beats, "downbeats": [to_s(f) for f in downs],
            "duration": round(len(samples) / RATE, 3), "start": start}


def nearest(beats: Sequence[float], t: float) -> Optional[float]:
    if not beats:
        return None
    i = bisect.bisect_left(beats, t)
    near = [beats[j] for j in (i - 1, i) if 0 <= j < len(beats)]
    return min(near, key=lambda b: abs(b - t))


def snap_to_beats(times: Sequence[float], beats: Sequence[float], tolerance: float = 0.1,
                  windows: Optional[Sequence[Optional[tuple[float, float]]]] = None) -> list[dict[str, Any]]:
    """Move each time to its nearest beat if that is within `tolerance` and
    inside the time's window (lo, hi); otherwise keep it."""
    out = []
    for k, t in enumerate(times):
        lo, hi = (windows[k] if windows and windows[k] else (float("-inf"), float("inf")))
        beat = nearest(beats, t)
        moved = beat is not None and abs(beat - t) <= tolerance and lo <= beat <= hi
        out.append({"time": t, "snapped": round(beat, 3) if moved else t,
                    "delta": round(beat - t, 3) if moved else 0.0, "on_beat": moved,
                    "nearest_beat": beat})
    return out


def beat_ratio(times: Sequence[float], beats: Sequence[float], tolerance: float = 0.08) -> Optional[float]:
    if not times or not beats:
        return None
    hits = sum(1 for t in times if abs(nearest(beats, t) - t) <= tolerance)
    return round(hits / len(times), 3)


def best_offset(beats: Sequence[float], downbeats: Sequence[float], anchor: float,
                cuts: Sequence[float] = (), max_offset: float = 4.0, step: float = 0.005,
                tolerance: float = 0.08, anchor_tolerance: float = 0.03) -> dict[str, Any]:
    """Music offset o (seconds skipped into the file) so that a downbeat plays
    at timeline time `anchor` and most `cuts` fall on beats. Timeline time
    t plays music time t + o."""
    best = None
    for o in np.arange(0.0, max_offset + 1e-9, step):
        shifted = [b - o for b in beats]
        down = nearest([d - o for d in downbeats], anchor)
        if down is None or abs(down - anchor) > anchor_tolerance:
            continue
        on = sum(1 for c in cuts if abs(nearest(shifted, c) - c) <= tolerance)
        score = (on, -abs(down - anchor), -o)
        if best is None or score > best[0]:
            best = (score, round(float(o), 3), on)
    if best is None:
        return {"offset": None, "cuts_on_beat": 0, "note": f"no downbeat within {anchor_tolerance}s of {anchor}"}
    return {"offset": best[1], "cuts_on_beat": best[2], "cuts": len(cuts)}


class BeatDetect(BaseTool):
    name = "beat_detect"
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
    capabilities = ["beat_detection", "beat_snapping", "music_alignment"]
    best_for = [
        "beat grid of a music bed for beat-synced cuts",
        "snapping cut times to beats inside speech pauses",
        "choosing a music offset so a downbeat lands on the punch line",
    ]
    input_schema = {
        "type": "object",
        "properties": {
            "operation": {"type": "string", "enum": ["analyze", "snap", "align"], "default": "analyze"},
            "input_path": {"type": "string", "description": "analyze/align: the music file"},
            "start": {"type": "number", "default": 0},
            "duration": {"type": "number"},
            "bpm_range": {"type": "array", "items": {"type": "number"}, "default": [60, 200]},
            "beats": {"type": "array", "items": {"type": "number"}, "description": "snap: timeline beats"},
            "times": {"type": "array", "items": {"type": "number"}},
            "windows": {"type": "array", "description": "snap: [lo, hi] or null per time"},
            "tolerance": {"type": "number", "default": 0.1},
            "anchor": {"type": "number", "description": "align: timeline time that must get a downbeat"},
            "max_offset": {"type": "number", "default": 4.0},
            "output_path": {"type": "string", "description": "analyze: write the grid as JSON"},
        },
    }
    resource_profile = ResourceProfile(cpu_cores=1, ram_mb=512, vram_mb=0, disk_mb=10)
    side_effects = ["analyze writes a beat JSON when output_path is given"]

    def execute(self, inputs: dict[str, Any]) -> ToolResult:
        op = inputs.get("operation", "analyze")
        try:
            if op == "snap":
                snapped = snap_to_beats(inputs["times"], inputs["beats"], float(inputs.get("tolerance", 0.1)),
                                        inputs.get("windows"))
                return ToolResult(success=True, data={"snapped": snapped})
            grid = analyze(Path(inputs["input_path"]), float(inputs.get("start", 0)), inputs.get("duration"),
                           tuple(inputs.get("bpm_range", (60, 200))))
            if op == "align":
                grid["alignment"] = best_offset(grid["beats"], grid["downbeats"], float(inputs["anchor"]),
                                                inputs.get("times", []), float(inputs.get("max_offset", 4.0)),
                                                tolerance=float(inputs.get("tolerance", 0.08)))
            if inputs.get("output_path"):
                out = Path(inputs["output_path"])
                out.parent.mkdir(parents=True, exist_ok=True)
                out.write_text(json.dumps(grid, indent=2), encoding="utf-8")
            return ToolResult(success=True, data=grid,
                              artifacts=[inputs["output_path"]] if inputs.get("output_path") else [])
        except (KeyError, RuntimeError, subprocess.SubprocessError) as exc:
            return ToolResult(success=False, error=f"{type(exc).__name__}: {exc}")
