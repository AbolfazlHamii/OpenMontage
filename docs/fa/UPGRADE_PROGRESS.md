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
| 2 | Two-tier brain (LLM router, bake-off) | in progress | | | bake-off < $0.50 with approval | |
| 3 | Editing style library + camera language | pending | | | $0 | |
| 4 | Learn style from a reference video | pending | | | < $0.05 | fix scene_detect first |
| 5 | Quality gate | pending | | | | |
| 6 | Studio FA usability | pending | | | | |
| 7 | Series template | waiting | | | | only after the owner approves the Samsung video |

## Blockers and open questions

- Known failing test (allowed until phase 4):
  `tests/tools/test_local_video_cache_inputs.py::test_scene_analysis_cache_tracks_requested_minimum_length`.
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
