"""Manual-images mode: shot list, prompt pack, image check, narration, timing, workspace."""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from PIL import Image

from lib import fa_manual_images as mi
from tools.base_tool import ToolResult

SHOTLIST = {
    "title": "نمونه",
    "style": {"prompt": "Inked cartoon, sepia.", "references": ["ref/style.png"]},
    "voice": {"voice_id": "Kore", "providers": ["avalai"]},
    "scenes": [
        {"id": "s1", "narration": "احتمالاً گوشیِ توی دستت سامسونگه، ولی می‌دونستی این شرکت با ماهی خشک شروع شد؟",
         "caption": "احتمالاً گوشیِ توی دستت سامسونگه… ولی می‌دونستی این شرکت با ماهی خشک شروع شد؟",
         "stamp": "امروز",
         "shots": [{"id": "s1a", "prompt": "A hand holding a phone.", "camera": "push_in"},
                   {"id": "s1b", "prompt": "A 1938 shop with dried fish.", "camera": "pan_left", "weight": 2}]},
        {"id": "s2", "narration": "سال هزار و نهصد و نود و پنج همه چیز عوض شد.", "caption": "سال ۱۹۹۵ همه چیز عوض شد.",
         "transition": "flash", "stamp": "گومی، ۱۹۹۵",
         "shots": [{"id": "s2", "prompt": "A bonfire of phones."}]},
    ],
}


@pytest.fixture
def project(tmp_path):
    proj = tmp_path / "proj"
    (proj / "manual_images").mkdir(parents=True)
    (proj / "manual_images" / "shotlist.json").write_text(json.dumps(SHOTLIST, ensure_ascii=False), encoding="utf-8")
    return proj


def _image(path: Path, size=(1376, 768)):
    path.parent.mkdir(parents=True, exist_ok=True)
    Image.new("RGB", size, (200, 180, 150)).save(path)


def test_init_writes_a_template_once(tmp_path):
    path = mi.init(tmp_path / "p")
    assert json.loads(path.read_text(encoding="utf-8"))["scenes"][0]["shots"][0]["id"] == "s1a"
    assert (tmp_path / "p" / "manual_images" / "in").is_dir()
    with pytest.raises(FileExistsError):
        mi.init(tmp_path / "p")


def test_validate_reports_problems():
    bad = {"scenes": [{"id": "a", "shots": [{"id": "x y", "prompt": ""}, {"id": "z", "prompt": "p", "camera": "zoom"}]},
                      {"id": "b", "narration": "متن", "shots": [{"id": "z", "prompt": "p"}]}]}
    problems = " | ".join(mi.validate(bad))
    for expected in ("a: needs narration", "shot id must be", "x y", "camera must be one of", "duplicate shot id z"):
        assert expected in problems


def test_prompt_pack_has_every_shot_with_style_and_rules(project):
    out = mi.write_prompt_pack(project)
    assert out["prompts"] == 3
    md = (project / "manual_images" / "PROMPTS.md").read_text(encoding="utf-8")
    assert "`in/s1b.png`" in md and "Style: Inked cartoon, sepia." in md and "No text, letters" in md
    assert "`ref/style.png`" in md
    page = (project / "manual_images" / "prompts.html").read_text(encoding="utf-8")
    assert 'dir="rtl"' in page and 'id="p-s2"' in page and 'src="in/s2.png"' in page
    assert (project / "manual_images" / "in").is_dir()


def test_check_finds_missing_wrong_aspect_small_and_broken(project):
    inbox = project / "manual_images" / "in"
    _image(inbox / "s1a.png")
    _image(inbox / "s1b.jpg", size=(1024, 1024))
    (inbox / "s2.webp").write_bytes(b"not an image")
    report = mi.check_images(project)
    rows = {r["id"]: r for r in report["shots"]}
    assert rows["s1a"]["problems"] == []
    assert any("not 16:9" in p for p in rows["s1b"]["problems"])
    assert any("small" in p for p in rows["s1b"]["problems"])
    assert rows["s2"]["problems"][0].startswith("unreadable")
    assert report["ready"] is False
    (inbox / "s2.webp").unlink()
    report = mi.check_images(project)
    assert report["missing"] == ["s2"] and not report["ready"]


def test_caption_chunks_split_at_marks_and_balance():
    chunks = mi.caption_chunks("یک دو سه، چهار پنج شش هفت هشت نه ده یازده دوازده. سیزده")
    # 9 words over the 6-word limit -> two balanced lines (5 + 4), not 6 + 3
    assert chunks == ["یک دو سه،", "چهار پنج شش هفت هشت", "نه ده یازده دوازده.", "سیزده"]


def test_caption_lines_do_not_end_on_a_leaning_word():
    assert mi.caption_chunks("ولی می‌دونستی این شرکت با فروش ماهی خشک شروع شد؟") == [
        "ولی می‌دونستی این شرکت", "با فروش ماهی خشک شروع شد؟"]
    assert mi.caption_chunks("رئیس سامسونگ ۱۵۰ هزار تا گوشیِ خراب رو جلوی کارگرهاش آتیش زد!") == [
        "رئیس سامسونگ ۱۵۰ هزار", "تا گوشیِ خراب رو", "جلوی کارگرهاش آتیش زد!"]


