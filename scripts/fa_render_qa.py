"""Quality gate for a Persian render. Writes a JSON report and prints a Persian summary.

    python scripts/fa_render_qa.py projects/<id>/renders/final.mp4 \
        --script projects/<id>/artifacts/script.json \
        --srt projects/<id>/assets/subtitles.srt \
        --workspace projects/<id>/hyperframes/index.html \
        --images projects/<id>/assets/images/*.png --check-images \
        --edit-plan projects/<id>/hyperframes/edit_pass.json --card full-history-in-n-minutes \
        --out projects/<id>/renders/qa.json

Free except --check-images (vision_bulk, about $0.0004 per image). Exit code
0 = pass, 1 = warnings, 2 = failures.
"""

from __future__ import annotations

import argparse
import glob
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from lib.fa_render_qa import parse_srt, persian_summary, run_qa  # noqa: E402
from styles.edit_style_loader import load_edit_style  # noqa: E402


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("render")
    parser.add_argument("--script", help="script artifact JSON")
    parser.add_argument("--srt", help="subtitles .srt")
    parser.add_argument("--captions-json", help="[{start, end, lines: [...]}]")
    parser.add_argument("--layout", help='caption layout JSON {"boxes": [{x,y,w,h} in 0-1], "safe_x", "safe_y"}')
    parser.add_argument("--workspace", help="HyperFrames/Remotion HTML entry to check RTL")
    parser.add_argument("--images", nargs="*", default=[], help="generated stills (globs ok)")
    parser.add_argument("--check-images", action="store_true", help="paid: ask vision_bulk about text in images")
    parser.add_argument("--freeze-max", type=float, default=6.0)
    parser.add_argument("--frames-dir", help="extract review frames here")
    parser.add_argument("--edit-plan", help="edit_pass.json (scripts/fa_edit_pass.py) for the edit-craft checks")
    parser.add_argument("--card", help="edit style card name for the cut-rhythm and beat checks")
    parser.add_argument("--out", help="report JSON path (default: <render>.qa.json)")
    args = parser.parse_args(argv)

    def read_json(p):
        return json.loads(Path(p).read_text(encoding="utf-8")) if p else None

    captions = None
    if args.srt:
        captions = parse_srt(Path(args.srt).read_text(encoding="utf-8"))
    elif args.captions_json:
        captions = read_json(args.captions_json)
    images = [Path(p) for pattern in args.images for p in sorted(glob.glob(pattern))]
    report = run_qa(
        Path(args.render),
        script=read_json(args.script),
        captions=captions,
        caption_layout=read_json(args.layout),
        workspace_html=Path(args.workspace).read_text(encoding="utf-8") if args.workspace else None,
        images=images if args.check_images else None,
        freeze_max=args.freeze_max,
        frames_dir=Path(args.frames_dir) if args.frames_dir else None,
        edit_plan=read_json(args.edit_plan),
        card=load_edit_style(args.card) if args.card else None,
    )
    summary = persian_summary(report)
    report["summary_fa"] = summary
    out = Path(args.out) if args.out else Path(args.render).with_suffix(".qa.json")
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    sys.stdout.buffer.write((summary + f"\n\n{out}\n").encode("utf-8"))
    return {"pass": 0, "warn": 1, "fail": 2}[report["status"]]


if __name__ == "__main__":
    raise SystemExit(main())
