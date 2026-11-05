# Persian (Farsi) productions

Read this before any stage of a production whose narration, dub or captions
are in Persian. It covers the parts that break silently for Persian: voice
routing, text written for TTS, dubbing gaps and right-to-left captions.
Read the channel's bible too (`skills/creative/channel-bible.md`): tone,
voice, lexicon and past edits live there.

## Voice

- `tts_selector` detects Persian text (or `language_code: "fa"`) and routes it
  through `PERSIAN_TTS_PRIORITY`: gemini_tts → avalai_gemini_tts →
  elevenlabs_tts (eleven_v3) →
  openai_tts → azure_tts (fa-IR voices) → piper_tts (fa_IR voice). Providers
  outside that list are never used for Persian, because the generic scorer
  does not know which providers speak it. If none is configured the call
  fails with a clear error instead of producing English-voiced gibberish.
- **Gemini 3.8 Flash TTS (default):**
  - The text is read verbatim. Put delivery direction in `style`
    (e.g. "پرانرژی و هیجان‌زده مثل یوتیوبر قصه‌گو، لهجه‌ی تهرانی محاوره"),
    never inside the text. Short vocal events can go inline: `<laugh>`,
    `<sigh>`, `<short pause>`.
  - At most 2 speakers per request (`turns` + `speakers`). For 3+ speakers
    synthesize each turn separately.
  - Input is capped at 8,192 tokens: synthesize scene by scene, never a whole
    long narration in one call. Use `gemini-3.8-flash-lite-tts` for drafts and
    approval samples, `gemini-3.8-flash-tts` for finals.
  - Output is WAV (24 kHz mono); `audio_duration_seconds` is returned.
  - The Gemini API is not offered in every country (Iran is not on Google's
    list); run productions from a machine in a supported region.
- **AvalAI (`avalai_gemini_tts`, second in the order):** the same Gemini 3.8
  TTS models, voices and `style`, through AvalAI (`AVALAI_API_KEY`), usable
  from Iran. AvalAI serves them on native `generateContent`, not on the
  Interactions API that `gemini_tts` uses, and does not expose the voice
  library (`list_voices`); pick voice names from the Gemini voice list.
  Cost is computed from `usageMetadata` (AvalAI promo price until
  2026-12-31, then double).
- **Fall-through:** for Persian with `preferred_provider: "auto"`, a provider
  that fails at call time (Google refusing the region, out of credit) is
  skipped and the next one in the order is tried; `fallback_from` in the
  result lists what failed. A different provider can mean a different
  voice: for a whole narration pass `allowed_providers: ["gemini", "avalai"]`
  so it never drifts to another voice family mid-video, and check
  `fallback_from` before mixing clips.
- ElevenLabs: only `eleven_v3` speaks Persian; `language_code: "fa"` selects
  it. v3 takes at most 5,000 characters per call.
- OpenAI `gpt-4o-mini-tts` (also through `OPENAI_BASE_URL` gateways such as
  AvalAI/GapGPT): works, no Persian-native voice; give `instructions`.
- Piper offline fallback needs a Persian voice downloaded (e.g.
  `fa_IR-amir-medium`); the selector passes that model name automatically.
- Always render one 20–30 second sample and get approval before the full
  narration.

## Images

- The owner can make the stills by hand in Nano Banana: `skills/meta/manual-images.md`
  (prompt pack with copy buttons, image check, narration, timing, render).
- Pin the model: `image_selector` with `model: "gemini-3.1-flash-image"`
  (Nano Banana 2) tries `google_imagen` first and, when Google refuses the
  call (403 from Iranian IPs and many VPN exits), retries the same request
  and model on `avalai_gemini_image`. `fallback_from` lists what failed.
  Without a pinned model there is no fall-through: Google's default
  (`gemini-nano-banana-2.1`) is not on AvalAI, and the scorer may pick any
  provider.
