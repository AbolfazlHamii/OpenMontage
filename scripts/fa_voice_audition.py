"""Audition Gemini voices for the Persian channel narrator.

    python scripts/fa_voice_audition.py --dry-run
    python scripts/fa_voice_audition.py --out projects/_voice_audition/2026-11-04

Renders one fixed story paragraph (numbers, foreign names, an excited line)
with 6 voices x 2 styles on the lite TTS model, measures each clip
(duration, characters per second, round-trip similarity: the clip is
transcribed and compared with the script, numbers as words and as digits),
then renders the top clips again on the full model and writes an HTML page
to listen and compare. The owner picks the narrator; the pick goes to the
channel bible (channels/<channel>/voices.yaml).

TTS goes through tts_selector restricted to the Gemini voice family
(Google first, AvalAI when Google refuses), transcription through
avalai_stt. The run refuses to start when the estimate is over --max-cost.
"""

from __future__ import annotations

import argparse
import datetime
import html
import json
import sys
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any, Callable

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from lib.fa_text import chars_per_second, round_trip, word_diff  # noqa: E402
from lib.parallel_runner import Job, run_parallel  # noqa: E402

# Numbers as words for the voice, digits for captions; both are references.
SCRIPT_WORDS = (
    "سال هزار و نهصد و سی و هشت، یه مرد جوون به اسم لی بیونگ‌چول توی شهر "
    "دِگو یه مغازه‌ی کوچیک باز کرد و ماهی خشک و میوه می‌فروخت. کل سرمایه‌ش "
    "سی هزار وون بود. هیچ‌کس فکرشم نمی‌کرد این مغازه یه روزی بشه سامسونگ؛ "
    "شرکتی که امروز گوشیش توی جیب صدها میلیون نفره. ولی صبر کن… داستان اصلی "
    "تازه از اینجا شروع می‌شه!"
)
SCRIPT_DIGITS = (
    "سال ۱۹۳۸، یه مرد جوون به اسم لی بیونگ‌چول توی شهر دِگو یه مغازه‌ی کوچیک "
    "باز کرد و ماهی خشک و میوه می‌فروخت. کل سرمایه‌ش ۳۰ هزار وون بود. هیچ‌کس "
    "فکرشم نمی‌کرد این مغازه یه روزی بشه سامسونگ؛ شرکتی که امروز گوشیش توی "
    "جیب صدها میلیون نفره. ولی صبر کن… داستان اصلی تازه از اینجا شروع می‌شه!"
)
# Spelling hints for the transcriber, so names it does not know do not
# count against the voice.
STT_PROMPT = "لی بیونگ‌چول، دگو، سامسونگ، وون"

VOICES = {
    "Kore": "زن، محکم",
    "Zephyr": "زن، روشن",
    "Sulafat": "زن، گرم",
    "Puck": "مرد، شاد",
    "Charon": "مرد، روایتگر",
    "Fenrir": "مرد، هیجانی",
}
STYLES = {
    "calm": "راوی آرام و گرم مستند، شمرده و با حوصله، لهجه‌ی تهرانی محاوره",
    "energetic": "پرانرژی و هیجان‌زده مثل یوتیوبر قصه‌گو، ریتم تند، لهجه‌ی تهرانی محاوره",
}
DRAFT_MODEL = "gemini-3.8-flash-lite-tts"
FINAL_MODEL = "gemini-3.8-flash-tts"
STT_MODEL = "gpt-4o-mini-transcribe"

# Estimate inputs. Gemini TTS bills ~25 audio tokens per second of output
# (AvalAI promo prices, see tools/audio/avalai_gemini_tts.py). The first
# audition (2026-11-04) measured 8.6-10.5 spoken letters per second across
# 6 voices and both styles; 14 was too optimistic and underestimated by half.
AUDIO_TOKENS_PER_SECOND = 25
TTS_OUTPUT_PRICE = {DRAFT_MODEL: 6.00, FINAL_MODEL: 9.00}  # USD per 1M tokens
ASSUMED_CPS = 9.5
STT_PRICE_PER_SECOND = 0.00005


@dataclass
class Take:
    voice: str
    style: str
    model: str
    path: str = ""
    provider: str = ""
    seconds: float = 0.0
    cps: float = 0.0
    transcript: str = ""
    round_trip: dict = field(default_factory=dict)
    misheard: list = field(default_factory=list)
    cost_usd: float = 0.0
    error: str = ""

    @property
    def key(self) -> str:
        return f"{self.voice}-{self.style}-{'final' if self.model == FINAL_MODEL else 'draft'}"


