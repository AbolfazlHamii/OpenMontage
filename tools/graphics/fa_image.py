"""Draft / final image stages with approved pins, for Persian productions.

Images are most of what a production costs (98% of the Samsung sample), and
three habits made them expensive: every look iteration ran at final quality,
an image the owner had already approved could be generated again, and no
seed was ever pinned, so the asset cache could not help.

This tool sits in front of image_selector:

- mode="draft": cheapest Gemini image model at 1K, for iterating on looks.
- mode="final": the production model at 2K, only after the look is agreed.
- operation="approve": copies the chosen file into
  projects/<id>/assets/approved/ under its content hash and records it in
  approved.json. From then on, generating that scene returns the pinned file
  at no cost; it is never sent to a provider again. To change it, the owner
  asks for operation="unapprove" (the file stays on disk).
- A seed derived from scene + prompt is always passed. image_selector drops
  it for providers without a seed input; providers that take one become
  cacheable by lib/asset_cache.
"""

from __future__ import annotations

import datetime
import hashlib
import json
import re
import shutil
from pathlib import Path
from typing import Any, Optional

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

# Prices: config/fa_pricing.yaml (AvalAI catalog). flash-lite 1K is $0.0336,
# half of flash 1K; flash 2K is $0.101.
MODES = {
    "draft": {"model": "gemini-3.1-flash-lite-image", "resolution": "1K"},
    "final": {"model": "gemini-3.1-flash-image", "resolution": "2K"},
}
APPROVED_DIR = Path("assets") / "approved"
MANIFEST = "approved.json"


def stable_seed(scene_id: str, prompt: str) -> int:
    digest = hashlib.sha256(f"{scene_id}\n{prompt}".encode("utf-8")).hexdigest()
    return int(digest[:8], 16) % 2**31


