"""music_duck: speech parsing, the volume curve, GSAP output and the baked bed. No network."""

from __future__ import annotations

import shutil
import wave

import numpy as np
import pytest

from tools.audio.music_duck import (
    MusicDuck,
    apply_envelope,
    duck_keyframes,
    ducking_depth_db,
    gsap_lines,
    level_at,
    merge_close,
    parse_silencedetect,
    render,
)

needs_ffmpeg = pytest.mark.skipif(shutil.which("ffmpeg") is None, reason="needs ffmpeg")

SILENCE = """[silencedetect @ 0] silence_start: -0.002
[silencedetect @ 0] silence_end: 0.186 | silence_duration: 0.188
[silencedetect @ 0] silence_start: 2.571
[silencedetect @ 0] silence_end: 2.817 | silence_duration: 0.246
[silencedetect @ 0] silence_start: 6.308
"""


def test_speech_is_the_space_between_silences():
    assert parse_silencedetect(SILENCE, 6.6) == [(0.186, 2.571), (2.817, 6.308)]
    assert parse_silencedetect("", 3.0) == [(0.0, 3.0)]


def test_short_gaps_merge_so_the_bed_does_not_pump():
    assert merge_close([(0, 1), (1.2, 2), (3, 4)], 0.45) == [(0, 2), (3, 4)]


def test_curve_ducks_under_speech_and_rises_in_real_pauses():
    speech = [(0.2, 2.5), (2.7, 6.3), (7.0, 9.0)]
    keys = duck_keyframes(speech, 10.0, under=0.1, gaps=0.3, fade_in=0)
    assert level_at(keys, 1.0) == pytest.approx(0.1)
    assert level_at(keys, 2.6) == pytest.approx(0.1)  # 0.2 s pause stays ducked
    assert level_at(keys, 6.75) == pytest.approx(0.3, abs=0.01)  # 0.7 s pause swells
    assert level_at(keys, 9.6) == pytest.approx(0.3)
    assert level_at(keys, 6.95) < 0.3  # already ducking before the voice comes back
    assert ducking_depth_db(keys, speech, 10.0) > 6


def test_drop_set_and_fade_out_events():
    events = [{"kind": "drop", "start": 4.0, "end": 5.0},
              {"kind": "set", "start": 5.0, "end": 6.0, "level": 0.4},
              {"kind": "fade_out", "start": 7.0, "end": 8.0}]
    keys = duck_keyframes([], 9.0, under=0.1, gaps=0.2, fade_in=0, events=events)
    assert level_at(keys, 4.5) == 0
    assert level_at(keys, 5.5) == pytest.approx(0.4)
    assert level_at(keys, 7.5) == pytest.approx(0.1, abs=0.01)
    assert level_at(keys, 8.5) == 0
    with pytest.raises(ValueError):
        duck_keyframes([], 2.0, events=[{"kind": "wobble"}])


def test_keyframes_keep_only_corners():
    keys = duck_keyframes([(1.0, 3.0)], 5.0, under=0.1, gaps=0.3, fade_in=0)
    assert len(keys) <= 8
    times = [t for t, _ in keys]
    assert times == sorted(times) and times[0] == 0 and times[-1] == 5.0


def test_gsap_lines_are_linear_ramps_on_the_selector():
    lines = gsap_lines([(0, 0.0), (0.3, 0.2), (2.0, 0.2), (2.1, 0.1)], "#bgm")
    assert lines[0] == 'tl.set("#bgm", { volume: 0 }, 0);'
    assert lines[1] == 'tl.to("#bgm", { volume: 0.2, duration: 0.300, ease: "none" }, 0);'
    assert len(lines) == 3  # the hold needs no tween


def test_envelope_scales_samples_from_their_timeline_start():
    samples = np.ones((48000, 2), dtype=np.float32)
    out = apply_envelope(samples, 48000, [(0, 0.0), (2.0, 1.0)], start=1.0)
    assert out[0, 0] == pytest.approx(0.5)
    assert out[-1, 1] == pytest.approx(1.0, abs=1e-3)


@needs_ffmpeg
def test_render_bakes_the_curve(tmp_path):
    src = tmp_path / "tone.wav"
    t = np.arange(48000 * 2) / 48000
    with wave.open(str(src), "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(48000)
        w.writeframes((0.5 * np.sin(2 * np.pi * 220 * t) * 32767).astype("<i2").tobytes())
    out = render(src, [(0, 1.0), (1.0, 1.0), (1.01, 0.0)], tmp_path / "bed.wav", 2.0)
    with wave.open(str(out), "rb") as w:
        assert w.getnchannels() == 2
        pcm = np.frombuffer(w.readframes(w.getnframes()), dtype="<i2").reshape(-1, 2)
    assert np.abs(pcm[:40000]).max() > 10000
    assert np.abs(pcm[50000:]).max() == 0


def test_tool_plan_with_given_speech():
    r = MusicDuck().execute({"duration": 6.0, "speech": [[0.5, 2.0], [3.5, 5.0]], "fade_in": 0})
    assert r.success, r.error
    assert r.data["gsap"][0].startswith('tl.set("#bgm"')
    assert r.data["ducking_db"] > 3
