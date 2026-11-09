"""Second-language audio track: narration overlay, fitting lines to the picture, voicing."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from lib import fa_audio_track as at
from lib import fa_manual_images as mi
from tools.base_tool import ToolResult

SHOTLIST = {
    "title": "نمونه",
    "voice": {"channel": "fa-main", "voice_id": "Charon", "style": "راوی", "providers": ["avalai"]},
    "scenes": [
        {"id": "s1", "narration": "اول.", "shots": [{"id": "s1a", "prompt": "A"}]},
        {"id": "s2", "narration": "دوم.", "shots": [{"id": "s2a", "prompt": "B"}]},
    ],
}
ENGLISH = {"language": "en", "voice": {"style": "Tense documentary narrator."},
           "scenes": {"s1": "First line.", "s2": "Second line."}}
TIMING = {"duration": 20.0, "scenes": [
    {"id": "s1", "start": 0.0, "end": 10.0, "voice_start": 0.25, "voice_seconds": 9.4},
    {"id": "s2", "start": 10.0, "end": 19.6, "voice_start": 10.0, "voice_seconds": 9.25}]}


@pytest.fixture
def project(tmp_path):
    proj = tmp_path / "proj"
    (proj / "manual_images").mkdir(parents=True)
    (proj / "manual_images" / "shotlist.json").write_text(json.dumps(SHOTLIST, ensure_ascii=False), encoding="utf-8")
    (proj / "manual_images" / "narration_en.json").write_text(json.dumps(ENGLISH), encoding="utf-8")
    return proj


def test_overlay_swaps_text_and_voice_but_not_the_persian_lexicon(project):
    data = at.shotlist_for(project, "en")
    assert [s["narration"] for s in data["scenes"]] == ["First line.", "Second line."]
    assert data["voice"]["language"] == "en" and data["voice"]["voice_id"] == "Charon"
    assert data["voice"]["style"] == "Tense documentary narrator."
    assert "channel" not in data["voice"]  # the channel lexicon respells Persian words
    assert data["scenes"][0]["shots"] == SHOTLIST["scenes"][0]["shots"]


def test_overlay_missing_a_scene_is_an_error(project):
    (project / "manual_images" / "narration_en.json").write_text(
        json.dumps({"scenes": {"s1": "Only one."}}), encoding="utf-8")
    with pytest.raises(ValueError, match="s2"):
        at.shotlist_for(project, "en")


def test_each_line_fits_before_the_next_line_starts():
    rows = {r["scene"]: r for r in at.fit({"s1": {"seconds": 9.0}, "s2": {"seconds": 9.5}}, TIMING)}
    assert rows["s1"]["window"] == pytest.approx(10.0 - 0.25 - at.LINE_GAP)
    assert rows["s1"]["tempo"] == 1.0 and rows["s1"]["fits"]
    # the last line ends before the closing fade
    assert rows["s2"]["window"] == pytest.approx(20.0 - at.END_FADE - 10.0 - at.LINE_GAP)
    assert rows["s2"]["tempo"] == pytest.approx(9.5 / rows["s2"]["window"], abs=1e-3)
    assert rows["s2"]["fits"] is (rows["s2"]["tempo"] <= at.MAX_TEMPO)
    too_long = at.fit({"s1": {"seconds": 12.0}, "s2": {"seconds": 1.0}}, TIMING)
    assert not too_long[0]["fits"]


def test_narrate_sends_the_overlay_language_without_the_channel(project):
    calls = []

    class TTS:
        def execute(self, inputs):
            calls.append(inputs)
            Path(inputs["output_path"]).parent.mkdir(parents=True, exist_ok=True)
            Path(inputs["output_path"]).write_bytes(b"wav")
            return ToolResult(success=True, data={}, cost_usd=0.001)

    out = mi.narrate(project, tts=TTS(), duration=lambda p: 3.0, data=at.shotlist_for(project, "en"))
    assert [c["text"] for c in calls] == ["First line.", "Second line."]
    assert all(c["language_code"] == "en" and "channel" not in c for c in calls)
    assert calls[0]["voice_id"] == "Charon"
    # the Persian clips are cached under other names and stay untouched
    assert all("s1_" in Path(c["path"]).name or "s2_" in Path(c["path"]).name for c in out["clips"].values())


def test_transcript_alignment_asks_for_the_take_language(tmp_path, monkeypatch):
    seen = {}

    class STT:
        def execute(self, inputs):
            seen.update(inputs)
            return ToolResult(success=True, data={"words": []}, cost_usd=0.0)

    monkeypatch.setattr(mi.shutil, "which", lambda name: None)  # no mp3 re-encode
    take = tmp_path / "take.wav"
    take.write_bytes(b"")
    mi._take_words(take, STT(), "en")
    assert seen["language"] == "en"


# -- subtitles ---------------------------------------------------------------------

def test_srt_times_and_numbering():
    srt = at.to_srt([{"start": 0.25, "end": 3661.5, "lines": ["Hello.", "Two lines."]}])
    assert srt.startswith("1\n00:00:00,250 --> 01:01:01,500\nHello.\nTwo lines.\n")


def test_long_sentence_splits_evenly_without_an_orphan_word():
    text = ("In 1937 and 1938 alone, by their own records, more than 680,000 people "
            "were shot in the cellars and forests around Moscow.")
    parts = at._even_parts(text)
    assert len(parts) == 2 and " ".join(parts) == text
    assert all(len(p.split()) > 3 for p in parts)
    assert all(len(at.textwrap.wrap(p, at.LINE_CHARS)) <= at.CUE_LINES for p in parts)


def test_cues_follow_persian_sentences_or_spread_over_the_scene():
    data = {"scenes": [{"id": "s1", "narration": "اول. دوم؟"}, {"id": "s2", "narration": "سوم."}]}
    timing = {"duration": 12.0, "scenes": [
        {"id": "s1", "voice_start": 0.0, "voice_seconds": 6.0},
        {"id": "s2", "voice_start": 6.5, "voice_seconds": 4.0}]}
    words = [{"word": "اول", "start": 0.1, "end": 2.0}, {"word": "دوم", "start": 4.0, "end": 5.9},
             {"word": "سوم", "start": 6.6, "end": 10.0}]
    # two sentences each side: the second English one starts with the second Persian one
    cues = at.subtitle_cues(data, {"s1": "The first one here. The second?", "s2": "Third one, read slowly."},
                            timing, words)
    assert [c["lines"][0] for c in cues] == ["The first one here.", "The second?", "Third one, read slowly."]
    assert 2.0 <= cues[1]["start"] <= 4.0 and cues[2]["start"] == pytest.approx(6.5)
    assert all(a["end"] <= b["start"] for a, b in zip(cues, cues[1:]))
    # different sentence counts: spread by length over the scene's line
    spread = at.subtitle_cues(data, {"s1": "One sentence only, spoken across both.", "s2": "Third."},
                              timing, words)
    assert spread[0]["start"] == 0.0 and spread[0]["end"] == pytest.approx(6.0)


def test_a_flash_cue_joins_its_neighbour():
    cues = [{"start": 0.0, "end": 0.4, "lines": ["Why?"], "scene": "s1"},
            {"start": 0.4, "end": 2.0, "lines": ["It's his signal."], "scene": "s1"},
            {"start": 2.0, "end": 4.0, "lines": ["Other scene."], "scene": "s2"}]
    merged = at._merge_fast(cues)
    assert merged[0]["lines"] == ["Why? It's his signal."] and merged[0]["end"] == 2.0
    assert merged[1]["lines"] == ["Other scene."]
