"""fa cost estimator and pricing refresh. No network."""

from __future__ import annotations

import datetime
import json
from pathlib import Path

import pytest
import yaml

from lib.fa_cost_estimate import (
    estimate,
    load_pricing,
    plan_from_brief,
    plan_from_scene_plan,
)
from scripts.fa_pricing_update import apply_catalog

REPO = Path(__file__).resolve().parents[2]
SAMPLE_PLAN = REPO / "docs" / "fa" / "examples" / "samsung_sample_plan.json"
# Samsung sample, from events.jsonl: 2 TTS lines + 3 stills (docs/fa/BASELINE.md).
SAMSUNG_ACTUAL_PROJECT_USD = 0.001499 + 0.001764 + 3 * 0.0672


@pytest.fixture
def pricing():
    return load_pricing(today=datetime.date(2026, 11, 4))


def test_samsung_sample_estimate_is_within_20_percent(pricing):
    plan = json.loads(SAMPLE_PLAN.read_text(encoding="utf-8"))
    est = estimate(plan, pricing)
    assert est.total_usd == pytest.approx(SAMSUNG_ACTUAL_PROJECT_USD, rel=0.20)
    assert est.images == 3
    assert est.narration_seconds == pytest.approx(6.6 + 7.76, rel=0.15)
    assert est.by("stage")["images"] == pytest.approx(0.2016)
    assert est.seconds_parallel < est.seconds_serial


def test_draft_is_cheaper_than_final_and_rounds_add_up(pricing):
    plan = {"scenes": [{"id": f"s{i}", "images": 1} for i in range(10)]}
    draft = estimate(plan, pricing, "draft")
    final = estimate(plan, pricing, "final")
    assert draft.total_usd == pytest.approx(10 * 0.0336)
    assert final.total_usd == pytest.approx(10 * 0.101)
    with_drafts = estimate(plan, pricing, "final", draft_rounds=2)
    assert with_drafts.total_usd == pytest.approx(10 * 0.101 + 20 * 0.0336)


def test_stale_prices_warn(pricing):
    old = load_pricing(today=datetime.date(2026, 12, 1))
    assert old["stale"] and not pricing["stale"]
    assert estimate({"scenes": []}, old).warnings


def test_scene_plan_counts_generated_images_and_narration_once():
    scene_plan = {"scenes": [
        {"id": "a", "type": "broll", "script_section_id": "x",
         "required_assets": [{"type": "image", "description": "", "source": "generate"},
                             {"type": "image", "description": "", "source": "provided"}]},
        {"id": "b", "type": "text_card", "script_section_id": "x", "required_assets": []},
        {"id": "c", "type": "generated", "script_section_id": "y"},
    ]}
    script = {"sections": [{"id": "x", "text": "سلام دنیا"}, {"id": "y", "text": "خداحافظ"}]}
    plan = plan_from_scene_plan(scene_plan, script)
    assert [s["images"] for s in plan["scenes"]] == [1, 0, 1]
    assert [s["narration"] for s in plan["scenes"]] == ["سلام دنیا", "", "خداحافظ"]


def test_brief_plan_uses_duration(pricing):
    plan = plan_from_brief({"target_duration_seconds": 90}, 6)
    assert len(plan["scenes"]) == 15
    est = estimate(plan, pricing, "final")
    assert est.narration_seconds == 90


def test_apply_catalog_updates_known_models_only():
    table = yaml.safe_load((REPO / "config" / "fa_pricing.yaml").read_text(encoding="utf-8"))
    catalog = {
        "gemini-3.1-flash-image": {"pricing": {
            "output_cost_per_image": 0.07, "output_cost_per_image_2048x2048": 0.11}},
        "claude-haiku-5-5": {"pricing": {"input": 0.2, "output": 1.0}},
        "brand-new-model": {"pricing": {"input": 9, "output": 9}},
    }
    table, notes = apply_catalog(table, catalog, datetime.date(2026, 12, 1))
    imgs = table["images"]["avalai"]["gemini-3.1-flash-image"]
    assert imgs["1K"] == 0.07 and imgs["2K"] == 0.11 and imgs["4K"] == 0.151
    assert table["llm"]["avalai"]["claude-haiku-5-5"] == {"input": 0.2, "output": 1.0}
    assert "brand-new-model" not in table["llm"]["avalai"]
    assert table["updated"] == "2026-12-01"
    assert any("not in catalog" in n for n in notes)
