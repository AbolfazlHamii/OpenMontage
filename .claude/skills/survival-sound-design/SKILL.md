---
name: survival-sound-design
description: Sound design and mix for the zombie series using the local Sonniss GDC 2026 library and procedural fill-ins - indexing and finding sounds, layering (ambience bed, foley, hard effects, creature voices, stingers), placing cues on narration words and picture, silence and music drops, and the loudness targets. Use when building the sound for any episode, intro or Short of The Milo Saga, and when deciding what still needs Freesound or a procedural sound.
---

# Survival sound design

Video 1's effects were all made by code and sounded thin. From episode 2 the bed of the mix is real
recordings: Sonniss GDC 2026 (`D:\assets\milo-saga\dl\sonniss-gdc2026`, 5 zips, ~350 WAV, royalty-free, no
credit, never for AI training). Music: the owner's Suno/Lyria tracks. Narration: Gemini TTS (own Google key
via the proxy).

## Library and index

1. Unzip once to `D:\assets\milo-saga\x\sonniss-gdc2026\` (not into the project).
2. Build `sfx_index.csv` (path, file name, vendor, duration, channels, peak, loudness) with ffprobe/ffmpeg
   `ebur128`. File names carry the category code (UCS style: `CREAHmn_`, `AMBPubl_`, `FIREBurn_`,
   `WINDDsgn_`, `AEROJet_`, `COMStatic_`, `EXPLDsgn_`, `GLASMvmt_`, `METLFric_`, `VOXMale_`): search by code
   and words.
3. Useful in the 2026 bundle: undead and creature vocal sets (Epic Stock Media Humanoid Creatures Vol 4,
   werewolf/orc growls), horror scare kit, crowds walla and public spaces, city rain and storms, extreme
   winds, fire crackle loops, train/car pass-bys, airplane interior, jet blast, radio static loops, emergency
   broadcast voice, alarms, explosions, glass, metal drags, locks and mechanisms, whooshes and impacts.
4. Missing so far (fill with Freesound CC0 if the owner makes a free key, or procedural): helicopter rotor
   loop, cargo plane flyover/landing, turboprop, chain-link fence rattle, police siren. Procedural code from
   video 1: `projects/en-furniture-30days/audio/make_sfx.py`.

## Layers (every scene)

| Layer | Level (relative to narration peak) | Notes |
|---|---|---|
| Narration | 0 dB reference | always intelligible; duck everything else under it |
| Ambience bed | -24 to -30 dB | one per location (wind + distant city, interior room tone, fire); change it on every location cut |
| Foley | -18 to -22 dB | footsteps on the right surface, cloth, breath, hands on metal; sells the cut-out characters as physical |
| Hard effects | -10 to -16 dB | impacts, crashes, rotor, engines; pan with the picture |
| Creature voices | -14 to -20 dB | growls layered and pitch-varied (never the same growl twice in a minute) |
| Stingers / whooshes | -12 dB | on cuts into danger, title cards, reveals |
| Music | -20 dB under speech, up to -8 dB in action without speech | the owner's tracks; drop to silence on `[DROP]` lines |

## Rules that make it cinematic

- **Silence is a sound.** 0.5-1.5 s of near-silence before a scare or after a death line; cut the music on
  `[DROP]`.
- **Sound before picture** (J-cut): the rotor or the growl starts 0.5-1 s before we cut to it.
- **Perspective:** far = quieter, duller (low-pass), more reverb; near = full and dry. Rotor and plane noise
  rise and fall with distance and pan left-right with the movement.
- **The rule of the episode is audible:** in episode 2 the planes are the loudest sound in the world; every
  landing is a mix event (low rumble rising, the dead's footsteps turning).
- **Variety:** no single sample more than twice per minute; vary pitch ±2 semitones and volume ±3 dB.
- **Emotion beats:** strip to one sound (breath, the toy radio crackle) under the line.

## Placement

- Cues sit on narration word times (`edit/timeline.json` word anchors) and on shot starts; keep a cue list
  per episode (`audio/cues.json`: time, file, gain, pan, fade).
- Build the mix with ffmpeg or the existing `audio/mix.py` pattern from video 1 (ducking under speech,
  `[DROP]` handling).

## Targets

-14 LUFS integrated, true peak ≤ -1.5 dBTP, dialogue never masked; check with `ffmpeg -af ebur128`. Listen
once on phone speakers and once on headphones before delivery.
