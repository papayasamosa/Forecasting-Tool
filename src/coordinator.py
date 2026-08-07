"""Process-wide inference coordinator for concurrent request management.

Provides a bounded semaphore-based coordinator that serialises inference
access to the shared Chronos-2 backend while recording queue and inference
timestamps for concurrency evidence.

Timeout semantics (explicitly separated — do not conflate these):

- ``queue_timeout_seconds`` — how long a *queued* request waits for the
  capacity permit.  When it expires the request raises
  ``CoordinatorTimeoutError``; it owns no permit and never touched the
  backend.
- ``backend_execution_timeout_seconds`` — the execution-liveness watchdog.
  A backend call that has not returned within this bound is presumed
  unresponsive; the coordinator **fails closed** (health state
  ``poisoned``) and the permit is **not** released, so no second request
  can ever enter a still-running shared pipeline.  Recovery requires a
  safe process/backend recycle.
- ``backend exception`` — a backend call that raises normally releases
  the permit (the execution genuinely ended) and the exception propagates.

Usage:
    from src.coordinator import InferenceCoordinator, CoordinatorExecution

    coordinator = InferenceCoordinator(capacity=1, queue_timeout_seconds=120)
    exec_record = coordinator.run(backend.forecast, task)
    result = exec_record.result
    queue_seconds = exec_record.request_record["queue_seconds"]
"""

from __future__ import annotations

import collections
import threading
import time
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Callable

# ---------------------------------------------------------------------------
# Defaults
# ---------------------------------------------------------------------------
DEFAULT_CAPACITY = 1
# 5 s queue timeout: justified by genuine measured Cloud durations (warm
# ~0.1-1 s, cold incl. model load ~6.4-8.7 s, max legitimate request ~8-9 s).
# See src/config.py COORDINATOR_QUEUE_TIMEOUT_SECONDS for the full rationale.
DEFAULT_QUEUE_TIMEOUT_SECONDS = 5
DEFAULT_BACKEND_EXECUTION_TIMEOUT_SECONDS = 900
DEFAULT_MAX_HISTORY = 256

# Health states
HEALTH_HEALTHY = "healthy"
HEALTH_POISONED = "poisoned"

# Failure categories recorded for diagnostics / telemetry.
FAILURE_CATEGORY_NONE = ""
FAILURE_CATEGORY_QUEUE_TIMEOUT = "queue_timeout"
FAILURE_CATEGORY_BACKEND_FAILURE = "backend_failure"
FAILURE_CATEGORY_BACKEND_UNRESPONSIVE = "backend_execution_unresponsive"


class CoordinatorTimeoutError(Exception):
    """Raised when the queue wait for the capacity permit times out.

    This is a *queue* timeout only: the request never acquired the permit
    and never touched the backend.
    """


class CoordinatorPoisonedError(Exception):
    """Raised when the coordinator is in the fail-closed ``poisoned`` state.

    An earlier backend execution was presumed unresponsive and the shared
    pipeline must not be reused.  New requests are refused until the
    application process is safely recycled.
    """


class BackendExecutionUnresponsiveError(Exception):
    """Raised when a backend execution exceeds the liveness watchdog.

    The coordinator transitions to ``poisoned`` and the capacity permit is
    deliberately **not** released — the unresponsive execution may still be
    using the shared pipeline.
    """


class CoordinatorLockError(Exception):
    """Raised when the coordinator lock is not held for the release path."""


@dataclass
class CoordinatorExecution:
    """Return type from ``InferenceCoordinator.run()``.

    Carries the forecast result together with the sanitised request record
    so callers never need to scan the coordinator's full history.
    """
    result: Any = None
    request_record: dict[str, Any] = field(default_factory=dict)