- `avalai_gemini_image` (`AVALAI_API_KEY`): `gemini-3.1-flash-image`
  ($0.0672 1K / $0.101 2K / $0.151 4K), `gemini-3-pro-image` ($0.134 up to
  2K, $0.24 4K), `gemini-3.1-flash-lite-image` ($0.0336 1K, drafts),
  `gemini-2.5-flash-image` ($0.04, 1K). Prices are AvalAI's live catalog;
  its docs say 2.5 was shut down on 2026-10-02 while the catalog still lists
  it. Up to 14 local reference images (`image_path`/`image_paths`,
  `generation_mode: "edit"`); no image URLs, no masks, no Imagen.
- AvalAI has no music model at all (no Lyria, no Suno; checked against its
  live catalog and docs). From Iran, `pixabay_music` fails too: pixabay.com
  times out directly and answers 403 through common VPN exits. Music has to
  come from a file the owner supplies (`music_library/` or the project's
  `assets/music/`), another VPN exit, or a machine Google serves (Lyria).
  Mind the licence: Suno's free tier is non-commercial, so a monetized
  channel needs a paid plan for Suno tracks.
- Mixkit works through the VPN (direct gets 403): its free music licence
  allows YouTube videos with no attribution, but forbids registering the
  track with Content ID or remixing it into a music-only track. Each
  `/free-stock-music/tag/<mood>/` page carries a JSON-LD track list
  (name, genre, artist, duration, MP3 URL, licence). Incompetech and Free
  Music Archive are reachable too (CC licences, attribution usually
  required). YouTube Studio's Audio Library needs the owner's own sign-in.
- Music bed level under Persian narration: `data-volume` ≈ 0.18 put a
  Mixkit film-score track ~14 dB under the voice; lift it on the punch
  line and fade it before the end.

## Writing the script for TTS

- Numbers as words in narration («هزار و نهصد و هفتاد و شش»); captions may
  keep digits («۱۹۷۶»). Keep the two versions side by side in the script.
- Foreign names in Persian spelling the voice can read («استیو جابز»,
  «وازنیاک»); the channel's `lexicon.tsv` is that list, and `tts_selector`
  applies it when given `channel`. `lib/fa_text.spell_numbers` turns digits
  into words.
- Pace: Gemini 3.8 voices read spoken Persian at **8.6–10.5 letters per
  second** (6 voices × calm/energetic, 2026-11-04 audition; letters and
  digits only, `lib/fa_text.chars_per_second`). Budget ~9.5, not the 14
  an English rule of thumb suggests: a 150-letter line is ~16 s.
- Round-trip check (`scripts/fa_voice_audition.py`, `avalai_stt`): the
  transcriber writes spoken forms in written Persian («جوون» → «جوان»,
  «کوچیک» → «کوچک»), so compare with `lib/fa_text.round_trip`, which folds
  those. Real slips seen: «صدها» heard as «ست‌ها» (2 of 12 voices), a year
  replaced by «سالی از اون روزها», «جیب» read as «دست». The lite and full
  models both change words now and then; listen to any final clip whose
  round-trip is under 0.97.
- Zero-width non-joiner (U+200C) in «می‌شه», «شرکت‌ها».
- One register per production: spoken Tehrani for YouTube storytelling,
  written Persian for formal explainers. Never mix.
- Persian usually runs longer than English. For dubs, budget each line:
  `max_chars ≈ segment_seconds × voice_chars_per_second` (measure cps from the
  approved sample) and rewrite rather than speeding audio past 1.08×.

## Dubbing (localization-dub)

`scripts/fa_dub.py` (`lib/fa_dub.py`) runs the Persian dub stage by stage:
prepare → translate → (review, approve) → synth or export-vo/import-vo →
mix → qa. Notes from the first real run (2026-11-04, 2.5 min, 2 speakers):

- Stems: `stem_separator` (Demucs 4.1 htdemucs, CPU, ~1.25x real time,
  cached by content). Demucs 4.1 needs no torchaudio; weights come from
  Hugging Face on first use (~2 min here).
