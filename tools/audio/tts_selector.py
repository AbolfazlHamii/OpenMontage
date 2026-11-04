"""Capability-level text-to-speech selector that chooses among provider tools.

Provider discovery is automatic — any BaseTool with capability="tts"
is picked up from the registry.  Adding a new TTS provider requires only creating
the tool file in tools/audio/; no changes to this selector are needed.
"""

from __future__ import annotations

import re
from typing import Any

from tools.base_tool import (
    BaseTool,
    ToolResult,
    ToolRuntime,
    ToolStability,
    ToolTier,
    ToolStatus,
)

# ---- Language-aware routing -------------------------------------------------
# The scorer in lib/scoring.py has no notion of language, so for Persian text it
# could pick Piper (English model by default), ElevenLabs multilingual_v2 (no
# Persian) or Google Cloud TTS (no fa-IR Chirp voices) and produce garbage
# without any error. Persian is therefore routed by an explicit, ordered
# allowlist of tools known to speak it, with the inputs each one needs.

_ARABIC_SCRIPT = re.compile(r"[؀-ۿݐ-ݿﭐ-﷿ﹰ-﻿]")
# Letters Persian uses and Arabic does not: پ چ ژ گ and the Persian kāf/yeh.
_PERSIAN_LETTERS = re.compile(r"[پچژگکی]")

PERSIAN_TTS_PRIORITY = [
    "gemini_tts",      # Gemini 3.8 Flash TTS lists Iranian Persian; style control
    "avalai_gemini_tts",  # same Gemini voices via AvalAI when Google is unreachable
    "elevenlabs_tts",  # only with eleven_v3 (language_code=fa selects it)
    "openai_tts",      # gpt-4o-mini-tts reads Persian; no Persian-native voice
    "azure_tts",       # fa-IR neural voices
    "piper_tts",       # offline fallback; needs a downloaded fa_IR voice
]
PERSIAN_TOOL_DEFAULTS: dict[str, dict[str, Any]] = {
    "elevenlabs_tts": {"language_code": "fa"},
    "azure_tts": {"voice": "fa-IR-DilaraNeural", "locale": "fa-IR"},
    "piper_tts": {"model": "fa_IR-amir-medium"},
}


def detect_text_language(text: str) -> str | None:
    """Return "fa" for Persian text, else None (unknown / leave to the scorer)."""
    words = text.split()
    if not words:
        return None
    arabic_script = sum(1 for w in words if _ARABIC_SCRIPT.search(w))
    if arabic_script * 2 <= len(words):
        return None
    return "fa" if _PERSIAN_LETTERS.search(text) else None


def resolve_tts_language(inputs: dict[str, Any]) -> str | None:
    """Explicit language_code wins; otherwise detect from the text."""
    code = str(inputs.get("language_code") or "").strip().lower()
    if code:
        return "fa" if code.split("-")[0] in {"fa", "fas", "per"} else None
    return detect_text_language(str(inputs.get("text") or ""))


