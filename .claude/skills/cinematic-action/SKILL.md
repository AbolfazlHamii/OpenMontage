---
name: cinematic-action
description: Make action scenes and the overall look of the zombie series feel like a film - shot coverage for a set piece, screen direction, cutting on action, impact frames, speed ramps, whip pans, sound-led cuts, and the cinematic finish (aspect, grade, haze, grain, lens) - with the exact switches in our Blender shot renderer and ffmpeg edit. Use when planning or editing any action beat or chase, a crash, a jump, a reveal, or when a cut "looks like a slideshow" or "not cinematic".
---

# Cinematic action for The Milo Saga

General film grammar lives in `skills/creative/cinematic.md` and `skills/creative/camera-language.md`; how to
build the 3D sets in `blender-3d-city-shot`; sound in `survival-sound-design`; checks in `shot-qa-gates`.
This skill is the action layer on top: what to shoot, how to cut it, how to finish it.

## 1. Coverage for one set piece (plan it as 6-10 shots)

| Order | Shot | Job |
|---|---|---|
| 1 | Establishing wide (high or long lens) | Geography: hero, threat, goal, the way between |
| 2 | Hero medium, moving | Who we follow, which way they go |
| 3 | Threat reveal (low angle, or through something) | How dangerous, how close |
| 4 | Insert: hands, feet, the object | The physical task (the ladder rung, the radio button) |
| 5 | Obstacle 1-2-3, each with a new angle | Escalation; never the same framing twice in a row |
| 6 | The quiet beat: extreme close-up, sound drops | Breath before the release |
| 7 | Release / impact (fastest cuts, shake, flash) | The peak |
| 8 | Held wide after the peak (3-4 s) | Let the viewer see the result and breathe |
| 9 | Reaction close-up | What it cost |

## 2. Rules that keep action readable

- **Screen direction:** pick it per sequence (the helicopter flies left to right, the horde comes from the far
  end) and keep it. Crossing the line only on purpose, with a shot that shows the turn (180-degree rule).
- **Scale ladder:** cut wide -> medium -> close in steps of at least two sizes or a clear angle change, or the
  cut jumps.
- **Cut on action:** start the next shot in the middle of a movement (a kick, a turn, a fall), never on a still
  frame; the motion hides the cut.
- **Eye trace:** the next shot's point of interest sits where the eye already is (same third of the frame).
- **One idea per shot**, and the shot ends when the idea lands (0.8-2 s at a peak, 3-5 s for wides).
- **Motivated light:** every bright spot has a source in the world (lamp, fire, alarm, searchlight); action
  peaks get a light change (red alarm, a flare, a flash).

## 3. Editing techniques (how we do each one)

| Technique | Use for | How here |
|---|---|---|
| Impact frame | crash, hit, kick | 2-3 frames of white or black (`kind: "white"`/`"black"` in the timeline) + a boom on the cut |
| Camera shake | rotor wash, impact, panic | `cam.shake` 0.3 (wind) / 0.8 (danger) / 1.5 (crash) in the shot spec; never on calm wides |
| Roll / Dutch angle | loss of control, spinning | `cam.roll [a, b]`; upside-down shots roll 180 |
| Speed ramp | the jump, the reach for a hand | render at 24 fps, retime the clip (ffmpeg `setpts`) 1.0 -> 0.4 -> 1.0 around the peak |
| Whip pan | time or place jump in action | a 6-frame shot with a fast yaw (`cam.from`/`to` 90 degrees apart) + `Woosh` sound |
| Push-in | realisation, dread | slow dolly toward the face over the whole shot (`to` 10-15% closer) |
| Pull-back reveal | scale of the threat | start close on the hero, end wide on the horde |
| Match cut | time jumps, callbacks | same shape or position across two scenes (the hat on the bunk -> the hat on the asphalt) |
| J-cut / L-cut | dialogue and transitions | sound of the next shot starts 0.3-1 s early (J) or the line continues over the next picture (L) |
| Sound-first cut | scares | the growl starts on black or on the previous shot, the picture follows |
| Hard drop | turns ("You won't be.") | music and ambience cut to silence for 0.4-0.8 s on `[DROP]` |

## 4. The cinematic finish (every frame)

- **Aspect:** 16:9 delivery; for flashbacks or the intro sting only, 2.39:1 letterbox bars (do not letterbox
  the whole episode: phones lose picture).
- **Grade:** one look per location family: dusk = warm key, teal shadows; night street = sodium orange pools,
  blue fill; interiors = single warm source; alarms = red. Keep skin/cards neutral. Lift blacks slightly
  (no pure black except impact frames).
- **Atmosphere:** haze or fog in every exterior (depth reads in layers: dark foreground, mid lit, bright fogged
  background); light shafts from lamps and searchlights.
- **Lens:** wide (16-24 mm) for action and scale, long (50-85 mm) for faces and the horde stacking up;
  shallow depth of field only on close-ups.
- **Texture:** fine film grain over the whole edit (ffmpeg `noise=alls=6:allf=t`), soft vignette, bloom on
  practical lights (already in the Blender compositor).
- **Motion:** nothing is fully still: a slow push, drifting dust, flickering light, a breathing card.

## 5. Checklist before rendering a sequence

1. Geography shot first; screen direction marked on the shot list.
2. No two consecutive shots with the same size and angle.
3. Every peak has a quiet beat before it and a held wide after it.
4. Each impact has picture (flash/shake) and sound (boom/hit) on the same frame.
5. Light changes at the peak; every light has a visible source.
6. Contact sheet checked (`shot-qa-gates`): no empty frames, faces readable, nothing upside down by accident.