- Speakers: AvalAI cannot diarize (`gpt-4o-transcribe-diarize` returned
  plain text, $0.046). Instead whisper-1 gives word times ($0.015 per
  2.5 min) and Gemini listening to the audio gives who said what and each
  voice's gender; `align_turns` puts the turns on the word times. Quick
  hand-offs under ~0.5 s can land on the wrong speaker: read
  `segments_en.json` before translating.
- Voices: `voice_map.json` maps each source speaker to a `dub_pool` voice of
  the same gender (`VOICE_GENDER`), fixed for the whole video.
- Translation: the worker drafts in chunks of 6 lines (a whole video in one
  call ran out of tokens on the reasoning models and came back empty).
  Every line is final Persian, so the agent reviews all of them, then the
  owner; `approve` records edits in the channel bible. The first draft
  turned 1967 into «نهصد و شصت و هفت»: check every number.
- Timing: `lib/dub_timing.py` — budget = slot × cps, atempo up to 1.08x,
  at most 2 rewrites (worker, flagged `review_required`), then the silence
  before the next line, else flagged for the owner. The text is only
  rewritten before synthesis when it cannot fit even with the pause after
  it. An empty or longer rewrite is ignored (the reasoning workers return
  empty text when `max_tokens` is small; the shorten call uses 6000).
- Synthesis from Iran: `synth --providers avalai`. With Google first, one
  `gemini_tts` call hung for minutes on a stalled proxy socket (it had no
  timeout; now 120 s). Clips are keyed by line, voice, style and model, so
  editing one line re-synthesizes only that line.
- Mix: each line is matched to the original voice stem's loudness, laid
  over the accompaniment stem with `audio_mixer`, muxed with the source
  picture, then `loudness_normalize` to −14 LUFS / −1 dBTP.
- QA (`qa`): no line more than 200 ms into the next, round-trip per line
  ≥ 0.90, loudness, and a warning when the brief's `rights` is `unknown`.
  Transcribe with `gpt-4o-transcribe`: the mini model read 2 s Persian
  clips as Kurdish or Turkish. A low score on the sped-up placed copy is
  re-checked on the raw clip. A line both transcripts mishear the same way
  is a real risk (the voice turned «سکته» into «سکسه»): rewrite it with a
  different word rather than re-rolling the take. The final loudnorm aims
  at −1.5 dBTP, because the AAC encode lifted −1 back to −0.7.
- First real run (owned 2.5 min, 2 speakers, 25 lines): 11 worker
  rewrites, of which the agent kept 6 and rewrote 5 itself (the worker
  wrote «لاب», digits in speech, and dropped meaning); final QA passed.
  Cost about $0.28 including the test source and every retry.
- Energy matters more than accuracy for entertainment dubs: styles come from
  `gemini_video_analyze` segments (emotion, energy) by overlap.

## Captions (right-to-left)

- `subtitle_gen` detects Persian (`direction: "auto"`) and prefixes each line
  with U+200F; `video_compose` burns subtitles with ASS `Encoding=-1`. Both
  are needed, or the trailing «.» / «!» lands on the wrong side and a line such
  as «Steve Jobs و Wozniak …» reads in the wrong order.
- Fonts: install Vazirmatn on the render machine and pass
  `subtitle_style: {"font": "Vazirmatn"}`. The default Inter has no Persian
  glyphs. Remotion's `CaptionOverlay` already falls back to Vazirmatn/Tahoma
  and switches to RTL by word majority.
- Never ask an image or video model to draw Persian text; render titles and
  thumbnail text with HTML (HyperFrames/Remotion) so Chromium shapes it.
- HyperFrames: Vazirmatn is not in its bundled font set and the render
  browser has no installed fonts. Copy the TTFs into the workspace and
  declare them with `@font-face` (see
  `projects/samsung-history-fa/hyperframes-sample/index.html`).
- HyperFrames captions: hide a finished caption group with opacity only.
  A sample whose groups were killed with `tl.set(el, {visibility:
  "hidden"})` plus build-time `tl.seek()` self-checks rendered no captions
  at all, although the same page was correct in a normal browser.
