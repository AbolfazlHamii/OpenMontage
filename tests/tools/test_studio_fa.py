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


def test_backlot_already_running_returns_url_without_spawning(client, monkeypatch):
    monkeypatch.setattr(server, "_backlot_alive", lambda port: True)
    monkeypatch.setattr(server.subprocess, "Popen", lambda *a, **k: pytest.fail("spawned"))
    res = client.post("/api/backlot/open", headers=PANEL, json={"project_id": "samsung-history-fa"})
    assert res.status_code == 200, res.text
    assert res.json()["url"].endswith(":4750/p/samsung-history-fa")


def test_backlot_down_starts_only_the_server(client, monkeypatch):
    spawned = []
    monkeypatch.setattr(server, "_backlot_alive", lambda port: bool(spawned))
    monkeypatch.setattr(server.subprocess, "Popen", lambda cmd, **kw: spawned.append((cmd, kw["cwd"])))
    res = client.post("/api/backlot/open", headers=PANEL, json={})
    assert res.status_code == 200, res.text
    cmd, cwd = spawned[0]
    assert cmd[1:4] == ["-m", "backlot", "serve"] and cwd == server.REPO_ROOT
    assert res.json()["url"] == "http://127.0.0.1:4750/"


def test_backlot_that_never_answers_is_a_clear_error(client, monkeypatch):
    clock = iter(range(0, 100, 5))
    monkeypatch.setattr(server, "_backlot_alive", lambda port: False)
    monkeypatch.setattr(server.subprocess, "Popen", lambda *a, **k: None)
    monkeypatch.setattr(server.time, "time", lambda: next(clock))
    monkeypatch.setattr(server.time, "sleep", lambda s: None)
    res = client.post("/api/backlot/open", headers=PANEL, json={})
    assert res.status_code == 502
    assert "4750" in res.json()["detail"]


def test_backlot_rejects_path_like_project_ids(client):
    res = client.post("/api/backlot/open", headers=PANEL, json={"project_id": "..\\x"})
    assert res.status_code == 400


def test_status_lists_persian_order(client):
    from tools.audio.tts_selector import PERSIAN_TTS_PRIORITY

    names = [p["name"] for p in client.get("/api/status").json()["providers"]]
    assert names == PERSIAN_TTS_PRIORITY


# ---- production pages (studio_fa/production.py) ---------------------------------

import json as _json
import shutil as _shutil
import time as _time

from studio_fa import production

WIZARD = {"project_id": "demo-history", "topic": "کل تاریخ سونی در ۹۰ ثانیه", "format": "landscape",
          "duration_seconds": 90, "edit_style": "full-history-in-n-minutes", "voice": "Kore",
          "voice_style": "", "budget_usd": 3, "draft_rounds": 1}


@pytest.fixture
def projects(monkeypatch, tmp_path):
    from lib import paths

    root = tmp_path / "projects"
    root.mkdir()
    monkeypatch.setattr(paths, "PROJECTS_DIR", root)
    return root


def test_production_writes_need_the_panel_header(client, projects):
    for path, body in [("/api/fa/projects", WIZARD), ("/api/fa/estimate", WIZARD),
                       ("/api/fa/llm-routing", {"tier": "bulk", "entries": [{"profile": "avalai", "model": "m"}]}),
                       ("/api/fa/styles/learn", {"name": "x-style", "url": "https://e.x/v"}),
                       ("/api/fa/health/ping", {})]:
        assert client.post(path, json=body).status_code == 403, path


def test_wizard_estimates_then_creates_a_valid_project(client, projects):
    est = client.post("/api/fa/estimate", json=WIZARD, headers=PANEL).json()
    assert est["final"]["total_usd"] > est["draft"]["total_usd"] > 0
    assert est["within_budget"]
    res = client.post("/api/fa/projects", json=WIZARD, headers=PANEL)
    assert res.status_code == 200, res.text
    brief = _json.loads((projects / "demo-history/artifacts/brief.json").read_text(encoding="utf-8"))
    assert brief["metadata"]["edit_style"] == "full-history-in-n-minutes"
    assert (projects / "demo-history/project.json").exists()
    assert (projects / "demo-history/artifacts/estimate.json").exists()
    again = client.post("/api/fa/projects", json=WIZARD, headers=PANEL)
    assert again.status_code == 409 and "شناسه" in again.json()["detail"]


