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
import shutil
import subprocess
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
