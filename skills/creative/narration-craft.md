# Narration Craft — hooks, open loops and retention for Persian narration

## When to Use

At the `script` stage of any narrated Persian video, after the draft and
before any TTS is paid for. Write the draft, run the lint, fix what it flags,
then ask the owner to approve the script.

```bash
python scripts/fa_script_lint.py draft.txt --target 90 --voice narrator
python scripts/fa_script_lint.py projects/<id>/artifacts/script.json --voice Charon --style calm --llm
```

`--voice` takes the narrator's measured pace (letters per second) from
`channels/fa-main/voices.yaml`, so the timeline matches the real voice: on the
Samsung sample the lint estimated 15.1 s for two lines that Kore read in
14.4 s. `--llm` adds a worker-tier draft of the open loops (~$0.0005); it is a
draft for you to review, never a verdict. Exit code 0/1/2 = low/medium/high
risk. The report is `<input>.lint.json`; paste its Persian summary to the owner.

The lint flags; it does not decide. Every threshold below is a heuristic for
spoken Tehrani Persian, and the evidence behind each is stated honestly.

## Evidence levels

- **A** — platform documentation (what YouTube itself measures).
- **B** — published research.
- **C** — documented practitioner practice (named creators, leaked or public production guides).
- **D** — our own heuristic, set from the reference analysis and the audition; not tested on this channel's analytics yet. Revisit after the first 5 uploads (`channels/fa-main/retros/`).

## The checks

| Check (`code`) | Rule (lint threshold) | Why | Evidence |
|---|---|---|---|
| Hook timing (`hook_late`, `hook_missing`) | First hook — "you"-address, a number, a question or a turn («ولی») — by 3 s (warn), 5 s (fail). | YouTube Analytics reports *Intro* as the share still watching at 30 s, i.e. whether the opening matched what the title and thumbnail promised. The first seconds decide that. 3/5 s are our cut-offs. | A for the 30 s Intro metric; D for 3/5 s |
| First open loop (`loop_late`) | A question the viewer wants answered opens by 10 s. | Curiosity rises when attention is drawn to a specific gap in knowledge (information-gap account). | B (Loewenstein 1994); D for 10 s |
| Loops at once (`loops_too_many`) | At most 3 open at the same time. | A gap that is too large or too many gaps turns curiosity into confusion. | B (direction), D (number) |
| Unclosed loops (`loop_unclosed`) | Every opened loop is answered, except one carried into a next-episode ending. | An unpaid promise costs trust and comments. | C/D |
| Re-hooks (`rehook_gap`) | Something new — «ولی», a question, a number, a turn — at least every 8 s (warn), 12 s (fail). | Matches the edit cards' pattern-interrupt range. The MrBeast production guide plans deliberate re-engagement beats through the video. | C (practice), D (8/12 s) |
| Causality (`and_then`) | More «ولی»/«برای همین» than «و بعد». | "But / therefore" instead of "and then" between beats: the South Park writers' rule. | C |
| Sentence length (`sentence_long`) | No sentence over 7 s of speech; some punches ≤ 1.5 s. | Listeners cannot re-read; long Persian clauses with the verb at the end bury the point. | D |
| Rhythm (`rhythm_flat`) | Sentence-length variation CV ≥ 0.25 when there are ≥ 6 sentences. | Same-length sentences read as a drone in TTS. | D |
| Specifics (`vague`, `vague_words`) | ≥ 0.5 numbers/years/names per 10 s; fewer vague words («خیلی»، «کلی»، «صدها») than specifics. | Specific facts are what the reference does every sentence (CEOzoned notes: a visual gag per sentence). | C (reference), D (rate) |
| Ending (`ending_flat`, `ending_weak`) | End on a loop back to the hook, a next-episode tease, a question or a twist — not only a summary or "subscribe". | A flat ending gives no reason to watch to the end or start another video. | C/D |
| Early end signal (`end_signal_early`) | «خلاصه»، «در آخر» … not before 85% of the runtime. | Viewers leave when the video sounds finished. | C/D |
| Early CTA (`cta_early`) | No subscribe/comment request in the first 30 s. | The first 30 s are the Intro window; spend them on the promise, not the ask. | A (window), C |
| Register (`register_mixed`) | No bookish forms («است»، «می‌باشد»، «آن‌ها»، «را») in colloquial narration. | The channel voice is spoken Tehrani (`channels/fa-main/channel.md`); mixed register sounds like a news anchor reading a script. | D (channel decision) |
| Digits (`digits`) | Numbers spelled out in TTS text; digits only in captions. | TTS reads digits inconsistently; the channel bible spells them out. | D (measured in the audition) |
| Length (`too_long`, `too_short`, `section_overflow`) | Within ±5–15% of the target; each section fits its time slot. | Overruns force speed-ups or cuts later, after audio is paid for. | D |
| Outro (`outro_long`) | Trailing subscribe/comment requests ≤ 8 s. | Every "Most replayed" curve we pulled falls to ~0 in the outro (5 of 5 videos, below). | A (curve) + D (8 s) |

