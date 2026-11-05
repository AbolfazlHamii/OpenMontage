"""Edit-craft checks for the render QA gate: rhythm, hook, SFX, captions, music.

They read an edit plan (the `edit_pass.json` that scripts/fa_edit_pass.py
writes, or one written by hand for an older render) instead of guessing
from pixels: cut and punch-in times, speech segments, caption groups with
word times, SFX cues, beat grid and the music volume curve.

    {"duration": 15, "cuts": [...], "interrupts": [...], "speech": [[a, b]],
     "captions": [{"start", "end", "words": [{"start", "end"}]}],
     "sfx": [{"at", "start", "duration", "bed"}], "beats": [...],
     "music_keyframes": [[t, gain]], "music_end": 14.9, "end_screen": null}

Thresholds and where they come from are in skills/creative/editing-craft.md.
"""

from __future__ import annotations

from typing import Any, Optional

from lib.fa_render_qa import Check
from tools.audio.beat_detect import beat_ratio, nearest
from tools.audio.music_duck import ducking_depth_db


def _changes(plan: dict) -> list[float]:
    return sorted(set(plan.get("cuts", [])) | set(plan.get("interrupts", [])))


def _accents(plan: dict) -> list[dict]:
    return [c for c in plan.get("sfx", []) if not c.get("bed")]


def check_cut_rhythm(plan: dict, card: Optional[dict] = None) -> Check:
    duration = float(plan["duration"])
    changes = [t for t in _changes(plan) if 0 < t < duration]
    bounds = [0.0, *changes, duration]
    holds = [b - a for a, b in zip(bounds, bounds[1:])]
    asl = duration / (len(changes) + 1)
    ev = {"visual_changes": len(changes), "asl_seconds": round(asl, 2),
          "changes_per_minute": round(len(changes) / (duration / 60), 1), "longest_hold": round(max(holds), 2)}
    if not card:
        return Check("cut_rhythm", "pass" if max(holds) <= 6 else "warn",
                     f"ASL {asl:.1f} s, longest hold {max(holds):.1f} s (no style card given)", ev)
    sections = card["pacing"]["sections"]
    section = "hook" if duration <= sections["hook"].get("duration_seconds", 15) + 1 else "body"
    target = sections[section]["asl_seconds"]
    limit = card["pattern_interrupt_seconds"]["max"]
    ev.update({"card": card["name"], "section": section, "card_asl": target, "card_max_hold": limit})
    problems = []
    if abs(asl - target) / target > 0.35:
        problems.append(f"ASL {asl:.1f} s vs card {target} s")
    if max(holds) > limit:
        problems.append(f"a {max(holds):.1f} s stretch with no visual change (card max {limit} s)")
    if problems:
        return Check("cut_rhythm", "warn", "; ".join(problems), ev)
    return Check("cut_rhythm", "pass", f"ASL {asl:.1f} s (card {target} s), longest hold {max(holds):.1f} s", ev)


def check_hook(plan: dict, hook: float = 5.0) -> Check:
    changes = [t for t in _changes(plan) if 0 < t < hook]
    speech = plan.get("speech") or []
    captions = plan.get("captions") or []
    accents = [c for c in _accents(plan) if c["at"] < hook]
    ev = {"changes": changes, "sfx": [c["at"] for c in accents]}
    problems = []
    if len(changes) < 2:
        problems.append(f"{len(changes)} visual change(s) in the first {hook:g} s (want 2+)")
    if speech and captions:
        lag = captions[0]["start"] - speech[0][0]
        ev["caption_lag"] = round(lag, 2)
        if lag > 0.3:
            problems.append(f"first caption {lag:.2f} s after the voice starts")
    if not accents:
        problems.append(f"no sound accent in the first {hook:g} s")
    if problems:
        return Check("hook_edit", "warn", "; ".join(problems), ev)
    return Check("hook_edit", "pass", f"{len(changes)} visual changes and {len(accents)} sound accent(s) "
                 f"in the first {hook:g} s", ev)


