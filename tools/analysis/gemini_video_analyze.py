"""Watch a reference video with Gemini and return a structured breakdown.

video_analyzer gives exact cut times and keyframes but leaves the
interpretation (story beats, why the hook works, who speaks with what
energy) to the agent's eyes on 20 frames. Gemini watches the whole video,
sound included, so this tool returns that interpretation as JSON: story
beats, a hook analysis of the first 15 seconds, shot length, visual style,
on-screen text, and per-segment speaker and energy for dubs.

A public YouTube URL is passed as file_data.file_uri, so nothing is
downloaded. Local files go inline (up to 20 MB) or through the Files API.

Routes, in order for `route: "auto"`: Google (GOOGLE_API_KEY / Vertex),
then the same request on AvalAI's native Gemini endpoint (AVALAI_API_KEY;
Google refuses Iranian IPs), then the local video_analyzer when
`fallback_local` is true. `fallback_from` lists what failed.
"""

from __future__ import annotations

import base64
import json
import mimetypes
import os
import re
import time
from pathlib import Path
from typing import Any

from tools.base_tool import (
    BaseTool,
    Determinism,
    ExecutionMode,
    ResourceProfile,
    RetryPolicy,
    ToolResult,
    ToolRuntime,
    ToolStability,
    ToolStatus,
    ToolTier,
)

DEFAULT_MODEL = "gemini-3.8-flash"
# USD per 1M tokens (input, output) from AvalAI's live catalog, 2026-11-04.
# Google's own list price for these models is not verified from here
# (ai.google.dev answers 403 from Iran); the same numbers are used for both.
PRICES = {
    "gemini-3.8-flash": (0.75, 3.75),
    "gemini-3.5-flash-lite": (0.30, 2.50),
    "gemini-3.1-pro-preview": (2.00, 12.00),
}
# Gemini video tokens per second: frames at 1 fps (66 tokens at low media
# resolution, 258 at default) plus 32 tokens of audio.
TOKENS_PER_SECOND = {"low": 66 + 32, "default": 258 + 32}
OUTPUT_TOKENS_ESTIMATE = 3000
# Gemini caps a request at 20 MB and base64 adds a third, so files over
# ~14 MB are sent as a 360p proxy (the analysis runs at low resolution
# anyway) or, on the Google route, through the Files API.
INLINE_LIMIT_BYTES = 14 * 1024 * 1024
# The prompt alone is ~450 tokens. An answer whose prompt count is not well
# above that was written without the video (AvalAI does this for YouTube
# links: 434 prompt tokens and an invented analysis, 2026-11-04).
PROMPT_ONLY_TOKENS = 600
URL_RE = re.compile(r"^https?://", re.I)
YOUTUBE_RE = re.compile(r"^https?://(www\.|m\.)?(youtube\.com|youtu\.be)/", re.I)

REQUIRED_KEYS = {
    "duration_seconds", "story_beats", "hook", "average_shot_length_seconds",
    "visual_style", "on_screen_text", "segments",
}

PROMPT = """Watch this video (picture and sound) and describe how it is made.
Answer with one JSON object and nothing else, with exactly these keys:

{
  "duration_seconds": number,
  "story_beats": [{"time": "MM:SS", "beat": "what happens and why it matters"}],
  "hook": {
    "summary": "what the first 15 seconds show and say",
    "technique": "the hook device (big number, paradox, question, cold open...)",
    "why_it_works": "one or two sentences",
    "first_line": "the first spoken sentence, verbatim"
  },
  "average_shot_length_seconds": number,
  "cuts_per_minute": number,
  "visual_style": {
    "medium": "e.g. 2D cartoon stills with camera moves, live action, 3D",
    "palette": "main colours and how they change",
    "camera": "typical movement on each shot",
    "typography": "on-screen text style",
    "transitions": "most used transitions"
  },
  "on_screen_text": [{"time": "MM:SS", "text": "verbatim"}],
  "segments": [{
    "start": "MM:SS", "end": "MM:SS",
    "speaker": "narrator / speaker_1 / a name if said",
    "emotion": "e.g. excited, ironic, calm, tense",
    "energy": "low | medium | high",
    "summary": "what is said"
  }],
  "music_and_sound": "music style, where it changes, notable sound effects"
}

Times are MM:SS from the start of the part you were given. Segments cover the
whole runtime in order, one per speaker turn or change of energy. Keep text
in the video's own language."""


