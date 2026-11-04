"""AvalAI Gemini TTS adapter and the Persian provider fall-through.

No network: requests.post is replaced with a fake.
"""

from __future__ import annotations

import base64
import datetime
import io
import struct
import wave

import pytest

from tools.audio.avalai_gemini_tts import AvalAIGeminiTTS
from tools.audio.tts_selector import PERSIAN_TTS_PRIORITY, TTSSelector
from tools.base_tool import ToolResult, ToolStatus

FA_TEXT = "اپل توی سال هزار و نهصد و هفتاد و شش توی یه گاراژ کوچیک شروع شد"
PCM_ONE_SECOND = struct.pack("<h", 0) * 24000


class _FakeResponse:
    def __init__(self, status_code=200, payload=None, text=""):
        self.status_code = status_code
        self._payload = payload or {}
        self.text = text

    def json(self):
        return self._payload


def _audio_payload(data: bytes, mime: str, usage=None):
    payload = {
        "candidates": [{
            "content": {"parts": [{
                "inlineData": {"mimeType": mime, "data": base64.b64encode(data).decode()}
            }]}
        }]
    }
    if usage:
        payload["usageMetadata"] = usage
    return payload


def _wav_bytes(frames: bytes, rate=24000) -> bytes:
    buf = io.BytesIO()
    with wave.open(buf, "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(rate)
        w.writeframes(frames)
    return buf.getvalue()


@pytest.fixture
def avalai_key(monkeypatch):
    monkeypatch.setenv("AVALAI_API_KEY", "test-key")
    monkeypatch.delenv("AVALAI_BASE_URL", raising=False)


def test_single_speaker_request_uses_voice_and_style():
    request = AvalAIGeminiTTS().build_request(
        {"text": FA_TEXT, "voice_id": "Puck", "style": "پرانرژی", "model_id": "gemini-3.8-flash-lite-tts"}
    )
    assert request["model"] == "gemini-3.8-flash-lite-tts"
    body = request["body"]
    assert body["generationConfig"]["responseModalities"] == ["AUDIO"]
    voice = body["generationConfig"]["speechConfig"]["voiceConfig"]["prebuiltVoiceConfig"]
    assert voice == {"voiceName": "Puck"}
    assert body["contents"][0]["parts"] == [{"text": FA_TEXT, "speechMetadata": {"style": "پرانرژی"}}]


def test_two_speaker_request():
    request = AvalAIGeminiTTS().build_request({
        "turns": [
            {"speaker": "Host", "text": "سلام", "style": "شاد"},
            {"speaker": "Guest", "text": "درود"},
        ],
        "speakers": [{"speaker": "Host", "voice": "Kore"}, {"speaker": "Guest", "voice": "Puck"}],
    })
    config = request["body"]["generationConfig"]["speechConfig"]["multiSpeakerVoiceConfig"]
    assert [c["speaker"] for c in config["speakerVoiceConfigs"]] == ["Host", "Guest"]
    parts = request["body"]["contents"][0]["parts"]
    assert parts[1] == {"text": "درود", "speechMetadata": {"speaker": "Guest"}}


def test_three_speakers_rejected_like_gemini_tts():
    turns = [{"speaker": s, "text": "سلام"} for s in "abc"]
    speakers = [{"speaker": s, "voice": "Kore"} for s in "abc"]
    with pytest.raises(ValueError, match="at most 2 speakers"):
        AvalAIGeminiTTS().build_request({"turns": turns, "speakers": speakers})


def test_status_follows_key(monkeypatch):
    monkeypatch.delenv("AVALAI_API_KEY", raising=False)
    assert AvalAIGeminiTTS().get_status() == ToolStatus.UNAVAILABLE
    monkeypatch.setenv("AVALAI_API_KEY", "k")
    assert AvalAIGeminiTTS().get_status() == ToolStatus.AVAILABLE


def test_wav_response_written_as_is(monkeypatch, tmp_path, avalai_key):
    seen = {}

    def fake_post(url, headers, json, timeout):
        seen.update(url=url, headers=headers)
        return _FakeResponse(payload=_audio_payload(
            _wav_bytes(PCM_ONE_SECOND), "audio/wav",
            usage={"promptTokenCount": 40, "candidatesTokenCount": 1000},
        ))

    monkeypatch.setattr("requests.post", fake_post)
    out = tmp_path / "a.wav"
    result = AvalAIGeminiTTS().execute({"text": FA_TEXT, "output_path": str(out)})
    assert result.success, result.error
    assert seen["url"] == "https://api.avalai.ir/v1beta/models/gemini-3.8-flash-tts:generateContent"
    assert seen["headers"]["Authorization"] == "Bearer test-key"
    assert result.data["audio_duration_seconds"] == 1.0
    assert result.cost_usd is not None and result.cost_usd > 0


def test_raw_pcm_is_wrapped_in_wav(monkeypatch, tmp_path, avalai_key):
    monkeypatch.setattr(
        "requests.post",
        lambda *a, **k: _FakeResponse(payload=_audio_payload(PCM_ONE_SECOND * 2, "audio/L16;codec=pcm;rate=24000")),
    )
    out = tmp_path / "b.wav"
    result = AvalAIGeminiTTS().execute({"text": FA_TEXT, "output_path": str(out)})
    assert result.success, result.error
    assert result.data["audio_duration_seconds"] == 2.0


def test_http_error_is_reported(monkeypatch, tmp_path, avalai_key):
    monkeypatch.setattr(
        "requests.post", lambda *a, **k: _FakeResponse(status_code=402, text="insufficient credit")
    )
    result = AvalAIGeminiTTS().execute({"text": FA_TEXT, "output_path": str(tmp_path / "c.wav")})
    assert not result.success
    assert "402" in result.error and "credit" in result.error


def test_cost_switches_to_standard_rate_after_promo():
    usage = {"promptTokenCount": 1_000_000, "candidatesTokenCount": 1_000_000}
    promo = AvalAIGeminiTTS._cost("gemini-3.8-flash-tts", usage, datetime.date(2026, 11, 4))
    standard = AvalAIGeminiTTS._cost("gemini-3.8-flash-tts", usage, datetime.date(2027, 1, 1))
    assert promo == 9.5
    assert standard == 19.0


# ---- selector fall-through -------------------------------------------------

def _install(monkeypatch, behaviours, calls):
    """behaviours: list of (tool_class, succeed: bool)."""
    for cls, succeed in behaviours:
        def fake_execute(self, inputs, _ok=succeed):
            calls.append(self.name)
            if _ok:
                return ToolResult(success=True, data={"output": "", "audio_duration_seconds": 1.0})
            return ToolResult(success=False, error="User location is not supported")

        monkeypatch.setattr(cls, "get_status", lambda self: ToolStatus.AVAILABLE)
        monkeypatch.setattr(cls, "execute", fake_execute)
    monkeypatch.setattr(TTSSelector, "_providers", lambda self: [c() for c, _ in behaviours])


def test_avalai_follows_gemini_in_persian_order():
    assert PERSIAN_TTS_PRIORITY.index("avalai_gemini_tts") == PERSIAN_TTS_PRIORITY.index("gemini_tts") + 1


def test_gemini_failure_falls_back_to_avalai(monkeypatch, tmp_path):
    from tools.audio.gemini_tts import GeminiTTS

    calls: list = []
    _install(monkeypatch, [(GeminiTTS, False), (AvalAIGeminiTTS, True)], calls)
    result = TTSSelector().execute({"text": FA_TEXT, "output_path": str(tmp_path / "n.wav")})
    assert result.success, result.error
    assert calls == ["gemini_tts", "avalai_gemini_tts"]
    assert result.data["selected_tool"] == "avalai_gemini_tts"
    assert result.data["fallback_from"][0]["tool"] == "gemini_tts"


def test_all_persian_providers_failing_lists_each_error(monkeypatch, tmp_path):
    from tools.audio.gemini_tts import GeminiTTS

    calls: list = []
    _install(monkeypatch, [(GeminiTTS, False), (AvalAIGeminiTTS, False)], calls)
    result = TTSSelector().execute({"text": FA_TEXT, "output_path": str(tmp_path / "n.wav")})
    assert not result.success
    assert "gemini_tts" in result.error and "avalai_gemini_tts" in result.error


def test_explicit_provider_does_not_fall_through(monkeypatch, tmp_path):
    from tools.audio.gemini_tts import GeminiTTS

    calls: list = []
    _install(monkeypatch, [(GeminiTTS, False), (AvalAIGeminiTTS, True)], calls)
    result = TTSSelector().execute({
        "text": FA_TEXT, "preferred_provider": "gemini", "output_path": str(tmp_path / "n.wav"),
    })
    assert not result.success
    assert calls == ["gemini_tts"]


def test_english_does_not_fall_through(monkeypatch, tmp_path):
    from tools.audio.gemini_tts import GeminiTTS

    calls: list = []
    _install(monkeypatch, [(GeminiTTS, False), (AvalAIGeminiTTS, True)], calls)
    TTSSelector().execute({"text": "Hello there", "output_path": str(tmp_path / "n.wav")})
    assert len(calls) == 1
