"""LLM bake-off for the worker/bulk tiers on five real Persian-channel tasks.

    python scripts/llm_bakeoff.py --list            # candidates + worst-case cost, no calls
    python scripts/llm_bakeoff.py --run --cap 0.30  # run; stops starting calls past the cap
    python scripts/llm_bakeoff.py --report          # rebuild report.html from results + scores

Outputs in docs/fa/llm_bakeoff/: results.json (raw), scores.json (quality
scores written by the agent after reading the outputs), report.html (Persian
outputs side by side, RTL) for the owner to judge.
"""

from __future__ import annotations

import argparse
import html
import json
import sys
import threading
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from lib.parallel_runner import Job, run_parallel  # noqa: E402
from tools.text.openai_compat_llm import OpenAICompatLLM, validate_json  # noqa: E402

OUT_DIR = Path(__file__).resolve().parent.parent / "docs" / "fa" / "llm_bakeoff"
MAX_TOKENS = 2500

CANDIDATES = [
    {"profile": "avalai", "model": "kimi-k3.1-pro", "family": "Kimi"},
    {"profile": "avalai", "model": "kimi-k2.6", "family": "Kimi"},
    {"profile": "avalai", "model": "deepseek-v4.1-flash", "family": "DeepSeek"},
    {"profile": "avalai", "model": "qwen3.8-flash", "family": "Qwen"},
    {"profile": "avalai", "model": "gemini-3.8-flash", "family": "Gemini Flash"},
    {"profile": "avalai", "model": "gemini-3.1-flash-lite", "family": "Gemini Flash"},
    {"profile": "avalai", "model": "claude-haiku-5-5", "family": "Claude Haiku"},
    {"profile": "gemini", "model": "gemini-3.8-flash", "family": "Gemini direct",
     "price": {"input": 0.75, "output": 3.75}},
]

FA_SYSTEM = (
    "You write for a Persian-language YouTube channel (Iranian audience, "
    "colloquial Tehran Persian, energetic but accurate)."
)

TASKS = [
    {
        "id": "narration",
        "title": "پیش‌نویس narration محاوره‌ای",
        "json": False,
        "prompt": (
            "Write a 20-second Persian narration (about 55-65 words) in colloquial spoken "
            "Tehran Persian for a fast history video. Topic: in 1938 Lee Byung-chul opened a "
            "small trading shop in Daegu, Korea, selling dried fish, vegetables and noodles; "
            "it was called Samsung Sanghoe, 'three stars'. Open with a question to the viewer. "
            "Write numbers as words the narrator will say. Output only the narration."
        ),
    },
    {
        "id": "translation",
        "title": "ترجمه EN→FA",
        "json": False,
        "prompt": (
            "Translate into natural colloquial Persian for a voice-over (not word for word; "
            "keep facts exact):\n\n\"In 1995, Samsung's chairman ordered 150,000 faulty phones "
            "to be piled up in a factory yard in Gumi and set on fire in front of the "
            "employees. The message was simple: quality first, whatever it costs.\""
        ),
    },
    {
        "id": "image_prompts",
        "title": "prompt تصویر برای ۵ صحنه",
        "json": True,
        "schema": {
            "type": "object", "required": ["prompts"],
            "properties": {"prompts": {"type": "array", "minItems": 5, "maxItems": 5, "items": {
                "type": "object", "required": ["scene", "prompt"],
                "properties": {"scene": {"type": "integer"}, "prompt": {"type": "string", "minLength": 40}},
            }}},
        },
        "prompt": (
            "Write English image-generation prompts for 5 scenes of a 2D editorial illustration "
            "video (flat shapes, grain, limited palette: navy, cream, cobalt accent). No text, "
            "letters or logos may appear in any image. Scenes: 1) a phone in a viewer's hand, "
            "today; 2) a small 1938 Daegu storefront selling dried fish; 3) 1969 first "
            "electronics factory; 4) 1995 bonfire of phones in a factory yard, workers watching; "
            "5) a modern foldable phone on a pedestal. Return JSON: "
            '{"prompts": [{"scene": 1, "prompt": "..."}, ...]}'
        ),
    },
    {
        "id": "hooks",
        "title": "۱۰ هوک",
        "json": True,
        "schema": {
            "type": "object", "required": ["hooks"],
            "properties": {"hooks": {"type": "array", "minItems": 10, "maxItems": 10,
                                     "items": {"type": "string", "minLength": 10}}},
        },
        "prompt": (
            "Write 10 different opening hooks (first 3 seconds, max 18 words each) in "
            "colloquial Persian for a 90-second video 'The whole history of Samsung in 90 "
            "seconds'. Mix: big number, paradox of origins, direct question, shocking moment "
            "(1995 phone bonfire). Return JSON: {\"hooks\": [\"...\", ...]}"
        ),
    },
    {
        "id": "json_fill",
        "title": "پرکردن JSON",
        "json": True,
        "schema": {
            "type": "object", "required": ["events"],
            "properties": {"events": {"type": "array", "minItems": 5, "items": {
                "type": "object", "required": ["year", "event_fa", "category"],
                "properties": {
                    "year": {"type": "integer", "minimum": 1900, "maximum": 2030},
                    "event_fa": {"type": "string", "minLength": 5},
                    "category": {"type": "string", "enum": ["founding", "product", "crisis", "expansion"]},
                },
            }}},
        },
        "prompt": (
            "Extract the timeline from this text into JSON {\"events\": [{\"year\": int, "
            "\"event_fa\": short Persian description, \"category\": one of founding|product|"
            "crisis|expansion}]}. Text: Samsung was founded in 1938 as a trading company. It "
            "entered electronics in 1969, made its first semiconductor investment in 1974, "
            "burned 150,000 faulty phones in 1995, launched the first Galaxy S in 2010 and its "
            "first foldable phone in 2019."
        ),
    },
]


