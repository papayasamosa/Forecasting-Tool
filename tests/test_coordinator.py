"""Tests for InferenceCoordinator: the process-wide semaphore that serialises
concurrent forecast calls.

These prove genuine concurrent behaviour with real threads rather than
asserting on a weakened ordering condition — a prior coordinator test
(evidence: "Fix flaky coordinator test") had to relax its overlap assertion
to ``first_start <= second_completion``, which is also true for two purely
sequential calls and therefore does not prove overlap actually occurred.
"""
from __future__ import annotations

import threading
import time
from datetime import datetime

import pytest

from src.coordinator import (
    CoordinatorTimeoutError,
    InferenceCoordinator,
)


def _parse(ts: str) -> datetime:
    return datetime.fromisoformat(ts)


class TestCapacityOneSerialisesCalls:
    def test_two_overlapping_requests_are_serialised(self):
        """With capacity=1, two threads that both attempt to acquire at the
        same time must never have their inference windows overlap — one
        must fully complete before the other's inference window starts."""
        coordinator = InferenceCoordinator(capacity=1, timeout_seconds=5)
        # Synchronises the two threads' *attempt to acquire*, not their
        # entry into the guarded call — with capacity=1 only one thread can
        # ever be inside the guarded call at once, so a barrier placed
        # inside it would deadlock the other thread's wait.
        barrier = threading.Barrier(2)

        def _slow_call(tag: str):
            time.sleep(0.15)
            return tag

        results: dict[str, Exception | str] = {}

        def _worker(tag: str):
            barrier.wait(timeout=2)
            try:
                results[tag] = coordinator.run(_slow_call, tag, request_id=tag)
            except Exception as exc:  # pragma: no cover - only on failure
                results[tag] = exc

        t1 = threading.Thread(target=_worker, args=("req_a",))
        t2 = threading.Thread(target=_worker, args=("req_b",))
        t1.start()
        t2.start()
        t1.join(timeout=5)
        t2.join(timeout=5)

        assert results["req_a"] == "req_a"
        assert results["req_b"] == "req_b"

        log = {e["request_id"]: e for e in coordinator.request_log}
        first, second = sorted(
            log.values(), key=lambda e: e["inference_start_utc"]
        )
        first_end = _parse(first["completion_time_utc"])
        second_start = _parse(second["inference_start_utc"])
        # Serialised: the second request's inference cannot begin before the
        # first request's inference has actually completed.
        assert second_start >= first_end

    def test_semaphore_capacity_is_available_again_after_success(self):
        coordinator = InferenceCoordinator(capacity=1, timeout_seconds=5)
        coordinator.run(lambda: "ok", request_id="req_1")
        # A second call must acquire immediately (no deadlock / leaked permit).
        started = time.monotonic()
        coordinator.run(lambda: "ok", request_id="req_2")
        assert time.monotonic() - started < 1.0


class TestCapacityTwoAllowsGenuineOverlap:
    def test_two_concurrent_requests_overlap_in_wall_time(self):
        """With capacity=2, two simultaneous calls must actually run at the
        same time — proven by overlapping [inference_start, completion)
        windows, not just non-decreasing timestamps."""
        coordinator = InferenceCoordinator(capacity=2, timeout_seconds=5)
        barrier = threading.Barrier(2)

        def _slow_call(tag: str):
            barrier.wait(timeout=2)
            time.sleep(0.2)
            return tag

        def _worker(tag: str):
            coordinator.run(_slow_call, tag, request_id=tag)

        t1 = threading.Thread(target=_worker, args=("req_a",))
        t2 = threading.Thread(target=_worker, args=("req_b",))
        t1.start()
        t2.start()
        t1.join(timeout=5)
        t2.join(timeout=5)

        log = {e["request_id"]: e for e in coordinator.request_log}
        a_start = _parse(log["req_a"]["inference_start_utc"])
        a_end = _parse(log["req_a"]["completion_time_utc"])
        b_start = _parse(log["req_b"]["inference_start_utc"])
        b_end = _parse(log["req_b"]["completion_time_utc"])
        # Interval intersection, independent of which request the test
        # happens to label "first".
        overlap = min(a_end, b_end) > max(a_start, b_start)
        assert overlap, (
            f"Expected overlapping inference windows with capacity=2: "
            f"req_a=({a_start}, {a_end}) req_b=({b_start}, {b_end})"
        )


