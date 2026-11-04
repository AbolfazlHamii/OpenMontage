"""Hook lab and fact-check helpers for Persian productions.

Hook lab: the worker tier drafts 12 hooks, the agent shortlists 3 with
reasons, the owner picks one. Fact-check: the bulk tier extracts checkable
claims from the script, the agent verifies each against a source, and the
result goes into decision_log (category fact_check / hook_selection).

The cheap tiers only draft; every decision here is the agent's or the owner's.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Optional

import jsonschema

REPO_ROOT = Path(__file__).resolve().parent.parent
DECISION_SCHEMA = REPO_ROOT / "schemas" / "artifacts" / "decision_log.schema.json"

HOOKS_SCHEMA = {
    "type": "object", "required": ["hooks"],
    "properties": {"hooks": {"type": "array", "minItems": 12, "maxItems": 12, "items": {
        "type": "object", "required": ["text", "type"],
        "properties": {"text": {"type": "string", "minLength": 8},
                       "type": {"type": "string", "enum": ["number", "paradox", "question", "shock", "story", "promise"]}},
    }}},
}
CLAIMS_SCHEMA = {
    "type": "object", "required": ["claims"],
    "properties": {"claims": {"type": "array", "items": {
        "type": "object", "required": ["claim", "kind"],
        "properties": {"claim": {"type": "string"}, "section_id": {"type": "string"},
                       "kind": {"type": "string", "enum": ["date", "number", "name", "event", "quote", "other"]}},
    }}},
}
VERDICTS = {"verified", "corrected", "removed", "unverified"}


def hooks_prompt(topic: str, brief: str = "") -> str:
    return (
        f"Write 12 different opening hooks (first 3 seconds, at most 18 words each) in colloquial "
        f"Tehran Persian for a YouTube video: {topic}. {brief}\n"
        "Mix the types: number, paradox, question, shock, story, promise (2 of each). "
        "Only facts that are in the brief; no invented numbers. "
        'Return JSON {"hooks": [{"text": "...", "type": "number"}, ...]}'
    )


def claims_prompt(script_text: str) -> str:
    return (
        "List every checkable factual claim in this narration script (dates, numbers, names, "
        "events, quotes). One claim per item, in the script's language, short. "
        'Return JSON {"claims": [{"claim": "...", "kind": "date", "section_id": "..."}]}\n\n'
        + script_text
    )


def script_text(script: dict[str, Any]) -> str:
    return "\n".join(f"[{s['id']}] {s['text']}" for s in script.get("sections", []))


def draft(llm, task: str, prompt: str, schema: dict[str, Any]) -> tuple[Any, float, Optional[str]]:
    r = llm.execute({"task": task, "prompt": prompt, "json_schema": schema, "temperature": 0.7})
    return (r.data or {}).get("json"), r.cost_usd or 0.0, None if r.success else r.error


def _load_log(path: Path, project_id: str) -> dict[str, Any]:
    if path.exists():
        return json.loads(path.read_text(encoding="utf-8"))
    return {"version": "1.0", "project_id": project_id, "decisions": []}


def _next_id(log: dict[str, Any]) -> str:
    nums = [int(d["decision_id"][1:]) for d in log["decisions"]
            if str(d.get("decision_id", "")).startswith("d") and d["decision_id"][1:].isdigit()]
    return f"d{max(nums, default=0) + 1}"


def append_decision(log_path: Path, entry: dict[str, Any], project_id: str = "") -> dict[str, Any]:
    """Append one decision, validate the whole log, write atomically."""
    log = _load_log(log_path, project_id or log_path.parent.name)
    entry = {"decision_id": _next_id(log), **entry}
    log["decisions"].append(entry)
    schema = json.loads(DECISION_SCHEMA.read_text(encoding="utf-8"))
    jsonschema.validate(log, schema)
    tmp = log_path.with_suffix(".json.tmp")
    tmp.write_text(json.dumps(log, ensure_ascii=False, indent=2), encoding="utf-8")
    tmp.replace(log_path)
    return entry


def hook_decision(hooks: list[dict[str, Any]], shortlist: list[dict[str, Any]],
                  owner_pick: Optional[int], stage: str = "script") -> dict[str, Any]:
    """shortlist: [{index, reason, score}] chosen by the agent; owner_pick: index or None."""
    options = [{"option_id": f"h{s['index']}", "label": hooks[s["index"]]["text"],
                "score": float(s.get("score", 0.5)), "reason": s["reason"]} for s in shortlist]
    if owner_pick is None:
        selected, reason = "pending_owner", "Agent shortlist of 3 from 12 worker drafts; waiting for the owner."
    else:
        selected = f"h{owner_pick}"
        reason = "Owner picked from the agent's shortlist (12 worker drafts → 3)."
    return {"stage": stage, "category": "hook_selection", "subject": "Opening hook",
            "options_considered": options, "selected": selected, "reason": reason,
            "user_visible": True, "user_approved": owner_pick is not None}


def fact_check_decision(claims: list[dict[str, Any]], stage: str = "script") -> dict[str, Any]:
    """claims: [{claim, verdict, source, note}] after the agent checked each one."""
    bad = [c for c in claims if c.get("verdict") not in VERDICTS]
    if bad:
        raise ValueError(f"claims without a verdict: {[c['claim'] for c in bad]}")
    missing = [c["claim"] for c in claims if c["verdict"] in {"verified", "corrected"} and not c.get("source")]
    if missing:
        raise ValueError(f"verified/corrected claims need a source: {missing}")
    score = {"verified": 1.0, "corrected": 0.7, "removed": 0.0, "unverified": 0.2}
    options = [{"option_id": f"c{i + 1}", "label": c["claim"][:120], "score": score[c["verdict"]],
                "reason": f"{c['verdict']}: {c.get('source') or c.get('note') or 'no source'}"[:300]}
               for i, c in enumerate(claims)]
    counts = {v: sum(1 for c in claims if c["verdict"] == v) for v in sorted(VERDICTS)}
    unverified = counts.get("unverified", 0)
    return {"stage": stage, "category": "fact_check", "subject": "Script fact-check",
            "options_considered": options,
            "selected": "script_cleared" if not unverified else "script_has_unverified_claims",
            "reason": "Claims extracted by the bulk tier, each checked by the agent against a source: "
                      + ", ".join(f"{k} {v}" for k, v in counts.items() if v),
            "user_visible": True}
