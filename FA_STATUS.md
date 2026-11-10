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
| Second-language audio track (YouTube multi-language audio) | `lib/fa_audio_track.py`, `scripts/fa_audio_track.py` | `manual_images/narration_<lang>.json` (text per scene + voice) → `synth` (same voice groups, transcript split, reports each line against its window; > x1.12 speed-up = rewrite shorter) → `mix` (the render's own music sections and SFX cues, -14 LUFS) → `preview` (video with the new track); `srt` = subtitles in that language timed to the video's Persian voice (transcribes the render once, ~$0.04; merges cues under 1 s or over 17 chars/s). KGB English, 2026-11-09: 37 lines all fit (max x1.07), $0.14, `renders/kgb-history_audio_en.wav` + `renders/kgb_final_en.mp4`. Upload needs the channel's Advanced features; delete YouTube's auto dub for that language first |
| Desktop shortcut | `Desktop\استودیو ویدیو فارسی.lnk` | Opens `studio-fa.bat` minimized (not in the repo) |

## Environment (owner's Windows laptop)

- Repo: `D:\project\videio v\OpenMontage`, venv `.venv` (Python 3.11).
- ffmpeg 8.1: `%LOCALAPPDATA%\Programs\ffmpeg\ffmpeg-n8.1-latest-win64-gpl-8.1\bin`
  (on the user PATH; shells started before the install need it added).
- Vazirmatn installed per user; `.env` sets `SUBTITLE_FONTS_DIR`.
- Keys in `.env` (git-ignored): `GOOGLE_API_KEY`, `AVALAI_API_KEY`,
  `DAHL_API_KEY`. Key values also live in the owner's private secrets file,
  never in the repo.
- Dahl Inference (`https://inference.dahl.global/v1`, added 2026-11-09):
  OpenAI-compatible, **text only** — `/audio/*`, `/images/*` and
  `/embeddings` return 404, `image_url` parts are rejected. Live models:
  `MiniMaxAI/MiniMax-M2.7` (puts `<think>…</think>` inline; the tool strips
  it), `deepseek-ai/DeepSeek-V4-Flash-0731`, `zai-org/GLM-5.3-Flash`
  (`GET /v1/models`, no key). $0.02 per 1M tokens in+out after the 100M free
  grant; **the free grant burns after 7 days without a request**. Free
  accounts get frequent `429 model_concurrency` at peak (paid first). Prompts
  run on independent operators of the Gonka network (privacy policy): no
  private material. Direct connection works from Iran; profile uses
  `proxy: direct`. Key balance: `GET /tokens/current` with the key.
  Verified 2026-11-09: JSON-mode hooks in Persian via `openai_compat_llm`
  from MiniMax (~350 tokens) and GLM; DeepSeek returned 429 at that moment.
  Persian quality is rough (emoji, a Latin fragment inside a Persian word),
  so it is not in any tier (bake-off 2026-11-09: see Next steps 5).
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
| Dahl profile (text only, not in a tier yet) | `config/llm_routing.yaml` (`dahl`), `config/fa_pricing.yaml` (`llm.dahl`) |
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
- Owner review of the first 1:40 (2026-11-05): images too sparse from 0:12
  (missing rows held on screen), an abrupt jump into the history at 0:40, and
  the 0:49 line ("its leader fears something") was loose. Fixed: s05 now
  bridges from the car boot ("how did this man end up in a car boot? … back to
  winter 1917") with `image: s01c` reuse, the Cheka is "a special commission to
  fight counter-revolution and sabotage" (its official name, Wikipedia), and
  `rhythm.max_still: 3.6` adds punch-in cuts (avg cut 2.6 s). 58/98 images in;
  redo list `manual_images/zapi_redo.txt` (14 rows), new images continue at row 72.
  Section windows: `manual_images/render_windows.txt`.
- Render by music section, not by scene, so a track never restarts mid-section: `renders/preview_99s.mp4` = scenes 1–9 with m01+m02.
- Round 3 (2026-11-05 ~12:00): owner's Suno tracks 3–6 are `music/m03`–`m06`
  (m07–m10 still to come). 77 images in after importing rows 75–98 (names
  matched rows this time, still checked by eye; row 80 was a broken 126 px
  icon, rows 72, 73, 79, 87, 88, 90 never came). To keep the rhythm every
  still held over ~5 s got a new shot on the words it covers (backup:
  `shotlist.before_round3.json`, script logic: one new shot per long still,
  ids end in x/y/w): 148 shots, avg 3.2 s per still, max 5.9 s (the outro).
  Free callbacks: s06a reuses the 1917 room (s39c), s29r the car boot
  (s01c), s39r the four-eras line-up (s04x). Everything still missing
  (67 = 47 new + 14 redo + 6 never made) is in `manual_images/zapi_round3.txt`
  (rows → shots in `zapi_round3_rows.json`); this replaces `zapi_redo.txt`.
  `render_sections.sh [upto]` renders one window per music section and joins
  them into `renders/kgb_so_far.mp4`.
- Round 3 images (2026-11-05 ~13:30): the owner now saves ZAPI FLOW output to
  `Downloads/zapi-img/`. 56 matched by content (names lagged one row up to
  row 21, matched from row 22 on; five "29_*" files were copies of other
  rows). s15x now reuses s15a (the same study). 133/143 in; the last 10 are
  in `manual_images/zapi_round4.txt`. Full render (all sections, music only
  up to m06) runs via `render_sections.sh 475.5`.
- Round 4 (2026-11-05 ~13:45): 9 of the last 10 in (from `zapi-img/01–10`
  and `Downloads/1/`; extras kept in `in/alts/`). 142/143; only s05y (sailors
  storming the palace stairs) is missing, prompt in `Downloads/kgb_zapi_s05y.txt`.
- Owner review of 0–1:49 (2026-11-06), all applied:
  - "The voice sounds like a different person in places (1:20)." Per-scene
    TTS calls drift (median pitch 101–156 Hz). New in `lib/fa_manual_images.py`:
    `voice.groups` voices several scenes per call, `voice.align: "transcript"`
    transcribes the take (AvalAI whisper-1 word times, uploaded as 16 kHz mp3)
    and cuts at each scene's first word (`scene_breaks_from_words`,
    `split_on_pauses(..., breaks)`). Pause-only splitting failed (scene breaks
    are no longer than sentence pauses). KGB: 4 groups starting s01, s10, s19,
    s29 (on music changes). Cost: TTS ~$0.12 + STT ~$0.05.
  - "Type dates and names in English like documentaries (0:50, 1:12)." Shot
    field `title` (1–2 lines) is typed letter by letter bottom-left with a red
    block cursor (Courier New Bold from Windows, `TYPEWRITER_FONT` overrides),
    `sfx.title: "typing"` (new synth). 44 titles in the KGB shot list, dates
    checked (Cheka 20 Dec 1917, Lenin shot 30 Aug 1918, Bandera 15 Oct 1959...).
  - "The gunshot effect is weak." There was no gunshot; the generic hit played.
    New synth `gunshot` / `gunshots-3` (crack + body + thump + yard echo) in
    `lib/sfx_synth.py` and the library; three shots on «شلیک» in s08 (Kaplan
    fired three times), shots under the Kabul palace storming, «ترور سرخ» now
    the bass impact.
  - s05y made by API (owner asked): avalai gemini-3.1-flash-image 1K with s05a
    and s06w as style references, $0.067.
- `render_sections.sh [upto] [from]` now reads window edges from the music
  sections and the current narration instead of fixed times, and reuses
  windows before `from`.
- Bug found 2026-11-06: `preview` narrated each window on its own, so with
  voice groups every window became a new TTS take (9 extra takes, ~$0.16, and
  the 0–1:45 sent to the owner changed voice at 0:34). Fixed (commit 2906763):
  windows use the whole video's clips. Window joins also add ~1 s of tail per
  join; for the real cut use one `build --render`, not joined windows.
- First full cut (2026-11-06 04:09): `renders/kgb_full_v1.mp4`, one pass, 7:22,
  -14.1 LUFS, 143/143 images, 44 titles, both gunshots; phone copy
  `kgb_full_v1_small.mp4` (720p, 28 MB). Still missing: Suno m07–m10 (no music
  from Kabul to the end).
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

### KGB: finish without music (2026-11-06)

Owner: "build it to the end until I give you the music". Done:
- `renders/kgb_full_v2.mp4`: v1 re-leveled (two-pass loudnorm, −14.3 LUFS,
  true peak −1.7 dBTP; v1 hit 0.0 dBTP on the gunshots) and the audio cut
  to the video length. `fa_render_qa.py` passes (only warning: the end fade).
  `render_video` now normalizes to −2.5 dBTP (AAC lifts the peaks).
- `packaging/`: `titles.txt` (5 titles, rubric 88–100; recommended
  «از چکا تا پوتین: داستان کامل کا.گ.ب»), `description.txt` (hook, 15
  chapters from the final timing, 17 sources, music/SFX credit, 3 hashtags),
  `tags.txt`, `pinned_comment.txt`, thumbnails `thumbs_A|B|C/` (punch: car
  boot «فرار مرگبار»; era: Lubyanka today «۱۹۱۷ / هنوز روشنه»; question:
  eagle seal «توش چی بود؟»), all pass the phone check; `thumbs_ABC.jpg`.
- Open: Suno m07–m10 (then `build --render` once more, QA, re-check the
  chapter times), the owner's Suno plan must allow commercial use, Persian
  SRT not made (captions are off; could export one from the narration).
- **Final (2026-11-06 11:17): `renders/kgb_final.mp4`** (7:22, 1080p, QA pass:
  −14.4 LUFS, −1.0 dBTP). Owner said to use the existing music for the rest:
  m07–m10 are cut from unused parts of m05, m04, m02, m03 (notes at the end
  of `music/SUNO_PROMPTS.md`). Phone copy `kgb_final_small.mp4` is for viewing
  only. Timing unchanged, so the chapters in `packaging/description.txt` hold.
  The `youtube-upload` session (channel @spoilfa) was told to use this file.

## Blender Shorts test: "the spy eagle" (2026-11-10)

Owner sent three references (a tutorial on making 3D-background / flat-2D-character
Shorts with code, and two such Shorts, 27.8M and 0.8M views) and asked for a
20 s Blender test with detail, several characters, smoke and light, on a channel
topic, plus a viral strategy. `projects/short-thing-fa/` (git-ignored):
- `blender/build_thing.py` builds three toon sets in code (embassy garden, the
  ambassador's study, the street at night), flat 2D round-head characters
  (blink, talk, idle), smoke sprites, volume haze, a pulsing radio beam, 9
  cameras switched by markers; `-- timing.json out [preview]`.
- Laptop: RTX 2050 4 GB, Ryzen 5 7535HS, Blender 5.2 at `D:\software\New folder (2)`.
  Eevee 1080x1920: 446 frames in ~16 min (~2.2 s/frame; street with many lights
  hits "shadow buffer full" warnings).
- Voice: one take, 5 beats, $0.005. Captions: `make_captions.py` (word times
  from whisper, $0.002) then `make_captions_pop.py` (Lalezar OFL in `fonts/`,
  key words yellow, pop-in, lower third), drawn by headless Chrome because PIL
  here has no Persian shaping. Mix: `make_short.py` (music = KGB m04, SFX on
  cuts, two-pass loudness → -15.2 LUFS / -1.4 dBTP).
- Owner feedback so far: the first captions (Vazirmatn, centre) were "bad,
  centred, ugly" → replaced. Captions on Shorts are an exception to the
  channel's no-text rule (viral strategy); confirm with the owner.

### Video library (2026-11-10)

Owner asked for clean folders and numbered names. Finished videos now live in
`D:\projectideio v\SPOIL\` (outside the repo), one folder per video with a fixed
three-digit number: 001 KGB (fa, en-audio, phone preview, thumbs, texts), 002 Stasi
(in production: prompts, narration, sources), 003 spy-eagle Short, 004 boot-escape
Short. `SPOIL/README.md` is the Persian index (status, main file, working folder,
upload links). Next number: 005. KGB previews and superseded cuts moved to
`projects/kgb-history-fa/renders/_old/` (~4 GB, not deleted).

### Blender Short 2: "escape in the boot" (2026-11-10)

Owner: the eagle short was weak; wanted a far better, more creative 16 s Blender short
on another KGB topic. `projects/short-escape-fa/`: Gordievsky's 1985 escape (crisps
for the dogs and a nappy changed on the boot, per Macintyre / The Economist).
- `blender/build_escape.py`: second-generation 2D characters (almond eyes with
  glints, mood brows, talking mouths, sleeves with hands, shoes, walk cycles, ushanka,
  bob hair, a baby), two 3D German shepherds (sniff, tail wag, walk), a bevelled
  sedan with lamps and a hinged boot lid, a checkpoint with a lifting striped boom,
  booth, watchtower searchlight, pine forest, fog, moon; a POV set inside the boot
  (slit light, the dog's shadow, dust, heartbeat shake); a dawn set in Finland.
  10 shots in 16 s. `probe` mode times chosen frames at full size.
- Lessons: parenting with `matrix_parent_inverse` while the parent's world matrix
  is still identity puts children at parent + local, so give child coordinates
  relative to the pivot; keyed props can drift into another set's camera (hide
  them outside their shot); AgX greys flat whites (use Standard and grade later);
  motion blur + 32 samples + dense volumes made frames ~40 s, without them 1-4 s.
- Render 384 frames in ~11 min. Mix: owner's Suno m06, synth heartbeat on the
  boot shots, pop captions (Lalezar). Grade in YUV only (a screen-blended glow in
  RGB turned the frames magenta). -14.9 LUFS / -1.8 dBTP.

## Live-stream prototype: "The Archivist" (2026-11-10)

Offline test only; nothing streamed. Design note `docs/fa/ARCHIVIST_LIVE.md`, code
`lib/archivist/` (archive retrieval over the KGB/MI6 scripts, Dahl brain with moderation
and a fact-check pass, cipher game, rig and compositor), runner `scripts/archivist_test.py`
(assets | chat | voice | render), tests `tests/lib/test_archivist.py` (12 pass).
- Character stills (base, blink, two mouth shapes, page turn, shelf reach, file hold) in
  `projects/archivist-live-fa/stills/`; one voice for every line via Google REST TTS with a
  429 wait-and-retry (the SDK path hung).
- 8-message fake chat: 5 answered from the sources, off-topic refused ("not in my archive"),
  abuse dropped before it reaches the screen, cipher answer scored on the leaderboard.
- Sample `projects/archivist-live-fa/renders/archivist_sample.mp4` (1080p, 6:31) + sheet.
- Lesson: answer + verify took 17-80 s per question, far too slow for live; a live version
  needs a faster model, pre-voiced files while thinking, and the fact-check run in parallel.

## Next production: MI6 long video, library 005 (2026-11-10)

Chosen from the retention research (`channels/fa-main/research/2026-11-10_retention_and_next_long.md`):
MI6 is a top topic with almost no Persian coverage. Project `projects/mi6-history-fa/`.
- 104 scenes (`narration_draft.py`, revised by `revise1.py`/`revise2.py`): cold open on
  Philby ("the spy-hunter was the spy"), an open loop on the green ink paid off in the last
  line, a question or turn at least every 12 s (lint medium, no high), like-ask at s074.
  Claims and sources: `artifacts/sources.md`.
- Voiced in 9 groups with transcript alignment: 13.9 min of speech, video 14:32, $0.29
  (`clip_seconds.json`).
- Owner asked for more images: 428 cue-timed shots in `shots.py` (avg 1.95 s, longest
  ~4 s, `rhythm.max_still` 2.6), 48 typed English titles, 20 SFX marks, recurring
  visual callbacks (green pen, wolf in a shepherd's coat, green chess knight, invisible
  building). `build_shotlist.py` writes `manual_images/shotlist.json`.
- Owner hand-off: `manual_images/zapi_flow.txt` (428 lines, also `Downloads/zapi_mi6.txt`),
  `music/SUNO_PROMPTS.md` (m01–m09, also `Downloads/suno_mi6.md`); packaging in
  `SPOIL/005_long_mi6-history/`.
- Next: owner makes images (ZAPI FLOW, row numbers on) and music; `import`, `check`,
  `build --render`; then Shorts from this video with the 45–60 s story formula.

## Next production: Stasi (2026-11-06/07)

Owner chose the episode the KGB video teases. Own script (no ArchiveInMinutes
Stasi video was found). Project `projects/stasi-history-fa/`, same pipeline:
- 44 scenes, cold open on Vera Lengsfeld finding out from her file that
  "Donald" was her husband; callback to the KGB video in Dresden (s34).
  Claims and sources: `artifacts/sources.md` (unverified details left out).
  Lint: medium, no high findings (longest gap 10.7 s).
- Narration voiced in 4 groups (s01, s14, s25, s37) with transcript
  alignment: 344 s of speech, video ~6:00, $0.12.
- 117 shots after a rhythm pass on the voiced timing (avg 3.1 s, max 5.9 s);
  33 English titles; gunshots on Mielke's 1931 shooting; music sections
  m01–m08 (`music/SUNO_PROMPTS.md`).
- 5 stills copied from the KGB project (clock, four-eras line-up, Berlin Wall,
  Dresden officer, crowd at the gate); 111 prompts for the owner in
  `manual_images/zapi_stasi.txt` (rows in `zapi_stasi_rows.json`), also
  `Downloads/stasi_zapi.txt` and `Downloads/stasi_suno_prompts.md`.
- Next: owner makes the images (ZAPI FLOW → `Downloads/zapi-img/`) and the
  music; match images by content, import, render with `build --render`.

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
   Dahl's three models were added to the bake-off on 2026-11-09
   (`--run --only dahl`, $0.0004): quality 3.3 / 2.5 / 3.2 against 4.4 for
   AvalAI DeepSeek, and the free tier timed out or returned 429 on 4 of 15
   calls. Not in any tier; at most a last fallback for `json_fill` /
   `classification` if the owner wants it (`RECOMMENDATION.md`).
6. `fa` is pushed to `AbolfazlHamii/OpenMontage` up to `6ff8807` (2026-11-05,
   owner's go-ahead; includes the fixes for eight edge cases found by the
   code review of the edit pass, hook lab and manual-images mode). Push
   again only when the owner asks.
