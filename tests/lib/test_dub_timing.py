"""lib/dub_timing: budget, stretch, rewrite, gap borrowing, flagging, overlaps."""

from __future__ import annotations

import pytest

from lib import dub_timing as dt


def _synth(durations):
    """Fake TTS: returns the next duration from the list on each call."""
    calls = []

    def synthesize(text):
        calls.append(text)
        return f"clip{len(calls)}.wav", durations[len(calls) - 1]

    synthesize.calls = calls
    return synthesize


def _rewriter(outputs):
    calls = []

    def rewrite(text, max_chars, attempt):
        calls.append((text, max_chars, attempt))
        return outputs[attempt - 1]

    rewrite.calls = calls
    return rewrite


SEG = dt.Segment(id="s1", start=10.0, end=14.0, text="سلام دنیا", speaker="SPEAKER_00")


def test_budget_and_spoken_chars():
    assert dt.char_budget(4.0, 9.5) == 38
    assert dt.spoken_chars("سلام، دنیا!") == 8
    assert dt.tempo_for(4.2, 4.0) == pytest.approx(1.05)
    assert dt.tempo_for(3.0, 4.0) == 1.0


def test_fits_without_change():
    fit = dt.fit_segment(SEG, _synth([3.5]), None, cps=9.5)
    assert fit.status == "ok" and fit.tempo == 1.0
    assert fit.start == 10.0 and fit.end == 13.5
    assert not fit.review_required


def test_up_to_8_percent_is_stretched():
    fit = dt.fit_segment(SEG, _synth([4.3]), None, cps=9.5)
    assert fit.status == "stretched"
    assert fit.tempo == pytest.approx(1.075)
    assert fit.end == pytest.approx(14.0)


def test_long_line_is_rewritten_with_measured_budget():
    synth = _synth([6.0, 4.1])
    rewrite = _rewriter(["کوتاه‌تر"])
    seg = dt.Segment(id="s1", start=0, end=4.0, text="ا" * 30)
    fit = dt.fit_segment(seg, synth, rewrite, cps=9.5)
    assert fit.status == "rewritten" and fit.rewrites == 1
    assert fit.text == "کوتاه‌تر"
    assert fit.review_required
    # 30 letters took 6 s -> 5 cps measured -> 4 s slot = 20 letters.
    assert rewrite.calls[0][1] == 20
    assert fit.texts_tried == ["ا" * 30, "کوتاه‌تر"]


def test_text_far_over_budget_is_rewritten_before_any_audio():
    synth = _synth([2.1])
    rewrite = _rewriter(["خلاصه"])
    seg = dt.Segment(id="s1", start=0, end=2.0, text="ا" * 60)
    fit = dt.fit_segment(seg, synth, rewrite, cps=9.5)
    assert synth.calls == ["خلاصه"]          # the long text was never synthesized
    assert rewrite.calls[0][1] == 19
    assert fit.rewrites == 1 and fit.status == "rewritten"


def test_at_most_two_rewrites_then_borrow_the_gap():
    synth = _synth([6.0, 5.5, 5.0])
    rewrite = _rewriter(["سلام دن", "سلام"])
    fit = dt.fit_segment(SEG, synth, rewrite, cps=9.5, next_start=15.0)
    assert len(rewrite.calls) == 2 and len(synth.calls) == 3
    assert fit.status == "used_gap"
    assert fit.tempo == pytest.approx(1.0)
    assert fit.end == pytest.approx(15.0)


def test_flagged_when_nothing_fits_and_overlap_reported():
    synth = _synth([7.0, 7.0, 7.0])
    rewrite = _rewriter(["یک", "دو"])
    fit = dt.fit_segment(SEG, synth, rewrite, cps=9.5, next_start=14.5)
    assert fit.status == "flagged"
    assert fit.tempo == dt.MAX_STRETCH
    assert fit.end == pytest.approx(10 + 7 / 1.08, abs=1e-3)
    assert fit.overlap_seconds == pytest.approx(fit.end - 14.5, abs=1e-3)


def test_pause_after_the_line_counts_before_any_rewrite():
    # 24 letters: over the 2 s slot's budget (19) but within slot + pause (28),
    # so the text is synthesized as written; the voice read it fast enough.
    synth = _synth([2.1])
    rewrite = _rewriter(["unused"])
    seg = dt.Segment(id="s1", start=0, end=2.0, text="ا" * 24)
    fit = dt.fit_segment(seg, synth, rewrite, cps=9.5, next_start=3.0)
    assert rewrite.calls == [] and synth.calls == ["ا" * 24]
    assert fit.status == "stretched"


def test_last_line_may_run_to_the_end_of_the_video():
    segs = [dt.Segment(id="a", start=0.0, end=1.0, text="x")]
    fits = dt.fit_all(segs, lambda s: (lambda t: ("a.wav", 1.5)), None, lambda s: 9.5, media_end=3.0)
    assert fits[0].status == "used_gap"


def test_recorded_takes_have_no_rewrite():
    fit = dt.fit_segment(SEG, _synth([5.0]), None, cps=9.5, next_start=20.0)
    assert fit.status == "used_gap" and fit.rewrites == 0


def test_fit_all_uses_next_start_and_overlaps_check():
    segs = [
        dt.Segment(id="a", start=0.0, end=2.0, text="x", speaker="A"),
        dt.Segment(id="b", start=2.1, end=4.0, text="x", speaker="B"),
        dt.Segment(id="c", start=4.0, end=6.0, text="x", speaker="A"),
    ]
    durations = {"a": 2.0, "b": 2.6, "c": 1.0}
    fits = dt.fit_all(
        segs,
        synthesize_for=lambda s: (lambda text, s=s: (f"{s.id}.wav", durations[s.id])),
        rewrite=None,
        cps_for=lambda s: 9.5,
    )
    assert [f.status for f in fits] == ["ok", "flagged", "ok"]
    found = dt.overlaps(fits)
    assert found == [{"id": "b", "next": "c", "overlap_seconds": pytest.approx(2.1 + 2.6 / 1.08 - 4.0, abs=1e-3)}]
    assert dt.overlaps(fits, tolerance=1.0) == []


def test_empty_or_longer_rewrite_is_ignored_and_the_gap_is_used():
    synth = _synth([5.0])
    rewrite = _rewriter(["", "much longer text than before"])
    fit = dt.fit_segment(SEG, synth, rewrite, cps=9.5, next_start=15.0)
    assert fit.status == "used_gap" and fit.text == SEG.text
    assert len(rewrite.calls) == 1      # an empty answer ends the rewrites


def test_failing_rewriter_does_not_stop_the_line():
    def boom(text, max_chars, attempt):
        raise RuntimeError("worker down")

    fit = dt.fit_segment(SEG, _synth([7.0]), boom, cps=9.5, next_start=14.5)
    assert fit.status == "flagged" and fit.rewrites == 0 and not fit.review_required


def test_a_line_may_run_up_to_200_ms_into_the_next():
    # 3.9 s slot, 0.1 s pause: 4.4 s at 1.08x is 4.074 s placed, 74 ms past 14.0.
    fit = dt.fit_segment(dt.Segment(id="s", start=10.0, end=13.9, text="x"), _synth([4.4]), None,
                         cps=9.5, next_start=14.0)
    assert fit.status == "used_gap" and 0 < fit.overlap_seconds <= dt.OVERLAP_TOLERANCE
