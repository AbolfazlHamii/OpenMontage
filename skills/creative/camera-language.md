# Camera Language

## When to Use

At `scene_plan` (choosing `shot_language` per scene) and at `edit` /
compose time (moving a "camera" over still images). Part A is for prompts to
AI image/video models; Part B is for virtual camera work on stills in
HyperFrames (GSAP) or Remotion. Pair with an edit style card
(`styles/editing/*.yaml`, `camera_moves`) for how often each move appears.

`scene_plan.shot_language` fields: `shot_size`, `camera_angle`, `lens`,
`lens_mm`, `camera_movement`, `depth_of_field`, `lighting_key`,
`color_temperature`. `lib/shot_prompt_builder.py` turns them into prompt text.

## Shot size

| Size (`shot_size`) | Shows | Emotional effect / use |
|---|---|---|
| `extreme_wide`, `establishing` | Place, scale | Orientation, isolation, epic scale; open a new era/location |
| `wide` | Whole subject + setting | Context, geography of an action |
| `medium_wide` | Subject knees-up with surroundings | Action with context; group scenes |
| `medium` | Waist-up | Neutral narration, explanation |
| `medium_close` | Chest-up | Engagement; dialogue |
| `close_up` | Face / object | Emotion, importance; reaction beats |
| `extreme_close_up`, `insert` | Detail (eye, button, date on a document) | Tension, proof, "look at this" |
| `over_shoulder` | Subject seen past another | Relationship, confrontation |

Rule of thumb for explainers on stills: wide to establish each era, then
medium/close for the claim, insert for the proof.

## Angle (`camera_angle`)

| Angle | Effect |
|---|---|
| `eye_level` | Neutral, honest, "one of us" |
| `low` | Power, dominance, heroism (founders, giant products) |
| `high` | Vulnerability, smallness, being judged |
| `dutch` | Unease, crisis, something wrong (scandals, failures) |
| `birds_eye` | God's view, pattern, scale of crowds/factories |
| `worms_eye` | Monumentality, awe, threat towering above |
| `top_down` | Flat-lay; desks, maps, documents; diagrammatic clarity |
| `pov` | Immersion: "you are holding this phone" |
| `over_the_shoulder` | Sharing a character's view; confrontation |

## Movement (`camera_movement`)

| Move | Effect |
|---|---|
| `static` | Calm, observational; lets text and narration lead |
| `pan_left/right` | Reveal, follow along a timeline (in RTL, prefer right→left reveals for "forward in time") |
| `tilt_up/down` | Reveal height (up = aspiration), descent (down = fall) |
| `dolly_in` / `zoom_in` | Growing importance, intimacy, tension |
| `dolly_out` / `zoom_out` | Revelation of context, loneliness, ending |
| `tracking_*` | Momentum, journeys |
| `crane_up/down` | Scale, transitions between levels of a story |
| `handheld` | Urgency, documentary truth, chaos |
| `steadicam` | Smooth immersion |
| `whip_pan` | Energy; transition between ideas |
| `orbital` | Hero reveal of a product/object |
| `rack_focus` | Shift of attention between two subjects/ideas |

## Lens and depth of field (`lens`, `lens_mm`, `depth_of_field`)

| Lens | Effect |
|---|---|
| `ultra_wide` / 14–24 mm | Exaggerated space, dynamism, distortion near edges |
| `wide` / 24–35 mm | Environmental storytelling |
| `normal` / 50 mm | Natural, honest |
| `telephoto` / 85–200 mm | Compression, isolation, voyeuristic distance |
| `macro` | Texture and detail as spectacle |
| `fisheye` | Comic, surreal, skate/music energy |
| `anamorphic` | Cinematic, oval bokeh, horizontal flares |
| `tilt_shift` | Miniature world; factories and cities as toys |

Shallow DoF isolates and adds emotion; deep focus keeps everything legible
(diagrams, crowds, maps).

## Part A — prompting AI image/video models

Order inside a prompt (what `shot_prompt_builder` emits): lens → shot size,
angle, movement → subject and action → light and colour → style.

- Name one size, one angle and at most one movement per shot; stacking
  several moves makes video models jitter.
