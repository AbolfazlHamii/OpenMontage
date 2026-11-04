"""One tool for every OpenAI-compatible chat endpoint.

AvalAI, Moonshot, OpenRouter, Ollama and Gemini's OpenAI endpoint all speak
/v1/chat/completions, so they are profiles in config/llm_routing.yaml rather
than separate tools. A profile whose key is missing reports unavailable; it
never raises.

What this tool owns:
- cost from the response's `usage`, priced from the routing entry or
  config/fa_pricing.yaml (unknown price -> cost_status "unquoted");
- a content-addressed cache for temperature 0 calls (`.llm_cache/`);
- JSON mode: parse, validate against `json_schema`, one repair retry;
- timeouts, proxy choice per profile, and no SDK auto-retry (max_retries=0;
  llm_selector decides what to retry);
- keys never reach errors, logs or results (`redact`).
"""

from __future__ import annotations

import base64
import hashlib
import json
import mimetypes
import os
import re
from pathlib import Path
from typing import Any, Optional

import yaml

from tools.base_tool import (
    BaseTool,
    Determinism,
    ExecutionMode,
    ToolResult,
    ToolRuntime,
    ToolStability,
    ToolStatus,
    ToolTier,
)

REPO_ROOT = Path(__file__).resolve().parents[2]
ROUTING_PATH = REPO_ROOT / "config" / "llm_routing.yaml"
PRICING_PATH = REPO_ROOT / "config" / "fa_pricing.yaml"
CACHE_ENV = "OPENMONTAGE_LLM_CACHE_DIR"

_SECRET_PATTERNS = [
    (re.compile(r"(?i)(bearer\s+)[A-Za-z0-9._~+/=-]{6,}"), r"\1***"),
    (re.compile(r"\b(sk|aa)-[A-Za-z0-9_-]{8,}"), r"\1-***"),
    (re.compile(r"(?i)([?&](?:key|api_key|token)=)[^&\s\"']+"), r"\1***"),
]


def load_yaml(path: Path) -> dict[str, Any]:
    with open(path, encoding="utf-8") as f:
        return yaml.safe_load(f) or {}


def redact(text: Any, secrets: Optional[list[str]] = None) -> str:
    """Remove API keys from text bound for an error, a log or an artifact."""
    out = str(text)
    for secret in secrets or []:
        if secret and len(secret) >= 6:
            out = out.replace(secret, "***")
    for pattern, repl in _SECRET_PATTERNS:
        out = pattern.sub(repl, out)
    return out


def known_secrets(routing: dict[str, Any]) -> list[str]:
    names = {p.get("key_env") for p in routing.get("profiles", {}).values()}
    return [os.environ[n] for n in names if n and os.environ.get(n)]


def extract_json(text: str) -> Any:
    """Parse a JSON reply, tolerating a ```json fence around it."""
    stripped = text.strip()
    fence = re.match(r"^```(?:json)?\s*(.*?)\s*```$", stripped, re.S)
    if fence:
        stripped = fence.group(1)
    return json.loads(stripped)


def validate_json(data: Any, schema: Optional[dict[str, Any]]) -> Optional[str]:
    """None when valid, else a short reason."""
    if not schema:
        return None
    import jsonschema

    try:
        jsonschema.validate(data, schema)
    except jsonschema.ValidationError as exc:
        where = "/".join(str(p) for p in exc.absolute_path) or "(root)"
        return f"{where}: {exc.message}"[:300]
    return None