def estimate_seconds(text: str = SCRIPT_WORDS) -> float:
    spoken = sum(1 for ch in text if ch.isalnum())
    return spoken / ASSUMED_CPS


def estimate_cost(voices: int, styles: int, top: int) -> dict[str, float]:
    seconds = estimate_seconds()
    tokens = seconds * AUDIO_TOKENS_PER_SECOND
    drafts = voices * styles
    draft_tts = drafts * tokens * TTS_OUTPUT_PRICE[DRAFT_MODEL] / 1e6
    final_tts = top * tokens * TTS_OUTPUT_PRICE[FINAL_MODEL] / 1e6
    stt = (drafts + top) * seconds * STT_PRICE_PER_SECOND
    return {
        "clip_seconds": round(seconds, 1),
        "draft_tts": round(draft_tts, 4),
        "final_tts": round(final_tts, 4),
        "transcription": round(stt, 4),
        "total": round(draft_tts + final_tts + stt, 4),
    }


def _default_tts() -> Callable[[dict], Any]:
    from tools.audio.tts_selector import TTSSelector

    return TTSSelector().execute


def _default_stt() -> Callable[[dict], Any]:
    from tools.analysis.avalai_stt import AvalAISTT

    return AvalAISTT().execute


def render_take(take: Take, out_dir: Path, tts: Callable, stt: Callable,
                providers: list[str]) -> Take:
    path = out_dir / f"{take.key}.wav"
    result = tts({
        "text": SCRIPT_WORDS,
        "language_code": "fa",
        "voice_id": take.voice,
        "style": STYLES[take.style],
        "model_id": take.model,
        "allowed_providers": providers,
        "output_path": str(path),
    })
    if not result.success:
        take.error = result.error or "TTS failed"
        return take
    take.path = path.name
    take.provider = result.data.get("selected_provider") or result.data.get("provider", "")
    take.seconds = round(float(result.data.get("audio_duration_seconds") or 0.0), 2)
    take.cps = chars_per_second(SCRIPT_WORDS, take.seconds)
    take.cost_usd += result.cost_usd or 0.0

    heard = stt({
        "audio_path": str(path),
        "model": STT_MODEL,
        "language": "fa",
        "prompt": STT_PROMPT,
        "output_path": str(path.with_suffix(".transcript.json")),
    })
    if not heard.success:
        take.error = "transcription failed: " + (heard.error or "?")
        return take
    take.transcript = heard.data["text"]
    take.round_trip = round_trip(take.transcript, SCRIPT_WORDS, SCRIPT_DIGITS)
    take.misheard = word_diff(take.transcript, SCRIPT_WORDS)[:12]
    take.cost_usd = round(take.cost_usd + (heard.cost_usd or 0.0), 6)
    return take


def _run(takes: list[Take], out_dir: Path, tts, stt, providers, limit: int) -> list[Take]:
    jobs = [Job(key=t.key, provider="tts",
                fn=lambda t=t: render_take(t, out_dir, tts, stt, providers))
            for t in takes]
    report = run_parallel(jobs, limits={"tts": limit})
    done = []
    for take, job in zip(takes, report.results):
        if not job.ok:
            take.error = take.error or job.error or "failed"
        done.append(take)
    return done


def rank(takes: list[Take]) -> list[Take]:
    """Best round-trip first; ties go to the clip closer to the usual pace."""
    ok = [t for t in takes if not t.error and t.round_trip]
    return sorted(ok, key=lambda t: (-t.round_trip["best"], abs(t.cps - ASSUMED_CPS)))