- HyperFrames + GSAP: never `fromTo()` a flash or overlay that starts late;
  `fromTo` applies its start state at build time (a fire flash tinted the
  whole video orange). Use `tl.set()` at the start time plus `tl.to()`.

## Motion and editing (RTL)

- Pick an edit style card (`styles/editing/*.yaml`) at proposal, next to the
  visual playbook; `full-history-in-n-minutes` is the channel's default for
  "کل تاریخ X" videos. Recipes: `skills/creative/editing-tricks.md`,
  `skills/creative/camera-language.md`.
- Motion that means "forward in time" goes right→left; "before" sits on the
  right in split screens.
- Animate whole Persian words, never single letters: per-letter spans break
  Arabic-script joining. Line breaks between words only; keep ZWNJ.
- Word-level caption highlight: HTML spans in the composition, not ASS colour
  overrides (libass shaping across overrides is unverified for Persian).
- Beat-synced cuts: `beat_detect` (analyze / snap inside speech pauses /
  align a downbeat to the punch line). Missing SFX: `lib/sfx_synth.py`
  (procedural, licence-free).
- Learn a style from a reference with `edit_style_extractor` (cards land in
  `styles/editing/learned/`); keep downloads and keyframes under
  `projects/_reference/<name>/` (git-ignored). Check renders against the card
  with its `compare` operation.

## Remake from a link

The owner pastes a YouTube (Shorts or long), Instagram, TikTok or X link and
asks for a Persian version: follow `skills/meta/remake-from-link.md`
(`scripts/fa_remake.py`, or Studio FA → ویدیوی جدید → «از لینک بساز»).

- Default is **transcreate**: structure, pacing and hook technique only; our
  own research, script, images and voice. Dub needs `rights`
  (own / licensed / permission) and is refused without it.
- YouTube answers 429 to caption downloads from this network; the kit falls
  back to AvalAI whisper-1 with the source language from the metadata.
  `avalai_stt` defaults to `fa` (it checks our own TTS): never call it on a
  foreign video without `language`, or the transcript comes back as Persian
  gibberish.
- Instagram needs a cookies.txt the owner exports (outside the repo,
  `OPENMONTAGE_COOKIES_FILE`) or the reel as a file.
- The kit puts `api.avalai.ir` in `NO_PROXY` for its run (below).

## Working from Iran

- Google's Gemini docs and API answer 403 from Iranian IPs and from many
  VPN exits too. Use AvalAI (above), or run on a VPS in a supported region.
- AvalAI is an Iranian service: reach it directly, not through the VPN.
  When `HTTPS_PROXY` points at a local VPN client (v2rayN `127.0.0.1:10808`)
  and that client stalls, AvalAI calls die mid-response (`IncompleteRead`,
  `SSL: UNEXPECTED_EOF`) while `curl --noproxy "*"` answers in a second.
  Add `api.avalai.ir` to `NO_PROXY` for the run. A broken mid-response call
  may still be billed; check the AvalAI dashboard.
- Video understanding (`gemini_video_analyze`): AvalAI accepts a YouTube
  `fileUri` but the model never sees the video and invents an analysis
  (434 prompt tokens, an answer about a different topic; 2026-11-04). The
  tool refuses links on the AvalAI route and rejects any answer whose
  prompt token count is far below the video's (~98 tokens/s at low
  resolution). Pass a local file instead; files over ~14 MB go as a 360p
  proxy. A 3-minute reference cost $0.020 through AvalAI.
- `hyperframes render` downloads `chrome-headless-shell` from Google
  storage, which answers 403 from Iran. Point it at the installed Chrome:
  `HYPERFRAMES_BROWSER_PATH=C:\Program Files\Google\Chrome\Application\chrome.exe`
  (lint, check and snapshot already work without it).
- Downloads (pip, npm, GitHub release assets) often stop halfway with no
  error, leaving a truncated file. Check sizes/zip integrity, and retry
  through a proxy with resume (`curl -C -`).
