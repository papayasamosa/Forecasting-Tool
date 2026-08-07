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
    BackendExecutionUnresponsiveError,
    CoordinatorPoisonedError,
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
                exec_record = coordinator.run(_slow_call, tag, request_id=tag)
                results[tag] = exec_record.result
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
        exec_record = coordinator.run(lambda: "recovered", request_id="next")
        assert exec_record.result == "recovered"
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


class TestBackendExecutionWatchdog:
    """Stage A regression class: a backend execution that acquires the
    permit and then never returns must FAIL CLOSED.

    The coordinator must not release the permit (the old execution may
    still be using the shared pipeline), must refuse all new requests until
    the process is recycled, and must surface the unresponsive state in its
    health diagnostics.
    """

    def _hang_then_release(self, release_event: threading.Event):
        """A backend call that blocks until the test releases it."""
        release_event.wait(timeout=10)
        return "should-not-be-seen"

    def test_unresponsive_execution_poisons_coordinator_and_retains_permit(self):
        coordinator = InferenceCoordinator(
            capacity=1, queue_timeout_seconds=2, backend_execution_timeout_seconds=0.2
        )
        release_event = threading.Event()

        with pytest.raises(BackendExecutionUnresponsiveError):
            coordinator.run(
                self._hang_then_release, release_event, request_id="hung",
            )

        # The coordinator must be in the fail-closed poisoned state and must
        # report the unresponsive failure category.
        assert coordinator.health_state == "poisoned"
        assert coordinator.last_failure_category == "backend_execution_unresponsive"

        # The permit is deliberately retained (not released): ownership of
        # the unresponsive execution is still recorded.
        assert coordinator.active_request_id == "hung"
        assert coordinator.active_since_utc != ""

        # The request record is typed and truthful.
        record = coordinator.get_request_record("hung")
        assert record["success"] is False
        assert record["error_code"] == "BackendExecutionUnresponsiveError"

        # The hung worker must be released so the test process can exit
        # cleanly (the poisoned coordinator never reuses the permit).
        release_event.set()

    def test_poisoned_coordinator_refuses_new_requests_fast(self):
        """While poisoned, a new request must be refused immediately with
        CoordinatorPoisonedError — and the backend function must NOT be
        called again (no second inference can enter the shared pipeline)."""
        coordinator = InferenceCoordinator(
            capacity=1, queue_timeout_seconds=2, backend_execution_timeout_seconds=0.2
        )
        release_event = threading.Event()
        calls = []

        def _tracking_fn():
            calls.append("called")

        with pytest.raises(BackendExecutionUnresponsiveError):
            coordinator.run(self._hang_then_release, release_event, request_id="hung")
        release_event.set()

        started = time.monotonic()
        with pytest.raises(CoordinatorPoisonedError):
            coordinator.run(_tracking_fn, request_id="refused")
        elapsed = time.monotonic() - started
        # Refused fast — no queue wait, no backend call.
        assert elapsed < 1.0
        assert calls == [], "backend must never be invoked while poisoned"

        # Even a genuine queue timeout cannot reset the poisoned state.
        assert coordinator.health_state == "poisoned"

    def test_poisoned_state_is_not_recovered_in_process(self):
        """Fail-closed means the coordinator stays poisoned until the
        process is recycled — releasing the old execution must NOT make the
        permit reusable."""
        coordinator = InferenceCoordinator(
            capacity=1, queue_timeout_seconds=2, backend_execution_timeout_seconds=0.2
        )
        release_event = threading.Event()

        with pytest.raises(BackendExecutionUnresponsiveError):
            coordinator.run(self._hang_then_release, release_event, request_id="hung")
        # The old execution genuinely ends now.
        release_event.set()
        time.sleep(0.1)

        with pytest.raises(CoordinatorPoisonedError):
            coordinator.run(lambda: "nope", request_id="later")
        assert coordinator.health_state == "poisoned"

    def test_queue_timeout_does_not_poison_coordinator(self):
        """A QUEUE timeout (never acquired the permit) must leave the
        coordinator healthy — the permit is unowned and untouched."""
        coordinator = InferenceCoordinator(
            capacity=1, queue_timeout_seconds=0.2, backend_execution_timeout_seconds=2
        )
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

        assert coordinator.health_state == "healthy"
        assert coordinator.last_failure_category == "queue_timeout"

        # After the holder completes, the permit is reusable: the queue
        # timeout never consumed an unowned permit.
        release_holder.set()
        holder_thread.join(timeout=5)
        coordinator.run(lambda: "ok", request_id="after")
        assert coordinator.request_log[-1]["success"] is True


class TestDiagnosticsSafety:
    """Coordinator diagnostics must never carry raw payloads or secrets."""

    def test_request_records_contain_only_allowlisted_fields(self):
        coordinator = InferenceCoordinator(capacity=1, queue_timeout_seconds=2)

        secret_value = "hf_secret_payload_abc"
        raw_rows = [{"timestamp": "2024-01-01", "target": 123.45}]
        coordinator.run(
            lambda *a, **k: "ok", raw_rows, marker=secret_value, request_id="req_x",
        )
        allowed = {
            "request_id", "start_time_utc", "inference_start_utc",
            "completion_time_utc", "queue_seconds", "inference_seconds",
            "success", "error_code", "sync_mode",
        }
        for entry in coordinator.request_log:
            assert set(entry.keys()) == allowed, (
                f"unexpected fields in request record: {sorted(entry)}"
            )
            serialised = repr(entry)
            assert secret_value not in serialised
            assert "123.45" not in serialised

    def test_diagnostics_properties_never_expose_raw_args(self):
        coordinator = InferenceCoordinator(
            capacity=1, queue_timeout_seconds=2, backend_execution_timeout_seconds=5
        )
        coordinator.run(lambda: "ok", request_id="req_1")
        diagnostics = {
            "health_state": coordinator.health_state,
            "active_request_id": coordinator.active_request_id,
            "active_since_utc": coordinator.active_since_utc,
            "last_release_at_utc": coordinator.last_release_at_utc,
            "last_failure_category": coordinator.last_failure_category,
            "queue_depth": coordinator.queue_depth,
            "capacity": coordinator.capacity,
            "queue_timeout_seconds": coordinator.queue_timeout_seconds,
            "backend_execution_timeout_seconds": coordinator.backend_execution_timeout_seconds,
        }
        assert diagnostics["health_state"] == "healthy"
        assert diagnostics["last_failure_category"] == ""
        assert diagnostics["queue_depth"] == 0
        # No raw inputs, no user identity, no secrets are ever stored.
        serialised = repr(diagnostics)
        assert "hf_" not in serialised
        assert "123.45" not in serialised
