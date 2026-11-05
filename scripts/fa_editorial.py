"""Hook lab and fact-check steps for a Persian production.

    # 12 hook drafts from the worker tier -> projects/<id>/artifacts/hooks.json
    python scripts/fa_editorial.py hooks --project projects/<id> --topic "کل تاریخ سامسونگ در ۹۰ ثانیه" --brief brief.txt
    # agent writes its shortlist into hooks.json ("shortlist": [{index, reason, score}]), then:
    python scripts/fa_editorial.py log-hooks --project projects/<id> [--owner-pick 7]

    # claims from the script (bulk tier) -> projects/<id>/artifacts/claims.json
    python scripts/fa_editorial.py claims --project projects/<id>
    # agent fills verdict/source for each claim, then:
    python scripts/fa_editorial.py log-claims --project projects/<id>
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from lib import fa_editorial as ed  # noqa: E402


def _read(p: Path):
    return json.loads(p.read_text(encoding="utf-8"))


def _write(p: Path, data) -> None:
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("step", choices=["hooks", "log-hooks", "claims", "log-claims"])
    parser.add_argument("--project", required=True)
    parser.add_argument("--topic")
    parser.add_argument("--brief", help="text file with the facts the hooks may use")
    parser.add_argument("--script", help="script artifact (default artifacts/script.json)")
    parser.add_argument("--owner-pick", type=int)
    args = parser.parse_args(argv)

    project = Path(args.project)
    hooks_path = project / "artifacts" / "hooks.json"
    claims_path = project / "artifacts" / "claims.json"
    log_path = project / "decision_log.json"

    if args.step in ("hooks", "claims"):
        from tools.text.llm_selector import LLMSelector

        llm = LLMSelector()
        if args.step == "hooks":
            brief = Path(args.brief).read_text(encoding="utf-8") if args.brief else ""
            data, cost, err = ed.draft(llm, "hooks", ed.hooks_prompt(args.topic or "", brief), ed.HOOKS_SCHEMA)
            out = {"status": "drafts_for_agent", "hooks": ed.annotate_hooks((data or {}).get("hooks", [])),
                   "shortlist": [], "cost_usd": cost, "error": err}
            _write(hooks_path, out)
        else:
            script = _read(Path(args.script) if args.script else project / "artifacts" / "script.json")
            data, cost, err = ed.draft(llm, "claim_extraction", ed.claims_prompt(ed.script_text(script)),
                                       ed.CLAIMS_SCHEMA)
            claims = [{**c, "verdict": "unverified", "source": None, "note": ""}
                      for c in (data or {}).get("claims", [])]
            out = {"status": "to_verify", "claims": claims, "cost_usd": cost, "error": err}
            _write(claims_path, out)
        print(json.dumps({"written": str(hooks_path if args.step == "hooks" else claims_path),
                          "cost_usd": cost, "error": err}, ensure_ascii=False))
        return 0 if not err else 1

    if args.step == "log-hooks":
        data = _read(hooks_path)
        if len(data.get("shortlist", [])) != 3:
            print("hooks.json needs a shortlist of exactly 3 (agent's pick with reasons)")
            return 1
        entry = ed.append_decision(log_path, ed.hook_decision(data["hooks"], data["shortlist"], args.owner_pick))
    else:
        entry = ed.append_decision(log_path, ed.fact_check_decision(_read(claims_path)["claims"]))
    print(json.dumps({"logged": entry["decision_id"], "selected": entry["selected"]}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
