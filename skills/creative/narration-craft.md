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
14.4 s, but on the 85 s Samsung draft Kore with flash-lite read 8.1 letters/s
(the estimate ran ~10% short): budget with the pace measured for the voice,
model and style you will use. `--llm` adds a worker-tier draft of the open
loops (under $0.01; $0.0037 with claude-haiku-5-5 on the 85 s draft); it is a
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

## Hooks by time window

YouTube only measures the 30 s mark (**A**); the 3 s and 10 s windows are practice (**C**)
and our lint thresholds (**D**). Facebook's "47% of the value in the first 3 seconds" is
about *ads*, from a 2015 Facebook-commissioned Nielsen study — do not quote it for YouTube.

| Window | Job | Script move |
|---|---|---|
| 0–3 s | Stop the scroll: the hook is in the first words, no "hi, welcome". | One hook type below; the lint wants the first «تو», number, question or «ولی» by 3 s. |
| 3–10 s | State the gap: why this is strange, what is at stake. | The paradox's second half, or the question the video answers. |
| 10–30 s | Keep the title's promise: show the viewer they are in the right video, then give a first small payoff. | CEOzoned says the title line at ~15 s ("This is the entire history of Coca-Cola"); our «این کل تاریخ سامسونگه». |

The hook lab (`scripts/fa_editorial.py hooks`) drafts one hook of each type below, with the
question each one leaves open (`open_loop`) and the lint's timing (`first_hook_seconds`).
Shortlist hooks that land under 3 s and whose loop the video really answers.
The examples are patterns; facts in a real script need sources.

| Type | What it is | Example (spoken Tehrani) |
|---|---|---|
| `number` | A big exact number. | «هر سال دویست و چهل و یک میلیون تا گوشی با یه اسم از کارخونه میاد بیرون.» |
| `paradox` | Two true facts that should not fit. | «بزرگ‌ترین سازنده‌ی چیپ حافظه‌ی دنیا، با فروش ماهی خشک شروع کرد.» |
| `question` | A question the viewer can almost answer. | «فکر می‌کنی سامسونگ اولش چی می‌فروخت؟ نه گوشی، نه تلویزیون…» |
| `shock` | The most extreme act, said flatly. | «رئیس سامسونگ صد و پنجاه هزار تا گوشیِ خودشو آتیش زد.» |
| `story` | One person, one year, one place, mid-action. | «سال هزار و نهصد و سی و هشت، تو شهر تگو، یه مرد جوون یه مغازه‌ی کوچیک باز کرد.» |
| `promise` | What the viewer will know by the end. | «تا آخر این ویدیو می‌فهمی یه بقالی چطوری شد غول تکنولوژی.» |
| `you` | Puts the viewer in the scene. | «احتمالاً گوشیِ توی دستت سامسونگه…» |
| `myth` | What people believe, then that it is wrong. | «همه فکر می‌کنن سامسونگ از اول الکترونیکی بود. ولی سی و یک سال طول کشید تا اولین تلویزیونشو بسازه.» |
| `contrast` | Tiny start vs giant today, one breath. | «از یه مغازه‌ی ماهی خشک… تا چیپی که الان توی گوشیِ توئه.» |
| `cold_open` | Start at the climax, then rewind. | «صد و پنجاه هزار تا گوشی وسط حیاط کارخونه داره می‌سوزه. ولی بذار از اول بگم.» |
| `stakes` | What was about to be lost. | «یه تصمیم اشتباه دیگه، و کل شرکت از دست می‌رفت.» |
| `mystery` | One strange detail, explained later. | «یه چیزی توی این عکس قدیمی هست که کل داستان سامسونگ رو لو می‌ده.» |

## Re-hooks in the script, not only the edit

A re-hook is a sentence that changes the question: a «ولی», a new number, a new person, or
the viewer's own question said aloud («می‌گی چرا؟ خب…»). Plan them in the text; the editor's
cuts (`styles/editing/`) then land on them. Useful moves:

- **Reminder before the payoff:** «یادته گفتم با ماهی خشک شروع کرد؟ حالا ببین…» — the loop
  works because the viewer wants the answer (Ovsiankina), so bring the question back.
