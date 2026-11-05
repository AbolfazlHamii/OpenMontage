"""sfx_placer: events from a workspace, peak placement, density rules, tags, stem. No network."""

from __future__ import annotations

import json
import shutil
import wave

import numpy as np
import pytest

from tools.audio.sfx_placer import (
    SfxPlacer,
    assign_tracks,
    audio_tags,
    events_from_hyperframes,
    plan_cues,
    render_stem,
)

needs_ffmpeg = pytest.mark.skipif(shutil.which("ffmpeg") is None, reason="needs ffmpeg")

LIB = {
    "whoosh": {"file": "whoosh.wav", "duration": 0.6, "peak_s": 0.2},
    "hit": {"file": "hit.wav", "duration": 0.9, "peak_s": 0.01},
    "pop": {"file": "pop.wav", "duration": 0.2, "peak_s": 0.01},
    "crackle": {"file": "crackle.wav", "duration": 9.0, "peak_s": 1.0},
}

HTML = """<div id="root">
<section id="scene-a" class="clip scene" data-start="0" data-duration="2.7" data-track-index="0"></section>
<section id="scene-b" class="clip scene" data-start="2.7" data-duration="4" data-track-index="0"></section>
<div id="fx" class="clip" data-start="0" data-duration="15" data-track-index="1"></div>
<i id="punch" data-sfx="hit" data-sfx-at="5.5"></i>
<i id="quiet" data-sfx="none" data-sfx-at="6"></i>
<i id="fire" data-sfx="crackle" data-sfx-at="6.7" data-sfx-lead="0.5" data-sfx-dur="3"></i>
<span class="em key" data-ws="1.78" data-we="2.5"><span class="w" data-ws="1.78" data-we="2.5">سامسونگه</span></span>
<audio id="vo" src="a.wav" data-start="0" data-track-index="0"></audio>
</div>"""


def test_events_from_a_hyperframes_workspace():
    events = events_from_hyperframes(HTML)
    assert [(e["at"], e["sfx"], e["kind"]) for e in events] == [
        (1.78, "pop", "emphasis"), (2.7, "whoosh", "cut"), (5.5, "hit", "mark"), (6.7, "crackle", "mark")]
    fire = events[-1]
    assert fire["lead"] == 0.5 and fire["duration"] == 3.0


def test_peak_lands_on_the_event_and_early_cues_trim_the_file():
    plan = plan_cues([{"at": 2.7, "sfx": "whoosh", "kind": "cut"}, {"at": 0.05, "sfx": "whoosh", "kind": "cut"}], LIB)
    late, early = sorted(plan["cues"], key=lambda c: -c["at"])
    assert late["start"] == pytest.approx(2.5)
    assert early["start"] == 0 and early["media_start"] == pytest.approx(0.15)
    assert early["duration"] == pytest.approx(0.45)


def test_bed_with_lead_starts_before_its_picture():
    plan = plan_cues([{"at": 6.7, "sfx": "crackle", "lead": 0.5, "duration": 3.0}], LIB)
    cue = plan["cues"][0]
    assert cue["start"] == pytest.approx(6.2) and cue["duration"] == 3.0 and cue["bed"]


def test_min_gap_keeps_the_higher_priority_cue():
    plan = plan_cues([{"at": 5.5, "sfx": "pop", "kind": "emphasis"}, {"at": 5.6, "sfx": "hit", "kind": "mark"}],
                     LIB, min_gap=0.3)
    assert [c["sfx"] for c in plan["cues"]] == ["hit"]
    assert "within 0.3s" in plan["dropped"][0]["reason"]


def test_density_cap_drops_emphasis_first():
    events = [{"at": t, "sfx": "pop", "kind": "emphasis"} for t in np.arange(0.5, 10, 0.5)]
    events.append({"at": 5.25, "sfx": "whoosh", "kind": "cut"})
    plan = plan_cues(events, LIB, duration=10.0, max_per_minute=30)
    assert len(plan["cues"]) == 5
    assert any(c["sfx"] == "whoosh" for c in plan["cues"])


def test_sfx_under_speech_are_turned_down_and_unknown_names_dropped():
    plan = plan_cues([{"at": 1.0, "sfx": "pop"}, {"at": 4.0, "sfx": "pop"}, {"at": 5.0, "sfx": "boing"}],
                     LIB, speech=[(0.5, 2.0)])
    quiet, loud = plan["cues"]
    assert quiet["volume"] < loud["volume"]
    assert plan["dropped"][0]["reason"] == "no 'boing' in the library"


def test_tracks_never_overlap():
    cues = assign_tracks([{"start": 0, "duration": 2}, {"start": 1, "duration": 1}, {"start": 2.5, "duration": 1}])
    assert [c["track"] for c in cues] == [20, 21, 20]


def test_audio_tags_carry_timing_volume_and_trim():
    tag = audio_tags([{"file": "whoosh.wav", "start": 0, "duration": 0.45, "media_start": 0.15,
                       "track": 20, "volume": 0.3}])
    assert tag == ('<audio id="sfx-0" src="assets/sfx/whoosh.wav" data-start="0" data-duration="0.45" '
                   'data-media-start="0.15" data-track-index="20" data-volume="0.3"></audio>')


def _write_wav(path, seconds, peak_at):
    rate = 48000
    x = np.zeros(int(seconds * rate), dtype=np.float32)
    i = int(peak_at * rate)
    x[i:i + 480] = 0.8
    with wave.open(str(path), "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(rate)
        w.writeframes((x * 32767).astype("<i2").tobytes())


@needs_ffmpeg
def test_stem_puts_the_peak_on_the_cut(tmp_path):
    _write_wav(tmp_path / "whoosh.wav", 0.6, 0.2)
    (tmp_path / "library.json").write_text(json.dumps({"files": {"whoosh": LIB["whoosh"]}}), encoding="utf-8")
    r = SfxPlacer().execute({"operation": "render_stem", "library_dir": str(tmp_path), "duration": 3.0,
                             "events": [{"at": 2.0, "sfx": "whoosh", "volume": 1.0}],
                             "output_path": str(tmp_path / "stem.wav")})
    assert r.success, r.error
    with wave.open(str(tmp_path / "stem.wav"), "rb") as w:
        pcm = np.frombuffer(w.readframes(w.getnframes()), dtype="<i2").reshape(-1, 2)
        rate = w.getframerate()
    assert abs(np.argmax(np.abs(pcm[:, 0])) / rate - 2.0) < 0.02
    assert r.data["cues"][0]["start"] == pytest.approx(1.8)
