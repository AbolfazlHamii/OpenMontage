# Delegation Protocol — write less, choose and review more

## When to Use

Any stage that needs a lot of text the viewer never sees verbatim: source
summaries, outline and scene-breakdown drafts, EN→FA translation drafts,
per-scene image prompts, 10–15 hook options, title/tag variants, JSON
filling, classification, transcript-chunk summaries, claim extraction.

**Rule: do not write bulk text yourself. Delegate it, choose from it, review it.**

## How

1. Pick the task name from `config/llm_routing.yaml` (`tasks:`). It decides
   the tier: `bulk` (classification, JSON repair, claims), `worker` (drafts,
   prompts, hooks), `vision_bulk` (frames CLIP is unsure about).
2. Write the prompt to a file and run, from Bash:

   ```bash
   python -m tools.text.llm_selector --task hooks --input brief_hooks.txt --out hooks.json --cost-log projects/<id>/cost_log.json
   ```

   Add `--schema schema.json` when you need a fixed JSON shape. The output
   has `result`, `model`, `cost_usd` and `fallback_from`.
3. Many independent items (one prompt per scene): call `llm_selector` with
   `operation: "batch"` and one item per scene; it runs them in parallel with
   a cap per provider.
4. **Choose and review.** You are the premium tier. Pick the best options,
   fix them, and say why. Cheap output is raw material, never the deliverable.
5. If the result says `ESCALATE TO AGENT`, the cheap tiers failed twice or
   the task is premium-only: do it yourself.

## Red lines

- **Final Persian text is never delivered by a cheap model.** Narration,
  final subtitles, titles and descriptions (`*_final` tasks) always pass your
  review; in interactive mode the router refuses to send them out at all.
- Order of preference: free local (CLIP, ffmpeg, Ollama if installed) →
  bulk → worker → premium.
- Report model and cost for each delegated batch in the stage summary.
- Never paste keys into prompts or files; the router reads them from `.env`.

## Modes

- **Interactive** (default): you, inside Claude Code, are premium. Only
  bulk/worker/vision_bulk go to APIs.
- **Headless** (`OPENMONTAGE_LLM_MODE=headless`): unattended runs; premium
  is called through AvalAI.
- **"Economy mode"** means running all of Claude Code on Kimi through
  `ANTHROPIC_BASE_URL`. It is not the default and its Persian quality is not
  guaranteed.

## Subagents

`.claude/agents/fa-asset-runner.md` (Sonnet) runs tools mechanically from a
written plan; `.claude/agents/fa-qa-checker.md` (Haiku) runs format checks.
Neither makes creative decisions.
