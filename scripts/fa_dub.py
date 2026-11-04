"""Persian dub of an existing video, stage by stage (lib/fa_dub.py).

    python scripts/fa_dub.py prepare   --project projects/<id> --source video.mp4 --rights own
    python scripts/fa_dub.py translate --project projects/<id> [--analysis gemini_analysis.json]
      (review dub/segments_fa.json, then:)
    python scripts/fa_dub.py approve   --project projects/<id> [--ids s001,s002]
    python scripts/fa_dub.py synth     --project projects/<id>
      or, with voice actors:
    python scripts/fa_dub.py export-vo --project projects/<id>
    python scripts/fa_dub.py import-vo --project projects/<id> --takes <folder>
    python scripts/fa_dub.py mix       --project projects/<id>
    python scripts/fa_dub.py qa        --project projects/<id>
    python scripts/fa_dub.py status    --project projects/<id>
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from lib import fa_dub  # noqa: E402


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    sub = parser.add_subparsers(dest="cmd", required=True)
    for name in ("prepare", "translate", "approve", "synth", "export-vo", "import-vo", "mix", "qa", "status"):
        p = sub.add_parser(name)
        p.add_argument("--project", required=True)
        if name == "prepare":
            p.add_argument("--source", required=True)
            p.add_argument("--rights", choices=fa_dub.RIGHTS, default="unknown")
            p.add_argument("--language", default="en")
            p.add_argument("--channel", default="fa-main")
        if name == "translate":
            p.add_argument("--analysis", help="gemini_video_analyze JSON for per-line styles")
        if name == "approve":
            p.add_argument("--ids", help="comma-separated line ids (default: all)")
        if name == "synth":
            p.add_argument("--allow-drafts", action="store_true",
                           help="synthesize unreviewed lines (samples only)")
            p.add_argument("--providers", help="TTS providers in order, e.g. avalai (default: voices.yaml)")
            p.add_argument("--no-rewrite", action="store_true",
                           help="no worker rewrites: long lines use the next pause or get flagged")
        if name == "import-vo":
            p.add_argument("--takes", required=True)
        if name == "qa":
            p.add_argument("--no-round-trip", action="store_true")
    args = parser.parse_args(argv)

    from lib.env_loader import load_env

    load_env()
    project = Path(args.project)
    if args.cmd == "prepare":
        out = fa_dub.prepare(project, Path(args.source), source_language=args.language,
                             channel=args.channel, rights=args.rights)
    elif args.cmd == "translate":
        analysis = json.loads(Path(args.analysis).read_text(encoding="utf-8")) if args.analysis else None
        out = fa_dub.draft_translation(project, analysis=analysis)
    elif args.cmd == "approve":
        out = {"approved": fa_dub.approve_lines(project, args.ids.split(",") if args.ids else None)}
    elif args.cmd == "synth":
        out = fa_dub.synthesize(project, allow_drafts=args.allow_drafts, rewrites=not args.no_rewrite,
                                providers=args.providers.split(",") if args.providers else None)
    elif args.cmd == "export-vo":
        out = {"scripts": [str(p) for p in fa_dub.export_vo(project)]}
    elif args.cmd == "import-vo":
        out = fa_dub.import_vo(project, Path(args.takes))
    elif args.cmd == "mix":
        out = fa_dub.mix(project)
    elif args.cmd == "qa":
        out = fa_dub.qa(project, check_round_trip=not args.no_round_trip)
    else:
        out = fa_dub.status(project)
    print(json.dumps(out, ensure_ascii=False, indent=2))
    return 0 if out.get("pass", True) else 1


if __name__ == "__main__":
    raise SystemExit(main())
