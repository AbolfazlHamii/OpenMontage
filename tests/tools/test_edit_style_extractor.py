"""edit_style_extractor: measurements, CLIP-first labelling, card output. No network.

The end-to-end test renders a tiny local clip with ffmpeg; LLM calls and
CLIP are fakes.
"""

from __future__ import annotations

import json
import shutil
import subprocess

import numpy as np
import pytest

from styles.edit_style_loader import load_edit_style
from tools.analysis.edit_style_extractor import (
    EditStyleExtractor,
    compare_metrics,
    cut_rate_curve,
    detect_onsets,
    motion_label,
    onset_sync,
    section_bounds,
    section_pacing,
    words_per_minute,
)
from tools.base_tool import ToolResult


def _shots(lengths):
    t, out = 0.0, []
    for n in lengths:
        out.append({"start_seconds": t, "end_seconds": t + n})
        t += n
    return out


def test_section_pacing_and_curve():
    shots = _shots([2] * 10 + [4] * 30 + [6] * 5)  # 20 + 120 + 30 = 170 s
    duration = 170.0
    bounds = section_bounds(duration)
    assert bounds["hook"] == (0.0, 17.0)
    pacing = section_pacing(shots, duration)
    assert pacing["hook"]["asl_seconds"] == pytest.approx(2.0, abs=0.3)
    assert pacing["body"]["asl_seconds"] == pytest.approx(4.0, abs=0.5)
    cuts = [s["start_seconds"] for s in shots[1:]]
    curve = cut_rate_curve(cuts, duration)
    assert curve[0]["cuts_per_minute"] > curve[-1]["cuts_per_minute"]


def test_onset_sync_uses_80ms_window():
    cuts = [1.0, 2.0, 3.0, 4.0]
    onsets = [0.95, 2.07, 3.2, 10.0]
    assert onset_sync(cuts, onsets)["ratio"] == 0.5
    assert onset_sync(cuts, onsets, duration=20)["chance"] == pytest.approx(0.032)
    assert onset_sync([], onsets)["ratio"] is None


def test_words_per_minute_handles_duration_or_end():
    segs = [{"text": "one two three", "start": 0, "duration": 1.0},
            {"text": "four five six", "start": 30, "end": 60}]
    assert words_per_minute(segs) == 6.0
    assert words_per_minute(segs, 0, 10) == pytest.approx(180.0)
    assert words_per_minute([]) is None


def test_motion_labels():
    assert motion_label(0.5) == "static"
    assert motion_label(5) == "ken_burns"
    assert motion_label(30) == "fast_motion"


def test_detect_onsets_finds_clicks():
    rate = 8000
    x = np.zeros(rate * 3, dtype=np.float32)
    for t in (0.5, 1.5, 2.5):
        i = int(t * rate)
        x[i:i + 400] = 0.8
    onsets = detect_onsets(x, rate)
    assert len(onsets) == 3
    assert all(abs(a - b) < 0.03 for a, b in zip(onsets, (0.5, 1.5, 2.5)))


def test_compare_metrics_flags_deviation():
    card = load_edit_style("full-history-in-n-minutes")
    ok = compare_metrics({"asl_seconds": 3.9, "cuts_per_minute": 15.0, "words_per_minute": 150,
                          "subtitles_present": True, "longest_static_seconds": 7}, card)
    assert ok["pass"]
    bad = compare_metrics({"asl_seconds": 8.0, "cuts_per_minute": 7.0,
                           "subtitles_present": False, "longest_static_seconds": 20}, card)
    assert not bad["pass"]
    assert {c["check"] for c in bad["checks"] if not c["pass"]} == {
        "asl_seconds", "cuts_per_minute", "subtitles", "pattern_interrupt"}


class _FakeLLM:
    def __init__(self):
        self.calls = []
        self.cost_usd = 0.0

    def execute(self, inputs):
        self.calls.append(inputs)
        if inputs.get("operation") == "batch":
            results = {it["id"]: {"json": {"shot_size": "wide", "camera_angle": "eye_level",
                                           "content": "illustration", "has_text": True}}
                       for it in inputs["items"]}
            return ToolResult(success=True, data={"results": results}, cost_usd=0.0004 * len(results))
        return ToolResult(success=True, data={"json": {"beats": ["big number", "paradox"],
                                                       "formula": "number then paradox"}},
                          cost_usd=0.0002)


@pytest.mark.skipif(shutil.which("ffmpeg") is None, reason="needs ffmpeg")
def test_extract_end_to_end_with_fakes(tmp_path):
    clip = tmp_path / "ref.mp4"
    subprocess.run([
        "ffmpeg", "-v", "error", "-y", "-f", "lavfi", "-i", "color=c=black:s=64x36:r=10:d=6",
        "-f", "lavfi", "-i", "sine=frequency=440:duration=6",
        "-vf", "drawbox=x=0:y=0:w=iw:h=ih:color=white:t=fill:enable='between(t,2,3.99)'",
        "-c:v", "libx264", "-c:a", "aac", "-shortest", str(clip)], check=True)
    transcript = tmp_path / "t.json"
    transcript.write_text(json.dumps({"segments": [
        {"text": "سلام " * 10, "start": 0.0, "end": 6.0}]}, ensure_ascii=False), encoding="utf-8")

    llm = _FakeLLM()
    shots = [{"start_seconds": 0.0, "end_seconds": 2.0}, {"start_seconds": 2.0, "end_seconds": 4.0},
             {"start_seconds": 4.0, "end_seconds": 6.0}]
    confident = {"shot_size": ("wide", 0.9), "camera_angle": ("eye_level", 0.9), "content": ("illustration", 0.9)}
    unsure = {"shot_size": ("medium", 0.2), "camera_angle": ("eye_level", 0.9), "content": ("photo", 0.9)}
    tool = EditStyleExtractor(
        llm_selector=llm,
        scene_detector=lambda path, offset: shots,
        clip_labeler=lambda paths: [confident, unsure, confident][: len(paths)],
    )
    r = tool.execute({"input_path": str(clip), "name": "test-learned", "work_dir": str(tmp_path / "work"),
                      "transcript_path": str(transcript), "editing_dir": str(tmp_path / "editing"),
                      "max_frames": 3})
    assert r.success, r.error
    card = load_edit_style("test-learned", editing_dir=tmp_path / "editing")
    assert card["source"]["kind"] == "learned"
    assert card["source"]["measured"]["asl_seconds"] == 2.0
    assert card["pacing"]["words_per_minute"] == 100.0
    assert card["hook_formula"]["beats"] == ["big number", "paradox"]
    batch = next(c for c in llm.calls if c.get("operation") == "batch")
    assert [it["id"] for it in batch["items"]] == ["1"]  # only the frame CLIP was unsure about
    assert r.cost_usd == pytest.approx(0.0006)
    report = json.loads((tmp_path / "work" / "report.json").read_text(encoding="utf-8"))
    assert report["hook_status"] == "draft_for_agent_review"
