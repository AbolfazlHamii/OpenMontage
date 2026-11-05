"""Edit-craft QA checks and the edit pass helpers. Pure: no media, no network."""

from __future__ import annotations

import pytest

from lib.fa_edit_qa import (
    check_beat_sync,
    check_caption_onscreen,
    check_cut_accents,
    check_cut_rhythm,
    check_end_screen,
    check_hook,
    check_music_ducking,
    check_music_ending,
    check_sfx_density,
    edit_checks,
)
from lib.fa_render_qa import Check, persian_summary
from styles.edit_style_loader import load_edit_style

CARD = load_edit_style("full-history-in-n-minutes")
BEATS = [round(0.313 + 0.603 * k, 3) for k in range(25)]


def v1_plan():
    """The first Samsung sample as it was rendered: 3 cuts and a punch, no SFX, flat bed."""
    return {
        "duration": 15.0, "cuts": [2.7, 6.85, 9.06], "interrupts": [13.36],
        "speech": [[0.19, 2.57], [2.82, 6.31], [6.98, 14.22]],
        "captions": [{"start": s, "end": e} for s, e in
                     [(0.19, 2.6), (2.83, 4.12), (4.17, 6.55), (6.99, 8.95), (9.06, 12.15), (12.21, 13.3),
                      (13.36, 14.6)]],
        "sfx": [], "beats": BEATS,
        "music_keyframes": [[0, 0], [0.5, 0.18], [13.36, 0.18], [13.66, 0.26], [14.4, 0.26], [15.0, 0]],
        "music_end": 15.0,
    }


def v2_plan():
    p = v1_plan()
    p.update({
        "cuts": [2.705, 6.931, 9.06], "interrupts": [1.78, 4.505, 13.36],
        "captions": [{"start": 0.13, "end": 2.84, "words": [{"start": 0.19, "end": 0.9}]},
                     {"start": 2.84, "end": 3.96}, {"start": 3.96, "end": 6.92}, {"start": 6.92, "end": 9.17},
                     {"start": 9.17, "end": 12.19}, {"start": 12.19, "end": 13.23}, {"start": 13.23, "end": 14.6}],
        "sfx": [{"at": 1.78}, {"at": 2.705}, {"at": 4.48}, {"at": 6.931}, {"at": 6.931, "bed": True},
                {"at": 10.15}, {"at": 13.36}],
        "music_keyframes": [[0, 0], [0.3, 0.14], [6.4, 0.24], [6.9, 0.14], [12.6, 0.14], [12.75, 0], [13.36, 0],
                            [13.37, 0.24], [14.6, 0.24], [BEATS[24], 0]],
        "music_end": BEATS[24],
    })
    return p


def test_v1_shows_what_the_edit_was_missing():
    checks = {c.name: c for c in edit_checks(v1_plan(), CARD)}
    assert checks["sfx_density"].status == "warn" and "no sound effects" in checks["sfx_density"].detail
    assert checks["cut_accents"].status == "warn"
    assert checks["hook_edit"].status == "warn"
    assert checks["caption_onscreen"].status == "warn" and checks["caption_onscreen"].evidence["blinks"]
    assert checks["beat_sync"].evidence["ratio"] == 0.25 and checks["beat_sync"].status == "warn"  # chance ~0.27
    assert checks["music_ending"].status == "warn"
    assert checks["end_screen"].status == "skipped"


def test_v2_plan_passes_the_edit_checks():
    checks = {c.name: c for c in edit_checks(v2_plan(), CARD)}
    bad = {n: c.detail for n, c in checks.items() if c.status == "warn"}
    assert bad == {}


def test_rhythm_flags_a_long_hold_against_the_card():
    c = check_cut_rhythm({"duration": 15.0, "cuts": [2.7], "interrupts": []}, CARD)
    assert c.status == "warn" and "no visual change" in c.detail
    assert c.evidence["card_max_hold"] == CARD["pattern_interrupt_seconds"]["max"]


def test_hook_wants_changes_caption_and_sound_early():
    plan = {"duration": 15, "cuts": [2.7], "interrupts": [], "speech": [[0.2, 2.5]],
            "captions": [{"start": 0.9, "end": 2.5}], "sfx": []}
    detail = check_hook(plan).detail
    assert "1 visual change" in detail and "first caption" in detail and "no sound accent" in detail


def test_sfx_density_limits():
    dense = {"duration": 10.0, "sfx": [{"at": t / 10} for t in range(0, 100, 10)]}
    assert check_sfx_density(dense).status == "warn"  # 60/min
    close = {"duration": 60.0, "sfx": [{"at": 1.0}, {"at": 1.1}, {"at": 9.0}, {"at": 20.0}, {"at": 30.0},
                                      {"at": 40.0}, {"at": 50.0}]}
    assert "0.10 s apart" in check_sfx_density(close).detail
    assert check_cut_accents({"cuts": [2.0, 5.0], "sfx": [{"at": 2.05}]}).evidence["share"] == 0.5


def test_caption_blinks_short_groups_and_stray_words():
    plan = {"captions": [{"start": 0.0, "end": 0.5, "words": [{"start": 5.0, "end": 5.2}]},
                         {"start": 0.6, "end": 2.0}], "speech": [[0, 2]]}
    c = check_caption_onscreen(plan)
    assert c.evidence["too_short"] == [0] and c.evidence["blinks"] == [0]
    assert c.evidence["words_outside_speech"] == 1


def test_beat_sync_and_ending_use_the_grid():
    plan = {"duration": 15, "cuts": [BEATS[4], BEATS[10] + 0.02, 9.06], "interrupts": [], "beats": BEATS}
    c = check_beat_sync(plan, CARD)
    assert c.evidence["ratio"] == pytest.approx(0.667, abs=0.001) and c.status == "pass"
    assert check_music_ending({"music_end": BEATS[3] + 0.03, "beats": BEATS}).status == "pass"
    assert check_music_ending({"music_end": BEATS[3] + 0.3, "beats": BEATS}).status == "warn"


def test_flat_bed_is_flagged():
    flat = {"duration": 10, "music_keyframes": [[0, 0.18], [10, 0.18]], "speech": [[1, 4], [6, 9]]}
    assert check_music_ducking(flat).status == "warn"


def test_end_screen_only_for_long_videos():
    assert check_end_screen({"duration": 90, "end_screen": {"start": 75, "end": 90}}).status == "pass"
    assert check_end_screen({"duration": 90}).status == "warn"


def test_persian_summary_names_the_edit_checks():
    report = {"render": "x.mp4", "status": "warn", "checks": [
        Check("sfx_density", "warn", "no sound effects").__dict__, Check("beat_sync", "pass", "ok").__dict__]}
    text = persian_summary(report)
    assert "تراکم افکت صوتی" in text and "برش روی ضرب موسیقی" in text
