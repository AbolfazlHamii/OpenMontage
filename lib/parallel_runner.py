"""Run independent jobs in parallel with a concurrency cap per provider.

Asset generation in OpenMontage is serial: three stills took three times as
long as one. Scene images and narration lines are independent, so they can
run side by side, but each provider has its own rate limit, so the cap is
per provider rather than global.

One failed job never stops the batch: every job gets a JobResult, in input
order, saying whether it succeeded and why not. A ToolResult with
success=False counts as a failure just like an exception does.

    from lib.parallel_runner import Job, run_parallel
    jobs = [Job(key=s["id"], provider="avalai", fn=lambda s=s: tool.execute(s))
            for s in scenes]
    for r in run_parallel(jobs, limits={"avalai": 3}):
        print(r.key, r.ok, r.error)

`plan_makespan` gives the wall time a batch would take under the same caps,
from per-job durations. It runs no jobs and is what cost/time estimates use.
"""

from __future__ import annotations

import heapq
import time
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field
from typing import Any, Callable, Iterable, Optional

DEFAULT_LIMIT = 3


@dataclass
class Job:
    key: str
    provider: str
    fn: Callable[[], Any]


@dataclass
class JobResult:
    key: str
    provider: str
    ok: bool
    value: Any = None
    error: Optional[str] = None
    seconds: float = 0.0
    cost_usd: float = 0.0


@dataclass
class BatchReport:
    results: list[JobResult] = field(default_factory=list)
    seconds: float = 0.0

    @property
    def succeeded(self) -> list[JobResult]:
        return [r for r in self.results if r.ok]

    @property
    def failed(self) -> list[JobResult]:
        return [r for r in self.results if not r.ok]

    @property
    def cost_usd(self) -> float:
        return round(sum(r.cost_usd for r in self.results), 6)

    def summary(self) -> dict[str, Any]:
        return {
            "total": len(self.results),
            "succeeded": len(self.succeeded),
            "failed": [{"key": r.key, "provider": r.provider, "error": r.error} for r in self.failed],
            "seconds": round(self.seconds, 2),
            "cost_usd": self.cost_usd,
        }


def _limit_for(provider: str, limits: Optional[dict[str, int]], default: int) -> int:
    value = (limits or {}).get(provider, default)
    return max(1, int(value))


def _run_one(job: Job, clock: Callable[[], float]) -> JobResult:
    started = clock()
    try:
        value = job.fn()
    except Exception as exc:  # one job's failure stays with that job
        return JobResult(job.key, job.provider, False, error=f"{type(exc).__name__}: {exc}",
                         seconds=clock() - started)
    seconds = clock() - started
    cost = getattr(value, "cost_usd", 0.0) or 0.0
    if getattr(value, "success", True) is False:
        return JobResult(job.key, job.provider, False, value=value,
                         error=getattr(value, "error", None) or "tool reported failure",
                         seconds=seconds, cost_usd=cost)
    return JobResult(job.key, job.provider, True, value=value, seconds=seconds, cost_usd=cost)


def run_parallel(
    jobs: Iterable[Job],
    limits: Optional[dict[str, int]] = None,
    default_limit: int = DEFAULT_LIMIT,
    clock: Callable[[], float] = time.monotonic,
) -> BatchReport:
    """Run jobs concurrently, at most `limits[provider]` at a time per provider."""
    jobs = list(jobs)
    started = clock()
    if not jobs:
        return BatchReport()
    # One pool per provider, sized to its cap: a shared pool would let jobs
    # queued for a busy provider hold threads another provider could use.
    pools = {
        p: ThreadPoolExecutor(max_workers=_limit_for(p, limits, default_limit),
                              thread_name_prefix=f"om-{p}")
        for p in dict.fromkeys(j.provider for j in jobs)
    }
    try:
        futures = [pools[j.provider].submit(_run_one, j, clock) for j in jobs]
        results = [f.result() for f in futures]
    finally:
        for pool in pools.values():
            pool.shutdown(wait=True)
    return BatchReport(results=results, seconds=clock() - started)


def plan_makespan(
    durations: Iterable[tuple[str, float]],
    limits: Optional[dict[str, int]] = None,
    default_limit: int = DEFAULT_LIMIT,
) -> float:
    """Wall seconds for (provider, seconds) jobs run in order under per-provider caps.

    Providers run independently of each other, so the batch takes as long as
    its slowest provider; within a provider, jobs start in input order on the
    first free slot.
    """
    per_provider: dict[str, list[float]] = {}
    for provider, seconds in durations:
        per_provider.setdefault(provider, []).append(float(seconds))
    makespan = 0.0
    for provider, items in per_provider.items():
        slots = [0.0] * _limit_for(provider, limits, default_limit)
        heapq.heapify(slots)
        end = 0.0
        for seconds in items:
            free_at = heapq.heappop(slots)
            finish = free_at + seconds
            end = max(end, finish)
            heapq.heappush(slots, finish)
        makespan = max(makespan, end)
    return makespan
