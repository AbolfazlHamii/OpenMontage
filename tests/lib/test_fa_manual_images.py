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


def _speech(rate, pattern):
    """Tone for each positive length, silence for each negative one (seconds)."""
    import numpy as np

    parts = []
    for sec in pattern:
        n = int(abs(sec) * rate)
        parts.append(np.zeros(n) if sec < 0 else 8000 * np.sin(np.arange(n) * 2 * np.pi * 140 / rate))
    return np.concatenate(parts).astype(np.int16)


def test_split_on_pauses_cuts_at_scene_breaths_not_commas():
    rate = 8000
    # scene A (2 s with a short comma pause), long breath, scene B (1 s), breath, scene C (1 s)
    samples = _speech(rate, [0.9, -0.2, 1.1, -0.7, 1.0, -0.6, 1.0])
    bounds = mi.split_on_pauses(samples, rate, [20, 10, 10])
    cuts = [b / rate for _, b in bounds[:-1]]
    assert cuts[0] == pytest.approx(2.2 + mi.CLIP_PAD, abs=0.02)
    assert cuts[1] == pytest.approx(3.9 + mi.CLIP_PAD, abs=0.02)
    assert bounds[1][0] / rate == pytest.approx(2.9 - mi.CLIP_PAD, abs=0.02)


def test_scene_breaks_follow_the_transcript_despite_spelling():
    texts = ["سال هزار و نهصد و هفده بود.", "یه کمیسیونِ ویژه درست می‌کنن."]
    # the transcriber writes the year as digits and splits a word differently
    heard = [("سال", 0.0, 0.3), ("1917", 0.3, 1.4), ("بود", 1.4, 1.7),
             ("یک", 2.3, 2.5), ("کمیسیون", 2.5, 3.0), ("ویژه", 3.0, 3.3), ("درست", 3.3, 3.6), ("میکنن", 3.6, 4.0)]
    words = [{"word": w, "start": a, "end": b} for w, a, b in heard]
    assert mi.scene_breaks_from_words(words, texts) == [pytest.approx(2.0)]


def test_split_follows_transcript_breaks_over_letter_shares():
    rate = 8000
    # letter shares say the first scene is the long one; the transcript says it ends at 1.25 s
    samples = _speech(rate, [1.0, -0.5, 2.0, -0.4, 1.0])
    bounds = mi.split_on_pauses(samples, rate, [30, 10], breaks=[1.25])
    assert bounds[0][1] / rate == pytest.approx(1.0 + mi.CLIP_PAD, abs=0.02)


def test_narrate_voices_a_group_in_one_call_and_splits_it(project):
    import wave

    rate, calls = 8000, []

    class TTS:
        def execute(self, inputs):
            calls.append(inputs)
            with wave.open(inputs["output_path"], "wb") as w:
                w.setnchannels(1), w.setsampwidth(2), w.setframerate(rate)
                w.writeframes(_speech(rate, [2.0, -0.7, 1.0]).tobytes())
            return ToolResult(success=True, data={}, cost_usd=0.003)

    data = json.loads((project / "manual_images" / "shotlist.json").read_text(encoding="utf-8"))
    data["voice"]["groups"] = ["s1"]
    (project / "manual_images" / "shotlist.json").write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")
    (project / "manual_images" / "audio").mkdir(parents=True)

    def seconds(path):
        with wave.open(str(path)) as w:
            return w.getnframes() / w.getframerate()

    out = mi.narrate(project, tts=TTS(), duration=seconds)
    assert len(calls) == 1 and "\n\n" in calls[0]["text"]
    assert out["clips"]["s1"]["seconds"] == pytest.approx(2.0 + mi.CLIP_PAD, abs=0.02)
    assert out["clips"]["s2"]["seconds"] == pytest.approx(1.0 + mi.CLIP_PAD, abs=0.02)
    mi.narrate(project, tts=TTS(), duration=seconds)
    assert len(calls) == 1