def run_audition(out_dir: Path, voices: list[str], styles: list[str], top: int = 2,
                 tts: Callable | None = None, stt: Callable | None = None,
                 providers: list[str] | None = None, limit: int = 3) -> dict:
    out_dir.mkdir(parents=True, exist_ok=True)
    tts = tts or _default_tts()
    stt = stt or _default_stt()
    providers = providers or ["gemini", "avalai"]

    drafts = _run([Take(v, s, DRAFT_MODEL) for v in voices for s in styles],
                  out_dir, tts, stt, providers, limit)
    leaders = rank(drafts)[:top]
    finals = _run([Take(t.voice, t.style, FINAL_MODEL) for t in leaders],
                  out_dir, tts, stt, providers, limit)

    results = {
        "created_at": datetime.datetime.now(datetime.timezone.utc).isoformat(),
        "script_words": SCRIPT_WORDS,
        "script_digits": SCRIPT_DIGITS,
        "styles": {k: STYLES[k] for k in styles},
        "models": {"draft": DRAFT_MODEL, "final": FINAL_MODEL, "stt": STT_MODEL},
        "drafts": [asdict(t) for t in drafts],
        "finals": [asdict(t) for t in finals],
        "ranking": [t.key for t in rank(drafts)],
        "cost_usd": round(sum(t.cost_usd for t in drafts + finals), 6),
    }
    _write(out_dir, results)
    return results


def _write(out_dir: Path, results: dict) -> None:
    (out_dir / "results.json").write_text(
        json.dumps(results, ensure_ascii=False, indent=2), encoding="utf-8")
    (out_dir / "index.html").write_text(render_html(results), encoding="utf-8")


def rescore(out_dir: Path) -> dict:
    """Score saved transcripts again (after a change to lib/fa_text) without
    paying for new audio. The finals stay the ones already rendered."""
    results = json.loads((out_dir / "results.json").read_text(encoding="utf-8"))
    for group in ("drafts", "finals"):
        takes = [Take(**t) for t in results[group]]
        for take in takes:
            if take.transcript:
                take.round_trip = round_trip(take.transcript, SCRIPT_WORDS, SCRIPT_DIGITS)
                take.misheard = word_diff(take.transcript, SCRIPT_WORDS)[:12]
        results[group] = [asdict(t) for t in takes]
        if group == "drafts":
            results["ranking"] = [t.key for t in rank(takes)]
    _write(out_dir, results)
    return results


def _row(t: dict, rank_no: int | None) -> str:
    rt = t.get("round_trip") or {}
    misheard = "، ".join(f"«{h or '—'}» به‌جای «{e}»" for h, e in t.get("misheard") or [])
    audio = (f'<audio controls preload="none" src="{html.escape(t["path"])}"></audio>'
             if t.get("path") else "")
    status = html.escape(t["error"]) if t.get("error") else ""
    return (
        "<tr>"
        f"<td>{rank_no or ''}</td>"
        f"<td><b>{html.escape(t['voice'])}</b><br><small>{html.escape(VOICES.get(t['voice'], ''))}</small></td>"
        f"<td>{'آرام' if t['style'] == 'calm' else 'پرانرژی'}</td>"
        f"<td>{audio}{status}</td>"
        f"<td>{t.get('seconds', 0):.1f}</td>"
        f"<td>{t.get('cps', 0):.1f}</td>"
        f"<td>{rt.get('vs_words', 0):.0%}</td>"
        f"<td>{rt.get('vs_digits', 0):.0%}</td>"
        f"<td class='heard'>{html.escape(t.get('transcript', ''))}"
        f"{'<br><small>' + html.escape(misheard) + '</small>' if misheard else ''}</td>"
        f"<td>{html.escape(t.get('provider', ''))}</td>"
        "</tr>"
    )


