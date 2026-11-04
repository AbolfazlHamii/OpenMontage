# Persian (Farsi) productions

Read this before any stage of a production whose narration, dub or captions
are in Persian. It covers the parts that break silently for Persian: voice
routing, text written for TTS, dubbing gaps and right-to-left captions.

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
  «وازنیاک»); keep a per-channel pronunciation list and reuse it.
- Zero-width non-joiner (U+200C) in «می‌شه», «شرکت‌ها».
- One register per production: spoken Tehrani for YouTube storytelling,
  written Persian for formal explainers. Never mix.
- Persian usually runs longer than English. For dubs, budget each line:
  `max_chars ≈ segment_seconds × voice_chars_per_second` (measure cps from the
  approved sample) and rewrite rather than speeding audio past 1.08×.

## Dubbing (localization-dub) — known gaps

- There is no stem-separation tool yet. Without one, the dub either keeps the
  English voice under the Persian or loses the music and effects. Separate
  vocals from accompaniment (Demucs) before mixing; mix the Persian voice over
  the accompaniment stem with `audio_mixer` (tracks placed with offsets).
- Get speakers from `transcriber` with `diarize: true`; map each speaker to a
  fixed voice for the whole video.
- Energy matters more than accuracy for entertainment dubs: give every turn
  a `style` that matches the source moment (shouting, laughing, whispering).

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
- Learn a style from a reference with `edit_style_extractor` (cards land in
  `styles/editing/learned/`); keep downloads and keyframes under
  `projects/_reference/<name>/` (git-ignored). Check renders against the card
  with its `compare` operation.

## Working from Iran

- Google's Gemini docs and API answer 403 from Iranian IPs and from many
  VPN exits too. Use AvalAI (above), or run on a VPS in a supported region.
- AvalAI is an Iranian service: reach it directly, not through the VPN.
  When `HTTPS_PROXY` points at a local VPN client (v2rayN `127.0.0.1:10808`)
  and that client stalls, AvalAI calls die mid-response (`IncompleteRead`,
  `SSL: UNEXPECTED_EOF`) while `curl --noproxy "*"` answers in a second.
  Add `api.avalai.ir` to `NO_PROXY` for the run. A broken mid-response call
  may still be billed; check the AvalAI dashboard.
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

## Review

Before presenting a Persian render, extract frames where captions contain
punctuation or Latin words and check reading order, and listen to the first
and last 10 seconds of narration for mispronounced names and numbers.