- Windows: `fc-list` does not exist. Install Vazirmatn per user
  (`%LOCALAPPDATA%\Microsoft\Windows\Fonts` + the HKCU Fonts registry key)
  and set `SUBTITLE_FONTS_DIR` to that folder: ffmpeg's libass only scans
  `C:\Windows\Fonts`, and silently burns Arial instead (with a missing-glyph
  box in words like «دلار»). Confirm with
  `python scripts/fa_smoke_test.py subtitles` and look at the frame.

## Cost and speed defaults

Measured against the Samsung sample (`docs/fa/BASELINE.md`): images were 98%
of the spend, and 57% of tool time went to failed calls.

- **Estimate first.** Before any paid stage run
  `python scripts/fa_estimate.py --scene-plan … --script …` (or `--brief`,
  or `--plan`) and show the owner draft and final totals. Prices come from
  `config/fa_pricing.yaml`; the script warns when the table is older than
  14 days (`python scripts/fa_pricing_update.py` refreshes it from AvalAI).
  On the sample it matched the project's metered cost ($0.2049).
- **Images go through `fa_image`.** `mode: draft` (flash-lite 1K, $0.0336)
  while the look is being decided; `mode: final` (flash 2K, $0.101) only for
  stills the owner has agreed on. When the owner approves a still, call
  `fa_image` with `operation: approve`: it is pinned under
  `assets/approved/` by hash and every later request for that scene returns
  the pinned file for free. Never regenerate an approved scene; ask the owner
  to unapprove it first. Gemini image models take no seed, so these calls
  are never cached; providers that take a seed get a stable one from
  `fa_image`.
- **Independent calls run in parallel.** Scene stills go through
  `fa_image` with `operation: batch` (one item per scene); narration lines
  through `lib/parallel_runner.run_parallel` around `tts_selector`. Both cap
  concurrency per provider (default 3). A failed item is reported in the batch summary; retry only
  that item. Three stills: 54 s serial in the sample, ~11 s in parallel
  (`plan_makespan`).
- **Every render before approval is a preview.** HyperFrames:
  `quality: "draft"` (CRF 28, fastest x264 settings; 15 s sample rendered
  in 37 s instead of 53 s). FFmpeg path: `profile: "preview_720"` or
  `"preview_540"`. Delivery settings (`standard`/`high`,
  `youtube_landscape`) only for the approved cut.
- **Delivery loudness: −14 LUFS, true peak ≤ −1 dBTP.** HyperFrames and
  Remotion mix their own audio (the sample came out at −11.5 LUFS), so run
  `loudness_normalize` on the final render (its defaults are −14 / −1).
  When `audio_mixer` builds the mix, pass `loudnorm_target: -14`; its
  limiter sits at −1.5 dBTP, which already meets the ceiling. Do not change
  `audio_mixer`'s −16 default: it belongs to upstream podcast pipelines.

## Text models (LLM router)

- **Red line: a cheap model never delivers final Persian text.** Narration,
  final subtitles, titles and descriptions always pass premium review (the
  agent in interactive mode). `llm_selector` refuses to send `*_final` tasks
  to a cheap tier. Drafts from cheap models are raw material only.
- Bulk text goes through `python -m tools.text.llm_selector` (see
  `skills/meta/delegation-protocol.md`). Bake-off 2026-11-04
  (`docs/fa/llm_bakeoff/`): deepseek-v4.1-flash wrote the most accurate
  colloquial Persian per dollar; gemini-3.8-flash sounds liveliest but
  invents facts (an unsourced "20% of Korea's economy" hook), so fact-check
  its drafts; Kimi K2.6 returned empty answers when its reasoning used the
  whole output budget; qwen misspelled the founder's name (لی بونگ‌چول).
- Google's OpenAI-compatible endpoint answered 403 from the owner's network
  on 2026-11-04, same as images; the router falls through to AvalAI.
- Cheap models add preambles ("for a YouTube video I wrote…") to
  translations; strip them, and ask for "output only the text".

