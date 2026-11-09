"""A second-language audio track for a finished manual-images video.

YouTube takes extra audio tracks per language (multi-language audio). The
picture stays as rendered, so the new narration has to land where the old one
did: each scene's line starts at the Persian line's start and ends before the
next scene's line begins.

    manual_images/narration_<lang>.json   {"language", "voice": {...}, "scenes": {id: text}}

`synth` voices it with the same voice groups as the Persian take (one voice
across a group, split back by transcript). `fit` measures every line against
its window; a line that needs more than MAX_TEMPO speed-up must be rewritten
shorter. `mix` lays the lines over the video's own music and sound effects
(same sections, fades and cues as the render) and brings the result to the
render's loudness.
"""

from __future__ import annotations

import json
import math
import re
import shutil
import subprocess
import textwrap
from pathlib import Path
from typing import Optional

from lib import fa_manual_images as mi

MAX_TEMPO = 1.12     # faster than this sounds rushed
LINE_GAP = 0.12      # silence kept before the next scene's line
END_FADE = 0.8       # the render fades the music out over this
RATE = 48000


def narration_path(project: Path, language: str) -> Path:
    return mi.root(project) / f"narration_{language}.json"


def shotlist_for(project: Path, language: str) -> dict:
    """The shot list with another language's narration and voice."""
    data = mi.load_shotlist(project)
    overlay = json.loads(narration_path(project, language).read_text(encoding="utf-8"))
    texts = overlay["scenes"]
    missing = [s["id"] for s in data["scenes"] if s["id"] not in texts and not s.get("audio")]
    if missing:
        raise ValueError(f"narration_{language}.json has no text for {', '.join(missing)}")
    voice = {k: v for k, v in (data.get("voice") or {}).items() if k != "channel"}
    voice.update(overlay.get("voice") or {})
    voice["language"] = overlay.get("language", language)
    scenes = [dict(s, narration=texts[s["id"]], caption=texts[s["id"]]) for s in data["scenes"]]
    return {**data, "voice": voice, "scenes": scenes}


def windows(timing: dict) -> dict[str, float]:
    """Seconds each scene's line may take: up to the next line's start."""
    scenes = timing["scenes"]
    out = {}
    for i, sc in enumerate(scenes):
        nxt = scenes[i + 1]["voice_start"] if i + 1 < len(scenes) else timing["duration"] - END_FADE
        out[sc["id"]] = round(nxt - sc["voice_start"] - LINE_GAP, 3)
    return out


def fit(clips: dict, timing: dict) -> list[dict]:
    """Per scene: window, clip length, the speed-up it needs, and whether it fits."""
    rows = []
    for sc_id, window in windows(timing).items():
        seconds = clips[sc_id]["seconds"]
        tempo = max(1.0, seconds / window)
        rows.append({"scene": sc_id, "window": window, "seconds": seconds,
                     "tempo": round(tempo, 3), "fits": tempo <= MAX_TEMPO})
    return rows


def synth(project: Path, language: str, tts=None, stt=None) -> dict:
    data = shotlist_for(project, language)
    voice = mi.narrate(project, tts=tts, stt=stt, data=data)
    timing = mi._read(mi.root(project) / "timing.json")
    report = {"language": language, "cost_usd": voice["cost_usd"], "clips": voice["clips"],
              "fit": fit(voice["clips"], timing)}
    mi._write(mi.root(project) / f"audio_{language}.json", report)
    return report


def _run(cmd: list[str]) -> None:
    proc = subprocess.run(cmd, capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=900)
    if proc.returncode != 0:
        raise RuntimeError(proc.stderr[-600:])


def _voice_stem(clips: dict, timing: dict, out: Path) -> Path:
    ffmpeg = shutil.which("ffmpeg") or "ffmpeg"
    rows = {r["scene"]: r for r in fit(clips, timing)}
    cmd = [ffmpeg, "-v", "error", "-y", "-f", "lavfi", "-t", f"{timing['duration']:.3f}",
           "-i", f"anullsrc=r={RATE}:cl=stereo"]
    parts = []
    for i, sc in enumerate(timing["scenes"], start=1):
        cmd += ["-i", clips[sc["id"]]["path"]]
        tempo = min(rows[sc["id"]]["tempo"], MAX_TEMPO)
        speed = f"atempo={tempo:.4f}," if tempo > 1.0 else ""
        delay = int(round(sc["voice_start"] * 1000))
        parts.append(f"[{i}:a]{speed}aresample={RATE},aformat=channel_layouts=stereo,"
                     f"atrim=duration={rows[sc['id']]['window'] + LINE_GAP:.3f},"
                     f"adelay={delay}|{delay}[v{i}]")
    mix = "".join(f"[v{i}]" for i in range(1, len(timing["scenes"]) + 1))
    parts.append(f"[0:a]{mix}amix=inputs={len(timing['scenes']) + 1}:duration=first:normalize=0[out]")
    cmd += ["-filter_complex", ";".join(parts), "-map", "[out]", "-c:a", "pcm_s16le", str(out)]
    _run(cmd)
    return out


