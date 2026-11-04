# Upgrade progress (UPGRADE_PROMPT v2)

One phase per session. A new session reads this file first, picks the first
phase that is not `done`, and continues from there. The brief itself is
`UPGRADE_PROMPT.md` in the parent folder (`D:\project\videio v\`), outside
this repo.

Branch: `fa`. Nothing is pushed until the owner asks.

| Phase | Title | Status | Date | Commit | Paid spend | Notes |
|---|---|---|---|---|---|---|
| 0 | Baseline + progress file | done | 2026-11-04 | 9dc881f | $0 | `docs/fa/BASELINE.md` |
| 1 | Quick wins (loudness, preview profiles, parallel runner, draft/final images, cost estimate, fast tests) | next | | | budget $0 | |
| 2 | Two-tier brain (LLM router, bake-off) | pending | | | bake-off < $0.50 with approval | |
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
