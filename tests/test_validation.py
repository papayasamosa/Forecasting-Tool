"""Tests for validation logic — Phase 1 ingestion/validation slice.

Covers the typed data-quality checks in ``src.validation`` (duplicate
timestamps with remediation guidance, missing target values, short history,
zero/near-zero series, IQR outliers, irregular dates, frequency inference)
and the ``validate_prepared_dataframe`` orchestration.
"""
from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from src.schemas import ErrorCode, IssueSeverity, WarningCode
from src.validation import (
    detect_duplicate_timestamps,
    detect_irregular_dates,
    detect_missing_target_values,
    detect_outliers,
    detect_short_history,
    detect_zero_or_near_zero,
    infer_frequency,
    normalize_frequency_alias,
    validate_prepared_dataframe,
)


# ---------------------------------------------------------------------------
# Fixtures / helpers
# ---------------------------------------------------------------------------


def _prepared_df(rows: int = 20, *, freq: str = "W", seed: int = 42) -> pd.DataFrame:
    rng = np.random.default_rng(seed=seed)
    dates = pd.date_range("2024-01-01", periods=rows, freq=freq)
    return pd.DataFrame(
        {"timestamp": dates, "target": 100 + rng.normal(0, 5, size=rows)}
    )


def _with_duplicates(df: pd.DataFrame) -> pd.DataFrame:
    out = df.copy()
    dup = out.iloc[[2]].copy()
    return pd.concat([out, dup], ignore_index=True).sort_values("timestamp").reset_index(drop=True)


def _first_error(report) -> dict:
    issues = report.errors if hasattr(report, "errors") else report
    assert issues, "expected at least one error"
    return issues[0]


def _first_warning(report) -> dict:
    issues = report.warnings if hasattr(report, "warnings") else report
    assert issues, "expected at least one warning"
    return issues[0]


# ---------------------------------------------------------------------------
# Duplicate timestamps
# ---------------------------------------------------------------------------


class TestDetectDuplicateTimestamps:
    def test_clean_series_no_issues(self):
        df = _prepared_df()
        assert detect_duplicate_timestamps(df) == []

    def test_duplicates_blocking_with_guidance(self):
        df = _with_duplicates(_prepared_df())
        issues = detect_duplicate_timestamps(df)
        assert len(issues) == 1
        issue = issues[0]
        assert issue.severity == IssueSeverity.ERROR
        assert issue.code == ErrorCode.DUPLICATE_TIMESTAMPS.value
        assert issue.field == "timestamp"
        assert "duplicate" in issue.message.lower()
        # Remediation guidance must be present (Phase 1 contract).
        assert "aggregate" in issue.message.lower() or "re-upload" in issue.message.lower()
        # The duplicated value must be named.
        dup_value = str(df.loc[df["timestamp"].duplicated(keep=False), "timestamp"].iloc[0])
        assert dup_value in issue.message

    def test_missing_column_returns_empty(self):
        df = _prepared_df().drop(columns=["timestamp"])
        assert detect_duplicate_timestamps(df) == []

    def test_all_nat_returns_empty(self):
        df = pd.DataFrame({"timestamp": pd.to_datetime([None, None]), "target": [1.0, 2.0]})
        assert detect_duplicate_timestamps(df) == []

    def test_message_bounded_for_many_duplicates(self):
        df = pd.DataFrame(
            {"timestamp": pd.to_datetime(["2024-01-01"] * 8 + ["2024-01-08"] * 3),
             "target": list(range(11))}
        )
        issues = detect_duplicate_timestamps(df)
        assert len(issues) == 1
        # 11 duplicate rows across 2 distinct timestamps.
        assert "11 duplicate" in issues[0].message
        assert "2 distinct" in issues[0].message


# ---------------------------------------------------------------------------
# Missing target values
# ---------------------------------------------------------------------------


class TestDetectMissingTargetValues:
    def test_no_missing_returns_empty(self):
        df = _prepared_df()
        assert detect_missing_target_values(df) == []

    def test_all_missing_is_blocking(self):
        df = _prepared_df()
        df["target"] = np.nan
        issues = detect_missing_target_values(df)
        assert len(issues) == 1
        issue = issues[0]
        assert issue.severity == IssueSeverity.ERROR
        assert issue.code == ErrorCode.MISSING_TARGET_VALUES.value
        assert "no valid values" in issue.message

    def test_partial_missing_is_warning(self):
        df = _prepared_df()
        df.loc[3, "target"] = np.nan
        issues = detect_missing_target_values(df)
        assert len(issues) == 1
        issue = issues[0]
        assert issue.severity == IssueSeverity.WARNING
        assert issue.code == WarningCode.MISSING_TARGET_VALUES.value
        assert "1 missing" in issue.message

    def test_missing_column_returns_empty(self):
        df = _prepared_df().drop(columns=["target"])
        assert detect_missing_target_values(df) == []

    def test_empty_df_returns_empty(self):
        assert detect_missing_target_values(pd.DataFrame({"target": []})) == []


