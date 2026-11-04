# Baseline — before the upgrade (phase 0)

Measured 2026-11-04 on the owner's laptop (Windows 11, branch `fa`, commit
`1ed7c43`). Every number names its source. Nothing was re-rendered or
re-generated to produce this file; the only commands run were `ffprobe`,
`ffmpeg -af ebur128` and one `pytest tests`.

Reference production: `projects/samsung-history-fa/` — a 15 s sample of
"کل تاریخ سامسونگ در ۹۰ ثانیه" (2 narration lines, 3 stills, HyperFrames
atelier render, 3 music variants). Project files are read-only for this work.

Times below are UTC. The laptop clock is UTC−8 (PST), so file mtimes read
8 h earlier than the event log.

## 1. Time per stage (Samsung sample)

Source: `events.jsonl` (tool start/finish), artifact mtimes, git commit times.

| Stage | Start → end (UTC) | Wall time | Notes |
|---|---|---|---|
| Project init | 14:16:41 | — | `project.json` `created_at` |
| Research + proposal artifacts | 14:16:41 → 14:20:10 | 3 m 29 s | `research_brief.json` mtime 14:19:39; both checkpoints 14:20:10. Research thinking before init is not logged. |
| Narration TTS (2 lines) | 14:20:32 → 14:22:52 | 2 m 20 s | s1: 9.4 s (gemini_tts 403 → avalai 4.8 s). s2: 130.3 s (avalai alone took 129 s). |
| (Gap: building the AvalAI image tool) | 14:22:52 → 15:46:57 | 84 m | Commit `565387b` at 15:42:49. One-off engineering, not production. |
| Stills, attempt 1 (3 images) | 15:46:57 → 15:54:41 | 7 m 44 s | All failed: Google 403, then AvalAI through the VPN proxy broke mid-response (282 s, 82 s, 82 s). |
| Stills, attempt 2 (3 images) | 15:56:20 → 15:57:14 | 54 s | All succeeded direct to AvalAI, 10–11.6 s per image, serial. |
| Pixabay music | 16:06:06 → 16:06:07 | 1 s | Failed (blocked). |
| Atelier authoring (HTML/GSAP workspace) | 16:06 → 16:21:42 | ~15 m | gsap.min.js 16:09, snapshot passes 16:16 and 16:20–16:21. Agent work, no tool events. |
| Render, attempt 1 | 16:21:42 → 16:22:07 | 25 s | Failed. |
| Render `sample_no_music.mp4` | 16:22:29 → 16:23:32 | 63.1 s (tool) / 38 s (HyperFrames render step) | Tool wall time from `events.jsonl`; `render_seconds: 38` from `renders/sample_review.json`. Difference = lint/check/snapshot steps. |
| Review frames | 16:23:58 → 16:24:00 | 2 s | `renders/review/*.png` |
| Music download (Mixkit) | 16:46:51 → 16:47:02 | 11 s | after owner asked for other sites |
| Render music variant A | 16:48:11 → 16:49:26 | 74.7 s | |
| Render music variant B | 16:49:26 → 16:50:31 | 65.2 s | |
| Decision log + review final | 16:53:45 | — | `decision_log.json`, `sample_review.json` mtime |

Total from init to last artifact: **2 h 37 m** wall for a 15 s sample, of which
~84 m was tool building and an unknown part was waiting for the owner.
Pure tool time (sum of top-level tool durations in `events.jsonl`,
successful + failed): 886 s ≈ 14.8 m. Failed or blocked calls (Google 403s,
proxy breaks, Pixabay, render attempt 1): ≈ 502 s ≈ 8.4 m (57%).

Asset generation is serial: the three stills ran one after another (no
`ThreadPoolExecutor`/`asyncio.gather` in `tools/` or `lib/`).

## 2. Cost by provider and stage

Source: `events.jsonl` `cost_usd`, `assets/sample/images.json`, `FA_STATUS.md`.

| Stage | Provider / model | Calls OK | Cost (USD) |
|---|---|---|---|
| Narration | AvalAI `gemini-3.8-flash-tts` (via `avalai_gemini_tts`) | 2 | 0.003263 (0.001499 + 0.001764) |
| Narration | Google `gemini_tts` | 0 (403) | 0 |
| Stills | AvalAI `gemini-3.1-flash-image` 1K (via `avalai_gemini_image`) | 3 | 0.2016 (3 × 0.0672) |
| Stills | Google `google_imagen` | 0 (403) | 0 |
| Tool test image (outside project) | AvalAI `gemini-3.1-flash-image` | 1 | 0.0672 (`fa_smoke/avalai_image_test.png`) |
| Possible charge on a broken call | AvalAI | ? | 0.0672 — **not confirmed** |
| Music | Mixkit (free licence) | 3 tracks | 0 |
| Render | HyperFrames, local | 3 | 0 |
| Text (research, script, prompts) | the agent itself (Claude Code session) | — | 0 API; subscription not metered here |