- **Escalate the stakes** each act: money → reputation → the company itself.
- **Close one loop, open the next in the same breath** (the "therefore… but" chain).
  For 60–90 s: one big loop (the hook's paradox) + 2–3 small ones that close within 20 s.
  For 5–15 min: the big loop pays off at 40–80% (heatmap peaks, above), a new loop per act.

## Delivery: directing Gemini TTS in Persian

Gemini 3.8 TTS reads the text verbatim; delivery goes in `style`, short tags like
`<short pause>` work inline (`skills/creative/persian-localization.md`). It has no emphasis
markup, so emphasis is written into the text:

- **Energy curve = one `style` per section.** Synthesize section by section (the token cap
  forces it anyway) and give each section its own style. Record it in the script artifact:
  `voice_performance.energy_curve` and `sections[].delivery_cues` (`pace`, `energy`,
  `emphasis_words`, `pause_before_seconds`, `provider_text`).
  - hook: «پرانرژی و کنجکاو، مثل رفیقی که یه راز می‌گه، ریتم تند، لهجه‌ی تهرانی محاوره»
  - story: «قصه‌گو و گرم، ریتم متوسط رو به تند، صمیمی»
  - reveal: «آروم‌تر و جدی، کلمه‌ی آخر رو محکم بگو»
  - ending: «گرم و صمیمی، کمی آروم‌تر، با لبخند»
- **Pause before the reveal.** `<short pause>` (≈0.4 s in the lint) before the number or the
  twist; listeners recognised words heard after a silent pause better in a later memory test
  (MacGregor, Corley & Donaldson 2010, **B**). Longer silences go in the edit
  (`pause_before_seconds`), not as TTS tags.
- **Emphasis by position.** Make the reveal its own short sentence and put it last:
  «…و همه رو آتیش زد. <short pause> صد و پنجاه هزار تا.» An ellipsis «…» gives a
  hesitation; «!» lifts the pitch.
- **Pace.** Our voices read ~9–10 letters/s (~150 words/min, `voices.yaml`); the Persian
  channel we studied speaks ~190 words/min (`channels/fa-main/tone.md`, **C**). Ask for a
  fast style, allow up to 1.08× speed-up in the edit, and slow down on numbers and names.
- **Check the take.** Round-trip every final clip (`lib/fa_text.round_trip`); a style that is
  too fast starts dropping or changing words (the audition: Charon energetic 0.964).

## Address, specifics and register

- **«تو», not «شما».** A conversational, second-person style helped learning in Moreno &
  Mayer's experiments (personalization principle, **B**; later reviews found smaller effects,
  and it may fade in long lessons). The channel speaks to one friend, so singular «تو».
- **Exact beats round.** "Sharp" numbers (241.2 million) read as more factual than round ones
  (Schindler & Yalch 2006, ads, **B**). Say the exact number once, then a picture of it
  («یعنی تقریباً هر ثانیه هشت تا گوشی»).
- **Names and places** make a beat concrete: one protagonist per era, named once, then
  «همون آقای لی».
- **Sentence rhythm:** short-short-long; never three sentences of the same length in a row
  (lint `rhythm_flat`). Persian is verb-final: if the subject and the verb are more than ~12
  words apart, split the sentence.

## Endings and calls to action

- **Loop ending (default for the "entire history" format):** come back to the hook's image
  and close it. CEOzoned closes Coca-Cola with the hook's paradox ("a failed medicine…") and
  "And that is the entire history of Coca-Cola" — no ask (reference transcript).
- **Next-episode tease:** end on the open question the next video answers; the lint lets one
  loop stay open for it (`next_episode`).
- **CTA placement:** never in the first 30 s (`cta_early`); a one-line comment question can
  sit right after a payoff mid-video; the closing ask stays under 8 s (`outro_long`).
- **End screens** can only sit in the last 5–20 s (YouTube Help, **A**): leave 5 s of picture
  after the last line so the end-screen video does not cover a beat.
- **Shorts cut:** every replay of a Short counts as a view since 31 March 2025 (**A**), so a
  last line that flows into the first one is worth writing for the vertical cut.

## Persian-speaking audience

- **Spoken Tehrani all the way** («می‌شه»، «اون»، «رو»، «یه»); written Persian is a separate
  register, and mixing them sounds like a news anchor (lint `register_mixed`). The channel's
  safe and "too rude for now" slang lists are in `channels/fa-main/tone.md`.
