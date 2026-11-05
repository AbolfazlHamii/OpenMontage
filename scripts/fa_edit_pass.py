"""Apply the edit pass to a HyperFrames workspace from its edit_plan.json.

    python scripts/fa_edit_pass.py projects/<id>/hyperframes

Reads `<workspace>/edit_plan.json` (format in skills/creative/editing-craft.md),
then, all local and free:
1. speech segments of each narration clip (silencedetect)
2. word-timed caption groups (word_captions, from the whisper word JSONs,
   starts snapped to the word attacks in the narration audio)
3. beat grid of the music bed, mapped onto the timeline (beat_detect);
   a music clip with `"align_downbeat": true` starts on a downbeat
4. a snap report: each cut's nearest beat, and whether it fits its pause
5. the music volume curve (music_duck) as GSAP volume tweens
6. SFX cues (sfx_placer); the files used are copied to assets/sfx/

and rewrites the blocks between these markers in index.html:
    <!-- edit-pass:captions --> ... <!-- /edit-pass:captions -->
    <!-- edit-pass:audio --> ... <!-- /edit-pass:audio -->
    // edit-pass:music ... // /edit-pass:music
Everything it decided goes to `<workspace>/edit_pass.json`, which
scripts/fa_render_qa.py takes as --edit-plan.
"""

from __future__ import annotations

import argparse
import json
import re
import shutil
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO))

from tools.audio.beat_detect import analyze, nearest, snap_to_beats  # noqa: E402
from tools.audio.music_duck import duck_keyframes, gsap_lines, level_at, speech_segments  # noqa: E402
from tools.audio.sfx_placer import audio_tags, load_library, plan_cues  # noqa: E402
from tools.subtitle.word_captions import audio_onsets, build_groups, caption_cues, render_html  # noqa: E402


def replace_block(text: str, name: str, body: str, js: bool = False) -> str:
    if js:
        pattern = re.compile(rf"(// edit-pass:{name}\n)(.*?)([ \t]*// /edit-pass:{name})", re.S)
    else:
        pattern = re.compile(rf"(<!-- edit-pass:{name} -->\n)(.*?)([ \t]*<!-- /edit-pass:{name} -->)", re.S)
    match = pattern.search(text)
    if not match:
        raise ValueError(f"marker edit-pass:{name} not found in index.html")
    indent = re.match(r"[ \t]*", match.group(3)).group(0)
    lines = "".join(f"{indent}{line}\n" for line in body.splitlines())
    return text[:match.start()] + match.group(1) + lines + match.group(3) + text[match.end():]


def pause_window(t: float, speech: list) -> tuple[float, float]:
    """The silence a cut sits in, or a ±60 ms window when it is inside speech."""
    prev_end = max((b for a, b in speech if b <= t), default=0.0)
    next_start = min((a for a, b in speech if a >= t), default=t + 10)
    if any(a < t < b for a, b in speech):
        return (t - 0.06, t + 0.06)
    return (prev_end, next_start)


def slice_keys(keys: list, a: float, b: float) -> list:
    inside = [(t, v) for t, v in keys if a < t < b]
    return [(a, level_at(keys, a)), *inside, (b, level_at(keys, b))]


