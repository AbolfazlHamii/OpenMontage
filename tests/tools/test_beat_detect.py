"""beat_detect on synthetic click tracks (ffmpeg decodes; no network, no paid calls)."""

from __future__ import annotations

import shutil
import wave

import numpy as np
import pytest

from tools.audio.beat_detect import (
    BeatDetect,
    analyze,
    beat_ratio,
    best_offset,
    nearest,
    snap_to_beats,
)

needs_ffmpeg = pytest.mark.skipif(shutil.which("ffmpeg") is None, reason="needs ffmpeg")
RATE = 22050


def click_track(path, bpm, seconds=20.0, start=0.5):
    """Accented 4/4 clicks over light noise; returns the true beat times."""
    x = np.random.default_rng(0).normal(0, 0.01, int(RATE * seconds)).astype(np.float32)
    times = np.arange(start, seconds, 60 / bpm)
    tail = np.arange(300)
    for k, t in enumerate(times):
        i = int(t * RATE)
        freq, amp = (150, 1.0) if k % 4 == 0 else (1000, 0.6)
        x[i:i + 300] += amp * np.sin(2 * np.pi * freq * tail / RATE) * np.exp(-tail / 60)
    with wave.open(str(path), "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(RATE)
        w.writeframes((np.clip(x, -1, 1) * 32767).astype("<i2").tobytes())
    return times


@needs_ffmpeg
@pytest.mark.parametrize("bpm", [80, 120, 128])
def test_tempo_and_beat_times_on_click_tracks(tmp_path, bpm):
    truth = click_track(tmp_path / "c.wav", bpm)
    grid = analyze(tmp_path / "c.wav")
    assert grid["bpm"] == pytest.approx(bpm, rel=0.02)
    errors = [min(abs(b - t) for t in truth) for b in grid["beats"]]
    # Within the ±80 ms window that beat-synced cuts use, with margin; no
    # beats invented before the first click or after the last one.
    assert max(errors) < 0.03
    assert len(grid["beats"]) >= 0.9 * len(truth)
    assert grid["beats"][0] >= truth[0] - 0.03 and grid["beats"][-1] <= truth[-1] + 0.03


@needs_ffmpeg
def test_downbeats_follow_the_accent(tmp_path):
    truth = click_track(tmp_path / "c.wav", 120)
    grid = analyze(tmp_path / "c.wav")
    accented = truth[::4]
    hits = [min(abs(d - a) for a in accented) < 0.03 for d in grid["downbeats"]]
    assert sum(hits) >= 0.8 * len(hits)


@needs_ffmpeg
def test_tool_analyze_writes_grid_and_aligns(tmp_path):
    click_track(tmp_path / "c.wav", 100)
    out = tmp_path / "grid.json"
    r = BeatDetect().execute({"operation": "align", "input_path": str(tmp_path / "c.wav"),
                              "anchor": 5.0, "times": [2.0, 3.2], "output_path": str(out)})
    assert r.success, r.error
    assert out.exists() and "alignment" in r.data


def test_snap_and_ratio_are_pure():
    beats = [0.5, 1.0, 1.5, 2.0]
    assert nearest(beats, 1.2) == 1.0
    assert nearest([], 1.0) is None
    snapped = snap_to_beats([0.97, 1.31, 1.92, 1.95], beats, tolerance=0.1,
                            windows=[None, None, None, (1.9, 1.98)])
    assert [s["snapped"] for s in snapped] == [1.0, 1.31, 2.0, 1.95]
    assert [s["on_beat"] for s in snapped] == [True, False, True, False]  # last: beat outside its pause
    assert beat_ratio([1.0, 1.31, 2.05], beats, tolerance=0.08) == pytest.approx(0.667)
    aligned = best_offset([0.5, 1.0, 1.5, 2.0, 2.5, 3.0], [0.5, 2.5], anchor=1.5, max_offset=2.0)
    assert aligned is not None


def test_missing_file_is_a_clean_failure(tmp_path):
    r = BeatDetect().execute({"input_path": str(tmp_path / "nope.mp3")})
    assert not r.success