def test_wizard_refuses_over_budget_and_leaves_nothing(client, projects):
    res = client.post("/api/fa/projects", json={**WIZARD, "budget_usd": 0.1}, headers=PANEL)
    assert res.status_code == 400 and "بودجه" in res.json()["detail"]
    assert not (projects / "demo-history").exists()
    bad = client.post("/api/fa/projects", json={**WIZARD, "project_id": "Bad Id"}, headers=PANEL)
    assert bad.status_code == 400


def test_timeline_review_writes_decision_log(client, projects):
    client.post("/api/fa/projects", json=WIZARD, headers=PANEL)
    t = client.get("/api/fa/projects/demo-history/timeline").json()
    assert [s["name"] for s in t["stages"]][:3] == ["research", "proposal", "script"]
    r = client.post("/api/fa/projects/demo-history/review",
                    json={"stage": "proposal", "action": "approve", "note": "خوبه"}, headers=PANEL)
    assert r.status_code == 200, r.text
    log = _json.loads((projects / "demo-history/decision_log.json").read_text(encoding="utf-8"))
    d = log["decisions"][-1]
    assert d["selected"] == "approve" and d["subject"] == "Checkpoint review: proposal" and d["user_approved"]
    stage = next(s for s in r.json()["timeline"]["stages"] if s["name"] == "proposal")
    assert stage["review"] == "approve"
    assert client.post("/api/fa/projects/demo-history/review",
                       json={"stage": "nope", "action": "approve"}, headers=PANEL).status_code == 400


def test_protected_project_is_read_only(client, projects):
    p = projects / "samsung-history-fa"
    p.mkdir()
    (p / "project.json").write_text(_json.dumps({"pipeline_type": "animated-explainer"}), encoding="utf-8")
    assert client.get("/api/fa/projects/samsung-history-fa/timeline").json()["protected"]
    r = client.post("/api/fa/projects/samsung-history-fa/review",
                    json={"stage": "proposal", "action": "approve"}, headers=PANEL)
    assert r.status_code == 403 and not (p / "decision_log.json").exists()


def test_costs_count_each_call_once(client, projects):
    p = projects / "demo"
    p.mkdir()
    events = [
        {"ts": "2026-11-04T15:56:40", "tool": "avalai_gemini_image", "depth": "2", "event": "finish", "cost_usd": "0.0672"},
        {"ts": "2026-11-04T15:56:40", "tool": "image_selector", "depth": "1", "event": "finish", "cost_usd": "0.0672"},
        {"ts": "2026-11-04T15:56:40", "tool": "image_selector", "event": "finish", "cost_usd": "0.0672"},
        {"ts": "2026-11-04T14:20:42", "tool": "avalai_gemini_tts", "depth": "1", "event": "finish", "cost_usd": "0.0015"},
    ]
    (p / "events.jsonl").write_text("\n".join(_json.dumps(e) for e in events), encoding="utf-8")
    (p / "cost_log.json").write_text(_json.dumps({"entries": [
        {"tool": "openai_compat_llm", "actual_usd": 0.0001, "timestamp": "2026-12-01T00:00:00"}]}), encoding="utf-8")
    c = client.get("/api/fa/costs").json()
    assert c["projects"][0]["total_usd"] == pytest.approx(0.0688)
    assert c["months"] == {"2026-11": pytest.approx(0.0687), "2026-12": pytest.approx(0.0001)}


def test_health_lists_profiles_without_keys(client, monkeypatch):
    monkeypatch.setenv("AVALAI_API_KEY", "aa-secretkey123456")
    h = client.get("/api/fa/health").json()
    names = {p["name"] for p in h["llm_profiles"]}
    assert {"avalai", "gemini", "moonshot"} <= names
    assert "aa-secretkey123456" not in _json.dumps(h)
    monkeypatch.setattr(production, "_ping_profile",
                        lambda cfg, name: {"reachable": True, "latency_ms": 120, "http": 200, "error": None})
    pinged = client.post("/api/fa/health/ping", json={}, headers=PANEL).json()
    avalai = next(p for p in pinged["llm_profiles"] if p["name"] == "avalai")
    assert avalai["latency_ms"] == 120 and pinged["pinged"]