def render_html(results: dict) -> str:
    order = {k: i + 1 for i, k in enumerate(results["ranking"])}
    head = ("<tr><th>رتبه</th><th>صدا</th><th>سبک</th><th>گوش بده</th><th>ثانیه</th>"
            "<th>حرف در ثانیه</th><th>شباهت (عدد به حروف)</th><th>شباهت (عدد با رقم)</th>"
            "<th>چیزی که متن‌برداری شنید</th><th>ارائه‌دهنده</th></tr>")

    def _key(t):
        return f"{t['voice']}-{t['style']}-{'final' if t['model'] == results['models']['final'] else 'draft'}"

    drafts = sorted(results["drafts"], key=lambda t: order.get(_key(t), 999))
    finals = "".join(_row(t, i + 1) for i, t in enumerate(results["finals"]))
    rows = "".join(_row(t, order.get(_key(t))) for t in drafts)
    return f"""<!doctype html>
<html lang="fa" dir="rtl"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>آزمون صدای کانال</title>
<style>
:root {{ color-scheme: light dark; --bg:#fbfaf7; --fg:#1d1b18; --muted:#6b665d; --line:#e4dfd5; --accent:#1f4fd1; }}
@media (prefers-color-scheme: dark) {{ :root {{ --bg:#16171a; --fg:#ece9e3; --muted:#a29d93; --line:#2c2e33; --accent:#8aa8ff; }} }}
body {{ margin:0; padding:24px 16px; background:var(--bg); color:var(--fg);
       font-family: Vazirmatn, Tahoma, sans-serif; line-height:1.8; }}
main {{ max-width:1200px; margin:auto; }}
h1 {{ font-size:1.5rem; margin:0 0 .25rem; }} h2 {{ font-size:1.15rem; margin-top:2rem; }}
p, small {{ color:var(--muted); }}
blockquote {{ margin:0; padding:12px 16px; border-inline-start:3px solid var(--accent); background:color-mix(in srgb, var(--accent) 6%, transparent); }}
.wrap {{ overflow-x:auto; }}
table {{ border-collapse:collapse; width:100%; font-size:.92rem; }}
th, td {{ border-bottom:1px solid var(--line); padding:8px 6px; text-align:start; vertical-align:top; }}
th {{ font-weight:600; white-space:nowrap; }}
td.heard {{ min-width:280px; }}
audio {{ width:220px; }}
</style></head><body><main>
<h1>آزمون صدای راوی کانال</h1>
<p>هر صدا با دو سبک خونده شده. «شباهت» یعنی متن‌برداری خودکار چقدر همون متن رو شنیده (بعد از یکسان‌سازی ی/ک، نیم‌فاصله و عددها). عدد بالا یعنی تلفظ واضح‌تر؛ ولی انتخاب نهایی با گوش شماست.
هزینه‌ی کل: {results['cost_usd']:.4f} دلار.</p>
<blockquote>{html.escape(results['script_words'])}</blockquote>
<h2>دو گزینه‌ی برتر با مدل کامل ({html.escape(results['models']['final'])})</h2>
<div class="wrap"><table>{head}{finals}</table></div>
<h2>همه‌ی پیش‌نویس‌ها ({html.escape(results['models']['draft'])})</h2>
<div class="wrap"><table>{head}{rows}</table></div>
<p>سبک آرام: {html.escape(results['styles'].get('calm', ''))}<br>
سبک پرانرژی: {html.escape(results['styles'].get('energetic', ''))}</p>
</main></body></html>
"""


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--out", default=f"projects/_voice_audition/{datetime.date.today()}")
    parser.add_argument("--voices", default=",".join(VOICES))
    parser.add_argument("--styles", default=",".join(STYLES))
    parser.add_argument("--top", type=int, default=2)
    parser.add_argument("--max-cost", type=float, default=0.15)
    parser.add_argument("--providers", default="gemini,avalai",
                        help="TTS providers tts_selector may use, in order")
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--rescore", action="store_true",
                        help="re-score the transcripts already in --out (free)")
    args = parser.parse_args(argv)

    if args.rescore:
        results = rescore(Path(args.out))
        print(f"Re-scored {args.out}; best: {', '.join(results['ranking'][:3])}")
        return 0

    voices = [v for v in args.voices.split(",") if v]
    styles = [s for s in args.styles.split(",") if s]
    unknown = [s for s in styles if s not in STYLES]
    if unknown:
        parser.error(f"unknown style(s): {', '.join(unknown)}")
    estimate = estimate_cost(len(voices), len(styles), args.top)
    print(json.dumps({"estimate_usd": estimate}, ensure_ascii=False, indent=2))
    if args.dry_run:
        return 0
    if estimate["total"] > args.max_cost:
        print(f"Estimate ${estimate['total']} is over --max-cost ${args.max_cost}; not running.")
        return 2

    from lib.env_loader import load_env

    load_env()
    out_dir = Path(args.out)
    results = run_audition(out_dir, voices, styles, args.top,
                           providers=args.providers.split(","))
    failed = [t for t in results["drafts"] + results["finals"] if t["error"]]
    print(f"Wrote {out_dir / 'index.html'}; cost ${results['cost_usd']:.4f}; "
          f"{len(failed)} failed")
    for t in failed:
        print(f"  {t['voice']}-{t['style']}: {t['error'][:200]}")
    return 0 if not failed else 1


if __name__ == "__main__":
    raise SystemExit(main())
