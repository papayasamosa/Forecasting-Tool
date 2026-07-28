"""Centralised application configuration.

Defaults are defined here per PRD requirements.
"""
from __future__ import annotations

from typing import ClassVar

# ---------------------------------------------------------------------------
# Model
# ---------------------------------------------------------------------------
MODEL_ID: str = "amazon/chronos-2"

# Hugging Face revision/commit pinned for this model. "main" is a placeholder
# until the Stage 0 measured-evidence run resolves and records an exact
# snapshot commit to pin (see docs/stage_0_benchmark_report.md).
MODEL_REVISION: str = "main"

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
