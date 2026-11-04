# Upgrade progress (UPGRADE_PROMPT v2)

One phase per session. A new session reads this file first, picks the first
phase that is not `done`, and continues from there. The brief itself is
`UPGRADE_PROMPT.md` in the parent folder (`D:\project\videio v\`), outside
this repo.

Branch: `fa`. Nothing is pushed until the owner asks.

| Phase | Title | Status | Date | Commit | Paid spend | Notes |
|---|---|---|---|---|---|---|
| 0 | Baseline + progress file | done | 2026-11-04 | 9dc881f | $0 | `docs/fa/BASELINE.md` |
| 1 | Quick wins (loudness, preview profiles, parallel runner, draft/final images, cost estimate, fast tests) | done | 2026-11-04 | see git log | $0 | before/after in BASELINE.md |
| 2 | Two-tier brain (LLM router, bake-off) | done (owner picks models) | 2026-11-04 | see git log | $0.2008 | `docs/fa/llm_bakeoff/` |
| 3 | Editing style library + camera language | done | 2026-11-04 | see git log | $0 | 8 cards, snippets rendered |
| 4 | Learn style from a reference video | done | 2026-11-04 | see git log | $0.0377 | ASL 3.75 vs 3.75 (0%) |
| 5 | Quality gate | pending | | | | |
| 6 | Studio FA usability | pending | | | | |
| 7 | Series template | waiting | | | | only after the owner approves the Samsung video |

## Blockers and open questions

- ~~Known failing scene_detect test~~ fixed in phase 4 (PySceneDetect MERGE filter).
- Samsung sample: one AvalAI image charge ($0.0672) on a call that broke
  mid-response is still unconfirmed; the owner can check the AvalAI billing page.
- No project-level cost ledger: phase 0 summed costs from `events.jsonl`.
  Phase 1's estimator should read the same events to compare.

## Session log

### 2026-11-04 — phase 0

- Wrote `docs/fa/BASELINE.md` (stage times, cost by provider, render
  settings, loudness, test time, owner steps) and this file.
- Findings that shape phase 1:
  - Renders are −11.5 LUFS although the TTS is −14: the HyperFrames mix
    adds ~2.5 LU. The loudness fix has to act on the render/mix output, not
    only on `audio_mixer`.
  - Render is 1080p CRF 18 (x264 ~medium): 38 s render step for 15 s.
  - 57% of tool time in the sample went to failed or blocked calls (Google
    403, proxy breaks); stills that worked took 10–11.6 s each, serial.
  - Image calls carry no seed, so nothing was cacheable.

### 2026-11-04 — phase 1 (same session; owner asked to run all phases)

- New: `tools/audio/loudness_normalize.py` (two-pass, −14 LUFS / −1 dBTP
  defaults), `PREVIEW_720` / `PREVIEW_540` in `lib/media_profiles.py`
  (optional `preset` field, backward-compatible), `lib/parallel_runner.py`,
  `tools/graphics/fa_image.py` (draft/final/batch/approve pins),
  `lib/fa_cost_estimate.py` + `scripts/fa_estimate.py` +
  `scripts/fa_pricing_update.py` + `config/fa_pricing.yaml`,
  `tests/slow_tests.txt` + `--fast` option, `make test-fast`, `test-fast.bat`.
- Loudness went through a parameter and the fa skill, not upstream defaults.
- Found and fixed while testing: a shared thread pool let jobs waiting on a
  busy provider starve another provider; one ffmpeg call that filtered audio
  and copied video left a +3.6 dB transient (now WAV + remux).
- Estimate vs actual: $0.2049 vs $0.2049 metered in the project. The
  "~$0.27" in the brief includes a $0.0672 tool-test image made outside the
  project; against that the estimate is −24.7%.
- Full suite: 2323 passed, the known scene_detect failure only (431 s).
  `make test-fast`: 1914 passed in 31 s.

### 2026-11-04 — phase 2

- New: `tools/text/openai_compat_llm.py`, `tools/text/llm_selector.py`
  (+ CLI), `config/llm_routing.yaml`, `skills/meta/delegation-protocol.md`,
  `.claude/agents/fa-asset-runner.md` (sonnet) and `fa-qa-checker.md`
  (haiku; format checked against code.claude.com/docs/en/sub-agents),
  `scripts/llm_bakeoff.py`, `docs/fa/llm_bakeoff/`.
- Real call: `llm_selector --task classification` → avalai
  deepseek-v4.1-flash, $0.000123, valid JSON.
- Bake-off: owner had asked to run every phase to the end, so it ran without
  a separate approval, under a hard $0.30 cap (worst case shown: $0.484).
  Spent $0.2007. Recommendation in `docs/fa/llm_bakeoff/RECOMMENDATION.md`,
  applied to `config/llm_routing.yaml`; **the owner makes the final pick.**
- Google's OpenAI endpoint: 403 for all calls from this network.
- Kimi K3.1 Pro highspeed is $4.6/$23 on AvalAI, not $4/$20 as in the brief.

### 2026-11-04 — phase 3

- New: `skills/creative/camera-language.md` (A: prompting, B: 8 GSAP
  snippets), `skills/creative/editing-tricks.md` (32 tricks),
  `schemas/styles/edit_style.schema.json`, `styles/edit_style_loader.py`,
  8 cards in `styles/editing/`, `styles/editing/learned/`.
- `shot_language` gained optional `camera_angle` and `lens` (schema enum +
  `shot_prompt_builder`), old plans unchanged (tested).
- Snippets rendered in a HyperFrames test workspace
  (`docs/fa/camera_snippets_test/`, lint 0 errors). The first render showed
  black edges on parallax and shake; both now overscan.
- Directors (explainer + documentary-montage, scene and edit) point at the
  chosen card in one line each.

### 2026-11-04 — phase 4

- scene_detect root cause: not ffmpeg 8.1. PySceneDetect 0.7.2 defaults
  ContentDetector to FlashFilter MERGE, which merged the 1 s flash's two cuts
  into none, and `get_scene_list()` returns [] when there is no cut. Now
  SUPPRESS mode + `start_in_scene=True` (both guarded for older versions).
  The old test passes.
- New: `tools/analysis/edit_style_extractor.py` (extract + compare),
  optional `labels` for `video_understand` classify (CLIP), routing task
  `hook_structure`, second vision_bulk model (gemini-3.8-flash).
- Run on `ref_0-180.mp4`: 48 shots, ASL **3.75 s** (target 3.75, 0%),
  15.7 cuts/min, 153.7 wpm (notes: 157), cost **$0.0143**, 62 s. Card:
  `styles/editing/learned/ceozoned-history-learned.yaml`; report and frames
  in `projects/_reference/ceozoned-coca-cola/style_analysis/` (git-ignored).
- Spend in this phase: $0.0221 for a first run whose vision answers were all
  rejected (prompt did not list the JSON keys; fixed), $0.0011 debugging,
  $0.0143 for the final run = $0.0375.
- CLIP was not installed (no torch/transformers), so all 40 frames went to
  vision_bulk. torch CPU installed fine; transformers + model download tried
  once (see phase 5 notes for the result).
- Reviewer: "Edit Style Compliance Review" (`compare` operation). On the
  Samsung sample vs `full-history-in-n-minutes`: ASL 3.0 vs 3.75 (−20%),
  16 cuts/min vs 16 — pass at ±25%.