# ---------------------------------------------------------------------------
# Short history
# ---------------------------------------------------------------------------


class TestDetectShortHistory:
    def test_adequate_history_no_issue(self):
        assert detect_short_history(20) == []

    def test_short_history_warns(self):
        issues = detect_short_history(5)
        assert len(issues) == 1
        issue = issues[0]
        assert issue.severity == IssueSeverity.WARNING
        assert issue.code == WarningCode.SHORT_HISTORY.value
        assert "5" in issue.message

    def test_min_override(self):
        assert detect_short_history(15, min_history_rows=20) != []
        assert detect_short_history(15, min_history_rows=10) == []

    def test_disabled_threshold(self):
        assert detect_short_history(0, min_history_rows=0) == []


# ---------------------------------------------------------------------------
# Zero / near-zero series
# ---------------------------------------------------------------------------


class TestDetectZeroOrNearZero:
    def test_varying_series_no_issue(self):
        df = _prepared_df()
        assert detect_zero_or_near_zero(df) == []

    def test_constant_series_warns(self):
        df = _prepared_df()
        df["target"] = 42.0
        issues = detect_zero_or_near_zero(df)
        assert len(issues) == 1
        issue = issues[0]
        assert issue.severity == IssueSeverity.WARNING
        assert issue.code == WarningCode.ZERO_OR_NEAR_ZERO.value
        assert "constant" in issue.message.lower()

    def test_near_zero_spread_warns(self):
        df = _prepared_df()
        df["target"] = 1e-12 + np.zeros(len(df))
        assert detect_zero_or_near_zero(df) != []

    def test_empty_target_no_issue(self):
        df = _prepared_df()
        df["target"] = np.nan
        assert detect_zero_or_near_zero(df) == []

    def test_missing_column_no_issue(self):
        df = _prepared_df().drop(columns=["target"])
        assert detect_zero_or_near_zero(df) == []


# ---------------------------------------------------------------------------
# Outliers
# ---------------------------------------------------------------------------


class TestDetectOutliers:
    def test_no_outliers_no_issue(self):
        df = _prepared_df()
        assert detect_outliers(df) == []

    def test_outlier_warns(self):
        df = _prepared_df(rows=30)
        df.loc[0, "target"] = 1000.0  # clearly beyond 3*IQR
        issues = detect_outliers(df)
        assert len(issues) == 1
        issue = issues[0]
        assert issue.severity == IssueSeverity.WARNING
        assert issue.code == WarningCode.OUTLIERS_DETECTED.value
        assert "1 value" in issue.message

    def test_too_few_rows_no_issue(self):
        df = _prepared_df(rows=3)
        assert detect_outliers(df) == []

    def test_flat_series_no_issue(self):
        df = _prepared_df()
        df["target"] = 1.0
        assert detect_outliers(df) == []

    def test_missing_column_no_issue(self):
        df = _prepared_df().drop(columns=["target"])
        assert detect_outliers(df) == []


# ---------------------------------------------------------------------------
# Irregular dates
# ---------------------------------------------------------------------------


class TestDetectIrregularDates:
    def test_regular_dates_no_issue(self):
        df = _prepared_df(freq="D")
        assert detect_irregular_dates(df) == []

    def test_big_gap_warns(self):
        df = _prepared_df(rows=8, freq="D")
        # Insert a 30-day gap: duplicate the 4th row date shifted +30d.
        gap_row = df.iloc[[3]].copy()
        gap_row["timestamp"] = gap_row["timestamp"] + pd.Timedelta(days=30)
        df = pd.concat([df, gap_row], ignore_index=True).sort_values("timestamp").reset_index(drop=True)
        issues = detect_irregular_dates(df)
        assert len(issues) == 1
        issue = issues[0]
        assert issue.severity == IssueSeverity.WARNING
        assert issue.code == WarningCode.IRREGULAR_DATES.value
        assert "irregular" in issue.message.lower()

    def test_fewer_than_three_rows_no_issue(self):
        df = _prepared_df(rows=2)
        assert detect_irregular_dates(df) == []

    def test_non_datetime_no_issue(self):
        df = pd.DataFrame({"timestamp": ["a", "b", "c"], "target": [1, 2, 3]})
        assert detect_irregular_dates(df) == []

    def test_identical_dates_no_issue_here(self):
        # All-identical dates are the duplicates check's authority.
        df = pd.DataFrame(
            {"timestamp": pd.to_datetime(["2024-01-01"] * 5), "target": list(range(5))}
        )
        assert detect_irregular_dates(df) == []


