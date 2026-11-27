---
name: blender-cinematic-2d
description: Turn flat painted background plates into cinematic 2.5D shots with Blender (EEVEE) - depth-projected plate with real parallax, eased camera moves (push, truck, crane, orbit, shake), volumetric haze with light shafts from the painted lamps, floating dust, depth of field, grain and vignette - rendered from the command line to 1920x1080 30 fps MP4. Use for establishing and insert shots of the cut-out cartoon channel (with ae-cutout-cartoon), or any time a still painting should feel like a camera is moving through it.
---

# Cinematic 2.5D shots from painted plates (Blender)

Reference implementation: `projects/en-furniture-30days/blender/` (video 1). Its `README.md` holds the
live status (done / in progress / planned) and who owns which folders: read it before continuing work there.
Copy that folder into a new episode and edit the two JSON files; the scripts are generic.

Blender 5.2 lives at `D:\software\New folder (2)\blender.exe` (override with env `BLENDER`).
System Python is `py` (has numpy and Pillow); ffmpeg is on PATH. No downloads, no API cost.

## Files

| File | Role |
|---|---|
| `depthlib.py` | Depth models (numpy only): `tunnel`, `ground`, `flat`, `map` + rectangular `cards` |
| `scene2d5.py` | Blender script: builds the scene from one cfg JSON and renders PNG frames |
| `run_shots.py` | Driver: merges `plates.json` + `shots_*.json`, reads clip lengths from `edit/timeline*.json`, runs Blender, encodes MP4, writes `out/shots.json` |
| `plates.json` | Per plate: depth model, lamps, haze, dust, dof |
| `shots_video1.json` | Per shot index: plate and camera move (shot keys override plate keys) |
| `work/` | cfg, Blender log and temporary frames per shot (git-ignored) |

## How it works

1. A projection camera sits at the origin looking along +Y (lens 30 mm, 36 mm sensor). Every cell
   of a 480x270 grid over the plate (+12% margin, painting mirrored into the margin) becomes a vertex
   pushed along its camera ray to the depth from `depthlib`. From the origin the mesh is the painting,
   pixel for pixel (emission shader, Standard view transform); a moving camera sees real parallax.
