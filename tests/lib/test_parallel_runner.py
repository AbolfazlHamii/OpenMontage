"""lib.parallel_runner: per-provider caps, failure isolation, virtual-time plans.

No sleeps: jobs block on events, and timing uses a fake clock.
"""

from __future__ import annotations

import itertools
import threading

import pytest

from lib.parallel_runner import Job, plan_makespan, run_parallel
from tools.base_tool import ToolResult


class _Tracker:
    def __init__(self):
        self.lock = threading.Lock()
        self.running: dict[str, int] = {}
        self.peak: dict[str, int] = {}

    def enter(self, provider):
        with self.lock:
            self.running[provider] = self.running.get(provider, 0) + 1
            self.peak[provider] = max(self.peak.get(provider, 0), self.running[provider])

    def leave(self, provider):
        with self.lock:
            self.running[provider] -= 1


def _blocking_jobs(tracker, release, provider, n, started=None):
    def make(i):
        def fn():
            tracker.enter(provider)
            if started is not None:
                started.release()
            release.wait(timeout=5)
            tracker.leave(provider)
            return ToolResult(success=True, cost_usd=0.01, data={"i": i})
        return Job(key=f"{provider}-{i}", provider=provider, fn=fn)
    return [make(i) for i in range(n)]


def test_cap_is_per_provider():
    tracker = _Tracker()
    release = threading.Event()
    started = threading.Semaphore(0)
    jobs = (_blocking_jobs(tracker, release, "avalai", 7, started)
            + _blocking_jobs(tracker, release, "google", 4, started))

    def let_go():
        # 3 avalai + 2 google can start before anything finishes.
        for _ in range(5):
            assert started.acquire(timeout=5)
        release.set()

    t = threading.Thread(target=let_go)
    t.start()
    report = run_parallel(jobs, limits={"avalai": 3, "google": 2})
    t.join()

    assert tracker.peak == {"avalai": 3, "google": 2}
    assert len(report.succeeded) == 11
    assert report.cost_usd == pytest.approx(0.11)


def test_default_cap_is_three():
    tracker = _Tracker()
    release = threading.Event()
    started = threading.Semaphore(0)
    jobs = _blocking_jobs(tracker, release, "x", 6, started)

    def let_go():
        for _ in range(3):
            assert started.acquire(timeout=5)
        release.set()

    t = threading.Thread(target=let_go)
    t.start()
    run_parallel(jobs)
    t.join()
    assert tracker.peak["x"] == 3


def test_one_failure_does_not_stop_the_batch_and_order_is_kept():
    def boom():
        raise RuntimeError("HTTP 403")

    jobs = [
        Job("a", "p", lambda: ToolResult(success=True, cost_usd=0.0672)),
        Job("b", "p", boom),
        Job("c", "p", lambda: ToolResult(success=False, error="no image data")),
        Job("d", "q", lambda: "plain value"),
    ]
    report = run_parallel(jobs)

    assert [r.key for r in report.results] == ["a", "b", "c", "d"]
    assert [r.ok for r in report.results] == [True, False, False, True]
    assert report.results[1].error == "RuntimeError: HTTP 403"
    assert report.results[2].error == "no image data"
    assert report.results[3].value == "plain value"
    summary = report.summary()
    assert summary["succeeded"] == 2
    assert {f["key"] for f in summary["failed"]} == {"b", "c"}
    assert summary["cost_usd"] == pytest.approx(0.0672)


def test_seconds_come_from_the_injected_clock():
    ticks = itertools.count(0, 10)
    lock = threading.Lock()

    def clock():
        with lock:
            return float(next(ticks))

    report = run_parallel([Job("a", "p", lambda: 1)], clock=clock)
    assert report.results[0].seconds == 10.0
    assert report.seconds == 30.0


def test_empty_batch():
    report = run_parallel([])
    assert report.results == [] and report.seconds == 0.0


def test_plan_makespan_virtual_time():
    # Samsung sample: three stills at ~11 s each, serial today.
    stills = [("avalai", 11.6), ("avalai", 10.1), ("avalai", 10.6)]
    assert plan_makespan(stills, limits={"avalai": 1}) == pytest.approx(32.3)
    assert plan_makespan(stills, limits={"avalai": 3}) == pytest.approx(11.6)
    # Providers run side by side; the batch ends with the slowest one.
    mixed = stills + [("avalai_tts", 5.0), ("avalai_tts", 5.0)]
    assert plan_makespan(mixed, limits={"avalai": 3, "avalai_tts": 1}) == pytest.approx(11.6)
    # Five jobs on two slots: 4+4 | 4+4 | 4 -> 12.
    assert plan_makespan([("p", 4)] * 5, limits={"p": 2}) == pytest.approx(12.0)
    assert plan_makespan([]) == 0.0