- **Humour:** short, about the situation or ourselves; never about ethnic groups (Turk/Rashti/Lor
  jokes), religion, or the viewer's country's politics or sanctions. Quote a person's own
  provocative line as theirs («به قول خودش…»), do not make it ours.
- **Years in full.** «سال شصت و نه» sounds like the Iranian year 1369 (1990), not 1969: say
  the full Gregorian year once («سال هزار و نهصد و شصت و نه»), then relative time («نه سال بعد»).
- **References:** prefer things every Persian speaker knows (bazaar, «سوپری سر کوچه», Nokia
  1100, exam stress) over US pop culture. No politics: topics.md already drops political subjects.
- **Viewing conditions:** YouTube is filtered in Iran, so many viewers watch through VPNs on
  mobile data; the first line must work at low resolution with the captions on.

## Claims we checked (and what to do with them)

| Claim you will meet | Status |
|---|---|
| "Humans now have an 8-second attention span, less than a goldfish" | Myth: traced to a 2015 Microsoft Canada report citing a commercial stats site; no study behind it (BBC, 2017). Never use. |
| "47% of a video's value is in the first 3 seconds" | Facebook/Nielsen, 2015, mobile *ads*, Facebook-commissioned. Not about YouTube narration. |
| "Keep 50% (or 60%) past 30 s and YouTube treats it as a good intro" | Third-party guides (vidIQ and others) disagree on the number; YouTube's Help page defines Intro but gives no target. Anecdotal. |
| MrBeast guide: "the first minute is when most people click off; re-engage at ~3 and ~6 min" | Leaked 2024 document, not confirmed as authentic. Practice, **C**. |
| "Open loops work because of the Zeigarnik effect" | Memory advantage not replicated (2025 meta-analysis); the urge to resume is real. See above. |

## Working with the lint

1. Draft the script yourself (premium tier: final Persian text is never delegated —
   `skills/meta/delegation-protocol.md`). Hook options can come from the hook lab
   (`scripts/fa_editorial.py hooks`: 12 types, each with its open loop and hook timing).
2. Run the lint; fix every 🔴; fix 🟡 unless you have a reason, and write the reason in
   the script stage summary.
3. With `--llm`, compare the drafted loops with what you intended. If the worker sees a
   loop you did not mean, the viewer may too.
4. Run the fact-check step on the final text before TTS.
5. Show the owner: the script, the lint summary, and what you changed.

Worked example (a draft, not approved): `docs/fa/narration/samsung_90s_draft.*` — the plain
text with loop markers, the schema-valid script artifact with per-section TTS styles,
`metadata.loops` and a digits caption version, and the before/after reports in
`docs/fa/narration/lint_reports.md`.

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
- MacGregor, L. J., Corley, M. & Donaldson, D. I. (2010). Listening to the sound of silence:
  Disfluent silent pauses in speech have consequences for listeners. *Neuropsychologia*
  48(14), 3982–3992.
- Moreno, R. & Mayer, R. E. (2000). Engaging students in active learning: The case for
  personalized multimedia messages. *Journal of Educational Psychology* 92, 724–733.
- Schindler, R. M. & Yalch, R. F. (2006). It Seems Factual, But Is It? Effects of Using Sharp
  versus Round Numbers in Advertising Claims. *Advances in Consumer Research* 33, 586–590.
- YouTube Help — Add end screens to videos (last 5–20 s): https://support.google.com/youtube/answer/6388789
- Shorts views count every start or replay from 31 March 2025:
  https://techcrunch.com/2025/03/26/youtube-is-changing-how-youtube-shorts-views-are-counted
- Facebook/Nielsen first-3-seconds figures (ads): https://www.marketingdive.com/news/facebook-offers-tips-for-converting-tv-ads-to-mobile/448510/
- Goldfish attention-span myth: https://www.warc.com/newsandopinion/opinion/the_goldfish_myth/2806
- Gemini speech generation (style prompts, inline tags): https://ai.google.dev/gemini-api/docs/speech-generation
  (403 from Iran; the project's tested notes are in `skills/creative/persian-localization.md`).
- Spoken vs written Persian (diglossia): https://sites.la.utexas.edu/persian_online_resources/language-specific-grammar/diglossia/