def test_titles_are_typed_on_their_shot_and_give_way_to_the_next(project, tmp_path):
    data = mi.load_shotlist(project)
    data["scenes"][0]["shots"][0]["title"] = ["WINTER 1917", "PETROGRAD, RUSSIA"]
    data["scenes"][0]["shots"][1]["title"] = "LEE BYUNG-CHUL"
    timing = mi.plan_timing(data, {"s1": {"seconds": 6.0}, "s2": {"seconds": 3.0}})
    first, second = timing["titles"]
    shots = {s["id"]: s for s in timing["shots"]}
    assert first["start"] == pytest.approx(shots["s1a"]["start"] + mi.TITLE_LEAD)
    assert second["start"] == pytest.approx(shots["s1b"]["start"] + mi.TITLE_LEAD)
    assert first["end"] <= second["start"] - 0.15 + 1e-6
    assert second["end"] - second["start"] == pytest.approx(mi.TITLE_HOLD)

    data["scenes"][1]["shots"][0]["title"] = ["a", "b", "c"]
    assert any("title must be one or two lines" in p for p in mi.validate(data))


def test_workspace_types_the_titles(project, tmp_path):
    data = json.loads((project / "manual_images" / "shotlist.json").read_text(encoding="utf-8"))
    data["scenes"][1]["shots"][0]["title"] = ["GUMI, 1995"]
    (project / "manual_images" / "shotlist.json").write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")
    for shot in ("s1a", "s1b", "s2"):
        _image(project / "manual_images" / "in" / f"{shot}.png")
    for name in ("a.wav", "b.wav"):
        (tmp_path / name).write_bytes(b"wav")
    clips = {"s1": {"path": str(tmp_path / "a.wav"), "seconds": 6.0},
             "s2": {"path": str(tmp_path / "b.wav"), "seconds": 3.0}}
    mi.build_workspace(project, clips)
    page = (project / "manual_images" / "workspace" / "index.html").read_text(encoding="utf-8")
    assert 'id="title-0"' in page and 'id="tc-0-0-9"' in page and 'id="cur-0-0"' in page
    assert '"type_step": 0.045' in page


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
    assert seen["loud"]["true_peak"] == -2.5
    assert out["output"].endswith("manual_images.mp4")


def test_cli_prompts_and_status(project, capsys):
    from scripts import fa_manual_images as cli

    assert cli.main(["prompts", "--project", str(project)]) == 0
    assert json.loads(capsys.readouterr().out)["prompts"] == 3
    assert cli.main(["status", "--project", str(project)]) == 0
    assert "0/3 images" in json.loads(capsys.readouterr().out)["status"]


# -- ZAPI FLOW -------------------------------------------------------------------

def test_zapi_file_has_one_line_per_shot_in_order(project):
    pack = mi.write_prompt_pack(project)
    lines = Path(pack["zapi_flow"]).read_text(encoding="utf-8").splitlines()
    assert len(lines) == 3
    assert lines[1].startswith("A 1938 shop with dried fish.")
    assert all("\n" not in line and "No text" in line for line in lines)
    assert json.loads((project / "manual_images" / "zapi_flow_order.json").read_text(encoding="utf-8")) == ["s1a", "s1b", "s2"]
    assert "zapi-all" in (project / "manual_images" / "prompts.html").read_text(encoding="utf-8")


def test_characters_are_written_into_each_prompt(project):
    data = json.loads((project / "manual_images" / "shotlist.json").read_text(encoding="utf-8"))
    data["style"]["characters"] = {"Lenin": "bald man with a pointed beard, dark three-piece suit"}
    data["scenes"][1]["shots"][0]["characters"] = ["Lenin"]
    assert mi.validate(data) == []
    prompt = mi.full_prompt(data["scenes"][1]["shots"][0], data["style"])
    assert "Characters: Lenin: bald man with a pointed beard" in prompt
    data["scenes"][0]["shots"][0]["characters"] = ["Stalin"]
    assert any("'Stalin' is not in style.characters" in p for p in mi.validate(data))


def _downloads(folder: Path, names: list[str]) -> None:
    import os
    import time

    for k, name in enumerate(names):
        _image(folder / name)
        stamp = time.time() - 100 + k
        os.utime(folder / name, (stamp, stamp))


