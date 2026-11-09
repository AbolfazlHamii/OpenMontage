# LLM bake-off — recommendation (2026-11-04)

Run: `python scripts/llm_bakeoff.py --run --cap 0.30` — 8 candidates × 5 real
tasks for the Samsung video (colloquial narration draft, EN→FA translation,
5 image prompts, 10 hooks, timeline JSON). Spent **$0.2007** of the $0.30
cap (worst case announced: $0.484). Raw outputs: `results.json`; side-by-side
Persian outputs for the owner: `report.html`; agent scores: `scores.json`.

| Model (AvalAI unless noted) | OK | Cost (5 tasks) | Avg s | JSON valid | Quality /5 |
|---|---|---|---|---|---|
| deepseek-v4.1-flash | 5/5 | $0.0032 | 7.5 | 3/3 | **4.4** |
| claude-haiku-5-5 | 5/5 | $0.0034 | 8.8 | 3/3 | 4.1 |
| qwen3.8-flash | 5/5 | $0.0058 | 35.0 | 3/3 | 4.1 |
| kimi-k3.1-pro | 4/5 | $0.0975 | 32.0 | 2/3 | 3.9 |
| gemini-3.8-flash | 5/5 | $0.0267 | 16.2 | 3/3 | 3.9 |
| gemini-3.1-flash-lite | 5/5 | $0.0022 | 2.3 | 3/3 | 3.7 |
| kimi-k2.6 | 5/5* | $0.0619 | 51.0 | 3/3 | 2.9 |
| gemini-3.8-flash (Google direct) | 0/5 | $0 | – | – | – (403) |

\* two answers were empty: the reasoning used all 2500 output tokens.

## Proposed tiers (applied in `config/llm_routing.yaml`; the owner decides)

- **worker:** deepseek-v4.1-flash → claude-haiku-5-5 → gemini-3.8-flash.
  Best quality per dollar, faithful translation, valid JSON every time.
- **bulk:** gemini-3.1-flash-lite → deepseek-v4.1-flash → qwen3.8-flash.
  Fastest (2.3 s) and cheapest; weaker at free-form Persian, which bulk tasks
  do not need.
- **vision_bulk:** gemini-3.1-flash-lite — not tested here (text-only run);
  quality unverified.
- **premium (headless only):** claude-opus-5-5 → claude-sonnet-5-5 — not
  benchmarked; both need AvalAI account tier ≥ 1.

## Kimi

Not recommended for worker/bulk on this evidence: K2.6 burns its output budget
on reasoning (15k output tokens for 5 tasks) and K3.1 Pro failed the hooks JSON
twice at ~30× DeepSeek's cost. Catalog price check: kimi-k3.1-pro $2/$10 per
1M (matches the brief); kimi-k3.1-pro-highspeed is **$4.6/$23** on AvalAI
(the brief's $4/$20 does not match the catalog).

## Dahl (added 2026-11-09, `--run --only dahl`)

Three open models on Dahl's free tier, same five tasks, $0.0004 in all:

| Model | ok | avg s | quality |
|---|---|---|---|
| MiniMax M2.7 | 5/5 | 31 | 3.3 |
| DeepSeek V4 Flash | 2/5 | 73 | 2.5 |
| GLM 5.3 Flash | 4/5 | 49 | 3.2 |

Not recommended for any tier yet. Quality is below AvalAI DeepSeek V4.1
Flash (4.4) and the free tier is unreliable: `429 model_concurrency` even
after four 20 s retries, and 120 s timeouts. MiniMax spends its whole output
budget on inline reasoning for long prose (empty narration); GLM invents
figures in hooks, like Gemini. All three got `json_fill` right, so Dahl could
be a last, near-free fallback for `json_fill`/`classification` if AvalAI is
down; that is the owner's call. A paid top-up gets priority at peak and
might fix the reliability side, not the quality side.

## Caveats

- One run per task (temperature 0.7); scores are the agent's reading, not a
  panel. The owner should read `report.html` before deciding.
- Gemini's livelier Persian came with invented facts — another reason final
  Persian text stays premium-reviewed.
