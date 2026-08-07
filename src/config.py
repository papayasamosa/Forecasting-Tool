"""Centralised application configuration.

Defaults are defined here per PRD requirements.
"""
from __future__ import annotations

from typing import ClassVar

# ---------------------------------------------------------------------------
# Model
# ---------------------------------------------------------------------------
MODEL_ID: str = "amazon/chronos-2"

# Hugging Face revision/commit pinned for this model.  This is a concrete,
# immutable snapshot SHA recorded by the Stage 0 measured-evidence run (see
# docs/stage_0_benchmark_report.md) — it is NOT a "main" placeholder.
MODEL_REVISION: str = "29ec3766d36d6f73f0696f85560a422f50e8498c"

# ---------------------------------------------------------------------------
# Forecast defaults
# ---------------------------------------------------------------------------
DEFAULT_QUANTILES: list[float] = [0.1, 0.5, 0.9]
DEFAULT_FOLDS: int = 5
DEFAULT_EXPANDING_WINDOW: bool = True
DEFAULT_NON_OVERLAPPING_STEP: bool = True

# ---------------------------------------------------------------------------
# Upload constraints
# ---------------------------------------------------------------------------
MAX_UPLOAD_SIZE_MB: int = 50
MAX_UPLOAD_SIZE_BYTES: int = 50 * 1024 * 1024

# ---------------------------------------------------------------------------
# Mode defaults
# ---------------------------------------------------------------------------
DEFAULT_MODE: str = "standard_univariate"
CROSS_LEARNING: bool = False

# ---------------------------------------------------------------------------
# Timing (seconds)
# ---------------------------------------------------------------------------
MODEL_LOAD_TIMEOUT: int = 300

# ---------------------------------------------------------------------------
# Inference coordinator (process-wide semaphore serialising forecast calls)
# ---------------------------------------------------------------------------
COORDINATOR_CAPACITY: int = 1

# Queue timeout: how long a request waits for the capacity-1 permit before
# the coordinator raises CoordinatorTimeoutError.  The request never touches
# the backend while queued.  Justified by genuine measured Cloud durations
# (docs/evidence/cloud_gate_c/): cold forecast ~7-9 s (model load 6.9-8.7 s),
# warm forecast ~0.06-0.09 s.  120 s is comfortably above legitimate cold
# execution (~13x the measured cold duration) while avoiding the previous
# five-minute silent wait.  This is a QUEUE timeout, not an execution bound.
COORDINATOR_QUEUE_TIMEOUT_SECONDS: int = 120

# Backend execution-liveness watchdog: if backend.forecast() has not returned
# within this bound it is presumed unresponsive; the coordinator fails closed
# (poisoned) and the capacity permit is NOT reused, so no second inference
# can enter a still-running shared pipeline.  Generous to accommodate the
# first-run model download/load on Community Cloud while still bounding a
# genuine hang.  Recovery requires a safe process/backend recycle.
COORDINATOR_BACKEND_EXECUTION_TIMEOUT_SECONDS: int = 900

# Deprecated alias kept for backward compatibility (maps to the queue
# timeout).  New code should use COORDINATOR_QUEUE_TIMEOUT_SECONDS.
COORDINATOR_TIMEOUT_SECONDS: int = COORDINATOR_QUEUE_TIMEOUT_SECONDS

# ---------------------------------------------------------------------------
# Supported quantile range
# ---------------------------------------------------------------------------
QUANTILE_MIN: float = 0.01
QUANTILE_MAX: float = 0.99

# ---------------------------------------------------------------------------
# Horizon constraints
# ---------------------------------------------------------------------------
HORIZON_MIN: int = 1
# Chronos-2 max prediction length is 1024 for the 120M model
HORIZON_MAX: int = 1024

# ---------------------------------------------------------------------------
# Context cap
# ---------------------------------------------------------------------------
# Chronos-2 supports up to 8192 context length for the 120M variant
CONTEXT_WINDOW_CAP: int = 8192

# ---------------------------------------------------------------------------
# Seasonality defaults for seasonal naive baseline
# ---------------------------------------------------------------------------
SEASONAL_PERIODS: ClassVar[dict[str, int]] = {
    "D": 7,   # daily -> weekly
    "W": 52,  # weekly -> annual
    "M": 12,  # monthly -> annual
}