- Video models: describe the movement with speed and direction ("slow dolly
  in toward the founder's face, 4 seconds"), not just its name.
- Image models: movement words do nothing; use size, angle, lens and DoF.
- Keep the camera vocabulary consistent across a sequence (same lens family,
  same colour temperature per era) so stills cut together.
- Persian channel: never ask an image or video model for text (Persian or
  otherwise). Text goes in the composition layer.

Example (scene_plan → prompt):

```json
{"shot_size": "medium", "camera_angle": "low", "lens": "wide", "lens_mm": 35,
 "depth_of_field": "shallow", "lighting_key": "golden_hour"}
```

→ "wide-angle lens, 35mm lens, shallow depth of field with bokeh. medium shot
from waist up, low-angle shot looking up at the subject. <description>. warm
golden hour sunlight"

## Part B — virtual camera on stills (HyperFrames / Remotion)

All snippets below are GSAP for HyperFrames and were rendered in a test
workspace (`docs/fa/camera_snippets_test/`, 16 s, 8 scenes, `quality: draft`,
lint 0 errors) on 2026-11-04. They assume the usual workspace setup:

```js
const W = 1920, H = 1080;
const tl = gsap.timeline({ paused: true });
// ... snippets ... then: window.__timelines["<composition-id>"] = tl;
```

Elements are absolutely positioned `1920×1080` wrappers (`.cam` / `.layer`)
holding an `<img>` with `object-fit: cover`, `transform-origin: 50% 50%`.
Every animation goes on `tl`: HyperFrames seeks the timeline frame by frame,
so `Math.random()`, CSS transitions and `setTimeout` are not deterministic.
Use the seeded `rand` in `shake`.

For Remotion, the same math applies with `interpolate(frame, [start, end],
[from, to], {easing: Easing.inOut(Easing.sin)})` driving `transform`/`filter`
instead of `tl.to`.

### Framing helper (needed by Ken Burns)

Put image point (px, py) at frame point (tx, ty) at scale s, clamped so the
image always covers the frame.

```js
function frame(px, py, s, tx = 0.5, ty = 0.5) {
  const lim = (s - 1) / 2;
  const clamp = (v) => Math.max(-lim, Math.min(lim, v));
  return { scale: s, x: clamp(tx - 0.5 - s * (px - 0.5)) * W, y: clamp(ty - 0.5 - s * (py - 0.5)) * H };
}
```

### Ken Burns with easing

Slow push and drift between two framings. `sine.inOut` for calm,
`power2.out` for a push that lands on a word. Scale 1.05–1.3 over 3–6 s; above
1.4 a 1K still goes soft (Samsung sample: use 2K stills for pushes this big).

```js
function kenBurns(el, t, dur, from, to, ease = "sine.inOut") {
  tl.set(el, frame(from.px, from.py, from.s), t);
  tl.to(el, { ...frame(to.px, to.py, to.s), duration: dur, ease }, t);
}
kenBurns("#cam-shop", 2.7, 4, { px: 0.3, py: 0.4, s: 1.1 }, { px: 0.6, py: 0.5, s: 1.3 });
```

### Multi-layer parallax

Separate foreground (cut-out PNG with alpha) from background; near layers move
more. Each layer is overscaled exactly enough that its shift never shows an
edge (the first version without this showed a black strip).

```js
function parallax(layers, t, dur, dx, ease = "none") {
  // layers: [{el, depth}] depth 0 = far (barely moves), 1 = near
  for (const { el, depth } of layers) {
    const shift = dx * depth;
    tl.set(el, { x: shift / 2, scale: 1 + (shift + 8) / W }, t);
    tl.to(el, { x: -shift / 2, duration: dur, ease }, t);
  }
}
parallax([{ el: "#bg", depth: 0.2 }, { el: "#hero", depth: 1 }], 2, 2, 260);
```

### 2.5D from a depth map

One still, several copies masked by thresholded depth bands, moved as
parallax layers. Get a grayscale depth map (near = white) from a local
depth model or the image generator, then cut bands with ffmpeg (free):

```bash
for T in 96 160 208; do ffmpeg -y -i depth.png -vf "format=gray,geq=lum='if(gte(lum(X,Y),$T),255,0)'" depth_$T.png; done
```

```html
<div id="d0" class="layer"><img src="assets/img/still.png" /></div>
<div id="d1" class="layer slice" style="mask-image:url(assets/img/depth_96.png)"><img src="assets/img/still.png" /></div>
<div id="d2" class="layer slice" style="mask-image:url(assets/img/depth_160.png)"><img src="assets/img/still.png" /></div>
<!-- .slice { mask-mode: luminance; mask-size: cover; } -->
```

```js
parallax([{ el: "#d0", depth: 0.1 }, { el: "#d1", depth: 0.4 }, { el: "#d2", depth: 0.7 }], 4, 2, 200);
```

Keep `dx` small (≤ 200 px over 2 s): bands share the same pixels, so large
shifts open visible seams at band edges.

### Push-in on the beat

A fast scale kick that settles back a little; place `t` on the stressed word
or the music hit.

```js
function punchIn(el, t, amount = 0.08, settle = 0.35) {
  tl.to(el, { scale: `+=${amount}`, duration: 0.08, ease: "power4.out" }, t);
  tl.to(el, { scale: `-=${amount * 0.4}`, duration: settle, ease: "sine.out" }, t + 0.08);
}
```

### Shake (deterministic, decaying)

Impacts, explosions, "shock" facts. Seeded so every render is identical;
overscans so edges never show.

```js
function shake(el, t, dur, amp = 14, hz = 24, seed = 7) {
  let s = seed;
  const rand = () => ((s = (s * 16807) % 2147483647) / 2147483647) * 2 - 1;
  const steps = Math.round(dur * hz);
  tl.set(el, { scale: 1 + (4 * amp) / H }, t);
  for (let i = 0; i < steps; i++) {
    const k = 1 - i / steps;
    tl.to(el, { x: rand() * amp * k, y: rand() * amp * k, rotation: rand() * 0.6 * k,
                duration: 1 / hz, ease: "none" }, t + i / hz);
  }
  tl.to(el, { x: 0, y: 0, rotation: 0, scale: 1, duration: 0.05 }, t + dur);
}
```

Use a wrapper element for shake (`.shake > .cam`) when the same element also
has a Ken Burns move, so the two transforms do not fight.

### Rack focus with blur

Shift attention from one layer to another.

```js
function rackFocus(fromEl, toEl, t, dur = 0.6, blur = 10) {
  tl.set(fromEl, { filter: "blur(0px)" }, t);
  tl.set(toEl, { filter: `blur(${blur}px)` }, t);
  tl.to(fromEl, { filter: `blur(${blur}px)`, duration: dur, ease: "sine.inOut" }, t);
  tl.to(toEl, { filter: "blur(0px)", duration: dur, ease: "sine.inOut" }, t);
}
```

Blur is the most expensive filter to render; keep it ≤ 12 px and on as few
layers as possible.

### Pseudo dolly-zoom (vertigo)

Needs a cut-out subject over a background: the background scales up while the
subject holds (slightly shrinks). For realisation moments.

```js
function dollyZoom(subjectEl, bgEl, t, dur, bgScale = 1.35) {
  tl.set(bgEl, { scale: 1 }, t);
  tl.set(subjectEl, { scale: 1 }, t);
  tl.to(bgEl, { scale: bgScale, duration: dur, ease: "power1.inOut" }, t);
  tl.to(subjectEl, { scale: 0.96, duration: dur, ease: "power1.inOut" }, t);
}
```

### Whip-pan transition

Outgoing shot flies off with motion blur; bring the next scene in from the
opposite side with the mirror move so there is no black frame.

```js
function whipPan(outEl, t, dur = 0.25, dir = -1) {
  tl.to(outEl, { x: dir * W * 0.6, filter: "blur(18px)", duration: dur, ease: "power3.in" }, t);
}
```

## RTL notes (Persian)

- Reading direction is right→left: a pan or slide that reveals from right to
  left reads as "forward"; left→right reads as "back in time".
- Keep caption-safe areas clear of the move's end framing (bottom 18%).
- Era stamps and labels go in HTML, never baked into the still.