class OpenAICompatLLM(BaseTool):
    name = "openai_compat_llm"
    version = "0.1.0"
    tier = ToolTier.CORE
    capability = "text_generation"
    provider = "openai_compat"
    stability = ToolStability.EXPERIMENTAL
    execution_mode = ExecutionMode.SYNC
    determinism = Determinism.STOCHASTIC
    runtime = ToolRuntime.API

    dependencies = ["python:openai", "python:httpx"]
    install_instructions = (
        "Set the key for at least one profile in config/llm_routing.yaml "
        "(AVALAI_API_KEY, GOOGLE_API_KEY, MOONSHOT_API_KEY or OPENROUTER_API_KEY), "
        "or run Ollama locally."
    )
    agent_skills = ["provider-model-refresh"]
    capabilities = ["chat_completion", "json_mode", "vision"]
    best_for = ["bulk and worker text tasks behind llm_selector"]
    not_good_for = ["final Persian text that reaches viewers (premium review only)"]

    input_schema = {
        "type": "object",
        "required": ["profile", "model"],
        "properties": {
            "profile": {"type": "string"},
            "model": {"type": "string"},
            "messages": {"type": "array", "items": {"type": "object"}},
            "prompt": {"type": "string"},
            "system": {"type": "string"},
            "images": {"type": "array", "items": {"type": "string"},
                       "description": "Local image paths sent with the prompt (vision)."},
            "temperature": {"type": "number", "default": 0.7},
            "max_tokens": {"type": "integer", "default": 2048},
            "json_mode": {"type": "boolean", "default": False},
            "json_schema": {"type": "object"},
            "timeout_seconds": {"type": "number", "default": 60},
            "use_cache": {"type": "boolean", "default": True},
            "price": {"type": "object", "description": "USD per 1M tokens {input, output}"},
        },
    }
    side_effects = ["paid API call (except Ollama)", "writes .llm_cache/ entries for temperature 0"]

    def __init__(self, routing_path: Path = ROUTING_PATH, transport: Any = None):
        self.routing_path = routing_path
        # Tests pass an httpx.MockTransport here; no socket is ever opened.
        self.transport = transport

    # -- configuration ----------------------------------------------------

    @property
    def routing(self) -> dict[str, Any]:
        return load_yaml(self.routing_path)

    def profile_status(self, profile: str) -> tuple[bool, str]:
        cfg = self.routing.get("profiles", {}).get(profile)
        if cfg is None:
            return False, f"unknown profile {profile!r}"
        key_env = cfg.get("key_env")
        if key_env and not os.environ.get(key_env):
            return False, f"{key_env} not set"
        return True, "ok"

    def get_status(self) -> ToolStatus:
        profiles = self.routing.get("profiles", {})
        if any(self.profile_status(p)[0] and not cfg.get("local")
               for p, cfg in profiles.items()):
            return ToolStatus.AVAILABLE
        return ToolStatus.UNAVAILABLE

    def price_for(self, profile: str, model: str,
                  explicit: Optional[dict[str, float]] = None) -> Optional[dict[str, float]]:
        if explicit:
            return explicit
        if self.routing.get("profiles", {}).get(profile, {}).get("local"):
            return {"input": 0.0, "output": 0.0}
        try:
            return load_yaml(PRICING_PATH).get("llm", {}).get(profile, {}).get(model)
        except OSError:
            return None

    def estimate_cost(self, inputs: dict[str, Any]) -> float:
        price = self.price_for(inputs.get("profile", ""), inputs.get("model", ""), inputs.get("price"))
        if not price:
            return 0.0
        chars = sum(len(str(m.get("content", ""))) for m in self._messages(inputs))
        out_tokens = inputs.get("max_tokens", 2048)
        return round((chars / 3 * price["input"] + out_tokens * price["output"]) / 1_000_000, 6)

    # -- request building -------------------------------------------------

    @staticmethod
    def _messages(inputs: dict[str, Any]) -> list[dict[str, Any]]:
        if inputs.get("messages"):
            return list(inputs["messages"])
        messages = []
        if inputs.get("system"):
            messages.append({"role": "system", "content": inputs["system"]})
        content: Any = inputs.get("prompt", "")
        if inputs.get("images"):
            parts = [{"type": "text", "text": content}]
            for path in inputs["images"]:
                mime = mimetypes.guess_type(path)[0] or "image/png"
                data = base64.b64encode(Path(path).read_bytes()).decode("ascii")
                parts.append({"type": "image_url", "image_url": {"url": f"data:{mime};base64,{data}"}})
            content = parts
        messages.append({"role": "user", "content": content})
        return messages

    @staticmethod
    def cache_key(profile: str, model: str, messages: list[dict[str, Any]],
                  json_mode: bool, schema: Optional[dict[str, Any]], max_tokens: int) -> str:
        blob = json.dumps([profile, model, messages, json_mode, schema, max_tokens],
                          ensure_ascii=False, sort_keys=True)
        return hashlib.sha256(blob.encode("utf-8")).hexdigest()

    @staticmethod
    def cache_dir() -> Path:
        return Path(os.environ.get(CACHE_ENV) or REPO_ROOT / ".llm_cache")

    def _client(self, cfg: dict[str, Any], api_key: str, timeout: float):
        import httpx
        import openai

        http_client = httpx.Client(
            timeout=timeout,
            trust_env=cfg.get("proxy", "env") == "env",
            transport=self.transport,
        )
        return openai.OpenAI(
            base_url=cfg["base_url"],
            api_key=api_key or "unused",
            max_retries=0,
            timeout=timeout,
            http_client=http_client,
        )

    def _complete(self, client, request: dict[str, Any]) -> tuple[str, dict[str, int], str]:
        resp = client.chat.completions.create(**request)
        text = resp.choices[0].message.content or ""
        usage = resp.usage
        tokens = {
            "prompt_tokens": getattr(usage, "prompt_tokens", 0) or 0,
            "completion_tokens": getattr(usage, "completion_tokens", 0) or 0,
        }
        return text, tokens, getattr(resp, "model", request["model"])

    # -- execute ----------------------------------------------------------

    def execute(self, inputs: dict[str, Any]) -> ToolResult:
        routing = self.routing
        secrets = known_secrets(routing)
        profile = inputs["profile"]
        model = inputs["model"]
        ok, reason = self.profile_status(profile)
        if not ok:
            return ToolResult(success=False, error=f"profile {profile} unavailable: {reason}",
                              data={"unavailable": True, "profile": profile})
        cfg = routing["profiles"][profile]
        defaults = routing.get("defaults", {})
        timeout = float(inputs.get("timeout_seconds", defaults.get("timeout_seconds", 60)))
        temperature = float(inputs.get("temperature", defaults.get("temperature", 0.7)))
        max_tokens = int(inputs.get("max_tokens", defaults.get("max_tokens", 2048)))
        json_mode = bool(inputs.get("json_mode"))
        schema = inputs.get("json_schema")
        price = self.price_for(profile, model, inputs.get("price"))
        try:
            messages = self._messages(inputs)
        except OSError as exc:
            return ToolResult(success=False, error=f"cannot read image: {exc}")

        use_cache = temperature == 0 and inputs.get("use_cache", True)
        key = self.cache_key(profile, model, messages, json_mode, schema, max_tokens)
        cache_file = self.cache_dir() / key[:2] / f"{key}.json"
        if use_cache and cache_file.exists():
            cached = json.loads(cache_file.read_text(encoding="utf-8"))
            return ToolResult(success=True, data={**cached, "from_cache": True},
                              cost_usd=0.0, model=cached.get("model"), from_cache=True)

        request: dict[str, Any] = {
            "model": model,
            "messages": messages,
            "temperature": temperature,
            "max_tokens": max_tokens,
        }
        if json_mode:
            request["response_format"] = {"type": "json_object"}

        api_key = os.environ.get(cfg.get("key_env") or "", "")
        usage = {"prompt_tokens": 0, "completion_tokens": 0}
        try:
            client = self._client(cfg, api_key, timeout)
            text, u, served_model = self._complete(client, request)
            usage = {k: usage[k] + u[k] for k in usage}
            parsed, rejection, repaired = None, None, False
            if json_mode:
                parsed, rejection = self._parse(text, schema)
                if rejection:
                    repaired = True
                    request["messages"] = messages + [
                        {"role": "assistant", "content": text},
                        {"role": "user", "content": (
                            "That reply was not valid for the required JSON format "
                            f"({rejection}). Reply again with only the corrected JSON."
                        )},
                    ]
                    text, u, served_model = self._complete(client, request)
                    usage = {k: usage[k] + u[k] for k in usage}
                    parsed, rejection = self._parse(text, schema)
        except Exception as exc:
            from tools.provider_routing import short_error

            return ToolResult(
                success=False,
                error=redact(f"{type(exc).__name__}: {short_error(exc)}", secrets),
                data={"profile": profile, "model": model},
            )

        cost = None
        if price is not None:
            cost = round((usage["prompt_tokens"] * price["input"]
                          + usage["completion_tokens"] * price["output"]) / 1_000_000, 8)
        data = {
            "text": text,
            "json": parsed,
            "profile": profile,
            "model": model,
            "served_model": served_model,
            "usage": usage,
            "cost_status": "metered" if cost is not None else "unquoted",
            "repaired": repaired,
            "from_cache": False,
        }
        if json_mode and rejection:
            return ToolResult(success=False, data={**data, "rejected": True, "rejection": rejection},
                              error=f"invalid JSON after one repair: {rejection}",
                              cost_usd=cost or 0.0, model=model)
        if use_cache:
            cache_file.parent.mkdir(parents=True, exist_ok=True)
            cache_file.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")
        return ToolResult(success=True, data=data, cost_usd=cost or 0.0, model=model)

    @staticmethod
    def _parse(text: str, schema: Optional[dict[str, Any]]) -> tuple[Any, Optional[str]]:
        try:
            parsed = extract_json(text)
        except (json.JSONDecodeError, ValueError) as exc:
            return None, f"not JSON: {exc.msg if hasattr(exc, 'msg') else exc}"
        return parsed, validate_json(parsed, schema)
