"""Studio FA control panel: API guards, .env writes, TTS wiring.

No network and no paid calls: tts_selector is replaced with a fake.
"""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from studio_fa import server
from tools.base_tool import ToolResult

PANEL = {"X-Studio-FA": "1"}


@pytest.fixture
def client(monkeypatch, tmp_path):
    monkeypatch.setattr(server, "STATE_DIR", tmp_path / "state")
    monkeypatch.setattr(server, "ENV_PATH", tmp_path / ".env")
    return TestClient(server.create_app(), base_url="http://127.0.0.1")


def test_foreign_host_rejected(client):
    assert client.get("/api/health", headers={"Host": "evil.example"}).status_code == 400


def test_post_without_panel_header_rejected(client):
    res = client.post("/api/tts", json={"text": "سلام"})
    assert res.status_code == 403


def test_env_write_keeps_other_lines_and_hides_secrets(client, monkeypatch):
    # setenv (not delenv) so monkeypatch restores the real value afterwards.
    monkeypatch.setenv("AVALAI_API_KEY", "old")
    server.ENV_PATH.write_text("# comment\nAVALAI_API_KEY=old\nOTHER=1\n", encoding="utf-8")
    res = client.post("/api/env", json={"name": "AVALAI_API_KEY", "value": "new-key"}, headers=PANEL)
    assert res.status_code == 200
    assert res.json()["env"]["AVALAI_API_KEY"] == {"set": True, "value": None}
    assert server.ENV_PATH.read_text(encoding="utf-8").splitlines() == [
        "# comment", "AVALAI_API_KEY=new-key", "OTHER=1",
    ]


def test_env_rejects_unknown_names_and_newlines(client):
    assert client.post("/api/env", json={"name": "PATH", "value": "x"}, headers=PANEL).status_code == 400
    res = client.post("/api/env", json={"name": "OPENAI_BASE_URL", "value": "a\nB=1"}, headers=PANEL)
    assert res.status_code == 400


def test_tts_passes_choices_to_selector_and_records_history(client, monkeypatch):
    seen = {}

    def fake_execute(self, inputs):
        seen.update(inputs)
        return ToolResult(
            success=True,
            data={"selected_tool": "avalai_gemini_tts", "audio_duration_seconds": 2.0,
                  "fallback_from": [{"tool": "gemini_tts", "error": "region"}]},
            cost_usd=0.0012,
        )

    monkeypatch.setattr("tools.audio.tts_selector.TTSSelector.execute", fake_execute)
    res = client.post("/api/tts", headers=PANEL, json={
        "text": "سلام دنیا", "voice_id": "Puck", "style": "آرام", "provider": "avalai",
    })
    assert res.status_code == 200, res.text
    clip = res.json()
    assert seen["voice_id"] == "Puck"
    assert seen["preferred_provider"] == "avalai"
    assert seen["language_code"] == "fa"
    assert seen["output_path"].endswith(".wav")
    assert clip["cps"] == 4.5
    assert clip["fallback_from"][0]["tool"] == "gemini_tts"
    assert client.get("/api/tts/history").json()[0]["id"] == clip["id"]


def test_tts_failure_is_reported(client, monkeypatch):
    monkeypatch.setattr(
        "tools.audio.tts_selector.TTSSelector.execute",
        lambda self, inputs: ToolResult(success=False, error="All Persian TTS providers failed"),
    )
    res = client.post("/api/tts", headers=PANEL, json={"text": "سلام"})
    assert res.status_code == 502
    assert "Persian" in res.json()["detail"]


def test_tts_rejects_bad_voice_name(client):
    res = client.post("/api/tts", headers=PANEL, json={"text": "سلام", "voice_id": "../x"})
    assert res.status_code == 422


def test_media_cannot_escape_state_dir(client):
    (server.STATE_DIR / "tts").mkdir(parents=True)
    assert client.get("/media/tts/..%2F..%2Fsecret.txt").status_code == 404
    assert client.get("/media/other/x.wav").status_code == 404


def test_status_lists_persian_order(client):
    from tools.audio.tts_selector import PERSIAN_TTS_PRIORITY

    names = [p["name"] for p in client.get("/api/status").json()["providers"]]
    assert names == PERSIAN_TTS_PRIORITY
