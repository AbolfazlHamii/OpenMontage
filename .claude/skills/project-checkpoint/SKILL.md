---
name: project-checkpoint
description: Keep a resumable checkpoint of long video work (renders, builds, TTS, image batches) so that after a crash, a session restart, a lost connection or "ادامه بده" nothing finished is redone. Use at the start of any resumed video task, before and after every long step, and whenever the owner asks where things stand or says work was lost.
---

# Project checkpoint: never redo finished work

Long steps in this repo (After Effects builds, aerender, Blender renders, TTS, image batches, mixes) get
interrupted: the session restarts, After Effects crashes, the connection drops. The rule: **every long
step leaves a file that says it is done, and every runner skips work whose output is already there and
newer than its inputs.**

## 1. STATE.md in the project folder

Each project has `STATE.md` next to its README. Read it first when resuming; rewrite it after every
milestone (it is short, overwrite it, do not append forever):

```
# State - <project> - <YYYY-MM-DD HH:MM>
Goal now: <one line>
Done (outputs that exist and are current):
- <artifact path> - <what it is> - <date>
In progress:
- <what> - started <time> - how to see progress: <log path / command>
Next steps, in order (exact commands):
1. ...
Decisions the owner made (do not ask again):
- ...
Known problems / gotchas found this round:
- ...
```

Keep paths exact and commands copy-pasteable. Decisions and owner feedback go here too, so a new
session does not re-ask or re-break them.

## 2. Runners that resume

- Make a runner skip an item when its output exists and is newer than every input
  (`[ out -nt in ]` in bash, `Path.stat().st_mtime` in Python). Then "run it again" is always safe.
- Write outputs to a temp name and rename when complete (`x.part.mp4` -> `x.mp4`), so a half-written
  file never counts as done. Delete leftovers of the temp name on start.
- One log per item (`renders/parts/p3.log`), so you can tell which item died and why.
- Batches of paid calls (TTS, images): skip existing files; never regenerate what exists unless asked.
- After a crash, kill leftovers first (`aerender.exe`, `AfterFX.com`, orphaned bash loops from earlier
  runs - `ps -ef | grep render`), check free disk (`df -h`), then rerun the runner.

## 3. Before a long step

- Note in STATE.md what is about to run, the expected time and the log path.
- Estimate time from a short measured sample (e.g. 90 frames) instead of guessing, and tell the owner
  the finish time.
- Do not run two heavy renderers at once on this laptop (After Effects + Blender together crashed
  After Effects and made frames ~20x slower).

## 4. When resuming ("ادامه بده", new session, after a crash)

1. Read `STATE.md`, then check reality: which outputs exist, which processes run, last lines of logs.
2. Fix STATE.md if it is wrong, then continue from the first step that is not done.
3. Tell the owner in one or two lines what was already done and what is left, with a time estimate.
