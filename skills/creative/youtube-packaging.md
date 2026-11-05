# YouTube Packaging — titles, thumbnails, topics and publishing for the Persian channel

## When to Use

- Publish stage of any Persian video (explainer / animated-explainer,
  character-animation, documentary-montage): title, thumbnail, description,
  chapters, tags, upload settings. The checklist at the end is the stage's
  exit gate.
- Proposal stage: judging a topic before money is spent (topic rubric).
- Planning the channel: series, cadence, Shorts.

Out of scope here (other skills own them): the hook and narration
(`skills/creative/narration-craft.md`), the edit (`editing-tricks.md`), the
animation. Packaging only promises; the video has to keep the promise.

Tools:

| What | Where |
|---|---|
| Thumbnail builder (HTML/CSS → 1280×720 PNG/JPG, 3 variants, phone check) | `scripts/fa_thumbnail.py`, `lib/fa_thumbnail.py`, templates in `styles/thumbnails/fa/` |
| Title drafts (worker tier), title and topic rubrics, description/chapters/tags | `scripts/fa_packaging.py`, `lib/fa_packaging.py` |
| Packaging the export folder | `export_bundle` (publish capability) |

## Evidence levels

Every claim below carries one of these tags. Do not present a C or D claim
to the owner as a YouTube rule.

- **A** — YouTube's own Help Center, blog or Creator Insider.
- **B** — Reported by trade press from YouTube statements, or a sizeable
  public data study.
- **C** — Consistent advice from experienced creators/consultants;
  anecdotal.
- **D** — Our own reasoning for this channel; untested until our analytics
  say so.

## How recommendation works (what packaging is for)

- Signals YouTube lists (A, Help "How YouTube recommendations work"): watch
  history, search history, subscriptions, likes, dislikes, "Not interested",
  "Don't recommend channel", and satisfaction surveys. Home relies mostly on
  watch history; Up Next mostly on the video being watched.
