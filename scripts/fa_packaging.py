"""Packaging for a Persian video: title drafts, title/topic scores, description.

    # 15 title drafts from the worker tier, scored (cents; the agent reviews them)
    python scripts/fa_packaging.py titles --brief title_brief.json --out <dir> \
        --cost-log projects/<id>/cost_log.json
    python scripts/fa_packaging.py titles --brief title_brief.json --out <dir> --dry-run

    # score titles you wrote (one per line, or a JSON list)
    python scripts/fa_packaging.py score-titles --titles titles.txt --keyword سامسونگ

    # rank candidate topics (criteria 0-5 per topic; see youtube-packaging.md)
    python scripts/fa_packaging.py topics --topics topics.json --out ranked_topics.json

    # description, chapters, tags from the script (and scene plan) + reviewed lines
    python scripts/fa_packaging.py describe --script projects/<id>/artifacts/script.json \
        --meta packaging_meta.json --out <dir>

`describe` writes description.txt, chapters.txt, tags.txt and metadata.json in
the shape export_bundle takes. Rules: skills/creative/youtube-packaging.md.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from lib import fa_packaging as fp  # noqa: E402


def _read_json(path: str):
    return json.loads(Path(path).read_text(encoding="utf-8"))


def _write(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")


def _print(text: str) -> None:
    sys.stdout.buffer.write((text + "\n").encode("utf-8"))


def cmd_titles(args) -> int:
    brief = _read_json(args.brief)
    out = Path(args.out)
    if args.dry_run:
        _write(out / "title_prompt.txt", fp.title_prompt(brief))
        _print(fp.title_prompt(brief))
        return 0
    # AvalAI must be reached directly from Iran; the router's profile says so too.
    no_proxy = os.environ.get("NO_PROXY", "")
    if "api.avalai.ir" not in no_proxy:
        os.environ["NO_PROXY"] = ",".join(p for p in (no_proxy, "api.avalai.ir") if p)
    result = fp.draft_titles(brief, cost_log_path=args.cost_log)
    _write(out / "titles_draft.json", json.dumps(result, ensure_ascii=False, indent=2))
    if not result["success"]:
        _print(f"failed: {result['error']}")
        return 1
    _print(f"{len(result['drafts'])} drafts from {result['model']} ({result['tier']}), "
           f"${result['cost_usd']:.4f}")
    for d in result["drafts"]:
        _print(f"{d['score']:>3}  {d['title']}  [{d.get('pattern', '')}]")
    _print(f"saved {out / 'titles_draft.json'} (drafts only: review before use)")
    return 0


def cmd_score_titles(args) -> int:
    path = Path(args.titles)
    text = path.read_text(encoding="utf-8")
    titles = json.loads(text) if path.suffix == ".json" else [t for t in text.splitlines() if t.strip()]
    titles = [t["title"] if isinstance(t, dict) else t for t in titles]
    rows = [fp.score_title(t, args.keyword, args.alias) for t in titles]
    if args.out:
        _write(Path(args.out), json.dumps(rows, ensure_ascii=False, indent=2))
    for r in sorted(rows, key=lambda r: r["score"], reverse=True):
        _print(f"{r['score']:>3}  {r['chars']:>3} ch  {r['title']}")
        for note in r["notes"]:
            _print(f"          - {note}")
    return 0


def cmd_topics(args) -> int:
    ranked = fp.rank_topics(_read_json(args.topics))
    if args.out:
        _write(Path(args.out), json.dumps(ranked, ensure_ascii=False, indent=2))
    for t in ranked:
        _print(f"{t['rank']:>2}. {t['score']:>5}  {t['name']}  ({t['verdict']})")
    return 0


def cmd_describe(args) -> int:
    meta = _read_json(args.meta)
    sections = []
    if args.script:
        sections = _read_json(args.script).get("sections", [])
    if args.scene_plan and not any(s.get("chapter") or s.get("label") for s in sections):
        sections = _read_json(args.scene_plan).get("scenes", [])
    # Reviewed chapter titles may be given per section id in the meta file.
    names = meta.get("chapters", {})
    for s in sections:
        if s.get("id") in names:
            s["chapter"] = names[s["id"]]
    chapters, notes = fp.build_chapters(sections)

    sources = meta.get("sources")
    if sources is None and args.research:
        sources = [{"title": s.get("title", ""), "url": s["url"]}
                   for s in _read_json(args.research).get("sources", []) if s.get("url")]
    description = fp.build_description(
        meta["hook"], meta.get("summary", ""), chapters, sources=sources,
        music=meta.get("music", ""), series_line=meta.get("series_line", ""),
        hashtags=meta.get("hashtags", []), cta=meta.get("cta", ""))
    report = fp.description_report(description, meta.get("keyword", ""))
    tags = fp.build_tags(meta.get("keyword", ""), meta.get("aliases", []), meta.get("extra_tags", []),
                         meta.get("series", ""))

    out = Path(args.out)
    _write(out / "description.txt", description)
    _write(out / "chapters.txt", "\n".join(fp.chapter_lines(chapters)) + ("\n" if chapters else ""))
    _write(out / "tags.txt", "\n".join(tags) + "\n")
    metadata = {
        "title": meta.get("title", ""),
        "description": description,
        "tags": tags,
        "hashtags": [fp.hashtag(h) for h in meta.get("hashtags", [])][:fp.HASHTAGS_SHOWN],
        "chapters": chapters,
        "chapter_notes": notes,
        "checks": report,
        "draft": bool(meta.get("draft")),
    }
    _write(out / "metadata.json", json.dumps(metadata, ensure_ascii=False, indent=2))
    _print(description)
    for line in notes + report["problems"]:
        _print(f"- {line}")
    _print(f"{len(tags)} tags, {sum(len(t) for t in tags) + len(tags) - 1} characters")
    return 0 if not report["problems"] else 1


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    sub = parser.add_subparsers(dest="command", required=True)

    p = sub.add_parser("titles", help="title drafts from the worker tier, scored")
    p.add_argument("--brief", required=True)
    p.add_argument("--out", required=True)
    p.add_argument("--cost-log")
    p.add_argument("--dry-run", action="store_true", help="write the prompt only, no API call")
    p.set_defaults(fn=cmd_titles)

    p = sub.add_parser("score-titles", help="score titles you wrote")
    p.add_argument("--titles", required=True)
    p.add_argument("--keyword", default="")
    p.add_argument("--alias", action="append", default=[])
    p.add_argument("--out")
    p.set_defaults(fn=cmd_score_titles)

    p = sub.add_parser("topics", help="rank candidate topics")
    p.add_argument("--topics", required=True)
    p.add_argument("--out")
    p.set_defaults(fn=cmd_topics)

    p = sub.add_parser("describe", help="description, chapters and tags")
    p.add_argument("--script")
    p.add_argument("--scene-plan")
    p.add_argument("--research", help="research_brief.json; its sources go in the description")
    p.add_argument("--meta", required=True, help="reviewed hook, summary, keyword, hashtags, music")
    p.add_argument("--out", required=True)
    p.set_defaults(fn=cmd_describe)

    args = parser.parse_args(argv)
    return args.fn(args)


if __name__ == "__main__":
    sys.exit(main())
