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

Reference: CEOzoned, "The ENTIRE History of Coca-Cola in 11 Minutes"
(https://www.youtube.com/watch?v=_OuJBX6Q4Cc, 323K views).
Analysis files: `projects/_reference/ceozoned-coca-cola/` (git-ignored):
`video_analysis_brief.json` (first 180 s: 48 scenes), `transcript_full_brief.json`
(full transcript, 1720 words), `keyframes/`, `contact_sheet.jpg`, `REFERENCE_NOTES.md`.

What the reference does: 45 of 48 shots are still cartoon images with camera
moves (3 motion clips), ~3.75 s per shot, 16 cuts/min, ~157 wpm narration.
Hook = huge present-day number → paradox origin → "This is the entire
history of X". Recurring round-headed characters, warm sepia palette.

Next step: the owner picks a concept, pipeline sample and runtime (see the
proposal in the hub file / conversation). Nothing has been generated yet;
spend so far on this production: $0.

## Next steps

1. Owner approves a concept → `init_project`, open Backlot, run
   `animated-explainer` stage by stage (read each director skill first).
2. 10 s samples: `animated-explainer` (Nano Banana stills + camera moves) vs
   `character-animation`, owner picks.
3. Phase 1 voice audition before the final narration.
