"""Retention lint for a Persian narration script, before any audio is made.

    python scripts/fa_script_lint.py draft.txt --target 90
    python scripts/fa_script_lint.py projects/<id>/artifacts/script.json --voice Charon --style calm
    python scripts/fa_script_lint.py draft.txt --llm      # + worker-tier open-loop draft (cents)

Plain text: one section per line, '#' line = title. Prints a Persian summary
and writes <input>.lint.json (or --out). Exit code 0 = low risk, 1 = medium,
2 = high. Checks and thresholds: skills/creative/narration-craft.md.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from lib.fa_script_lint import DEFAULT_CPS, lint, load_script, persian_summary  # noqa: E402

VOICES = Path(__file__).resolve().parent.parent.parent / "channels" / "fa-main" / "voices.yaml"


def voice_cps(voice: str, style: str | None = None, path: Path = VOICES) -> float | None:
    """Measured letters-per-second from the channel bible: a role (`narrator`)
    or an auditioned voice (`Charon`, optionally with its style)."""
    if not path.exists():
        return None
    import yaml

    data = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    role = (data.get("roles") or {}).get(voice)
    if role and role.get("cps"):
        return float(role["cps"])
    for key, rows in data.items():
        if not key.startswith("audition") or not isinstance(rows, list):
            continue
        for row in rows:
            if str(row.get("voice", "")).lower() == voice.lower() and (style is None or row.get("style") == style):
                return float(row["cps"])
    return None


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("script")
    parser.add_argument("--target", type=float, help="target length in seconds")
    parser.add_argument("--cps", type=float, help="narrator letters per second")
    parser.add_argument("--voice", help="role or auditioned voice in channels/fa-main/voices.yaml")
    parser.add_argument("--style", help="audition style for --voice (calm / energetic)")
    parser.add_argument("--names", nargs="*", default=[], help="proper names to count as specifics")
    parser.add_argument("--llm", action="store_true", help="paid: worker-tier draft of open loops")
    parser.add_argument("--out")
    args = parser.parse_args(argv)

    cps = args.cps or (voice_cps(args.voice, args.style) if args.voice else None) or DEFAULT_CPS
    llm = None
    if args.llm:
        from tools.text.llm_selector import LLMSelector
        llm = LLMSelector()
    path = Path(args.script)
    report = lint(load_script(path), cps=cps, target=args.target, names=args.names, llm=llm)
    out = Path(args.out) if args.out else path.with_suffix(".lint.json")
    out.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    sys.stdout.buffer.write((persian_summary(report) + f"\n\n{out}\n").encode("utf-8"))
    return {"low": 0, "medium": 1, "high": 2}[report["risk"]]


if __name__ == "__main__":
    raise SystemExit(main())
