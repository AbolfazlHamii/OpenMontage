"""fa_edit_pass end to end on a tiny synthetic workspace (ffmpeg, no network)."""

from __future__ import annotations

import json
import shutil
import sys
import wave
from pathlib import Path

import numpy as np
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "scripts"))

import fa_edit_pass  # noqa: E402
from lib.sfx_synth import render  # noqa: E402

needs_ffmpeg = pytest.mark.skipif(shutil.which("ffmpeg") is None, reason="needs ffmpeg")
RATE = 22050

HTML = """<!doctype html>
<html lang="fa"><body>
<div id="root" data-composition-id="t" data-duration="6">
  <div id="captions" class="clip" data-start="0" data-duration="6" data-track-index="3">
    <!-- edit-pass:captions -->
    <!-- /edit-pass:captions -->
  </div>
  <audio id="vo-1" src="assets/audio/vo.wav" data-start="0.5" data-track-index="10"></audio>
  <!-- edit-pass:audio -->
  <!-- /edit-pass:audio -->
</div>
<script>
  const tl = gsap.timeline({ paused: true });
  // edit-pass:music
  // /edit-pass:music
</script>
</body></html>
"""


def _wav(path, x, rate=RATE):
    path.parent.mkdir(parents=True, exist_ok=True)
    with wave.open(str(path), "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(rate)
        w.writeframes((np.clip(x, -1, 1) * 32767).astype("<i2").tobytes())


def test_replace_block_keeps_markers_and_indent():
    text = "<div>\n    <!-- edit-pass:x -->\n    old\n    <!-- /edit-pass:x -->\n</div>"
    out = fa_edit_pass.replace_block(text, "x", "a\nb")
    assert out == "<div>\n    <!-- edit-pass:x -->\n    a\n    b\n    <!-- /edit-pass:x -->\n</div>"
    with pytest.raises(ValueError):
        fa_edit_pass.replace_block(text, "missing", "")


def test_pause_window():
    speech = [(0.2, 2.5), (2.8, 6.0)]
    assert fa_edit_pass.pause_window(2.7, speech) == (2.5, 2.8)
    assert fa_edit_pass.pause_window(4.0, speech) == (3.94, 4.06)


@needs_ffmpeg
def test_edit_pass_on_a_small_workspace(tmp_path):
    ws = tmp_path / "ws"
    t = np.arange(int(RATE * 4)) / RATE
    voice = np.where(((t > 0.2) & (t < 1.6)) | ((t > 2.2) & (t < 3.6)), 0.4 * np.sin(2 * np.pi * 180 * t), 0)
    _wav(ws / "assets/audio/vo.wav", voice)
    clicks = np.random.default_rng(0).normal(0, 0.01, int(RATE * 12))
    for k, beat in enumerate(np.arange(0.25, 12, 0.5)):
        i = int(beat * RATE)
        clicks[i:i + 300] += (1.0 if k % 4 == 0 else 0.6) * np.sin(2 * np.pi * (150 if k % 4 == 0 else 1000)
                                                                     * np.arange(300) / RATE) * np.exp(-np.arange(300) / 60)
    _wav(ws / "assets/audio/music.wav", clicks)
    words = [{"word": "سلام", "start": 0.0, "end": 0.9}, {"word": "دنیا", "start": 0.9, "end": 1.7},
             {"word": "خداحافظ", "start": 1.8, "end": 3.2}]
    (ws / "assets/audio/vo.words.json").write_text(json.dumps({"words": words}, ensure_ascii=False), encoding="utf-8")
    lib = tmp_path / "lib"
    files = {"whoosh": render("whoosh", lib / "whoosh.wav"), "pop": render("pop", lib / "pop.wav")}
    (lib / "library.json").write_text(json.dumps({"files": files}), encoding="utf-8")
    (lib / "LICENSE.md").write_text("own work", encoding="utf-8")
    (ws / "index.html").write_text(HTML, encoding="utf-8")
    plan = {
        "duration": 6.0, "sfx_library": "../lib",
        "narration": [{"id": "vo-1", "src": "assets/audio/vo.wav", "start": 0.5, "words": "assets/audio/vo.words.json"}],
        "captions": [{"text": "سلام *دنیا*", "clip": "vo-1"}, {"text": "خداحافظ", "clip": "vo-1"}],
        "music": {"src": "assets/audio/music.wav", "analyze_seconds": 12,
                  "clips": [{"id": "bgm", "start": 0, "end": 3.0, "track": 12},
                            {"id": "bgm-2", "start": 3.4, "end": 6.0, "track": 13, "align_downbeat": True}],
                  "events": [{"kind": "drop", "start": 3.0, "end": 3.4}, {"kind": "fade_out", "start": 5.5, "end": 5.75}]},
        "cuts": [{"at": 2.25, "sfx": "whoosh"}], "interrupts": [{"at": 1.4}],
        "emphasis_sfx": "pop",
    }
    (ws / "edit_plan.json").write_text(json.dumps(plan, ensure_ascii=False), encoding="utf-8")

    r = fa_edit_pass.run(ws)

    html = (ws / "index.html").read_text(encoding="utf-8")
    assert '<span class="em key"' in html and 'id="bgm-2"' in html and 'src="assets/sfx/whoosh.wav"' in html
    assert 'tl.set("#bgm", { volume: 0 }, 0);' in html
    assert (ws / "assets/sfx/LICENSE.md").exists() and (ws / "assets/sfx/pop.wav").exists()
    assert r["captions"][0]["words"][0]["start"] >= 0.68  # clamped into speech (voice starts at 0.7)
    assert [c["sfx"] for c in r["sfx"]] == ["pop", "whoosh"]
    bgm2 = r["music_clips"][1]
    assert min(abs(bgm2["media_start"] - b) for b in np.arange(0.25, 12, 0.5)) < 0.03  # re-enters on a beat
    assert min(abs(b - 3.4) for b in r["beats"]) < 0.01  # ... which plays exactly at the clip start
    assert r["music_end"] == pytest.approx(5.75, abs=0.02)
    assert json.loads((ws / "edit_pass.json").read_text(encoding="utf-8"))["cuts"] == [2.25]
