---
name: survival-episode-structure
description: Skeleton and review gate for long (10-25 min) second-person countdown survival episodes of The Milo Saga / Melvin-style channels - cold open, series intro, chapter template, set-piece design, escalation and breathers, mystery thread, cliffhanger, loops table - plus the final script review that combines retention, clarity and human checks. Use when planning, outlining, writing or reviewing an episode script for the zombie series.
---

# Survival episode structure (10-25 min)

Built on the measured reference format (`channels/dayzero/research/2026-11-12_style-bible.md`) and the
lessons from video 1 (`projects/milo-ep2-airlift/PLAN.md` section 1). Use with `story-clarity` and
`human-story`; hooks and retention numbers live in `skills/creative/narration-craft.md`; the first and last
30 seconds in `video-openings-endings`; the middle and the analytics loop in `audience-retention`. For the
3-minute series format see `projects/milo-ep2-airlift/SERIES_3MIN.md`.

## Macro shape

| Part | Time (22 min ep.) | Job |
|---|---|---|
| Cold open | 0:00-0:40 | Flash-forward to the worst moment: "you + number" in the first 3 s, real danger on screen by 10 s, one unanswered question |
| Series intro | 0:40-0:58 | Reusable sting (same every episode, only the episode tag changes) |
| Set-up | 0:58-2:30 | Where we are after last episode (one line recap, no more), the new rule shown/told/tested, the goal and the countdown, the inventory |
| Act 1 | to ~8:00 | 3-4 chapters: the plan meets the world; each chapter a new obstacle |
| Midpoint turn | ~8:00-11:00 | The plan breaks (crash, betrayal, rule changes); the stakes become personal |
| Act 2 | to ~18:00 | 4-5 chapters, faster cuts, bigger set pieces, a quiet emotional chapter in the middle |
| Climax | ~18:00-21:00 | The cold-open moment arrives, then goes further than we showed; a sacrifice or a choice |
| Cliffhanger | last 30-60 s | One small win, one new question; "Part N" card, 5 s of picture for the end screen |

For 10-14 min episodes keep the same shape with fewer chapters (6-8).

## Chapter template (one per countdown step, 1.2-2 min)

1. **Clock card + where we are** (story-clarity: who / where / want).
2. **New problem** caused by the last chapter ("but" / "so").
3. **Plan**: one practical survival idea (a real fact: water per day, how to splint a leg, why sound carries
   at night). Keep it true and simple.
4. **Complication**: the plan meets the rule or a person.
5. **Set piece or turn**: the visual peak of the chapter.
6. **Cost**: something is lost (inventory number goes down, someone is hurt, time is spent).
7. **Breath + new sign**: a human beat, then a sign of the next problem (the hook into the next chapter).

## Set-piece design (action that reads)

- **Geography first:** one wide shot + one line placing hero, threat and goal.
- **Clear goal with a visible finish line** (the ramp, the door, the other roof).
- **Ticking clock** on screen or in sound (engine noise rising, the 40-second window).
- **Three escalating obstacles**, each harder, then a **reversal** (the plan fails, an improvised one works).
- **One quiet beat inside the action** (a hand reaching, a breath held) before the release.
- **Consequence that carries over** (injury, lost item, a promise) so action changes the story.
- Shot rhythm: 1-2 s cuts at the peak, a held 3-4 s wide right after to let the viewer breathe.

## Escalation and breathers

Plot intensity per chapter on a 1-5 scale before writing. Rules: never three 5s in a row; after every 4 or 5
put a 2 (human beat); the curve must end higher than it started; the quietest chapter sits just before the
final run (calm before the storm).

## Threads to run across the episode

- **Countdown** (planes left, hours left): stated every chapter.
- **Inventory** in numbers at start, mid and end (it should end worse).
- **One mystery thread** opened early, paid near the end (who is on the radio, why the dead turn east).
- **One relationship thread** with warmth planted, tested, paid (Milo and Vera; Pip's radio).
- **Callback props** that return at the climax.

## Loops table (required in every script file)

| Loop | Opens (time, line) | Re-planted | Pays (time, line) |
|---|---|---|---|
Max 3 open at once; every loop paid except the one carried to the next episode.

## Script file format

Markdown with `[CARD: ...]`, `[SFX: ...]`, `[DROP]`, `[BEAT]`, `[HOLD 2s]`, chapter headers with target times,
then the loops table, the intensity curve and the cast/sets/props lists (the shot list is built from these).
English and Persian versions keep the same lines in the same order (one line = one clip) so the timeline syncs.

## Final review gate (before the owner sees a draft, and again before TTS)

1. **Structure:** macro shape timings within ±15%; every chapter follows the template; intensity curve obeys
   the rules.
2. **Clarity:** run the cold-viewer audit from `story-clarity`; zero `?WHO/?WHY/?RULE/?JUMP` marks.
3. **Human:** answer the four human-ness questions from `human-story` for every chapter.
4. **Retention:** hook by 3 s, first loop by 10 s, something new every ~8 s, comment question only after a
   payoff, outro ≤ 8 s (`narration-craft`; run `scripts/fa_script_lint.py` on the Persian version).
5. **Universal audience:** no Iran angle, nothing gory, no real brands or real people
   (memory: videos-universal-audience).
6. **Read aloud** the cold open and the climax at narration speed; fix every stumble.
7. Show the owner: premise line, the intensity curve and the loops table first, then the full script.
