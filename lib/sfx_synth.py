"""Procedural sound effects: whoosh, swish, pop, hit, riser, fire crackle.

Made from seeded noise and sine sweeps with numpy only, so the files are our
own work with no licence attached, and the same seed gives the same file.
They fill the gaps in the bundled HyperFrames library (Pixabay licence):
a riser of any length, a paper swish for wipes, a crackle bed for fire.

    from lib.sfx_synth import render
    render("whoosh", Path("assets/sfx/whoosh_synth.wav"), duration=0.6)
"""

from __future__ import annotations

import wave
from pathlib import Path

import numpy as np

RATE = 48000
PEAK_DBFS = -3.0


def _rng(seed: int) -> np.random.Generator:
    return np.random.default_rng(seed)


def _lowpass(x: np.ndarray, cutoff, rate: int = RATE) -> np.ndarray:
    """One-pole low-pass; `cutoff` is a number or one value per sample (sweeps)."""
    fc = np.broadcast_to(np.asarray(cutoff, dtype=np.float64), x.shape)
    a = np.exp(-2 * np.pi * np.clip(fc, 10, rate / 2.2) / rate)
    y = np.empty_like(x)
    prev = 0.0
    for i in range(len(x)):
        prev = (1 - a[i]) * x[i] + a[i] * prev
        y[i] = prev
    return y


def _highpass(x: np.ndarray, cutoff, rate: int = RATE) -> np.ndarray:
    return x - _lowpass(x, cutoff, rate)


def _normalize(x: np.ndarray, peak_dbfs: float = PEAK_DBFS) -> np.ndarray:
    top = np.max(np.abs(x)) or 1.0
    return (x / top * 10 ** (peak_dbfs / 20)).astype(np.float32)


def _sweep(f0: float, f1: float, n: int, rate: int = RATE) -> np.ndarray:
    freq = np.geomspace(f0, f1, n)
    return np.sin(2 * np.pi * np.cumsum(freq) / rate)


def whoosh(duration: float = 0.6, peak: float = 0.62, seed: int = 1) -> np.ndarray:
    """Air rush that swells to `peak` (fraction of the length) and falls away."""
    n = int(duration * RATE)
    t = np.linspace(0, 1, n)
    rise = np.clip(t / peak, 0, 1) ** 2.2
    fall = np.exp(-np.clip(t - peak, 0, None) / max(1 - peak, 1e-3) * 4)
    env = np.where(t <= peak, rise, fall)
    cutoff = 400 + 3600 * env
    noise = _rng(seed).standard_normal(n)
    return _normalize(_highpass(_lowpass(noise, cutoff), 180) * env)


def swish(duration: float = 0.28, seed: int = 2) -> np.ndarray:
    """Short dry paper slide with a flutter; for wipes and cut-paper reveals."""
    n = int(duration * RATE)
    t = np.arange(n) / RATE
    env = (1 - np.exp(-t / 0.012)) * np.exp(-t / (duration * 0.35))
    flutter = 0.65 + 0.35 * np.sin(2 * np.pi * 31 * t + 1.3)
    noise = _rng(seed).standard_normal(n)
    return _normalize(_highpass(_lowpass(noise, 7000), 1800) * env * flutter)


def pop(duration: float = 0.16, seed: int = 3) -> np.ndarray:
    """Round bubble pop for text and pills landing (pitch drops 900 -> 380 Hz)."""
    n = int(duration * RATE)
    t = np.arange(n) / RATE
    tone = _sweep(900, 380, n) * (1 - np.exp(-t / 0.002)) * np.exp(-t / 0.035)
    click = _rng(seed).standard_normal(n) * np.exp(-t / 0.0015) * 0.25
    return _normalize(tone + click)


def hit(duration: float = 0.9, seed: int = 4) -> np.ndarray:
    """Low thump with a short noise crack on top; for punch-ins and smash cuts."""
    n = int(duration * RATE)
    t = np.arange(n) / RATE
    body = _sweep(70, 38, n) * np.exp(-t / 0.22)
    crack = _lowpass(_rng(seed).standard_normal(n), 1600) * np.exp(-t / 0.03) * 2.5
    return _normalize(np.tanh(1.8 * (body + crack)))


def riser(duration: float = 1.5, seed: int = 5) -> np.ndarray:
    """Noise and tone that build to the very end, then a 30 ms release."""
    n = int(duration * RATE)
    t = np.linspace(0, 1, n)
    env = (np.exp(3.2 * t) - 1) / (np.exp(3.2) - 1)
    tail = int(0.03 * RATE)
    env[-tail:] *= np.linspace(1, 0, tail)
    noise = _lowpass(_rng(seed).standard_normal(n), 300 + 6000 * t ** 1.5)
    tone = _sweep(180, 720, n) * 0.18
    return _normalize((_highpass(noise, 150) + tone) * env)


def crackle(duration: float = 3.0, density: float = 38.0, seed: int = 6) -> np.ndarray:
    """Fire bed: low rumble plus sparse crackles (`density` per second)."""
    n = int(duration * RATE)
    rng = _rng(seed)
    rumble = _lowpass(rng.standard_normal(n), 260) * 0.6
    sparks = np.zeros(n)
    count = rng.poisson(density * duration)
    for at, amp, length in zip(rng.integers(0, n, count), rng.uniform(0.2, 1.0, count),
                               rng.integers(int(0.002 * RATE), int(0.009 * RATE), count)):
        end = min(n, at + length)
        sparks[at:end] += amp * rng.standard_normal(end - at) * np.exp(-np.arange(end - at) / (length / 4))
    fade = int(min(0.25, duration / 4) * RATE)
    env = np.ones(n)
    env[:fade] = np.linspace(0, 1, fade)
    env[-fade:] = np.linspace(1, 0, fade)
    bed = rumble + _highpass(sparks, 1200)
    # Soft-clip the spark peaks first: peak-normalized, the sparse sparks left
    # the bed at -35 dBFS RMS and it vanished under the music in the mix.
    return _normalize(np.tanh(3 * bed / np.max(np.abs(bed))) * env)


SYNTHS = {"whoosh": whoosh, "swish": swish, "pop": pop, "hit": hit, "riser": riser, "crackle": crackle}


def write_wav(path: Path, samples: np.ndarray, rate: int = RATE) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    pcm = (np.clip(samples, -1, 1) * 32767).astype("<i2")
    with wave.open(str(path), "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(rate)
        w.writeframes(pcm.tobytes())
    return path


def peak_time(samples: np.ndarray, rate: int = RATE, window: float = 0.01, within_db: float = 1.5) -> float:
    """When the sound first reaches full strength (a 10 ms window within
    `within_db` of the loudest): the moment that should land on the cut.
    For a sustained boom that is its attack, not wherever the maximum
    happens to fall in the sustain."""
    hop = max(1, int(window * rate))
    frames = len(samples) // hop
    if frames == 0:
        return 0.0
    rms = np.sqrt(np.mean(samples[: frames * hop].reshape(frames, hop).astype(np.float64) ** 2, axis=1))
    first = int(np.argmax(rms >= rms.max() * 10 ** (-within_db / 20)))
    return round((first + 0.5) * hop / rate, 3)


def render(name: str, path: Path, **kwargs) -> dict:
    samples = SYNTHS[name](**kwargs)
    write_wav(path, samples)
    return {"file": path.name, "duration": round(len(samples) / RATE, 3), "peak_s": peak_time(samples),
            "source": f"lib/sfx_synth.py {name} {kwargs}".strip(), "licence": "own work (procedural)"}