def test_import_by_serial_maps_rows_and_keeps_alternates(project, tmp_path):
    mi.write_prompt_pack(project)
    dl = tmp_path / "flow"
    _downloads(dl, ["2_a_1938_shop.png", "1_a_hand.png", "3_bonfire.png", "3_bonfire (1).png"])
    report = mi.import_flow(project, dl)
    assert report["by"] == "serial"
    assert {c["shot"]: c["from"] for c in report["copied"]} == {
        "s1a": "1_a_hand.png", "s1b": "2_a_1938_shop.png", "s2": "3_bonfire.png"}
    assert report["alternates"] == 1
    assert (project / "manual_images" / "in" / "alts" / "s2_alt1.png").exists()
    assert report["still_missing"] == []
    assert mi.check_images(project)["ready"]


def test_import_falls_back_to_download_order(project, tmp_path):
    mi.write_prompt_pack(project)
    dl = tmp_path / "flow"
    # No serial toggle: names carry prompt words (1938 is out of range), so time order wins.
    _downloads(dl, ["hand.png", "shop_1938.png"])
    report = mi.import_flow(project, dl)
    assert report["by"] == "time"
    assert [c["shot"] for c in report["copied"]] == ["s1a", "s1b"]
    assert report["still_missing"] == ["s2"]


def test_import_keeps_existing_images_unless_overwrite(project, tmp_path):
    mi.write_prompt_pack(project)
    _image(project / "manual_images" / "in" / "s1a.jpg")
    dl = tmp_path / "flow"
    _downloads(dl, ["1.png", "2.png", "3.png"])
    assert mi.import_flow(project, dl)["kept_existing"] == ["s1a"]
    again = mi.import_flow(project, dl, overwrite=True)
    assert "s1a" in [c["shot"] for c in again["copied"]]
    assert not (project / "manual_images" / "in" / "s1a.jpg").exists()
    assert (project / "manual_images" / "in" / "s1a.png").exists()


# -- cues and caption-free builds --------------------------------------------------

def _cued(cue: str | None, second_cue: str | None = None) -> dict:
    data = json.loads(json.dumps(SHOTLIST))
    shots = data["scenes"][0]["shots"]
    shots.append({"id": "s1c", "prompt": "A third still.", "camera": "still"})
    if cue:
        shots[1]["cue"] = cue
    if second_cue:
        shots[2]["cue"] = second_cue
    return data


CLIPS = {"s1": {"seconds": 10.0}, "s2": {"seconds": 4.0}}


def test_cue_starts_the_shot_where_its_words_are_spoken():
    data = _cued("ولی می‌دونستی")
    timing = mi.plan_timing(data, CLIPS)
    s1b = next(s for s in timing["shots"] if s["id"] == "s1b")
    text = data["scenes"][0]["narration"]
    share = mi._letters(text[:text.find("ولی می‌دونستی")]) / mi._letters(text)
    assert s1b["start"] == pytest.approx(mi.LEAD_IN + 10.0 * share - mi.CUE_LEAD, abs=0.01)
    # the uncued shot after it shares the rest of the scene with it by weight
    s1c = next(s for s in timing["shots"] if s["id"] == "s1c")
    scene_end = timing["scenes"][0]["end"]
    assert s1c["end"] == pytest.approx(scene_end, abs=0.01)
    assert (s1c["start"] - s1b["start"]) == pytest.approx(2 * (scene_end - s1c["start"]), abs=0.02)


def test_without_cues_shots_split_by_weight_as_before():
    timing = mi.plan_timing(json.loads(json.dumps(SHOTLIST)), CLIPS)
    a, b = [s for s in timing["shots"] if s["scene"] == "s1"]
    assert (b["end"] - b["start"]) == pytest.approx(2 * (a["end"] - a["start"]), abs=0.01)


def test_cues_out_of_order_and_unknown_cues_are_rejected():
    with pytest.raises(ValueError, match="out of order"):
        mi.plan_timing(_cued("ماهی خشک", "احتمالاً گوشیِ"), CLIPS)
    assert any("is not in the scene's narration" in p for p in mi.validate(_cued("کلمه‌ای که نیست")))


def test_captions_can_be_switched_off():
    data = json.loads(json.dumps(SHOTLIST))
    data["captions"] = False
    assert mi.plan_timing(data, CLIPS)["captions"] == []


