"""Offline test of "The Archivist" live character (nothing goes live).

    python scripts/archivist_test.py assets   # stills (AvalAI Gemini image, ~$0.10 each)
    python scripts/archivist_test.py chat     # fake chat -> moderation + answers (Dahl)
    python scripts/archivist_test.py voice    # every spoken line (AvalAI Gemini TTS)
    python scripts/archivist_test.py render   # sample MP4 + contact sheet
    python scripts/archivist_test.py all

Work files go to projects/archivist-live-fa/ (git-ignored, regenerable).
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO))

from lib.env_loader import load_env  # noqa: E402

WORK = REPO / "projects" / "archivist-live-fa"
CHAT = REPO / "lib" / "archivist" / "test_chat.json"


def cmd_assets(args) -> None:
    from lib.archivist.assets import generate

    # AvalAI uploads fail through the local proxy (SSL EOF); Google (TTS)
    # needs it from Iran, so only this step goes direct.
    for var in ("HTTPS_PROXY", "HTTP_PROXY", "https_proxy", "http_proxy"):
        os.environ.pop(var, None)
    os.environ["NO_PROXY"] = "*"

    print(json.dumps(generate(WORK / "stills"), ensure_ascii=False, indent=1))


def cmd_chat(args) -> None:
    from lib.archivist.brain import Brain

    brain = Brain()
    messages = json.loads(CHAT.read_text(encoding="utf-8"))["messages"]
    turns = []
    for msg in messages:
        turn = brain.handle(msg["user"], msg["text"])
        row = {**turn.__dict__, "t": msg["t"], "expect": msg["expect"]}
        turns.append(row)
        print(f"{msg['user']}: {turn.category} -> {turn.action} {turn.latency_s} {turn.notes}", flush=True)
    WORK.mkdir(parents=True, exist_ok=True)
    (WORK / "turns.json").write_text(json.dumps(turns, ensure_ascii=False, indent=1), encoding="utf-8")


def cmd_voice(args) -> None:
    from lib.archivist.show import voice_all

    print(json.dumps(voice_all(WORK, force=args.force), ensure_ascii=False, indent=1))


def cmd_render(args) -> None:
    from lib.archivist.show import render_sample

    print(json.dumps(render_sample(WORK, seconds=args.seconds), ensure_ascii=False, indent=1))


def main() -> None:
    load_env()
    parser = argparse.ArgumentParser()
    parser.add_argument("step", choices=["assets", "chat", "voice", "render", "all"])
    parser.add_argument("--force", action="store_true", help="re-voice cached lines")
    parser.add_argument("--seconds", type=float, default=0, help="render only the first N seconds")
    args = parser.parse_args()
    steps = ["assets", "chat", "voice", "render"] if args.step == "all" else [args.step]
    for step in steps:
        globals()[f"cmd_{step}"](args)


if __name__ == "__main__":
    main()