class InferenceCoordinator:
    """Process-wide inference coordinator with timed, fail-closed access.

    Design (WP1 + Stage A robustness closure):
    - A bounded semaphore with configurable capacity (default 1) serialises
      access to the shared backend inference.
    - Queue-start and inference-start timestamps are recorded per request.
    - ``queue_timeout_seconds`` bounds the wait for the permit.
    - After the permit is acquired the backend call runs under a
      **watchdog**: if it has not returned within
      ``backend_execution_timeout_seconds`` the coordinator enters the
      ``poisoned`` health state, the permit is **not** released (the old
      execution may still be running on the shared pipeline), and a
      ``BackendExecutionUnresponsiveError`` is raised to the caller.
    - While poisoned, every new request is refused immediately with
      ``CoordinatorPoisonedError`` — no second inference can ever enter a
      still-running shared backend.  Recovery requires a safe process /
      backend recycle (Streamlit Community Cloud reboot re-creates the
      process, the coordinator, and the pipeline).
    - The permit is released only on genuine completion (success or a
      backend exception that proves the execution ended).
    - Request history is held in a ``collections.deque(maxlen=N)`` so it
      never grows without bound.
    - ``run()`` returns a ``CoordinatorExecution`` with the result and the
      current request record — callers never scan the full history.
    - ``st.cache_resource`` at the entry point ensures one coordinator per
      process (same as the model adapter).

    Thread safety: all internal state is protected by the semaphore itself
    and dedicated locks on the request log and health/ownership state.
    """

    def __init__(
        self,
        capacity: int = DEFAULT_CAPACITY,
        queue_timeout_seconds: float = DEFAULT_QUEUE_TIMEOUT_SECONDS,
        backend_execution_timeout_seconds: float = DEFAULT_BACKEND_EXECUTION_TIMEOUT_SECONDS,
        max_history: int = DEFAULT_MAX_HISTORY,
        **kwargs: Any,
    ):
        # Backward-compatible alias: ``timeout_seconds=`` maps to the queue
        # timeout.  Accepted only as a keyword alias so existing call sites
        # keep working; new code should use ``queue_timeout_seconds``.
        if "timeout_seconds" in kwargs:
            if queue_timeout_seconds != DEFAULT_QUEUE_TIMEOUT_SECONDS:
                raise TypeError(
                    "timeout_seconds and queue_timeout_seconds are aliases; "
                    "specify only one"
                )
            queue_timeout_seconds = kwargs.pop("timeout_seconds")
        if kwargs:
            raise TypeError(f"unexpected keyword arguments: {sorted(kwargs)}")
        if capacity < 1:
            raise ValueError(f"capacity must be >= 1, got {capacity}")
        if queue_timeout_seconds <= 0:
            raise ValueError(f"queue_timeout_seconds must be > 0, got {queue_timeout_seconds}")
        if backend_execution_timeout_seconds <= 0:
            raise ValueError(
                f"backend_execution_timeout_seconds must be > 0, "
                f"got {backend_execution_timeout_seconds}"
            )
        if max_history < 1:
            raise ValueError(f"max_history must be >= 1, got {max_history}")
        self._capacity = capacity
        self._queue_timeout_seconds = float(queue_timeout_seconds)
        self._backend_execution_timeout_seconds = float(backend_execution_timeout_seconds)
        self._max_history = max_history
        self._semaphore = threading.BoundedSemaphore(capacity)
        self._request_log: collections.deque[dict[str, Any]] = collections.deque(maxlen=max_history)
        self._log_lock = threading.Lock()
        self._state_lock = threading.Lock()
        self._health_state = HEALTH_HEALTHY
        self._last_failure_category = FAILURE_CATEGORY_NONE
        self._active_request_id = ""
        self._active_since_utc = ""
        self._last_release_at_utc = ""
        self._queue_waiters = 0
        self._sync_mode = "semaphore"

    # ------------------------------------------------------------------
    # Read-only properties (safe diagnostics surface — never raw payloads)
    # ------------------------------------------------------------------
    @property
    def capacity(self) -> int:
        return self._capacity

    @property
    def queue_timeout_seconds(self) -> float:
        return self._queue_timeout_seconds

    @property
    def backend_execution_timeout_seconds(self) -> float:
        return self._backend_execution_timeout_seconds

    @property
    def timeout_seconds(self) -> float:
        """Deprecated alias for ``queue_timeout_seconds``."""
        return self._queue_timeout_seconds

    @property
    def max_history(self) -> int:
        return self._max_history

    @property
    def sync_mode(self) -> str:
        return self._sync_mode

    @property
    def health_state(self) -> str:
        """``healthy`` or ``poisoned`` (fail-closed after an unresponsive
        backend execution)."""
        with self._state_lock:
            return self._health_state

    @property
    def last_failure_category(self) -> str:
        """Most recent failure category (queue_timeout / backend_failure /
        backend_execution_unresponsive) or ``""`` when healthy."""
        with self._state_lock:
            return self._last_failure_category

    @property
    def active_request_id(self) -> str:
        """Request ID currently owning the permit (empty when idle)."""
        with self._state_lock:
            return self._active_request_id

    @property
    def active_since_utc(self) -> str:
        """UTC ISO timestamp when the current owner acquired the permit."""
        with self._state_lock:
            return self._active_since_utc

    @property
    def last_release_at_utc(self) -> str:
        """UTC ISO timestamp of the most recent genuine permit release."""
        with self._state_lock:
            return self._last_release_at_utc

    @property
    def queue_depth(self) -> int:
        """Approximate number of requests currently waiting for a permit."""
        with self._state_lock:
            return self._queue_waiters

    @property
    def request_log(self) -> list[dict[str, Any]]:
        """Return a copy of the request log for evidence capture."""
        with self._log_lock:
            return list(self._request_log)

    def get_request_record(self, request_id: str) -> dict[str, Any] | None:
        """O(1) lookup by request_id (scans at most max_history)."""
        with self._log_lock:
            for entry in self._request_log:
                if entry.get("request_id") == request_id:
                    return dict(entry)
            return None

    def clear_log(self) -> None:
        """Clear the request log (e.g. between test scenarios)."""
        with self._log_lock:
            self._request_log.clear()

    def _record_request(self, entry: dict[str, Any]) -> None:
        """Thread-safe append to the request log (bounded deque)."""
        with self._log_lock:
            self._request_log.append(entry)

    def _utcnow(self) -> datetime:
        return datetime.now(timezone.utc)

    def _set_active(self, request_id: str, since: datetime) -> None:
        with self._state_lock:
            self._active_request_id = request_id
            self._active_since_utc = since.isoformat()

    def _clear_active_and_release(self, at: datetime) -> None:
        """Record a genuine release: clear ownership and release the permit.

        Only called when the owned execution has genuinely completed
        (success or an exception raised by the backend call itself).  It is
        deliberately NOT called on watchdog timeout.
        """
        with self._state_lock:
            self._active_request_id = ""
            self._active_since_utc = ""
            self._last_release_at_utc = at.isoformat()
        self._semaphore.release()

    def run(
        self,
        fn: Callable[..., Any],
        *args: Any,
        request_id: str = "",
        **kwargs: Any,
    ) -> CoordinatorExecution:
        """Execute ``fn(*args, **kwargs)`` under the serialised permit.

        Parameters
        ----------
        fn : callable
            The inference function to execute (e.g. ``adapter.forecast``).
        *args : Any
            Positional arguments for ``fn``.
        request_id : str
            Optional identifier for the request (auto-generated if empty).
        **kwargs : Any
            Keyword arguments for ``fn``.

        Returns
        -------
        CoordinatorExecution
            Dataclass with ``result`` (the return value of ``fn``) and
            ``request_record`` (the sanitised telemetry for this request).

        Raises
        ------
        CoordinatorPoisonedError
            If the coordinator is already in the fail-closed poisoned state
            (refused without touching the permit or the backend).
        CoordinatorTimeoutError
            If the permit cannot be acquired within ``queue_timeout_seconds``.
        BackendExecutionUnresponsiveError
            If the owned backend execution exceeds the liveness watchdog;
            the coordinator enters the poisoned state and the permit is not
            released.
        Any exception raised by ``fn`` is propagated after releasing the
        permit (the execution genuinely ended).
        """
        rid = request_id or f"req_{int(time.time() * 1_000_000)}"
        queue_start = self._utcnow()

        # Fail-closed gate: never touch the permit or backend while poisoned.
        if self._health_state == HEALTH_POISONED:
            record = {
                "request_id": rid,
                "start_time_utc": queue_start.isoformat(),
                "inference_start_utc": "",
                "completion_time_utc": self._utcnow().isoformat(),
                "queue_seconds": 0.0,
                "inference_seconds": 0.0,
                "success": False,
                "error_code": "CoordinatorPoisonedError",
                "sync_mode": self._sync_mode,
            }
            self._record_request(record)
            raise CoordinatorPoisonedError(
                "The forecasting backend is in a fail-closed state after an "
                "unresponsive execution. Please reload the app; the service "
                "cannot accept new forecasts until the process is recycled."
            )

        # Queue wait (bounded by queue_timeout_seconds).
        with self._state_lock:
            self._queue_waiters += 1
        try:
            acquired = self._semaphore.acquire(
                blocking=True, timeout=self._queue_timeout_seconds
            )
        finally:
            with self._state_lock:
                self._queue_waiters -= 1

        if not acquired:
            record = {
                "request_id": rid,
                "start_time_utc": queue_start.isoformat(),
                "inference_start_utc": "",
                "completion_time_utc": self._utcnow().isoformat(),
                "queue_seconds": round(self._queue_timeout_seconds, 3),
                "inference_seconds": 0.0,
                "success": False,
                "error_code": "CoordinatorTimeoutError",
                "sync_mode": self._sync_mode,
            }
            self._record_request(record)
            with self._state_lock:
                self._last_failure_category = FAILURE_CATEGORY_QUEUE_TIMEOUT
            raise CoordinatorTimeoutError(
                f"Queue wait timed out after {self._queue_timeout_seconds}s"
            )

        inference_start = self._utcnow()
        queue_seconds = (inference_start - queue_start).total_seconds()
        self._set_active(rid, inference_start)

        # ------------------------------------------------------------------
        # Watchdog-monitored backend execution.
        #
        # The backend call runs on a worker thread so the coordinator can
        # observe whether it ever returns.  On watchdog expiry the
        # coordinator FAILS CLOSED: it does NOT release the permit (the old
        # execution may still be using the shared pipeline) and it refuses
        # every subsequent request until the process is recycled.  This is
        # the safe alternative to an unkillable fake timeout: no second
        # inference can ever enter a still-running shared backend.
        # ------------------------------------------------------------------
        done = threading.Event()
        outcome: dict[str, Any] = {}

        def _worker() -> None:
            try:
                outcome["result"] = fn(*args, **kwargs)
            except BaseException as exc:  # noqa: BLE001 - re-raised by run()
                outcome["error"] = exc
            finally:
                done.set()

        worker = threading.Thread(
            target=_worker,
            name=f"coordinator-{rid[-12:]}",
            daemon=True,
        )
        worker.start()
        finished = done.wait(timeout=self._backend_execution_timeout_seconds)

        completion = self._utcnow()
        inference_seconds = (completion - inference_start).total_seconds()

        if not finished:
            # Unresponsive execution: fail closed.  The permit is retained
            # (never released) so the shared pipeline cannot be reused while
            # the old execution may still be running.
            record = {
                "request_id": rid,
                "start_time_utc": queue_start.isoformat(),
                "inference_start_utc": inference_start.isoformat(),
                "completion_time_utc": completion.isoformat(),
                "queue_seconds": round(queue_seconds, 3),
                "inference_seconds": round(inference_seconds, 3),
                "success": False,
                "error_code": "BackendExecutionUnresponsiveError",
                "sync_mode": self._sync_mode,
            }
            self._record_request(record)
            with self._state_lock:
                self._health_state = HEALTH_POISONED
                self._last_failure_category = FAILURE_CATEGORY_BACKEND_UNRESPONSIVE
            # NOTE: ``_active_request_id`` is deliberately left set — the
            # owner may still be running and the permit is not reusable.
            raise BackendExecutionUnresponsiveError(
                f"Backend execution did not return within "
                f"{self._backend_execution_timeout_seconds}s and is presumed "
                "unresponsive. The service has failed closed and cannot accept "
                "new forecasts until the application process is recycled."
            )

        # Genuine completion: the execution has ended; the permit is safe to
        # release and ownership is cleared.
        self._clear_active_and_release(completion)

        if "error" in outcome:
            exc = outcome["error"]
            record = {
                "request_id": rid,
                "start_time_utc": queue_start.isoformat(),
                "inference_start_utc": inference_start.isoformat(),
                "completion_time_utc": completion.isoformat(),
                "queue_seconds": round(queue_seconds, 3),
                "inference_seconds": round(inference_seconds, 3),
                "success": False,
                "error_code": type(exc).__name__,
                "sync_mode": self._sync_mode,
            }
            self._record_request(record)
            with self._state_lock:
                self._last_failure_category = FAILURE_CATEGORY_BACKEND_FAILURE
            raise exc

        result = outcome["result"]
        record = {
            "request_id": rid,
            "start_time_utc": queue_start.isoformat(),
            "inference_start_utc": inference_start.isoformat(),
            "completion_time_utc": completion.isoformat(),
            "queue_seconds": round(queue_seconds, 3),
            "inference_seconds": round(inference_seconds, 3),
            "success": True,
            "error_code": "",
            "sync_mode": self._sync_mode,
        }
        self._record_request(record)
        return CoordinatorExecution(result=result, request_record=record)