2. Depth is hand-modelled, not estimated: most plates are one-point perspective, so
   - `tunnel` (aisles, racks, stairwells, rooms): `Z = near / max(|x-vx|/bx, |y-vy|/by)`, clamped
     at `far` (the back wall). Give the vanishing point `vp` and the half box `box`.
   - `ground` (exteriors, aerials, high angles): `Z = near*(1-yh)/(y-yh)` below the horizon `yh`
     (negative when it lies above the frame), `far` above it.
   - `cards` override a rectangle: `z` a number, `[z_left, z_right]` for a receding facade,
     `"ground"` (depth of the rect's bottom edge), `mode` set / near / mul, soft `feather`.
   - `map`: a grayscale PNG (white = near) if a real depth map exists. A depth-estimation model
     would give one, but it is a download: ask the owner first with name, source and size.
   Check with `py blender/run_shots.py --depth` -> `work/depth_check.jpg` (plate with green lamp
   markers beside the inverse depth; white = near).
3. Haze: a box volume (Principled Volume, drifting noise density). `density` is per `near` metres
   (0.05-0.07 interiors, 0.035 night exterior, 0.02 day aerial); color defaults from the plate.
   World color = plate mean, so the fog takes the scene's tint.
4. Lamps: `{"at": [x, y]}` on each painted fixture -> a spot pointing down (cone in the fog = light
   shaft) or `"kind": "point"` (glow). Color is sampled from the painting; `power`, `cone`, `flicker`
   (sparks, fire), `dir` (aim a spot along a vector, e.g. skylight shafts). Lights only touch the
   volume; the painting is never relit. Exterior point lights need low power (0.1).
5. Dust: ~250 tiny additive specks 0.8-9 m from the camera drifting with a slight wobble; the near
   ones become bokeh through DOF. `count: 0` turns it off (aerials).
6. Camera (`move`): distances are in units of the plate's `near` depth (where stretching shows first).
   - `push` amount 0.15-0.5 for tunnels (in units of near), or `zoom` for rooms, ground plates and
     inserts: how much the aim point grows on screen (1.12-1.15 push, 1.06-1.08 slow push; d = R(1-1/zoom)).
     `extra: [dx, dy, dz]` adds drift/rise
   - `truck` amount 0.25-0.4 (negative = right to left), keeps the `aim` point steady
   - `crane` amount > 0 = down, tracks `aim`
   - `orbit` amount in degrees (10-15) around `aim` (good for aerials)
   - `pan`/`tilt`/`roll`/`crop` as `[start, end]` lerps; `shake` (deg, high frequency) with
     `shake_decay`; `breath` (default 0.12 deg handheld drift); `ease` linear (default; a clip cut
     short still moves from its first frame) / inout / out.
   - DOF: `dof.fstop` (2.8 default, 4 for exteriors, 0 = off), focus on `aim`.
7. ffmpeg adds vignette and moving grain (`GRADE` in run_shots.py), x264 crf 16, no audio.

## Shots with characters: atmosphere plates

Characters stay in After Effects. `run_shots.py --passes` renders, per character shot, the painting from a
static projection camera with haze, lamp cones, flicker and dust (dust kept behind the characters), no DOF,
no grade, at the size AE shows the plate (each painting's own aspect; close shots, fit 2, render only the
centre 1/fit) -> `out/plates/plate_<i>.mp4` + `plates.json`. AE imports it instead of the plate PNG and divides
the plate scale by `crop`; its camera move, characters and grade stay, so feet stay planted and one clip
serves every language cut. Code for the AE side: the project's `blender/README.md`.

## Grade match with the AE cut

Clips that are spliced over the AE render must carry the AE MAIN grade. `match_grade.py <AE render>`
(or `part.mp4@first_shot_index`) pairs the first frame of still-start shots with the plain plate and writes a
per-channel LUT `ae_grade.cube` (error 15 -> 1.5 of 255 on video 1). `run_shots.py` keeps an ungraded master
`out/raw/shot_<i>.mp4` and grades it (LUT + vignette + grain) into `out/shot_<i>.mp4`; `--regrade` redoes the
grade after a new LUT without rendering.

## Running

```
py blender/run_shots.py --depth                       # check depth models first (seconds)
py blender/run_shots.py --stills --preview --only 11  # 3 frames per shot -> work/stills.jpg
py blender/run_shots.py --only 11,28                  # final clips -> out/shot_<i>.mp4
```
Long batches: run them detached (PowerShell `Start-Process` on Git's `bash.exe` with a queue script, see the
project README), not as a background Bash task of a Claude session: those die with the session. `--missing`
skips finished clips, so a stopped queue just starts again.

One shot by hand: `blender -b --factory-startup -P blender/scene2d5.py -- --cfg work/shot_11/cfg.json --out frames [--preview] [--frames 0,40,80] [--blend scene.blend]`
(`--blend` saves the built scene to open in the Blender UI).

Clip length = max(dur in `edit/timeline.json`, dur in `edit/timeline_fa.json`) + 0.5 s, so one clip
serves both language cuts; the editor lays it at each cut's shot start and trims the tail.

Speed (RTX 2050 laptop, 8 TAA samples, volume tile 16): ~0.4 s per 1080p frame with the GPU to itself
(a 7 s clip in ~80 s; all 12 video-1 clips, 1784 frames, in ~12 min), ~1.5-2 s while After Effects
renders on the same GPU. Volume tile 8 is 2.5x slower and looks the same. Preview mode is
half size with 4 samples (~0.5 s/frame).

## Picking shots and limits

- Best gains: one-point interiors (aisles, racks, stairwells), exteriors with a ground plane,
  aerials (orbit). Shots without characters are simplest. Skip text cards and close inserts that
  are flat by nature.
- The mesh is continuous, so there are no holes but depth jumps (card edges) stretch: keep moves
  moderate, put cards where the painting has a real silhouette and feather them.
- A truck/orbit reveals the margin; the margin mirrors the painting, but keep truck <= 0.25 near with
  `crop` 1.1, orbit <= 5 degrees with `crop` 1.12. Pushes are the safest move (no edge reveal).
- The tunnel's max() makes a crease along the box diagonals: straight lines crossing it bend on a
  push. For tall racks/side walls use a corridor (`box: [0.5, 6]`): two flat walls, no crease.
- A lamp over a far region lands far away and becomes a long grey bar: give it `"z"` (metres).
- Haze across a big depth jump (card in front of a far sky) draws a hard fog edge: lower `far`.
- Card edges must sit exactly on a painted silhouette (feather 0.008-0.02); a card cutting through an
  object bends it. Always look at 3 stills per shot before the full render.
- The 4 GB GPU runs one EEVEE render at a time; a second one (or heavy AE GPU work) can crash with
  "out of memory".
- Characters: cfg `sprites` puts a PNG or a PNG sequence with alpha (e.g. a walk rendered in After
  Effects on transparency) on a camera-facing plane standing on the floor:
  `{"image": "abs/path/f_0001.png", "sequence": 120, "at": [x, y_feet], "height": 0.35, "anchor": 1}`
  (height = fraction of frame height; depth from the plate's depth model at the feet, or `"z"`).
  Building a rig from `cast/v4/parts/` inside Blender (head on collar, thin ink limbs) is not done
  yet; render the character in AE and bring it in as a sequence.
