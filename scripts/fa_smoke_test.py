"""Phase 0 smoke test for Persian productions.

Two checks, run from the repo root:

  1. subtitles: write a Persian SRT with subtitle_gen, burn it onto a plain
     background with video_compose (Vazirmatn), and save one frame as PNG.
     Free; needs ffmpeg and the Vazirmatn font.
  2. tts: synthesize one Persian sentence through tts_selector and report
     which provider was picked and audio_duration_seconds. Calls a paid API
     (one short sentence, well under $0.01 on Gemini Flash TTS).

    python scripts/fa_smoke_test.py subtitles
    python scripts/fa_smoke_test.py tts
    python scripts/fa_smoke_test.py all

Outputs go to fa_smoke/.
"""
from __future__ import annotations

import argparse
import json
import shutil
import subprocess
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT))

SUBTITLE_LINES = [
    "اپل در سال ۱۹۷۶ توی یه گاراژ شروع شد.",
    "Steve Jobs و Wozniak فقط ۱۳۰۰ دلار داشتن!",
]
TTS_TEXT = (
    "اپل توی سال هزار و نهصد و هفتاد و شش، توی یه گاراژ کوچیک شروع شد؛ "
    "استیو جابز و استیو وازنیاک فقط هزار و سیصد دلار پول داشتن."
)


def check_subtitles(out_dir: Path) -> bool:
    from tools.subtitle.subtitle_gen import SubtitleGen
    from tools.video.video_compose import VideoCompose

    if not shutil.which("ffmpeg"):
        print("ffmpeg not found on PATH")
        return False

    segments = [
        {"start": i * 2.0, "end": i * 2.0 + 2.0, "text": text}
        for i, text in enumerate(SUBTITLE_LINES)
    ]
    srt = out_dir / "fa.srt"
    result = SubtitleGen().execute({"segments": segments, "output_path": str(srt)})
    if not result.success:
        print("subtitle_gen failed:", result.error)
        return False
    print(f"subtitle_gen: {result.data['cue_count']} cues, direction={result.data['direction']}")

    background = out_dir / "background.mp4"
    subprocess.run(
        ["ffmpeg", "-y", "-loglevel", "error", "-f", "lavfi",
         "-i", "color=c=0x1e293b:s=1280x720:d=4:r=25", str(background)],
        check=True,
    )
    burned = out_dir / "subtitled.mp4"
    result = VideoCompose().execute({
        "operation": "burn_subtitles",
        "input_path": str(background),
        "subtitle_path": str(srt),
        "output_path": str(burned),
        "subtitle_style": {"font": "Vazirmatn", "font_size": 36},
    })
    if not result.success:
        print("video_compose burn_subtitles failed:", result.error)
        return False

    # Second cue is on screen from 2s to 4s.
    frame = out_dir / "frame_latin_name.png"
    subprocess.run(
        ["ffmpeg", "-y", "-loglevel", "error", "-ss", "3", "-i", str(burned),
         "-frames:v", "1", str(frame)],
        check=True,
    )
    print(f"frame: {frame}")
    return True


def check_tts(out_dir: Path) -> bool:
    from tools.audio.tts_selector import TTSSelector

    out = out_dir / "narration_fa.wav"
    result = TTSSelector().execute({"text": TTS_TEXT, "output_path": str(out)})
    if not result.success:
        print("tts_selector failed:", result.error)
        return False
    data = result.data
    summary = {
        "selected_tool": data.get("selected_tool"),
        "language": data.get("language"),
        "audio_duration_seconds": data.get("audio_duration_seconds"),
        "output": data.get("output"),
        "cost_usd": result.cost_usd,
    }
    print(json.dumps(summary, ensure_ascii=False, indent=2))
    return data.get("selected_tool") == "gemini_tts" and bool(data.get("audio_duration_seconds"))


def main() -> int:
    parser = argparse.ArgumentParser(description="Persian production smoke test")
    parser.add_argument("check", choices=["subtitles", "tts", "all"])
    parser.add_argument("--out", default="fa_smoke")
    args = parser.parse_args()

    out_dir = Path(args.out)
    out_dir.mkdir(parents=True, exist_ok=True)
    ok = True
    if args.check in ("subtitles", "all"):
        ok = check_subtitles(out_dir) and ok
    if args.check in ("tts", "all"):
        ok = check_tts(out_dir) and ok
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
