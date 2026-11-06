"""Build the channel's SFX library: bundled HyperFrames sounds + procedural ones.

    python scripts/fa_sfx_library.py --dest projects/_sfx_library/fa-v1

Writes the files, `library.json` ({name: {file, duration, peak_s,
sustain_s, source, licence}}) and `LICENSE.md`. `peak_s` (first moment at
full strength) is what sfx_placer puts on the cut; `sustain_s` (time within
6 dB of full) tells a hit (< 0.3 s) from a held boom. Local and free;
nothing is downloaded.

Licences (read 2026-11-05 on the sources' own pages):
- bundled set (.agents/skills/hyperframes-media/assets/sfx, from Pixabay):
  Pixabay Content License, terms "Last updated: 20 October, 2026" — free for
  commercial use (monetized YouTube included), no attribution; no selling or
  redistributing a file on its own ("Standalone"), no claiming ownership,
  which includes registering it with Content ID.
- procedural set (lib/sfx_synth.py): our own work.
"""

from __future__ import annotations

import argparse
import json
import shutil
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO))

import numpy as np  # noqa: E402

from lib.sfx_synth import peak_time, render  # noqa: E402
from tools.audio.beat_detect import decode_mono  # noqa: E402

BUNDLED = REPO / ".agents" / "skills" / "hyperframes-media" / "assets" / "sfx"
PICKS = ["whoosh", "whoosh-short", "pop", "click-soft", "impact-bass-1", "riser", "sparkle", "glitch-3"]
SYNTH = {
    "whoosh-synth": ("whoosh", {"duration": 0.6}),
    "swish": ("swish", {}),
    "pop-synth": ("pop", {}),
    "hit": ("hit", {}),
    "riser-1.5": ("riser", {"duration": 1.5}),
    "crackle": ("crackle", {"duration": 9.0}),
    "gunshot": ("gunshot", {}),
    "gunshots-3": ("gunshot", {"shots": 3}),
    "typing": ("typing", {"duration": 1.0}),
}
PIXABAY = "Pixabay Content License (https://pixabay.com/service/terms/, last updated 20 October 2026)"

LICENSE_MD = """# SFX library licence

Built by `scripts/fa_sfx_library.py` on the date in `library.json`.

| Files | Source | Licence |
|---|---|---|
| {bundled} | HyperFrames bundled set (`.agents/skills/hyperframes-media/assets/sfx`, originally Pixabay, see its CREDITS.md) | {pixabay} |
| {synth} | `lib/sfx_synth.py` (procedural, seeded) | own work, no third-party rights |

Pixabay terms as read on pixabay.com on 2026-11-05: content may be used "for
commercial or non-commercial purposes" without credit; you cannot "sell or
distribute the Content" on a "Standalone basis" (no creative effort added) or
claim ownership of it. Using a sound inside an edited video is allowed; do not
upload these files on their own, and do not register them (or a video's
soundtrack built only from them) with YouTube Content ID. Pixabay content
"may be subject to additional intellectual property rights", so a claim on a
video stays the uploader's problem: keep this file with the project.

CC0 alternative if more sounds are needed: Kenney "Impact Sounds" (130 files)
and "Interface Sounds" (100 files), kenney.nl, "Creative Commons CC0".
"""


def sustain(samples, rate: int = 48000) -> float:
    hop = rate // 100
    frames = len(samples) // hop
    rms = np.sqrt(np.mean(samples[: frames * hop].reshape(frames, hop).astype(np.float64) ** 2, axis=1))
    return round(float((rms >= rms.max() / 2).sum()) / 100, 2)


def build(dest: Path) -> dict:
    import datetime

    dest.mkdir(parents=True, exist_ok=True)
    manifest = json.loads((BUNDLED / "manifest.json").read_text(encoding="utf-8"))
    files = {}
    for key in PICKS:
        src = BUNDLED / manifest[key]["file"]
        shutil.copy2(src, dest / src.name)
        samples = decode_mono(src, rate=48000)
        files[key] = {"file": src.name, "duration": round(len(samples) / 48000, 3),
                      "peak_s": peak_time(samples, 48000), "sustain_s": sustain(samples),
                      "source": "hyperframes bundled (Pixabay)",
                      "licence": PIXABAY, "note": manifest[key]["description"]}
    for key, (kind, kwargs) in SYNTH.items():
        files[key] = render(kind, dest / f"{key}.wav", **kwargs)
        files[key]["sustain_s"] = sustain(decode_mono(dest / f"{key}.wav", rate=48000))
    library = {"name": dest.name, "built": datetime.date.today().isoformat(), "files": files}
    (dest / "library.json").write_text(json.dumps(library, ensure_ascii=False, indent=2), encoding="utf-8")
    (dest / "LICENSE.md").write_text(LICENSE_MD.format(
        bundled=", ".join(files[k]["file"] for k in PICKS), pixabay=PIXABAY,
        synth=", ".join(files[k]["file"] for k in SYNTH)), encoding="utf-8")
    return library


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--dest", default=str(REPO / "projects" / "_sfx_library" / "fa-v1"))
    args = parser.parse_args(argv)
    library = build(Path(args.dest))
    for name, item in library["files"].items():
        print(f"{name:16} {item['duration']:6.2f} s  peak {item['peak_s']:.3f} s  "
              f"sustain {item['sustain_s']:.2f} s  {item['file']}")
    print(Path(args.dest) / "library.json")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
