"""Edit style cards: how a video is cut, separate from how it looks.

Cards live in styles/editing/*.yaml (authored) and styles/editing/learned/
*.yaml (written by tools/analysis/edit_style_extractor.py). They are
validated by schemas/styles/edit_style.schema.json. A card complements a
visual playbook (styles/*.yaml); playbook_loader only globs styles/*.yaml, so
the two never mix.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Optional

import jsonschema
import yaml

STYLES_DIR = Path(__file__).resolve().parent
EDITING_DIR = STYLES_DIR / "editing"
LEARNED_SUBDIR = "learned"
SCHEMA_PATH = STYLES_DIR.parent / "schemas" / "styles" / "edit_style.schema.json"


def load_schema() -> dict[str, Any]:
    with open(SCHEMA_PATH, encoding="utf-8") as f:
        return json.load(f)


def validate_edit_style(card: dict[str, Any]) -> None:
    """Raise jsonschema.ValidationError (or ValueError) if the card is invalid."""
    jsonschema.validate(card, load_schema())
    pi = card["pattern_interrupt_seconds"]
    if pi["min"] > pi["max"]:
        raise ValueError("pattern_interrupt_seconds.min is greater than max")
    points = [p["at"] for p in card["music_energy_curve"]]
    if points != sorted(points):
        raise ValueError("music_energy_curve points must be in time order")


def _card_paths(editing_dir: Path) -> list[Path]:
    return sorted(editing_dir.glob("*.yaml")) + sorted((editing_dir / LEARNED_SUBDIR).glob("*.yaml"))


def list_edit_styles(editing_dir: Optional[Path] = None) -> list[str]:
    return [p.stem for p in _card_paths(editing_dir or EDITING_DIR)]


def load_edit_style(name: str, editing_dir: Optional[Path] = None) -> dict[str, Any]:
    """Load and validate a card by name; authored cards win over learned ones."""
    editing_dir = editing_dir or EDITING_DIR
    for path in (editing_dir / f"{name}.yaml", editing_dir / LEARNED_SUBDIR / f"{name}.yaml"):
        if path.exists():
            with open(path, encoding="utf-8") as f:
                card = yaml.safe_load(f)
            validate_edit_style(card)
            return card
    raise FileNotFoundError(f"Edit style not found: {name!r} (searched {editing_dir})")


def save_edit_style(card: dict[str, Any], editing_dir: Optional[Path] = None,
                    learned: bool = True) -> Path:
    validate_edit_style(card)
    editing_dir = editing_dir or EDITING_DIR
    folder = editing_dir / LEARNED_SUBDIR if learned else editing_dir
    folder.mkdir(parents=True, exist_ok=True)
    path = folder / f"{card['name']}.yaml"
    with open(path, "w", encoding="utf-8") as f:
        yaml.safe_dump(card, f, sort_keys=False, allow_unicode=True)
    return path


def card_summary(card: dict[str, Any]) -> dict[str, Any]:
    """The numbers a director or reviewer needs at a glance."""
    sections = card["pacing"]["sections"]
    return {
        "name": card["name"],
        "title": card["title"],
        "asl_seconds": {k: v["asl_seconds"] for k, v in sections.items()},
        "cuts_per_minute": {k: v["cuts_per_minute"] for k, v in sections.items()},
        "words_per_minute": card["pacing"]["words_per_minute"],
        "pattern_interrupt_seconds": card["pattern_interrupt_seconds"],
        "top_transitions": [t["name"] for t in sorted(card["transitions"], key=lambda t: -t["weight"])[:3]],
        "top_camera_moves": [m["name"] for m in sorted(card["camera_moves"], key=lambda m: -m["weight"])[:3]],
        "subtitles": card["subtitles"]["style"],
    }
