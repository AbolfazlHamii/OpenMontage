"""video_compose passes a fonts folder to libass so per-user fonts load."""

from __future__ import annotations

from tools.video.video_compose import VideoCompose


def test_no_fonts_dir_by_default(monkeypatch, tmp_path):
    monkeypatch.delenv("SUBTITLE_FONTS_DIR", raising=False)
    flt = VideoCompose._subtitles_filter(tmp_path / "a.srt", {"font": "Vazirmatn"})
    assert "fontsdir" not in flt
    assert "FontName=Vazirmatn" in flt


def test_fonts_dir_from_env(monkeypatch, tmp_path):
    fonts = tmp_path / "fonts"
    fonts.mkdir()
    monkeypatch.setenv("SUBTITLE_FONTS_DIR", str(fonts))
    flt = VideoCompose._subtitles_filter(tmp_path / "a.srt", {})
    assert ":fontsdir='" in flt
    assert flt.index("fontsdir") < flt.index("force_style")


def test_style_fonts_dir_wins_and_is_escaped(monkeypatch, tmp_path):
    monkeypatch.setenv("SUBTITLE_FONTS_DIR", str(tmp_path / "env"))
    flt = VideoCompose._subtitles_filter(tmp_path / "a.srt", {"fonts_dir": str(tmp_path / "style")})
    fontsdir = flt.split(":fontsdir='")[1].split("'")[0]
    assert fontsdir.endswith("/style")
    assert "\\\\" not in fontsdir  # backslashes turned into forward slashes
    assert "fonts_dir" not in VideoCompose._build_subtitle_style({"fonts_dir": "x"})