def worst_case(c: dict) -> float:
    llm = OpenAICompatLLM()
    price = llm.price_for(c["profile"], c["model"], c.get("price"))
    if not price:
        return float("nan")
    per_call = (600 * price["input"] + MAX_TOKENS * price["output"]) / 1e6
    return per_call * len(TASKS) * 1.5  # 1.5: room for one JSON repair on some tasks


def list_candidates() -> None:
    llm = OpenAICompatLLM()
    total = 0.0
    for c in CANDIDATES:
        ok, why = llm.profile_status(c["profile"])
        wc = worst_case(c)
        total += 0 if wc != wc else wc
        print(f"{c['family']:<14} {c['profile']:<7} {c['model']:<24} "
              f"worst ${wc:.3f}  {'ok' if ok else why}")
    print(f"worst case total ${total:.3f} (typical is a fraction of this)")


def run(cap: float) -> None:
    llm = OpenAICompatLLM()
    spent = [0.0]
    lock = threading.Lock()
    results = []

    def one(c, task):
        with lock:
            if spent[0] >= cap:
                return {"skipped": "cost cap reached"}
        started = time.monotonic()
        r = llm.execute({
            "profile": c["profile"], "model": c["model"], "price": c.get("price"),
            "system": FA_SYSTEM, "prompt": task["prompt"], "temperature": 0.7,
            "max_tokens": MAX_TOKENS, "json_mode": task["json"],
            "json_schema": task.get("schema"), "use_cache": False, "timeout_seconds": 120,
        })
        seconds = time.monotonic() - started
        with lock:
            spent[0] += r.cost_usd or 0.0
        valid = None
        if task["json"]:
            valid = r.success and validate_json(r.data.get("json"), task.get("schema")) is None
        return {
            "success": r.success, "error": r.error, "seconds": round(seconds, 2),
            "cost_usd": r.cost_usd, "usage": (r.data or {}).get("usage"),
            "repaired": (r.data or {}).get("repaired"), "json_valid": valid,
            "text": (r.data or {}).get("text"), "json": (r.data or {}).get("json"),
        }

    jobs = [Job(key=f"{c['profile']}|{c['model']}|{t['id']}", provider=c["profile"],
                fn=lambda c=c, t=t: one(c, t))
            for c in CANDIDATES for t in TASKS]
    report = run_parallel(jobs, limits={"avalai": 4, "gemini": 2})
    for job_result in report.results:
        profile, model, task = job_result.key.split("|")
        row = {"profile": profile, "model": model, "task": task}
        row.update(job_result.value if job_result.ok else {"success": False, "error": job_result.error})
        results.append(row)
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    payload = {"date": time.strftime("%Y-%m-%d"), "cap_usd": cap,
               "spent_usd": round(spent[0], 6), "max_tokens": MAX_TOKENS,
               "wall_seconds": round(report.seconds, 1), "results": results}
    (OUT_DIR / "results.json").write_text(json.dumps(payload, ensure_ascii=False, indent=2),
                                          encoding="utf-8")
    print(f"spent ${spent[0]:.4f} in {report.seconds:.0f} s; wrote {OUT_DIR / 'results.json'}")


def summarize(results: list[dict], scores: dict) -> list[dict]:
    rows = []
    for c in CANDIDATES:
        mine = [r for r in results if r["profile"] == c["profile"] and r["model"] == c["model"]]
        ok = [r for r in mine if r.get("success")]
        json_rows = [r for r in mine if r.get("json_valid") is not None or
                     next(t for t in TASKS if t["id"] == r["task"])["json"]]
        key = f"{c['profile']}|{c['model']}"
        s = scores.get(key, {})
        task_scores = [v for k, v in s.items() if k in {t["id"] for t in TASKS}]
        rows.append({
            "key": key, "family": c["family"], "profile": c["profile"], "model": c["model"],
            "ok": len(ok), "total": len(mine),
            "cost_usd": round(sum(r.get("cost_usd") or 0 for r in mine), 6),
            "seconds_avg": round(sum(r.get("seconds") or 0 for r in ok) / len(ok), 1) if ok else None,
            "json_valid": f"{sum(1 for r in json_rows if r.get('json_valid'))}/{len(json_rows)}",
            "out_tokens": sum((r.get("usage") or {}).get("completion_tokens", 0) for r in mine),
            "quality": round(sum(task_scores) / len(task_scores), 2) if task_scores else None,
            "note": s.get("note", ""),
        })
    return rows


