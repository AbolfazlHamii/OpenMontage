"""Studio FA CLI.

    python -m studio_fa [--port N] [--no-browser]
"""

from __future__ import annotations

import argparse
import os
import threading
import webbrowser

from studio_fa import DEFAULT_PORT


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="studio_fa", description=__doc__)
    parser.add_argument("--port", type=int, default=int(os.environ.get("STUDIO_FA_PORT", DEFAULT_PORT)))
    parser.add_argument("--no-browser", action="store_true")
    args = parser.parse_args(argv)

    import uvicorn

    url = f"http://127.0.0.1:{args.port}/"
    if not args.no_browser:
        threading.Timer(1.2, webbrowser.open, args=(url,)).start()
    print(f"studio_fa: {url}")
    uvicorn.run("studio_fa.server:app", host="127.0.0.1", port=args.port, log_level="warning")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
