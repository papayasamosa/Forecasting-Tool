"""Canonical schemas for ForecastTask, ForecastResult, and supporting types.

These typed dataclasses are the internal contract between all layers of the
application.  No UI-dataframe objects should cross module boundaries.
"""
from __future__ import annotations

import dataclasses
import uuid
from datetime import datetime
from enum import Enum
from typing import Any


# ──────────────────────────────────────────────────────────────────────
# Enums / constrained values
# ──────────────────────────────────────────────────────────────────────

class ForecastMode(str, Enum):
    STANDARD_UNIVARIATE = "standard_univariate"
    # Future phases will add: MULTIVARIATE, COVARIATE_AWARE, CROSS_LEARNING, etc.


class IssueSeverity(str, Enum):
    ERROR = "error"          # Blocks the forecast
    WARNING = "warning"      # Non-blocking advisory


class BaselineModel(str, Enum):
    LAST_VALUE = "last_value"
    SEASONAL_NAIVE = "seasonal_naive"


class SourceType(str, Enum):
    ACTUAL = "actual"
    FORECAST = "forecast"


class WarningCode(str, Enum):
    SHORT_HISTORY = "short_history"
    MISSING_TARGET_VALUES = "missing_target_values"
    OUTLIERS_DETECTED = "outliers_detected"
    IRREGULAR_DATES = "irregular_dates"
    CONTEXT_TRUNCATION = "context_truncation"
    ZERO_OR_NEAR_ZERO = "zero_or_near_zero"
    FEW_FOLDS = "few_folds"
    SEASONAL_NAIVE_INELIGIBLE = "seasonal_naive_ineligible"


class ErrorCode(str, Enum):
    """Blocking (ERROR-severity) validation codes.

    These are raised by the Phase 1 ingestion/validation slice for inputs
    that cannot be safely forecast and must be corrected by the user.
    """
    DUPLICATE_TIMESTAMPS = "duplicate_timestamps"
    INVALID_TIMESTAMPS = "invalid_timestamps"
    MISSING_TIMESTAMPS = "missing_timestamps"
    MISSING_TARGET_VALUES = "missing_target_values"
    EMPTY_DATA = "empty_data"


# ──────────────────────────────────────────────────────────────────────
# Validation types
# ──────────────────────────────────────────────────────────────────────

@dataclasses.dataclass(frozen=True)
class ValidationIssue:
    severity: IssueSeverity
    code: str
    message: str
    field: str | None = None


@dataclasses.dataclass(frozen=True)
class ValidationReport:
    issues: tuple[ValidationIssue, ...] = ()

    @property
    def is_blocking(self) -> bool:
        """Derived from presence of ERROR-severity issues."""
        return len(self.errors) > 0

    @property
    def errors(self) -> list[ValidationIssue]:
        return [i for i in self.issues if i.severity == IssueSeverity.ERROR]

    @property
    def warnings(self) -> list[ValidationIssue]:
        return [i for i in self.issues if i.severity == IssueSeverity.WARNING]


# ──────────────────────────────────────────────────────────────────────
# Core forecast objects
# ──────────────────────────────────────────────────────────────────────

@dataclasses.dataclass(frozen=True)
class ForecastTask:
    """Everything the forecasting backend needs to produce a prediction.

    Raises ``ValueError`` at construction if invariants are violated.
    """
    mode: ForecastMode = ForecastMode.STANDARD_UNIVARIATE

    # Canonical long-format data (after validation & normalisation)
    # Columns: timestamp (sorted), target (float), optionally item_id
    historical_data: tuple[dict[str, Any], ...] = ()  # list of row-dicts

    # Optional future-known data (covariates in later phases)
    future_data: tuple[dict[str, Any], ...] = ()

    # Column mapping (canonical names after ingestion mapping)
    timestamp_column: str = "timestamp"
    item_id_column: str = "item_id"
    target_columns: tuple[str, ...] = ("target",)

    # Covariate roles (reserved for later phases)
    covariate_roles: dict[str, str] = dataclasses.field(default_factory=dict)

    # Frequency string inferred or overridden (pandas offset alias)
    frequency: str = ""

    # Forecast horizon
    prediction_length: int = 13

    # Quantile levels requested
    quantile_levels: tuple[float, ...] = (0.1, 0.5, 0.9)

    # Context window cap
    context_window_cap: int | None = None

    # Cross-learning flag (off in Phase 1)
    cross_learning: bool = False

    # Batch size for cross-learning / joint prediction
    batch_size: int | None = None

    def __post_init__(self) -> None:
        """Validate task invariants at construction time."""
        from src.config import (
            HORIZON_MIN,
            HORIZON_MAX,
            CONTEXT_WINDOW_CAP,
            QUANTILE_MIN,
            QUANTILE_MAX,
        )

        if not isinstance(self.mode, ForecastMode):
            raise ValueError(
                f"Unsupported mode '{self.mode}'. "
                f"Valid modes: {[m.value for m in ForecastMode]}"
            )
        if not self.historical_data:
            raise ValueError("historical_data must not be empty")
        if not self.target_columns:
            raise ValueError("target_columns must not be empty")
        if self.mode == ForecastMode.STANDARD_UNIVARIATE and len(self.target_columns) > 1:
            raise ValueError(
                "Standard univariate mode supports exactly one target column, "
                f"got {len(self.target_columns)}"
            )
        if self.prediction_length < HORIZON_MIN or self.prediction_length > HORIZON_MAX:
            raise ValueError(
                f"prediction_length must be between {HORIZON_MIN} and {HORIZON_MAX}, "
                f"got {self.prediction_length}"
            )
        if not self.quantile_levels:
            raise ValueError("quantile_levels must not be empty")
        seen = set()
        for q in self.quantile_levels:
            if q < QUANTILE_MIN or q > QUANTILE_MAX:
                raise ValueError(
                    f"Quantile must be in [{QUANTILE_MIN}, {QUANTILE_MAX}], got {q}"
                )
            rounded = round(q, 6)
            if rounded in seen:
                raise ValueError(f"Duplicate quantile level: {q}")
            seen.add(rounded)
        # Canonicalize to ascending order so downstream code (adapter output
        # construction, monotonicity checks) never depends on caller-supplied
        # ordering.
        object.__setattr__(self, "quantile_levels", tuple(sorted(self.quantile_levels)))
        if self.context_window_cap is not None and self.context_window_cap <= 0:
            raise ValueError(
                f"context_window_cap must be positive, got {self.context_window_cap}"
            )
        if self.context_window_cap is not None and self.context_window_cap > CONTEXT_WINDOW_CAP:
            raise ValueError(
                f"context_window_cap exceeds maximum of {CONTEXT_WINDOW_CAP}"
            )
        if self.cross_learning:
            raise ValueError(
                "cross_learning is not supported in Stage 0 / Phase 1"
            )


