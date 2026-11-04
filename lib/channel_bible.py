"""Channel bible: the per-channel memory every Persian production reads.

A channel folder holds the tone guide, the approved voices, character
references, a pronunciation lexicon for TTS, a term glossary, the owner's
script edits and one retro per video:

    <channels dir>/<channel>/
        channel.md        tone, audience, register, hook formulas, CTA
        voices.yaml       voice + style + cps per role
        characters/<name>/  reference images + description.md
        lexicon.tsv       term -> spelling the voice reads correctly
        lexicon_suggestions.tsv   words round-trip keeps mishearing (owner approves)
        glossary.tsv      fixed term equivalents (en -> fa)
        examples/<project>.jsonl  owner edits, before and after
        retros/<date>-<project>.md

The live channels live outside the public fork: OPENMONTAGE_CHANNELS_DIR
points at them (the owner keeps them in a private backup repo). Without it,
<repo>/channels is used; only channels/_template is tracked there.

    python -m lib.channel_bible show --channel fa-main
    python -m lib.channel_bible apply --channel fa-main --text "..."
    python -m lib.channel_bible suggest --channel fa-main --audition <results.json>
    python -m lib.channel_bible approve --channel fa-main --term صدها --tts "صَدها"
"""

from __future__ import annotations

import argparse
import csv
import datetime
import json
import os
import re
import shutil
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import yaml

REPO_ROOT = Path(__file__).resolve().parent.parent
TEMPLATE = REPO_ROOT / "channels" / "_template"
LEXICON_FIELDS = ["term", "tts", "note"]
SUGGESTION_FIELDS = ["expected", "heard", "count", "sources", "status"]


def channels_dir() -> Path:
    configured = os.environ.get("OPENMONTAGE_CHANNELS_DIR")
    return Path(configured) if configured else REPO_ROOT / "channels"


def channel_path(channel: str) -> Path:
    if not re.fullmatch(r"[a-z0-9][a-z0-9_-]*", channel):
        raise ValueError(f"channel name must be a lowercase slug: {channel!r}")
    return channels_dir() / channel


def create_channel(channel: str) -> Path:
    """Copy channels/_template to a new channel folder (never overwrites)."""
    path = channel_path(channel)
    if path.exists():
        raise FileExistsError(f"channel already exists: {path}")
    shutil.copytree(TEMPLATE, path)
    voices = path / "voices.yaml"
    voices.write_text(voices.read_text(encoding="utf-8").replace("<channel>", channel),
                      encoding="utf-8")
    return path


def _read_tsv(path: Path) -> list[dict[str, str]]:
    if not path.exists():
        return []
    with path.open(encoding="utf-8", newline="") as f:
        rows = csv.DictReader((line for line in f if not line.startswith("#")), delimiter="\t")
        return [{k: (v or "").strip() for k, v in row.items() if k} for row in rows]


def _write_tsv(path: Path, fields: list[str], rows: list[dict[str, Any]]) -> None:
    with path.open("w", encoding="utf-8", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=fields, delimiter="\t", extrasaction="ignore")
        writer.writeheader()
        writer.writerows(rows)


@dataclass
class Channel:
    name: str
    path: Path

    @property
    def lexicon(self) -> list[dict[str, str]]:
        return [r for r in _read_tsv(self.path / "lexicon.tsv") if r.get("term") and r.get("tts")]

    @property
    def glossary(self) -> list[dict[str, str]]:
        return [r for r in _read_tsv(self.path / "glossary.tsv") if r.get("en") and r.get("fa")]

    @property
    def voices(self) -> dict[str, Any]:
        path = self.path / "voices.yaml"
        if not path.exists():
            return {}
        return yaml.safe_load(path.read_text(encoding="utf-8")) or {}

    def voice_for(self, role: str = "narrator") -> dict[str, Any]:
        role_cfg = (self.voices.get("roles") or {}).get(role)
        if not role_cfg:
            raise KeyError(f"no voice for role {role!r} in {self.path / 'voices.yaml'}")
        return role_cfg


def load_channel(channel: str) -> Channel:
    path = channel_path(channel)
    if not path.is_dir():
        raise FileNotFoundError(
            f"channel {channel!r} not found in {channels_dir()} "
            "(set OPENMONTAGE_CHANNELS_DIR or create it with create_channel)"
        )
    return Channel(channel, path)


def _term_pattern(term: str) -> re.Pattern:
    # \w covers Persian letters, so a term never matches inside a longer
    # word; ZWNJ is not \w, so «سامسونگ‌ها» still matches «سامسونگ».
    return re.compile(rf"(?<!\w){re.escape(term)}(?!\w)", re.IGNORECASE)


def apply_lexicon(text: str, lexicon: list[dict[str, str]]) -> tuple[str, list[str]]:
    """Replace lexicon terms with their TTS spelling, longest term first.
    Returns the new text and the terms that were replaced. Captions keep the
    script spelling; only the text sent to the voice changes."""
    applied = []
    for row in sorted(lexicon, key=lambda r: len(r["term"]), reverse=True):
        text, count = _term_pattern(row["term"]).subn(row["tts"], text)
        if count:
            applied.append(row["term"])
    return text, applied


