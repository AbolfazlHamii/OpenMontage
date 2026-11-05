# Upgrade progress (UPGRADE_PROMPT v2)

One phase per session. A new session reads this file first, picks the first
phase that is not `done`, and continues from there. The brief itself is
`UPGRADE_PROMPT.md` in the parent folder (`D:\project\videio v\`), outside
this repo.

Branch: `fa`. Nothing is pushed until the owner asks.

| Phase | Title | Status | Date | Commit | Paid spend | Notes |
|---|---|---|---|---|---|---|
| 0 | Baseline + progress file | done | 2026-11-04 | 9dc881f | $0 | `docs/fa/BASELINE.md` |
| 1 | Quick wins (loudness, preview profiles, parallel runner, draft/final images, cost estimate, fast tests) | done | 2026-11-04 | 3aa51d3 | $0 | before/after in BASELINE.md |
| 2 | Two-tier brain (LLM router, bake-off) | done (owner picks models) | 2026-11-04 | 35645fc | $0.2008 | `docs/fa/llm_bakeoff/` |
| 3 | Editing style library + camera language | done | 2026-11-04 | 057f766 | $0 | 8 cards, snippets rendered |
| 4 | Learn style from a reference video | done | 2026-11-04 | f221e07 | $0.0375 | ASL 3.75 vs 3.75 (0%) |
| 5 | Quality gate | done | 2026-11-04 | cccb269 | $0.0009 | QA flags −11.5 LUFS |
| 6 | Studio FA usability | done | 2026-11-04 | 41e1f40 | $0 | 9 screenshots in docs/fa/screens/ |
| 7 | Series template | **waiting** (منتظر) | 2026-11-04 | – | $0 | Samsung video not approved yet; skipped as the brief says |

Paid spend across phases 0–7: **$0.2393** (phase 2 $0.2008 incl. one $0.0001
test call, phase 4 $0.0375, phase 5 $0.0009, phase 6 $0). No single call over
$0.05.

## Blockers and open questions

- **Owner decides:** worker/bulk models (bake-off recommendation applied in
  `config/llm_routing.yaml`; report `docs/fa/llm_bakeoff/report.html`).
- Local CLIP weights could not be downloaded from huggingface.co on this
  network (timeouts); download once over the VPN to make frame labels free.

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

### 2026-11-04 — phase 5

- New: `lib/fa_render_qa.py` + `scripts/fa_render_qa.py` (reuses
  `visual_qa` probe/review and `loudness_normalize`; blackdetect,
  freezedetect, A/V sync, duration vs script, captions, workspace RTL,
  text-in-images via vision_bulk), `lib/fa_editorial.py` +
  `scripts/fa_editorial.py` (hook lab, fact-check → decision_log),
  `fa_image` `set_style` (style reference, character sheets, palette).
- `decision_log` schema: two new categories, `fact_check` and
  `hook_selection` (enum extension only).
- `composition_validator` was not wired in: it validates Remotion props
  JSON, and the Persian renders so far are HyperFrames atelier workspaces.
- Ran on `projects/samsung-history-fa/renders/sample_no_music.mp4`
  (read-only; report in `docs/fa/qa/`): loudness **fail −11.5 LUFS**,
  everything else pass, 3 stills have no text ($0.0009).
- Local CLIP: torch CPU installed; transformers installed; the CLIP weights
  download from huggingface.co timed out (read/handshake timeouts) on this
  network. Tried once. Options: download through the VPN once (the model is
  cached afterwards), or keep vision_bulk (~$0.014 per 40 frames).

### 2026-11-04 — phase 6

- New: `studio_fa/production.py` (router under `/api/fa`, wired with two
  lines in `server.py`), `studio_fa/ui/production.js`, new tabs in
  `index.html`, styles in `app.css`. Write endpoints sit behind
  `_require_panel`; keys are only entered through the existing `/api/env`
  (now also MOONSHOT_API_KEY / OPENROUTER_API_KEY); errors are one Persian
  sentence with a fix, redacted; unexpected errors are caught by a Persian
  500 handler.
- `openai_compat_llm`: a `local` profile (Ollama) is available only when its
  port answers.
- Checked in the browser against a scratch projects folder (copy of the
  Samsung metadata; the real project untouched): wizard → estimate ($2.04 for
  90 s final with one draft round, refused at $1, created at $3) → project;
  timeline approve wrote decision `d1`; Samsung timeline shows locked. Found
  and fixed: the brief failed validation after the project folder was
  already created (now validated first; `key_points` non-empty).
- Screenshots (dark theme, 1440 px): `docs/fa/screens/{home,new,projects,
  timeline,costs,health,styles,routing,keys}.png`.
- Tests: `tests/tools/test_studio_fa.py` 24 passed (12 new).

### 2026-11-04 — phase 7

- Skipped: the owner has not approved the Samsung video yet (still at the
  sample review). Run this phase after approval.

### 2026-11-05 — remake from a link (owner request after the phases)

The owner asked for "give it a YouTube or Instagram link and it makes a
Persian version", both Shorts and long YouTube videos.

- New: `tools/analysis/reference_kit.py` (link or file → kit in
  `projects/_reference/<slug>/`: video, transcript, outline, learned edit
  card, Gemini analysis, claims, worker translation draft, `remake_brief.json`,
  `REMAKE_fa.md`), `scripts/fa_remake.py`, `skills/meta/remake-from-link.md`,
  Studio FA «از لینک بساز» (`POST /api/fa/remake`, pre-fills the wizard and
  attaches the kit to the brief), tests `tests/tools/test_reference_kit.py`.
- Modes: transcreate (default; structure, pacing, hook technique only) and
  dub (refused without `rights` own / licensed / permission).
- Real runs (paid, all under the $0.10 cap):
  - NASA Short, 39 s, 9:16: every step ran, **$0.0136**; YouTube captions
    429 on both routes → whisper-1 $0.0039 in 2.9 s.
  - CEOzoned Coca-Cola, 11 min, 16:9 (target 90 s): free captions, 186
    shots (ASL 3.55 s), 8 sections, 34 claims, **$0.0809** (style $0.0172,
    Gemini $0.0562 for the first 8 min, text $0.0075). 10.5 min wall time,
    with the test suite and the Short sharing the CPU (scene detection 4 min).
- Found and fixed while testing:
  - CLIP: transformers installed without weights made frame labels try a
    HuggingFace download and hang; now only used when the weights are cached
    (`clip_weights_cached`), offline.
  - `avalai_stt` defaults to `fa`; on an English video it returned Persian
    gibberish. The kit passes the source language (or "" to detect).
  - STT `ReadTimeout` and Gemini `SSLError` on `api.avalai.ir`: the shell's
    `HTTPS_PROXY` (v2rayN) carried plain `requests` calls. The kit adds the
    AvalAI host to `NO_PROXY` for its run and retries STT once.
  - Studio FA runs without `HTTPS_PROXY`, so its "direct" yt-dlp calls
    really are direct and YouTube refuses them (WinError 10061); each step
    waited out yt-dlp's retries there (~2 min each) before the proxy. The
    route that worked last now goes first.
  - Gemini estimate was 3× low ($0.0184 vs $0.0562); now
    $0.004 + $0.00011/s from the two runs. The brief records each step's
    actual cost (`cost.actual`).
- An 11-minute video **without** captions plans ~$0.14: under the default
  $0.10 the Gemini step is skipped and listed; `--budget 0.15` runs it.
- Instagram: untested with a real session (needs the owner's cookies.txt or
  the reel file).
