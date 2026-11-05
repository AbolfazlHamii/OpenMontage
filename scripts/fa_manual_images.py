"""Still-led video from images the owner makes in Nano Banana (lib/fa_manual_images.py).

    python scripts/fa_manual_images.py init    --project projects/<id>
      (the agent fills manual_images/shotlist.json from the approved script)
    python scripts/fa_manual_images.py prompts --project projects/<id>
      (the owner opens manual_images/prompts.html, makes the images, saves them in manual_images/in/)
    python scripts/fa_manual_images.py import  --project projects/<id> --from <ZAPI FLOW download folder>
      (or the owner pastes manual_images/zapi_flow.txt into ZAPI FLOW and this copies the results in)
    python scripts/fa_manual_images.py check   --project projects/<id>
    python scripts/fa_manual_images.py build   --project projects/<id> [--render]
    python scripts/fa_manual_images.py preview --project projects/<id> --upto 60 [--render]
      (the part built so far while images are still coming in; missing stills borrow a neighbour)
    python scripts/fa_manual_images.py status  --project projects/<id>
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from lib import fa_manual_images as mi  # noqa: E402


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    sub = parser.add_subparsers(dest="cmd", required=True)
    for name in ("init", "prompts", "import", "check", "build", "preview", "status"):
        p = sub.add_parser(name)
        p.add_argument("--project", required=True)
        if name in ("build", "preview"):
            p.add_argument("--render", action="store_true", help="also render and normalize to -14 LUFS")
        if name == "preview":
            p.add_argument("--upto", type=float, default=60.0, help="build up to this second of the video")
            p.add_argument("--from", dest="start", type=float, default=0.0, help="start at this second (whole scenes)")
        if name == "import":
            p.add_argument("--from", dest="folder", required=True, help="folder ZAPI FLOW downloaded into")
            p.add_argument("--by", choices=("auto", "serial", "time"), default="auto")
            p.add_argument("--overwrite", action="store_true", help="replace images already in in/")
    args = parser.parse_args(argv)

    from lib.env_loader import load_env

    load_env()
    project = Path(args.project)
    if args.cmd == "init":
        out = {"shotlist": str(mi.init(project))}
    elif args.cmd == "prompts":
        out = mi.write_prompt_pack(project)
    elif args.cmd == "import":
        out = mi.import_flow(project, Path(args.folder), by=args.by, overwrite=args.overwrite)
    elif args.cmd == "check":
        out = mi.check_images(project)
    elif args.cmd == "preview":
        out = mi.preview(project, args.upto, from_seconds=args.start, render_video=args.render)
    elif args.cmd == "build":
        out = mi.build(project, render_video=args.render)
    else:
        out = {"status": mi.status(project).summary()}
    print(json.dumps(out, ensure_ascii=False, indent=2))
    return 0 if out.get("ready", True) else 1


if __name__ == "__main__":
    raise SystemExit(main())
