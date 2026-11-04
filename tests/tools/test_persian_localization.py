"""Persian (fa) production path: TTS routing, Gemini TTS output, RTL subtitles.

Regression for language-blind TTS routing: lib/scoring.py does not know
which providers speak Persian, so Persian text could be sent to Piper's
English voice or to ElevenLabs multilingual_v2 and come back as garbage with
no error.
"""

from __future__ import annotations

import struct
import wave

import pytest

from tools.audio.tts_selector import (
    PERSIAN_TTS_PRIORITY,
    TTSSelector,
    detect_text_language,
    resolve_tts_language,
)
from tools.base_tool import ToolResult, ToolStatus

FA_TEXT = "اپل توی سال هزار و نهصد و هفتاد و شش توی یه گاراژ کوچیک شروع شد"


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        (FA_TEXT, "fa"),
        ("Steve Jobs و Wozniak فقط هزار و سیصد دلار داشتن و اپل رو ساختن", "fa"),
        ("مرحبا بكم في هذا الفيديو الجديد", None),  # Arabic, not Persian
        ("Hello and welcome to the channel", None),
        ("", None),
    ],
)
def test_detect_text_language(text, expected):
    assert detect_text_language(text) == expected


def test_explicit_language_code_wins():
    assert resolve_tts_language({"text": "Hello", "language_code": "fa-IR"}) == "fa"
    assert resolve_tts_language({"text": FA_TEXT, "language_code": "en-US"}) is None


def _fake_tools(monkeypatch, classes, calls):
    for cls in classes:
        def fake_execute(self, inputs, _name=cls.__name__):
            calls.append((self.name, dict(inputs)))
            return ToolResult(success=True, data={"output": ""})

        monkeypatch.setattr(cls, "get_status", lambda self: ToolStatus.AVAILABLE)
        monkeypatch.setattr(cls, "execute", fake_execute)
    monkeypatch.setattr(TTSSelector, "_providers", lambda self: [c() for c in classes])


def test_persian_text_prefers_gemini_over_piper(monkeypatch, tmp_path):
    from tools.audio.gemini_tts import GeminiTTS
    from tools.audio.piper_tts import PiperTTS

    calls: list = []
    _fake_tools(monkeypatch, [PiperTTS, GeminiTTS], calls)
    result = TTSSelector().execute(
        {"text": FA_TEXT, "output_path": str(tmp_path / "n.wav")}
    )
    assert result.success, result.error
    assert result.data["selected_tool"] == "gemini_tts"
    assert result.data["language"] == "fa"


def test_persian_fallback_to_piper_gets_persian_voice(monkeypatch, tmp_path):
    from tools.audio.piper_tts import PiperTTS

    calls: list = []
    _fake_tools(monkeypatch, [PiperTTS], calls)
    result = TTSSelector().execute(
        {"text": FA_TEXT, "output_path": str(tmp_path / "n.wav")}
    )
    assert result.success, result.error
    assert calls[0][0] == "piper_tts"
    assert calls[0][1]["model"].startswith("fa_IR")


def test_persian_with_no_capable_provider_fails_loudly(monkeypatch, tmp_path):
    from tools.audio.google_tts import GoogleTTS

    assert "google_tts" not in PERSIAN_TTS_PRIORITY
    calls: list = []
    _fake_tools(monkeypatch, [GoogleTTS], calls)
    result = TTSSelector().execute(
        {"text": FA_TEXT, "output_path": str(tmp_path / "n.wav")}
    )
    assert not result.success
    assert "Persian" in result.error
    assert calls == []


def test_gemini_tts_rejects_three_speakers():
    from tools.audio.gemini_tts import GeminiTTS

    turns = [{"speaker": s, "text": "سلام"} for s in ("a", "b", "c")]
    speakers = [{"speaker": s, "voice": "Kore"} for s in ("a", "b", "c")]
    with pytest.raises(ValueError, match="at most 2 speakers"):
        GeminiTTS().build_request({"turns": turns, "speakers": speakers})


def test_gemini_tts_wav_duration(tmp_path):
    from tools.audio.gemini_tts import GeminiTTS

    path = tmp_path / "a.wav"
    with wave.open(str(path), "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(24000)
        w.writeframes(struct.pack("<h", 0) * 36000)
    assert GeminiTTS._wav_duration(path) == 1.5


def test_persian_subtitles_get_rtl_marks(tmp_path):
    from tools.subtitle.subtitle_gen import SubtitleGen

    segments = [
        {"start": 0.0, "end": 2.0, "text": "اپل در سال ۱۹۷۶ شروع شد."},
        {"start": 2.0, "end": 4.0, "text": "Steve Jobs و Wozniak فقط ۱۳۰۰ دلار داشتن!"},
    ]
    out = tmp_path / "fa.srt"
    result = SubtitleGen().execute({"segments": segments, "output_path": str(out)})
    assert result.success, result.error
    assert result.data["direction"] == "rtl"
    text_lines = [
        line for line in out.read_text(encoding="utf-8").split("\n")
        if line and "-->" not in line and not (line.isascii() and line.isdigit())
    ]
    assert text_lines and all(line.startswith("‏") for line in text_lines)


def test_english_subtitles_unchanged(tmp_path):
    from tools.subtitle.subtitle_gen import SubtitleGen

    out = tmp_path / "en.srt"
    result = SubtitleGen().execute(
        {"segments": [{"start": 0, "end": 1, "text": "Hello world"}], "output_path": str(out)}
    )
    assert result.data["direction"] == "ltr"
    assert "‏" not in out.read_text(encoding="utf-8")


def test_subtitle_style_sets_auto_base_direction():
    from tools.video.video_compose import VideoCompose

    assert "Encoding=-1" in VideoCompose._build_subtitle_style({}).split(",")
