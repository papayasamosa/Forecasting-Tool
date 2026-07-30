"""Process-wide inference coordinator for concurrent request management.

Provides a bounded semaphore-based coordinator that serialises inference
access to the shared Chronos-2 backend while recording queue and inference
timestamps for concurrency evidence.

Usage:
    from src.coordinator import InferenceCoordinator, CoordinatorExecution

    coordinator = InferenceCoordinator(capacity=1, timeout_seconds=300)
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
DEFAULT_TIMEOUT_SECONDS = 300
DEFAULT_MAX_HISTORY = 256


class CoordinatorTimeoutError(Exception):
    """Raised when the coordinator's semaphore acquire times out."""


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
    """Process-wide inference coordinator with timed semaphore access.

    Design (WP1):
    - A bounded semaphore with configurable capacity (default 1) serialises
      access to the shared backend inference.
    - Queue-start and inference-start timestamps are recorded per request.
    - A configurable timeout prevents indefinite waiting.
    - The semaphore is always released in ``finally``.
    - Request history is held in a ``collections.deque(maxlen=N)`` so it
      never grows without bound.
    - ``run()`` returns a ``CoordinatorExecution`` with the result and the
      current request record — callers never scan the full history.
    - ``st.cache_resource`` at the entry point ensures one coordinator per
      process (same as the model adapter).

    Thread safety: all internal state is protected by the semaphore itself
    and a lock on the request log.
    """

    def __init__(
        self,
        capacity: int = DEFAULT_CAPACITY,
        timeout_seconds: float = DEFAULT_TIMEOUT_SECONDS,
        max_history: int = DEFAULT_MAX_HISTORY,
    ):
        if capacity < 1:
            raise ValueError(f"capacity must be >= 1, got {capacity}")
        if timeout_seconds <= 0:
            raise ValueError(f"timeout_seconds must be > 0, got {timeout_seconds}")
        if max_history < 1:
            raise ValueError(f"max_history must be >= 1, got {max_history}")
        self._capacity = capacity
        self._timeout_seconds = timeout_seconds
        self._max_history = max_history
        self._semaphore = threading.BoundedSemaphore(capacity)
        self._request_log: collections.deque[dict[str, Any]] = collections.deque(maxlen=max_history)
        self._log_lock = threading.Lock()
        self._sync_mode = "semaphore"

    @property
    def capacity(self) -> int:
        return self._capacity

    @property
    def timeout_seconds(self) -> float:
        return self._timeout_seconds

    @property
    def max_history(self) -> int:
        return self._max_history

    @property
    def sync_mode(self) -> str:
        return self._sync_mode

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

    def run(
        self,
        fn: Callable[..., Any],
        *args: Any,
        request_id: str = "",
        **kwargs: Any,
    ) -> CoordinatorExecution:
        """Execute ``fn(*args, **kwargs)`` under the semaphore.

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
            Named tuple with ``result`` (the return value of ``fn``) and
            ``request_record`` (the sanitised telemetry for this request).

        Raises
        ------
        CoordinatorTimeoutError
            If the semaphore cannot be acquired within ``timeout_seconds``.
        Any exception raised by ``fn`` is propagated after releasing the
        semaphore.
        """
        rid = request_id or f"req_{int(time.time() * 1_000_000)}"
        queue_start = datetime.now(timezone.utc)

        # Acquire the semaphore with timeout
        acquired = self._semaphore.acquire(blocking=True, timeout=self._timeout_seconds)
        if not acquired:
            record = {
                "request_id": rid,
                "start_time_utc": queue_start.isoformat(),
                "inference_start_utc": "",
                "completion_time_utc": datetime.now(timezone.utc).isoformat(),
                "queue_seconds": self._timeout_seconds,
                "inference_seconds": 0.0,
                "success": False,
                "error_code": "CoordinatorTimeoutError",
                "sync_mode": self._sync_mode,
            }
            self._record_request(record)
            raise CoordinatorTimeoutError(
                f"Semaphore acquire timed out after {self._timeout_seconds}s"
            )

        inference_start = datetime.now(timezone.utc)
        queue_seconds = (inference_start - queue_start).total_seconds()

        try:
            result = fn(*args, **kwargs)
            completion_time = datetime.now(timezone.utc)
            inference_seconds = (completion_time - inference_start).total_seconds()
            record = {
                "request_id": rid,
                "start_time_utc": queue_start.isoformat(),
                "inference_start_utc": inference_start.isoformat(),
                "completion_time_utc": completion_time.isoformat(),
                "queue_seconds": round(queue_seconds, 3),
                "inference_seconds": round(inference_seconds, 3),
                "success": True,
                "error_code": "",
                "sync_mode": self._sync_mode,
            }
            self._record_request(record)
            return CoordinatorExecution(result=result, request_record=record)
        except Exception as exc:
            completion_time = datetime.now(timezone.utc)
            inference_seconds = (completion_time - inference_start).total_seconds()
            record = {
                "request_id": rid,
                "start_time_utc": queue_start.isoformat(),
                "inference_start_utc": inference_start.isoformat(),
                "completion_time_utc": completion_time.isoformat(),
                "queue_seconds": round(queue_seconds, 3),
                "inference_seconds": round(inference_seconds, 3),
                "success": False,
                "error_code": type(exc).__name__,
                "sync_mode": self._sync_mode,
            }
            self._record_request(record)
            raise
        finally:
            self._semaphore.release()