Totals: project **$0.2049**; with the tool test image **$0.2721** (≈ the
$0.27 in `FA_STATUS.md`); worst case with the unconfirmed charge $0.3393.
Media is 100% of the metered spend; images alone are 98.4% of the project spend.

No project-level cost ledger file exists: costs had to be summed from the
event log. `images.json` records no seed, so none of these images is cacheable
by `lib/asset_cache.py`.

## 3. Render settings and time

Source: `ffprobe` and the x264 SEI string inside
`renders/sample_no_music.mp4`; `renders/sample_review.json`;
`tools/video/hyperframes_compose.py` (`quality` default `standard`).

| Item | Value |
|---|---|
| Runtime | HyperFrames, atelier, `quality=standard` (tool default) |
| Video | H.264 High, libx264 core 165, 1920×1080, 30 fps, yuv420p, 8.44 Mb/s |
| Rate control | `crf=18.0` (from SEI) |
| Preset | not written in the SEI; options `ref=3 subme=7 me=hex rc_lookahead=40 trellis=1` match x264 `medium` (inferred), `bframes=0`, `keyint=250` |
| Audio | AAC LC 48 kHz stereo, 186 kb/s |
| File | 15.0 s, 16.19 MB |
| Render time | 38 s render step / 63.1 s tool wall → 2.5–4.2 s of wall per second of video |
| Music variants | 74.7 s and 65.2 s tool wall |

Extrapolated to the full 90 s at these settings: ~4–6 min per render
(linear estimate, not measured).

## 4. Loudness

Source: `ffmpeg -hide_banner -nostats -i <file> -vn -af ebur128=peak=true -f null -`
(ffmpeg 8.1). Target for YouTube on this channel: −14 LUFS, true peak ≤ −1 dBTP.

| File | Integrated | LRA | True peak |
|---|---|---|---|
| `renders/sample_no_music.mp4` | −11.5 LUFS | 1.2 LU | −2.9 dBFS |
| `renders/sample_music_a_fun_and_games.mp4` | −11.5 LUFS | 1.2 LU | −2.8 dBFS |
| `renders/sample_music_b_secret_garden.mp4` | −11.5 LUFS | 1.2 LU | −2.9 dBFS |
| `assets/sample/s1_narration.wav` | −14.1 LUFS | 0.9 LU | −0.9 dBFS |
| `assets/sample/s2_narration.wav` | −14.0 LUFS | 0.9 LU | −1.0 dBFS |

The raw TTS lands at −14 already; the HyperFrames mix adds ~2.5 LU, so the
renders end 2.5 LU louder than target. `audio_mixer` defaults to −16 LUFS
(podcast). Neither path targets −14 today.

## 5. Test suite

Source: one run of `pytest tests -q -p no:cacheprovider` on this laptop.

| Item | Value |
|---|---|
| Wall time | 418 s wall (pytest reports 414.7 s = 6 m 55 s) |
| Result | 2294 passed, 1 failed (known: `test_scene_analysis_cache_tracks_requested_minimum_length`), 12 skipped, 3 xfailed |
| `pytest-xdist` | not installed; serial run |

## 6. Owner's manual steps for one video

Source: `decision_log.json` (d1–d11), `FA_STATUS.md`.
Counted for the 15 s sample so far; the full video is not done yet.

Done by the owner (8):

1. Pick concept (d1).
2. Pick render runtime (d2, overrode the agent's pick).
3. Music plan: compare three sources (d3).
4. Approve sample budget ($0.50).
5. Image provider policy "both" after Google 403 (d6).
6. Approve the visual identity (d7).
7. Ask for other music sites after Pixabay was blocked (d10).
8. Pick music variant A by ear (d11).

Still open before a finished video (at least 5): approve the stills' look,
review the sample render, pick the pipeline (character-animation sample not
made yet), approve the full-production budget, pick the channel voice
(phase 1 audition). Plus the usual gated checkpoints (script, scene_plan,
assets) of `animated-explainer`.

Infrastructure chores the owner had to handle: VPN/proxy route for Google,
starting Studio FA / Backlot. Not counted above.

## Before → after (filled in by later phases)

| Metric | Before (this file) | After | Phase |
|---|---|---|---|
| Render loudness | −11.5 LUFS | | 1 |
| Preview render time (15 s) | 38 s / 63 s at 1080p CRF 18 | | 1 |
| 3 stills, wall time | 54 s serial | | 1 |
| Test suite wall time | 418 s (serial) | | 1 |
| Cost estimate error vs actual | no estimator | | 1 |
| Cost of the sample | $0.2721 | | 1–2 |
