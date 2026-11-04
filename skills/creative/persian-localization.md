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

## Working from Iran

- Google's Gemini docs and API answer 403 from Iranian IPs and from many
  VPN exits too. Use AvalAI (above), or run on a VPS in a supported region.
- Downloads (pip, npm, GitHub release assets) often stop halfway with no
  error, leaving a truncated file. Check sizes/zip integrity, and retry
  through a proxy with resume (`curl -C -`).
- Windows: `fc-list` does not exist. Install Vazirmatn per user
  (`%LOCALAPPDATA%\Microsoft\Windows\Fonts` + the HKCU Fonts registry key)
  and set `SUBTITLE_FONTS_DIR` to that folder: ffmpeg's libass only scans
  `C:\Windows\Fonts`, and silently burns Arial instead (with a missing-glyph
  box in words like «دلار»). Confirm with
  `python scripts/fa_smoke_test.py subtitles` and look at the frame.

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
