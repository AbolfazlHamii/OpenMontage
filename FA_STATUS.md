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
| RTL subtitles | `tools/subtitle/subtitle_gen.py`, `tools/video/video_compose.py` | RLM per line + ASS `Encoding=-1`; `SUBTITLE_FONTS_DIR` / `fonts_dir` for per-user fonts on Windows |
| Control panel | `studio_fa/`, `studio-fa.bat` | `python -m studio_fa` → http://127.0.0.1:4760/ |
| Smoke test | `scripts/fa_smoke_test.py` | `subtitles` (free) and `tts` (paid, < $0.01) |
| Gateway check | `scripts/check_gateway.py` | OpenAI-compatible gateways |
| Tests | `tests/tools/test_persian_localization.py`, `test_avalai_gemini_tts.py`, `test_subtitle_fonts_dir.py`, `test_studio_fa.py` | all mocked |

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
  (9.2 s, $0.0014), subtitle frame with Vazirmatn in correct RTL order.

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

Blocked: Google API (images, Lyria) returns 403 from the owner's current
network (IP 83.122.107.129) and from the local proxy exit 45.65.112.227.
It worked earlier from 205.252.135.82 (owner's VPN). Owner decision ("both"):
build an AvalAI image tool that is always available, and prefer Google when
the VPN makes it reachable.

Sample script:
1. «احتمالاً گوشیِ توی دستت سامسونگه… ولی می‌دونستی این شرکت با فروش ماهی خشک شروع شد؟»
2. «سال هزار و نهصد و نود و پنج، رئیس سامسونگ صد و پنجاه هزار تا گوشیِ خراب رو جلوی کارگرهاش آتیش زد!»
   (captions use digits: ۱۹۹۵، ۱۵۰ هزار)

Reference analysis: `projects/_reference/ceozoned-coca-cola/` (`REFERENCE_NOTES.md`).

## Next steps

1. New tool `tools/graphics/avalai_gemini_image.py` (BaseTool, capability
   image_generation): AvalAI native `POST https://api.avalai.ir/v1beta/models/{model}:generateContent`
   with Bearer `AVALAI_API_KEY`, models `gemini-3.1-flash-image` (Nano Banana 2,
   ~$0.067/img) and `gemini-3-pro-image`; reference images as `inlineData`;
   `responseModalities: ["IMAGE"]`; mocked tests. Route: Google first, AvalAI
   when Google fails (same idea as the TTS fall-through). AvalAI has no Lyria.
2. `tts_selector`: shorten HTML error pages in `fallback_from` (Google's 403
   page is dumped in full).
3. Sample images (3 stills: hook phone, 1938 Daegu dried-fish shop, 1995
   Gumi bonfire; no text in images), Pixabay track, then HyperFrames
   composition with Vazirmatn RTL captions; character-animation sample.
4. Present samples + actual cost; then script stage for the full 90 s.
5. Phase 1 voice audition before the final narration.