- "Valued watch time" (A, YouTube blog "On YouTube's recommendation
  system"): survey ratings of 4–5 stars count; a click that ends in a
  disappointed viewer is worth little.
- Test & Compare picks the winner by **watch time share, not CTR** (A).
  YouTube's own A/B tool tells you what it optimises: clicks that turn into
  watching.
- Clickbait gets fewer recommendations because viewers leave early (A, CTR
  FAQ). Our rule: the title/thumbnail promise must be paid inside the first
  30 s and in full by the end (the narration skill's "answer at 40–80%").
- Shorts and long videos are recommended by separate systems (B, Creator
  Insider as reported). YouTube's stated position is that Shorts do not hurt
  long-form reach (B); Shorts viewers rarely become long-form viewers (C).

### What "a good CTR" means

- Half of all channels and videos sit between **2% and 10%** impressions CTR
  (A). New videos (< 1 week) and videos under 100 views swing wider (A).
- CTR falls as a video reaches wider audiences (Home, Suggested): a high
  CTR on few impressions is a loyal audience, not a better thumbnail (A).
- Compare CTR only within the same traffic source and the same age of
  video. Search CTR is higher than Browse; external traffic has none.
- What we watch instead of CTR alone: **impressions × CTR × average view
  duration** (watch time per impression). A thumbnail that adds 1 point of
  CTR and loses 20% of view duration is a loss.
- Do not check CTR in the first hours (A, CTR FAQ) and never delete and
  re-upload a video because day one was slow (C).

## Titles

### Patterns for "the history of X" (Persian examples)

| Pattern | Example | Why it works |
|---|---|---|
| Time-boxed whole story | «کل تاریخ سامسونگ در ۹۰ ثانیه» | Clear subject + a promise of efficiency; proven series format (C) |
| Origin twist (contrast) | «سامسونگ با ماهی خشک شروع شد» | The gap between "fish" and "phone" is the curiosity (C) |
| Single dramatic event | «روزی که سامسونگ ۱۵۰ هزار گوشی خودش رو آتیش زد» | A concrete scene; easy to draw as a thumbnail (C) |
| How-question | «سامسونگ چطور از یه ماهی‌فروشی غول شد؟» | Matches how people search («... چطور ... شد») (D) |
| Then → now | «از ماهی خشک تا گلکسی: داستان سامسونگ» | Two eras = the channel's time-coded palette (D) |

- One subject, named early. The first ~40 characters survive truncation on
  phones; put the brand there (C).
- Length: aim for 20–60 characters, hard limit 100 (A for the limit). One
  dataset finds titles of ≤ 30 characters get more views (B, 1of10); others
  find no effect, so do not over-fit. Past ~60 phones cut the end.
- Numbers: use them when the number *is* the story («۱۵۰ هزار گوشی»,
  «۹۰ ثانیه»), not as decoration (B: studies disagree on numbers in titles).
- Curiosity vs clarity: a new channel has no trust yet, so clarity wins —
  the viewer must know the topic from the title alone; the thumbnail adds the
  surprise (C).
- Title and thumbnail are **one message in two parts**: the thumbnail text
  must not repeat the title. Title = the subject and promise; thumbnail = the
  emotion or the twist (C).
- No ALL-CAPS-style shouting, no «!!!» or «؟؟», no promises the video does
  not keep (A on clickbait, C on punctuation).

### Persian specifics

- **Search words.** Persian viewers search «تاریخچه X», «داستان X»,
  «داستان موفقیت X», «X چطور ... شد», «بیوگرافی ...», «مستند ...», and the
  brand in Latin letters (Samsung) (D, from Persian site titles; verify with
  YouTube autocomplete before each video).
- **Register.** The channel narrates in spoken Tehrani. Titles may use a
  spoken verb («آتیش زد», «شد؟») but keep the searchable keyword in standard
  spelling («سامسونگ», «تاریخچه»). Never mix two registers in one title (D).
- **Digits.** Persian digits in the title («۹۰») look native; put the Latin
  form («90») and spelled form in tags/description (D).
- **Letters.** Never Arabic «ي»/«ك» in a title; ZWNJ where standard
  («می‌شه», «ماهی‌فروشی»). Put common misspellings and spacing variants in
  tags, which is exactly what tags are for (A: tags matter mainly for
  misspellings).
- **Bidi.** A Latin word at the start or end of a Persian title next to
  punctuation gets reordered on screen («Galaxy!» jumps sides). Keep Latin
  words in the middle or leave them to the description (D).
- The rubric in `lib/fa_packaging.score_title` checks all of the above
  mechanically. It does not judge taste; you do.

### Getting title options

1. `python scripts/fa_packaging.py titles --brief <brief.json> --out <dir>`
   sends the brief to the worker tier (task `title_tag_variants`) and scores
   every draft. Cost is printed and logged; it is cents.
2. The drafts are raw material. **You** pick, rewrite and finalise; a cheap
   model never delivers final Persian (`skills/meta/delegation-protocol.md`).
3. Present 5 reviewed options with the rubric score and one line of reasoning
   each; recommend one.

## Thumbnails

### Composition

- One focal point: one face/character, one object, one action. If you
  cannot describe the thumbnail in one sentence, it is two thumbnails (C).
- Faces and emotion: an expressive face is the most repeated advice in
  thumbnail design (C). For a cartoon channel the recurring character with a
  big, readable expression plays this role.
- Text: **at most 3–4 words** (C, the "3-word rule"), and it must add to the
  title, not repeat it. 2 words is better on a phone.
- Size: at 1280×720 the main text needs a font size of at least ~100 px so it
  is still ~12 px tall when the thumbnail is 160 px wide on a phone (D;
  checked automatically).
- Contrast: text on a solid panel or with a thick dark stroke; contrast
  ratio ≥ 4.5 between text and its backing (WCAG AA, checked). The whole
  thumbnail must also stand apart from both YouTube themes (white and
  near-black); avoid large pure-white or pure-black edges (C).
- Keep the **bottom-right corner clear** (duration badge) and the bottom
  edge (watch-progress bar) (A for the badge's existence; D for exact size:
  the builder masks ~20%×14% there).
- RTL eye path: Persian viewers read from the right, so the text block sits
  top-right and the subject left of centre (D).
- No Persian text inside AI images — ever. Text is HTML (Vazirmatn) laid over
  a text-free still. No exact brand logos in generated art (channel rule).
- File: 1280×720, under 2 MB (A). The builder writes a PNG master and a JPG
  for upload and fails if the JPG is over 2 MB.

### Channel brand consistency

- Same font family (Vazirmatn Black), same text corner, same accent
  (Samsung-like cobalt only for emphasis), same era stamp («۱۹۳۸») as in the
  video. Returning viewers should recognise the channel in a feed before they
  read it (C).
- Time-coded palette carries over: past = browns/creams, today = cold
  greys, cobalt only on the one thing that matters.

### The three templates (`styles/thumbnails/fa/`)

| Variant | Template | Use when |
|---|---|---|
| A | `punch` | Strong emotion or action in the still (bonfire, shock face). Zoomed crop + 2–3 huge words. |
| B | `era` | The twist is a date or an era contrast. Big era stamp + a short line. |
| C | `question` | The twist is an object (a dried fish). Ring highlight on the object + a short question. |

All three come from **one background still** and one short text set, so the
A/B test compares framing and words, not art budgets.

Spec fields per variant (`--spec`, see the script's docstring): `template`,
`headline` (`|` breaks the line), `kicker`, `year`, `focus` (point of the
still kept in view), `zoom`, `subject` (face/object text must not cover),
`ring` (question template), `side` (`right` default, `left` when the subject
is on the right). The builder fails a variant whose text covers the subject,
sits under the duration badge, overflows, or is < 12 px tall at 160 px wide.
Different stills for different variants = run the builder once per still and
pick across the sets (Samsung: `projects/samsung-history-fa/packaging/`).

### Phone check

`fa_thumbnail.py` writes `preview_phone.png`: every variant at 160, 246 and
360 px wide on light and dark backgrounds, next to the title. Look at it
before choosing. If the words are not readable at 160 px, the variant fails.

### Test & Compare (YouTube Studio)

- Up to 3 thumbnails, 3 titles, or 3 title+thumbnail pairs (A). Desktop
  Studio only, needs "advanced features" (A). Not for Shorts, made-for-kids,
  private or 18+ videos (A).
- Winner = highest **watch time share**; results are Winner / Performed the
  same / Inconclusive; a test runs a few days up to 2 weeks (A).
- Changing the title or thumbnail during a test stops it (A).
- Small channels: low impressions often end "inconclusive". Test big
  differences (different concept), not colour tweaks; test the thumbnail
  first, titles later (C).

## Topics

### What Persian viewers watch in this genre (D unless marked)

- Brands they touch daily: phones (Samsung ~46% of phones in Iran,
  StatCounter, in the research brief; Xiaomi, Apple), cars (Kia's Pride is
  Iran's own nostalgia), apps (Instagram, Telegram), games (PlayStation,
  Nintendo).
- Nostalgia is a strong pull for this audience (Nokia 1100/3310, Paykan,
  Pride) (C).
- Foreign brands carry less risk than Iranian state-linked companies;
  anything touching politics, religion, sanctions or living people's legal
  cases is a risk the owner decides on.
- The audience is partly in Iran (behind filtering, via VPN) and partly in
  the diaspora; analytics geography is distorted by VPN exits (C).

### Evergreen vs trending

- "History of X" is evergreen: search and Suggested keep bringing viewers
  for years (C). Use a news peg (launch, record valuation, scandal) to time
  the upload, not to pick the topic.

### Series

- One format, one thumbnail family, one playlist: «تاریخ برندها در ۹۰ ثانیه».
  Series build returning viewers and session time; playlists autoplay the next
  episode (C).
- Pair episodes that answer each other (Samsung → LG, PlayStation → Nintendo)
  so the end screen has an obvious next video (D).

### Judge a topic before spending money (rubric: `score_topic`)

| Criterion | Weight | Cheap evidence |
|---|---|---|
| Demand | 25 | YouTube autocomplete in Persian; Persian videos on the topic whose views beat their channel's size (outliers); a Community poll |
| Twist | 20 | Can you say the surprise in one sentence? («با ماهی خشک شروع شد») |
| Familiarity | 15 | Do Persian viewers own/use/remember it? |
| Visual | 15 | Can you draw the thumbnail in 3 words + 1 image? Distinct eras? |
| Series fit | 10 | Does it pair with another episode? |
| Evergreen | 10 | Will it be searched in two years? |
| Cost | 5 | Number of distinct scenes × image cost |
| Risk | −30 max | Politics, religion, sanctions, defamation, living private people |

Score ≥ 70: make it. 55–69: make it if the owner likes it. < 55: drop or find
a better angle.

## Upload strategy

- **Upload private first, then schedule.** Studio's Checks (copyright and
  ad-suitability) run before publishing (A); fix claims before anyone sees
  the video.
- **Frequency**: quality per video beats a fixed schedule for a new channel
  (C; YouTube staff repeat this in Creator Insider, not verified here). Pick a
  cadence the budget can keep (one video a week or every two weeks) and keep
  it (C).
- **Timing**: time of day matters little in the long run (B, Creator
  Insider as reported). Until Studio's "When your viewers are on YouTube"
  has data: publish ~19:00–21:00 Tehran time (UTC+3:30, no DST), Thursday or
  Friday evenings are the Iranian weekend; that is ~17:30 in Europe and
  ~midday on the US east coast for the diaspora (D).
- **First 24 hours**: the video is shown to likely viewers first; slow days
  are normal and evergreen videos can grow later (C). Reply to comments early;
  pin one comment with a question («شما الان چه گوشی‌ای دارید؟») (C).
- **Shorts from the long video**: cut 1–2 vertical moments (the twist, the
  dramatic event) as Shorts of 30–60 s (Shorts may run up to 3 min, A), each
  with the "related video" link to the full video (B for the feature;
  click-through is low, C). They do not hurt
  the long video (B) but bring a different audience (C).
- **Instagram Reels**: same vertical cut; the first 1–2 seconds are the
  packaging (there is no thumbnail in the feed); the cover shows on the
  profile grid; burned-in captions because many watch muted (C).
- **End screens**: last 5–20 s, video ≥ 25 s, up to 4 elements (A). Keep
  the outro itself ≤ 8 s (narration-craft: viewers leave there) and let a
  5–8 s end screen sit over the last beat; the edit leaves the left/top
  third calm for one video + subscribe (D).
- **Playlists**: one per series, in story order (C).
- **Community posts / polls**: use polls to pick the next topic — free topic
  research (D). Availability depends on the channel.
- **Hype** (fan boosts for channels < 500k subs): only in some countries;
  check availability for this channel's audience (B).

## Description, chapters, tags, captions

- The title, thumbnail and description matter more for discovery than tags
  (A). Tags matter mainly for misspellings (A) — for Persian that means
  spelling variants and the Latin brand name.
- **Description**: first two lines = the hook + the keyword phrase
  («تاریخچه سامسونگ»); they show in search. Then chapters, sources (the
  research brief's links: trust), music credit, series playlist link (C).
- **Hashtags**: 3 at most are shown above the title; more than 60 and all
  are ignored (A).
- **Chapters**: first at 0:00, at least 3, each ≥ 10 s (A, as YouTube words
  it). `build_chapters` enforces this and merges short sections.
- **Captions**: upload the Persian SRT even though captions are burned in
  (accessibility, translations). An English subtitle track — and later an
  English audio track through the dub tools — widens reach; YouTube reports
  >25% of watch time from non-primary languages for creators who added
  audio tracks (B). The SEO weight of captions is not documented: treat it as
  small (D).
- **Altered content**: cartoon/animation is exempt from the AI disclosure
  (A). Tick "Yes" only if a video ever shows realistic AI depictions of real
  people or events.

## Monetization basics (decide early)

- YPP thresholds (A; re-check the Help page when applying): 1,000
  subscribers + 4,000 public watch hours in 12 months, or 1,000 + 10M Shorts
  views in 90 days; a lower tier (500 subs, 3 uploads in 90 days, 3,000 hours
  or 3M Shorts views) unlocks fan funding only.
- **Iran is not on the YPP country list** (A). Monetization needs a channel
  and an AdSense payee in an eligible country, with real identity and
  residence. Using someone else's identity breaks AdSense terms. This is
  the owner's legal decision, not an agent's.
- Revenue from viewers inside Iran is low: no Iranian advertisers because of
  sanctions (C, Persian creators' reports).
- **Inauthentic content** (A, July 2025 wording): mass-produced or
  template-repetitive videos lose monetization. An AI-assisted channel must
  show clear human editorial work: researched sources, the owner's script
  edits (kept in the channel bible), varied structure per video.
- **Content ID and stock music**: "royalty-free" tracks can still be claimed
  when a contributor registers them (C, reported for Pixabay). Keep the
  licence copy next to the track (`assets/music/LICENSE.md`), upload private
  first, dispute with the licence if claimed. Never use music from reference
  videos.

## Process (publish stage)

1. Read the channel bible (`channel.md`) and this skill.
2. Titles: run `scripts/fa_packaging.py titles`, pick and rewrite 5, score
   them, recommend one.
3. Thumbnails: pick the background still with the strongest single emotion
   or object; write 2–3 words that complete (not repeat) the title; run
   `scripts/fa_thumbnail.py`; **look at the PNGs and `preview_phone.png`**.
4. Description, chapters, tags: `scripts/fa_packaging.py describe` from the
   script + scene plan; review every Persian line yourself.
5. Hand everything to `export_bundle`.
6. Self-Evaluate with the checklist below; anything unchecked goes into the
   publish summary as an open item.

## Publish checklist

- [ ] Title: subject named in the first ~40 characters, 20–60 characters,
      no «ي/ك», correct ZWNJ, no Latin word at an edge, rubric ≥ 70.
- [ ] Title promise paid in the first 30 s of the video.
- [ ] Thumbnail text ≤ 4 words, does not repeat the title, readable at
      160 px (phone preview looked at), contrast ≥ 4.5.
- [ ] Bottom-right corner clear; no Persian text inside the AI still; no
      exact logos.
- [ ] 3 thumbnail variants ready for Test & Compare (A = default).
- [ ] JPG ≤ 2 MB, 1280×720.
- [ ] Description: hook + keyword in the first two lines, chapters, sources,
      music licence line, ≤ 3 hashtags.
- [ ] Chapters valid (0:00 first, ≥ 3, each ≥ 10 s).
- [ ] Tags: brand in Persian + Latin, spelling variants, series name.
- [ ] Persian SRT attached; altered-content question answered.
- [ ] Upload private → Checks clean (copyright) → schedule.
- [ ] End screen: 1 video (series next) + subscribe; playlist set.
- [ ] Shorts cut planned with the related-video link.
- [ ] Pinned comment written.

## Sources

- YouTube Help — How YouTube recommendations work:
  https://support.google.com/youtube/answer/16089387
- YouTube Help — Impressions and CTR FAQ:
  https://support.google.com/youtube/answer/7628154
- YouTube Help — Test & compare thumbnails and titles:
  https://support.google.com/youtube/answer/13861714
- YouTube Help — Add tags: https://support.google.com/youtube/answer/146402
- YouTube Help — Disclosing altered or synthetic content:
  https://support.google.com/youtube/answer/14328491
- YouTube Help — YPP availability: https://support.google.com/youtube/answer/13429240
- YouTube blog — On YouTube's recommendation system:
  https://blog.youtube/inside-youtube/on-youtubes-recommendation-system/
- Tubefilter — title testing in Test & compare (Jul 2025):
  https://www.tubefilter.com/2025/07/16/youtube-feature-test-and-compare-titles-thumbnails/
- Search Engine Journal — Shorts algorithm Q&A:
  https://www.searchenginejournal.com/youtube-shorts-algorithm-explained-in-qa-format/
- Search Engine Land — Shorts → long-form links:
  https://searchengineland.com/youtube-enables-linking-shorts-long-form-videos-430655
- Search Engine Land — YouTube on when to post:
  https://searchengineland.com/youtube-issues-guidance-on-when-to-post-content-for-maximum-reach-438774
- Plagiarism Today — "inauthentic content" (Jul 2025):
  https://www.plagiarismtoday.com/2025/07/08/youtube-targets-inauthentic-content/
- TechCrunch — multi-language audio for all creators (Sep 2025):
  https://techcrunch.com/2025/09/10/youtubes-multi-language-audio-feature-for-dubbing-videos-rolls-out-to-all-creators/
- 1of10 — title data study (B, one dataset):
  https://1of10.com/blog/what-actually-makes-a-youtube-video-go-viral-in-2025
- Tubefilter — Hype goes global (Aug 2025):
  https://www.tubefilter.com/2025/08/26/youtube-hype-feature-launches-united-states-global/
