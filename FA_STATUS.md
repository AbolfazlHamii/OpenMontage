# Persian channel (branch `fa`) — status and handoff

Read this first if you are picking up work on the Persian YouTube channel.
The owner talks Persian; code, comments and commits are English. The full
brief (phases 0–5) is `BUILD_PROMPT.md` (kept outside the repo, in the
owner's Downloads). The owner's cross-project hub has the same status in
Persian: `D:\project\MaN\projects-hub\projects\openmontage-fa.md`.

Last updated: 2026-11-05 (remake from a link; earlier: build phases 1–3, 5; research tools)

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
| Remake from a link | `tools/analysis/reference_kit.py`, `scripts/fa_remake.py`, Studio FA «از لینک بساز» | YouTube Shorts / long, Instagram (cookies.txt or file), TikTok, X → kit in `projects/_reference/<slug>/`; transcreate by default, dub only with rights; `skills/meta/remake-from-link.md` |
| Manual images (owner makes stills) | `lib/fa_manual_images.py`, `scripts/fa_manual_images.py`, `skills/meta/manual-images.md` | Prompt pack, image check, build/render. **ZAPI FLOW**: `zapi_flow.txt` (one prompt per line) + `import --from <download folder>` (row number in file name, else download order; extras to `in/alts/`); `style.characters` repeats a person's description in each prompt |
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
- Full suite: `pytest tests` ≈ 7 min, 2388 passed, 0 failed (2026-11-04); `make test-fast` ≈ 35 s. The old
  scene_detect failure was fixed in upgrade phase 4 (PySceneDetect 0.7's
  MERGE flash filter, not ffmpeg).

## Phase status

- Phase 0 (setup): done.
- Phase 1 (voice audition): done 2026-11-04, **owner picks the narrator.**
  `scripts/fa_voice_audition.py`; page
  `projects/_voice_audition/2026-11-04/index.html` (6 voices x 2 styles,
  $0.073). Top by round-trip: Charon calm, Puck energetic; the Samsung
  sample used Kore energetic.
- Phase 2 (channel bible): done. `lib/channel_bible.py`, skill
  `skills/creative/channel-bible.md`, template `channels/_template/`. The
  live channel `fa-main` is in `D:/project/videio v/channels/` (private
  backup repo, `OPENMONTAGE_CHANNELS_DIR` in `.env`). 3 lexicon suggestions
  wait for the owner (e.g. «صدها» heard as «ست‌ها»).
- Phase 3 (`gemini_video_analyze`): done. AvalAI does not fetch YouTube
  links (it invents an answer); pass local files.
- Phase 4 (first transcreation): **waiting for the owner** — both samples
  exist now: animated-explainer `renders/sample_music_a_fun_and_games.mp4`
  and character-animation `renders/sample_character_animation.mp4` (10 s,
  hand-drawn SVG rig in `character-sample/`, $0, decision d12, review
  `renders/sample_character_review.json`). Owner: pick the pipeline, the
  narrator voice, and approve the full 90 s budget (~$2).
- Phase 5 (dub gaps): **done.** Acceptance run on an owned 2.5 min
  two-speaker test source (`projects/_dub_test/`, rights own): QA passes
  (no overlaps, round-trip ≥ 0.90 on all 25 lines, −13.96 LUFS /
  −1.07 dBTP). Render: `projects/_dub_test/renders/dub_fa.mp4`. Cost of the
  whole test about $0.28.

Tooling upgrade (separate brief, `UPGRADE_PROMPT.md` v2 in the parent
folder): progress in `docs/fa/UPGRADE_PROGRESS.md`, measured starting point
in `docs/fa/BASELINE.md`. Phases 0–6 done 2026-11-04; phase 7 (series
template) waits for the owner's approval of the Samsung video.

New since the upgrade (details in the progress file and in
`skills/creative/persian-localization.md`):

| Piece | Where |
|---|---|
| Loudness to −14 LUFS / −1 dBTP | `tools/audio/loudness_normalize.py` |
| Preview profiles | `lib/media_profiles.py` (`preview_720`, `preview_540`) |
| Parallel runs per provider | `lib/parallel_runner.py` |
| Draft/final stills, approved pins, style refs | `tools/graphics/fa_image.py` |
| Cost estimate + price table | `scripts/fa_estimate.py`, `config/fa_pricing.yaml`, `scripts/fa_pricing_update.py` |
| Fast tests | `make test-fast`, `test-fast.bat`, `tests/slow_tests.txt` |
| LLM router (worker/bulk/vision, CLI) | `tools/text/`, `config/llm_routing.yaml`, `skills/meta/delegation-protocol.md` |
| Bake-off | `scripts/llm_bakeoff.py`, `docs/fa/llm_bakeoff/` |
| Camera language, editing tricks, edit style cards | `skills/creative/camera-language.md`, `editing-tricks.md`, `styles/editing/` |
| Style learning + compliance check | `tools/analysis/edit_style_extractor.py` |
| Render QA, hook lab, fact-check | `scripts/fa_render_qa.py`, `scripts/fa_editorial.py` |
| Studio FA production pages | `studio_fa/production.py`, `studio_fa/ui/production.js` |
| Script retention lint | `scripts/fa_script_lint.py`, `lib/fa_script_lint.py`, `skills/creative/narration-craft.md` |
| Beat grid / snap / align | `tools/audio/beat_detect.py` |
| Procedural SFX (licence-free) | `lib/sfx_synth.py` |

## Current production: KGB remake (2026-11-05)

Owner switched (2026-11-05) from the Soviet Union video to ArchiveInMinutes'
"The ENTIRE History of the KGB in 13 Minutes" (https://www.youtube.com/watch?v=VNJhu4rh6OY,
13:51, 237K views); the Soviet Union kit stays in `projects/_reference/archive-soviet-union/`
unused. KGB kit: `projects/_reference/archive-kgb/` ($0.028; notes incl. the
Persian market in `REFERENCE_NOTES.md`). The source uses AI cartoon stills,
~3.1 s shots, 166 wpm, cold open in Dresden 1989.

Project `projects/kgb-history-fa/`, manual-images mode (owner makes the stills
in Google Flow with ZAPI FLOW):
- Defaults chosen by the agent (owner asked to just build; may change):
  full KGB history, ~8 min, narrator Charon
  (tense documentary style, AvalAI route), channel cartoon look with Soviet
  red as the single accent.
- Owner (2026-11-05): videos are for every audience, no Iran angle unless
  asked (rule in `channels/fa-main/channel.md`). The Iran thread was
  removed; the cold open is now Gordievsky in the car boot at the border
  (second person), closed at s29–s31.
- `manual_images/shotlist.json`: 37 scenes, 98 shots, 7.8 min, 12 recurring
  characters in `style.characters` (described, not named, for Flow).
  Owner (2026-11-05): no text on screen: `captions: false`, no stamps, no
  empty caption band in the prompts. Every shot after a scene's first has a
  `cue` (the words it appears on); `manual_images/alignment.json` lists each
  shot with the words spoken over it (avg 4.8 s per still, max 8.7 s).
- `artifacts/sources.md`: every claim with its sources; left out Moqarebi,
  the number of expelled diplomats and the "40 men" (unverified).
- Script lint (`artifacts/narration.lint.json`): risk medium, no high
  findings after two revision passes.
- Prompt pack: `manual_images/zapi_flow.txt` (98 lines), `prompts.html`.
- Narration done: 40 clips in `manual_images/audio/` (Charon via AvalAI, 492 s = 8.2 min, ~$0.11).
  The Windows system proxy (v2rayN) breaks AvalAI calls when it is down: run with
  `NO_PROXY=*` and the HTTP(S)_PROXY variables unset; clips are cached, a rerun only voices missing scenes.

- Images arriving (2026-11-05): ZAPI FLOW names are unreliable here (a file
  often carries the next row's number, some rows were made twice), so
  images are matched to shots by looking at them; `manual_images/flow_import.json`
  logs each copy. 18/98 in after the first batch.
- Music: 10 Suno sections, prompts in `music/SUNO_PROMPTS.md`; files go to
  `music/m01.mp3`…`m10.mp3` and are already wired as `music.sections`
  (cross-fade 1 s; a missing file is only a warning).
- Sound design: `sfx` in the shot list (swish on scene changes, whoosh on
  flash jumps, 18 cued accents, 3 crackle beds) from `projects/_sfx_library/fa-v1`.
- Images: 53/98 in (content-matched; 2026-11-05 ~09:30). Music m01, m02 from the owner's Suno runs (Downloads/1.mp3, 2.mp3); bed sits ~19 dB under the mix (volume 0.16).
- Render by music section, not by scene, so a track never restarts mid-section: `renders/preview_99s.mp4` = scenes 1–9 with m01+m02.
- Earlier note: 27/98 in (content-matched). Rejected row 34 (hammer and sickle on
  the US Great Seal); the seal prompts now say so. Redo list for the owner:
  `manual_images/zapi_redo.txt` (rows in `zapi_redo_rows.json`).
- Building as images arrive: `preview --from A --upto B --render` per scene
  (windows in `manual_images/scene_windows.txt`), loop in
  `projects/kgb-history-fa/render_scenes.sh s07 s08 ...`; renders in
  `renders/preview_<A>-<B>s.mp4`, stitched to `renders/kgb_so_far.mp4`
  (scenes 1–5, 56 s). Render needs `npm_config_prefer_offline=true` (the
  npx check times out on the dead proxy) and `HYPERFRAMES_BROWSER_PATH` =
  installed Chrome; ~6 s of render per second of video.

Next: owner pastes `zapi_flow.txt` into ZAPI FLOW (Flow image mode, 16:9,
serial number in file name) → `scripts/fa_manual_images.py import --project
projects/kgb-history-fa --from <download folder>` → `check` → look at the
images (no text, same faces) → pick a tense music track (none chosen yet;
Mixkit, licence copy in assets/music/) → `build --render` → render QA.

## Earlier production: first transcreation

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

0. Remake from a link works for YouTube Shorts and long videos (real runs:
   $0.014 and $0.081, `docs/fa/UPGRADE_PROGRESS.md`). Owner: send a link to
   remake → the agent presents 2–3 concepts. Instagram needs the owner's
   exported cookies.txt (outside the repo) or the reel file.
1. Research sessions (2026-11-04, on another Claude account) stopped
   before writing their reports; no findings were saved anywhere. They left
   three uncommitted tools, now finished and tested (commit `195d15e`):
   the script retention lint + `narration-craft` skill (narration/hooks),
   `beat_detect` and `sfx_synth` (editing). Animation craft is largely
   covered by `camera-language.md`; **YouTube packaging (titles, thumbnails,
   topic choice) has no skill yet** — rerun that research if wanted.
2. Owner picks the pipeline for the full video from the two samples.
3. Owner: pick the narrator voice (audition page) and approve the full
   90 s budget; then script stage for the full video.
4. Optional: `fit_all` could let the last dub line run to the end of the
   video instead of flagging it. (Image providers are in Studio FA's health
   page since upgrade phase 6.)
5. Owner: confirm or change the bake-off's worker/bulk model picks
   (`docs/fa/llm_bakeoff/report.html`, Studio FA → مسیریابی متن).
6. `fa` is pushed to `AbolfazlHamii/OpenMontage` up to `6ff8807` (2026-11-05,
   owner's go-ahead; includes the fixes for eight edge cases found by the
   code review of the edit pass, hook lab and manual-images mode). Push
   again only when the owner asks.