def test_preview_builds_the_first_scenes_and_borrows_missing_stills(project, monkeypatch):
    class TTS:
        def execute(self, inputs):
            Path(inputs["output_path"]).parent.mkdir(parents=True, exist_ok=True)
            Path(inputs["output_path"]).write_bytes(b"wav")
            return ToolResult(success=True, data={}, cost_usd=0.0)

    monkeypatch.delenv("SUBTITLE_FONTS_DIR", raising=False)
    _image(project / "manual_images" / "in" / "s1a.png")
    # s1 runs ~6.6 s and s2 starts after it: a 5 s preview keeps only s1.
    out = mi.preview(project, 5.0, tts=TTS(), duration=lambda p: 6.0)
    assert out["scenes"] == ["s1"]
    assert out["borrowed"] == {"s1b": "s1a"}
    work = Path(out["workdir"])
    assert work.parent == project / "manual_images" / "preview"
    assert sorted(p.name for p in (work / "manual_images" / "in").iterdir()) == ["s1a.png", "s1b.png"]
    assert (work / "manual_images" / "workspace" / "index.html").exists()
    # the real project's inbox is untouched
    assert not (project / "manual_images" / "in" / "s1b.png").exists()
    with pytest.raises(RuntimeError, match="no images yet"):
        (project / "manual_images" / "in" / "s1a.png").unlink()
        mi.preview(project, 5.0, tts=TTS(), duration=lambda p: 6.0)


def test_preview_window_starts_at_whole_scenes(project, monkeypatch):
    class TTS:
        def execute(self, inputs):
            Path(inputs["output_path"]).parent.mkdir(parents=True, exist_ok=True)
            Path(inputs["output_path"]).write_bytes(b"wav")
            return ToolResult(success=True, data={}, cost_usd=0.0)

    monkeypatch.delenv("SUBTITLE_FONTS_DIR", raising=False)
    _image(project / "manual_images" / "in" / "s2.png")
    out = mi.preview(project, 30.0, from_seconds=5.0, tts=TTS(), duration=lambda p: 6.0)
    assert out["scenes"] == ["s2"]
    with pytest.raises(RuntimeError, match="no scene starts"):
        mi.preview(project, 30.0, from_seconds=20.0, tts=TTS(), duration=lambda p: 6.0)


def test_music_sections_cross_fade_and_carry_into_a_window():
    timing = {"duration": 30.0, "scenes": [{"id": "a", "start": 0.0}, {"id": "b", "start": 10.0}, {"id": "c", "start": 20.0}]}
    cfg = {"sections": [{"from": "a", "path": "m1.mp3"}, {"from": "c", "path": "m2.mp3"}]}
    tracks = mi.music_tracks(cfg, timing)
    assert [(t["path"], t["start"], t["end"]) for t in tracks] == [("m1.mp3", 0.0, 20.0 + mi.MUSIC_XFADE), ("m2.mp3", 20.0, 30.0)]
    # A window that opens on scene b: the section from a is still playing.
    window = {"duration": 15.0, "scenes": [{"id": "b", "start": 0.0}, {"id": "c", "start": 8.0}]}
    cfg_window = dict(cfg, active_at_start=cfg["sections"][0])
    assert [(t["path"], t["start"]) for t in mi.music_tracks(cfg_window, window)] == [("m1.mp3", 0.0), ("m2.mp3", 8.0)]
    assert mi.music_tracks({}, timing) == []


def test_ducked_music_dips_under_voice_and_drops_before_a_cue(monkeypatch):
    from tools.audio import music_duck
    from tools.audio.music_duck import level_at

    timing = {"duration": 20.0, "scenes": [
        {"id": "a", "start": 0.0, "voice_start": 0.0, "voice_seconds": 8.0},
        {"id": "b", "start": 10.0, "voice_start": 10.0, "voice_seconds": 6.0}]}
    data = {"scenes": [{"id": "a", "narration": "یک دو سه. اسمش؟ کیم"}, {"id": "b", "narration": "پایان"}]}
    said = {"a.wav": [(0.0, 3.0), (3.8, 8.0)], "b.wav": [(0.0, 6.0)]}
    monkeypatch.setattr(music_duck, "speech_segments",
                        lambda path, offset=0.0: [(a + offset, b + offset) for a, b in said[path.name]])
    clips = {"a": {"path": "a.wav"}, "b": {"path": "b.wav"}}
    cfg = {"duck": {"under": 0.1, "gaps": 0.3}, "drops": [{"scene": "a", "cue": "اسمش"}],
           "sections": [{"from": "a", "path": "m1.mp3", "gain": 2.0, "fade_in": 0.0},
                        {"from": "b", "path": "m2.mp3"}]}
    first, second = mi.music_mix(cfg, data, timing, clips)
    assert level_at(first["keys"], 1.5) == pytest.approx(0.2)    # under the voice, times the gain
    assert level_at(first["keys"], 8.9) == pytest.approx(0.6)    # pause between scenes
    assert level_at(first["keys"], 3.6) == pytest.approx(0.0)    # dropped in the pause before the cue
    assert level_at(second["keys"], 3.0) == pytest.approx(0.1)
    assert "keys" not in mi.music_mix({"sections": cfg["sections"]}, data, timing, clips)[0]