def _music_stem(project: Path, data: dict, timing: dict, out: Path) -> Optional[Path]:
    """The render's music sections: each fades in and out over
    min(1 s, length / 3) and plays at music.volume (manual-images page)."""
    music_cfg = data.get("music") or {}
    tracks = mi.music_tracks(music_cfg, timing)
    if not tracks:
        return None
    volume = float(music_cfg.get("volume", 0.18))
    ffmpeg = shutil.which("ffmpeg") or "ffmpeg"
    cmd = [ffmpeg, "-v", "error", "-y", "-f", "lavfi", "-t", f"{timing['duration']:.3f}",
           "-i", f"anullsrc=r={RATE}:cl=stereo"]
    parts, n = [], 0
    for track in tracks:
        src = mi._resolve(project, track["path"])
        if not src.exists():
            continue
        n += 1
        length = track["end"] - track["start"]
        fade = min(1.0, length / 3)
        delay = int(round(track["start"] * 1000))
        cmd += ["-i", str(src)]
        parts.append(f"[{n}:a]atrim=duration={length:.3f},asetpts=PTS-STARTPTS,aresample={RATE},"
                     f"aformat=channel_layouts=stereo,volume={volume:.3f},afade=t=in:d={fade:.3f},"
                     f"afade=t=out:st={length - fade:.3f}:d={fade:.3f},adelay={delay}|{delay}[m{n}]")
    if not n:
        return None
    mix = "".join(f"[m{i}]" for i in range(1, n + 1))
    parts.append(f"[0:a]{mix}amix=inputs={n + 1}:duration=first:normalize=0[out]")
    cmd += ["-filter_complex", ";".join(parts), "-map", "[out]", "-c:a", "pcm_s16le", str(out)]
    _run(cmd)
    return out


def _sfx_stem(project: Path, data: dict, timing: dict, out: Path) -> Optional[Path]:
    """The same cues the render placed (they follow the picture, not the voice)."""
    sfx_cfg = data.get("sfx") or {}
    if not sfx_cfg.get("library"):
        return None
    from tools.audio.sfx_placer import SfxPlacer

    speech = [[sc["voice_start"], sc["voice_start"] + sc["voice_seconds"]] for sc in timing["scenes"]]
    result = SfxPlacer().execute({
        "operation": "render_stem", "library_dir": str(mi._resolve(project, sfx_cfg["library"])),
        "events": mi.sfx_events(sfx_cfg, data, timing), "speech": speech,
        "duration": timing["duration"], "output_path": str(out)})
    if not result.success:
        raise RuntimeError(f"sound effects: {result.error}")
    return out


def mix(project: Path, language: str, loudness=None) -> dict:
    """voice + music + sound effects -> renders/<slug>_audio_<lang>.wav at -14 LUFS."""
    from tools.audio.loudness_normalize import LoudnessNormalize

    report = mi._read(mi.root(project) / f"audio_{language}.json")
    clips = report["clips"]
    data = mi.load_shotlist(project)
    timing = mi._read(mi.root(project) / "timing.json")
    stems_dir = Path(project) / "renders" / f"stems_{language}"
    stems_dir.mkdir(parents=True, exist_ok=True)
    stems = [_voice_stem(clips, timing, stems_dir / "voice.wav"),
             _music_stem(project, data, timing, stems_dir / "music.wav"),
             _sfx_stem(project, data, timing, stems_dir / "sfx.wav")]
    stems = [s for s in stems if s]
    ffmpeg = shutil.which("ffmpeg") or "ffmpeg"
    raw = stems_dir / "mix_raw.wav"
    inputs = sum((["-i", str(s)] for s in stems), [])
    fade_at = timing["duration"] - END_FADE
    _run([ffmpeg, "-v", "error", "-y", *inputs, "-filter_complex",
          f"{''.join(f'[{i}:a]' for i in range(len(stems)))}amix=inputs={len(stems)}:duration=longest:normalize=0,"
          f"afade=t=out:st={fade_at:.3f}:d={END_FADE}[out]",
          "-map", "[out]", "-c:a", "pcm_s16le", str(raw)])
    slug = Path(project).name.removesuffix("-fa")
    out = Path(project) / "renders" / f"{slug}_audio_{language}.wav"
    loudness = loudness or LoudnessNormalize()
    result = loudness.execute({"input_path": str(raw), "output_path": str(out), "true_peak": -2.5})
    if not result.success:
        raise RuntimeError(f"loudness: {result.error}")
    rows = fit(clips, timing)
    return {"output": str(out), "duration": timing["duration"], "stems": [str(s) for s in stems],
            "sped_up": [r["scene"] for r in rows if r["tempo"] > 1.0],
            "too_long": [r["scene"] for r in rows if not r["fits"]], "loudness": result.data}