class TTSSelector(BaseTool):
    name = "tts_selector"
    version = "0.2.0"
    tier = ToolTier.VOICE
    capability = "tts"
    provider = "selector"
    stability = ToolStability.BETA
    runtime = ToolRuntime.HYBRID
    agent_skills = ["text-to-speech", "elevenlabs"]

    capabilities = [
        "text_to_speech",
        "provider_selection",
    ]
    supports = {
        "user_preference_routing": True,
        "offline_fallback": True,
        "multilingual": True,
    }
    best_for = [
        "preflight tool selection",
        "user-facing recommendation flows",
    ]

    input_schema = {
        "type": "object",
        "required": ["text"],
        "properties": {
            "preferred_tool": {
                "type": "string",
                "description": "Exact tool name; never falls back.",
            },
            "hosting_provider": {
                "type": "string",
                "description": "Required API host, e.g. fal.ai, atlascloud, replicate.",
            },
            "text": {"type": "string"},
            "voice_id": {
                "type": "string",
                "description": "Provider-specific voice ID. Passed through to the selected TTS provider.",
            },
            "voice": {
                "type": "string",
                "description": "Provider-specific voice name or ID. fal.ai ElevenLabs accepts names such as Rachel.",
            },
            "voice_language": {
                "type": "string",
                "enum": ["zh", "en"],
                "description": "Kling official voice language. Passed through when selected provider supports it.",
            },
            "voice_speed": {
                "type": "number",
                "minimum": 0.5,
                "maximum": 2.0,
                "description": "Kling official voice speed. Use speed for OpenAI/ElevenLabs-style controls.",
            },
            "model_id": {
                "type": "string",
                "description": "TTS model to use (e.g. eleven-v3 or eleven_multilingual_v2). Passed through to provider.",
            },
            "stability": {
                "type": "number",
                "minimum": 0,
                "maximum": 1,
                "description": "Voice stability (ElevenLabs). Lower = more expressive.",
            },
            "similarity_boost": {
                "type": "number",
                "minimum": 0,
                "maximum": 1,
                "description": "Voice similarity boost (ElevenLabs).",
            },
            "style": {
                "type": ["number", "string"],
                "description": "Style exaggeration (ElevenLabs). Higher = more expressive.",
            },
            "instructions": {
                "type": "string",
                "description": "Provider-level delivery instructions for expressive narration when supported.",
            },
            "speaking_rate": {
                "type": "number",
                "minimum": 0.25,
                "maximum": 2.0,
                "description": "Google-style speakingRate control. Use speed for OpenAI/ElevenLabs-style controls.",
            },
            "speed": {
                "type": "number",
                "minimum": 0.25,
                "maximum": 4.0,
                "description": "Alias for speaking speed used by some providers.",
            },
            "pitch": {
                "type": "number",
                "minimum": -50,
                "maximum": 50,
                "description": "Provider-specific pitch control. Google TTS accepts -20..20; HeyGen-style providers may accept wider ranges.",
            },
            "input_type": {
                "type": "string",
                "enum": ["text", "ssml"],
                "default": "text",
                "description": "Use 'ssml' only when the selected provider supports tags such as <break>.",
            },
            "language_code": {
                "type": "string",
                "description": "Provider-specific language code, such as en-US for Google or en for fal.ai ElevenLabs.",
            },
            "timestamps": {
                "type": "boolean",
                "default": False,
                "description": "Request word timestamps when the selected provider supports them.",
            },
            "apply_text_normalization": {
                "type": "string",
                "enum": ["auto", "on", "off"],
                "description": "Text normalization mode for providers that support it.",
            },
            "seed": {
                "type": "integer",
                "description": "Optional generation seed for providers that support reproducible speech.",
            },
            "voice_performance": {
                "type": "object",
                "description": "Structured voice-performance plan or section delivery cues from the script artifact.",
            },
            "sample_mode": {
                "type": "boolean",
                "default": False,
                "description": "True when generating an approval sample before batch narration.",
            },
            "output_format": {
                "type": ["string", "object"],
                "description": "Audio output format (e.g. mp3_44100_128). Passed through to provider.",
            },
            "preferred_provider": {
                "type": "string",
                "description": "Provider name or 'auto'. Valid values are discovered at runtime from the registry.",
                "default": "auto",
            },
            "allowed_providers": {
                "type": "array",
                "items": {"type": "string"},
            },
            "operation": {
                "type": "string",
                "enum": ["generate", "rank"],
                "default": "generate",
                "description": "Operation mode. 'rank' returns scored provider rankings without generating.",
            },
            "output_path": {"type": "string"},
        },
    }

    def _providers(self) -> list[BaseTool]:
        """Auto-discover TTS providers from the registry."""
        from tools.tool_registry import registry

        registry.ensure_discovered()
        return [t for t in registry.get_by_capability("tts") if t.name != self.name]

    @property
    def fallback_tools(self) -> list[str]:
        """Dynamically built from discovered providers."""
        return [t.name for t in self._providers()]

    @property
    def provider_matrix(self) -> dict[str, dict[str, str]]:
        """Built at runtime from each provider's best_for field."""
        matrix = {}
        for tool in self._providers():
            strength = ", ".join(tool.best_for) if tool.best_for else tool.name
            matrix[tool.provider] = {"tool": tool.name, "strength": strength}
        return matrix

    def get_status(self) -> ToolStatus:
        if any(tool.get_status() == ToolStatus.AVAILABLE for tool in self._providers()):
            return ToolStatus.AVAILABLE
        return ToolStatus.UNAVAILABLE

    def estimate_cost(self, inputs: dict[str, Any]) -> float:
        candidates = self._providers()
        if not candidates:
            return 0.0
        tool, _ = self._select_best_tool(
            inputs, candidates, self._prepare_task_context(inputs)
        )
        return tool.estimate_cost(inputs) if tool else 0.0

    def execute(self, inputs: dict[str, Any]) -> ToolResult:
        from lib.scoring import rank_providers

        task_context = self._prepare_task_context(inputs)
        from tools.provider_routing import filter_explicit_route, short_error

        candidates = filter_explicit_route(inputs, self._providers())

        # Rank mode — return scored provider rankings without generating
        if inputs.get("operation") == "rank":
            rankings = rank_providers(candidates, task_context)
            return ToolResult(
                success=True,
                data={
                    "rankings": self._serialize_rankings(candidates, rankings),
                    "explanation": "\n".join(r.explain() for r in rankings[:5]),
                    "normalized_task_context": task_context,
                },
            )

        # Normal generation — use scored selection
        language = resolve_tts_language(inputs)
        # Persian falls through PERSIAN_TTS_PRIORITY when a provider fails at
        # call time (e.g. Gemini refusing the caller's region), so AvalAI can
        # stand in for Google. Other languages keep single-shot behavior.
        fall_through = language == "fa" and inputs.get("preferred_provider", "auto") == "auto"
        failures: list[dict[str, str]] = []
        while True:
            tool, score = self._select_best_tool(
                inputs,
                [c for c in candidates if c.name not in {f["tool"] for f in failures}],
                task_context,
            )
            if tool is None:
                if failures:
                    return ToolResult(
                        success=False,
                        error="All Persian TTS providers failed: " + "; ".join(
                            f"{f['tool']}: {f['error']}" for f in failures
                        ),
                    )
                if language == "fa":
                    return ToolResult(
                        success=False,
                        error=(
                            "No Persian-capable TTS provider is available. Configure one of: "
                            + ", ".join(PERSIAN_TTS_PRIORITY)
                            + " (e.g. GOOGLE_API_KEY for gemini_tts, AVALAI_API_KEY "
                            "for avalai_gemini_tts)."
                        ),
                    )
                return ToolResult(success=False, error="No TTS provider available.")

            try:
                adapted = self._adapt_inputs(tool, inputs)
            except (ValueError, TypeError) as exc:
                return ToolResult(success=False, error=str(exc))
            if language == "fa":
                for key, value in PERSIAN_TOOL_DEFAULTS.get(tool.name, {}).items():
                    adapted.setdefault(key, value)
            result = tool.execute(adapted)
            if result.success or not fall_through:
                break
            failures.append({"tool": tool.name, "error": short_error(result.error)})

        if result.success:
            if failures:
                # A different provider may mean a different voice; let the
                # director notice before it mixes clips from two providers.
                result.data["fallback_from"] = failures
            if language:
                result.data.setdefault("language", language)
            # Pipelines check narration length against the edit (explainer
            # scene/compose directors read audio_duration_seconds), but many
            # providers do not report it. Measure it here for all of them.
            if result.data.get("audio_duration_seconds") is None:
                output = result.data.get("output") or (result.artifacts or [None])[0]
                if output:
                    try:
                        from tools.analysis.audio_probe import probe_duration

                        duration = probe_duration(output)
                        if duration:
                            result.data["audio_duration_seconds"] = round(duration, 2)
                    except Exception:  # duration is best-effort metadata
                        pass
            result.data.setdefault("selected_tool", tool.name)
            result.data["selected_provider"] = tool.provider
            result.data["selection_reason"] = (
                score.explain() if score else f"Selected {tool.provider} ({tool.name})"
            )
            if score:
                result.data["provider_score"] = score.to_dict()
            result.data.update(self._tool_context_payload(tool))
            result.data["alternatives_considered"] = [
                t.name
                for t in candidates
                if t.name != tool.name and t.get_status().value == "available"
            ]
        return result

    @staticmethod
    def _adapt_inputs(tool: BaseTool, inputs: dict[str, Any]) -> dict[str, Any]:
        """Translate capability-level controls to provider-native inputs."""
        adapted = dict(inputs)
        props = tool.input_schema.get("properties", {})
        if inputs.get("model") and "model_id" in props and "model" not in props:
            if inputs.get("model_id") and inputs["model_id"] != inputs["model"]:
                raise ValueError("model and model_id disagree")
            adapted["model_id"] = inputs["model"]
            adapted.pop("model", None)
        if tool.name not in {"azure_tts", "mai_tts"}:
            return adapted

        if inputs.get("voice_id") and not inputs.get("voice"):
            adapted["voice"] = inputs["voice_id"]

        speed = inputs.get("speaking_rate", inputs.get("speed"))
        if speed is not None and "rate" not in inputs:
            percent = round((float(speed) - 1.0) * 100)
            adapted["rate"] = f"{percent:+d}%" if percent else "0%"

        pitch = inputs.get("pitch")
        if isinstance(pitch, (int, float)):
            adapted["pitch"] = f"{pitch:+g}st" if pitch else "0%"

        # The selector's numeric style is ElevenLabs-specific. Azure's style
        # is a named express-as value such as "calm" or "newscast".
        if not isinstance(inputs.get("style"), str):
            adapted.pop("style", None)

        output_format = str(inputs.get("output_format", ""))
        if output_format.startswith("mp3"):
            adapted["output_format"] = "mp3"
        elif output_format.startswith(("wav", "riff", "pcm")):
            adapted["output_format"] = "wav"
        return adapted

    def _select_best_tool(
        self,
        inputs: dict[str, Any],
        candidates: list[BaseTool],
        task_context: dict[str, Any],
    ) -> tuple[BaseTool | None, object]:
        """Select the best TTS provider using scored ranking."""
        from lib.scoring import rank_providers

        from tools.provider_routing import filter_explicit_route

        candidates = filter_explicit_route(inputs, candidates)
        preferred = inputs.get("preferred_provider", "auto")
        allowed = set(inputs.get("allowed_providers") or [])
        if allowed:
            candidates = [tool for tool in candidates if tool.provider in allowed]

        language = resolve_tts_language(inputs)
        if language == "fa":
            candidates = [t for t in candidates if t.name in PERSIAN_TTS_PRIORITY]

        rankings = rank_providers(candidates, task_context)

        tool_by_name: dict[str, BaseTool] = {}
        for tool in candidates:
            if (
                tool.name not in tool_by_name
                and tool.get_status() == ToolStatus.AVAILABLE
            ):
                tool_by_name[tool.name] = tool

        if language == "fa" and preferred == "auto":
            # Generic scores do not know Persian quality; use the known order.
            score_by_name = {s.tool_name: s for s in rankings}
            for name in PERSIAN_TTS_PRIORITY:
                if name in tool_by_name:
                    return tool_by_name[name], score_by_name.get(name)
            return None, None

        if preferred != "auto":
            for score_item in rankings:
                if (
                    score_item.provider == preferred
                    and score_item.tool_name in tool_by_name
                ):
                    return tool_by_name[score_item.tool_name], score_item

        for score_item in rankings:
            if score_item.tool_name in tool_by_name:
                return tool_by_name[score_item.tool_name], score_item

        return None, None

    def _prepare_task_context(self, inputs: dict[str, Any]) -> dict[str, Any]:
        from lib.scoring import normalize_task_context

        return normalize_task_context(
            inputs.get("task_context", {}),
            prompt=inputs.get("text", ""),
            capability=self.capability,
            operation=inputs.get("operation", "generate"),
        )

    @staticmethod
    def _tool_context_payload(tool: BaseTool) -> dict[str, Any]:
        info = tool.get_info()
        return {
            "selected_tool_agent_skills": info.get("agent_skills", []),
            "required_agent_skills": info.get("agent_skills", []),
            "selected_tool_usage_location": info.get("usage_location"),
            "selected_tool_best_for": info.get("best_for", []),
        }

    def _serialize_rankings(
        self, candidates: list[BaseTool], rankings: list[object]
    ) -> list[dict[str, Any]]:
        tool_by_name = {tool.name: tool for tool in candidates}
        serialized: list[dict[str, Any]] = []
        for score in rankings:
            item = score.to_dict()
            tool = tool_by_name.get(score.tool_name)
            if tool:
                info = tool.get_info()
                item["agent_skills"] = info.get("agent_skills", [])
                item["usage_location"] = info.get("usage_location")
                item["best_for"] = info.get("best_for", [])
                item["status"] = str(tool.get_status())
            serialized.append(item)
        return serialized