def apply_channel_lexicon(inputs: dict[str, Any]) -> tuple[dict[str, Any], list[str]]:
    """tts_selector hook: apply the channel's lexicon to `text` and `turns`."""
    lexicon = load_channel(inputs["channel"]).lexicon
    adapted = {k: v for k, v in inputs.items() if k != "channel"}
    applied: list[str] = []
    if adapted.get("text"):
        adapted["text"], hits = apply_lexicon(adapted["text"], lexicon)
        applied += hits
    if adapted.get("turns"):
        turns = []
        for turn in adapted["turns"]:
            new_text, hits = apply_lexicon(turn["text"], lexicon)
            applied += hits
            turns.append({**turn, "text": new_text})
        adapted["turns"] = turns
    return adapted, sorted(set(applied))


def suggest_lexicon(channel: Channel, misheard: list[tuple[str, str]], source: str,
                    min_count: int = 2) -> list[dict[str, Any]]:
    """Record words round-trip mishears. A word becomes a pending suggestion
    once it was misheard `min_count` times (across this call and earlier ones);
    the owner approves it into lexicon.tsv. Returns the pending rows."""
    path = channel.path / "lexicon_suggestions.tsv"
    rows = {r["expected"]: r for r in _read_tsv(path)}
    known = {r["term"] for r in channel.lexicon}
    for heard, expected in misheard:
        if not expected or expected in known:
            continue
        row = rows.setdefault(expected, {"expected": expected, "heard": "", "count": "0",
                                         "sources": "", "status": "watching"})
        heard_set = [h for h in row["heard"].split(" | ") if h]
        if heard and heard not in heard_set:
            heard_set.append(heard)
        row["heard"] = " | ".join(heard_set)
        row["count"] = str(int(row["count"] or 0) + 1)
        sources = [s for s in row["sources"].split(" | ") if s]
        if source not in sources:
            sources.append(source)
        row["sources"] = " | ".join(sources)
        if row["status"] == "watching" and int(row["count"]) >= min_count:
            row["status"] = "pending"
    ordered = sorted(rows.values(), key=lambda r: -int(r["count"] or 0))
    _write_tsv(path, SUGGESTION_FIELDS, ordered)
    return [r for r in ordered if r["status"] == "pending"]


def approve_lexicon(channel: Channel, term: str, tts: str, note: str = "") -> None:
    """Owner-approved entry: add (or replace) it in lexicon.tsv and mark the
    matching suggestion approved."""
    path = channel.path / "lexicon.tsv"
    rows = [r for r in _read_tsv(path) if r.get("term") != term]
    rows.append({"term": term, "tts": tts, "note": note})
    _write_tsv(path, LEXICON_FIELDS, rows)
    suggestions = channel.path / "lexicon_suggestions.tsv"
    if suggestions.exists():
        pending = _read_tsv(suggestions)
        for row in pending:
            if row["expected"] == term:
                row["status"] = "approved"
        _write_tsv(suggestions, SUGGESTION_FIELDS, pending)


def record_edit(channel: Channel, project: str, stage: str, before: str, after: str,
                note: str = "") -> Path:
    """Save one owner edit (script, title, caption...) as a before/after example."""
    path = channel.path / "examples" / f"{project}.jsonl"
    path.parent.mkdir(parents=True, exist_ok=True)
    entry = {
        "date": datetime.date.today().isoformat(),
        "stage": stage,
        "before": before,
        "after": after,
        "note": note,
    }
    with path.open("a", encoding="utf-8") as f:
        f.write(json.dumps(entry, ensure_ascii=False) + "\n")
    return path


def retro_path(channel: Channel, project: str, date: datetime.date | None = None) -> Path:
    date = date or datetime.date.today()
    return channel.path / "retros" / f"{date.isoformat()}-{project}.md"


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description="Channel bible helper")
    sub = parser.add_subparsers(dest="cmd", required=True)
    for name in ("show", "apply", "suggest", "approve", "create"):
        p = sub.add_parser(name)
        p.add_argument("--channel", required=True)
        if name == "apply":
            p.add_argument("--text", required=True)
        if name == "suggest":
            p.add_argument("--audition", required=True, help="fa_voice_audition results.json")
            p.add_argument("--min-count", type=int, default=2)
        if name == "approve":
            p.add_argument("--term", required=True)
            p.add_argument("--tts", required=True)
            p.add_argument("--note", default="")
    args = parser.parse_args(argv)

    from lib.env_loader import load_env

    load_env()
    if args.cmd == "create":
        print(create_channel(args.channel))
        return 0
    channel = load_channel(args.channel)
    if args.cmd == "show":
        print(json.dumps({
            "path": str(channel.path),
            "voices": channel.voices.get("roles", {}),
            "lexicon": len(channel.lexicon),
            "glossary": len(channel.glossary),
        }, ensure_ascii=False, indent=2))
    elif args.cmd == "apply":
        text, applied = apply_lexicon(args.text, channel.lexicon)
        print(json.dumps({"text": text, "applied": applied}, ensure_ascii=False))
    elif args.cmd == "suggest":
        results = json.loads(Path(args.audition).read_text(encoding="utf-8"))
        pending = []
        for take in results.get("drafts", []) + results.get("finals", []):
            pairs = [tuple(p) for p in take.get("misheard") or []]
            source = f"audition:{take['voice']}-{take['style']}-{take['model']}"
            pending = suggest_lexicon(channel, pairs, source, args.min_count)
        print(json.dumps({"pending": pending}, ensure_ascii=False, indent=2))
    elif args.cmd == "approve":
        approve_lexicon(channel, args.term, args.tts, args.note)
        print(f"approved {args.term} -> {args.tts}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
