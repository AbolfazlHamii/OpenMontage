"""Speech-to-text through AvalAI's OpenAI-compatible transcription endpoint.

WhisperX (transcriber) is not installed on the owner's laptop and Google is
blocked from Iran, so the Persian round-trip check (voice audition, dub QA)
transcribes through AvalAI instead. AvalAI serves OpenAI, ElevenLabs and Groq
transcription models on /v1/audio/transcriptions.
"""

from __future__ import annotations

import json
import os
import wave
from pathlib import Path

from tools.audio._speech_api import SpeechAPI
from tools.base_tool import ToolResult

# USD per second of input audio, from AvalAI's live catalog
# (https://api.avalai.ir/public/models, read 2026-11-04).
PRICE_PER_SECOND = {
    "gpt-4o-transcribe": 0.0001,
    "gpt-4o-mini-transcribe": 0.00005,
    "whisper-1": 0.0001,
    "scribe_v2": 0.000062,
    "groq.whisper-large-v3": 0.000031,
    "groq.whisper-large-v3-turbo": 0.00001111,
}
DEFAULT_MODEL = "gpt-4o-mini-transcribe"


def audio_seconds(path: Path) -> float | None:
    if path.suffix.lower() == ".wav":
        try:
            with wave.open(str(path), "rb") as w:
                return w.getnframes() / float(w.getframerate())
        except (wave.Error, EOFError):
            return None
    return None


class AvalAISTT(SpeechAPI):
    name = "avalai_stt"
    capability = "analysis"
    capabilities = ["speech_to_text"]
    provider = "avalai"
    credential = "AVALAI_API_KEY"
    dependencies = ["env:AVALAI_API_KEY"]
    install_instructions = (
        "Set AVALAI_API_KEY (AvalAI console). AVALAI_BASE_URL overrides "
        "https://api.avalai.ir."
    )
    best_for = [
        "Persian transcription from Iran without WhisperX or Google",
        "round-trip pronunciation checks on TTS samples",
    ]
    side_effects = ["calls a paid transcription API", "writes a transcript JSON"]
    input_schema = {
        "type": "object",
        "required": ["audio_path"],
        "properties": {
            "audio_path": {"type": "string"},
            "output_path": {"type": "string"},
            "model": {"enum": sorted(PRICE_PER_SECOND), "default": DEFAULT_MODEL},
            "language": {"type": "string", "default": "fa"},
            "prompt": {
                "type": "string",
                "description": "Spelling hints (names, terms) passed to the model.",
            },
        },
    }

    def estimate_cost(self, inputs):
        seconds = audio_seconds(Path(inputs["audio_path"]))
        if seconds is None:
            return super().estimate_cost(inputs)
        return round(seconds * PRICE_PER_SECOND[inputs.get("model", DEFAULT_MODEL)], 6)

    def generate(self, inputs, key):
        import requests

        model = inputs.get("model", DEFAULT_MODEL)
        path = Path(inputs["audio_path"])
        data = {"model": model, "response_format": "json"}
        if inputs.get("language", "fa"):
            data["language"] = inputs.get("language", "fa")
        if inputs.get("prompt"):
            data["prompt"] = inputs["prompt"]
        base_url = os.environ.get("AVALAI_BASE_URL", "https://api.avalai.ir")
        with path.open("rb") as audio:
            response = requests.post(
                f"{base_url.rstrip('/')}/v1/audio/transcriptions",
                headers={"Authorization": f"Bearer {key}"},
                data=data,
                files={"file": (path.name, audio)},
                timeout=120,
            )
        if response.status_code != 200:
            raise ValueError(
                f"AvalAI returned HTTP {response.status_code}: {response.text[:300]}"
            )
        body = response.json()
        if "text" not in body:
            raise ValueError("Transcription response has no text")

        seconds = audio_seconds(path)
        cost = round(seconds * PRICE_PER_SECOND[model], 6) if seconds else None
        out = Path(inputs.get("output_path") or path.with_suffix(".transcript.json"))
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text(json.dumps(body, ensure_ascii=False, indent=2), encoding="utf-8")
        return ToolResult(
            success=True,
            data={
                "text": body["text"],
                "provider": self.provider,
                "model": model,
                "output": str(out),
                "audio_seconds": seconds,
                "cost_status": "estimated" if cost is not None else "unquoted",
            },
            artifacts=[str(out)],
            model=model,
            cost_usd=cost,
        )
