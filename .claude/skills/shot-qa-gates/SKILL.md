---
name: shot-qa-gates
description: Automatic and visual quality checks before every full render of an animated episode - floating or detached heads, necks behind collars, feet off the ground, cards clipping into geometry, characters facing the wrong way, black/empty/flat frames, repeated pictures, stale render parts, audio/picture length mismatch. Use before rendering any After Effects or Blender shot or episode of the zombie series, and when joining render parts.
---

# Shot QA gates

Video 1 shipped with heads behind collars, floating heads, a repeated plate 15 times and once a stale render
part. Every check below exists because of one of those. A shot is not rendered at full quality until it
passes gates 1 and 2; an episode is not joined until it passes gate 3.

## Gate 1: character (per character x view x pose, once per rig change)

Render each pose/view of the character alone on transparency (AE comp or the cut-out PNG) and check:
- **One body:** the alpha must be one connected shape (ignore specks < 0.2% of the area). Two big shapes =
  floating head or detached limb. Implement with a flood fill over alpha > 128 (no scipy needed; see
  `blender/cutout.py` for the pattern).
- **Neck joins collar:** in the head-collar band (from `cast/fit_v4.py` NECKLINE), every row has opaque pixels
  across the neck; no transparent gap row.
- **Head size:** head height / body height within the character's range (Milo ~1/5); a zombie at 1/3 is a bug.
- **Feet on the ground line:** lowest opaque row = the rig's ground y (±2 px).
- Output: `qa/char_<name>.jpg` contact sheet with a red box on any failure.

## Gate 2: shot (every shot, 3 preview frames: first, middle, last)

- **Contact sheet** of all shots (3 frames each, shot index and kind under each) -> look at it, every time.
- **Feet on ground (Blender):** ray-cast down from each card's feet; |gap| < 2 cm, and not standing on a car,
  table or kerb edge unless intended.
- **No clipping:** card plane bounding box does not intersect scene meshes (except the ground).
- **Vehicles:** every moving vehicle's nose points along its path (owner caught a helicopter flying
  tail-first in the look test, 2026-11-15); rotors and wheels turn; parked cars sit on the road, not on
  the sidewalk, parallel to the kerb unless crashed. Check with a 3-frame strip of the vehicle, not a still.
- **Facing:** a walking/running card faces its direction of travel; in dialogue, the two characters face
  each other (180° rule kept between consecutive shots).
- **In frame:** every listed character's bbox is inside the 5% safe area unless the shot says "exit".
- **Not empty / black / flat:** mean luminance > 0.04 and std > 0.02 on every preview frame (only `black`
  shots may fail).
- **No repeats:** 64x36 grey thumbnails; correlation > 0.95 with any shot in the previous 60 s = repeat ->
  change angle or plate (neighbouring legit edits of one scene can score 0.93-0.99: check by eye).
- **Scale sanity:** characters at similar depth have similar heights (±10%).
- Output: `qa/shots.json` (pass/fail per check per shot) and `qa/shots.jpg`; fix every fail, re-run.

## Gate 3: render and join

- Every part's output is newer than its source (.aep/.blend/cfg) and has the expected frame count
  (`ffprobe -count_frames`); a part that failed mid-way (e.g. "connection forcibly closed") is re-rendered,
  never joined stale.
- Black-frame scan of the joined video (`ffmpeg blackdetect`) only where the timeline has black shots.
- Audio length = picture length (±1 frame); loudness -14 LUFS, true peak ≤ -1.5 dBTP.
- Spot-check 10 random frames at full resolution.

## Reporting

Show the owner the contact sheet and the count of fixed issues, never only "all good". If a check was not
run, say so.