## Writing patterns that pass the lint

- **Open on the viewer or the paradox, not the background.**
  «احتمالاً گوشیِ توی دستت سامسونگه… ولی می‌دونستی این شرکت با فروش ماهی خشک شروع شد؟»
  — "you" at 1.9 s, then the paradox. Compare «این شرکت در سال ۱۹۳۸ تأسیس شد» — no hook.
- **Plant the question, delay the answer, then pay it off.** Mark it so the lint can check it:
  plain text `{{open:fish}} … {{close:fish}}`; in a script artifact put
  `metadata.loops = [{"id", "question", "opens": <section id>, "closes": <section id or null>}]`
  (section text goes to TTS verbatim, so markers must not be inside it).
- **Every 8 seconds, give a «ولی» or a number.** «ولی سی سال بعد، یه تصمیم همه‌چی رو عوض کرد.»
- **Break long clauses before the verb drifts away.** Persian puts the verb last; two short
  sentences beat one long one for the ear.
- **Close the circle.** Reuse two content words of the first sentence in the last (the lint
  detects this as a `loop` ending), or tease the next episode.

## What the research actually supports about "open loops"

- **Curiosity is an information gap** the viewer notices (Loewenstein 1994). It is strongest
  when the viewer can almost guess the answer: in Kang et al. (2009) curiosity peaked at
  middling confidence, and curious people remembered surprising answers better a week or two
  later. So ask questions the viewer can make a guess at («فکر می‌کنی چند تا باتری داشت؟»),
  not ones about things they know nothing of. **B** (one fMRI study of 19 people; no replication found).
- **The Zeigarnik effect** (unfinished things are remembered better), often quoted for open
  loops, failed to replicate in a 2025 meta-analysis; the urge to *resume* an interrupted
  task (Ovsiankina) held up. An open loop works because the viewer wants the ending, not
  because they remember it: keep the question in front of them and remind them just before
  the payoff. **B**
- **Spoilers did not spoil**: readers enjoyed stories more when told the ending first
  (Leavitt & Christenfeld 2011; a later thesis found the effect only for a separate spoiler
  paragraph). Saying *what* happens in the hook is fine; the loop is *how* and *why*.
  **B** (contested)
- **Narrative transportation**: people absorbed in a story are moved by it more (Green &
  Brock 2000, four experiments; a later meta-analysis by van Laer and colleagues). Second-person scenes
  («تصور کن…»), concrete images and one protagonist are how Persian channels do it
  (`channels/fa-main/tone.md`). **B** (mechanism) + **C** (practice)
- **Progressive novelty**: pacing is how fast new information arrives (Mario Joos, former
  MrBeast retention strategist, as quoted by Vidpros). **C**

## What "Most replayed" heatmaps show (2026-11-05)

YouTube's "Most replayed" curve (yt-dlp `heatmap`, 100 points per video, only for videos
with enough views) marks moments watched or rewatched most. It is not the retention graph,
but YouTube's own key-moments report treats spikes as rewatched/shared and dips as skipped
(**A**). We lined the curves of 5 reference videos (Crayon Capital: Enron 1.1M, Wolf of
Wall Street 4.3M; Company Man: Nokia 1.2M; Gooneh Var: 2 videos, 73K–107K) up with their
transcripts (`scratchpad heat_beats.py`; transcripts under `projects/_reference/`).

