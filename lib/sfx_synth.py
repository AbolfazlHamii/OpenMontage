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


def _room(dry: np.ndarray, seconds: float, seed: int) -> np.ndarray:
    """Dry sound in a hard-walled yard: a slap echo off the far wall and a
    darkening noise tail (FFT convolution with a decaying-noise impulse)."""
    n_ir = int(seconds * RATE)
    t = np.arange(n_ir) / RATE
    ir = _lowpass(_rng(seed).standard_normal(n_ir), 2600) * np.exp(-t / (seconds / 5))
    ir[0] = 0.0
    size = len(dry) + n_ir
    wet = np.fft.irfft(np.fft.rfft(dry, size) * np.fft.rfft(ir, size), size)
    wet *= 0.45 * np.max(np.abs(dry)) / (np.max(np.abs(wet)) or 1.0)
    out = np.concatenate([dry, np.zeros(n_ir)]) + wet
    slap = int(0.11 * RATE)
    out[slap:] += 0.3 * _lowpass(out[:-slap], 3000)
    return out


def gunshot(shots: int = 1, gaps: tuple = (0.42, 0.36), seed: int = 7) -> np.ndarray:
    """Pistol shots: a hard broadband crack, a short body and a low thump,
    soft-clipped, then the yard's echo. Several shots come at uneven gaps,
    the later ones a little weaker, like a hand firing again."""
    rng = _rng(seed)
    starts = [0.0]
    for i in range(shots - 1):
        starts.append(starts[-1] + gaps[i % len(gaps)])
    n = int((starts[-1] + 0.35) * RATE)
    dry = np.zeros(n)
    for i, at in enumerate(starts):
        m = int(0.35 * RATE)
        t = np.arange(m) / RATE
        noise = rng.standard_normal(m)
        crack = _highpass(noise, 900) * np.exp(-t / 0.006) * 3.0
        body = _lowpass(noise, 3200) * (1 - np.exp(-t / 0.0004)) * np.exp(-t / 0.045) * 1.6
        thump = _sweep(110, 42, m) * np.exp(-t / 0.08) * 1.2
        shot = np.tanh(2.4 * (crack + body + thump)) * (0.92 ** i) * rng.uniform(0.9, 1.0)
        a = int(at * RATE)
        dry[a:a + m] += shot[: n - a]
    return _normalize(_room(dry, 1.1, seed + 100))


def typing(duration: float = 1.0, step: float = 0.045, seed: int = 8) -> np.ndarray:
    """Typewriter keys at `step` seconds apart, each a dry clack with a small
    metallic ring; uneven strength and timing so it does not sound like a clock."""
    rng = _rng(seed)
    n = int((duration + 0.1) * RATE)
    out = np.zeros(n)
    m = int(0.04 * RATE)
    t = np.arange(m) / RATE
    at = 0.0
    while at < duration:
        noise = rng.standard_normal(m)
        clack = _highpass(noise, 2200) * np.exp(-t / 0.004) + np.sin(2 * np.pi * rng.uniform(2400, 3100) * t) * np.exp(-t / 0.012) * 0.25
        a = int(at * RATE)
        out[a:a + m] += clack[: n - a] * rng.uniform(0.55, 1.0)
        at += step * rng.uniform(0.75, 1.3)
    return _normalize(out)


SYNTHS = {"whoosh": whoosh, "swish": swish, "pop": pop, "hit": hit, "riser": riser, "crackle": crackle,
          "gunshot": gunshot, "typing": typing}


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
