"""stem_separator: demucs command, outputs, content cache. Demucs is faked."""

from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

import pytest

from tools.audio import stem_separator as ss


@pytest.fixture
def fake_demucs(monkeypatch, tmp_path):
    monkeypatch.setenv("OPENMONTAGE_STEMS_CACHE_DIR", str(tmp_path / "cache"))
    calls = {"ffmpeg": [], "demucs": []}

    def fake_ffmpeg(self, cmd, timeout=None, **kwargs):
        calls["ffmpeg"].append(cmd)
        Path(cmd[-1]).write_bytes(b"RIFF-source")

    def fake_run(cmd, **kwargs):
        calls["demucs"].append(cmd)
        out = Path(cmd[cmd.index("-o") + 1]) / cmd[cmd.index("-n") + 1] / Path(cmd[-1]).stem
        out.mkdir(parents=True)
        (out / "vocals.wav").write_bytes(b"voice")
        (out / "no_vocals.wav").write_bytes(b"music")
        return SimpleNamespace(returncode=0, stdout="", stderr="")

    monkeypatch.setattr(ss.StemSeparator, "run_command", fake_ffmpeg)
    monkeypatch.setattr(ss.subprocess, "run", fake_run)
    return calls


def test_separates_video_into_vocals_and_accompaniment(fake_demucs, tmp_path):
    video = tmp_path / "source.mp4"
    video.write_bytes(b"video-bytes")
    result = ss.StemSeparator().execute({"input_path": str(video)})

    assert result.success, result.error
    out = tmp_path / "source_stems"
    assert Path(result.data["vocals"]) == out / "vocals.wav"
    assert (out / "vocals.wav").read_bytes() == b"voice"
    assert (out / "accompaniment.wav").read_bytes() == b"music"
    assert "-vn" in fake_demucs["ffmpeg"][0]
    cmd = fake_demucs["demucs"][0]
    assert cmd[1:3] == ["-m", "demucs"]
    for flag, value in (("--two-stems", "vocals"), ("-n", "htdemucs"), ("-d", "cpu"), ("--shifts", "0")):
        assert cmd[cmd.index(flag) + 1] == value
    assert not result.data["cached"]


def test_second_run_on_same_bytes_comes_from_cache(fake_demucs, tmp_path):
    video = tmp_path / "a.mp4"
    video.write_bytes(b"same")
    tool = ss.StemSeparator()
    first = tool.execute({"input_path": str(video), "output_dir": str(tmp_path / "one")})
    copy = tmp_path / "b.mp4"
    copy.write_bytes(b"same")
    second = tool.execute({"input_path": str(copy), "output_dir": str(tmp_path / "two")})

    assert first.success and second.success
    assert len(fake_demucs["demucs"]) == 1
    assert second.data["cached"] and second.from_cache
    assert (tmp_path / "two" / "accompaniment.wav").read_bytes() == b"music"
    assert first.data["cache_key"] == second.data["cache_key"]


def test_cache_key_changes_with_settings_and_bytes(tmp_path):
    tool = ss.StemSeparator()
    a = tmp_path / "a.wav"
    a.write_bytes(b"one")
    base = tool.cache_key_for(a, {})
    assert tool.cache_key_for(a, {"shifts": 2}) != base
    assert tool.cache_key_for(a, {"model": "htdemucs_ft"}) != base
    a.write_bytes(b"two")
    assert tool.cache_key_for(a, {}) != base


def test_demucs_failure_is_reported(fake_demucs, tmp_path, monkeypatch):
    monkeypatch.setattr(ss.subprocess, "run",
                        lambda cmd, **k: SimpleNamespace(returncode=1, stdout="", stderr="weights 404"))
    video = tmp_path / "x.mp4"
    video.write_bytes(b"x")
    result = ss.StemSeparator().execute({"input_path": str(video)})
    assert not result.success and "weights 404" in result.error


def test_missing_input():
    assert not ss.StemSeparator().execute({"input_path": "nope.mp4"}).success
