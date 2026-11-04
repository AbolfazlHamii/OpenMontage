"""Channel bible: template, lexicon in TTS, suggestions, owner edits."""

from __future__ import annotations

import json

import pytest

from lib import channel_bible as cb
from tools.audio.tts_selector import TTSSelector
from tools.base_tool import ToolResult


@pytest.fixture
def channels(tmp_path, monkeypatch):
    monkeypatch.setenv("OPENMONTAGE_CHANNELS_DIR", str(tmp_path))
    return tmp_path


def test_create_channel_copies_template(channels):
    path = cb.create_channel("fa-test")
    for name in ("channel.md", "voices.yaml", "lexicon.tsv", "glossary.tsv",
                 "lexicon_suggestions.tsv", "characters", "examples", "retros"):
        assert (path / name).exists(), name
    channel = cb.load_channel("fa-test")
    assert channel.voices["channel"] == "fa-test"
    assert channel.voice_for("narrator")["status"] == "pending_owner_pick"
    with pytest.raises(FileExistsError):
        cb.create_channel("fa-test")


def test_channel_name_must_be_a_slug(channels):
    with pytest.raises(ValueError):
        cb.channel_path("../escape")
    with pytest.raises(FileNotFoundError):
        cb.load_channel("missing")


def test_apply_lexicon_longest_first_and_word_bounded():
    lexicon = [
        {"term": "Samsung", "tts": "سامسونگ"},
        {"term": "Samsung Electronics", "tts": "سامسونگ الکترونیکس"},
        {"term": "دگو", "tts": "دِگو"},
    ]
    text, applied = cb.apply_lexicon(
        "samsung electronics و Samsung‌ها توی دگو، نه دگوها", lexicon)
    assert text == "سامسونگ الکترونیکس و سامسونگ‌ها توی دِگو، نه دگوها"
    assert applied == ["Samsung Electronics", "Samsung", "دگو"]


def test_tts_selector_applies_channel_lexicon(channels, monkeypatch):
    cb.create_channel("fa-test")
    cb.approve_lexicon(cb.load_channel("fa-test"), "Wozniak", "وازنیاک")
    seen = {}

    class FakeTool:
        name = "avalai_gemini_tts"
        provider = "avalai"
        capability = "tts"
        input_schema = {"properties": {"model_id": {}}}

        def execute(self, inputs):
            seen.update(inputs)
            return ToolResult(success=True, data={"audio_duration_seconds": 1.0})

        def get_status(self):
            class S:
                value = "available"
            return S()

    selector = TTSSelector()
    monkeypatch.setattr(selector, "_providers", lambda: [FakeTool()])
    monkeypatch.setattr(selector, "_select_best_tool",
                        lambda inputs, candidates, ctx: (candidates[0] if candidates else None, None))
    monkeypatch.setattr(selector, "_tool_context_payload", staticmethod(lambda tool: {}))
    result = selector.execute({"text": "استیو Wozniak فقط پول داشت", "channel": "fa-test"})

    assert result.success, result.error
    assert seen["text"] == "استیو وازنیاک فقط پول داشت"
    assert "channel" not in seen
    assert result.data["lexicon_applied"] == ["Wozniak"]


def test_tts_selector_reports_missing_channel(channels):
    result = TTSSelector().execute({"text": "سلام", "channel": "nope"})
    assert not result.success and "nope" in result.error


def test_suggestions_need_two_misses_then_owner_approves(channels):
    cb.create_channel("fa-test")
    channel = cb.load_channel("fa-test")
    assert cb.suggest_lexicon(channel, [("ست ها", "صدها")], "take-1") == []
    pending = cb.suggest_lexicon(channel, [("ست‌ها", "صدها"), ("کنه", "کرد")], "take-2")
    assert [p["expected"] for p in pending] == ["صدها"]
    assert pending[0]["count"] == "2"
    assert pending[0]["heard"] == "ست ها | ست‌ها"

    cb.approve_lexicon(channel, "صدها", "صَدها", "audition 2026-11-04")
    assert channel.lexicon == [{"term": "صدها", "tts": "صَدها", "note": "audition 2026-11-04"}]
    rows = cb._read_tsv(channel.path / "lexicon_suggestions.tsv")
    assert {r["expected"]: r["status"] for r in rows} == {"صدها": "approved", "کرد": "watching"}
    # Approved terms are not suggested again.
    assert cb.suggest_lexicon(channel, [("ست ها", "صدها")], "take-3") == []


def test_record_edit_and_retro_path(channels):
    cb.create_channel("fa-test")
    channel = cb.load_channel("fa-test")
    path = cb.record_edit(channel, "samsung-history-fa", "script", "قبل", "بعد", "shorter")
    entry = json.loads(path.read_text(encoding="utf-8").splitlines()[0])
    assert entry["before"] == "قبل" and entry["after"] == "بعد" and entry["stage"] == "script"
    assert cb.retro_path(channel, "x").parent == channel.path / "retros"


def test_cli_apply_and_suggest(channels, tmp_path, capsys):
    cb.create_channel("fa-test")
    cb.approve_lexicon(cb.load_channel("fa-test"), "Daegu", "دِگو")
    assert cb.main(["apply", "--channel", "fa-test", "--text", "شهر Daegu"]) == 0
    assert json.loads(capsys.readouterr().out)["text"] == "شهر دِگو"

    audition = tmp_path / "results.json"
    audition.write_text(json.dumps({"drafts": [
        {"voice": "Kore", "style": "calm", "model": "lite", "misheard": [["ست ها", "صدها"]]},
        {"voice": "Puck", "style": "calm", "model": "lite", "misheard": [["ست ها", "صدها"]]},
    ], "finals": []}, ensure_ascii=False), encoding="utf-8")
    assert cb.main(["suggest", "--channel", "fa-test", "--audition", str(audition)]) == 0
    assert json.loads(capsys.readouterr().out)["pending"][0]["expected"] == "صدها"
