"""Estimate a Persian production's cost and generation time before paying.

    python scripts/fa_estimate.py --plan docs/fa/examples/samsung_sample_plan.json
    python scripts/fa_estimate.py --scene-plan projects/<id>/artifacts/scene_plan.json \
        --script projects/<id>/artifacts/script.json --draft-rounds 2
    python scripts/fa_estimate.py --brief projects/<id>/artifacts/brief.json --json

Prints draft and final side by side. Prices: config/fa_pricing.yaml.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from lib.fa_cost_estimate import estimate, load_plan, load_pricing  # noqa: E402


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--plan")
    parser.add_argument("--scene-plan")
    parser.add_argument("--script")
    parser.add_argument("--brief")
    parser.add_argument("--mode", choices=["draft", "final", "both"], default="both")
    parser.add_argument("--draft-rounds", type=int, default=0,
                        help="draft passes over the images before the final pass")
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args(argv)

    pricing = load_pricing()
    plan = load_plan(args.plan, args.scene_plan, args.script, args.brief,
                     pricing["assumptions"]["seconds_per_image"])
    modes = ["draft", "final"] if args.mode == "both" else [args.mode]
    results = [estimate(plan, pricing, m, args.draft_rounds if m == "final" else 0) for m in modes]

    if args.json:
        print(json.dumps([r.to_dict() for r in results], ensure_ascii=False, indent=2))
        return 0
    for r in results:
        print(f"== {r.mode}: ${r.total_usd:.4f}  ({r.images} images, "
              f"{r.narration_seconds:.0f} s narration)")
        for line in r.lines:
            print(f"   {line.stage:<10} {line.provider:<7} {line.model:<36} "
                  f"{line.quantity:>6} {line.unit:<14} ${line.cost_usd:.4f}  {line.note}")
        print(f"   generation time: {r.seconds_serial:.0f} s serial, "
              f"{r.seconds_parallel:.0f} s with parallel_runner")
        for w in r.warnings:
            print(f"   WARNING: {w}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