# ---------------------------------------------------------------------------
# Frequency inference
# ---------------------------------------------------------------------------


class TestInferFrequency:
    def test_daily(self):
        df = _prepared_df(freq="D")
        assert infer_frequency(df) == "D"

    def test_weekly(self):
        df = _prepared_df(freq="W")
        assert infer_frequency(df) == "W"

    def test_monthly_normalised(self):
        # pandas 3.x uses 'ME' (month-end); infer_frequency normalises to 'M'.
        df = _prepared_df(freq="ME")
        assert infer_frequency(df) == "M"

    def test_irregular_returns_empty(self):
        df = _prepared_df(rows=8, freq="D")
        gap_row = df.iloc[[3]].copy()
        gap_row["timestamp"] = gap_row["timestamp"] + pd.Timedelta(days=30)
        df = pd.concat([df, gap_row], ignore_index=True).sort_values("timestamp").reset_index(drop=True)
        assert infer_frequency(df) == ""

    def test_too_few_rows_returns_empty(self):
        df = _prepared_df(rows=1)
        assert infer_frequency(df) == ""

    def test_non_datetime_returns_empty(self):
        df = pd.DataFrame({"timestamp": ["a", "b"], "target": [1, 2]})
        assert infer_frequency(df) == ""

    def test_missing_column_returns_empty(self):
        df = _prepared_df().drop(columns=["timestamp"])
        assert infer_frequency(df) == ""


class TestNormalizeFrequencyAlias:
    def test_weekly_anchored(self):
        assert normalize_frequency_alias("W-SUN") == "W"
        assert normalize_frequency_alias("W-MON") == "W"

    def test_monthly(self):
        assert normalize_frequency_alias("ME") == "M"
        assert normalize_frequency_alias("M") == "M"

    def test_daily_passthrough(self):
        assert normalize_frequency_alias("D") == "D"

    def test_empty_passthrough(self):
        assert normalize_frequency_alias("") == ""


# ---------------------------------------------------------------------------
# Orchestration
# ---------------------------------------------------------------------------


class TestValidatePreparedDataframe:
    def test_clean_data_not_blocking(self):
        df = _prepared_df()
        report = validate_prepared_dataframe(df)
        assert report.is_blocking is False
        assert report.errors == []
        assert report.warnings == []

    def test_duplicates_blocking(self):
        df = _with_duplicates(_prepared_df())
        report = validate_prepared_dataframe(df)
        assert report.is_blocking is True
        issue = _first_error(report)
        assert issue.code == ErrorCode.DUPLICATE_TIMESTAMPS.value

    def test_all_missing_target_blocking(self):
        df = _prepared_df()
        df["target"] = np.nan
        report = validate_prepared_dataframe(df)
        assert report.is_blocking is True
        issue = _first_error(report)
        assert issue.code == ErrorCode.MISSING_TARGET_VALUES.value

    def test_short_history_warns_not_blocking(self):
        df = _prepared_df(rows=5)
        report = validate_prepared_dataframe(df)
        assert report.is_blocking is False
        assert any(
            i.code == WarningCode.SHORT_HISTORY.value for i in report.warnings
        )

    def test_original_rows_respected_for_short_history(self):
        # Even when only a capped subset is passed, the original row count
        # must be used for the short-history check.
        df = _prepared_df(rows=20)
        report = validate_prepared_dataframe(
            df.iloc[-5:].reset_index(drop=True), original_rows=20
        )
        assert not any(
            i.code == WarningCode.SHORT_HISTORY.value for i in report.warnings
        )

    def test_constant_series_warns(self):
        df = _prepared_df()
        df["target"] = 7.0
        report = validate_prepared_dataframe(df)
        assert any(
            i.code == WarningCode.ZERO_OR_NEAR_ZERO.value for i in report.warnings
        )

    def test_custom_mapping_respected(self):
        df = _prepared_df().rename(columns={"timestamp": "ts", "target": "val"})
        from src.data_ingestion import ColumnMapping

        report = validate_prepared_dataframe(
            df, ColumnMapping(timestamp="ts", target="val")
        )
        assert report.is_blocking is False

