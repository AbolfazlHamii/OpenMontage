---
name: blender-3d-city-shot
description: Build cinematic 3D shots for the zombie series in Blender 5.2 (EEVEE) from the downloaded free kits - city streets, wrecks, streetlights, helicopters and planes - with the painted 2D cast standing in them as lit cards with contact shadows, motivated light (lamp pools, light shafts in fog, searchlights), painterly Kuwahara finish and eased camera moves. Use for any 3D location shot, aerial, set piece or the series intro of The Milo Saga (episode 2 onwards).
---

# 3D city shots in Blender (The Milo Saga)

Reference implementation: `projects/milo-ep2-airlift/blender/look_avenue.py` (the 10 s look test: dusk avenue,
lamps waking in a wave, helicopter crossing, crane up from behind Milo). Copy its helpers for new shots.
Blender: `D:\software\New folder (2)\blender.exe` (5.2, EEVEE). Assets: `D:\assets\milo-saga\` (see
`free-asset-library`). Older 2.5D plate pipeline: `blender-cinematic-2d`.

## Building blocks (helpers in look_avenue.py)

- `load(path, size, axis)`: imports a glTF/GLB/FBX into its own collection (not in the scene), centres it on
  x/y, base on z=0, scales so its bbox along `axis` ("z", "x", "max") equals `size` metres; stores the scaled
  extent in `col["ext"]`.
- `instance(col, at, rot)`: a collection-instance empty. Use it for every repeated piece (street tiles,
  buildings, lamps): light on memory, fast to build.
- `card(png, height, at, facing, emit)`: a cut-out character standing on the ground, pivot at the feet,
  dithered alpha, slight emission (0.08-0.15) so it reads but still takes the scene light.
- `blob(at, r)`: a soft dark ellipse under the feet (contact shadow). Always add one under every card.
- Cut-outs from the v4 turnarounds: `blender/cutout.py <turn png> <column 0-3> <out>` (0 front, 1 three-
  quarter, 2 side, 3 back); it removes the grey background, the pockets between legs and the painted floor
  shadow. Animated characters come from After Effects as PNG sequences on transparency (same card, image
  sequence).

## World scale and layout

- Metres, Z up. Quaternius Downtown: `Street_4Lane` is 6 m long x 18 m wide (road along X), sidewalk tiles
  3 x 3 m at y = ±10.5, buildings ~21 / 15.5 / 13 m wide and 25-28 m tall; place them at
  y = ±(12.2 + depth/2), the south side rotated 180°.
- Characters: Milo 1.55 m, adults 1.7-1.8 m, Pip 1.2 m. Cars 4.4-6 m, bus 11 m, helicopter 13 m, lamp posts 7 m.
- Ruins (Majadroid FBX) as a far skyline, 55-95 m tall, beyond the end of the street.

## Light recipe that worked

- Sky: Poly Haven HDRI (`the_sky_is_on_fire` for dusk), strength 0.2-0.35, rotated so the bright part sits
  down the street. Sun: low, warm (1.0, 0.55, 0.3), energy ~3, from behind the subject for a rim.
- **Fog in a box, never in the world:** a cube over the set with a Principled Volume (density 0.004-0.008,
  cool grey-blue). A world volume swallows the sky in EEVEE (everything turned black).
- **Lamp lights below the lamp head** (0.8 m under it): a light placed inside the shade is shadowed by the
  shade and lights nothing. Spot 70°, energy 12-15 kW, warm (1.0, 0.62, 0.3); a small emissive sphere as the
  bulb. Animate energy for flicker or a "waking" wave.
- Searchlight: a narrow spot (9°, 60 kW) parented to the helicopter, aimed down and forward.
- Contrast comes from cool ambient + warm practicals; keep the street dark between pools.

## Vehicles and street furniture (owner feedback 2026-11-15)

- Check every model's forward axis before animating: the Poly Pizza helicopter `EQJ2MECUbx` has its nose on
  -Y, so flying along +Y needs `rot = pi`. A vehicle flying or driving backwards is the first thing viewers see.
- Rotors must turn: `load_helicopter()` in `look_avenue_v2.py` cuts the top 8% of the mesh off as the main
  rotor, puts its origin on the mast (the highest vertex cluster) and spins it with a driver (`frame * 0.85`).
- Streetlight `nFwrlcLvM5`: arm towards -Y, so kerb-side lamps on +Y use rot 0 and on -Y rot pi; the glowing
  lens is a flat disc at the centre of the "Light" material faces (no floating bulb spheres); the spot sits
  0.2 m under it.
- Cars: Kenney car-kit + Poly Pizza wrecks, run through `grime()` (darker, desaturated, rough); parked ones
  along the kerbs (|y| ~7.2, parallel), only a few crashed across the lanes; scatter car-kit debris
  (doors, bumpers, tyres), also grimed.
- Compositor Glare in 5.2 is configured through inputs (`glare.inputs["Type"].default_value = "Bloom"`),
  not node properties; the default "Streaks" draws star crosses on every lamp.

## Look finish

- Compositor: Kuwahara (anisotropic, size 5) on the render gives the painted look that matches the cast.
- AgX view transform, "Medium High Contrast". In ffmpeg: vignette + light moving grain.
- **No Freestyle on whole city scenes** (it needed 11 GB and crashed). Ink lines, if wanted, only on a few
  hero objects (Line Art modifier on one collection) or later in compositing.
- Strip vertex-colour nodes from imported Quaternius materials (their wear masks rendered as red patches).

## Camera language here

- Track-to an aim empty; key both camera and aim; lens 24-35 mm for places, 50-85 mm for faces.
- Signature move: crane up from behind Milo's hat to the wide street (look test).
- Depth of field focused on the character card (`dof.focus_object`), f/2.8 at ground level.
- Motivate every move (follow a run, reveal a threat, rise for scale); hold still for emotion.

## Workflow

1. `--preview --frames 1,mid,last` (half size, 8 samples, ~1 s/frame on the RTX 2050) -> contact sheet -> look.
2. Fix, repeat. Run `shot-qa-gates` before a full render.
3. Full render to PNG frames (`--out`), then ffmpeg to MP4. 1080p full quality: a few s/frame on the laptop;
   final episode renders go to the rented servers (one Blender per GPU).
4. Paths: always pass absolute `--out` (a relative path rendered to `C:\work`).
5. With Blender MCP connected (`blender` MCP server, add-on `blender_mcp`), build and inspect live in the UI,
   then save the shot as a script for batch rendering.
