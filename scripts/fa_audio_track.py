"""Second-language audio track for a finished manual-images video (lib/fa_audio_track.py).

    python scripts/fa_audio_track.py synth   --project projects/<id> --language en
      (paid TTS; prints each line against its window; rewrite lines marked too long)
    python scripts/fa_audio_track.py mix     --project projects/<id> --language en
    python scripts/fa_audio_track.py preview --project projects/<id> --language en --video renders/<final>.mp4
    python scripts/fa_audio_track.py srt     --project projects/<id> --language en --video renders/<final>.mp4
      (subtitles in that language timed to the video's Persian voice; ~$0.04 transcription)

The text goes in manual_images/narration_<lang>.json first.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from lib import fa_audio_track  # noqa: E402


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("command", choices=["synth", "mix", "preview", "srt"])
    parser.add_argument("--project", required=True)
    parser.add_argument("--language", default="en")
    parser.add_argument("--video", help="preview, srt: the rendered video, relative to the project")
    args = parser.parse_args(argv)
    project = Path(args.project)

    if args.command == "synth":
        report = fa_audio_track.synth(project, args.language)
        for row in report["fit"]:
            mark = "" if row["tempo"] <= 1.0 else ("  speed-up" if row["fits"] else "  TOO LONG")
            print(f"{row['scene']}  {row['seconds']:6.2f} s / {row['window']:6.2f} s  x{row['tempo']:.3f}{mark}")
        print(f"cost ${report['cost_usd']:.4f}")
        return 0 if all(r["fits"] for r in report["fit"]) else 1
    if args.command == "mix":
        print(json.dumps(fa_audio_track.mix(project, args.language), ensure_ascii=False, indent=2))
        return 0
    if not args.video:
        parser.error(f"{args.command} needs --video")
    video = Path(args.video) if Path(args.video).is_absolute() else project / args.video
    if args.command == "srt":
        print(json.dumps(fa_audio_track.subtitles(project, args.language, video), ensure_ascii=False, indent=2))
        return 0
    print(fa_audio_track.preview(project, args.language, video))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