def parse_offset(value: Any) -> float | None:
    """Seconds from 90, "90", "90s", "1:30" or "01:02:03"."""
    if value is None or value == "":
        return None
    if isinstance(value, (int, float)):
        return float(value)
    text = str(value).strip().rstrip("s")
    if ":" in text:
        seconds = 0.0
        for part in text.split(":"):
            seconds = seconds * 60 + float(part)
        return seconds
    return float(text)


def parse_json_answer(text: str) -> dict[str, Any]:
    """The model's JSON, tolerating a code fence or prose around it."""
    text = (text or "").strip()
    fenced = re.search(r"```(?:json)?\s*(\{.*\})\s*```", text, re.S)
    if fenced:
        text = fenced.group(1)
    elif not text.startswith("{"):
        start, end = text.find("{"), text.rfind("}")
        if start == -1 or end <= start:
            raise ValueError("model answer has no JSON object")
        text = text[start:end + 1]
    data = json.loads(text)
    if not isinstance(data, dict):
        raise ValueError("model answer is not a JSON object")
    missing = REQUIRED_KEYS - set(data)
    if missing:
        raise ValueError("model answer is missing: " + ", ".join(sorted(missing)))
    return data


def _camel(key: str) -> str:
    head, *rest = key.split("_")
    return head + "".join(word.title() for word in rest)


def to_rest(value: Any) -> Any:
    """SDK-style snake_case request -> REST camelCase (enum values untouched)."""
    if isinstance(value, dict):
        return {_camel(k): to_rest(v) for k, v in value.items()}
    if isinstance(value, list):
        return [to_rest(v) for v in value]
    return value


