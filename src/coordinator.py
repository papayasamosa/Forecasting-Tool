"""Process-wide inference coordinator for concurrent request management.

Provides a bounded semaphore-based coordinator that serialises inference
access to the shared Chronos-2 backend while recording queue and inference
timestamps for concurrency evidence.

Usage:
    from src.coordinator import InferenceCoordinator

    coordinator = InferenceCoordinator(capacity=1, timeout_seconds=300)
    result = coordinator.run(backend.forecast, task)
"""

from __future__ import annotations

import threading
import time
from datetime import datetime, timezone
from typing import Any, Callable

# ---------------------------------------------------------------------------
# Defaults
# ---------------------------------------------------------------------------
DEFAULT_CAPACITY = 1
DEFAULT_TIMEOUT_SECONDS = 300


class CoordinatorTimeoutError(Exception):
    """Raised when the coordinator's semaphore acquire times out."""


class CoordinatorLockError(Exception):
    """Raised when the coordinator lock is not held for the release path."""


class InferenceCoordinator:
    """Process-wide inference coordinator with timed semaphore access.

    Design (WP10):
    - A bounded semaphore with configurable capacity (default 1) serialises
      access to the shared backend inference.
    - Queue-start and inference-start timestamps are recorded per request.
    - A configurable timeout prevents indefinite waiting.
    - The semaphore is always released in ``finally``.
    - ``st.cache_resource`` at the entry point ensures one coordinator per
      process (same as the model adapter).

    Thread safety: all internal state is protected by the semaphore itself
    and a lock on the request log.
    """

    def __init__(self, capacity: int = DEFAULT_CAPACITY, timeout_seconds: float = DEFAULT_TIMEOUT_SECONDS):
        if capacity < 1:
            raise ValueError(f"capacity must be >= 1, got {capacity}")
        if timeout_seconds <= 0:
            raise ValueError(f"timeout_seconds must be > 0, got {timeout_seconds}")
        self._capacity = capacity
        self._timeout_seconds = timeout_seconds
        self._semaphore = threading.BoundedSemaphore(capacity)
        self._request_log: list[dict[str, Any]] = []
        self._log_lock = threading.Lock()
        self._sync_mode = "semaphore"

    @property
    def capacity(self) -> int:
        return self._capacity

    @property
    def timeout_seconds(self) -> float:
        return self._timeout_seconds

    @property
    def sync_mode(self) -> str:
        return self._sync_mode

    @property
    def request_log(self) -> list[dict[str, Any]]:
        """Return a copy of the request log for evidence capture."""
        with self._log_lock:
            return list(self._request_log)

    def clear_log(self) -> None:
        """Clear the request log (e.g. between test scenarios)."""
        with self._log_lock:
            self._request_log.clear()

    def _record_request(self, entry: dict[str, Any]) -> None:
        """Thread-safe append to the request log."""
        with self._log_lock:
            self._request_log.append(entry)

    def run(
        self,
        fn: Callable[..., Any],
        *args: Any,
        request_id: str = "",
        **kwargs: Any,
    ) -> Any:
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
        Any
            The return value of ``fn(*args, **kwargs)``.

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
            self._record_request({
                "request_id": rid,
                "start_time_utc": queue_start.isoformat(),
                "inference_start_utc": "",
                "completion_time_utc": datetime.now(timezone.utc).isoformat(),
                "queue_seconds": self._timeout_seconds,
                "inference_seconds": 0.0,
                "success": False,
                "error_code": "CoordinatorTimeoutError",
                "sync_mode": self._sync_mode,
            })
            raise CoordinatorTimeoutError(
                f"Semaphore acquire timed out after {self._timeout_seconds}s"
            )

        inference_start = datetime.now(timezone.utc)
        queue_seconds = (inference_start - queue_start).total_seconds()

        try:
            result = fn(*args, **kwargs)
            completion_time = datetime.now(timezone.utc)
            inference_seconds = (completion_time - inference_start).total_seconds()
            self._record_request({
                "request_id": rid,
                "start_time_utc": queue_start.isoformat(),
                "inference_start_utc": inference_start.isoformat(),
                "completion_time_utc": completion_time.isoformat(),
                "queue_seconds": round(queue_seconds, 3),
                "inference_seconds": round(inference_seconds, 3),
                "success": True,
                "error_code": "",
                "sync_mode": self._sync_mode,
            })
            return result
        except Exception as exc:
            completion_time = datetime.now(timezone.utc)
            inference_seconds = (completion_time - inference_start).total_seconds()
            self._record_request({
                "request_id": rid,
                "start_time_utc": queue_start.isoformat(),
                "inference_start_utc": inference_start.isoformat(),
                "completion_time_utc": completion_time.isoformat(),
                "queue_seconds": round(queue_seconds, 3),
                "inference_seconds": round(inference_seconds, 3),
                "success": False,
                "error_code": type(exc).__name__,
                "sync_mode": self._sync_mode,
            })
            raise
        finally:
            self._semaphore.release()