## Script retention lint

Before any narration is synthesised, run
`python scripts/fa_script_lint.py <draft.txt|script.json> --target <s> --voice narrator`
and follow `skills/creative/narration-craft.md` (hook by 3 s, first open loop
by 10 s, a «ولی»/question/number every ≤ 8 s, sentences ≤ 7 s, spoken
register, numbers as words, a real ending). It times the text with the
narrator's measured pace from `channels/fa-main/voices.yaml`.

## Editorial steps (hook lab, fact-check)

- **Hook lab (script stage, before the narration is written):**
  `python scripts/fa_editorial.py hooks --project projects/<id> --topic "…" --brief facts.txt`
  drafts 12 hooks (worker tier). Read them, put your 3 best with reasons in
  `artifacts/hooks.json` → `shortlist`, run `log-hooks` (decision
  `hook_selection`, `pending_owner`), show the 3 to the owner, then
  `log-hooks --owner-pick N` with the owner's choice. Rewrite the chosen hook
  yourself; the draft is raw material.
- **Fact-check (historical content, after the script, before TTS):**
  `fa_editorial.py claims` extracts claims (bulk tier) into
  `artifacts/claims.json`. Check each against a source and set `verdict`
  (`verified` / `corrected` / `removed` / `unverified`) and `source`; then
  `log-claims` writes a `fact_check` decision. Do not record narration while
  any claim is `unverified`.

## Visual consistency

- Once the owner approves the look, pin it: `fa_image` with
  `operation: set_style`, `style_reference` (an approved still),
  `character_sheets` (one per recurring person) and `palette_tokens`
  (e.g. "navy #1b2a4a, cream #fff8ec, cobalt #1428a0"). Every later
  generation sends the reference images and appends the palette; name the
  people in a scene with `characters: [...]`.
- Keep palette tokens unchanged for the whole video; change them only per era
  by design, and log it.

## Quality gate

Before showing any render to the owner:

```bash
python scripts/fa_render_qa.py projects/<id>/renders/<file>.mp4 --script projects/<id>/artifacts/script.json --srt <subtitles.srt> --workspace <index.html> --images "projects/<id>/assets/images/*.png" --check-images --out projects/<id>/renders/<file>.qa.json
```

It checks −14 LUFS ±1 / true peak ≤ −1, black and frozen frames, A/V sync,
duration vs script, caption overlaps / reading speed / RLM / safe area, RTL
in the workspace, and text inside generated images (vision_bulk, ~$0.0003 an
image). Paste its Persian summary to the owner. Exit 2 = fix before review.
On the Samsung sample it flagged −11.5 LUFS (fix: `loudness_normalize`).

## Control panel

`python -m studio_fa` (or `studio-fa.bat`) opens a local Persian panel on
http://127.0.0.1:4760/: provider order and health, keys (written to `.env`),
voice auditions through `tts_selector` with duration, cps, cost and
fallback, RTL subtitle frames, the Persian tests, and each project opened in
Backlot. Auditions are kept in `.studio_fa/tts_history.jsonl`.

Production pages (`studio_fa/production.py`): new-video wizard (topic →
format/length → edit style card → voice → budget, with `fa_estimate` shown
before anything is created; it writes `project.json`, `artifacts/brief.json`
and `artifacts/estimate.json`), stage timeline with approve/reject that
appends to `decision_log` (subject `Checkpoint review: <stage>` — read these
before continuing a gated stage), cost dashboard (per project and month, from
`events.jsonl` + `cost_log.json`), provider health (TTS, image, LLM profiles;
the ping only lists models, free), style gallery + "learn from a link"
(cost estimate first, refuses over $0.50), and LLM routing per tier (writes
`config/llm_routing.yaml`). `samsung-history-fa` is read-only in the panel.
Screenshots: `docs/fa/screens/`.

## Review

Before presenting a Persian render, extract frames where captions contain
punctuation or Latin words and check reading order, and listen to the first
and last 10 seconds of narration for mispronounced names and numbers.