def preview(project: Path, language: str, video: Path) -> Path:
    """The rendered video with the new track in place of its audio, to watch."""
    slug = Path(project).name.removesuffix("-fa")
    track = Path(project) / "renders" / f"{slug}_audio_{language}.wav"
    out = Path(project) / "renders" / f"{video.stem}_{language}.mp4"
    _run([shutil.which("ffmpeg") or "ffmpeg", "-v", "error", "-y", "-i", str(video), "-i", str(track),
          "-map", "0:v", "-map", "1:a", "-c:v", "copy", "-c:a", "aac", "-b:a", "192k", "-shortest", str(out)])
    return out


# -- subtitles ---------------------------------------------------------------------

LINE_CHARS = 42      # per subtitle line
CUE_LINES = 2
MIN_CUE = 1.0
MAX_CPS = 17.0       # letters per second a viewer can read comfortably
MAX_SHIFT = 0.6      # how far a cue edge may move off the voice to be readable
_SENTENCE = re.compile(r"(?<=[.!?؟…:;؛])\s+")


def sentences(text: str) -> list[str]:
    return [s.strip() for s in _SENTENCE.split(text.strip()) if s.strip()]


def sentence_times(scene: dict, persian: list[str], words: list[dict]) -> Optional[list[tuple[float, float]]]:
    """Start and end of each Persian sentence in the video, from a transcript
    of the video's own audio (words in video time) matched within the scene."""
    start, end = scene["voice_start"], scene["voice_start"] + scene["voice_seconds"]
    if len(persian) == 1:
        return [(start, end)]
    inside = [w for w in words if start - 0.3 <= w["start"] <= end + 0.3]
    try:
        breaks = mi.scene_breaks_from_words(inside, persian)
    except ValueError:
        return None
    edges = [start] + [min(max(b, start), end) for b in breaks] + [end]
    if any(b <= a for a, b in zip(edges, edges[1:])):
        return None
    return list(zip(edges, edges[1:]))


def cues_for(text: str, start: float, end: float) -> list[dict]:
    """One sentence on screen from start to end, cut into cues of at most
    CUE_LINES lines; each cue gets time in proportion to its letters."""
    blocks = [textwrap.wrap(part, LINE_CHARS) for part in _even_parts(text)]
    sizes = [sum(len(line) for line in b) for b in blocks]
    cues, t = [], start
    for block, size in zip(blocks, sizes):
        length = (end - start) * size / sum(sizes)
        cues.append({"start": t, "end": t + length, "lines": block})
        t += length
    return cues


def _even_parts(text: str) -> list[str]:
    """A sentence too long for one cue, cut into parts of about equal length
    (greedy filling leaves a one-word orphan at the end)."""
    words = text.split()
    n = max(1, math.ceil(len(textwrap.wrap(text, LINE_CHARS)) / CUE_LINES))
    while True:
        target = len(text) / n
        parts, current = [], []
        for word in words:
            if current and len(" ".join(current + [word])) > target and len(parts) < n - 1:
                parts.append(" ".join(current))
                current = []
            current.append(word)
        parts.append(" ".join(current))
        if all(len(textwrap.wrap(p, LINE_CHARS)) <= CUE_LINES for p in parts):
            return parts
        n += 1