def test_timing_follows_the_narration(project):
    clips = {"s1": {"seconds": 6.0}, "s2": {"seconds": 3.0}}
    timing = mi.plan_timing(mi.load_shotlist(project), clips)
    s1, s2 = timing["scenes"]
    assert s1["start"] == 0.0 and s1["voice_start"] == mi.LEAD_IN
    assert s1["end"] == pytest.approx(mi.LEAD_IN + 6.0 + mi.SCENE_TAIL)
    assert s2["start"] == s1["end"] and s2["voice_start"] == s1["end"]
    shots = {s["id"]: s for s in timing["shots"]}
    # weight 2: s1b gets two thirds of scene 1
    assert shots["s1b"]["end"] - shots["s1b"]["start"] == pytest.approx(2 * (shots["s1a"]["end"] - shots["s1a"]["start"]))
    assert shots["s2"]["camera"] in mi.CAMERAS
    caps = [c for c in timing["captions"] if c["scene"] == "s1"]
    assert caps[0]["start"] == pytest.approx(mi.LEAD_IN) and caps[-1]["end"] == pytest.approx(mi.LEAD_IN + 6.0)
    assert timing["duration"] > s2["end"]


def test_narrate_uses_tts_once_per_text_and_reuses_files(project, tmp_path):
    calls = []

    class TTS:
        def execute(self, inputs):
            calls.append(inputs)
            Path(inputs["output_path"]).parent.mkdir(parents=True, exist_ok=True)
            Path(inputs["output_path"]).write_bytes(b"wav")
            return ToolResult(success=True, data={}, cost_usd=0.002)

    out = mi.narrate(project, tts=TTS(), duration=lambda p: 4.0)
    assert len(calls) == 2 and out["cost_usd"] == pytest.approx(0.004)
    assert calls[0]["voice_id"] == "Kore" and calls[0]["allowed_providers"] == ["avalai"]
    again = mi.narrate(project, tts=TTS(), duration=lambda p: 4.0)
    assert len(calls) == 2 and again["cost_usd"] == 0

    data = json.loads((project / "manual_images" / "shotlist.json").read_text(encoding="utf-8"))
    (project / "own.wav").write_bytes(b"wav")
    data["scenes"][1]["audio"] = "own.wav"
    (project / "manual_images" / "shotlist.json").write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")
    out = mi.narrate(project, tts=TTS(), duration=lambda p: 2.5)
    assert out["clips"]["s2"]["source"] == "file"


def test_workspace_has_every_shot_caption_and_audio(project, tmp_path, monkeypatch):
    inbox = project / "manual_images" / "in"
    for shot in ("s1a", "s1b", "s2"):
        _image(inbox / f"{shot}.png")
    for name in ("a.wav", "b.wav"):
        (tmp_path / name).write_bytes(b"wav")
    monkeypatch.delenv("SUBTITLE_FONTS_DIR", raising=False)
    clips = {"s1": {"path": str(tmp_path / "a.wav"), "seconds": 6.0},
             "s2": {"path": str(tmp_path / "b.wav"), "seconds": 3.0}}
    out = mi.build_workspace(project, clips)
    page = (project / "manual_images" / "workspace" / "index.html").read_text(encoding="utf-8")
    assert out["shots"] == 3
    for shot in ("s1a", "s1b", "s2"):
        assert f'id="cam-{shot}"' in page and f"assets/img/{shot}.png" in page
    assert 'id="vo-s2"' in page and "گومی، ۱۹۹۵" in page and "۱۹۹۵" in page
    plan = json.loads(page.split("const PLAN = ")[1].split(";\n")[0])
    assert len(plan["flashes"]) == 1 and len(plan["moves"]) == 3
    assert (project / "manual_images" / "workspace" / "assets" / "js" / "gsap.min.js").exists()
    assert json.loads((project / "manual_images" / "timing.json").read_text(encoding="utf-8"))["shots"]


def test_build_refuses_missing_images(project):
    with pytest.raises(RuntimeError, match="s1a"):
        mi.build(project)


def test_render_normalizes_with_headroom(project, tmp_path):
    seen = {}

    class Compose:
        def execute(self, inputs):
            seen["compose"] = inputs
            Path(inputs["output_path"]).write_bytes(b"mp4")
            return ToolResult(success=True, data={})

    class Loud:
        def execute(self, inputs):
            seen["loud"] = inputs
            Path(inputs["output_path"]).write_bytes(b"mp4")
            return ToolResult(success=True, data={})

    out = mi.render(project, compose=Compose(), loudness=Loud())
    assert seen["compose"]["operation"] == "render_existing"
    assert seen["loud"]["true_peak"] == -1.5
    assert out["output"].endswith("manual_images.mp4")


def test_cli_prompts_and_status(project, capsys):
    from scripts import fa_manual_images as cli

    assert cli.main(["prompts", "--project", str(project)]) == 0
    assert json.loads(capsys.readouterr().out)["prompts"] == 3
    assert cli.main(["status", "--project", str(project)]) == 0
    assert "0/3 images" in json.loads(capsys.readouterr().out)["status"]
