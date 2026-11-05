"""Persian YouTube thumbnails: three A/B variants from one still, plus a phone check.

Quick (same words in all three templates):
    python scripts/fa_thumbnail.py --background still.png --text "با ماهی شروع شد" \
        --year 1938 --title "کل تاریخ سامسونگ در ۹۰ ثانیه" --out projects/<id>/packaging/thumbnails

Full control (per-variant words, focus, zoom, ring):
    python scripts/fa_thumbnail.py --spec thumbnails_spec.json --out <dir>

Spec: {"background": "...", "title": "...", "defaults": {"focus": [0.45, 0.6]},
       "variants": [{"id": "A", "template": "punch", "headline": "...", "kicker": "..."}, ...]}
Templates: punch, era, question (styles/thumbnails/fa/). Writes thumb_<id>.png
(master), thumb_<id>.jpg (upload, <= 2 MB), preview_phone.png and thumbnails.json.
Look at the PNGs and the preview before choosing. Rules: skills/creative/youtube-packaging.md.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from lib.fa_thumbnail import Variant, default_variants, make_thumbnails  # noqa: E402


def _floats(text: str | None) -> tuple[float, ...] | None:
    return tuple(float(v) for v in text.split(",")) if text else None


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--spec", help="JSON spec with per-variant settings")
    parser.add_argument("--background", help="text-free still (any size, 16:9 is best)")
    parser.add_argument("--text", help="2-4 words; '|' splits two lines")
    parser.add_argument("--kicker", default="")
    parser.add_argument("--year", default="")
    parser.add_argument("--focus", help="x,y of the subject in the still, 0-1 (default 0.5,0.5)")
    parser.add_argument("--ring", help="x,y,radius of the ring in variant C, frame fractions")
    parser.add_argument("--title", default="", help="the video title (checks the thumbnail does not repeat it)")
    parser.add_argument("--out", required=True)
    parser.add_argument("--chrome", help="Chrome/Chromium path (default: CHROME_PATH or the usual install)")
    args = parser.parse_args(argv)

    if args.spec:
        spec_path = Path(args.spec)
        spec = json.loads(spec_path.read_text(encoding="utf-8"))
        background = Path(spec["background"])
        if not background.is_absolute():
            background = (spec_path.parent / background).resolve()
        title = spec.get("title", args.title)
        variants = [Variant.from_dict(v, spec.get("defaults")) for v in spec["variants"]]
        palette = spec.get("palette")
    elif args.background and args.text:
        background = Path(args.background)
        title = args.title
        variants = default_variants(args.text, args.kicker, args.year,
                                    _floats(args.focus) or (0.5, 0.5), _floats(args.ring))
        palette = None
    else:
        parser.error("give --spec, or --background with --text")

    report = make_thumbnails(background, variants, Path(args.out), title=title,
                             chrome=args.chrome, palette=palette)
    for v in report["variants"]:
        status = "ok  " if v["passed"] else "FAIL"
        print(f"{status} {v['id']} {v['template']:<8} phone px {v['phone_px']}  "
              f"contrast {v['contrast']}  jpg {v['jpg_bytes'] // 1024} KB")
        for line in v["problems"] + v["warnings"]:
            print(f"       - {line}")
    print(f"preview: {report['preview']}")
    print(f"report:  {Path(args.out) / 'thumbnails.json'}")
    return 0 if report["all_passed"] else 1


if __name__ == "__main__":
    sys.exit(main())
