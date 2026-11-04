"""lib/fa_dub stages with fake tools: no network, no Demucs, no ffmpeg."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from lib import channel_bible as cb
from lib import fa_dub
from tools.base_tool import ToolResult

RAW = [
    {"speaker": "A", "start": 2.5, "end": 4.0, "text": "Okay Leo, quick question."},
    {"speaker": "A", "start": 4.1, "end": 6.0, "text": "What do they have in common?"},
    {"speaker": "B", "start": 6.4, "end": 8.0, "text": "Nothing."},
    {"speaker": "A", "start": 8.5, "end": 12.0, "text": "It's the microwave."},
]


def _words(raw):
    out = []
    for seg in raw:
        parts = seg["text"].split()
        step = (seg["end"] - seg["start"]) / len(parts)
        out += [{"word": w.strip(",.?"), "start": seg["start"] + i * step,
                 "end": seg["start"] + (i + 1) * step} for i, w in enumerate(parts)]
    return out


TURNS = [{"speaker": "A", "text": "Okay Leo, quick question. What do they have in common?"},
         {"speaker": "B", "text": "Nothing."},
         {"speaker": "A", "text": "It's the microwave."}]


class FakeStems:
    def execute(self, inputs):
        out = Path(inputs["output_dir"])
        out.mkdir(parents=True, exist_ok=True)
        (out / "vocals.wav").write_bytes(b"v")
        (out / "accompaniment.wav").write_bytes(b"m")
        return ToolResult(success=True, data={"vocals": str(out / "vocals.wav"),
                                              "accompaniment": str(out / "accompaniment.wav")})


class FakeSTT:
    def __init__(self, text="", words=None):
        self.calls, self.text, self.words = [], text, words or []

    def execute(self, inputs):
        self.calls.append(inputs)
        return ToolResult(success=True, data={"text": self.text, "words": self.words},
                          cost_usd=0.001)


class FakeLLM:
    def __init__(self, lines):
        self.lines, self.calls = lines, []

    def execute(self, inputs):
        self.calls.append(inputs)
        return ToolResult(success=True, data={"json": {"lines": self.lines}, "model": "fake"},
                          cost_usd=0.002)


def _touch(cmd):
    Path(cmd[-1]).parent.mkdir(parents=True, exist_ok=True)
    Path(cmd[-1]).write_bytes(b"x")


@pytest.fixture
def project(tmp_path, monkeypatch):
    monkeypatch.setenv("OPENMONTAGE_CHANNELS_DIR", str(tmp_path / "channels"))
    cb.create_channel("fa-test")
    voices = cb.channel_path("fa-test") / "voices.yaml"
    voices.write_text(voices.read_text(encoding="utf-8").replace(
        "dub_pool: []", "dub_pool: [Charon, Kore, Puck]\naudition_x:\n  - {voice: Charon, cps: 10.0}\n"
                        "  - {voice: Charon, cps: 9.0}"), encoding="utf-8")
    proj = tmp_path / "proj"
    (proj / "renders").mkdir(parents=True)
    source = proj / "source.mp4"
    source.write_bytes(b"video")
    fa_dub.prepare(proj, source, channel="fa-test", rights="own", stems_tool=FakeStems(),
                   stt=FakeSTT(words=_words(RAW)), labeler=lambda path, secs: ({"turns": TURNS, "speakers": {"A": "male", "B": "female"}}, 0.004),
                   run=_touch)
    return proj


def test_merge_turns_joins_close_same_speaker_chunks():
    lines = fa_dub.merge_turns(RAW)
    assert [(l["id"], l["speaker"], l["start"], l["end"]) for l in lines] == [
        ("s001", "A", 2.5, 6.0), ("s002", "B", 6.4, 8.0), ("s003", "A", 8.5, 12.0)]
    assert lines[0]["text"] == "Okay Leo, quick question. What do they have in common?"
    # A long run is split at max_len.
    assert len(fa_dub.merge_turns(RAW, max_len=2.0)) == 4


def test_prepare_writes_meta_and_lines(project):
    meta = json.loads((project / "dub" / "meta.json").read_text(encoding="utf-8"))
    assert meta["rights"] == "own" and meta["channel"] == "fa-test"
    assert meta["cost_usd"] == {"transcription": 0.001, "speaker_labels": 0.004}
    lines = fa_dub.load_segments(project, "segments_en.json")
    assert [(l["speaker"], l["start"], l["end"]) for l in lines] == [
        ("A", 2.5, 6.0), ("B", 6.4, 8.0), ("A", 8.5, 12.0)]
    with pytest.raises(ValueError):
        fa_dub.prepare(project, project / "source.mp4", rights="maybe")


def test_align_turns_tolerates_transcript_differences():
    words = _words([{"start": 0.0, "end": 3.0, "text": "it was nineteen forty five and"},
                    {"start": 3.2, "end": 4.0, "text": "really wow"},
                    {"start": 4.5, "end": 6.0, "text": "then he left"}])
    turns = [{"speaker": "A", "text": "It was 1945, and"},
             {"speaker": "B", "text": "Really? Wow."},
             {"speaker": "A", "text": "Then he left."}]
    lines = fa_dub.align_turns(turns, words)
    assert [(l["speaker"], round(l["start"], 2), round(l["end"], 2)) for l in lines] == [
        ("A", 0.0, 3.0), ("B", 3.2, 4.0), ("A", 4.5, 6.0)]


class _Resp:
    def __init__(self, payload, status=200):
        self.status_code, self._payload, self.text = status, payload, ""

    def json(self):
        return self._payload


def test_gemini_turns_posts_audio_and_guards_against_no_audio(tmp_path, monkeypatch):
    monkeypatch.setenv("AVALAI_API_KEY", "k")
    wav = tmp_path / "a.wav"
    wav.write_bytes(b"RIFF")
    answer = {"candidates": [{"content": {"parts": [{"text": json.dumps(
        {"turns": TURNS, "speakers": {"A": "male", "B": "female"}})}]}}],
              "usageMetadata": {"promptTokenCount": 5000, "candidatesTokenCount": 300}}
    sent = {}

    def post(url, headers, json, timeout):
        sent.update(url=url, body=json)
        return _Resp(answer)

    labels, cost = fa_dub.gemini_turns(wav, 150.0, post=post)
    assert labels["turns"] == TURNS and labels["speakers"]["B"] == "female" and cost > 0
    assert sent["url"].endswith("/v1beta/models/gemini-3.8-flash:generateContent")
    assert sent["body"]["contents"][0]["parts"][0]["inlineData"]["mimeType"] == "audio/wav"
    answer["usageMetadata"]["promptTokenCount"] = 300
    with pytest.raises(RuntimeError, match="without the audio"):
        fa_dub.gemini_turns(wav, 150.0, post=post)


def test_voice_map_is_stable_and_follows_pool():
    segs = [{"speaker": "B", "start": 0}, {"speaker": "A", "start": 1}, {"speaker": "B", "start": 2}]
    first = fa_dub.map_voices(segs, ["Charon", "Kore"])
    assert first == {"B": "Charon", "A": "Kore"}
    assert fa_dub.map_voices(segs + [{"speaker": "C", "start": 3}], ["Charon", "Kore"], first)["B"] == "Charon"
    with pytest.raises(ValueError):
        fa_dub.map_voices(segs, [])
    # Gender wins over pool order: B is a woman, so she gets Kore.
    assert fa_dub.map_voices(segs, ["Charon", "Kore", "Puck"], genders={"B": "female", "A": "male"}) == {
        "B": "Kore", "A": "Charon"}


def test_styles_from_analysis_by_overlap():
    assert fa_dub.style_for("excited, curious", "high") == "محاوره‌ی تهرانی، پرانرژی، هیجان‌زده، کنجکاو"
    segs = [{"id": "s001", "start": 2.5, "end": 6.0}, {"id": "s002", "start": 40, "end": 42}]
    analysis = {"segments": [{"start": "00:00", "end": "00:05", "emotion": "calm", "energy": "low"},
                             {"start": "00:05", "end": "00:20", "emotion": "tense", "energy": "high"}]}
    styles = fa_dub.styles_from_analysis(segs, analysis)
    assert "آرام" in styles["s001"]
    assert styles["s002"] == "محاوره‌ی تهرانی"


def test_translate_budgets_from_voice_cps_and_marks_drafts(project):
    llm = FakeLLM([{"id": "s001", "fa": "لئو، یه سؤال"}, {"id": "s002", "fa": "هیچی"},
                   {"id": "s003", "fa": "مایکروویو"}])
    fa_dub.draft_translation(project, llm=llm)
    rows = fa_dub.load_segments(project)
    assert [r["review"] for r in rows] == ["draft"] * 3
    assert rows[0]["voice"] == "Charon" and rows[1]["voice"] == "Kore"
    assert rows[0]["budget_letters"] == 33          # 3.5 s x 9.5 (Charon's audition average)
    assert rows[1]["budget_letters"] == 15          # 1.6 s x 9.5 default
    assert llm.calls[0]["task"] == "translation_draft_en_fa"
    assert '"max_letters": 33' in llm.calls[0]["prompt"]


def test_translate_refuses_missing_lines(project):
    with pytest.raises(RuntimeError, match="s002"):
        fa_dub.draft_translation(project, llm=FakeLLM([{"id": "s001", "fa": "x"}]))


def _translated(project):
    fa_dub.draft_translation(project, llm=FakeLLM(
        [{"id": "s001", "fa": "لئو، یه سؤال"}, {"id": "s002", "fa": "هیچی"}, {"id": "s003", "fa": "مایکروویو"}]))


def test_approve_records_owner_edits(project):
    _translated(project)
    path = project / "dub" / "segments_fa.json"
    rows = json.loads(path.read_text(encoding="utf-8"))
    rows[1]["text"] = "هیچی بابا"
    path.write_text(json.dumps(rows, ensure_ascii=False), encoding="utf-8")
    assert fa_dub.approve_lines(project) == 3
    examples = cb.load_channel("fa-test").path / "examples" / "proj.jsonl"
    entry = json.loads(examples.read_text(encoding="utf-8").splitlines()[0])
    assert entry["before"] == "هیچی" and entry["after"] == "هیچی بابا" and entry["stage"] == "dub_line"


def test_synth_needs_approval_then_fits_every_line(project):
    _translated(project)
    with pytest.raises(RuntimeError, match="not approved"):
        fa_dub.synthesize(project, tts=None, rewrite=None)
    fa_dub.approve_lines(project)
    calls = []

    def tts_execute(inputs):
        calls.append(inputs)
        Path(inputs["output_path"]).parent.mkdir(parents=True, exist_ok=True)
        Path(inputs["output_path"]).write_bytes(b"wav")
        return ToolResult(success=True, data={"audio_duration_seconds": 1.5}, cost_usd=0.001)

    tts = type("T", (), {"execute": staticmethod(tts_execute)})()
    summary = fa_dub.synthesize(project, tts=tts, rewrite=lambda *a: "x")
    assert summary["lines"] == 3 and summary["status"] == {"ok": 3}
    assert all(c["channel"] == "fa-test" and c["language_code"] == "fa" for c in calls)
    assert calls[0]["voice_id"] == "Charon" and calls[1]["voice_id"] == "Kore"
    assert summary["cost_usd"] == pytest.approx(0.003)
    fits = fa_dub.load_fits(project)
    assert fits[0].start == 2.5 and fits[0].end == 4.0


def test_voice_actor_round_trip(project, tmp_path):
    _translated(project)
    run_calls = []
    scripts = fa_dub.export_vo(project, run=lambda cmd: run_calls.append(cmd))
    assert {p.parent.name for p in scripts} == {"A", "B"}
    text = scripts[0].read_text(encoding="utf-8")
    assert "s001" in text and "ref/s001.wav" in text and "Okay Leo" in text
    assert run_calls[0][run_calls[0].index("-ss") + 1] == "2.500"

    takes = tmp_path / "takes"
    for speaker, ids in (("A", ["s001", "s003"]), ("B", ["s002"])):
        (takes / speaker).mkdir(parents=True)
        for i in ids:
            (takes / speaker / f"{i}.wav").write_bytes(b"take")
    summary = fa_dub.import_vo(project, takes, duration=lambda p: 1.0)
    assert summary["lines"] == 3
    data = json.loads((project / "dub" / "fits.json").read_text(encoding="utf-8"))
    assert data["source"] == "voice_actor"
    (takes / "B" / "s002.wav").unlink()
    with pytest.raises(FileNotFoundError, match="s002"):
        fa_dub.import_vo(project, takes, duration=lambda p: 1.0)


class FakeLoudness:
    def __init__(self, levels):
        self.levels = levels

    def measure(self, path, target, tp, lra):
        return {"input_i": self.levels.get(Path(path).name, -20.0), "input_tp": -2.0}

    def execute(self, inputs):
        Path(inputs["output_path"]).write_bytes(b"final")
        return ToolResult(success=True, data={})


def test_mix_matches_original_voice_level_and_tempo(project):
    _translated(project)
    fa_dub.approve_lines(project)
    fits = [
        fa_dub.Fit(id="s001", speaker="A", text="x", audio_path="clips/s001.wav", raw_seconds=3.7,
                   tempo=1.06, start=2.5, end=6.0, status="stretched"),
        fa_dub.Fit(id="s002", speaker="B", text="x", audio_path="clips/s002.wav", raw_seconds=1.0,
                   tempo=1.0, start=6.4, end=7.4, status="ok"),
    ]
    fa_dub._save_fits(project, fits, "tts")
    run_calls, mixed = [], {}

    class Mixer:
        def execute(self, inputs):
            mixed.update(inputs)
            return ToolResult(success=True, data={})

    loud = FakeLoudness({"vocals.wav": -12.0, "s001.wav": -16.0, "s002.wav": -40.0})
    out = fa_dub.mix(project, mixer=Mixer(), loudness=loud, run=lambda cmd: run_calls.append(cmd))
    filters = [c[c.index("-af") + 1] for c in run_calls if "-af" in c]
    assert filters[0] == "atempo=1.0600,volume=4.00dB"
    assert filters[1] == "volume=12.00dB"            # capped at +12 dB
    assert mixed["tracks"][0]["role"] == "music"
    assert [t["start_seconds"] for t in mixed["tracks"][1:]] == [2.5, 6.4]
    assert mixed["normalize"] is False
    assert out["output"].endswith("dub_fa.mp4")
    mux = run_calls[-1]
    assert mux[mux.index("-c:v") + 1] == "copy"


def test_qa_reports_overlaps_round_trip_loudness_and_rights(project):
    _translated(project)
    fits = [
        fa_dub.Fit(id="s001", speaker="A", text="لئو، یه سؤال", audio_path="a.wav", raw_seconds=4.0,
                   tempo=1.0, start=2.5, end=6.8, status="used_gap"),
        fa_dub.Fit(id="s002", speaker="B", text="هیچی", audio_path="b.wav", raw_seconds=1.0,
                   tempo=1.0, start=6.4, end=7.4, status="ok"),
    ]
    fa_dub._save_fits(project, fits, "tts")
    (project / "renders" / "dub_fa.mp4").write_bytes(b"x")
    meta_path = project / "dub" / "meta.json"
    meta = json.loads(meta_path.read_text(encoding="utf-8"))
    meta["rights"] = "unknown"
    meta_path.write_text(json.dumps(meta), encoding="utf-8")

    class STT:
        def execute(self, inputs):
            text = "لئو یه سؤال" if "s001" in inputs["output_path"] else "چیزی دیگه"
            return ToolResult(success=True, data={"text": text}, cost_usd=0.0005)

    class Loud(FakeLoudness):
        def measure(self, path, target, tp, lra):
            return {"input_i": -14.3, "input_tp": -1.2}

    report = fa_dub.qa(project, stt=STT(), loudness=Loud({}))
    assert report["overlaps"] == [{"id": "s001", "next": "s002", "overlap_seconds": 0.4}]
    assert report["unreviewed"] == ["s001", "s002", "s003"]
    assert [r["id"] for r in report["round_trip_low"]] == ["s002"]
    assert report["loudness"]["pass"] is True
    assert report["rights"] == "unknown" and report["warnings"]
    assert report["pass"] is False
    assert report["cost_usd"] == pytest.approx(0.001)


def test_qa_asks_again_on_the_raw_clip_when_the_placed_copy_scores_low(project):
    _translated(project)
    fa_dub.approve_lines(project)
    root = project / "dub"
    (root / "mix" / "placed").mkdir(parents=True)
    raw = root / "clips" / "s002_raw.wav"
    raw.parent.mkdir(parents=True)
    raw.write_bytes(b"raw")
    (root / "mix" / "placed" / "s002.wav").write_bytes(b"placed")
    fa_dub._save_fits(project, [fa_dub.Fit(id="s002", speaker="B", text="هیچی", audio_path=str(raw),
                                           raw_seconds=1.0, tempo=1.05, start=6.4, end=7.35,
                                           status="stretched")], "tts")
    calls = []

    class STT:
        def execute(self, inputs):
            calls.append(inputs["audio_path"])
            text = "هیچی" if inputs["audio_path"].endswith("s002_raw.wav") else "هیچ چیز دیگه"
            out = Path(inputs["output_path"])     # like avalai_stt, which saves the transcript
            out.parent.mkdir(parents=True, exist_ok=True)
            out.write_text(json.dumps({"text": text}, ensure_ascii=False), encoding="utf-8")
            return ToolResult(success=True, data={"text": text}, cost_usd=0.0002)

    report = fa_dub.qa(project, stt=STT(), loudness=FakeLoudness({}))
    assert report["round_trip_low"] == []
    assert len(calls) == 2 and calls[1].endswith("s002_raw.wav")
    # A repeat run reuses both transcripts.
    fa_dub.qa(project, stt=STT(), loudness=FakeLoudness({}))
    assert len(calls) == 2
