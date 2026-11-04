"""Refresh config/fa_pricing.yaml from AvalAI's public model catalog.

    python scripts/fa_pricing_update.py            # update in place
    python scripts/fa_pricing_update.py --dry-run  # show changes only

Only models already in the table are updated; a model missing from the
catalog is reported, not removed. One attempt direct, one through the local
proxy (127.0.0.1:10808) if the first fails; 30 s timeout each.
"""

from __future__ import annotations

import argparse
import datetime
import sys
from pathlib import Path
from typing import Any

import requests
import yaml

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from lib.fa_cost_estimate import PRICING_PATH  # noqa: E402

CATALOG_URL = "https://api.avalai.ir/public/models"
PROXY = "http://127.0.0.1:10808"
SIZE_KEYS = {
    "1K": "output_cost_per_image",
    "2K": "output_cost_per_image_2048x2048",
    "4K": "output_cost_per_image_4096x4096",
}


def fetch_catalog(timeout: float = 30) -> dict[str, dict[str, Any]]:
    last = None
    for proxies in (None, {"https": PROXY, "http": PROXY}):
        try:
            resp = requests.get(CATALOG_URL, timeout=timeout, proxies=proxies)
            resp.raise_for_status()
            return {m["id"]: m for m in resp.json()["data"]}
        except Exception as exc:  # one direct try, one proxied try
            last = exc
    raise RuntimeError(f"catalog unreachable: {type(last).__name__}")


def apply_catalog(table: dict[str, Any], catalog: dict[str, dict[str, Any]],
                  today: datetime.date) -> tuple[dict[str, Any], list[str]]:
    notes: list[str] = []

    def note_change(where, old, new):
        if old != new:
            notes.append(f"{where}: {old} -> {new}")

    for model, sizes in table.get("images", {}).get("avalai", {}).items():
        pricing = (catalog.get(model) or {}).get("pricing")
        if not pricing:
            notes.append(f"images/{model}: not in catalog (kept)")
            continue
        for size, key in SIZE_KEYS.items():
            if size in sizes and key in pricing:
                note_change(f"images/{model}/{size}", sizes[size], pricing[key])
                sizes[size] = pricing[key]
    for section in ("tts", "llm"):
        for model, price in table.get(section, {}).get("avalai", {}).items():
            pricing = (catalog.get(model) or {}).get("pricing")
            if not pricing:
                notes.append(f"{section}/{model}: not in catalog (kept)")
                continue
            for k in ("input", "output"):
                if pricing.get(k) is not None:
                    note_change(f"{section}/{model}/{k}", price[k], float(pricing[k]))
                    price[k] = float(pricing[k])
    table["updated"] = today.isoformat()
    return table, notes


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args(argv)

    text = PRICING_PATH.read_text(encoding="utf-8")
    header = "".join(l + "\n" for l in text.splitlines() if l.startswith("#") and not l.startswith("# Fitted"))
    table = yaml.safe_load(text)
    try:
        catalog = fetch_catalog()
    except RuntimeError as exc:
        print(f"Not updated: {exc}. Prices stay dated {table['updated']}.")
        return 1
    assumptions_comment = (
        "# Fitted from the Samsung sample (docs/fa/BASELINE.md): 6.6 s and 7.76 s of\n"
        "# narration billed $0.001499 and $0.001764 at $9/M audio tokens.\n"
    )
    table, notes = apply_catalog(table, catalog, datetime.date.today())
    for n in notes or ["no price changes"]:
        print(n)
    if args.dry_run:
        return 0
    assumptions = table.pop("assumptions", None)
    body = yaml.safe_dump(table, sort_keys=False, allow_unicode=True)
    if assumptions:
        body += assumptions_comment + yaml.safe_dump({"assumptions": assumptions}, sort_keys=False)
    PRICING_PATH.write_text(header + body, encoding="utf-8")
    print(f"Wrote {PRICING_PATH} (updated {table['updated']})")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