def test_workspace_places_section_music(project, tmp_path, monkeypatch):
    inbox = project / "manual_images" / "in"
    for shot in ("s1a", "s1b", "s2"):
        _image(inbox / f"{shot}.png")
    for name in ("a.wav", "b.wav", "m1.mp3"):
        (tmp_path / name).write_bytes(b"x")
    monkeypatch.delenv("SUBTITLE_FONTS_DIR", raising=False)
    data = json.loads((project / "manual_images" / "shotlist.json").read_text(encoding="utf-8"))
    data["music"] = {"volume": 0.15, "sections": [{"from": "s1", "path": str(tmp_path / "m1.mp3")},
                                                  {"from": "s2", "path": "missing.mp3"}]}
    (project / "manual_images" / "shotlist.json").write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")
    clips = {"s1": {"path": str(tmp_path / "a.wav"), "seconds": 6.0}, "s2": {"path": str(tmp_path / "b.wav"), "seconds": 3.0}}
    out = mi.build_workspace(project, clips)
    page = (project / "manual_images" / "workspace" / "index.html").read_text(encoding="utf-8")
    assert 'id="bgm-0"' in page and 'id="bgm-1"' not in page
    assert any("missing.mp3 not found" in w for w in out["warnings"])


def test_sfx_events_from_scene_changes_marks_and_beds():
    data = json.loads(json.dumps(SHOTLIST))
    timing = mi.plan_timing(data, CLIPS)
    cfg = {"scene_change": "swish", "flash": "whoosh",
           "marks": [{"scene": "s1", "cue": "ماهی خشک", "sfx": "hit"}, {"scene": "s1", "cue": "نیست", "sfx": "hit"}],
           "beds": [{"scene": "s2", "sfx": "crackle", "seconds": 4}]}
    events = mi.sfx_events(cfg, data, timing)
    kinds = [(e["sfx"], e["kind"]) for e in events]
    assert ("whoosh", "cut") in kinds          # s2 is a flash transition
    assert ("hit", "mark") in kinds and ("crackle", "mark") in kinds
    assert sum(1 for e in events if e["sfx"] == "hit") == 1   # an unknown cue is skipped
    s1 = timing["scenes"][0]
    hit = next(e for e in events if e["sfx"] == "hit")
    assert s1["voice_start"] < hit["at"] < s1["voice_start"] + s1["voice_seconds"]


def test_workspace_adds_placed_sound_effects(project, tmp_path, monkeypatch):
    import wave

    lib = tmp_path / "sfxlib"
    lib.mkdir()
    for name in ("whoosh.wav", "hit.wav"):
        with wave.open(str(lib / name), "wb") as w:
            w.setnchannels(1); w.setsampwidth(2); w.setframerate(8000); w.writeframes(b"\x00\x00" * 4000)
    (lib / "library.json").write_text(json.dumps({"name": "t", "files": {
        "whoosh": {"file": "whoosh.wav", "duration": 0.5, "peak_s": 0.1, "sustain_s": 0.05},
        "hit": {"file": "hit.wav", "duration": 0.5, "peak_s": 0.01, "sustain_s": 0.05}}}), encoding="utf-8")
    inbox = project / "manual_images" / "in"
    for shot in ("s1a", "s1b", "s2"):
        _image(inbox / f"{shot}.png")
    for name in ("a.wav", "b.wav"):
        (tmp_path / name).write_bytes(b"x")
    monkeypatch.delenv("SUBTITLE_FONTS_DIR", raising=False)
    data = json.loads((project / "manual_images" / "shotlist.json").read_text(encoding="utf-8"))
    data["sfx"] = {"library": str(lib), "flash": "whoosh", "marks": [{"scene": "s1", "cue": "ماهی خشک", "sfx": "hit"}]}
    (project / "manual_images" / "shotlist.json").write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")
    clips = {"s1": {"path": str(tmp_path / "a.wav"), "seconds": 6.0}, "s2": {"path": str(tmp_path / "b.wav"), "seconds": 3.0}}
    out = mi.build_workspace(project, clips)
    page = (project / "manual_images" / "workspace" / "index.html").read_text(encoding="utf-8")
    assert "assets/sfx/whoosh.wav" in page and "assets/sfx/hit.wav" in page, out["warnings"]
    assert (project / "manual_images" / "workspace" / "assets" / "sfx" / "hit.wav").exists()


