"""openai_compat_llm + llm_selector, fully mocked.

The OpenAI SDK runs for real on top of httpx.MockTransport, so no socket is
opened; selector tests use a fake LLM tool.
"""

from __future__ import annotations

import json
from pathlib import Path

import httpx
import pytest
import yaml

from tools.base_tool import ToolResult
from tools.text import llm_selector as selector_mod
from tools.text.llm_selector import LLMSelector
from tools.text.openai_compat_llm import OpenAICompatLLM, extract_json, redact, strip_reasoning

KEY = "aa-TESTKEY1234567890abcdef"
DAHL_KEY = "dahl_TESTKEY1234567890abcdef"

ROUTING = {
    "mode": "interactive",
    "profiles": {
        "avalai": {"base_url": "https://api.avalai.ir/v1", "key_env": "AVALAI_API_KEY", "proxy": "direct"},
        "gemini": {"base_url": "https://g.example/v1", "key_env": "GOOGLE_API_KEY", "proxy": "env"},
        "dahl": {"base_url": "https://inference.dahl.global/v1", "key_env": "DAHL_API_KEY",
                 "text_only": True, "proxy": "direct"},
        "nokey": {"base_url": "https://n.example/v1", "key_env": "NOKEY_API_KEY"},
    },
    "tiers": {
        "bulk": [{"profile": "avalai", "model": "cheap-a"}, {"profile": "avalai", "model": "cheap-b"}],
        "worker": [{"profile": "nokey", "model": "w0"},
                   {"profile": "avalai", "model": "work-a"},
                   {"profile": "gemini", "model": "work-g", "price": {"input": 1, "output": 2}}],
        "premium": [{"profile": "avalai", "model": "prem"}],
    },
    "escalation": ["bulk", "worker", "premium"],
    "tasks": {
        "hooks": {"tier": "worker", "json": True},
        "classification": {"tier": "bulk", "json": True},
        "outline_draft": {"tier": "worker"},
        "narration_final": {"tier": "premium", "final_persian": True},
    },
    "defaults": {"timeout_seconds": 5, "temperature": 0.7, "max_tokens": 100},
}


@pytest.fixture
def routing_path(tmp_path, monkeypatch):
    path = tmp_path / "llm_routing.yaml"
    path.write_text(yaml.safe_dump(ROUTING), encoding="utf-8")
    monkeypatch.setenv("AVALAI_API_KEY", KEY)
    monkeypatch.setenv("GOOGLE_API_KEY", "g-key-abcdef123456")
    monkeypatch.setenv("DAHL_API_KEY", DAHL_KEY)
    monkeypatch.delenv("NOKEY_API_KEY", raising=False)
    monkeypatch.setenv("OPENMONTAGE_LLM_CACHE_DIR", str(tmp_path / "cache"))
    monkeypatch.delenv("OPENMONTAGE_LLM_MODE", raising=False)
    return path


def _completion(content, prompt_tokens=100, completion_tokens=50, model="cheap-a"):
    return {
        "id": "x", "object": "chat.completion", "created": 0, "model": model,
        "choices": [{"index": 0, "finish_reason": "stop",
                     "message": {"role": "assistant", "content": content}}],
        "usage": {"prompt_tokens": prompt_tokens, "completion_tokens": completion_tokens,
                  "total_tokens": prompt_tokens + completion_tokens},
    }


class _Server:
    """Scripted responses; records every request."""

    def __init__(self, *responses):
        self.responses = list(responses)
        self.requests = []

    def __call__(self, request: httpx.Request) -> httpx.Response:
        self.requests.append(request)
        status, body = self.responses.pop(0)
        return httpx.Response(status, json=body)

    def bodies(self):
        return [json.loads(r.content) for r in self.requests]


def _llm(routing_path, server):
    return OpenAICompatLLM(routing_path=routing_path, transport=httpx.MockTransport(server))


# -- openai_compat_llm -----------------------------------------------------

