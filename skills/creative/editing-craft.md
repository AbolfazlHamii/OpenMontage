# Editing Craft — the edit pass

## When to Use

After the stills, narration and music exist and the composition's cuts are
laid out (HyperFrames atelier workspace), before the final render. This file
covers what `editing-tricks.md` only names: placing sound design, editing the
music to the voice, word-timed RTL captions, and the QA that checks all of it.
The tricks themselves (match cut, whip-pan, map zoom…) stay in
`editing-tricks.md`; camera moves on stills in `camera-language.md`.

Everything here is local and free except the word timestamps
(`avalai_stt`, whisper-1, about $0.0001 per second of narration).

## The pass in five commands

```bash
python scripts/fa_sfx_library.py                       # once: projects/_sfx_library/fa-v1 (+ LICENSE.md)
# word timestamps per narration clip (paid, cents): avalai_stt {"word_timestamps": true}
python scripts/fa_edit_pass.py projects/<id>/<workspace>   # captions, music curve, SFX into index.html
# render: hyperframes_compose render_existing, then loudness_normalize (-14 LUFS / -1 dBTP)
python scripts/fa_render_qa.py <render> --edit-plan <workspace>/edit_pass.json --card <card>
```

`fa_edit_pass` reads `<workspace>/edit_plan.json` and rewrites three marked
blocks in `index.html` (`<!-- edit-pass:captions -->`, `<!-- edit-pass:audio -->`,
`// edit-pass:music`), so it can be re-run after any retime. Template:
`projects/samsung-history-fa/hyperframes-sample-v2/edit_plan.json` (git-ignored;
the fields are below).

```jsonc
{
  "duration": 15, "card": "full-history-in-n-minutes",
  "sfx_library": "../../_sfx_library/fa-v1",
  "narration": [{"id": "vo-1", "src": "assets/audio/s1.wav", "start": 0, "words": "assets/audio/s1.words.json"}],
  "captions": [{"text": "با فروش *ماهی خشک* شروع شد؟", "clip": "vo-1"}],   // *key* pill, _hot_ fire
  "music": {"src": "assets/audio/music_full.mp3", "under": 0.13, "gaps": 0.24,
            "clips": [{"id": "bgm", "start": 0, "end": 12.8, "track": 12},
                      {"id": "bgm-2", "start": 13.36, "end": 15, "track": 13, "align_downbeat": true}],
            "events": [{"kind": "drop", "start": 12.6, "end": 13.36},
                       {"kind": "set", "start": 13.36, "end": 15, "level": 0.28},
                       {"kind": "fade_out", "start": 14.43, "end": 14.555}]},
  "cuts": [{"at": 2.705, "sfx": "whoosh"}, {"at": 9.06}],          // scene changes
  "interrupts": [{"at": 1.78}],                                    // punch-ins, reframes
  "marks": [{"at": 13.36, "sfx": "hit", "priority": 4},
            {"at": 6.931, "sfx": "crackle", "lead": 0.55, "duration": 8, "volume": 0.35}],
  "emphasis_sfx": "pop", "beat_tolerance": 0.1,
  "caption_layout": {"boxes": [{"x": 0.083, "y": 0.79, "w": 0.834, "h": 0.1}]}
}
```

Evidence for each number: **M** measured (our renders, the CEOzoned
analysis in `projects/_reference/ceozoned-coca-cola/`), **P** platform or
engine docs, **R** editors' rule of thumb (vendor blogs, no controlled
study — treat as a starting point and check the retention graph).

## 1. Sound design

Tools: `tools/audio/sfx_placer.py`, library from `scripts/fa_sfx_library.py`,
missing sounds from `lib/sfx_synth.py`.

- **Peak on the moment.** Every library file carries `peak_s` (the first
  10 ms at full strength, within 1.5 dB of its loudest); the placer starts
  the file `peak_s` early so that moment lands on the cut, the pill pop or
  the punch word. The old "start 10–20 ms before the
  visual" rule (`sound-design.md`) is the same idea for a file whose peak is
  at its start. **R**
- **Families and levels** (HyperFrames `data-volume`, voice at 1): whoosh
  0.32, swish 0.3, pop 0.26, hit/impact 0.5, riser 0.28, crackle bed 0.3 (bed files are −26 dBFS RMS).
  Accents under speech are turned down ×0.7 (−3 dB). **R**
- **What gets a sound:** time jumps and scene changes (whoosh/swish), the
  first word of each key or hot caption run (pop), the punch line (low
  hit). Not every cut: 2 of 3 cuts carried one in the Samsung v2 and the
  plain cut-in reads as calmer. QA wants at least half the cuts. **R**
- **Density:** 6–36 accents per minute, never two within 0.3 s; when they
  clash the higher priority wins (mark > cut > emphasis), over the cap the
  emphasis pops go first. The CEOzoned style is dense (16 cuts/min plus text
  pops); 28/min in a 15 s hook is at the top of the range. **M/R**
