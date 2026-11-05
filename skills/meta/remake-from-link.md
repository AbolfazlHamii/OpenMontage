# Remake From a Link — Persian version of a YouTube / Instagram / TikTok video

## When to Use

The owner pastes a link (YouTube long video or Shorts, Instagram reel, TikTok,
X…) or a video file and says, in effect, "make this in Persian". This is the
Persian channel's entry into `skills/meta/video-reference-analyst.md`: same
spirit (a version of our own, not a copy), with the fa tools wired in.

## Two modes — decide first

| Mode | What we keep | What we make | Rights |
|---|---|---|---|
| **transcreate** (default) | Topic, structure, pacing, hook *technique*, edit rhythm | New research with sources, our own Persian script, our own images/animation, our narrator | Any public video. Never reuse its footage, audio, images, music or wording. |
| **dub** | The source video itself | Persian voices on the original picture | Only `own`, `licensed` or `permission`. Ask the owner which; record it. |

If the owner says "dub" for someone else's video, explain the copyright
problem in one line and offer transcreate.

## Step 1 — build the kit (one command, cents)

```bash
python scripts/fa_remake.py "<link>" [--target 90] [--mode dub --rights own] [--cookies cookies.txt]
```

`reference_kit` writes `projects/_reference/<slug>/` (git-ignored):

- `source.mp4` (≤ 720p; the length is checked against the metadata, because
  downloads here can stop silently; one resume retry through the proxy),
- `transcript.json` — platform captions first (free); if none or YouTube
  answers 429, AvalAI whisper-1 (~$0.006 per minute),
- `style/` + a learned card in `styles/editing/learned/<slug>-learned.yaml`
  (shot lengths, cut rate, motion, frame labels),
- `gemini_analysis.json` — story beats, hook, visual style (long videos: the
  first 8 minutes),
- `outline.json` — the whole video in 90 s sections (bulk tier),
- `claims.json` — checkable claims to verify (bulk tier),
- `transcript_fa_draft.txt` — worker-tier translation, **raw material only**,
- `remake_brief.json` + `REMAKE_fa.md` — facts, recommendation, cost estimate.

Paid analysis is capped by `--budget` (default $0.10); skipped steps are
listed in the notes, and `cost.actual` in the brief has each step's real
charge. Measured 2026-11-05: a 39 s Short $0.014 (~4 min); the 11-minute
Coca-Cola video $0.081 with free captions (~10 min, Gemini $0.056 of it).
Without captions an 11-minute video plans ~$0.14, so Gemini is skipped
under the default; ask the owner, then `--budget 0.15`.

Shorts are detected from the URL (`/shorts/`) or from a vertical video under
3 minutes; the Persian version then defaults to 9:16 (`youtube_shorts`
profile, `fast-shorts` card unless the learned card fits better). Long videos
default to 16:9; there is no length limit below 3 hours.

### Instagram (and other logged-in sites)

Instagram does not serve reels without a logged-in session. Two ways:

1. The owner exports `cookies.txt` once from a browser where they are logged
   in (an extension such as "Get cookies.txt LOCALLY"), saves it **outside
   the repo**, and sets `OPENMONTAGE_COOKIES_FILE=<path>` in `.env` (or
   passes `--cookies`). Never read the browser's cookie store yourself, and
   never commit or print the file.
2. The owner downloads the reel and gives the file path.

## Step 2 — present concepts (premium: you)

Read `REMAKE_fa.md`, `outline.json`, `gemini_analysis.json` and the learned
card. Present **2–3 Persian concepts** in Persian, each with: the angle (why a
Persian viewer cares), the hook (same technique, our own facts), length and
format, pipeline and runtime (present both runtimes), the edit style card, and
the cost estimate from the brief. Recommend one. Do not paste the source's
lines; the translation draft is only for your understanding.

Wait for the owner's pick, voice and budget (the budget gate is in the brief's
estimate; anything over $0.50 per call needs approval).

## Step 3 — run the normal pipeline with the kit

Create the project (Studio FA wizard, or `init_project`), copy the kit's facts
into `artifacts/brief.json` (`reference_material`: the kit path), then:

1. research **with sources** (the source video is not a source of facts) →
   `scripts/fa_editorial.py claims` → verify every claim;
2. hook lab (`scripts/fa_editorial.py hooks`) → owner picks;
3. script in colloquial Persian → `scripts/fa_script_lint.py --target <s> --voice narrator`;
4. `fa_estimate` → owner approves the budget;
5. TTS → stills through `fa_image` (draft, then final for approved looks) →
   compose with the chosen edit card (`camera-language.md`, `editing-tricks.md`);
6. `loudness_normalize` → `scripts/fa_render_qa.py` → owner review;
7. compare the render with the learned card:
   `edit_style_extractor` `operation: compare`.

Dub mode instead: `python scripts/fa_dub.py prepare --project projects/<id> --source <kit>/source.mp4 --rights <own|licensed|permission>`
and follow `scripts/fa_dub.py` stage by stage.

## Errors you will meet

| Error | Meaning | Do |
|---|---|---|
| `HTTP Error 429` on captions | YouTube rate-limits subtitle downloads | nothing — the kit falls back to speech-to-text |
| `Instagram sent an empty media response` | no logged-in session | cookies or a file (above) |
| `truncated download` | the network cut the file | the kit already retried once; try again later or download manually |
| step `skipped, estimate … would pass the budget` | paid step over `--budget` | rerun with a higher `--budget` after the owner agrees |
| `ReadTimeout` / `SSLError` on `api.avalai.ir` | the VPN proxy stalled; the kit already sends AvalAI direct and retries speech-to-text once | rerun later |