def test_profile_without_key_is_unavailable_not_an_error(routing_path):
    llm = _llm(routing_path, _Server())
    assert llm.profile_status("nokey") == (False, "NOKEY_API_KEY not set")
    r = llm.execute({"profile": "nokey", "model": "m", "prompt": "hi"})
    assert not r.success and r.data["unavailable"]


def test_call_reports_cost_from_usage_and_sends_no_retry(routing_path):
    server = _Server((200, _completion("سلام", 1000, 500)))
    llm = _llm(routing_path, server)
    r = llm.execute({"profile": "avalai", "model": "cheap-a", "prompt": "hi",
                     "price": {"input": 0.15, "output": 0.6}})
    assert r.success and r.data["text"] == "سلام"
    assert r.cost_usd == pytest.approx((1000 * 0.15 + 500 * 0.6) / 1e6)
    body = server.bodies()[0]
    assert body["model"] == "cheap-a" and body["max_tokens"] == 100
    assert "response_format" not in body
    assert server.requests[0].headers["authorization"] == f"Bearer {KEY}"


def test_price_falls_back_to_pricing_table(routing_path):
    server = _Server((200, _completion("ok", 1_000_000, 0)))
    llm = _llm(routing_path, server)
    r = llm.execute({"profile": "avalai", "model": "claude-haiku-5-5", "prompt": "x"})
    assert r.cost_usd == pytest.approx(0.1)  # config/fa_pricing.yaml
    r2 = _llm(routing_path, _Server((200, _completion("ok")))).execute(
        {"profile": "avalai", "model": "unknown-model", "prompt": "x"})
    assert r2.data["cost_status"] == "unquoted" and r2.cost_usd == 0.0


def test_server_error_is_one_request_and_a_clean_failure(routing_path):
    server = _Server((500, {"error": {"message": "upstream down"}}))
    r = _llm(routing_path, server).execute({"profile": "avalai", "model": "m", "prompt": "x"})
    assert not r.success and "InternalServerError" in r.error
    assert len(server.requests) == 1  # max_retries=0


def test_json_mode_repairs_once(routing_path):
    schema = {"type": "object", "required": ["hooks"],
              "properties": {"hooks": {"type": "array", "minItems": 2}}}
    server = _Server((200, _completion('{"hooks": ["one"]}', 10, 5)),
                     (200, _completion('```json\n{"hooks": ["one", "two"]}\n```', 20, 5)))
    r = _llm(routing_path, server).execute({
        "profile": "avalai", "model": "m", "prompt": "hooks", "json_mode": True,
        "json_schema": schema, "price": {"input": 1, "output": 1}})
    assert r.success and r.data["repaired"]
    assert r.data["json"] == {"hooks": ["one", "two"]}
    assert r.data["usage"] == {"prompt_tokens": 30, "completion_tokens": 10}
    first, second = server.bodies()
    assert first["response_format"] == {"type": "json_object"}
    assert second["messages"][-2]["role"] == "assistant"
    assert "minItems" in second["messages"][-1]["content"] or "too short" in second["messages"][-1]["content"]


def test_json_still_invalid_after_repair_is_rejected(routing_path):
    server = _Server((200, _completion("not json")), (200, _completion("still not")))
    r = _llm(routing_path, server).execute(
        {"profile": "avalai", "model": "m", "prompt": "x", "json_mode": True})
    assert not r.success and r.data["rejected"] and len(server.requests) == 2


def test_temperature_zero_is_cached(routing_path):
    server = _Server((200, _completion("deterministic")))
    llm = _llm(routing_path, server)
    call = {"profile": "avalai", "model": "m", "prompt": "same", "temperature": 0}
    first = llm.execute(call)
    second = llm.execute(call)
    assert first.success and second.success and second.from_cache
    assert second.cost_usd == 0.0 and second.data["text"] == "deterministic"
    assert len(server.requests) == 1
    # A non-zero temperature is never served from cache.
    server.responses.append((200, _completion("fresh")))
    assert llm.execute({**call, "temperature": 0.5}).data["text"] == "fresh"