- **Punch words:** a short low hit (`hit` from `sfx_synth`: 70→38 Hz thump,
  0.22 s decay, 30 ms crack) on the stressed word — low frequencies sit under
  the voice instead of masking it. The placer drops the pop that would land
  on the same word. Do **not** use the bundled `impact-bass-1` as a hit: it
  is a 2 s sub-bass held at −1 dBFS (`sustain_s` 1.9 in `library.json`); in
  the first v2 render it filled the 70 ms stop before «آتیش» (−12 dB instead
  of silence) and the last 0.4 s. Check `sustain_s` (< 0.3 s for accents). **M**
- **Beds as J-cuts:** a bed with `lead` (fire crackle 0.55 s before the
  bonfire appears) starts before its picture; the ear arrives first and the
  wipe feels motivated. **R**
- **Licences** (read on the sources' own pages, 2026-11-05):
  bundled HyperFrames set = Pixabay Content License (terms of 20 Oct 2026):
  commercial use and monetized YouTube fine, no credit; never upload a
  sound on its own or register it with Content ID. `sfx_synth` sounds are
  our own work. CC0 alternative: Kenney *Impact Sounds* (130) and
  *Interface Sounds* (100). Mixkit's SFX licence text did not load from
  here and its terms forbid passing files to third parties — not used.
  `fa_edit_pass` copies `LICENSE.md` into `assets/sfx/` with the files. **P**

## 2. Music editing

Tools: `tools/audio/music_duck.py` (volume curve), `tools/audio/beat_detect.py`
(grid, snap, align).

- **Duck under the voice, swell in pauses.** `under` 0.13 is about 17 dB
  under the narration with our TTS level (the v1 flat 0.18 measured ~14 dB);
  pauses of 0.45 s or more come up to `gaps` 0.24; shorter gaps stay ducked
  so the bed does not pump between words. Attack 80 ms, release 300 ms.
  `sound-design.md` asks 18–20 dB under speech. **M/R**
- **Silence drop, once:** music out (0.15 s fade) under the line before the
  key line, voice alone, then the punch. In Samsung v2: 12.6 → 13.36 under
  «جلوی کارگرهاش», then «آتیش زد!». **R**
- **Re-enter on a downbeat.** Split the bed into two clips; the second has
  `align_downbeat: true` and starts at the downbeat nearest to where the
  music would have been, so the hit and the music land together. **R**
- **End on a beat.** Put the `fade_out` end on a beat of the clip that is
  playing (the pass reports the grid). A bed that just fades with the picture
  reads as "the file ran out". **R**
- **Cuts on beats, but speech wins.** The snap report gives each cut's
  nearest beat and whether it fits the pause it sits in (`windows`); only
  move cuts that stay inside their pause. Samsung: 2.705 was already on a
  downbeat, 6.85 → 6.931 fitted, 9.06 (inside speech) stays. CEOzoned
  measured 70% of cuts on onsets vs 55% by chance — a weak but real
  preference. **M**
- **HyperFrames:** volume tweens are absolute and replace `data-volume`, so
  tweened music clips keep `data-volume="1"` (lint
  `audio_volume_tween_overrides_gain`). Outside HyperFrames, `music_duck`
  `render` bakes the same curve into a WAV. **P**

## 3. Word-timed RTL captions

Tool: `tools/subtitle/word_captions.py`.

- **Text from the script, time from whisper.** Captions show the script
  (our spelling, digits); whisper writes «رحیث» for «رئیس» and «1995» for
  «۱۹۹۵». Words are aligned by fuzzy similarity after folding digits,
  ی/ك/ئ, ZWNJ and diacritics; unmatched words share their neighbours' time
  by letter count. **M**
- **Fix whisper's edges.** Clamp into silencedetect speech, then snap each
  start to the nearest attack within 150 ms (`audio_onsets`). «آتیش» came
  130 ms early from whisper; the 70 ms stop before it is too short for
  silencedetect. A punch that is 130 ms late on screen looks wrong. **M**
- **Look:** the group shows dimmed (0.6; 0.45 was too faint to read ahead), each word lights up as it is
  said (#ffd23f, scale 1.08) and settles to cream; key runs get a cobalt
  pill that pops (`back.out`), hot runs are fire-coloured. Whole words only
  (letters would break Persian joining). **R** — vendor tests claim
  10–30% more watch time for word-by-word captions; no independent study
  found.
- **Timing rules:** group on screen 0.8–7 s; a caption appears with its first
  word (60 ms lead); gaps under 0.35 s are bridged so the box never blinks
  off for a few frames (v1 blinked 6 times in 15 s). **R**
- **Placement:** bottom edge 120 px (11%) up, above YouTube's control bar,
  inside the 5% safe area; max width 1600 px. **P/R**
- **HyperFrames:** group timing is `data-cs`/`data-ce`, not
  `data-start`/`data-end` (reserved for clips; lint error
  `deprecated_data_end`). **P**

## 4. Rhythm, hook and pattern interrupts

- **Change something every ≤ 6 s** (card `pattern_interrupt_seconds.max`);
  on stills a punch-in (jump cut 1.12 → 1.30 scale) on the stressed word
  counts. **M** (card from CEOzoned: ASL 3.75 s, 16 cuts/min)
- **Hook, first 5 s:** at least 2 visual changes, a sound accent and the
  caption with the first word. Samsung v2: punch on «سامسونگه» (1.78), time
  jump on the downbeat (2.705), punch onto the fish (4.505). **R**
- QA compares ASL to the card's section (hook for videos ≤ 18 s, else
  body) with 35% tolerance and flags any hold longer than the card's max.

## 5. Look: grade, grain, vignette

- **One grade per era** in CSS on the camera layer: present day crisp
  (`contrast(1.1)` also darkens the lighter linework of the hook still),
  1938 `sepia(0.32) saturate(0.86)`, 1995 `saturate(0.9) contrast(1.07)`.
- **One grain and vignette over everything** (overlay, opacity 0.09, 384 px
  seeded noise tile moved at 12 fps; radial vignette to 34% black) so stills
  from different generations look like one film. Grain raises the bitrate.

## 6. History transitions

- **Paper wipe, right to left** ("forward in time" moves right to left in
  RTL): the next era is its own clip on another track, revealed with
  `clip-path: inset(0 0 0 100%)` → `inset(0)` over 0.26 s, a torn cream edge
  riding the wipe, swish centred on the beat.
- **Era flash** on a time jump: cream flash 0.08 s in, 0.28 s out, plus a
  whoosh (editing-tricks #15). Never more than two tricks on one cut.

## 7. End screens and loops

- Videos ≥ 60 s: plan a 5–20 s end-screen block at the very end and leave
  room for two video boxes; put `end_screen: {start, end}` in the plan and
  QA checks it. **P**
- Shorts: no outro card; make the last line and frame lead into the first
  (editing-tricks #27).

## QA checks (scripts/fa_render_qa.py --edit-plan)

| Check | Pass when |
|---|---|
| `cut_rhythm` | ASL within 35% of the card section; no hold over the card max |
| `hook_edit` | ≥ 2 visual changes, a sound accent, caption within 0.3 s of the voice, all in the first 5 s |
| `sfx_density` | 6–36 accents/min, none closer than 0.25 s |
| `cut_accents` | ≥ 50% of cuts carry a sound |
| `caption_onscreen` | groups 0.8–7 s, no blink under 0.15 s, no word lit outside speech |
| `beat_sync` | share of visual changes on a beat (±80 ms) ≥ 0.8 × the card's ratio and above chance |
| `music_ducking` | bed ≥ 3 dB higher in real pauses than its usual level under speech |
| `music_ending` | music stops within 0.1 s of a beat |
| `end_screen` | (≥ 60 s) 5–20 s block ending at the end |

## Samsung sample: before → after (2026-11-05)

v1 = `renders/sample_music_a_fun_and_games.mp4`, v2 =
`renders/sample_music_a_v2_edit.mp4` (workspace `hyperframes-sample-v2/`);
same three stills, narration and Mixkit track. QA reports in
`renders/review/v1_baseline/qa_edit.json` and `renders/review/v2_edit/qa.json`.

| Check | v1 | v2 |
|---|---|---|
| loudness | −11.5 LUFS (fail) | −14.0 LUFS, −5.3 dBTP |
| visual changes, ASL | 4, 3.0 s | 6, 2.1 s (card hook 2.8 s) |
| hook, first 5 s | 1 change, no sound | 3 changes, 3 accents |
| SFX | none | 28/min, closest 0.38 s apart |
| cuts with a sound | 0/3 | 2/3 |
| captions | 7 groups, 4 blinks | 7 word-timed groups (29 words), no blinks |
| changes on a beat | 25% (chance 27%) | 67% (chance 26%) |
| bed in pauses vs under voice | 0 dB (flat 0.18) | +5.3 dB |
| music ending | 0.30 s off the beat | on the beat (14.56 s) |
| mix in the stop before «آتیش» | −31 dB (music) | −51 dB (silence drop) |

Two mistakes the measurements caught and the tools now prevent: a held
boom used as a hit (`sustain_s`), and a peak-normalized crackle bed that sat
at −54 dB in the mix (now soft-clipped to −26 dBFS RMS).

## Sources

- Licences: pixabay.com/service/terms (20 Oct 2026), kenney.nl/assets/impact-sounds,
  kenney.nl/assets/interface-sounds, kenney.nl/support, mixkit.co/license.
- HyperFrames: `.agents/skills/hyperframes-core/references/variables-and-media.md`
  (volume tweens), `tracks-and-clips.md` (no overlap on a track), lint codes.
- YouTube end screens: last 5–20 s (YouTube Help, via vizard.ai / creatorhandbook summaries).
- Retention advice (vendor, uncontrolled): air.io "advanced retention editing",
  joyspace.ai "pattern interrupts", opus.pro caption presets.
- Measured: `styles/editing/learned/ceozoned-history-learned.yaml`.
