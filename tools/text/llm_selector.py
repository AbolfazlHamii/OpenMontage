"""Route text tasks to the cheapest tier that can do them.

task -> tier (config/llm_routing.yaml) -> chain of profile/model entries.

- A call that fails (network, HTTP, missing key) falls through to the next
  entry in the tier and is reported in `fallback_from` (short_error).
- An answer that is rejected (invalid JSON after the tool's repair retry, or
  a caller's `validator`) counts against the tier; after two rejections the
  task escalates to the next tier and the reason is recorded.
- Premium in interactive mode is the agent itself: escalating there, or a
  task marked `final_persian`, returns control to the agent instead of
  calling an API.
- Costs go to a CostTracker ledger when `cost_log_path` is given.

CLI for the agent (Bash):

    python -m tools.text.llm_selector --task hooks --input in.txt --out out.json
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path
from typing import Any, Callable, Optional

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
from tools.text.openai_compat_llm import ROUTING_PATH, OpenAICompatLLM, load_yaml

MODE_ENV = "OPENMONTAGE_LLM_MODE"
REJECTIONS_BEFORE_ESCALATION = 2


class LLMSelector(BaseTool):
    name = "llm_selector"
    version = "0.1.0"
    tier = ToolTier.CORE
    capability = "text_generation"
    provider = "selector"
    stability = ToolStability.EXPERIMENTAL
    execution_mode = ExecutionMode.SYNC
    determinism = Determinism.STOCHASTIC
    runtime = ToolRuntime.HYBRID

    install_instructions = OpenAICompatLLM.install_instructions
    agent_skills = ["provider-model-refresh"]
    fallback_tools = ["openai_compat_llm"]
    capabilities = ["task_routing", "fallback", "escalation", "batch"]
    best_for = ["delegating bulk/worker text work (drafts, hooks, prompts, JSON) to cheap models"]
    not_good_for = ["final Persian narration, subtitles, titles or descriptions"]

    input_schema = {
        "type": "object",
        "properties": {
            "operation": {"type": "string", "enum": ["run", "batch", "plan"], "default": "run"},
            "task": {"type": "string"},
            "prompt": {"type": "string"},
            "system": {"type": "string"},
            "messages": {"type": "array", "items": {"type": "object"}},
            "images": {"type": "array", "items": {"type": "string"}},
            "json_schema": {"type": "object"},
            "temperature": {"type": "number"},
            "max_tokens": {"type": "integer"},
            "tier": {"type": "string", "description": "Override the task's tier."},
            "mode": {"type": "string", "enum": ["interactive", "headless"]},
            "cost_log_path": {"type": "string"},
            "items": {"type": "array", "items": {"type": "object"}},
        },
    }
    side_effects = ["paid API calls through openai_compat_llm"]

    def __init__(self, llm: Optional[OpenAICompatLLM] = None, routing_path: Path = ROUTING_PATH,
                 validator: Optional[Callable[[dict[str, Any]], Optional[str]]] = None):
        self.routing_path = routing_path
        self.llm = llm or OpenAICompatLLM(routing_path=routing_path)
        # Extra acceptance check on a successful answer: return a reason to reject.
        self.validator = validator

    @property
    def routing(self) -> dict[str, Any]:
        return load_yaml(self.routing_path)

    def run_mode(self, inputs: dict[str, Any]) -> str:
        return inputs.get("mode") or os.environ.get(MODE_ENV) or self.routing.get("mode", "interactive")

    def get_status(self) -> ToolStatus:
        return self.llm.get_status()

    def task_config(self, task: str) -> dict[str, Any]:
        tasks = self.routing.get("tasks", {})
        if task not in tasks:
            raise ValueError(f"unknown task {task!r}; known: {', '.join(sorted(tasks))}")
        return tasks[task]

    def tiers_from(self, tier: str) -> list[str]:
        order = self.routing.get("escalation", ["local", "bulk", "worker", "premium"])
        return order[order.index(tier):] if tier in order else [tier]

    def plan(self, task: str, tier: Optional[str] = None) -> list[dict[str, Any]]:
        """Entries the task would try, with availability, without calling anything."""
        cfg = self.task_config(task)
        out = []
        for t in self.tiers_from(tier or cfg["tier"]):
            for entry in self.routing.get("tiers", {}).get(t) or []:
                ok, reason = self.llm.profile_status(entry["profile"])
                out.append({"tier": t, **entry, "available": ok, "reason": reason})
        return out

    def estimate_cost(self, inputs: dict[str, Any]) -> float:
        for entry in self.plan(inputs["task"], inputs.get("tier")):
            if entry["available"] and entry["tier"] != "premium":
                return self.llm.estimate_cost({**inputs, **entry})
        return 0.0

    # -- execution ---------------------------------------------------------

    def _ledger(self, inputs: dict[str, Any]):
        if not inputs.get("cost_log_path"):
            return None
        from tools.cost_tracker import BudgetMode, CostTracker

        tracker = CostTracker(cost_log_path=Path(inputs["cost_log_path"]), mode=BudgetMode.WARN)
        tracker.approve_tool(self.llm.name)
        return tracker

    def _back_to_agent(self, task: str, reason: str, attempts: list, fallback_from: list,
                       cost: float) -> ToolResult:
        return ToolResult(
            success=False,
            error=f"ESCALATE TO AGENT: {task} needs the premium tier ({reason}). "
                  "Write or review this yourself; no API was called for it.",
            data={"escalated_to": "agent", "task": task, "reason": reason,
                  "attempts": attempts, "fallback_from": fallback_from},
            cost_usd=round(cost, 8),
        )

    def _run(self, inputs: dict[str, Any]) -> ToolResult:
        task = inputs["task"]
        cfg = self.task_config(task)
        mode = self.run_mode(inputs)
        tracker = self._ledger(inputs)
        attempts: list[dict[str, Any]] = []
        fallback_from: list[dict[str, str]] = []
        cost = 0.0

        if cfg.get("final_persian") and mode == "interactive":
            return self._back_to_agent(task, "final Persian text is premium-only", attempts,
                                       fallback_from, cost)

        request = {k: inputs[k] for k in ("prompt", "system", "messages", "images", "json_schema",
                                          "temperature", "max_tokens") if k in inputs}
        request["json_mode"] = bool(cfg.get("json") or inputs.get("json_schema"))
        tiers = self.tiers_from(inputs.get("tier") or cfg["tier"])
        escalation_reason = None

        for tier in tiers:
            if tier == "premium" and mode == "interactive":
                return self._back_to_agent(task, escalation_reason or "no cheaper tier succeeded",
                                           attempts, fallback_from, cost)
            if cfg.get("final_persian") and tier != "premium":
                continue
            rejections = 0
            for entry in self.routing.get("tiers", {}).get(tier) or []:
                if rejections >= REJECTIONS_BEFORE_ESCALATION:
                    break
                where = {"tier": tier, "profile": entry["profile"], "model": entry["model"]}
                available, why = self.llm.profile_status(entry["profile"])
                if not available:
                    fallback_from.append({**where, "error": why})
                    attempts.append({**where, "outcome": "unavailable"})
                    continue
                call = {**request, "profile": entry["profile"], "model": entry["model"]}
                if entry.get("price"):
                    call["price"] = entry["price"]
                entry_id = None
                if tracker is not None:
                    entry_id = tracker.estimate(self.llm.name, f"{task}:{entry['model']}",
                                                self.llm.estimate_cost(call))
                    tracker.reserve(entry_id)
                result = self.llm.execute(call)
                cost += result.cost_usd or 0.0
                if tracker is not None:
                    tracker.reconcile(entry_id, result.cost_usd or 0.0, success=result.success)

                if not result.success and not result.data.get("rejected"):
                    from tools.provider_routing import short_error

                    fallback_from.append({**where, "error": short_error(result.error)})
                    attempts.append({**where, "outcome": "failed"})
                    continue
                reason = result.data.get("rejection") if result.data.get("rejected") else None
                if reason is None and self.validator is not None:
                    reason = self.validator(result.data)
                if reason:
                    rejections += 1
                    attempts.append({**where, "outcome": "rejected", "reason": reason})
                    continue
                attempts.append({**where, "outcome": "accepted"})
                result.data.update({
                    "task": task, "tier": tier, "mode": mode,
                    "attempts": attempts, "fallback_from": fallback_from,
                    "escalated_from": escalation_reason,
                    "cost_usd_total": round(cost, 8),
                })
                result.cost_usd = round(cost, 8)
                return result
            if rejections >= REJECTIONS_BEFORE_ESCALATION:
                escalation_reason = f"{tier} answers rejected {rejections} times"
            elif escalation_reason is None:
                escalation_reason = f"no {tier} model available"

        return ToolResult(
            success=False,
            error=f"{task}: every tier failed ({escalation_reason})",
            data={"task": task, "attempts": attempts, "fallback_from": fallback_from},
            cost_usd=round(cost, 8),
        )

    def _batch(self, inputs: dict[str, Any]) -> ToolResult:
        from lib.parallel_runner import Job, run_parallel

        shared = {k: v for k, v in inputs.items() if k not in ("operation", "items")}
        cap = int(self.routing.get("defaults", {}).get("concurrency_per_profile", 3))
        jobs = []
        for i, item in enumerate(inputs.get("items") or []):
            call = {**shared, **item}
            first = next((e for e in self.plan(call["task"], call.get("tier")) if e["available"]),
                         {"profile": "none"})
            jobs.append(Job(key=str(item.get("id", i)), provider=first["profile"],
                            fn=lambda call=call: self._run(call)))
        report = run_parallel(jobs, default_limit=cap)
        return ToolResult(
            success=not report.failed,
            data={"summary": report.summary(),
                  "results": {r.key: (r.value.data if r.value is not None else None)
                              for r in report.results}},
            cost_usd=report.cost_usd,
            error=None if not report.failed else
            "; ".join(f"{f['key']}: {f['error']}" for f in report.summary()["failed"]),
        )

    def execute(self, inputs: dict[str, Any]) -> ToolResult:
        operation = inputs.get("operation", "run")
        try:
            if operation == "plan":
                return ToolResult(success=True, data={
                    "mode": self.run_mode(inputs),
                    "entries": self.plan(inputs["task"], inputs.get("tier")),
                })
            if operation == "batch":
                return self._batch(inputs)
            if not inputs.get("task"):
                return ToolResult(success=False, error="task is required")
            return self._run(inputs)
        except ValueError as exc:
            return ToolResult(success=False, error=str(exc))


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description="Run one text task through the LLM router.")
    parser.add_argument("--task", required=True)
    parser.add_argument("--input", required=True, help="text file with the prompt")
    parser.add_argument("--out", help="write the result JSON here")
    parser.add_argument("--system", help="file with a system prompt")
    parser.add_argument("--schema", help="JSON schema file for the answer")
    parser.add_argument("--tier")
    parser.add_argument("--mode", choices=["interactive", "headless"])
    parser.add_argument("--temperature", type=float)
    parser.add_argument("--cost-log")
    args = parser.parse_args(argv)

    inputs: dict[str, Any] = {
        "task": args.task,
        "prompt": Path(args.input).read_text(encoding="utf-8"),
    }
    if args.system:
        inputs["system"] = Path(args.system).read_text(encoding="utf-8")
    if args.schema:
        inputs["json_schema"] = json.loads(Path(args.schema).read_text(encoding="utf-8"))
    for key in ("tier", "mode", "temperature"):
        if getattr(args, key) is not None:
            inputs[key] = getattr(args, key)
    if args.cost_log:
        inputs["cost_log_path"] = args.cost_log

    result = LLMSelector().execute(inputs)
    data = result.data or {}
    out = {
        "success": result.success,
        "result": data.get("json") if data.get("json") is not None else data.get("text"),
        "model": data.get("model"),
        "profile": data.get("profile"),
        "tier": data.get("tier"),
        "cost_usd": result.cost_usd,
        "fallback_from": data.get("fallback_from", []),
        "escalated_to": data.get("escalated_to"),
        "error": result.error,
    }
    text = json.dumps(out, ensure_ascii=False, indent=2)
    if args.out:
        Path(args.out).write_text(text, encoding="utf-8")
    sys.stdout.buffer.write((text + "\n").encode("utf-8"))
    return 0 if result.success else 1


if __name__ == "__main__":
    raise SystemExit(main())