def test_key_never_leaks_into_errors_results_or_cache(routing_path, tmp_path):
    leaky = {"error": {"message": f"Invalid key {KEY} (Bearer {KEY})"}}
    r = _llm(routing_path, _Server((401, leaky))).execute(
        {"profile": "avalai", "model": "m", "prompt": "x"})
    assert not r.success
    assert KEY not in r.error and KEY not in json.dumps(r.data)

    class Boom:
        def __init__(self, *a, **k):
            raise RuntimeError(f"connect failed with api_key={KEY}")

    llm = _llm(routing_path, _Server())
    llm._client = Boom
    r2 = llm.execute({"profile": "avalai", "model": "m", "prompt": "x"})
    assert KEY not in r2.error

    _llm(routing_path, _Server((200, _completion("ok")))).execute(
        {"profile": "avalai", "model": "m", "prompt": "x", "temperature": 0})
    for f in (tmp_path / "cache").rglob("*.json"):
        assert KEY not in f.read_text(encoding="utf-8")


def test_redact_patterns():
    assert redact(f"Authorization: Bearer {KEY}") == "Authorization: Bearer ***"
    assert redact("url?key=AIzaSyabc123&x=1") == "url?key=***&x=1"
    assert "secretvalue" not in redact("x secretvalue y", ["secretvalue"])


def test_direct_profiles_ignore_proxy_env(routing_path, monkeypatch):
    seen = {}

    class Spy(httpx.Client):
        def __init__(self, **kwargs):
            seen.update(kwargs)
            super().__init__(**kwargs)

    monkeypatch.setattr(httpx, "Client", Spy)
    llm = _llm(routing_path, _Server())
    llm._client(ROUTING["profiles"]["avalai"], KEY, 5)
    assert seen["trust_env"] is False and seen["timeout"] == 5
    llm._client(ROUTING["profiles"]["gemini"], "k", 5)
    assert seen["trust_env"] is True


def test_inline_reasoning_is_stripped_and_dahl_is_priced_from_the_table(routing_path):
    reply = "<think>The user wants Persian.\nLet me think.</think>\n\nسلام"
    server = _Server((200, _completion(reply, 1_000_000, 1_000_000, model="MiniMaxAI/MiniMax-M2.7")))
    r = _llm(routing_path, server).execute(
        {"profile": "dahl", "model": "MiniMaxAI/MiniMax-M2.7", "prompt": "hi"})
    assert r.success and r.data["text"] == "سلام"
    assert r.cost_usd == pytest.approx(0.04)  # $0.02 per 1M in + out
    assert server.requests[0].url.host == "inference.dahl.global"
    assert server.requests[0].headers["authorization"] == f"Bearer {DAHL_KEY}"


def test_json_after_a_reasoning_block_parses_without_repair(routing_path):
    server = _Server((200, _completion('<think>JSON only.</think>{"hooks": ["a", "b"]}')))
    r = _llm(routing_path, server).execute(
        {"profile": "dahl", "model": "m", "prompt": "x", "json_mode": True})
    assert r.success and r.data["json"] == {"hooks": ["a", "b"]} and not r.data["repaired"]
    assert len(server.requests) == 1


def test_strip_reasoning():
    assert strip_reasoning("no reasoning here") == "no reasoning here"
    assert strip_reasoning("  <think>a\nb</think>  answer") == "answer"
    # Cut off while still thinking: nothing usable.
    assert strip_reasoning("<think>still going") == ""
    # Only a leading block is reasoning; later tags are content.
    assert strip_reasoning("answer <think>x</think>") == "answer <think>x</think>"


def test_text_only_profile_refuses_images_without_a_request(routing_path, tmp_path):
    image = tmp_path / "frame.png"
    image.write_bytes(b"not really a png")
    server = _Server()
    r = _llm(routing_path, server).execute(
        {"profile": "dahl", "model": "m", "prompt": "label", "images": [str(image)]})
    assert not r.success and "text-only" in r.error
    assert server.requests == []