@dataclasses.dataclass(frozen=True)
class RunMetadata:
    """Metadata captured from a completed forecast run."""
    run_id: str = ""
    run_timestamp: str = ""
    model_id: str = ""
    model_revision: str = ""
    forecast_mode: str = ""
    resolved_frequency: str = ""
    prediction_length: int = 0
    quantile_levels: tuple[float, ...] = ()
    context_rows_used: int = 0
    # Computed in Phase 1 Slice 4 (see tests/test_fingerprinting.py); always
    # "" in Stage 0.
    data_fingerprint: str = ""
    warnings: tuple[str, ...] = ()
    runtime_seconds: float = 0.0  # Deprecated: kept for backward compat
    # Preprocessing metadata — populated before record materialisation so
    # that large datasets are capped before Python dict expansion (P0-1).
    preprocessing_original_rows: int = 0
    preprocessing_retained_rows: int = 0
    preprocessing_retained_start: str = ""  # ISO date of first retained row
    preprocessing_date_range_start: str = ""  # ISO date of earliest original row
    preprocessing_date_range_end: str = ""  # ISO date of latest original row
    model_load_seconds: float = 0.0
    inference_seconds: float = 0.0
    result_conversion_seconds: float = 0.0
    total_runtime_seconds: float = 0.0
    model_was_loaded_this_run: bool = False
    pipeline_reused: bool = False
    package_versions: dict[str, str] = dataclasses.field(default_factory=dict)
    backend_name: str = ""


@dataclasses.dataclass(frozen=True)
class ForecastResult:
    """Canonical forecast output in long format.

    Each row in ``forecast_rows`` has at least:

        run_id | item_id | timestamp | target_name | point_prediction
        | quantile_<level> ...

    ``source_type`` is always ``forecast``.
    """
    run_id: str = ""
    forecast_rows: tuple[dict[str, Any], ...] = ()
    model_id: str = ""
    model_revision: str = ""
    point_prediction_name: str = "predictions"
    quantile_levels: tuple[float, ...] = ()
    runtime_metadata: RunMetadata = dataclasses.field(default_factory=RunMetadata)
    warnings: tuple[str, ...] = ()
    backend_name: str = ""


# ──────────────────────────────────────────────────────────────────────
# Backtesting types
# ──────────────────────────────────────────────────────────────────────

@dataclasses.dataclass(frozen=True)
class BacktestConfiguration:
    num_folds: int = 5
    expanding_window: bool = True
    non_overlapping: bool = True
    backtest_horizon: int | None = None  # defaults to prediction_length


@dataclasses.dataclass(frozen=True)
class BacktestFold:
    fold_id: int
    cutoff: Any  # timestamp of the cut-off
    horizon_steps: tuple[int, ...] = ()


@dataclasses.dataclass(frozen=True)
class BacktestResult:
    folds: tuple[BacktestFold, ...] = ()
    fold_results: tuple[ForecastResult, ...] = ()
    fold_predictions: tuple[dict[str, Any], ...] = ()  # long-format scored obs
    configuration: BacktestConfiguration = dataclasses.field(
        default_factory=BacktestConfiguration
    )


def new_run_id() -> str:
    """Return a short unique run identifier."""
    return uuid.uuid4().hex[:12]
