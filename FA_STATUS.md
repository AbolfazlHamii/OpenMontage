# Persian channel (branch `fa`) — status and handoff

Read this first if you are picking up work on the Persian YouTube channel.
The owner talks Persian; code, comments and commits are English. The full
brief (phases 0–5) is `BUILD_PROMPT.md` (kept outside the repo, in the
owner's Downloads). The owner's cross-project hub has the same status in
Persian: `D:\project\MaN\projects-hub\projects\openmontage-fa.md`.

Last updated: 2026-11-04

## Rules from the brief

- Work on the owner's fork `AbolfazlHamii/OpenMontage`, branch `fa`.
  Prefer new files over edits to upstream files (easier upstream merges).
- New tools follow `BaseTool`, with unit tests. No test may call a paid API.
- Ask the owner before any call estimated over $0.50, or before crossing the
  project budget.
- Re-check model IDs against official docs; say so when something does not
  match, never guess.
- Add every new Persian limitation to `skills/creative/persian-localization.md`.
- Read that skill before any Persian production stage.

## What exists (all on `fa`)

| Piece | Where | Notes |
|---|---|---|
| Persian TTS routing | `tools/audio/tts_selector.py` | Persian text → `PERSIAN_TTS_PRIORITY`; falls through to the next provider on a call-time failure; reports `fallback_from` |
| AvalAI Gemini TTS | `tools/audio/avalai_gemini_tts.py` | Same Gemini 3.8 voices via AvalAI native `generateContent`; cost from `usageMetadata` |
| AvalAI Gemini image | `tools/graphics/avalai_gemini_image.py` | Nano Banana models via AvalAI native `generateContent`; per-image cost from AvalAI's live catalog |
| Image mirror routing | `tools/graphics/image_selector.py` (`MIRROR_ORDER`) | Pinned Gemini image model → `google_imagen` first, same request on `avalai_gemini_image` if it fails; reports `fallback_from` |
| Short fallback errors | `tools/provider_routing.py` (`short_error`) | HTML error pages and escaped SDK payloads reduced to one line in `fallback_from` (TTS and images) |
| RTL subtitles | `tools/subtitle/subtitle_gen.py`, `tools/video/video_compose.py` | RLM per line + ASS `Encoding=-1`; `SUBTITLE_FONTS_DIR` / `fonts_dir` for per-user fonts on Windows |
| Control panel | `studio_fa/`, `studio-fa.bat` | `python -m studio_fa` → http://127.0.0.1:4760/. "Open in Backlot" returns the board URL when Backlot is up, else starts only `backlot serve` (the page opens the tab) |
| Smoke test | `scripts/fa_smoke_test.py` | `subtitles` (free) and `tts` (paid, < $0.01) |
| Gateway check | `scripts/check_gateway.py` | OpenAI-compatible gateways |
| Tests | `tests/tools/test_persian_localization.py`, `test_avalai_gemini_tts.py`, `test_avalai_gemini_image.py`, `test_subtitle_fonts_dir.py`, `test_studio_fa.py` | all mocked |
| Test network guard | `tests/conftest.py` | Also clears `HTTP(S)_PROXY` and sets `NO_PROXY=*` for the session: a loopback proxy (v2rayN) otherwise carried requests past the socket guard |
| Desktop shortcut | `Desktop\استودیو ویدیو فارسی.lnk` | Opens `studio-fa.bat` minimized (not in the repo) |

## Environment (owner's Windows laptop)

- Repo: `D:\project\videio v\OpenMontage`, venv `.venv` (Python 3.11).
- ffmpeg 8.1: `%LOCALAPPDATA%\Programs\ffmpeg\ffmpeg-n8.1-latest-win64-gpl-8.1\bin`
  (on the user PATH; shells started before the install need it added).
- Vazirmatn installed per user; `.env` sets `SUBTITLE_FONTS_DIR`.
- Keys in `.env` (git-ignored): `GOOGLE_API_KEY`, `AVALAI_API_KEY`. Key
  values also live in the owner's private secrets file, never in the repo.
- Network: Iran. Gemini API works directly from the laptop; Google's docs
  pages return 403. Downloads often truncate silently — retry through the
  local proxy `127.0.0.1:10808` with resume.
- Verified for real: `gemini_tts` (9 s Persian clip), `avalai_gemini_tts`
  (9.2 s, $0.0014), subtitle frame with Vazirmatn in correct RTL order,
  `image_selector` → google_imagen 403 → `avalai_gemini_image`
  (gemini-3.1-flash-image, 16:9 1K PNG 1376×768, 13 s, $0.0672;
  `fa_smoke/avalai_image_test.png`).
- This session's environment carries `HTTPS_PROXY=http://127.0.0.1:10808`
  (not set in Windows user/machine variables). Python clients use it.
- Full suite: `pytest tests` ≈ 7 min, 2289 passed. One known failure that
  predates `fa` work (fails on fc2747d too):
  `test_local_video_cache_inputs.py::test_scene_analysis_cache_tracks_requested_minimum_length`
  (scene_detect finds 0 scenes with this ffmpeg 8.1 / PySceneDetect).

## Phase status

- Phase 0 (setup): done.
- Phase 1 (channel voice audition): not started. The panel's voice studio
  covers ad-hoc auditions; `scripts/fa_voice_audition.py` is still to write.
- Phase 2–3, 5: not started.
- Phase 4 (first transcreation): **in progress — waiting at the proposal gate.**

## Current production: first transcreation

Project: `projects/samsung-history-fa/` (git-ignored), "کل تاریخ سامسونگ در ۹۰ ثانیه".
Backlot: `python -m backlot open samsung-history-fa`.

Approved by the owner (2026-11-04): concept Samsung; runtime **HyperFrames**
(agent had recommended Remotion); music = three variants to compare (Pixabay,
Lyria, none); 10 s samples of both `animated-explainer` and
`character-animation`. Sample budget approved: $0.50. Full production needs a
second approval.

Done:
- research + proposal checkpoints written (`artifacts/research_brief.json`,
  `proposal_packet.json`, `decision_log.json`, schema-valid).
- Sample narration: `assets/sample/s1_narration.wav`, `s2_narration.wav`
  (voice Kore, gemini-3.8-flash-tts, energetic style). Google returned 403,
  so both came from `avalai_gemini_tts` via the fall-through (~$0.0035 total).
  Sample script lines are in the hub file and below.

Google API (images, Lyria) returns 403 from the owner's current network
(IP 83.122.107.129) and from the local proxy exit 45.65.112.227. It worked
earlier from 205.252.135.82 (owner's VPN). Owner decision ("both"): AvalAI
image tool always available, Google preferred when reachable — done
(2026-11-04), see the mirror routing above. Lyria is still blocked (AvalAI
has no Lyria), so the Lyria music variant needs the VPN or a VPS.

Sample stills done (2026-11-04), waiting for the owner's look approval:
`assets/sample/s1a_hook_phone.png`, `s1b_fish_shop_1938.png`,
`s2_gumi_bonfire_1995.png` (16:9 1K, gemini-3.1-flash-image via AvalAI
after Google 403). Prompts (pre / critique / post) and costs:
`assets/sample/images.json`. Decisions d6–d8 in the decision log: image
provider change, visual identity (custom, time-coded palette, cobalt
accent; approved by the owner), accuracy notes (generic shop and founder,
no chairman at the bonfire). The hook still has lighter linework than the
other two.

Sample render done (2026-11-04), waiting for the owner's review:
`renders/sample_no_music.mp4` (15.0 s, 1080p30, narration complete,
−11.5 LUFS, 7 RTL caption groups, era stamps; review in
`renders/sample_review.json`). Atelier workspace:
`hyperframes-sample/index.html`, rendered with `hyperframes_compose`
`render_existing` and `HYPERFRAMES_BROWSER_PATH` set to the installed
Chrome (Google 403 on chrome-headless-shell). Pixabay and Lyria are
blocked from here and AvalAI has no music model (decision d9; the owner
had asked for Suno via AvalAI, it does not exist there). Music variants
from Mixkit instead (decision d10, licence copy in
`assets/music/LICENSE.md`): `renders/sample_music_a_fun_and_games.mp4`
(bed ~14 dB under the voice) and `renders/sample_music_b_secret_garden.mp4`
(~20 dB under, quieter section). **Owner picked A** (decision d11); the
workspace's `assets/audio/music.mp3` is `music_a.mp3` again.

Spent on this production so far: ~$0.0035 (sample narration) + $0.0672
(tool test image) + $0.2016 (three stills) = ~$0.27, plus possibly one
$0.0672 charge from a call that broke mid-response through the VPN proxy
(unconfirmed). Sample budget $0.50.

Sample script:
1. «احتمالاً گوشیِ توی دستت سامسونگه… ولی می‌دونستی این شرکت با فروش ماهی خشک شروع شد؟»
2. «سال هزار و نهصد و نود و پنج، رئیس سامسونگ صد و پنجاه هزار تا گوشیِ خراب رو جلوی کارگرهاش آتیش زد!»
   (captions use digits: ۱۹۹۵، ۱۵۰ هزار)

Reference analysis: `projects/_reference/ceozoned-coca-cola/` (`REFERENCE_NOTES.md`).

## Next steps

1. Character-animation sample (approved plan: a 10 s sample of both
   pipelines), then the owner picks the pipeline for the full video.
2. Present samples + actual cost; then script stage for the full 90 s.
3. Phase 1 voice audition before the final narration.
4. Optional: show image providers in Studio FA's health panel (it only
   covers TTS today).