class GeminiVideoAnalyze(BaseTool):
    name = "gemini_video_analyze"
    version = "0.1.0"
    tier = ToolTier.ANALYZE
    capability = "analysis"
    provider = "gemini"
    runtime = ToolRuntime.API
    stability = ToolStability.EXPERIMENTAL
    execution_mode = ExecutionMode.SYNC
    determinism = Determinism.STOCHASTIC
    retry_policy = RetryPolicy(max_retries=0)
    agent_skills = ["provider-model-refresh"]
    dependencies = []
    install_instructions = (
        "Set GOOGLE_API_KEY (Gemini API) or AVALAI_API_KEY (same models via "
        "AvalAI). Without either, fallback_local runs video_analyzer."
    )
    capabilities = ["video_understanding", "reference_analysis", "speaker_energy"]
    best_for = [
        "story beats, hook and pacing of a reference video without downloading it",
        "per-segment speaker and energy for a dub",
    ]
    resource_profile = ResourceProfile(network_required=True)
    side_effects = ["calls a paid multimodal API", "writes the analysis JSON"]
    user_visible_verification = ["Spot-check two story-beat times against the video"]
    idempotency_key_fields = ["source", "start_offset", "end_offset", "fps",
                              "media_resolution", "model"]

    input_schema = {
        "type": "object",
        "required": ["source"],
        "properties": {
            "source": {"type": "string", "description": "Public YouTube URL or local video path"},
            "start_offset": {"type": ["number", "string"], "description": "Seconds or MM:SS"},
            "end_offset": {"type": ["number", "string"], "description": "Seconds or MM:SS"},
            "fps": {"type": "number", "minimum": 0.1, "maximum": 24},
            "media_resolution": {"type": "string", "enum": ["low", "default"], "default": "low"},
            "model": {"type": "string", "default": DEFAULT_MODEL},
            "route": {"type": "string", "enum": ["auto", "google", "avalai"], "default": "auto"},
            "fallback_local": {"type": "boolean", "default": True},
            "duration_hint_seconds": {
                "type": "number",
                "description": "Video length for the cost estimate when no offsets are given.",
            },
            "output_path": {"type": "string"},
        },
    }

    def get_status(self) -> ToolStatus:
        from tools.google_credentials import has_google_credentials

        if has_google_credentials() or os.environ.get("AVALAI_API_KEY"):
            return ToolStatus.AVAILABLE
        return ToolStatus.UNAVAILABLE

    # -- cost ---------------------------------------------------------------

    @staticmethod
    def analysed_seconds(inputs: dict[str, Any]) -> float | None:
        start = parse_offset(inputs.get("start_offset")) or 0.0
        end = parse_offset(inputs.get("end_offset"))
        if end is not None:
            return max(0.0, end - start)
        hint = inputs.get("duration_hint_seconds")
        return max(0.0, float(hint) - start) if hint else None

    def estimate_cost(self, inputs: dict[str, Any]) -> float:
        seconds = self.analysed_seconds(inputs) or 600.0
        model = inputs.get("model", DEFAULT_MODEL)
        input_price, output_price = PRICES.get(model, PRICES[DEFAULT_MODEL])
        tokens = seconds * TOKENS_PER_SECOND[inputs.get("media_resolution", "low")]
        fps = float(inputs.get("fps") or 1.0)
        tokens *= max(1.0, fps)  # frames scale with fps; audio does not, close enough
        return round((tokens * input_price + OUTPUT_TOKENS_ESTIMATE * output_price) / 1e6, 4)

    @staticmethod
    def usage_cost(model: str, prompt_tokens: int, output_tokens: int) -> float | None:
        prices = PRICES.get(model)
        if not prices:
            return None
        return round((prompt_tokens * prices[0] + output_tokens * prices[1]) / 1e6, 6)

    # -- request ------------------------------------------------------------

    def build_request(self, inputs: dict[str, Any]) -> dict[str, Any]:
        source = inputs["source"]
        part: dict[str, Any]
        if URL_RE.match(source):
            if not YOUTUBE_RE.match(source):
                raise ValueError("Only public YouTube URLs can be passed by link; "
                                 "download other videos and pass the file.")
            part = {"file_data": {"file_uri": source, "mime_type": "video/*"}}
        else:
            path = Path(source)
            if not path.is_file():
                raise ValueError(f"video not found: {path}")
            part = {"local_path": str(path)}

        metadata: dict[str, Any] = {}
        start = parse_offset(inputs.get("start_offset"))
        end = parse_offset(inputs.get("end_offset"))
        if start is not None:
            metadata["start_offset"] = f"{start:g}s"
        if end is not None:
            metadata["end_offset"] = f"{end:g}s"
        if inputs.get("fps"):
            metadata["fps"] = float(inputs["fps"])
        if metadata:
            part["video_metadata"] = metadata

        resolution = inputs.get("media_resolution", "low")
        config = {"response_mime_type": "application/json"}
        if resolution == "low":
            config["media_resolution"] = "MEDIA_RESOLUTION_LOW"
        return {
            "model": inputs.get("model", DEFAULT_MODEL),
            "video_part": part,
            "prompt": PROMPT,
            "config": config,
        }

    def _proxy(self, path: Path) -> Path:
        """A 360p, low-bitrate copy small enough to send inline."""
        import tempfile

        out = Path(tempfile.mkdtemp(prefix="om-gva-")) / (path.stem + "_360p.mp4")
        self.run_command([
            "ffmpeg", "-y", "-hide_banner", "-loglevel", "error", "-i", str(path),
            "-vf", "scale=-2:360", "-c:v", "libx264", "-preset", "veryfast", "-crf", "32",
            "-c:a", "aac", "-b:a", "48k", "-ac", "1", str(out),
        ], timeout=900)
        if out.stat().st_size > INLINE_LIMIT_BYTES:
            raise ValueError("video is too long to send inline even at 360p; "
                             "pass start_offset/end_offset or use the Google route")
        return out

    def _inline_part(self, part: dict[str, Any]) -> dict[str, Any]:
        path = Path(part["local_path"])
        if path.stat().st_size > INLINE_LIMIT_BYTES:
            path = self._proxy(path)
        mime = mimetypes.guess_type(path.name)[0] or "video/mp4"
        inline = {"inline_data": {"mime_type": mime,
                                  "data": base64.b64encode(path.read_bytes()).decode()}}
        if "video_metadata" in part:
            inline["video_metadata"] = part["video_metadata"]
        return inline

    # -- routes -------------------------------------------------------------

    def _call_google(self, request: dict[str, Any]) -> tuple[str, int, int]:
        from tools.google_credentials import get_genai_client, has_google_credentials

        if not has_google_credentials():
            raise ValueError("no Google credentials")
        client = get_genai_client()
        part = dict(request["video_part"])
        if "local_path" in part:
            path = Path(part["local_path"])
            if path.stat().st_size > INLINE_LIMIT_BYTES:
                uploaded = client.files.upload(file=str(path))
                for _ in range(60):  # the Files API processes video before use
                    if getattr(getattr(uploaded, "state", None), "name", "ACTIVE") != "PROCESSING":
                        break
                    time.sleep(5)
                    uploaded = client.files.get(name=uploaded.name)
                video = {"file_data": {"file_uri": uploaded.uri, "mime_type": uploaded.mime_type}}
                if "video_metadata" in part:
                    video["video_metadata"] = part["video_metadata"]
                part = video
            else:
                part = self._inline_part(part)
        response = client.models.generate_content(
            model=request["model"],
            contents=[{"role": "user", "parts": [part, {"text": request["prompt"]}]}],
            config=request["config"],
        )
        usage = getattr(response, "usage_metadata", None)
        return (
            response.text,
            int(getattr(usage, "prompt_token_count", 0) or 0),
            int(getattr(usage, "candidates_token_count", 0) or 0),
        )

    def _call_avalai(self, request: dict[str, Any]) -> tuple[str, int, int]:
        import requests

        key = os.environ.get("AVALAI_API_KEY")
        if not key:
            raise ValueError("no AvalAI API key")
        part = request["video_part"]
        if "file_data" in part:
            raise ValueError("AvalAI does not fetch YouTube links (the model answers "
                             "without the video); download it and pass the file")
        if "local_path" in part:
            part = self._inline_part(part)
        body = to_rest({
            "contents": [{"role": "user", "parts": [part, {"text": request["prompt"]}]}],
            "generation_config": request["config"],
        })
        base_url = os.environ.get("AVALAI_BASE_URL", "https://api.avalai.ir")
        response = requests.post(
            f"{base_url.rstrip('/')}/v1beta/models/{request['model']}:generateContent",
            headers={"Authorization": f"Bearer {key}"},
            json=body,
            timeout=300,
        )
        if response.status_code != 200:
            raise ValueError(f"AvalAI returned HTTP {response.status_code}: {response.text[:300]}")
        payload = response.json()
        text = "".join(
            part.get("text", "")
            for candidate in payload.get("candidates", [])
            for part in candidate.get("content", {}).get("parts", [])
        )
        usage = payload.get("usageMetadata", {})
        return text, int(usage.get("promptTokenCount", 0)), int(usage.get("candidatesTokenCount", 0))

    def expected_video_tokens(self, inputs: dict[str, Any]) -> float | None:
        seconds = self.analysed_seconds(inputs)
        if seconds is None and not URL_RE.match(inputs["source"]):
            from tools.analysis.audio_probe import probe_duration

            try:
                seconds = probe_duration(inputs["source"])
            except Exception:
                seconds = None
        if not seconds:
            return None
        fps = max(1.0, float(inputs.get("fps") or 1.0))
        return seconds * TOKENS_PER_SECOND[inputs.get("media_resolution", "low")] * fps

    def check_ingested(self, inputs: dict[str, Any], prompt_tokens: int) -> str:
        """Refuse an answer the model wrote without seeing the video."""
        if not prompt_tokens:
            return "unchecked (no usage reported)"
        expected = self.expected_video_tokens(inputs)
        video_tokens = prompt_tokens - PROMPT_ONLY_TOKENS
        floor = 0.4 * expected if expected else 1000
        if video_tokens < floor:
            raise ValueError(
                f"the model answered without the video ({prompt_tokens} prompt tokens, "
                f"expected about {int(expected or floor) + PROMPT_ONLY_TOKENS}); "
                "the analysis would be invented"
            )
        return "ok"

    def _local_fallback(self, inputs: dict[str, Any], failures: list[dict[str, str]]) -> ToolResult:
        from tools.analysis.video_analyzer import VideoAnalyzer

        local_inputs = {"source": inputs["source"], "analysis_depth": "standard"}
        if inputs.get("output_path"):
            local_inputs["output_dir"] = str(Path(inputs["output_path"]).parent / "local_analysis")
        result = VideoAnalyzer().execute(local_inputs)
        if result.success:
            result.data["fallback_from"] = failures
            result.data["analysis_source"] = "video_analyzer"
            result.data["note"] = (
                "Gemini routes failed; this is the local analysis (cuts, keyframes, "
                "transcript). Story beats, hook and speaker energy are for the agent to read."
            )
        else:
            result.error = ("Gemini routes failed (" + "; ".join(
                f"{f['route']}: {f['error']}" for f in failures) + f"); local: {result.error}")
        return result

    def execute(self, inputs: dict[str, Any]) -> ToolResult:
        from tools.provider_routing import short_error

        started = time.time()
        try:
            request = self.build_request(inputs)
        except ValueError as exc:
            return ToolResult(success=False, error=str(exc))

        route = inputs.get("route", "auto")
        routes = ["google", "avalai"] if route == "auto" else [route]
        failures: list[dict[str, str]] = []
        # Answers refused after they were billed (no video, bad JSON) still cost.
        spent = 0.0
        for name in routes:
            try:
                text, prompt_tokens, output_tokens = (
                    self._call_google(request) if name == "google" else self._call_avalai(request)
                )
            except Exception as exc:  # one route failing moves on to the next
                failures.append({"route": name, "error": short_error(f"{type(exc).__name__}: {exc}")})
                continue
            cost = self.usage_cost(request["model"], prompt_tokens, output_tokens)
            spent += cost or 0.0
            try:
                ingest_check = self.check_ingested(inputs, prompt_tokens)
                analysis = parse_json_answer(text)
            except Exception as exc:
                failures.append({"route": name, "error": short_error(f"{type(exc).__name__}: {exc}")})
                continue

            cost = round(spent, 6) if cost is not None else None
            analysis["_meta"] = {
                "source": inputs["source"],
                "start_offset": inputs.get("start_offset"),
                "end_offset": inputs.get("end_offset"),
                "model": request["model"],
                "route": name,
                "prompt_tokens": prompt_tokens,
                "output_tokens": output_tokens,
                "ingest_check": ingest_check,
            }
            artifacts = []
            if inputs.get("output_path"):
                out = Path(inputs["output_path"])
                out.parent.mkdir(parents=True, exist_ok=True)
                out.write_text(json.dumps(analysis, ensure_ascii=False, indent=2), encoding="utf-8")
                artifacts.append(str(out))
            data = {"analysis": analysis, "route": name, "provider": name,
                    "model": request["model"], "analysis_source": "gemini",
                    "cost_status": "estimated" if cost is not None else "unquoted"}
            if failures:
                data["fallback_from"] = failures
            return ToolResult(success=True, data=data, artifacts=artifacts, cost_usd=cost,
                              model=request["model"], duration_seconds=round(time.time() - started, 2))

        if inputs.get("fallback_local", True):
            result = self._local_fallback(inputs, failures)
            result.cost_usd = round(spent, 6)
            return result
        return ToolResult(success=False, cost_usd=round(spent, 6),
                          error="All Gemini routes failed: " + "; ".join(
                              f"{f['route']}: {f['error']}" for f in failures))
