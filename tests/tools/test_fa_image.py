"""fa_image: draft/final routing, approved pins, stable seeds. No network."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from tools.base_tool import ToolResult, ToolStatus
from tools.graphics.fa_image import MODES, FaImage, infer_project_dir, stable_seed


class _FakeSelector:
    def __init__(self):
        self.calls = []

    def get_status(self):
        return ToolStatus.AVAILABLE

    def estimate_cost(self, inputs):
        return {"1K": 0.0336, "2K": 0.101}[inputs["resolution"]]

    def execute(self, inputs):
        self.calls.append(dict(inputs))
        out = Path(inputs["output_path"])
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_bytes(b"PNG" + inputs["prompt"].encode("utf-8"))
        return ToolResult(success=True, data={"output": str(out)}, artifacts=[str(out)],
                          cost_usd=0.0336, model=inputs["model"])


def _tool():
    sel = _FakeSelector()
    return FaImage(selector=sel), sel


def test_draft_uses_cheapest_model_and_pins_a_seed(tmp_path):
    tool, sel = _tool()
    out = tmp_path / "projects" / "demo" / "assets" / "draft" / "s1.png"
    r = tool.execute({"scene_id": "s1", "prompt": "a 1938 dried-fish shop", "output_path": str(out)})
    assert r.success
    call = sel.calls[0]
    assert call["model"] == MODES["draft"]["model"] == "gemini-3.1-flash-lite-image"
    assert call["resolution"] == "1K"
    assert call["seed"] == stable_seed("s1", "a 1938 dried-fish shop")
    assert r.data["mode"] == "draft" and r.data["source"] == "generated"


def test_final_uses_production_model_at_2k(tmp_path):
    tool, sel = _tool()
    out = tmp_path / "projects" / "demo" / "s1.png"
    tool.execute({"mode": "final", "scene_id": "s1", "prompt": "p", "output_path": str(out)})
    assert sel.calls[0]["model"] == "gemini-3.1-flash-image"
    assert sel.calls[0]["resolution"] == "2K"
    assert tool.estimate_cost({"mode": "final", "scene_id": "s1", "prompt": "p",
                               "output_path": str(out)}) == 0.101


def test_seed_is_stable_and_scene_specific():
    assert stable_seed("s1", "x") == stable_seed("s1", "x")
    assert stable_seed("s1", "x") != stable_seed("s2", "x")
    assert 0 <= stable_seed("s1", "x") < 2**31


def test_approved_scene_is_never_generated_again(tmp_path):
    tool, sel = _tool()
    project = tmp_path / "projects" / "demo"
    draft = project / "assets" / "draft" / "s1.png"
    tool.execute({"scene_id": "s1", "prompt": "hook", "output_path": str(draft)})
    assert len(sel.calls) == 1

    a = tool.execute({"operation": "approve", "scene_id": "s1", "image_path": str(draft),
                      "prompt": "hook", "model": "gemini-3.1-flash-lite-image"})
    assert a.success
    pinned = project / a.data["file"]
    assert pinned.exists() and pinned.parent.name == "approved"
    assert a.data["sha256"][:12] in pinned.name

    final = project / "assets" / "images" / "s1.png"
    r = tool.execute({"mode": "final", "scene_id": "s1", "prompt": "hook, but different",
                      "output_path": str(final)})
    assert r.success and r.cost_usd == 0.0
    assert r.data["source"] == "approved_pin"
    assert final.read_bytes() == pinned.read_bytes()
    assert len(sel.calls) == 1  # no provider call after approval
    assert tool.estimate_cost({"scene_id": "s1", "prompt": "x", "output_path": str(final)}) == 0.0


def test_approve_twice_is_refused_and_unapprove_keeps_the_file(tmp_path):
    tool, sel = _tool()
    project = tmp_path / "projects" / "demo"
    img = project / "a.png"
    img.parent.mkdir(parents=True)
    img.write_bytes(b"one")
    first = tool.execute({"operation": "approve", "scene_id": "s1", "image_path": str(img)})
    assert first.success
    again = tool.execute({"operation": "approve", "scene_id": "s1", "image_path": str(img)})
    assert not again.success and "unapprove" in again.error

    un = tool.execute({"operation": "unapprove", "scene_id": "s1", "project_dir": str(project)})
    assert un.success
    assert (project / first.data["file"]).exists()
    manifest = json.loads((project / "assets/approved/approved.json").read_text(encoding="utf-8"))
    assert manifest["scenes"] == {}
    assert [h["event"] for h in manifest["history"]] == ["approve", "unapprove"]

    tool.execute({"scene_id": "s1", "prompt": "new", "output_path": str(project / "b.png")})
    assert len(sel.calls) == 1  # generates again once unapproved


def test_project_dir_is_inferred_from_paths():
    assert infer_project_dir({"output_path": "projects/samsung/assets/x.png"}) == Path("projects/samsung")
    assert infer_project_dir({"project_dir": "p"}) == Path("p")
    assert infer_project_dir({"output_path": "elsewhere/x.png"}) is None


def test_bad_inputs():
    tool, _ = _tool()
    assert not tool.execute({"mode": "ultra", "prompt": "x"}).success
    assert not tool.execute({"operation": "nope"}).success
    assert not tool.execute({"scene_id": "s1"}).success
    assert not tool.execute({"operation": "approve", "scene_id": "s1",
                             "project_dir": "p", "image_path": "missing.png"}).success


def test_batch_runs_every_scene_and_reports_failures(tmp_path):
    tool, sel = _tool()
    original = sel.execute

    def flaky(inputs):
        if inputs["scene_id"] == "s2":
            return ToolResult(success=False, error="HTTP 403")
        return original(inputs)

    sel.execute = flaky
    project = tmp_path / "projects" / "demo"
    items = [{"scene_id": f"s{i}", "prompt": f"scene {i}",
              "output_path": str(project / f"s{i}.png")} for i in range(1, 5)]
    r = tool.execute({"operation": "batch", "mode": "draft", "items": items})
    assert not r.success and "s2: HTTP 403" in r.error
    assert r.data["summary"]["succeeded"] == 3
    assert r.data["results"]["s2"] is None
    assert len(r.artifacts) == 3
    assert r.cost_usd == pytest.approx(3 * 0.0336)
    assert {c["model"] for c in sel.calls} == {"gemini-3.1-flash-lite-image"}