def test_styles_gallery_and_learn_flow(client, projects, monkeypatch):
    cards = client.get("/api/fa/styles").json()
    assert any(c["name"] == "full-history-in-n-minutes" for c in cards)
    est = client.post("/api/fa/styles/learn/estimate",
                      json={"name": "ref-style", "url": "https://e.x/v", "duration_seconds": 180}, headers=PANEL).json()
    assert 0 < est["total_usd"] < 0.05
    assert client.post("/api/fa/styles/learn", json={"name": "Bad", "url": "https://e.x"},
                       headers=PANEL).status_code == 400
    assert client.post("/api/fa/styles/learn", json={"name": "ref-style", "url": "ftp://e.x"},
                       headers=PANEL).status_code == 400

    from tools.analysis import edit_style_extractor

    seen = {}

    def fake_execute(self, inputs):
        seen.update(inputs)
        return ToolResult(success=True, data={"asl_seconds": 3.7, "cost_usd": 0.01})

    monkeypatch.setattr(edit_style_extractor.EditStyleExtractor, "execute", fake_execute)
    job = client.post("/api/fa/styles/learn", json={"name": "ref-style", "url": "https://e.x/v"},
                      headers=PANEL).json()
    for _ in range(100):
        state = client.get(f"/api/fa/jobs/{job['id']}").json()
        if state["status"] != "running":
            break
        _time.sleep(0.05)
    assert state["status"] == "done" and state["result"]["asl_seconds"] == 3.7
    assert seen["url"] == "https://e.x/v" and "_reference" in seen["work_dir"]


def test_llm_routing_page_writes_only_the_tier(client, monkeypatch, tmp_path):
    from tools.text import openai_compat_llm

    routing = tmp_path / "llm_routing.yaml"
    _shutil.copy(openai_compat_llm.ROUTING_PATH, routing)
    monkeypatch.setattr(openai_compat_llm, "ROUTING_PATH", routing)
    before = routing.read_text(encoding="utf-8")
    r = client.post("/api/fa/llm-routing", headers=PANEL, json={
        "tier": "worker", "entries": [{"profile": "avalai", "model": "claude-haiku-5-5"}]})
    assert r.status_code == 200, r.text
    assert r.json()["tiers"]["worker"] == [{"profile": "avalai", "model": "claude-haiku-5-5"}]
    after = routing.read_text(encoding="utf-8")
    assert after.split("\ntiers:")[0] == before.split("\ntiers:")[0]  # header comments kept
    assert after.split("\nescalation:")[1] == before.split("\nescalation:")[1]  # tasks kept
    assert client.post("/api/fa/llm-routing", headers=PANEL, json={
        "tier": "worker", "entries": [{"profile": "nope", "model": "x1"}]}).status_code == 400
    assert client.post("/api/fa/llm-routing", headers=PANEL, json={
        "tier": "worker", "entries": [{"profile": "avalai", "model": "bad model!"}]}).status_code == 400
    assert client.get("/api/fa/llm-routing").json()["profiles"]["avalai"]["key_env"] == "AVALAI_API_KEY"


def test_errors_are_persian_and_redacted():
    assert "۴۰۳" in production.explain("PermissionDeniedError: Error code: 403")
    msg = production.explain("bad Bearer aa-TOPSECRETKEY12345 header")
    assert "TOPSECRETKEY" not in msg
    assert "کلید" in production.explain("AVALAI_API_KEY not set")


def test_unexpected_errors_reach_the_page_in_persian(monkeypatch):
    def boom(_):
        raise RuntimeError("disk exploded")

    monkeypatch.setattr(production, "_timeline", boom)
    res = TestClient(server.create_app(), base_url="http://127.0.0.1", raise_server_exceptions=False).get(
        "/api/fa/projects/x-y-z/timeline")
    assert res.status_code == 500 and "خطای پیش‌بینی‌نشده" in res.json()["detail"]