def check_sfx_density(plan: dict, max_per_minute: float = 36.0, min_per_minute: float = 6.0,
                      min_gap: float = 0.25) -> Check:
    duration = float(plan["duration"])
    accents = sorted(_accents(plan), key=lambda c: c["at"])
    rate = len(accents) / (duration / 60)
    gaps = [b["at"] - a["at"] for a, b in zip(accents, accents[1:])]
    ev = {"accents": len(accents), "beds": len(plan.get("sfx", [])) - len(accents),
          "per_minute": round(rate, 1), "closest_gap": round(min(gaps), 2) if gaps else None}
    if not accents:
        return Check("sfx_density", "warn", "no sound effects: cuts and text land in silence", ev)
    problems = []
    if rate > max_per_minute:
        problems.append(f"{rate:.0f}/min (max {max_per_minute:g})")
    if rate < min_per_minute:
        problems.append(f"{rate:.0f}/min (min {min_per_minute:g})")
    if gaps and min(gaps) < min_gap:
        problems.append(f"two accents {min(gaps):.2f} s apart (min {min_gap:g})")
    if problems:
        return Check("sfx_density", "warn", "; ".join(problems), ev)
    return Check("sfx_density", "pass", f"{rate:.0f} accents/min, closest {min(gaps) if gaps else 0:.2f} s apart", ev)


def check_cut_accents(plan: dict, window: float = 0.12) -> Check:
    cuts = plan.get("cuts", [])
    peaks = [c["at"] for c in _accents(plan)]
    if not cuts:
        return Check("cut_accents", "skipped", "no cuts in the plan", {})
    hit = [c for c in cuts if peaks and abs(nearest(peaks, c) - c) <= window]
    share = len(hit) / len(cuts)
    ev = {"cuts": cuts, "with_sound": hit, "share": round(share, 2)}
    status = "pass" if share >= 0.5 else "warn"
    return Check("cut_accents", status, f"{len(hit)}/{len(cuts)} cuts carry a sound accent", ev)


def check_caption_onscreen(plan: dict, min_on: float = 0.8, max_on: float = 7.0, flicker: float = 0.15) -> Check:
    groups = plan.get("captions") or []
    if not groups:
        return Check("caption_onscreen", "skipped", "no caption groups in the plan", {})
    short = [i for i, g in enumerate(groups) if g["end"] - g["start"] < min_on]
    long = [i for i, g in enumerate(groups) if g["end"] - g["start"] > max_on]
    blinks = [i for i, (a, b) in enumerate(zip(groups, groups[1:])) if 0.001 < b["start"] - a["end"] < flicker]
    speech = plan.get("speech") or []
    words = [w for g in groups for w in g.get("words", [])]
    stray = [w for w in words if speech and not any(a - 0.15 <= w["start"] <= b + 0.15 for a, b in speech)]
    ev = {"groups": len(groups), "too_short": short, "too_long": long, "blinks": blinks,
          "words": len(words), "words_outside_speech": len(stray)}
    problems = []
    if short:
        problems.append(f"{len(short)} group(s) under {min_on:g} s")
    if long:
        problems.append(f"{len(long)} group(s) over {max_on:g} s")
    if blinks:
        problems.append(f"{len(blinks)} blink(s): caption off for under {flicker:g} s between groups")
    if stray:
        problems.append(f"{len(stray)} word(s) highlighted outside speech")
    if problems:
        return Check("caption_onscreen", "warn", "; ".join(problems), ev)
    mode = "word-timed" if words else "group-timed"
    return Check("caption_onscreen", "pass", f"{len(groups)} {mode} groups, each {min_on:g}-{max_on:g} s, no blinks", ev)


