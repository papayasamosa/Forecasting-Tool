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
    is_blocking: bool = False

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
    """Everything the forecasting backend needs to produce a prediction."""
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
    data_fingerprint: str = ""
    warnings: tuple[str, ...] = ()
    runtime_seconds: float = 0.0
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
