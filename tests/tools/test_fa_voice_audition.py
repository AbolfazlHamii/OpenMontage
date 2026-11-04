"""Persian text helpers, AvalAI transcription and the voice audition script.

No network: requests.post and the TTS/STT callables are fakes.
"""

from __future__ import annotations

import json
import struct
import wave

import pytest

from lib import fa_text
from scripts import fa_voice_audition as audition
from tools.analysis.avalai_stt import AvalAISTT
from tools.base_tool import ToolResult


def _write_wav(path, seconds=1.0, rate=16000):
    with wave.open(str(path), "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(rate)
        w.writeframes(struct.pack("<h", 0) * int(rate * seconds))


# --- fa_text ---------------------------------------------------------------

@pytest.mark.parametrize("n, words", [
    (0, "صفر"),
    (7, "هفت"),
    (15, "پانزده"),
    (40, "چهل"),
    (105, "صد و پنج"),
    (1000, "هزار"),
    (1300, "هزار و سیصد"),
    (1938, "هزار و نهصد و سی و هشت"),
    (1995, "هزار و نهصد و نود و پنج"),
    (30000, "سی هزار"),
    (150000, "صد و پنجاه هزار"),
    (2000000, "دو میلیون"),
    (1001001, "یک میلیون و هزار و یک"),
])
def test_number_to_words(n, words):
    assert fa_text.number_to_words(n) == words


def test_spell_numbers_handles_every_digit_script_and_separators():
    assert fa_text.spell_numbers("سال ۱۹۹۵") == "سال هزار و نهصد و نود و پنج"
    assert fa_text.spell_numbers("١٣٠٠ دلار") == "هزار و سیصد دلار"
    assert fa_text.spell_numbers("150,000 گوشی") == "صد و پنجاه هزار گوشی"
    assert fa_text.spell_numbers("۱۵۰٬۰۰۰") == "صد و پنجاه هزار"


def test_normalize_unifies_spellings():
    assert fa_text.normalize("مي‌شه") == fa_text.normalize("می شه")
    assert fa_text.normalize("كتاب!") == "کتاب"
    assert fa_text.normalize("«سامسونگ»، ۱۹۳۸") == "سامسونگ 1938"


def test_round_trip_matches_digits_against_words():
    script = "سال هزار و نهصد و نود و پنج همه‌چیز عوض شد"
    heard = "سال ۱۹۹۵ همه چیز عوض شد."
    scores = fa_text.round_trip(heard, script)
    assert scores["best"] == 1.0


def test_round_trip_drops_with_mispronounced_name():
    script = "استیو وازنیاک فقط هزار و سیصد دلار داشت"
    heard = "استیو وزنیک فقط هزار و سیصد دلار داشت"
    assert 0.8 < fa_text.round_trip(heard, script)["best"] < 1.0


def test_chars_per_second_counts_letters_only():
    assert fa_text.chars_per_second("سلام، دنیا!", 1.0) == 8.0
    assert fa_text.chars_per_second("سلام", 0) == 0.0


def test_word_diff_reports_heard_and_expected():
    pairs = fa_text.word_diff("استیو وزنیک اومد", "استیو وازنیاک اومد")
    assert pairs == [("وزنیک", "وازنیاک")]


def test_written_transcript_of_spoken_script_is_not_an_error():
    script = "یه مرد جوون یه مغازه‌ی کوچیک باز کرد. کل سرمایه‌ش هیچ بود. فکرشم نمی‌کرد شرکتی که گوشیش"
    heard = "یه مرد جوان یه مغازه کوچک باز کرد. کل سرمایه‌اش هیچ بود. فکرش هم نمی‌کرد شرکتیکه گوشی‌ش"
    assert fa_text.word_diff(heard, script) == []
    assert fa_text.round_trip(heard, script)["best"] == 1.0
    # A real slip still shows.
    assert fa_text.word_diff("صد ها میلیون", "صدها میلیون") == []
    assert fa_text.word_diff("ست ها میلیون", "صدها میلیون") == [("ست ها", "صدها")]


# --- avalai_stt ------------------------------------------------------------

class _FakeResponse:
    def __init__(self, status_code=200, payload=None, text=""):
        self.status_code = status_code
        self._payload = payload or {}
        self.text = text

    def json(self):
        return self._payload


def test_avalai_stt_posts_to_transcriptions_and_prices_by_second(tmp_path, monkeypatch):
    monkeypatch.setenv("AVALAI_API_KEY", "test-key")
    monkeypatch.delenv("AVALAI_BASE_URL", raising=False)
    wav = tmp_path / "clip.wav"
    _write_wav(wav, seconds=10)
    calls = {}

    def fake_post(url, headers, data, files, timeout):
        calls.update(url=url, data=data, timeout=timeout, auth=headers["Authorization"])
        return _FakeResponse(payload={"text": "سلام دنیا"})

    monkeypatch.setattr("requests.post", fake_post)
    result = AvalAISTT().execute({"audio_path": str(wav), "prompt": "سامسونگ"})

    assert result.success, result.error
    assert calls["url"] == "https://api.avalai.ir/v1/audio/transcriptions"
    assert calls["data"]["model"] == "gpt-4o-mini-transcribe"
    assert calls["data"]["language"] == "fa"
    assert calls["data"]["prompt"] == "سامسونگ"
    assert result.data["text"] == "سلام دنیا"
    assert result.cost_usd == pytest.approx(10 * 0.00005)
    saved = json.loads((tmp_path / "clip.transcript.json").read_text(encoding="utf-8"))
    assert saved["text"] == "سلام دنیا"


def test_avalai_stt_timestamps_and_reported_cost(tmp_path, monkeypatch):
    monkeypatch.setenv("AVALAI_API_KEY", "test-key")
    wav = tmp_path / "talk.wav"
    _write_wav(wav, seconds=4)
    sent = {}

    def fake_post(url, headers, data, files, timeout):
        sent.update(data)
        return _FakeResponse(payload={"text": "hi there", "estimated_cost": {"unit": "0.0123"},
                                      "segments": [{"id": 0, "start": 0.1, "end": 1.2, "text": " hi "},
                                                   {"id": 1, "start": 1.5, "end": 2.0, "text": "there"}]})

    monkeypatch.setattr("requests.post", fake_post)
    result = AvalAISTT().execute({"audio_path": str(wav), "timestamps": True, "language": "en"})
    assert result.success, result.error
    assert sent["model"] == "whisper-1" and sent["response_format"] == "verbose_json"
    assert sent["timestamp_granularities[]"] == "segment"
    assert result.data["segments"] == [{"start": 0.1, "end": 1.2, "text": "hi"},
                                       {"start": 1.5, "end": 2.0, "text": "there"}]
    assert result.cost_usd == pytest.approx(0.0123)
    assert result.data["cost_status"] == "reported"


def test_avalai_stt_error_does_not_leak_key(tmp_path, monkeypatch):
    monkeypatch.setenv("AVALAI_API_KEY", "secret-key-123")
    wav = tmp_path / "clip.wav"
    _write_wav(wav)
    monkeypatch.setattr(
        "requests.post",
        lambda *a, **k: _FakeResponse(status_code=401, text="invalid key"),
    )
    result = AvalAISTT().execute({"audio_path": str(wav)})
    assert not result.success
    assert "401" in result.error
    assert "secret-key-123" not in result.error


def test_avalai_stt_unavailable_without_key(monkeypatch):
    monkeypatch.delenv("AVALAI_API_KEY", raising=False)
    assert AvalAISTT().get_status().value == "unavailable"


def test_avalai_stt_estimate_from_wav_length(tmp_path):
    wav = tmp_path / "clip.wav"
    _write_wav(wav, seconds=20)
    assert AvalAISTT().estimate_cost(
        {"audio_path": str(wav), "model": "groq.whisper-large-v3"}
    ) == pytest.approx(20 * 0.000031)


# --- audition script -------------------------------------------------------

def _fake_tts(calls):
    def tts(inputs):
        calls.append(inputs)
        _write_wav(inputs["output_path"], seconds=20)
        return ToolResult(success=True, data={
            "audio_duration_seconds": 20.0,
            "selected_provider": "avalai",
        }, cost_usd=0.003)
    return tts


def _fake_stt(transcripts):
    def stt(inputs):
        voice = inputs["audio_path"].split("\\")[-1].split("/")[-1].split("-")[0]
        return ToolResult(success=True, data={"text": transcripts.get(voice, audition.SCRIPT_DIGITS)},
                          cost_usd=0.001)
    return stt


def test_audition_ranks_drafts_and_renders_top_on_full_model(tmp_path):
    calls = []
    transcripts = {"Puck": "یه چیز دیگه کاملاً متفاوت"}
    results = audition.run_audition(
        tmp_path, ["Kore", "Puck"], ["calm", "energetic"], top=2,
        tts=_fake_tts(calls), stt=_fake_stt(transcripts), limit=2,
    )
    draft_calls = [c for c in calls if c["model_id"] == audition.DRAFT_MODEL]
    final_calls = [c for c in calls if c["model_id"] == audition.FINAL_MODEL]
    assert len(draft_calls) == 4 and len(final_calls) == 2
    assert all(c["allowed_providers"] == ["gemini", "avalai"] for c in calls)
    assert all(c["language_code"] == "fa" for c in calls)
    # Kore heard the script exactly, Puck did not: both finals are Kore.
    assert {f["voice"] for f in results["finals"]} == {"Kore"}
    assert results["ranking"][0].startswith("Kore")
    assert results["cost_usd"] == pytest.approx(6 * 0.004)
    page = (tmp_path / "index.html").read_text(encoding="utf-8")
    assert 'dir="rtl"' in page and "Kore-calm-draft.wav" in page
    saved = json.loads((tmp_path / "results.json").read_text(encoding="utf-8"))
    assert saved["drafts"][0]["round_trip"]["best"] == 1.0


def test_audition_keeps_going_when_one_voice_fails(tmp_path):
    def tts(inputs):
        if inputs["voice_id"] == "Puck":
            return ToolResult(success=False, error="All Persian TTS providers failed")
        _write_wav(inputs["output_path"], seconds=20)
        return ToolResult(success=True, data={"audio_duration_seconds": 20.0})

    results = audition.run_audition(tmp_path, ["Kore", "Puck"], ["calm"], top=1,
                                    tts=tts, stt=_fake_stt({}))
    errors = {t["voice"]: t["error"] for t in results["drafts"]}
    assert errors["Puck"] and not errors["Kore"]
    assert [f["voice"] for f in results["finals"]] == ["Kore"]


def test_rescore_rewrites_scores_without_new_calls(tmp_path):
    results = audition.run_audition(tmp_path, ["Kore"], ["calm"], top=1,
                                    tts=_fake_tts([]), stt=_fake_stt({}))
    saved = json.loads((tmp_path / "results.json").read_text(encoding="utf-8"))
    saved["drafts"][0]["round_trip"] = {}
    (tmp_path / "results.json").write_text(json.dumps(saved, ensure_ascii=False), encoding="utf-8")
    again = audition.rescore(tmp_path)
    assert again["drafts"][0]["round_trip"] == results["drafts"][0]["round_trip"]
    assert again["ranking"] == ["Kore-calm-draft"]


def test_estimate_and_cost_cap(capsys):
    estimate = audition.estimate_cost(6, 2, 2)
    assert 0 < estimate["total"] < 0.15
    assert audition.main(["--dry-run"]) == 0
    assert audition.main(["--max-cost", "0.0001", "--out", "unused"]) == 2
    assert "not running" in capsys.readouterr().out