def run(workspace: Path) -> dict:
    plan = json.loads((workspace / "edit_plan.json").read_text(encoding="utf-8"))
    duration = float(plan["duration"])

    clips, speech = {}, []
    for vo in plan["narration"]:
        sp = speech_segments(workspace / vo["src"], offset=float(vo["start"]))
        speech += sp
        words = json.loads((workspace / vo["words"]).read_text(encoding="utf-8"))
        clips[vo["id"]] = {"start": vo["start"], "words": words.get("words", words), "speech": sp,
                           "onsets": audio_onsets(workspace / vo["src"], float(vo["start"]))}
    speech.sort()
    groups = build_groups(plan["captions"], clips, duration)

    music = plan["music"]
    grid = analyze(workspace / music["src"], duration=music.get("analyze_seconds", duration + 30))
    beats: list[float] = []
    music_tags = []
    prev = None
    for clip in music["clips"]:
        length = clip["end"] - clip["start"]
        if clip.get("align_downbeat"):
            # Re-enter on the downbeat closest to where the music would be had it kept playing.
            want = prev["media_start"] + clip["start"] - prev["start"] if prev else 0.0
            clip["media_start"] = nearest(grid["downbeats"], want)
        media = float(clip.setdefault("media_start", 0.0))
        beats += [round(b - media + clip["start"], 3) for b in grid["beats"] if media <= b <= media + length]
        music_tags.append(f'<audio id="{clip["id"]}" src="{music["src"]}" data-start="{clip["start"]:g}" '
                          f'data-duration="{length:g}" data-media-start="{media:g}" '
                          f'data-track-index="{clip["track"]}" data-volume="1"></audio>')  # the volume tweens carry the level
        prev = clip
    beats.sort()

    cut_times = [c["at"] for c in plan.get("cuts", [])]
    snaps = snap_to_beats(cut_times, beats, float(plan.get("beat_tolerance", 0.1)),
                          [pause_window(t, speech) for t in cut_times])

    keys = duck_keyframes(speech, duration, under=music.get("under", 0.14), gaps=music.get("gaps", 0.24),
                          events=music.get("events", []))
    music_js = []
    for clip in music["clips"]:
        music_js += gsap_lines(slice_keys(keys, clip["start"], clip["end"]), f'#{clip["id"]}')
    # When the curve ends silent, the music stops where it last fell to zero.
    music_end = max(c["end"] for c in music["clips"])
    falls = [t1 for (t0, v0), (t1, v1) in zip(keys, keys[1:]) if v0 > 0.005 >= v1]
    if falls and keys[-1][1] <= 0.005:
        music_end = min(music_end, falls[-1])

    library_dir = (workspace / plan["sfx_library"]).resolve()
    library = load_library(library_dir)
    events = [{"at": c["at"], "sfx": c["sfx"], "kind": "cut"} for c in plan.get("cuts", []) if c.get("sfx")]
    events += [{**m, "kind": "mark"} for m in plan.get("marks", [])]
    if plan.get("emphasis_sfx"):
        for g in groups:
            for k, w in enumerate(g["words"]):
                if w["style"] != "plain" and (k == 0 or g["words"][k - 1]["style"] != w["style"]):
                    events.append({"at": w["start"], "sfx": plan["emphasis_sfx"], "kind": "emphasis"})
    sfx = plan_cues(events, library, speech=speech, duration=duration,
                    max_per_minute=float(plan.get("sfx_max_per_minute", 36)))
    (workspace / "assets" / "sfx").mkdir(parents=True, exist_ok=True)
    for cue in sfx["cues"]:
        shutil.copy2(library_dir / cue["file"], workspace / "assets" / "sfx" / cue["file"])
    shutil.copy2(library_dir / "LICENSE.md", workspace / "assets" / "sfx" / "LICENSE.md")

    index = workspace / "index.html"
    text = index.read_text(encoding="utf-8")
    text = replace_block(text, "captions", render_html(groups))
    text = replace_block(text, "audio", "\n".join(music_tags + [audio_tags(sfx["cues"])]))
    text = replace_block(text, "music", "\n".join(music_js), js=True)
    index.write_text(text, encoding="utf-8", newline="\n")

    result = {
        "duration": duration, "card": plan.get("card"),
        "cuts": [s["time"] for s in snaps], "interrupts": [i["at"] for i in plan.get("interrupts", [])],
        "speech": speech, "captions": groups, "caption_cues": caption_cues(groups),
        "caption_layout": plan.get("caption_layout"),
        "sfx": sfx["cues"], "sfx_dropped": sfx["dropped"],
        "bpm": grid["bpm"], "beats": beats, "snap_report": snaps,
        "music_clips": music["clips"], "music_keyframes": keys, "music_end": music_end,
        "end_screen": plan.get("end_screen"),
    }
    (workspace / "edit_pass.json").write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
    return result


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("workspace")
    args = parser.parse_args(argv)
    r = run(Path(args.workspace))
    out = [f"{len(r['captions'])} caption groups, {sum(len(g['words']) for g in r['captions'])} words",
           f"music {r['bpm']} BPM, ends {r['music_end']} s; clips "
           + ", ".join(f"{c['id']}@{c['start']} from {c.get('media_start', 0)}" for c in r["music_clips"]),
           f"{len(r['sfx'])} SFX cues, {len(r['sfx_dropped'])} dropped"]
    for s in r["snap_report"]:
        mark = "on beat" if s["on_beat"] else f"nearest beat {s['nearest_beat']}"
        out.append(f"  cut {s['time']}: {mark}" + (f" (snap {s['delta']:+.3f})" if s["delta"] else ""))
    for d in r["sfx_dropped"]:
        out.append(f"  dropped {d.get('sfx')} at {d.get('at')}: {d['reason']}")
    sys.stdout.buffer.write(("\n".join(out) + "\n").encode("utf-8"))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