def test_long_stills_get_punch_in_cuts():
    shot = {"id": "x", "start": 10.0, "end": 18.0, "camera": "pan_left", "focus": [0.5, 0.45]}
    assert len(mi.shot_moves(shot)) == 1
    moves = mi.shot_moves(shot, max_still=3.0, punch_focus=[0.3, 0.3])
    assert len(moves) == 3
    assert moves[0]["from"] == mi.camera_from_to("pan_left", [0.5, 0.45])[0]
    assert moves[1]["from"][:2] == (0.3, 0.3) and moves[1]["from"][2] > 1.3     # the punch-in
    assert moves[2]["from"][2] < moves[1]["from"][2]                           # back out wide
    assert moves[0]["start"] == 10.0 and moves[-1]["end"] == 18.0
    assert all(abs((m["end"] - m["start"]) - 8 / 3) < 0.01 for m in moves)


def test_a_shot_can_reuse_another_shots_image(project, tmp_path, monkeypatch):
    data = json.loads((project / "manual_images" / "shotlist.json").read_text(encoding="utf-8"))
    data["scenes"][1]["shots"].append({"id": "s2b", "image": "s1a", "camera": "push_in"})
    assert mi.validate(data) == []
    bad = json.loads(json.dumps(data)); bad["scenes"][1]["shots"][1]["image"] = "nope"
    assert any("not a shot with its own image" in p for p in mi.validate(bad))
    (project / "manual_images" / "shotlist.json").write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")
    pack = mi.write_prompt_pack(project)
    assert len(Path(pack["zapi_flow"]).read_text(encoding="utf-8").splitlines()) == 3   # no prompt for s2b
    for shot in ("s1a", "s1b", "s2"):
        _image(project / "manual_images" / "in" / f"{shot}.png")
    assert mi.check_images(project)["ready"] and mi.status(project).missing == []
    for name in ("a.wav", "b.wav"):
        (tmp_path / name).write_bytes(b"x")
    monkeypatch.delenv("SUBTITLE_FONTS_DIR", raising=False)
    clips = {"s1": {"path": str(tmp_path / "a.wav"), "seconds": 6.0}, "s2": {"path": str(tmp_path / "b.wav"), "seconds": 3.0}}
    mi.build_workspace(project, clips)
    assert (project / "manual_images" / "workspace" / "assets" / "img" / "s2b.png").exists()


def test_preview_handles_a_reused_image(project, monkeypatch):
    class TTS:
        def execute(self, inputs):
            Path(inputs["output_path"]).parent.mkdir(parents=True, exist_ok=True)
            Path(inputs["output_path"]).write_bytes(b"wav")
            return ToolResult(success=True, data={}, cost_usd=0.0)

    data = json.loads((project / "manual_images" / "shotlist.json").read_text(encoding="utf-8"))
    data["scenes"][1]["shots"].append({"id": "s2b", "image": "s1a", "camera": "pull_out"})
    (project / "manual_images" / "shotlist.json").write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")
    monkeypatch.delenv("SUBTITLE_FONTS_DIR", raising=False)
    _image(project / "manual_images" / "in" / "s1a.png")
    _image(project / "manual_images" / "in" / "s2.png")
    out = mi.preview(project, 30.0, from_seconds=5.0, tts=TTS(), duration=lambda p: 6.0)
    assert out["scenes"] == ["s2"] and "s2b" not in out["borrowed"]
    assert (Path(out["workdir"]) / "manual_images" / "in" / "s2b.png").exists()
