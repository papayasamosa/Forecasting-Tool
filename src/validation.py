"""Validation utilities for the Phase 1 ingestion/validation slice.

Produces typed ``ValidationReport`` objects (see ``src.schemas``) covering the
data-quality checks required before a univariate forecast:

* duplicate timestamps — blocking (ERROR) with detailed remediation guidance
  (this is the Phase 1 "duplicate-timestamp remediation" referenced by
  ``docs/community_cloud_test_checklist.md``: Stage 0 only raised a generic
  error, Phase 1 tells the user *which* timestamps collide and how to fix
  them);
* missing target values — blocking when *all* are missing, advisory otherwise;
* short history — advisory (``WarningCode.SHORT_HISTORY``);
* zero-or-near-zero target series — advisory (``WarningCode.ZERO_OR_NEAR_ZERO``);
* outliers — advisory (``WarningCode.OUTLIERS_DETECTED``, IQR-based);
* irregular dates / unreliable frequency inference — advisory
  (``WarningCode.IRREGULAR_DATES``);
* ``infer_frequency`` — pandas frequency inference helper reused by the
  forecast task builder, backtesting and baselines.

The validators assume the DataFrame has already been structurally prepared
(timestamp column parsed to datetime and sorted, columns present) — i.e. they
run on the output of ``data_ingestion.prepare_dataframe``.  Structural errors
(columns missing, timestamps unparseable) are raised by ``prepare_dataframe``
and converted to typed issues by ``data_ingestion.run_ingestion_pipeline``.
"""
from __future__ import annotations

from typing import TYPE_CHECKING, Iterable

import pandas as pd

from src.config import (
    IRREGULAR_DATE_TOLERANCE_MULTIPLIER,
    MIN_HISTORY_ROWS,
    OUTLIER_IQR_MULTIPLIER,
    ZERO_VARIANCE_EPS,
)
from src.schemas import (
    ErrorCode,
    IssueSeverity,
    ValidationIssue,
    ValidationReport,
    WarningCode,
)

if TYPE_CHECKING:  # pragma: no cover - import-time only, avoids circular import
    from src.data_ingestion import ColumnMapping


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------


def _issue(
    severity: IssueSeverity,
    code: str,
    message: str,
    field: str | None = None,
) -> ValidationIssue:
    return ValidationIssue(
        severity=severity,
        code=code,
        message=message,
        field=field,
    )


def _target_series(df: pd.DataFrame, target_col: str) -> pd.Series:
    """Numeric-coerced target column, NaN dropped."""
    return pd.to_numeric(df[target_col], errors="coerce").dropna()


# ---------------------------------------------------------------------------
# Individual checks
# ---------------------------------------------------------------------------


def detect_duplicate_timestamps(
    df: pd.DataFrame,
    ts_col: str = "timestamp",
    *,
    max_values_in_message: int = 5,
) -> list[ValidationIssue]:
    """Blocking check for duplicate timestamps with remediation guidance.

    Returns an ERROR issue (``ErrorCode.DUPLICATE_TIMESTAMPS``) listing the
    duplicated values (bounded) and concrete remediation options.  Empty list
    when every timestamp is unique.
    """
    if ts_col not in df.columns or df[ts_col].isna().all():
        return []

    dup_mask = df[ts_col].duplicated(keep=False)
    dup_count = int(dup_mask.sum())
    if dup_count == 0:
        return []

    counts = df.loc[dup_mask, ts_col].value_counts()
    total_duplicated = int(counts.sum())
    shown = list(counts.head(max_values_in_message).items())
    detail = ", ".join(
        f"{value} ({n}×)" for value, n in shown
    )
    if len(counts) > len(shown):
        detail += f", … ({len(counts) - len(shown)} more values)"

    message = (
        f"The timestamp column '{ts_col}' contains {total_duplicated} duplicate "
        f"row(s) across {len(counts)} distinct timestamp(s): {detail}. "
        "A univariate series needs one value per timestamp. Resolve the "
        "duplicates (aggregate to a single value per timestamp, drop the "
        "duplicate rows, or use a finer-grained timestamp) and re-upload."
    )
    return [
        _issue(
            IssueSeverity.ERROR,
            ErrorCode.DUPLICATE_TIMESTAMPS.value,
            message,
            field=ts_col,
        )
    ]


