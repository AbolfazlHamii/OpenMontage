---
name: veo-hard-shots
description: Plan and write prompt files for the few hardest action shots of the zombie series (helicopter crash, plane landing or take-off, explosions, huge crowds running) that the owner generates with Google Flow / Veo from our own rendered keyframes, so they match the painted cut-out style and cut cleanly with the Blender/After Effects shots. Use when a shot would cost days to animate, and when ingesting the owner's Flow clips back into the edit.
---

# Veo hard shots (owner's Google Flow)

Owner decision (2026-11-14): use Veo in Flow for the hardest scenes; free/included tools only. The owner
runs Flow (ZAPI FLOW for batches); we prepare keyframes and prompts and ingest the results.

## Which shots go to Veo

Only shots that are (a) spectacular, (b) short (4-8 s), (c) without a close character face, and (d) would
take days in Blender/AE. Typical: the helicopter spinning down into an avenue, a cargo plane landing over the
horde, the plane's ramp at take-off seen from far, a fence giving way under thousands of dead, an
explosion. Budget: 6-12 Veo shots per 20-min episode; everything else stays in our pipeline.

## Keep the style consistent

- **Always start from our own frame:** render the first frame (and if possible the last) of the shot in
  Blender with the exact set, light and camera; give it to Flow as the start (and end) frame. The model
  then keeps our city, colours and composition.
- Characters far or from behind only; never ask Veo for Milo's face (it drifts off-model).
- Same camera language as the episode: say the lens/move explicitly.
- Keep durations to the shot list; 8 s clips are trimmed in the edit.

## Prompt template (English, one line per shot in the prompt file)

```
<shot id> | start frame: <file> | end frame: <file or none> |
Hand-painted 2D animation style with soft painted shading and ink outlines, muted dusk palette, volumetric
fog, warm sodium streetlights. <ACTION in one sentence, physical and specific>. Camera: <lens, move,
speed>. Keep the buildings, colours and layout of the start frame. No text, no logos, no gore, no new
characters in the foreground. <duration> seconds.
```

Example: `E2-071 | start: e2_071_first.png | end: none | ... A military helicopter loses its tail rotor,
spins twice and drops behind the parked bus, a burst of sparks and dust rolls down the avenue towards the
camera. Camera: 35 mm, locked off, small shake on impact. ... 6 seconds.`

## Files

- Prompts: `projects/<episode>/veo/VEO_PROMPTS.txt` (one shot per line) + `veo/frames/` (start/end PNGs, 1920x1080).
- Owner's downloads -> `veo/in/` -> check each clip against its prompt (ZAPI FLOW can save a clip under the
  wrong row: compare first frame with our start frame, correlation > 0.9) -> `veo/clips/<shot id>.mp4`.
- Grade match: run the clip through the same LUT/vignette/grain as the Blender shots; conform to the
  episode's fps and 1920x1080; trim to the shot length.
- Sound: Veo audio is muted; sound comes from our mix (`survival-sound-design`).

## Review

Put every Veo clip through `shot-qa-gates` gate 2 (no text, no new faces, no gore, no style break). If a clip
breaks the style, re-prompt once; if it fails again, replace it with a simpler Blender shot.
