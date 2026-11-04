"""Gemini 3.8 TTS through AvalAI's native Gemini endpoint.

Same models, voices and style control as gemini_tts, reachable from Iran
without a Google account. AvalAI serves the 3.8 TTS models on
generateContent (/v1beta/models/{model}:generateContent), not on the
Interactions API that gemini_tts uses, so the request is rebuilt here.
"""

from __future__ import annotations

import base64
import datetime
import os
import wave
from pathlib import Path

from tools.audio.gemini_tts import GeminiTTS
from tools.base_tool import ToolResult, ToolStatus

# USD per 1M tokens (text input, audio output), from AvalAI's announcement of
# the 3.8 TTS models (2026-09-30). The promotional rate ends 2026-12-31.
PROMO_PRICES = {
    "gemini-3.8-flash-tts": (0.50, 9.00),
    "gemini-3.8-flash-lite-tts": (0.50, 6.00),
}
STANDARD_PRICES = {
    "gemini-3.8-flash-tts": (1.00, 18.00),
    "gemini-3.8-flash-lite-tts": (1.00, 12.00),
}
PROMO_ENDS = datetime.date(2026, 12, 31)


class AvalAIGeminiTTS(GeminiTTS):
    name = "avalai_gemini_tts"
    provider = "avalai"
    install_instructions = (
        "Set AVALAI_API_KEY (AvalAI console). AVALAI_BASE_URL overrides "
        "https://api.avalai.ir."
    )
    best_for = [
        "Gemini 3.8 voices and style control when Google's API is not reachable"
    ]

    def get_status(self):
        if os.environ.get("AVALAI_API_KEY"):
            return ToolStatus.AVAILABLE
        return ToolStatus.UNAVAILABLE

    def build_request(self, inputs):
        # Reuse gemini_tts validation (schema, at most 2 speakers, unique names).
        super().build_request(inputs)

        if inputs.get("turns"):
            turns = inputs["turns"]
            speech_config = {
                "multiSpeakerVoiceConfig": {
                    "speakerVoiceConfigs": [
                        {
                            "speaker": s["speaker"],
                            "voiceConfig": {
                                "prebuiltVoiceConfig": {"voiceName": s["voice"]}
                            },
                        }
                        for s in inputs["speakers"]
                    ]
                }
            }
        else:
            turns = [{"text": inputs["text"], "style": inputs.get("style", "")}]
            speech_config = {
                "voiceConfig": {
                    "prebuiltVoiceConfig": {
                        "voiceName": inputs.get("voice_id", "Kore")
                    }
                }
            }

        parts = []
        for turn in turns:
            part = {"text": turn["text"]}
            metadata = {k: turn[k] for k in ("speaker", "style") if turn.get(k)}
            if metadata:
                part["speechMetadata"] = metadata
            parts.append(part)

        return {
            "model": inputs.get("model_id", "gemini-3.8-flash-tts"),
            "body": {
                "contents": [{"role": "user", "parts": parts}],
                "generationConfig": {
                    "responseModalities": ["AUDIO"],
                    "speechConfig": speech_config,
                },
            },
        }

    def execute(self, inputs):
        try:
            if inputs.get("operation") == "list_voices":
                raise ValueError("AvalAI does not expose the Gemini voice library")
            key = os.environ.get("AVALAI_API_KEY")
            if not key:
                raise ValueError("No AvalAI API key. " + self.install_instructions)
            path = Path(inputs.get("output_path", "gemini_tts.wav"))
            if path.suffix.lower() != ".wav":
                raise ValueError(
                    "This adapter writes WAV; output_path must end in .wav"
                )
            request = self.build_request(inputs)

            import requests

            base_url = os.environ.get("AVALAI_BASE_URL", "https://api.avalai.ir")
            response = requests.post(
                f"{base_url.rstrip('/')}/v1beta/models/{request['model']}:generateContent",
                headers={"Authorization": f"Bearer {key}"},
                json=request["body"],
                timeout=300,
            )
            if response.status_code != 200:
                raise ValueError(
                    f"AvalAI returned HTTP {response.status_code}: {response.text[:300]}"
                )
            payload = response.json()
            audio = next(
                (
                    part["inlineData"]
                    for candidate in payload.get("candidates", [])
                    for part in candidate.get("content", {}).get("parts", [])
                    if part.get("inlineData", {}).get("data")
                ),
                None,
            )
            if not audio:
                raise ValueError("AvalAI returned no audio")

            data = base64.b64decode(audio["data"])
            mime = audio.get("mimeType", "").split(";")[0].strip().lower()
            path.parent.mkdir(parents=True, exist_ok=True)
            if mime in ("audio/wav", "audio/x-wav", "audio/wave"):
                path.write_bytes(data)
            elif mime in ("audio/l16", "audio/pcm"):
                # Raw 16-bit PCM, 24 kHz mono unless the MIME type says otherwise.
                rate = self._mime_param(audio.get("mimeType", ""), "rate", 24000)
                with wave.open(str(path), "wb") as out:
                    out.setnchannels(1)
                    out.setsampwidth(2)
                    out.setframerate(rate)
                    out.writeframes(data)
            else:
                raise ValueError(f"Unexpected audio type from AvalAI: {mime or '?'}")

            cost = self._cost(request["model"], payload.get("usageMetadata", {}))
            return ToolResult(
                success=True,
                data={
                    "provider": self.provider,
                    "model": request["model"],
                    "output": str(path),
                    "format": "wav",
                    "audio_duration_seconds": self._wav_duration(path),
                    "cost_status": "estimated" if cost is not None else "unquoted",
                },
                artifacts=[str(path)],
                cost_usd=cost,
                model=request["model"],
            )
        except Exception as exc:
            return ToolResult(success=False, error=str(exc))

    @staticmethod
    def _mime_param(mime: str, name: str, default: int) -> int:
        for param in mime.split(";")[1:]:
            key, _, value = param.strip().partition("=")
            if key == name and value.isdigit():
                return int(value)
        return default

    @staticmethod
    def _cost(model: str, usage: dict, today: datetime.date | None = None) -> float | None:
        today = today or datetime.date.today()
        prices = (PROMO_PRICES if today <= PROMO_ENDS else STANDARD_PRICES).get(model)
        if not prices or "candidatesTokenCount" not in usage:
            return None
        input_price, output_price = prices
        return round(
            (usage.get("promptTokenCount", 0) * input_price
             + usage["candidatesTokenCount"] * output_price) / 1_000_000,
            6,
        )
