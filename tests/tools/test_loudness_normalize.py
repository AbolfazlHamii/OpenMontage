"""loudness_normalize: measurement parsing and the second-pass command. No media."""

from __future__ import annotations

import subprocess

import pytest

from tools.audio.loudness_normalize import LoudnessNormalize, parse_loudnorm_json

FIRST_PASS = """[Parsed_loudnorm_0 @ 0000]
{
\t"input_i" : "-11.54",
\t"input_tp" : "-2.78",
\t"input_lra" : "1.50",
\t"input_thresh" : "-21.97",
\t"output_i" : "-14.06",
\t"output_tp" : "-5.25",
\t"output_lra" : "1.40",
\t"output_thresh" : "-24.39",
\t"normalization_type" : "dynamic",
\t"target_offset" : "0.06"
}
"""

AFTER = FIRST_PASS.replace('"-11.54"', '"-14.01"').replace('"-2.78"', '"-5.20"')


def test_parse_takes_the_last_measurement():
    m = parse_loudnorm_json("noise\n" + FIRST_PASS + "\n" + AFTER)
    assert m["input_i"] == -14.01
    assert "normalization_type" not in m


def test_parse_without_json_raises():
    with pytest.raises(ValueError):
        parse_loudnorm_json("no json here")


def test_second_pass_is_linear_with_measured_values():
    m = parse_loudnorm_json(FIRST_PASS)
    af = LoudnessNormalize.second_pass_filter(m, -14.0, -1.0, 11.0)
    assert af.startswith("loudnorm=I=-14.0:TP=-1.0:LRA=11.0")
    assert "measured_I=-11.54" in af and "offset=0.06" in af and "linear=true" in af
    assert af.endswith("aresample=48000")


def _fake_run(calls, outputs):
    def run(cmd, timeout=None, cwd=None):
        calls.append(cmd)
        if cmd[-1] == "-":  # measuring pass
            return subprocess.CompletedProcess(cmd, 0, "", outputs.pop(0))
        open(cmd[-1], "wb").close()
        return subprocess.CompletedProcess(cmd, 0, "", "")
    return run


def test_video_is_normalized_through_wav_and_remuxed(tmp_path, monkeypatch):
    src = tmp_path / "render.mp4"
    src.write_bytes(b"x")
    tool = LoudnessNormalize()
    calls = []
    monkeypatch.setattr(tool, "run_command", _fake_run(calls, [FIRST_PASS, AFTER]))
    r = tool.execute({"input_path": str(src)})

    assert r.success, r.error
    assert r.data["before"]["integrated_lufs"] == -11.54
    assert r.data["after"]["integrated_lufs"] == -14.01
    assert r.data["target"] == {"integrated_lufs": -14.0, "true_peak_dbtp": -1.0, "lra": 11.0}
    wav_pass, mux = calls[1], calls[2]
    assert wav_pass[-1].endswith(".wav") and "-vn" in wav_pass
    assert mux[mux.index("-c:v") + 1] == "copy"
    assert mux[-1].endswith("render_loudnorm.mp4")
    assert not list(tmp_path.glob("*.wav"))  # temp file cleaned up


def test_measure_only_writes_nothing(tmp_path, monkeypatch):
    src = tmp_path / "a.wav"
    src.write_bytes(b"x")
    tool = LoudnessNormalize()
    calls = []
    monkeypatch.setattr(tool, "run_command", _fake_run(calls, [FIRST_PASS]))
    r = tool.execute({"input_path": str(src), "operation": "measure"})
    assert r.success and r.data["before"]["true_peak_dbtp"] == -2.78
    assert len(calls) == 1 and r.artifacts == []


def test_refuses_to_overwrite_input(tmp_path, monkeypatch):
    src = tmp_path / "a.wav"
    src.write_bytes(b"x")
    tool = LoudnessNormalize()
    monkeypatch.setattr(tool, "run_command", _fake_run([], [FIRST_PASS]))
    r = tool.execute({"input_path": str(src), "output_path": str(src)})
    assert not r.success


def test_missing_input():
    assert not LoudnessNormalize().execute({"input_path": "nope.mp4"}).success