class TestTimeout:
    def test_timeout_raises_and_releases_no_permit(self):
        coordinator = InferenceCoordinator(capacity=1, timeout_seconds=0.2)
        holder_started = threading.Event()
        release_holder = threading.Event()

        def _hold():
            holder_started.set()
            release_holder.wait(timeout=5)
            return "held"

        holder_thread = threading.Thread(
            target=lambda: coordinator.run(_hold, request_id="holder")
        )
        holder_thread.start()
        holder_started.wait(timeout=2)

        with pytest.raises(CoordinatorTimeoutError):
            coordinator.run(lambda: "should not run", request_id="impatient")

        release_holder.set()
        holder_thread.join(timeout=5)

        log = {e["request_id"]: e for e in coordinator.request_log}
        assert log["impatient"]["success"] is False
        assert log["impatient"]["error_code"] == "CoordinatorTimeoutError"
        assert log["holder"]["success"] is True

        # The timed-out waiter must not have consumed a permit: a fresh call
        # after the holder releases must succeed immediately.
        coordinator.run(lambda: "ok", request_id="after")
        log_success = {e["request_id"]: e["success"] for e in coordinator.request_log}
        assert log_success["after"] is True


class TestReleaseAfterFailure:
    def test_semaphore_releases_after_backend_exception(self):
        """A failing inference call must still release its permit so the
        next request is not starved by an exception in `fn`."""
        coordinator = InferenceCoordinator(capacity=1, timeout_seconds=2)

        def _boom():
            raise RuntimeError("simulated backend failure")

        with pytest.raises(RuntimeError):
            coordinator.run(_boom, request_id="failing")

        log = {e["request_id"]: e for e in coordinator.request_log}
        assert log["failing"]["success"] is False
        assert log["failing"]["error_code"] == "RuntimeError"

        # Next call must acquire immediately — no permit leaked by the raise.
        started = time.monotonic()
        result = coordinator.run(lambda: "recovered", request_id="next")
        assert result == "recovered"
        assert time.monotonic() - started < 1.0


class TestConstructorValidation:
    def test_rejects_zero_capacity(self):
        with pytest.raises(ValueError):
            InferenceCoordinator(capacity=0)

    def test_rejects_non_positive_timeout(self):
        with pytest.raises(ValueError):
            InferenceCoordinator(timeout_seconds=0)


class TestRequestLog:
    def test_clear_log_empties_it(self):
        coordinator = InferenceCoordinator(capacity=1, timeout_seconds=2)
        coordinator.run(lambda: "ok", request_id="req_1")
        assert len(coordinator.request_log) == 1
        coordinator.clear_log()
        assert coordinator.request_log == []

    def test_request_log_is_a_copy(self):
        coordinator = InferenceCoordinator(capacity=1, timeout_seconds=2)
        coordinator.run(lambda: "ok", request_id="req_1")
        log = coordinator.request_log
        log.append({"tampered": True})
        assert len(coordinator.request_log) == 1

    def test_auto_generated_request_id_when_not_supplied(self):
        coordinator = InferenceCoordinator(capacity=1, timeout_seconds=2)
        coordinator.run(lambda: "ok")
        assert coordinator.request_log[0]["request_id"]

    def test_sync_mode_recorded_as_semaphore(self):
        coordinator = InferenceCoordinator(capacity=1, timeout_seconds=2)
        coordinator.run(lambda: "ok", request_id="req_1")
        assert coordinator.request_log[0]["sync_mode"] == "semaphore"
        assert coordinator.sync_mode == "semaphore"
