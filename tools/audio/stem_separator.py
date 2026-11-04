"""Split a soundtrack into vocals and accompaniment with Demucs.

A dub has to replace the voice and keep everything else. Without stems the
Persian voice either sits on top of the English one or the music and effects
are lost. Demucs htdemucs in two-stem mode gives vocals.wav (the original
voice, also used as the reference clip for voice actors) and
accompaniment.wav (music + effects, the bed the dub is mixed over).

Runs on CPU (about real time for htdemucs on a laptop). Results are cached
by the input file's content, model and settings, so a second pass over the
same video is instant. shifts defaults to 0, which makes the output
deterministic; more shifts trade time for a little quality.
"""

from __future__ import annotations

import hashlib
import importlib.util
import os
import shutil
import subprocess
import sys
import tempfile
import time
from pathlib import Path
from typing import Any

from tools.base_tool import (
    BaseTool,
    Determinism,
    ExecutionMode,
    ResourceProfile,
    ToolResult,
    ToolRuntime,
    ToolStability,
    ToolStatus,
    ToolTier,
)

def stems_cache_dir() -> Path:
    override = os.environ.get("OPENMONTAGE_STEMS_CACHE_DIR")
    if override:
        return Path(override).expanduser()
    return Path.home() / ".openmontage" / "stems_cache"


def file_sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as f:
        for block in iter(lambda: f.read(1 << 20), b""):
            digest.update(block)
    return digest.hexdigest()


class StemSeparator(BaseTool):
    name = "stem_separator"
    version = "0.1.0"
    tier = ToolTier.CORE
    capability = "audio_processing"
    provider = "demucs"
    runtime = ToolRuntime.LOCAL
    stability = ToolStability.EXPERIMENTAL
    execution_mode = ExecutionMode.SYNC
    determinism = Determinism.DETERMINISTIC

    dependencies = ["python:demucs", "cmd:ffmpeg"]
    install_instructions = (
        "pip install demucs==4.1.0 (needs torch; no torchaudio). The htdemucs "
        "weights download from Hugging Face on first use."
    )
    agent_skills = ["ffmpeg"]
    capabilities = ["stem_separation", "vocal_isolation"]
    best_for = [
        "removing the original voice before a dub while keeping music and effects",
        "isolating the source voice as a reference for voice actors",
    ]
    resource_profile = ResourceProfile(cpu_cores=4, ram_mb=4096, vram_mb=0, disk_mb=1000)
    side_effects = ["writes vocals.wav and accompaniment.wav", "fills the stems cache"]
    user_visible_verification = ["Listen to accompaniment.wav for leftover voice"]
    idempotency_key_fields = ["input_path", "model", "two_stems", "shifts"]

    input_schema = {
        "type": "object",
        "required": ["input_path"],
        "properties": {
            "input_path": {"type": "string", "description": "Video or audio file"},
            "output_dir": {"type": "string", "description": "Defaults to <stem>_stems next to the input"},
            "model": {"type": "string", "default": "htdemucs"},
            "two_stems": {"type": "string", "default": "vocals"},
            "device": {"type": "string", "enum": ["cpu", "cuda", "mps"], "default": "cpu"},
            "shifts": {"type": "integer", "minimum": 0, "maximum": 10, "default": 0},
            "use_cache": {"type": "boolean", "default": True},
        },
    }

    def get_status(self) -> ToolStatus:
        if importlib.util.find_spec("demucs") is None or shutil.which("ffmpeg") is None:
            return ToolStatus.UNAVAILABLE
        return ToolStatus.AVAILABLE

    def estimate_cost(self, inputs: dict[str, Any]) -> float:
        return 0.0

    def cache_key_for(self, path: Path, inputs: dict[str, Any]) -> str:
        parts = [file_sha256(path), inputs.get("model", "htdemucs"),
                 inputs.get("two_stems", "vocals"), str(inputs.get("shifts", 0)), self.version]
        return hashlib.sha256("|".join(parts).encode()).hexdigest()[:32]

    def _to_wav(self, src: Path, work: Path) -> Path:
        wav = work / "source.wav"
        self.run_command(["ffmpeg", "-y", "-hide_banner", "-loglevel", "error", "-i", str(src),
                          "-vn", "-ac", "2", "-ar", "44100", "-c:a", "pcm_s16le", str(wav)],
                         timeout=900)
        return wav

    def _run_demucs(self, wav: Path, work: Path, inputs: dict[str, Any]) -> tuple[Path, Path]:
        model = inputs.get("model", "htdemucs")
        stem = inputs.get("two_stems", "vocals")
        cmd = [sys.executable, "-m", "demucs", "--two-stems", stem, "-n", model,
               "-d", inputs.get("device", "cpu"), "--shifts", str(inputs.get("shifts", 0)),
               "-o", str(work / "out"), str(wav)]
        proc = subprocess.run(cmd, capture_output=True, text=True, encoding="utf-8",
                              errors="replace", timeout=3600)
        if proc.returncode != 0:
            raise RuntimeError("demucs failed: " + (proc.stderr or proc.stdout)[-600:])
        folder = work / "out" / model / wav.stem
        return folder / f"{stem}.wav", folder / f"no_{stem}.wav"

    def execute(self, inputs: dict[str, Any]) -> ToolResult:
        started = time.time()
        src = Path(inputs["input_path"])
        if not src.is_file():
            return ToolResult(success=False, error=f"Input not found: {src}")
        out_dir = Path(inputs.get("output_dir") or src.with_name(src.stem + "_stems"))
        stem = inputs.get("two_stems", "vocals")
        targets = {stem: out_dir / f"{stem}.wav", "accompaniment": out_dir / "accompaniment.wav"}

        key = self.cache_key_for(src, inputs)
        cached = stems_cache_dir() / key
        from_cache = inputs.get("use_cache", True) and all(
            (cached / p.name).is_file() for p in targets.values())
        try:
            if not from_cache:
                with tempfile.TemporaryDirectory(prefix="om-stems-") as tmp:
                    work = Path(tmp)
                    # Always re-encode: video input, and WAVs in odd formats.
                    voice, rest = self._run_demucs(self._to_wav(src, work), work, inputs)
                    cached.mkdir(parents=True, exist_ok=True)
                    shutil.copyfile(voice, cached / targets[stem].name)
                    shutil.copyfile(rest, cached / "accompaniment.wav")
            out_dir.mkdir(parents=True, exist_ok=True)
            for path in targets.values():
                shutil.copyfile(cached / path.name, path)
        except Exception as exc:
            return ToolResult(success=False, error=f"stem_separator: {type(exc).__name__}: {exc}")

        return ToolResult(
            success=True,
            data={
                stem: str(targets[stem]),
                "accompaniment": str(targets["accompaniment"]),
                "model": inputs.get("model", "htdemucs"),
                "cache_key": key,
                "cached": bool(from_cache),
            },
            artifacts=[str(p) for p in targets.values()],
            cost_usd=0.0,
            duration_seconds=round(time.time() - started, 2),
            from_cache=bool(from_cache),
        )
