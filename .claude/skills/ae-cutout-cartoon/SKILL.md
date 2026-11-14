---
name: ae-cutout-cartoon
description: Make a narrated 2D cut-out cartoon video (stick-figure survival style, like the English channel's furniture-store episode) in After Effects from AI-painted part sheets - cast, rigs with a foot-locked walk, sets, narration, shot plan, automatic AE build, sound and render. Use for any new episode of that channel or any AE character-animation video built by script.
---

# Cut-out cartoon video in After Effects

Reference project: `projects/en-furniture-30days/` (README lists every file). Shot grammar and look:
`projects/_reference/melvin-zombie-6days/SHOT_ANALYSIS.md`. Reuse the scripts there; copy the folder
layout for a new episode.

## Pipeline

1. **Cast.** `cast/make_v4.py` draws a turnaround (front, 3/4, side, back) per character; the hero's sheet
   is the style reference for everyone else (`REF` for variants such as a zombie version of a character).
   Look rules that made it "pretty": head ~1/5 of the height with soft painted shading, small face with
   eye highlights and no blush, real hair tufts, clothes with folds and seams, very thin long ink limbs,
   white mitten hands.
2. **Parts.** `cast/make_parts_v4.py` -> three sheets on #00FF00 (front heads 3x3, three-quarter heads 3x3,
   clothes in two rows). `cast/split_v4.py` keys by distance to pure green and cuts pieces row by row;
   `cast/clean_rims.py` peels the white sticker rims some sheets draw. Look at `check.png` and write the
   piece numbers into `CHARS` in `ae/rig_v4.jsx` (numbering differs per character).
   Then `cast/fit_v4.py`: measures where each head's neck stub enters its collar and where each arm
   leaves its sleeve (front automatic, side sleeve/neck columns read off a grid) -> `ae/fit_v4.jsx`, with
   `cast/fit_check.jpg` to look at. Head sheets sometimes draw a collar under the neck: cut it off (the
   image bottom must be the neck end). Despill green from part edges. Owner feedback that caused this:
   "heads not attached to the bodies".
   Placement: `edit/placement_check.py` draws every character box on its plate; feet must be on open
   floor (not on tables, counters, bunks or partition edges), crowd sizes must follow depth
   (`CROWD_FLOOR` in timeline.py).
3. **Rig** (`ae/rig_v4.jsx`, `buildRig(cfg)`): 1000x2400 comp, ground y=2300, `CTRL` sliders Travel,
   Stride, Lift, Expr, Talk, Look, ArmL/ArmR, Lean. Legs are two-bone IK to a planted foot and the gait
   phase comes from **distance travelled**, so a planted foot never slides when the scene layer moves by
   `Travel * scale` (`travelExpr`). Walk only in side view; heads are 9-frame precomps driven by Time Remap
   (expression, lip flap, blink). Views: front, side (faces right; flip the layer), back.
4. **Sets.** `sets/make_sets.py` (style reference = the first plate; empty of people; floor in the lower
   third; no text). Extra camera angles can be made by the owner with ZAPI FLOW / Nano Banana from
   one-line prompts (`edit/zapi_flow_prompts*.txt` + `edit/zapi_flow_files*.txt`), then
   `edit/ingest.py <download folder> <files list>` copies and 2x-upscales them into `sets/`.
5. **Narration.** `voice/make_voice.py --voice <name>`: one Gemini TTS call per section (voices drift
   between calls), PA lines in their own voice, 1.8 s gap before announcements for the chime, `[BEAT]` =
   0.6 s. Word times: AvalAI `whisper-1` with word timestamps (~$0.006/min); it writes numbers as digits
   and may drop a quiet line, so `edit/timeline.py` maps number words and falls back to the clip times in
   `voice/segments.json`.
6. **Shot plan.** `edit/shots.py`: every shot starts on a narration phrase (`at`, optional `delay`).
   Kinds: est, insert, stand, walk, crowd, close, card, pov, black. Aim for 3-3.5 s average, nothing
   over ~6 s, a new angle or plate every shot. `edit/timeline.py` -> `edit/timeline.json`.
7. **Build.** `ae/build_video.jsx` reads the timeline and makes one comp per shot (CAM null for push/pan/
   shake, WORLD null for tracking walks, plate blur/dim/night tint, cards with pop-in) and MAIN.
   Build a range first: set `FIRST_SHOT`/`LAST_SHOT` before `$.evalFile`.
8. **Sound.** `audio/make_sfx.py` (procedural, own work), music from Suno prompts (`audio/SUNO_PROMPTS.md`),
   `audio/mix.py` places cues on words, drops the music on `[DROP]` lines, ducks under speech and
   normalises to -14 LUFS / -1.5 dBTP.
9. **Render.** `aerender -project X.aep -comp MAIN -OMtemplate "Lossless" -output Y.avi`, then ffmpeg to
   H.264 and mux `audio/mix.wav`. Long renders: split frame ranges (`-s`/`-e`) over parallel aerender
   processes and concatenate.
10. **Thumbnail.** `ae/thumb.jsx` (hero big in front, the threat behind, a clock or object, 2-3 words).

## Running ExtendScript without the MCP bridge

With After Effects open: `AfterFX.com -r <wrapper.jsx>`. The wrapper `$.evalFile`s the real script inside
try/catch and writes `ok` or the error line to a log file; poll the log. `saveFrameToPng` is asynchronous:
wait until the PNGs exist and stop growing before reading them.

## ExtendScript gotchas (each one cost a debugging round)

- Chained ternaries group from the **left**: `a ? b : c ? d : e` is `(a ? b : c) ? d : e`. Always nest
  with parentheses.
- Adding a property to a shape group invalidates earlier references into it: fetch `Path` after adding
  the stroke (`layer.property("Contents").property(1).property("Contents").property(1).property("Path")`).
- New shape groups are added **below** existing ones: add the group that must draw on top first.
- `importFile` every time duplicates footage: cache imports (`IMPORTED` in rig_v4.jsx).
- Expressions that divide by a slider (Stride 0 in front view) return NaN and silently break the layer:
  guard with `Math.max(x, 1)`.
- Parented layers are positioned in the parent's space; nulls with anchor [0,0] at [0,0] keep comp
  coordinates.
- Globals set by one `AfterFX.com -r` wrapper survive into the next run in the same AE session: set
  every switch (`TIMELINE_FILE`, `FIRST_SHOT`...) explicitly in every wrapper.
- Escape `\1` in Python-written regex replacements carefully (heredocs turned them into control bytes);
  write such lines with `chr(92)` or the Edit tool.

## Retention rules used in the script

Hook in the first 3 s (you + number), the title's promise visible by ~20 s, something new every few
seconds, open loops listed with where each pays off, the title's payoff at 40-80%, a comment question
right after a payoff (not in the first 30 s), music drops on key lines, outro under 8 s with a Part 2 tease.
See `skills/creative/narration-craft.md`.