def detect_missing_target_values(
    df: pd.DataFrame,
    target_col: str = "target",
) -> list[ValidationIssue]:
    """Blocking when every target value is missing, advisory otherwise."""
    if target_col not in df.columns:
        return []
    total = len(df)
    if total == 0:
        return []
    missing = int(df[target_col].isna().sum())
    if missing == 0:
        return []

    if missing == total:
        message = (
            f"The target column '{target_col}' has no valid values "
            f"({missing} of {total} rows are missing or blank). Provide "
            "numeric values for the target before forecasting."
        )
        return [
            _issue(
                IssueSeverity.ERROR,
                ErrorCode.MISSING_TARGET_VALUES.value,
                message,
                field=target_col,
            )
        ]

    pct = 100.0 * missing / total
    message = (
        f"The target column '{target_col}' has {missing} missing value(s) "
        f"out of {total} rows ({pct:.1f}%). Missing target values are not "
        "supported by the model; fill or remove them before forecasting."
    )
    return [
        _issue(
            IssueSeverity.WARNING,
            WarningCode.MISSING_TARGET_VALUES.value,
            message,
            field=target_col,
        )
    ]


def detect_short_history(
    row_count: int,
    *,
    min_history_rows: int | None = None,
) -> list[ValidationIssue]:
    """Advisory check for very short series."""
    minimum = MIN_HISTORY_ROWS if min_history_rows is None else min_history_rows
    if minimum <= 0 or row_count >= minimum:
        return []
    message = (
        f"The series has only {row_count} row(s), fewer than the recommended "
        f"{minimum}. Short histories typically produce unreliable forecasts."
    )
    return [
        _issue(
            IssueSeverity.WARNING,
            WarningCode.SHORT_HISTORY.value,
            message,
            field="timestamp",
        )
    ]


def detect_zero_or_near_zero(
    df: pd.DataFrame,
    target_col: str = "target",
) -> list[ValidationIssue]:
    """Advisory check for a constant / flat target series."""
    if target_col not in df.columns:
        return []
    col = _target_series(df, target_col)
    if len(col) == 0:
        return []
    spread = float(col.max() - col.min())
    if abs(spread) >= ZERO_VARIANCE_EPS:
        return []
    message = (
        f"The target column '{target_col}' is (near-)constant "
        f"(value range ~{spread:.3g}). A constant series cannot support a "
        "meaningful forecast."
    )
    return [
        _issue(
            IssueSeverity.WARNING,
            WarningCode.ZERO_OR_NEAR_ZERO.value,
            message,
            field=target_col,
        )
    ]


def detect_outliers(
    df: pd.DataFrame,
    target_col: str = "target",
    *,
    max_values_in_message: int = 5,
) -> list[ValidationIssue]:
    """Advisory IQR-based outlier detection (never blocks)."""
    if target_col not in df.columns:
        return []
    col = _target_series(df, target_col)
    if len(col) < 4:
        return []
    q1 = float(col.quantile(0.25))
    q3 = float(col.quantile(0.75))
    iqr = q3 - q1
    if iqr == 0:
        # Flat series is handled by detect_zero_or_near_zero.
        return []
    lower = q1 - OUTLIER_IQR_MULTIPLIER * iqr
    upper = q3 + OUTLIER_IQR_MULTIPLIER * iqr
    outliers = col[(col < lower) | (col > upper)]
    if len(outliers) == 0:
        return []
    shown_values = list(outliers.head(max_values_in_message))
    shown = ", ".join(f"{v:.3g}" for v in shown_values)
    if len(outliers) > len(shown_values):
        shown += ", …"
    message = (
        f"The target column '{target_col}' has {len(outliers)} value(s) "
        f"beyond the {OUTLIER_IQR_MULTIPLIER:.0f}×IQR range "
        f"[{lower:.3g}, {upper:.3g}]: {shown}. Outliers can distort "
        "forecasts; review them before proceeding."
    )
    return [
        _issue(
            IssueSeverity.WARNING,
            WarningCode.OUTLIERS_DETECTED.value,
            message,
            field=target_col,
        )
    ]


