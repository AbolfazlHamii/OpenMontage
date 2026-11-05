"""From a link to a Persian remake kit, in one command.

    python scripts/fa_remake.py https://www.youtube.com/shorts/<id>
    python scripts/fa_remake.py "https://www.youtube.com/watch?v=<id>" --target 90
    python scripts/fa_remake.py https://www.instagram.com/reel/<id>/ --cookies cookies.txt
    python scripts/fa_remake.py my_video.mp4 --mode dub --rights own

Writes projects/_reference/<slug>/ (video, transcript, outline, style card,
Gemini analysis, Persian translation draft, claims, remake_brief.json) and
prints REMAKE_fa.md. Paid analysis stays under --budget (default $0.10);
steps over it are skipped and listed. Next steps: skills/meta/remake-from-link.md.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from tools.analysis.reference_kit import ReferenceKit  # noqa: E402


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("source", help="URL (YouTube, Shorts, Instagram, TikTok, X...) or a local video")
    parser.add_argument("--mode", choices=["transcreate", "dub"], default="transcreate")
    parser.add_argument("--rights", choices=["unknown", "own", "licensed", "permission"], default="unknown")
    parser.add_argument("--target", type=float, help="length of the Persian version in seconds")
    parser.add_argument("--budget", type=float, default=0.10, help="USD cap for paid analysis")
    parser.add_argument("--cookies", help="cookies.txt exported from a logged-in browser (Instagram)")
    parser.add_argument("--slug")
    parser.add_argument("--language", help="source language code (default: from the video)")
    parser.add_argument("--steps", nargs="*", choices=list(ReferenceKit.ALL_STEPS))
    args = parser.parse_args(argv)

    is_url = args.source.startswith(("http://", "https://"))
    inputs = {"url" if is_url else "input_path": args.source, "mode": args.mode, "rights": args.rights,
              "budget_usd": args.budget}
    for key, value in (("target_seconds", args.target), ("cookies_file", args.cookies), ("slug", args.slug),
                       ("language", args.language), ("steps", args.steps)):
        if value:
            inputs[key] = value
    result = ReferenceKit().execute(inputs)
    if not result.success:
        sys.stdout.buffer.write(f"نشد: {result.error}\n".encode("utf-8"))
        return 1
    folder = Path(result.data["folder"])
    text = (folder / "REMAKE_fa.md").read_text(encoding="utf-8")
    sys.stdout.buffer.write((text + f"\n{folder}\n").encode("utf-8"))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
