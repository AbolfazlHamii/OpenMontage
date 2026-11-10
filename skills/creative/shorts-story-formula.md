# Shorts story formula (from 12 measured 3D-cartoon Shorts)

Use for every vertical Short on the fa channel, and for the cold open and chapter turns
of long videos. Data and Persian notes: `channels/fa-main/research/2026-11-10_retention_and_next_long.md`.

## What the hits had (Ricks Clips 12-33M views, Toffee3D 827K) and the misses lacked
- **45-65 s, fast narration** (190-200 English wpm). Our 16-18 s tests had no room for a story.
- **Line 1 is a person doing something absurd, stated as fact**, no setup ("He put a bronze ball in a
  dragon's mouth and told the emperor: if this ever falls out, run.").
- **Mockery or doubt** from others right after; the viewer sides with the lone hero.
- **A false payoff mid-way** ("a ball fell... nothing happened; they laughed harder").
- **Dialogue**: short, funny quoted lines from the characters (two voices).
- **"You see," + an everyday analogy** explains the real mechanism late (~70 % in).
- **Visual, ironic payoff as the last words** ("The next morning, the palace was rubble."). No CTA at the end: it loops.
- **Continuous camera**: 0-3 hard cuts per minute; the camera glides through the 3D world; nothing static 4+ frames.
- **No dates or names** in the narration; universal characters ("the youngest engineer", "the emperor").
- Dry explainers in the same look fail ("How a bullet gets fired": 6K).

## Beat sheet (Persian, 45-60 s)
| s | beat |
|---|---|
| 0-3 | the absurd act (subject + verb + strange object) |
| 3-10 | why it's absurd + others mock (one quoted line) |
| 10-30 | escalation, 2-3 beats, a false payoff, stakes rise |
| 30-45 | «ببین...» + the mechanism through an everyday analogy |
| 45-55 | ironic visual payoff, the last words of the video |

## Production rules
- Two voices: narrator plus characters (Gemini multi-speaker TTS, or two calls in one group).
- Camera: continuous moves; hard cut only for a place/time jump (white flash).
- Word-by-word captions (`make_captions_pop.py`, Lalezar, key words yellow, lower third).
- Music stops on the twist; a low hit; push-in on the payoff.
- Check every fact with a source; say "legend says" for disputed stories.
- The `cartoon-audio-short` skill (installed in `~/.claude/skills/`) has the three.js engine,
  shot-plan and motion rules for this look; the Blender path is `projects/short-escape-fa/blender/`.