def file_sha256(path: Path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def infer_project_dir(inputs: dict[str, Any]) -> Optional[Path]:
    if inputs.get("project_dir"):
        return Path(inputs["project_dir"])
    for key in ("output_path", "image_path"):
        value = inputs.get(key)
        if not value:
            continue
        parts = Path(value).parts
        if "projects" in parts:
            i = parts.index("projects")
            if i + 1 < len(parts):
                return Path(*parts[: i + 2])
    return None


def _safe_name(scene_id: str) -> str:
    return re.sub(r"[^A-Za-z0-9_.-]+", "_", scene_id).strip("_") or "scene"


class FaImage(BaseTool):
    name = "fa_image"
    version = "0.1.0"
    tier = ToolTier.CORE
    capability = "image_staging"
    provider = "openmontage"
    stability = ToolStability.EXPERIMENTAL
    execution_mode = ExecutionMode.SYNC
    determinism = Determinism.STOCHASTIC
    runtime = ToolRuntime.HYBRID

    install_instructions = "Uses image_selector; needs one configured Gemini image provider."
    agent_skills = ["provider-model-refresh"]
    fallback_tools = ["image_selector"]
    capabilities = ["draft_images", "final_images", "approved_image_pins"]
    best_for = [
        "iterating on a look cheaply before paying for final stills",
        "making sure an approved still is never generated (or paid for) again",
    ]

    input_schema = {
        "type": "object",
        "properties": {
            "operation": {
                "type": "string",
                "enum": ["generate", "batch", "approve", "unapprove", "status"],
                "default": "generate",
            },
            "mode": {"type": "string", "enum": list(MODES), "default": "draft"},
            "scene_id": {"type": "string"},
            "prompt": {"type": "string"},
            "output_path": {"type": "string"},
            "image_path": {"type": "string", "description": "approve: the file to pin"},
            "project_dir": {"type": "string"},
            "aspect_ratio": {"type": "string", "default": "16:9"},
            "model": {"type": "string", "description": "Override the mode's model."},
            "resolution": {"type": "string", "description": "Override the mode's resolution."},
            "seed": {"type": "integer"},
            "preferred_tool": {"type": "string"},
            "items": {
                "type": "array",
                "items": {"type": "object"},
                "description": "batch: generate inputs, one per scene; run in parallel",
            },
            "concurrency": {"type": "integer", "default": 3},
        },
    }
    idempotency_key_fields = ["operation", "mode", "scene_id", "prompt", "aspect_ratio",
                              "model", "resolution", "seed"]
    side_effects = [
        "generate: writes an image to output_path (paid unless the scene is approved)",
        "approve: copies the image into assets/approved/ and updates approved.json",
    ]

    def __init__(self, selector: Optional[BaseTool] = None):
        self._selector = selector

    @property
    def selector(self) -> BaseTool:
        if self._selector is None:
            from tools.graphics.image_selector import ImageSelector
            self._selector = ImageSelector()
        return self._selector

    def get_status(self) -> ToolStatus:
        return self.selector.get_status()

    def estimate_cost(self, inputs: dict[str, Any]) -> float:
        if inputs.get("operation", "generate") != "generate":
            return 0.0
        project = infer_project_dir(inputs)
        if project and inputs.get("scene_id") and self._pin(project, inputs["scene_id"]):
            return 0.0
        return self.selector.estimate_cost(self._request(inputs))

    # -- approved pins -------------------------------------------------

    @staticmethod
    def _manifest_path(project: Path) -> Path:
        return project / APPROVED_DIR / MANIFEST

    def _load(self, project: Path) -> dict[str, Any]:
        path = self._manifest_path(project)
        if not path.exists():
            return {"version": 1, "scenes": {}, "history": []}
        return json.loads(path.read_text(encoding="utf-8"))

    def _save(self, project: Path, manifest: dict[str, Any]) -> None:
        path = self._manifest_path(project)
        path.parent.mkdir(parents=True, exist_ok=True)
        tmp = path.with_suffix(".json.tmp")
        tmp.write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")
        tmp.replace(path)

    def _pin(self, project: Path, scene_id: str) -> Optional[dict[str, Any]]:
        entry = self._load(project)["scenes"].get(scene_id)
        if entry and (project / entry["file"]).exists():
            return entry
        return None

    # -- operations ----------------------------------------------------

    def _request(self, inputs: dict[str, Any]) -> dict[str, Any]:
        mode = MODES[inputs.get("mode", "draft")]
        scene_id = inputs.get("scene_id", "")
        request = {
            "prompt": inputs["prompt"],
            "aspect_ratio": inputs.get("aspect_ratio", "16:9"),
            "model": inputs.get("model") or mode["model"],
            "resolution": inputs.get("resolution") or mode["resolution"],
            "seed": inputs.get("seed", stable_seed(scene_id, inputs["prompt"])),
        }
        for key in ("output_path", "scene_id", "preferred_tool"):
            if inputs.get(key):
                request[key] = inputs[key]
        return request

    def _generate(self, inputs: dict[str, Any]) -> ToolResult:
        if not inputs.get("prompt"):
            return ToolResult(success=False, error="prompt is required")
        project = infer_project_dir(inputs)
        scene_id = inputs.get("scene_id")
        if project and scene_id:
            pin = self._pin(project, scene_id)
            if pin:
                pinned = project / pin["file"]
                out = Path(inputs.get("output_path") or pinned)
                if out.resolve() != pinned.resolve():
                    out.parent.mkdir(parents=True, exist_ok=True)
                    shutil.copyfile(pinned, out)
                return ToolResult(
                    success=True,
                    data={"source": "approved_pin", "scene_id": scene_id, "output": str(out),
                          "sha256": pin["sha256"], "model": pin.get("model"),
                          "note": "approved image reused; unapprove it to generate again"},
                    artifacts=[str(out)],
                    cost_usd=0.0,
                    model=pin.get("model"),
                )

        request = self._request(inputs)
        result = self.selector.execute(request)
        result.data = {
            **(result.data or {}),
            "mode": inputs.get("mode", "draft"),
            "requested_model": request["model"],
            "resolution": request["resolution"],
            "seed_requested": request["seed"],
            "source": "generated",
        }
        return result

    def _batch(self, inputs: dict[str, Any]) -> ToolResult:
        from lib.parallel_runner import Job, run_parallel

        shared = {k: v for k, v in inputs.items()
                  if k in ("mode", "aspect_ratio", "model", "resolution", "project_dir")}
        jobs = [
            Job(key=item.get("scene_id") or str(i), provider="image",
                fn=lambda item=item: self._generate({**shared, **item}))
            for i, item in enumerate(inputs.get("items") or [])
        ]
        report = run_parallel(jobs, limits={"image": int(inputs.get("concurrency", 3))})
        outputs = {r.key: (r.value.data if r.ok else None) for r in report.results}
        summary = report.summary()
        return ToolResult(
            success=not report.failed,
            data={"summary": summary, "results": outputs},
            artifacts=[a for r in report.succeeded for a in (r.value.artifacts or [])],
            error=None if not report.failed else
            "; ".join(f"{f['key']}: {f['error']}" for f in summary["failed"]),
            cost_usd=report.cost_usd,
        )

    def _approve(self, inputs: dict[str, Any]) -> ToolResult:
        scene_id = inputs.get("scene_id")
        src = Path(inputs.get("image_path") or inputs.get("output_path") or "")
        project = infer_project_dir(inputs)
        if not scene_id or not project:
            return ToolResult(success=False, error="approve needs scene_id and a project")
        if not src.is_file():
            return ToolResult(success=False, error=f"Image not found: {src}")
        manifest = self._load(project)
        if scene_id in manifest["scenes"]:
            return ToolResult(
                success=False,
                error=f"{scene_id} already has an approved image; unapprove it first",
            )
        sha = file_sha256(src)
        rel = APPROVED_DIR / f"{_safe_name(scene_id)}_{sha[:12]}{src.suffix.lower()}"
        dest = project / rel
        dest.parent.mkdir(parents=True, exist_ok=True)
        if not dest.exists():
            shutil.copyfile(src, dest)
        entry = {
            "file": rel.as_posix(),
            "sha256": sha,
            "source_path": str(src),
            "prompt": inputs.get("prompt"),
            "model": inputs.get("model"),
            "approved_at": datetime.datetime.now(datetime.timezone.utc).isoformat(),
        }
        manifest["scenes"][scene_id] = entry
        manifest["history"].append({"event": "approve", "scene_id": scene_id, **entry})
        self._save(project, manifest)
        return ToolResult(success=True, data={"scene_id": scene_id, **entry},
                          artifacts=[str(dest)])

    def _unapprove(self, inputs: dict[str, Any]) -> ToolResult:
        scene_id = inputs.get("scene_id")
        project = infer_project_dir(inputs)
        if not scene_id or not project:
            return ToolResult(success=False, error="unapprove needs scene_id and a project")
        manifest = self._load(project)
        entry = manifest["scenes"].pop(scene_id, None)
        if entry is None:
            return ToolResult(success=False, error=f"{scene_id} has no approved image")
        manifest["history"].append({
            "event": "unapprove", "scene_id": scene_id, "file": entry["file"],
            "at": datetime.datetime.now(datetime.timezone.utc).isoformat(),
        })
        self._save(project, manifest)
        return ToolResult(success=True, data={"scene_id": scene_id, "kept_file": entry["file"]})

    def _status(self, inputs: dict[str, Any]) -> ToolResult:
        project = infer_project_dir(inputs)
        if not project:
            return ToolResult(success=False, error="status needs a project")
        return ToolResult(success=True, data={"scenes": self._load(project)["scenes"]})

    def execute(self, inputs: dict[str, Any]) -> ToolResult:
        operation = inputs.get("operation", "generate")
        if inputs.get("mode", "draft") not in MODES:
            return ToolResult(success=False, error=f"Unknown mode: {inputs.get('mode')}")
        handler = {
            "generate": self._generate,
            "batch": self._batch,
            "approve": self._approve,
            "unapprove": self._unapprove,
            "status": self._status,
        }.get(operation)
        if handler is None:
            return ToolResult(success=False, error=f"Unknown operation: {operation}")
        return handler(inputs)
