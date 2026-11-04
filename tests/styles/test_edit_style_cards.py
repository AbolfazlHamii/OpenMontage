"""Edit style cards: every shipped card is schema-valid; the loader stays apart from playbooks."""

from __future__ import annotations

import copy

import jsonschema
import pytest

from styles.edit_style_loader import (
    EDITING_DIR,
    card_summary,
    list_edit_styles,
    load_edit_style,
    save_edit_style,
    validate_edit_style,
)
from styles.playbook_loader import list_playbooks

EXPECTED = {
    "full-history-in-n-minutes", "map-explainer", "kinetic-typography",
    "ken-burns-documentary", "fast-shorts", "cinematic-trailer", "calm-tutorial", "news-brief",
}


def test_all_eight_cards_ship_and_validate():
    names = set(list_edit_styles())
    assert EXPECTED <= names
    for name in EXPECTED:
        card = load_edit_style(name)
        assert card["name"] == name
        assert card["source"]["kind"] == "authored"


def test_history_card_matches_reference_measurements():
    card = load_edit_style("full-history-in-n-minutes")
    assert card["pacing"]["sections"]["body"]["asl_seconds"] == 3.75
    assert card["pacing"]["sections"]["body"]["cuts_per_minute"] == 16
    assert card["pacing"]["words_per_minute"] == 157
    assert card["source"]["measured"]["asl_seconds"] == 3.75


def test_cards_are_not_playbooks():
    assert not EXPECTED & set(list_playbooks())


def test_schema_rejects_bad_cards():
    good = load_edit_style("fast-shorts")
    bad = copy.deepcopy(good)
    del bad["hook_formula"]
    with pytest.raises(jsonschema.ValidationError):
        validate_edit_style(bad)
    bad = copy.deepcopy(good)
    bad["transitions"][0]["weight"] = 1.5
    with pytest.raises(jsonschema.ValidationError):
        validate_edit_style(bad)
    bad = copy.deepcopy(good)
    bad["pattern_interrupt_seconds"] = {"min": 9, "max": 3}
    with pytest.raises(ValueError):
        validate_edit_style(bad)
    bad = copy.deepcopy(good)
    bad["music_energy_curve"] = [{"at": 0.8, "energy": 1}, {"at": 0.1, "energy": 0}]
    with pytest.raises(ValueError):
        validate_edit_style(bad)


def test_learned_cards_save_and_load(tmp_path):
    card = copy.deepcopy(load_edit_style("news-brief"))
    card["name"] = "learned-demo"
    card["source"] = {"kind": "learned", "reference": "test", "measured": {"asl_seconds": 4.0}}
    path = save_edit_style(card, editing_dir=tmp_path)
    assert path.parent.name == "learned"
    assert load_edit_style("learned-demo", editing_dir=tmp_path)["source"]["kind"] == "learned"
    assert "learned-demo" in list_edit_styles(tmp_path)


def test_summary():
    s = card_summary(load_edit_style("full-history-in-n-minutes"))
    assert s["top_transitions"][0] == "hard_cut"
    assert s["pattern_interrupt_seconds"] == {"min": 3, "max": 6}


def test_editing_dir_exists():
    assert (EDITING_DIR / "learned").is_dir()
