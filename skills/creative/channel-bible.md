# Channel bible

A Persian channel keeps its memory in a channel folder: tone, voices,
characters, pronunciation, terms, the owner's edits and one retro per video.
Every stage of a production for that channel reads it, and some stages write
back to it. Code: `lib/channel_bible.py`. Template: `channels/_template/`.

## Where it lives

- `OPENMONTAGE_CHANNELS_DIR` (in `.env`) points at the live channels. On the
  owner's laptop that is `D:/project/videio v/channels`, a private backup
  repo, because the fork is public. Without the variable, `<repo>/channels`
  is used; `.gitignore` keeps everything there except `_template` out of git.
- New channel: `python -m lib.channel_bible create --channel <slug>`.
- The brief names the channel (`channel: fa-main`). If it does not, ask.

| File | Read at | Written at |
|---|---|---|
| `channel.md` | research, proposal, script, every reviewer | owner only |
| `voices.yaml` | script (pace), assets (TTS), dub mapping | after the owner picks a voice |
| `characters/<name>/` | scene plan, assets (`fa_image` `set_style`) | when the owner approves a character |
| `lexicon.tsv` | assets: every TTS call | owner approves suggestions |
| `lexicon_suggestions.tsv` | before the voice sample | after every round-trip check |
| `glossary.tsv` | script, translation drafts (pass to the worker) | owner or agent, with the owner's OK |
| `examples/<project>.jsonl` | script drafts (latest 10 as style examples) | every owner edit |
| `retros/<date>-<project>.md` | proposal of the next video | after publish |

## Rules per stage

**Proposal / script.** Read `channel.md` first; it overrides generic tone
advice. Write numbers as words for the voice and keep a digits version for
captions (`lib/fa_text.spell_numbers` does the conversion). Budget lines with
the narrator's `cps` from `voices.yaml`: seconds ≈ spoken letters / cps.

**Voice.** Use `voices.yaml` → `roles.narrator` (voice, style, models,
providers). While `status` is `pending_owner_pick`, say so and use the listed
voice only for samples. Pass `channel: <slug>` to `tts_selector`: it applies
`lexicon.tsv` to the text (and to every `turn`) before synthesis and reports
`lexicon_applied`. Captions keep the script spelling.

**Round-trip.** After a voice sample, transcribe it (`avalai_stt`, or
`scripts/fa_voice_audition.py` for auditions) and compare with
`lib/fa_text.round_trip`. Feed `word_diff` pairs to
`lib.channel_bible.suggest_lexicon`; a word misheard twice becomes
`pending`. Show pending rows to the owner with a proposed respelling
(diacritic, split word, synonym); only `approve_lexicon` (the owner's call)
moves a row into `lexicon.tsv`. Spoken/written variants («جوون»/«جوان») are
folded before comparing and are not suggestions.

A miss can be the voice changing the words, not only mishearing (the
audition heard «سالی از اون روزها» for «سال هزار و نهصد و»). When the
round-trip on a final clip is under 0.97, listen to it before using it.

**Owner edits.** Whenever the owner changes a script line, title or caption,
call `record_edit(channel, project, stage, before, after, note)`. Before a
worker drafts script text, give it the latest examples from
`examples/*.jsonl` and the glossary.

**Retro.** After publish, copy `retros/TEMPLATE.md` to `retro_path(...)`
and fill it: planned vs actual cost (from `events.jsonl`), owner steps, what
broke, and what goes into `channel.md`, the lexicon or `voices.yaml` next
time. Propose those changes; the owner applies them.