def test_dahl_key_is_redacted():
    assert redact(f"bad key {DAHL_KEY}") == "bad key dahl_***"


def test_busy_dahl_model_falls_through_to_the_next_entry(routing_path):
    routing = yaml.safe_load(routing_path.read_text(encoding="utf-8"))
    routing["tiers"]["bulk"] = [{"profile": "dahl", "model": "zai-org/GLM-5.3-Flash"},
                                {"profile": "avalai", "model": "cheap-a"}]
    routing_path.write_text(yaml.safe_dump(routing), encoding="utf-8")
    busy = {"error": {"code": "model_concurrency", "type": "rate_limit_error",
                      "message": "This model is at concurrency capacity."}}

    def handler(request):
        if request.url.host == "inference.dahl.global":
            return httpx.Response(429, json=busy, headers={"Retry-After": "5"})
        return httpx.Response(200, json=_completion('{"label": "x"}'))

    llm = OpenAICompatLLM(routing_path=routing_path, transport=httpx.MockTransport(handler))
    r = LLMSelector(llm=llm, routing_path=routing_path).execute(
        {"task": "classification", "prompt": "x"})
    assert r.success and r.data["profile"] == "avalai"
    assert [a["outcome"] for a in r.data["attempts"]] == ["failed", "accepted"]
    assert r.data["fallback_from"][0]["profile"] == "dahl"


def test_extract_json_handles_fences():
    assert extract_json('```json\n{"a": 1}\n```') == {"a": 1}
    assert extract_json(' [1, 2] ') == [1, 2]


# -- llm_selector ------------------------------------------------------------

class _FakeLLM(OpenAICompatLLM):
    """Answers per model from a script; records calls."""

    def __init__(self, routing_path, script):
        super().__init__(routing_path=routing_path)
        self.script = script
        self.calls = []

    def execute(self, inputs):
        self.calls.append(inputs["model"])
        ok, reason = self.profile_status(inputs["profile"])
        if not ok:
            return ToolResult(success=False, error=f"profile unavailable: {reason}",
                              data={"unavailable": True})
        outcome = self.script.get(inputs["model"], "ok")
        if outcome == "fail":
            return ToolResult(success=False, error="<html><body>403 Forbidden</body></html>")
        if outcome == "reject":
            return ToolResult(success=False, data={"rejected": True, "rejection": "not JSON"},
                              cost_usd=0.001)
        return ToolResult(success=True, cost_usd=0.002,
                          data={"text": "done", "json": {"hooks": [1]}, "profile": inputs["profile"],
                                "model": inputs["model"]})


def _selector(routing_path, script=None, validator=None):
    fake = _FakeLLM(routing_path, script or {})
    return LLMSelector(llm=fake, routing_path=routing_path, validator=validator), fake


def test_unavailable_and_failing_entries_fall_through(routing_path):
    sel, fake = _selector(routing_path, {"work-a": "fail"})
    r = sel.execute({"task": "hooks", "prompt": "x"})
    assert r.success and r.data["model"] == "work-g" and r.data["tier"] == "worker"
    assert fake.calls == ["work-a", "work-g"]  # w0 has no key: never called
    froms = [f["model"] for f in r.data["fallback_from"]]
    assert froms == ["w0", "work-a"]
    assert r.data["fallback_from"][1]["error"] == "403 Forbidden"


def test_two_rejections_escalate_to_the_next_tier(routing_path):
    sel, fake = _selector(routing_path, {"cheap-a": "reject", "cheap-b": "reject"})
    r = sel.execute({"task": "classification", "prompt": "x"})
    assert r.success and r.data["tier"] == "worker"
    assert r.data["escalated_from"] == "bulk answers rejected 2 times"
    assert r.cost_usd == pytest.approx(0.001 + 0.001 + 0.002)