def build_report() -> None:
    data = json.loads((OUT_DIR / "results.json").read_text(encoding="utf-8"))
    scores_path = OUT_DIR / "scores.json"
    scores = json.loads(scores_path.read_text(encoding="utf-8")) if scores_path.exists() else {}
    rows = summarize(data["results"], scores)
    esc = html.escape

    def cell(r):
        if not r.get("success"):
            return f"<div class='err'>{esc(str(r.get('error') or r.get('skipped') or 'failed'))}</div>"
        body = r.get("text") or ""
        if r.get("json") is not None:
            body = json.dumps(r["json"], ensure_ascii=False, indent=1)
        meta = f"${(r.get('cost_usd') or 0):.5f} · {r.get('seconds')} s"
        if r.get("json_valid") is not None:
            meta += " · JSON " + ("ok" if r["json_valid"] else "invalid")
        return f"<div class='meta'>{meta}</div><pre>{esc(body)}</pre>"

    summary = "".join(
        f"<tr><td>{esc(r['family'])}</td><td dir='ltr'>{esc(r['profile'])} / {esc(r['model'])}</td>"
        f"<td>{r['ok']}/{r['total']}</td><td>${r['cost_usd']:.4f}</td><td>{r['seconds_avg'] or '–'}</td>"
        f"<td>{r['json_valid']}</td><td>{r['out_tokens']}</td>"
        f"<td>{r['quality'] if r['quality'] is not None else '–'}</td><td>{esc(r['note'])}</td></tr>"
        for r in rows)
    sections = []
    for t in TASKS:
        cols = "".join(
            f"<div class='card'><h4 dir='ltr'>{esc(c['model'])} <small>({esc(c['profile'])})</small>"
            f"{' · ' + str(scores.get(c['profile'] + '|' + c['model'], {}).get(t['id'])) + '/5' if scores.get(c['profile'] + '|' + c['model'], {}).get(t['id']) else ''}</h4>"
            + cell(next((r for r in data['results'] if r['profile'] == c['profile']
                         and r['model'] == c['model'] and r['task'] == t['id']), {}))
            + "</div>"
            for c in CANDIDATES)
        sections.append(f"<section><h2>{esc(t['title'])}</h2><details><summary>prompt</summary>"
                        f"<pre dir='ltr'>{esc(t['prompt'])}</pre></details><div class='grid'>{cols}</div></section>")
    page = f"""<!doctype html><html lang="fa" dir="rtl"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1"><title>LLM bake-off</title>
<style>
body{{font-family:Vazirmatn,Tahoma,sans-serif;margin:16px;background:#fbfaf7;color:#1b1f2a;line-height:1.7}}
table{{border-collapse:collapse;width:100%;font-size:14px}}td,th{{border:1px solid #ddd;padding:4px 8px;text-align:start}}
.grid{{display:grid;grid-template-columns:repeat(auto-fill,minmax(320px,1fr));gap:12px}}
.card{{background:#fff;border:1px solid #e3e0d8;border-radius:8px;padding:8px}}
.card h4{{margin:0 0 4px;font-size:14px}}pre{{white-space:pre-wrap;font-family:inherit;margin:0;font-size:15px}}
.meta{{color:#666;font-size:12px}}.err{{color:#a12;font-size:13px}}section{{margin-top:28px}}
</style></head><body>
<h1>مقایسه مدل‌ها برای کارهای worker/bulk</h1>
<p>تاریخ {esc(data['date'])} · هزینه کل ${data['spent_usd']:.4f} (سقف ${data['cap_usd']}) · سقف خروجی هر پاسخ {data['max_tokens']} توکن.
امتیاز کیفیت (۱ تا ۵) را ایجنت بعد از خواندن خروجی‌ها داده؛ تصمیم نهایی با شماست.</p>
<table><tr><th>خانواده</th><th>مدل</th><th>موفق</th><th>هزینه</th><th>ثانیه (میانگین)</th><th>JSON معتبر</th><th>توکن خروجی</th><th>کیفیت</th><th>یادداشت</th></tr>{summary}</table>
{''.join(sections)}
</body></html>"""
    (OUT_DIR / "report.html").write_text(page, encoding="utf-8")
    (OUT_DIR / "summary.json").write_text(json.dumps(rows, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"wrote {OUT_DIR / 'report.html'}")


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--list", action="store_true")
    parser.add_argument("--run", action="store_true")
    parser.add_argument("--report", action="store_true")
    parser.add_argument("--cap", type=float, default=0.30)
    args = parser.parse_args(argv)
    if args.list or not (args.run or args.report):
        list_candidates()
    if args.run:
        run(args.cap)
    if args.run or args.report:
        build_report()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
