# Editing Tricks

## When to Use

At `edit` and compose time, after the scene plan is fixed. Pick tricks
from the edit style card's `transitions`, `camera_moves`, `sfx_palette` and
`pattern_interrupt_seconds`; this file says how to build each one. Camera
moves on stills (Ken Burns, parallax, shake, rack focus, dolly-zoom) are in
`skills/creative/camera-language.md` Part B.
Placing SFX, ducking and beat-editing the music, word-timed RTL captions and
their QA checks (one command, `scripts/fa_edit_pass.py`): `skills/creative/editing-craft.md`.

Columns per trick: **what**, **when**, **retention effect**, **how**
(HF = HyperFrames/GSAP, RM = Remotion, FF = FFmpeg), **cost**. Every trick
here is local and free to render; "cost" is render time and authoring effort.
Paid generation only enters where noted.

## Rules that apply to all

- One idea per shot; the trick serves the sentence being said.
- Change something every 5–8 s (shot, framing, overlay, sound) — see
  pattern interrupt. The card's `pattern_interrupt_seconds` sets the range.
- Cut on the stressed word or on the beat, not mid-word: build cut times from
  word timestamps (transcriber) or silencedetect, as the Samsung sample did.
- Do not stack more than two tricks on one cut.
- Persian: text animates right→left; never split a Persian word across
  animated chunks (it breaks letter joining).

## Cuts

### 1. Match cut
- **What:** cut between two shots that share shape, motion or composition (a coin → the sun; a 1938 shop sign → the 2024 logo in the same position).
- **When:** time jumps, "then vs now", linking two eras.
- **Retention:** high — the eye is rewarded; feels authored.
- **How:** plan both stills with the shared element at the same frame point; HF: hard cut at the frame where `frame()` puts both at the same (tx, ty). FF: `concat` with no transition.
- **Cost:** low render; needs planning at scene_plan (prompts must place the element).

### 2. Smash cut
- **What:** abrupt cut from calm/quiet to loud/intense (or reverse).
- **When:** punchline, reversal ("…and then it all burned").
- **Retention:** very high; resets attention.
- **How:** cut on silence → hit SFX + full-volume next scene; HF: `tl.set` opacity swap; add `hit` SFX at the cut.
- **Cost:** low.

### 3. J-cut
- **What:** next scene's audio starts before its picture.
- **When:** pulling the viewer into the next era/topic; smooth narration chapters.
- **Retention:** medium-high; feels continuous.
- **How:** HF/RM: start the next `<audio>` (or SFX bed) 0.3–1 s before the visual cut. FF: `adelay` the next clip's audio earlier in `amix`.
- **Cost:** low.

### 4. L-cut
- **What:** current audio continues over the next picture.
- **When:** letting a quote or music phrase land over its consequence.
- **Retention:** medium; adds weight.
- **How:** extend the outgoing audio's `data-duration` past the visual cut.
- **Cost:** low.

### 5. Jump cut
- **What:** cut within the same framing, skipping time.
- **When:** compressing a process, talking heads, comic rhythm.
- **Retention:** high in shorts; tiring if constant.
- **How:** same still, two framings with ~8–15% scale difference, hard cut (HF `tl.set` to a new `frame()`).
- **Cost:** none.

### 6. Speed ramp
- **What:** motion speeds up then slows (or the reverse) within one shot.
- **When:** video clips into an impact; action beats.
- **Retention:** high; signals "this moment matters".
- **How:** FF: `setpts` with segments (`trim` + `setpts=0.5*PTS` + `concat`), audio `atempo`; RM: `<OffthreadVideo playbackRate>` split in two sequences. On stills, emulate with an ease like `expo.inOut` on the camera move.
- **Cost:** low; needs real footage for the true effect.

### 7. Cut on action
- **What:** cut in the middle of a movement to its continuation in the next shot.
- **When:** any sequence of shots of the same action.
- **Retention:** medium; invisible continuity.
- **How:** end shot A mid-move (e.g. hand reaching), shot B starts with the hand arriving.
- **Cost:** planning only.

## Transitions

### 8. Whip-pan transition
- **What:** fast blurred pan out of one scene into the next.
- **When:** topic or era change with energy.
- **Retention:** high; momentum.
- **How:** `whipPan()` (camera-language Part B) on the outgoing scene, mirror move on the incoming one; `whoosh` SFX centred on the cut.
- **Cost:** low; blur adds render time.

### 9. Mask reveal
- **What:** next scene revealed through a shape (circle, wipe, silhouette, text).
- **When:** "zoom into" a detail, brand/logo moments, chapter openers.
- **Retention:** high.
- **How:** HF: animate `clip-path: circle(0% at 50% 50%)` → `circle(150% …)` with GSAP; RM: `clipPath` style interpolated. RTL wipe goes right→left: `inset(0 0 0 100%)` → `inset(0)`.
- **Cost:** low.