def detect_irregular_dates(
    df: pd.DataFrame,
    ts_col: str = "timestamp",
) -> list[ValidationIssue]:
    """Advisory check for irregular spacing in the (sorted) timestamp column."""
    if ts_col not in df.columns or len(df) < 3:
        return []
    ts = df[ts_col]
    if not pd.api.types.is_datetime64_any_dtype(ts.dtype):
        return []
    diffs = ts.diff().dropna()
    if len(diffs) == 0:
        return []
    median = diffs.median()
    if median is pd.NaT or median.total_seconds() == 0:
        # Zero or missing median spacing (e.g. all identical dates) — the
        # duplicates check is the authority for that case.
        return []
    tol = pd.Timedelta(seconds=median.total_seconds() * IRREGULAR_DATE_TOLERANCE_MULTIPLIER)
    irregular = diffs[diffs > tol]
    if len(irregular) == 0:
        return []
    largest = irregular.max()
    message = (
        f"The timestamp column '{ts_col}' has {len(irregular)} gap(s) larger "
        f"than {IRREGULAR_DATE_TOLERANCE_MULTIPLIER:.0f}× the median spacing "
        f"(largest gap {largest}). Dates are irregular, so frequency "
        "inference and seasonal baselines may be unreliable."
    )
    return [
        _issue(
            IssueSeverity.WARNING,
            WarningCode.IRREGULAR_DATES.value,
            message,
            field=ts_col,
        )
    ]


# ---------------------------------------------------------------------------
# Frequency inference
# ---------------------------------------------------------------------------


def normalize_frequency_alias(freq: str) -> str:
    """Map anchored pandas offsets to the base aliases used by
    ``src.config.SEASONAL_PERIODS`` (``D``/``W``/``M``).

    pandas 2.x returns anchored offsets from ``pd.infer_freq`` for weekly
    ranges (``W-SUN``) and month-end offsets (``ME``); normalising keeps the
    ``frequency`` metadata stable and directly usable as a
    ``SEASONAL_PERIODS`` key.  Unrecognised/empty input passes through.
    """
    if not freq:
        return ""
    if freq.startswith("W-"):
        return "W"
    if freq.startswith("M") or freq.startswith("ME"):
        return "M"
    return freq


def infer_frequency(df: pd.DataFrame, ts_col: str = "timestamp") -> str:
    """Infer a pandas frequency string from the timestamp column.

    Returns ``""`` when the frequency cannot be inferred (irregular dates,
    too few points, non-datetime column).  Mirrors the pattern used by
    ``src/benchmarking.py``, and normalises anchored offsets to the base
    aliases (``D``/``W``/``M``) via ``normalize_frequency_alias``.
    """
    if ts_col not in df.columns or len(df) < 2:
        return ""
    ts = df[ts_col]
    if not pd.api.types.is_datetime64_any_dtype(ts.dtype):
        return ""
    inferred = pd.infer_freq(ts)
    if not isinstance(inferred, str):
        return ""
    return normalize_frequency_alias(inferred)


# ---------------------------------------------------------------------------
# Orchestration
# ---------------------------------------------------------------------------


def validate_prepared_dataframe(
    df: pd.DataFrame,
    mapping: ColumnMapping | None = None,
    *,
    original_rows: int | None = None,
    min_history_rows: int | None = None,
) -> ValidationReport:
    """Run all data-quality checks on a prepared DataFrame.

    Parameters
    ----------
    df : pd.DataFrame
        Prepared data (timestamp datetime & sorted, target numeric-ready).
        See ``data_ingestion.prepare_dataframe``.
    mapping : ColumnMapping or None
        Column mapping; defaults to literal ``timestamp``/``target``.
    original_rows : int or None
        Row count before context capping (used for the short-history check so
        a capped series isn't falsely flagged); defaults to ``len(df)``.
    min_history_rows : int or None
        Override for the short-history threshold.

    Returns
    -------
    ValidationReport
        Typed issues; ``is_blocking`` True when any ERROR is present.
    """
    ts_col = mapping.timestamp if mapping is not None else "timestamp"
    target_col = mapping.target if mapping is not None else "target"

    issues: list[ValidationIssue] = []
    issues.extend(detect_duplicate_timestamps(df, ts_col))
    issues.extend(detect_missing_target_values(df, target_col))
    issues.extend(
        detect_short_history(
            len(df) if original_rows is None else original_rows,
            min_history_rows=min_history_rows,
        )
    )
    issues.extend(detect_zero_or_near_zero(df, target_col))
    issues.extend(detect_outliers(df, target_col))
    issues.extend(detect_irregular_dates(df, ts_col))

    return ValidationReport(issues=tuple(issues))


__all__: Iterable[str] = (
    "detect_duplicate_timestamps",
    "detect_missing_target_values",
    "detect_short_history",
    "detect_zero_or_near_zero",
    "detect_outliers",
    "detect_irregular_dates",
    "normalize_frequency_alias",
    "infer_frequency",
    "validate_prepared_dataframe",
)