def subtitle_cues(data: dict, translated: dict, timing: dict, words: list[dict]) -> list[dict]:
    """Translated text timed to the Persian narration: sentence by sentence
    where both sides have the same number of sentences, else spread over the
    scene's line in proportion to length."""
    by_id = {s["id"]: s for s in timing["scenes"]}
    cues = []
    for scene in data["scenes"]:
        sc = by_id[scene["id"]]
        target = sentences(translated[scene["id"]])
        persian = sentences(scene["narration"])
        spans = sentence_times(sc, persian, words) if len(persian) == len(target) else None
        if spans is None:
            start, end = sc["voice_start"], sc["voice_start"] + sc["voice_seconds"]
            sizes = [len(s) for s in target]
            spans, t = [], start
            for size in sizes:
                spans.append((t, t + (end - start) * size / sum(sizes)))
                t = spans[-1][1]
        for text, (a, b) in zip(target, spans):
            cues += [dict(c, scene=scene["id"]) for c in cues_for(text, a, b)]
    cues = _balance(_merge_fast(cues))
    # a cue too short to read borrows from the gap after it, never the next cue
    for cue, nxt in zip(cues, cues[1:] + [None]):
        limit = nxt["start"] if nxt else timing["duration"]
        if cue["end"] - cue["start"] < MIN_CUE:
            cue["end"] = min(limit, cue["start"] + MIN_CUE)
    return cues


def _cps(cue: dict) -> float:
    return sum(len(line) for line in cue["lines"]) / max(0.01, cue["end"] - cue["start"])


def _merge_fast(cues: list[dict]) -> list[dict]:
    """A cue read faster than MAX_CPS, or shown for less than MIN_CUE, joins
    its neighbour in the same scene when the two still fit on CUE_LINES lines."""
    cues = list(cues)
    changed = True
    while changed:
        changed = False
        for i, cue in enumerate(cues):
            if _cps(cue) <= MAX_CPS and cue["end"] - cue["start"] >= MIN_CUE:
                continue
            for j in (i + 1, i - 1):
                if not 0 <= j < len(cues) or cues[j]["scene"] != cue["scene"]:
                    continue
                a, b = sorted((i, j))
                lines = textwrap.wrap(" ".join(cues[a]["lines"] + cues[b]["lines"]), LINE_CHARS)
                if len(lines) <= CUE_LINES:
                    cues[a] = {"start": cues[a]["start"], "end": cues[b]["end"], "lines": lines,
                               "scene": cue["scene"]}
                    del cues[b]
                    changed = True
                    break
            if changed:
                break
    return cues


def _balance(cues: list[dict]) -> list[dict]:
    """A cue still too fast takes up to MAX_SHIFT from a slower neighbour, or
    stays up into the silence before the next cue."""
    for i, cue in enumerate(cues):
        if _cps(cue) <= MAX_CPS:
            continue
        nxt = cues[i + 1] if i + 1 < len(cues) else None
        prev = cues[i - 1] if i else None
        if nxt and nxt["start"] > cue["end"]:
            cue["end"] = min(nxt["start"], cue["end"] + MAX_SHIFT)
        for other, forward in ((nxt, True), (prev, False)):
            if _cps(cue) <= MAX_CPS or not other or _cps(other) >= _cps(cue):
                continue
            letters = sum(len(line) for line in cue["lines"])
            other_letters = sum(len(line) for line in other["lines"])
            span = (other["end"] - cue["start"]) if forward else (cue["end"] - other["start"])
            want = span * letters / (letters + other_letters)
            if forward:
                edge = min(cue["start"] + want, cue["end"] + MAX_SHIFT)
                if edge > cue["end"] and edge >= other["start"]:
                    cue["end"] = other["start"] = round(edge, 3)
            else:
                edge = max(cue["end"] - want, cue["start"] - MAX_SHIFT)
                if edge < cue["start"] and edge <= other["end"]:
                    cue["start"] = other["end"] = round(edge, 3)
    return cues


def _srt_time(seconds: float) -> str:
    ms = int(round(seconds * 1000))
    h, ms = divmod(ms, 3_600_000)
    m, ms = divmod(ms, 60_000)
    s, ms = divmod(ms, 1000)
    return f"{h:02d}:{m:02d}:{s:02d},{ms:03d}"


def to_srt(cues: list[dict]) -> str:
    return "\n".join(f"{i}\n{_srt_time(c['start'])} --> {_srt_time(c['end'])}\n" + "\n".join(c["lines"]) + "\n"
                     for i, c in enumerate(cues, 1))


def subtitles(project: Path, language: str, video: Path, stt=None) -> dict:
    """packaging/subtitles_<lang>.srt timed to the rendered video's Persian voice
    (the video's audio is transcribed once, ~$0.0001 per second)."""
    data = mi.load_shotlist(project)
    timing = mi._read(mi.root(project) / "timing.json")
    overlay = json.loads(narration_path(project, language).read_text(encoding="utf-8"))
    words, cost = mi._take_words(video, stt, "fa")
    cues = subtitle_cues(data, overlay["scenes"], timing, words)
    out = Path(project) / "packaging" / f"subtitles_{language}.srt"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(to_srt(cues), encoding="utf-8")
    return {"output": str(out), "cues": len(cues), "cost_usd": cost}
