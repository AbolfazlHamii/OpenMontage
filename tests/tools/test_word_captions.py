"""word_captions: Persian normalisation, alignment to a noisy transcript, timing, HTML."""

from __future__ import annotations

import json

import pytest

from tools.subtitle.word_captions import (
    WordCaptions,
    align,
    build_groups,
    caption_cues,
    clamp_to_speech,
    normalize,
    parse_markup,
    render_html,
    snap_starts,
    time_words,
)

# whisper-1 on the Samsung sample's second line (2026-11-04), shortened.
S2_WORDS = [
    {"word": "سال", "start": 0.0, "end": 0.56}, {"word": "1995،", "start": 0.56, "end": 2.48},
    {"word": "رحیث", "start": 2.48, "end": 2.84}, {"word": "سامسونگ", "start": 2.84, "end": 3.40},
    {"word": "150", "start": 3.40, "end": 4.06}, {"word": "هزار", "start": 4.06, "end": 4.40},
    {"word": "تا", "start": 4.40, "end": 4.54}, {"word": "گوشی", "start": 4.54, "end": 4.82},
    {"word": "خراب", "start": 4.82, "end": 5.26}, {"word": "و", "start": 5.26, "end": 5.44},
    {"word": "جلوی", "start": 5.44, "end": 5.86}, {"word": "کارگراش", "start": 5.86, "end": 6.48},
    {"word": "آتیش", "start": 6.48, "end": 7.14}, {"word": "زد", "start": 7.14, "end": 7.46},
]
S2_SPEECH = [(6.978, 8.886), (8.998, 14.225)]


def test_normalize_folds_digits_letters_and_marks():
    assert normalize("۱۹۹۵،") == "1995"
    assert normalize("می‌دونستی") == "میدونستی"
    assert normalize("رئیس") == normalize("رييس")
    assert normalize("گوشیِ") == "گوشی"


def test_markup_styles_runs_and_keeps_trailing_punctuation_out():
    toks = parse_markup("احتمالاً *سامسونگه*… با *ماهی خشک* _آتیش زد!_")
    assert [(t["text"], t["tail"], t["style"]) for t in toks] == [
        ("احتمالاً", "", "plain"), ("سامسونگه", "…", "key"), ("با", "", "plain"),
        ("ماهی", "", "key"), ("خشک", "", "key"), ("آتیش", "", "hot"), ("زد!", "", "hot")]


def test_alignment_survives_the_transcripts_spelling():
    display = ["سال", "۱۹۹۵،", "رئیس", "سامسونگ", "۱۵۰", "هزار", "تا", "گوشیِ", "خراب", "رو",
               "جلوی", "کارگرهاش", "آتیش", "زد!"]
    assert align(display, [w["word"] for w in S2_WORDS]) == list(range(14))


def test_extra_display_word_gets_time_from_its_neighbours():
    toks = parse_markup("سال ۱۹۹۵ میلادی رئیس")
    words = [S2_WORDS[0], S2_WORDS[1], S2_WORDS[2]]
    time_words(toks, words)
    assert toks[2]["start"] >= toks[1]["start"] and toks[2]["end"] <= toks[3]["start"] + 1e-6
    assert all(a["end"] <= b["start"] + 1e-6 for a, b in zip(toks, toks[1:]))


def test_word_edges_are_clamped_into_speech():
    assert clamp_to_speech(0.0, 0.9, [(0.19, 2.57)]) == (0.19, 0.9)
    assert clamp_to_speech(1.78, 2.9, [(0.19, 2.57), (2.82, 6.3)]) == (1.78, 2.57)
    assert clamp_to_speech(7.0, 7.4, [(0.19, 2.57)]) == (2.52, 2.57)


def test_starts_snap_to_attacks_but_keep_their_order():
    spoken = [{"word": "a", "start": 12.19, "end": 12.61}, {"word": "b", "start": 12.61, "end": 13.23},
              {"word": "c", "start": 13.23, "end": 13.89}]
    snap_starts(spoken, [12.18, 12.6, 13.35, 13.58])
    assert [w["start"] for w in spoken] == [12.18, 12.6, 13.35]
    assert spoken[1]["end"] == 13.23  # already ends before the next attack
    far = [{"word": "x", "start": 1.0, "end": 1.5}]
    snap_starts(far, [1.4])
    assert far[0]["start"] == 1.0


def _groups():
    clips = {"vo-2": {"start": 6.75, "words": S2_WORDS, "speech": S2_SPEECH}}
    texts = ["سال *۱۹۹۵*،", "رئیس سامسونگ *۱۵۰ هزار* تا گوشیِ خراب رو", "جلوی کارگرهاش", "_آتیش زد!_"]
    return build_groups([{"text": t, "clip": "vo-2"} for t in texts], clips, 15.0)


def test_groups_follow_the_voice_without_blinks():
    groups = _groups()
    assert groups[0]["words"][0]["start"] == pytest.approx(6.978)  # whisper said 6.75
    assert groups[-1]["words"][0]["start"] == pytest.approx(13.23)
    for a, b in zip(groups, groups[1:]):
        assert a["end"] <= b["start"] + 1e-6
        assert b["start"] - a["end"] == 0 or b["start"] - a["end"] >= 0.35
    assert all(g["end"] - g["start"] >= 0.8 for g in groups)
    assert groups[-1]["end"] <= 15.0


def test_html_has_timed_words_and_emphasis_runs():
    out = render_html(_groups())
    assert '<div id="cg-1" class="cg" data-cs=' in out and "data-start" not in out
    assert '<span class="em key" data-ws="10.15"' in out
    assert out.count('class="w"') == 14
    assert '<span class="em hot"' in out and "آتیش" in out
    assert "</span>،</span>" in out  # the comma sits inside the pill, unstyled


def test_qa_cues_start_with_rlm():
    cues = caption_cues(_groups())
    assert all(c["lines"][0].startswith("‏") for c in cues)
    assert "۱۵۰ هزار" in cues[1]["lines"][0]


def test_tool_reads_words_json(tmp_path):
    words = tmp_path / "s2.words.json"
    words.write_text(json.dumps({"text": "...", "words": S2_WORDS}, ensure_ascii=False), encoding="utf-8")
    r = WordCaptions().execute({"groups": [{"text": "سال *۱۹۹۵*،", "clip": "a"}],
                                "clips": {"a": {"start": 6.75, "words_path": str(words), "speech": S2_SPEECH}},
                                "duration": 15, "output_path": str(tmp_path / "caps.json")})
    assert r.success, r.error
    assert json.loads((tmp_path / "caps.json").read_text(encoding="utf-8"))["groups"][0]["id"] == "cg-0"