def test_interactive_premium_goes_back_to_the_agent(routing_path):
    sel, fake = _selector(routing_path, {"work-a": "reject", "work-g": "reject"})
    r = sel.execute({"task": "hooks", "prompt": "x"})
    assert not r.success and r.data["escalated_to"] == "agent"
    assert "ESCALATE TO AGENT" in r.error and "worker answers rejected 2 times" in r.error
    assert "prem" not in fake.calls


def test_validator_rejections_count(routing_path):
    sel, fake = _selector(routing_path, validator=lambda data: "too generic")
    r = sel.execute({"task": "outline_draft", "prompt": "x"})
    assert r.data["escalated_to"] == "agent"
    assert [a["outcome"] for a in r.data["attempts"]] == ["unavailable", "rejected", "rejected"]


def test_final_persian_never_goes_to_a_cheap_model(routing_path):
    sel, fake = _selector(routing_path)
    r = sel.execute({"task": "narration_final", "prompt": "x"})
    assert r.data["escalated_to"] == "agent" and fake.calls == []
    headless = sel.execute({"task": "narration_final", "prompt": "x", "mode": "headless"})
    assert headless.success and fake.calls == ["prem"]


def test_mode_env_override(routing_path, monkeypatch):
    sel, _ = _selector(routing_path)
    monkeypatch.setenv("OPENMONTAGE_LLM_MODE", "headless")
    assert sel.run_mode({}) == "headless"


def test_costs_are_written_to_the_ledger(routing_path, tmp_path):
    sel, _ = _selector(routing_path, {"work-a": "fail"})
    log = tmp_path / "cost_log.json"
    sel.execute({"task": "hooks", "prompt": "x", "cost_log_path": str(log)})
    entries = json.loads(log.read_text(encoding="utf-8"))["entries"]
    assert [e["status"] for e in entries] == ["failed", "completed"]
    assert entries[1]["actual_usd"] == pytest.approx(0.002)


def test_plan_lists_entries_without_calling(routing_path):
    sel, fake = _selector(routing_path)
    r = sel.execute({"operation": "plan", "task": "hooks"})
    assert [e["model"] for e in r.data["entries"]] == ["w0", "work-a", "work-g", "prem"]
    assert r.data["entries"][0]["available"] is False and fake.calls == []


def test_batch_runs_items_in_parallel_and_isolates_failures(routing_path):
    sel, fake = _selector(routing_path, {"cheap-a": "fail", "cheap-b": "fail",
                                         "work-a": "fail", "work-g": "fail"})
    items = [{"id": "a", "task": "outline_draft", "prompt": "1"},
             {"id": "b", "task": "classification", "prompt": "2"}]
    r = sel.execute({"operation": "batch", "items": items})
    assert not r.success
    assert r.data["summary"]["total"] == 2 and r.data["summary"]["succeeded"] == 0


def test_unknown_task(routing_path):
    sel, _ = _selector(routing_path)
    assert "unknown task" in sel.execute({"task": "nope", "prompt": "x"}).error


def test_cli_writes_result(routing_path, tmp_path, monkeypatch, capsysbinary):
    src = tmp_path / "in.txt"
    src.write_text("موضوع: سامسونگ", encoding="utf-8")
    out = tmp_path / "out.json"
    seen = {}

    def fake_execute(self, inputs):
        seen.update(inputs)
        return ToolResult(success=True, cost_usd=0.0004, data={
            "json": {"hooks": ["الف"]}, "model": "work-a", "profile": "avalai",
            "tier": "worker", "fallback_from": [{"model": "w0", "error": "NOKEY_API_KEY not set"}]})

    monkeypatch.setattr(LLMSelector, "execute", fake_execute)
    code = selector_mod.main(["--task", "hooks", "--input", str(src), "--out", str(out)])
    assert code == 0 and seen["prompt"] == "موضوع: سامسونگ"
    result = json.loads(out.read_text(encoding="utf-8"))
    assert result["result"] == {"hooks": ["الف"]} and result["model"] == "work-a"
    assert result["cost_usd"] == 0.0004 and result["fallback_from"][0]["model"] == "w0"