def check_beat_sync(plan: dict, card: Optional[dict] = None, tolerance: float = 0.08) -> Check:
    beats = plan.get("beats") or []
    changes = [t for t in _changes(plan) if 0 < t < plan["duration"]]
    if not beats or not changes:
        return Check("beat_sync", "skipped", "no beat grid or no cuts", {})
    ratio = beat_ratio(changes, beats, tolerance)
    period = (beats[-1] - beats[0]) / max(len(beats) - 1, 1)
    chance = round(min(1.0, 2 * tolerance / period), 2) if period else None
    want = (card or {}).get("pacing", {}).get("beat_sync_ratio", 0.3)
    ev = {"ratio": ratio, "chance": chance, "card": want, "tolerance": tolerance}
    # Below chance the cuts ignore the music, whatever the card asks for.
    status = "pass" if ratio >= want * 0.8 and (chance is None or ratio > chance) else "warn"
    return Check("beat_sync", status, f"{ratio:.0%} of visual changes on a beat (chance {chance:.0%}, card {want:.0%})", ev)


def check_music_ducking(plan: dict, min_db: float = 3.0) -> Check:
    keys = plan.get("music_keyframes") or []
    speech = plan.get("speech") or []
    if not keys:
        return Check("music_ducking", "skipped", "no music curve in the plan", {})
    depth = ducking_depth_db(keys, speech, float(plan["duration"]))
    ev = {"depth_db": depth}
    if depth is None:
        return Check("music_ducking", "skipped", "no pauses to compare with speech", ev)
    if depth < min_db:
        return Check("music_ducking", "warn", f"bed only {depth:.1f} dB louder in pauses than under the voice "
                     f"(flat bed fights the voice; duck {min_db:g}+ dB)", ev)
    return Check("music_ducking", "pass", f"bed rises {depth:.1f} dB in pauses, ducks under the voice", ev)


def check_music_ending(plan: dict, tolerance: float = 0.1) -> Check:
    end, beats = plan.get("music_end"), plan.get("beats") or []
    if end is None or not beats:
        return Check("music_ending", "skipped", "no music end or beat grid in the plan", {})
    beat = nearest(beats, end)
    ev = {"music_end": end, "nearest_beat": beat}
    if abs(beat - end) <= tolerance:
        return Check("music_ending", "pass", f"music ends on a beat ({end:.2f} s)", ev)
    return Check("music_ending", "warn", f"music ends {end - beat:+.2f} s off the beat — cut or fade to a beat", ev)


def check_end_screen(plan: dict) -> Check:
    duration = float(plan["duration"])
    if duration < 60:
        return Check("end_screen", "skipped", "under 60 s: no end screen (loop the ending instead)", {})
    block = plan.get("end_screen")
    if not block:
        return Check("end_screen", "warn", "no end-screen block planned (YouTube allows 5-20 s at the end)", {})
    length = block["end"] - block["start"]
    ok = 5 <= length <= 20 and abs(block["end"] - duration) < 0.5
    return Check("end_screen", "pass" if ok else "warn",
                 f"end screen {length:.0f} s, ending {duration - block['end']:.1f} s before the end", block)


def edit_checks(plan: dict[str, Any], card: Optional[dict] = None) -> list[Check]:
    return [check_cut_rhythm(plan, card), check_hook(plan), check_sfx_density(plan), check_cut_accents(plan),
            check_caption_onscreen(plan), check_beat_sync(plan, card), check_music_ducking(plan),
            check_music_ending(plan), check_end_screen(plan)]


FA_NAMES = {
    "cut_rhythm": "ریتم برش‌ها", "hook_edit": "تدوین ۵ ثانیه اول", "sfx_density": "تراکم افکت صوتی",
    "cut_accents": "صدا روی برش‌ها", "caption_onscreen": "زمان نمایش زیرنویس", "beat_sync": "برش روی ضرب موسیقی",
    "music_ducking": "پایین آمدن موسیقی زیر صدا", "music_ending": "پایان موسیقی روی ضرب",
    "end_screen": "صفحه پایانی",
}