### 10. Map zoom
- **What:** zoom from world/country map down to a city, with a route or pin.
- **When:** "where it happened" (Daegu, Gumi, Seoul).
- **Retention:** high; orientation + motion.
- **How:** a single map image (public-domain/OSM-derived, attributed) or SVG; `kenBurns()` from wide to the city with `expo.inOut`; pin pops with `back.out`; route via SVG `stroke-dashoffset`. Never let an image model draw maps with labels (wrong names, fake text).
- **Cost:** low; free maps need attribution.

### 11. Paper-cut / layered collage
- **What:** elements as cut paper with drop shadows and slight jitter.
- **When:** history, archives, handmade feel.
- **Retention:** medium-high; texture.
- **How:** cut-out PNGs with `filter: drop-shadow(0 6px 0 rgba(0,0,0,.25))`, stepped motion (`steps(6)` ease or 12 fps holds), `parallax()` for depth.
- **Cost:** medium authoring; images need clean alpha.

### 12. Split screen
- **What:** two or more images side by side.
- **When:** before/after, compare, "meanwhile".
- **Retention:** medium-high; invites comparison.
- **How:** HF/RM: two `.cam` boxes at 50% width, each with its own move; divider animates in. In RTL, "before" sits on the right.
- **Cost:** low.

### 13. Light leak
- **What:** warm translucent light flare passing over the frame.
- **When:** nostalgia, memory, soft transitions between eras.
- **Retention:** low-medium; mood.
- **How:** HF: radial-gradient div with `mix-blend-mode: screen`, animate x and opacity over 0.6–1 s. FF: `blend=all_mode=screen` with a leak clip.
- **Cost:** low.

### 14. Glitch
- **What:** RGB split, slice offsets, flicker for 3–8 frames.
- **When:** tech failures, scandals, "error", digital-era chapters.
- **Retention:** high in short bursts; annoying if long.
- **How:** HF: three stacked copies with `mix-blend-mode: screen` and red/green/blue filters, offset by a seeded random per frame for 0.2 s; RM: same with `interpolate`. FF: `rgbashift` + `noise`.
- **Cost:** low.

### 15. Flash frame / dip
- **What:** 2–4 frames of white (or black) between shots.
- **When:** camera-flash moments, time jumps, impacts.
- **Retention:** medium; punctuation.
- **How:** full-frame div opacity 0→0.85→0 over 0.08 s + 0.28 s (Samsung sample `#flash-time`).
- **Cost:** none.

## Text and graphics

### 16. Kinetic typography
- **What:** words animate in sync with narration (scale, slide, colour).
- **When:** key claims, numbers, quotes; text-led shorts.
- **Retention:** high; reading + listening.
- **How:** word timestamps → GSAP per word/chunk; for Persian animate whole words (never letters), `direction: rtl`, Vazirmatn 800–900. RM: `@remotion/captions` style per-word sequences.
- **Cost:** medium authoring; free render.

### 17. Freeze-frame with callout
- **What:** motion stops, frame desaturates a bit, an arrow/circle/label points at something.
- **When:** "notice this", introducing a person, explaining a detail.
- **Retention:** high; creates a pause the viewer needs.
- **How:** on stills: stop the camera move (`tl.set` hold), `filter: saturate(.6)`, SVG circle draw (`stroke-dashoffset`), label pops in with `back.out`. On video: FF `tpad=stop_mode=clone` or RM `<Freeze>`.
- **Cost:** low.

### 18. Number counter
- **What:** a number counts up to its value (۱۵۰٬۰۰۰).
- **When:** stats, scale, money.
- **Retention:** high; anticipation.
- **How:** GSAP tween on an object, `onUpdate` writes `toLocaleString('fa-IR')`; keep the last frame on the exact value (round). Eastern Arabic digits for Persian.
- **Cost:** none.

### 19. Word highlight in RTL subtitles
- **What:** the spoken word in the caption lights up (colour or pill) as it is said.
- **When:** shorts, fast narration, accessibility.
- **Retention:** high on mobile.
- **How:** captions as HTML spans per word, `dir="rtl"`, highlight class toggled at word start times (word timestamps from the transcriber, or proportional to letters when no timestamps). Keep 3–6 words per caption card. Do not burn word-level highlight with ASS for Persian unless checked on a frame: libass shaping across `{\c}` overrides can break joins.
- **Cost:** medium authoring.

### 20. Lower third / era stamp
- **What:** small label with place/date/name.
- **When:** every new location or era.
- **Retention:** medium; orientation.
- **How:** HTML pill, slide in from the right (RTL), out after 2–3 s (Samsung sample stamps).
- **Cost:** none.

### 21. Doodle / hand-drawn annotation
- **What:** arrows, underlines, circles drawn on top of the image.
- **When:** pointing, emphasis, humour.
- **Retention:** medium-high.
- **How:** SVG paths with `stroke-dasharray` animated; slight wobble via filter `turbulence` (static seed).
- **Cost:** low.

## Sound