Peaks (rewatched):

- **The answer to the title's question, said right after the question.** Gooneh Var's top
  peak (+0.88 over its neighbourhood) is «…اونوقت چرا؟ خب به دلیل رژیم غذایی»; Nokia's
  (+0.97) is the "why it lost to smartphones" explanation.
- **The mechanism, with a number and a punchline.** "a pump and dump… at Stratton Oakmont
  it was called another Tuesday" (+0.78); "$586 million in earnings weren't real… cooked the
  books so hard they caught fire" (+0.49).
- **A turn or a new character.** "Wait, where's the actual money?" (+0.58), "Enter Arthur
  Andersen" (+0.57).
- **The story's shock moment** (Gooneh Var, Roman servant, +0.87).
- Most top peaks sit between 40% and 80% of the runtime: the payoff of the title belongs
  mid-video, stated crisply, not saved for the last seconds.

Dips (skipped):

- the long setup just before an answer («اینجا یه مشکلی بود، محاسبات جور درنمیاد…»
  dipped, the answer after it peaked): one sentence of problem, then the answer;
- side stories (Belfort's door-to-door meat business), generic lists ("mansions,
  Lamborghinis, Rolexes"), restating what was already said;
- every outro: all 5 curves end near 0. Nothing important after the last beat.

Rules we take from it (**D** until our own analytics confirm): one-sentence setups; the
title's answer at 40–80% with a number and a punchline; cut side stories and lists that
carry no stake; a new character or "wait, where's the money?" turn every few minutes;
outro under 8 s (`outro_long`).

## Working with the lint

1. Draft the script yourself (premium tier: final Persian text is never delegated —
   `skills/meta/delegation-protocol.md`). Hook options can come from the hook lab
   (`scripts/fa_editorial.py hooks`).
2. Run the lint; fix every 🔴; fix 🟡 unless you have a reason, and write the reason in
   the script stage summary.
3. With `--llm`, compare the drafted loops with what you intended. If the worker sees a
   loop you did not mean, the viewer may too.
4. Run the fact-check step on the final text before TTS.
5. Show the owner: the script, the lint summary, and what you changed.

## Sources

- YouTube Help — Measure key moments for audience retention (Intro = viewers still
  watching after the first 30 s): https://support.google.com/youtube/answer/9314415
- Loewenstein, G. (1994). The Psychology of Curiosity: A Review and Reinterpretation.
  *Psychological Bulletin* 116(1), 75–98.
- "How to Succeed in MrBeast Production" (internal guide, leaked 2024; first minute and
  re-engagement points) — summary: https://www.alexanderjarvis.com/memo-how-to-succeed-in-mrbeast-production/
- Trey Parker and Matt Stone on "but / therefore" (NYU talk), summarised:
  https://perell.com/note/but-therefore-rule/
- Kang, M. J. et al. (2009). The Wick in the Candle of Learning: Epistemic Curiosity Activates
  Reward Circuitry and Enhances Memory. *Psychological Science* 20(8), 963–973.
- Ghibellini, R. & Meier, B. (2025). Interruption, recall and resumption: a meta-analysis of
  the Zeigarnik and Ovsiankina effects. *Humanities and Social Sciences Communications* 12.
- Leavitt, J. D. & Christenfeld, N. J. S. (2011). Story Spoilers Don't Spoil Stories.
  *Psychological Science* 22(9), 1152–1154.
- Green, M. C. & Brock, T. C. (2000). The Role of Transportation in the Persuasiveness of
  Public Narratives. *Journal of Personality and Social Psychology* 79(5), 701–721.
- Mario Joos on pacing ("progressive novel information"), quoted by Vidpros:
  https://vidpros.com/retention-editing-what-you-can-learn-from-mario-joos/
- Channel measurements: `channels/fa-main/voices.yaml` (narrator pace), CEOzoned reference
  notes `projects/_reference/ceozoned-coca-cola/REFERENCE_NOTES.md`.
