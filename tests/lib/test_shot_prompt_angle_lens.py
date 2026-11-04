"""camera_angle and lens in shot_language: optional, schema-valid, in the prompt."""

from __future__ import annotations

import json
from pathlib import Path

import jsonschema

from lib.shot_prompt_builder import build_shot_prompt

SCHEMA = json.loads(
    (Path(__file__).resolve().parents[2] / "schemas/artifacts/scene_plan.schema.json")
    .read_text(encoding="utf-8")
)


def _plan(shot_language):
    return {"version": "1.0", "scenes": [{
        "id": "s1", "type": "generated", "description": "a 1938 dried-fish shop",
        "start_seconds": 0, "end_seconds": 3, "shot_language": shot_language,
    }]}


def test_new_fields_validate_and_old_plans_still_do():
    jsonschema.validate(_plan({"shot_size": "wide", "camera_angle": "low", "lens": "telephoto"}), SCHEMA)
    jsonschema.validate(_plan({"shot_size": "wide", "lens_mm": 35}), SCHEMA)


def test_unknown_angle_is_rejected():
    try:
        jsonschema.validate(_plan({"camera_angle": "sideways"}), SCHEMA)
    except jsonschema.ValidationError:
        return
    raise AssertionError("sideways should not validate")


def test_prompt_includes_angle_and_lens():
    prompt = build_shot_prompt({"description": "a shop", "shot_language": {
        "shot_size": "medium", "camera_angle": "worms_eye", "lens": "anamorphic", "lens_mm": 35}})
    assert "worm's-eye view" in prompt and "anamorphic lens" in prompt and "35mm lens" in prompt
    assert prompt.index("anamorphic") < prompt.index("35mm")


def test_prompt_without_new_fields_is_unchanged():
    scene = {"description": "a shop", "shot_language": {"shot_size": "wide", "lens_mm": 50}}
    assert build_shot_prompt(scene) == "50mm lens. wide shot capturing full scene. a shop"
