"""fa_sfx_library: the built library carries licences, peak and sustain (ffmpeg, no network)."""

from __future__ import annotations

import json
import shutil
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "scripts"))

import fa_sfx_library  # noqa: E402

needs_ffmpeg = pytest.mark.skipif(shutil.which("ffmpeg") is None, reason="needs ffmpeg")


@needs_ffmpeg
def test_library_tells_a_hit_from_a_held_boom(tmp_path):
    fa_sfx_library.build(tmp_path)
    files = json.loads((tmp_path / "library.json").read_text(encoding="utf-8"))["files"]
    assert set(fa_sfx_library.PICKS) | set(fa_sfx_library.SYNTH) == set(files)
    for name, item in files.items():
        assert (tmp_path / item["file"]).exists(), name
        assert 0 <= item["peak_s"] < item["duration"]
        assert item["licence"]
    assert files["impact-bass-1"]["sustain_s"] > 1.0
    assert files["hit"]["sustain_s"] < 0.3 and files["pop-synth"]["sustain_s"] < 0.1
    assert files["riser-1.5"]["peak_s"] > 1.2
    licence = (tmp_path / "LICENSE.md").read_text(encoding="utf-8")
    assert "Pixabay Content License" in licence and "Content ID" in licence and "whoosh.mp3" in licence
