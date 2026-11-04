"""Two-pass EBU R128 loudness normalization for finished renders.

audio_mixer normalizes the mixes it builds, but a HyperFrames or Remotion
render mixes its own audio, so the delivered file can land anywhere (the
Samsung sample came out at -11.5 LUFS). This tool measures the file, then
applies loudnorm in linear mode with the measured values so speech dynamics
are kept, and copies the video stream untouched.

Defaults are the YouTube target the Persian channel uses: -14 LUFS,
true peak -1 dBTP.
"""

from __future__ import annotations

import json
import re
import time
from pathlib import Path
from typing import Any

from tools.base_tool import (
    BaseTool,
    Determinism,
    ExecutionMode,
    ResourceProfile,
    ToolResult,
    ToolStability,
    ToolTier,
)

VIDEO_SUFFIXES = {".mp4", ".mkv", ".mov", ".webm", ".m4v"}
AUDIO_CODECS = {
    ".wav": ["-c:a", "pcm_s16le"],
    ".mp3": ["-c:a", "libmp3lame", "-b:a", "192k"],
    ".m4a": ["-c:a", "aac", "-b:a", "192k"],
    ".flac": ["-c:a", "flac"],
}


def parse_loudnorm_json(stderr: str) -> dict[str, float]:
    """Pull the JSON block loudnorm prints at the end of a measuring pass."""
    matches = re.findall(r"\{[^{}]*\"input_i\"[^{}]*\}", stderr, re.S)
    if not matches:
        raise ValueError("loudnorm printed no measurement")
    raw = json.loads(matches[-1])
    return {k: float(v) for k, v in raw.items() if k != "normalization_type"}


class LoudnessNormalize(BaseTool):
    name = "loudness_normalize"
    version = "0.1.0"
    tier = ToolTier.CORE
    capability = "audio_processing"
    provider = "ffmpeg"
    stability = ToolStability.EXPERIMENTAL
    execution_mode = ExecutionMode.SYNC
    determinism = Determinism.DETERMINISTIC

    dependencies = ["cmd:ffmpeg"]
    install_instructions = "Install FFmpeg: https://ffmpeg.org/download.html"
    agent_skills = ["ffmpeg"]

    capabilities = ["loudness_measurement", "loudness_normalization"]
    best_for = [
        "bringing a finished render to a platform loudness target",
        "measuring integrated loudness and true peak of a deliverable",
    ]

    input_schema = {
        "type": "object",
        "required": ["input_path"],
        "properties": {
            "operation": {
                "type": "string",
                "enum": ["normalize", "measure"],
                "default": "normalize",
            },
            "input_path": {"type": "string"},
            "output_path": {
                "type": "string",
                "description": "Defaults to <stem>_loudnorm<suffix> next to the input.",
            },
            "target_lufs": {"type": "number", "default": -14.0},
            "true_peak": {"type": "number", "default": -1.0},
            "lra": {"type": "number", "default": 11.0},
        },
    }

    resource_profile = ResourceProfile(cpu_cores=1, ram_mb=256, vram_mb=0, disk_mb=500)
    idempotency_key_fields = ["input_path", "operation", "target_lufs", "true_peak", "lra"]
    side_effects = ["writes a normalized copy to output_path (normalize only)"]
    user_visible_verification = ["Listen for pumping or clipping after normalization"]

    def measure(self, path: Path, target: float, tp: float, lra: float) -> dict[str, float]:
        cmd = [
            "ffmpeg", "-hide_banner", "-nostats", "-i", str(path), "-vn",
            "-af", f"loudnorm=I={target}:TP={tp}:LRA={lra}:print_format=json",
            "-f", "null", "-",
        ]
        proc = self.run_command(cmd, timeout=600)
        return parse_loudnorm_json(proc.stderr or "")

    @staticmethod
    def second_pass_filter(m: dict[str, float], target: float, tp: float, lra: float) -> str:
        return (
            f"loudnorm=I={target}:TP={tp}:LRA={lra}"
            f":measured_I={m['input_i']}:measured_TP={m['input_tp']}"
            f":measured_LRA={m['input_lra']}:measured_thresh={m['input_thresh']}"
            f":offset={m['target_offset']}:linear=true:print_format=json"
            # loudnorm resamples to 192 kHz internally.
            ",aresample=48000"
        )

    def execute(self, inputs: dict[str, Any]) -> ToolResult:
        src = Path(inputs["input_path"])
        if not src.exists():
            return ToolResult(success=False, error=f"Input not found: {src}")
        target = float(inputs.get("target_lufs", -14.0))
        tp = float(inputs.get("true_peak", -1.0))
        lra = float(inputs.get("lra", 11.0))
        start = time.time()

        try:
            before = self.measure(src, target, tp, lra)
        except Exception as e:
            return ToolResult(success=False, error=f"Loudness measurement failed: {e}")

        summary = {
            "integrated_lufs": before["input_i"],
            "true_peak_dbtp": before["input_tp"],
            "lra": before["input_lra"],
        }
        if inputs.get("operation", "normalize") == "measure":
            return ToolResult(
                success=True,
                data={"input": str(src), "before": summary},
                duration_seconds=round(time.time() - start, 2),
            )

        out = Path(inputs.get("output_path") or src.with_stem(f"{src.stem}_loudnorm"))
        if out.resolve() == src.resolve():
            return ToolResult(success=False, error="output_path must differ from input_path")
        out.parent.mkdir(parents=True, exist_ok=True)

        af = self.second_pass_filter(before, target, tp, lra)
        is_video = src.suffix.lower() in VIDEO_SUFFIXES
        # For video, normalize to a WAV first and mux it back. Filtering and
        # copying the video in one ffmpeg call left a +3.6 dB transient in the
        # Samsung render (true peak -1.6 instead of -5.2) with ffmpeg 8.1.
        wav = out.with_name(f".{out.stem}_loudnorm_tmp.wav")
        if is_video:
            cmds = [
                ["ffmpeg", "-y", "-hide_banner", "-nostats", "-i", str(src), "-vn",
                 "-af", af, "-c:a", "pcm_s16le", str(wav)],
                ["ffmpeg", "-y", "-hide_banner", "-nostats", "-i", str(src), "-i", str(wav),
                 "-map", "0:v", "-map", "1:a", "-c:v", "copy",
                 "-c:a", "aac", "-b:a", "192k", str(out)],
            ]
        else:
            codec = AUDIO_CODECS.get(out.suffix.lower(), ["-c:a", "aac", "-b:a", "192k"])
            cmds = [["ffmpeg", "-y", "-hide_banner", "-nostats", "-i", str(src),
                     "-af", af, *codec, str(out)]]
        try:
            for cmd in cmds:
                self.run_command(cmd, timeout=1200)
            after = self.measure(out, target, tp, lra)
        except Exception as e:
            return ToolResult(success=False, error=f"FFmpeg loudnorm failed: {e}")
        finally:
            wav.unlink(missing_ok=True)

        return ToolResult(
            success=True,
            data={
                "input": str(src),
                "output": str(out),
                "target": {"integrated_lufs": target, "true_peak_dbtp": tp, "lra": lra},
                "before": summary,
                "after": {
                    "integrated_lufs": after["input_i"],
                    "true_peak_dbtp": after["input_tp"],
                    "lra": after["input_lra"],
                },
            },
            artifacts=[str(out)],
            duration_seconds=round(time.time() - start, 2),
        )