### 22. SFX: whoosh, riser, hit
- **What:** short sound design under transitions and impacts.
- **When:** whoosh on whip-pans/slides; riser 1–2 s into a reveal; hit on smash cuts, punch-ins, numbers landing.
- **Retention:** high; sound sells motion more than pixels do.
- **How:** library SFX (CC0/royalty-free, licence noted) as `<audio>` clips at the cut time, −12 to −18 dB under narration peaks; ducking handled by mix levels. Never cover a stressed word with a hit. Missing sounds (a riser of exact length, a paper swish, a fire-crackle bed): `lib/sfx_synth.py` renders them procedurally — own work, no licence, same seed = same file; `render()` returns `peak_s`, the moment to put on the cut.
- **Cost:** free (library or `sfx_synth`); paid SFX generation only if neither fits.

### 23. Beat-sync cutting
- **What:** cuts and punch-ins on music beats.
- **When:** montages, intros, shorts.
- **Retention:** high; rhythm feels intentional.
- **How:** `beat_detect` (`operation: analyze`) gives BPM, beats and downbeats of the bed (local, free; on click tracks beats land within 11 ms). `snap` moves each cut to the nearest beat within the tolerance *and inside its speech pause* (`windows`), so speech still wins; `align` picks the music offset (`data-media-start`) that puts a downbeat on the punch line. Fast songs (≥ 150 BPM) may come back at half tempo; the beats are then every other real beat, still on the grid.
- **Cost:** none.

### 24. Silence drop
- **What:** music and ambience cut to silence for a beat before a key line.
- **When:** the most important sentence of the video.
- **Retention:** very high, once per video.
- **How:** volume tween to 0 over 0.1 s, 0.4–0.8 s of silence, line, music back.
- **Cost:** none.

### 25. Music energy curve
- **What:** music intensity follows the story (low in setup, peak at the turn, resolve at the end).
- **When:** every video with a bed.
- **Retention:** medium-high; emotional arc.
- **How:** choose sections of the track (or two tracks) and volume automation per the card's `music_energy_curve`.
- **Cost:** none.

## Structure

### 26. Pattern interrupt every 5–8 s
- **What:** a deliberate change: new shot, framing, graphic, SFX, colour shift, zoom.
- **When:** always, at the card's interval; tighter (3–5 s) in shorts.
- **Retention:** the main defence against drop-off.
- **How:** after the edit is laid out, scan the timeline for stretches longer than the max interval with nothing new; add a punch-in, callout or cutaway.
- **Cost:** none.

### 27. Loop hook
- **What:** the last line or frame flows into the first, so the video replays seamlessly.
- **When:** shorts and reels.
- **Retention:** very high on short-form (replays count).
- **How:** write the last sentence so it completes with the opening line; match the first and last frames (same still, same framing); no outro card.
- **Cost:** script planning only.

### 28. Open loop / curiosity gap
- **What:** pose a question early and answer it later ("why would a chairman burn his own phones? we'll get there").
- **When:** first 15 s, and before mid-video dips.
- **Retention:** high.
- **How:** script-level; mark the payoff scene in the scene plan; add a callback graphic when it pays off.
- **Cost:** none.

### 29. Cold open
- **What:** start in the middle of the most dramatic moment, then rewind.
- **When:** histories with one shocking event (1995 bonfire).
- **Retention:** high in the first 30 s.
- **How:** 3–6 s of the climax, "rewind" effect (fast reverse Ken Burns + tape SFX), then chronology.
- **Cost:** none.

### 30. Grain and texture
- **What:** film grain / paper texture over everything.
- **When:** to unify stills from different generations; archival feel.
- **Retention:** low directly; raises perceived quality.
- **How:** HF: full-frame noise PNG with `mix-blend-mode: overlay`, shifted by a seeded offset each frame (or a short looping grain video). FF: `noise=alls=12:allf=t`. Keep subtle (opacity 0.06–0.12) — grain inflates file size and bitrate.
- **Cost:** low; heavier encodes.

### 31. Colour shift per era
- **What:** palette/grade changes with the time period (sepia → muted → modern saturated).
- **When:** chronological histories.
- **Retention:** medium; orientation without text.
- **How:** CSS `filter: sepia() saturate() hue-rotate()` per scene, or a LUT in FF (`lut3d`). Pick values in the card's `color_type`.
- **Cost:** none.

### 32. Reaction cutaway
- **What:** a quick cut to a character's reaction (shock, laugh) after a fact.
- **When:** absurd or shocking facts (Coca-Cola reference: a reaction shot per gag).
- **Retention:** high; emotional cue for the viewer.
- **How:** reuse the protagonist's character sheet for consistent faces; 0.8–1.5 s close-up with a punch-in.
- **Cost:** one extra still per reaction (paid image; reuse where possible).

## Quick map from intent to trick

| Intent | Tricks |
|---|---|
| Start strong | 29 cold open, 28 open loop, 18 number counter, 2 smash cut |
| Change era/place | 1 match cut, 10 map zoom, 20 era stamp, 31 colour shift, 13 light leak |
| Emphasise a claim | 16 kinetic type, 17 freeze-frame callout, 24 silence drop, punch-in |
| Keep energy | 26 pattern interrupt, 23 beat-sync, 8 whip-pan, 22 SFX |
| Shorts | 19 word highlight, 27 loop hook, 5 jump cut, 14 glitch |
