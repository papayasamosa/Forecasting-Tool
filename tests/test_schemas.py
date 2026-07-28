"""Tests for canonical schemas, configuration, and invariant validation.

These tests do NOT require the Chronos model to load.
"""
from __future__ import annotations

import pytest

from src.schemas import (
    ForecastMode,
    ForecastTask,
    ForecastResult,
    ValidationIssue,
    ValidationReport,
    IssueSeverity,
    RunMetadata,
    new_run_id,
)
from src.config import (
    MODEL_ID,
    DEFAULT_QUANTILES,
    HORIZON_MIN,
    HORIZON_MAX,
    QUANTILE_MIN,
    QUANTILE_MAX,
)


class TestForecastTaskDefaults:
    def test_defaults(self):
        task = ForecastTask(
            historical_data=({"timestamp": "2024-01-01", "target": 1.0},),
            target_columns=("target",),
        )
        assert task.mode == ForecastMode.STANDARD_UNIVARIATE
        assert task.prediction_length == 13
        assert task.quantile_levels == (0.1, 0.5, 0.9)
        assert task.cross_learning is False

    def test_custom_values(self):
        task = ForecastTask(
            mode=ForecastMode.STANDARD_UNIVARIATE,
            historical_data=({"timestamp": "2024-01-01", "target": 1.0},),
            target_columns=("target",),
            prediction_length=24,
            quantile_levels=(0.05, 0.5, 0.95),
            frequency="D",
        )
        assert task.prediction_length == 24
        assert task.quantile_levels == (0.05, 0.5, 0.95)

    def test_horizon_bounds(self):
        assert HORIZON_MIN >= 1
        assert HORIZON_MAX <= 1024


class TestForecastTaskValidation:
    """Construction-time invariant validation (__post_init__)."""

    def test_empty_data_rejected(self):
        with pytest.raises(ValueError, match="must not be empty"):
            ForecastTask()

    def test_empty_target_rejected(self):
        with pytest.raises(ValueError, match="must not be empty"):
            ForecastTask(
                historical_data=({"timestamp": "2024-01-01", "target": 1.0},),
                target_columns=(),
            )

    def test_zero_horizon_rejected(self):
        with pytest.raises(ValueError, match="prediction_length"):
            ForecastTask(
                historical_data=({"timestamp": "2024-01-01", "target": 1.0},),
                target_columns=("target",),
                prediction_length=0,
            )

    def test_negative_horizon_rejected(self):
        with pytest.raises(ValueError, match="prediction_length"):
            ForecastTask(
                historical_data=({"timestamp": "2024-01-01", "target": 1.0},),
                target_columns=("target",),
                prediction_length=-5,
            )

    def test_overcap_horizon_rejected(self):
        with pytest.raises(ValueError, match="prediction_length"):
            ForecastTask(
                historical_data=({"timestamp": "2024-01-01", "target": 1.0},),
                target_columns=("target",),
                prediction_length=99999,
            )

    def test_empty_quantiles_rejected(self):
        with pytest.raises(ValueError, match="quantile_levels"):
            ForecastTask(
                historical_data=({"timestamp": "2024-01-01", "target": 1.0},),
                target_columns=("target",),
                quantile_levels=(),
            )

    def test_quantile_out_of_range(self):
        with pytest.raises(ValueError, match="Quantile"):
            ForecastTask(
                historical_data=({"timestamp": "2024-01-01", "target": 1.0},),
                target_columns=("target",),
                quantile_levels=(-0.1, 0.5),
            )
        with pytest.raises(ValueError, match="Quantile"):
            ForecastTask(
                historical_data=({"timestamp": "2024-01-01", "target": 1.0},),
                target_columns=("target",),
                quantile_levels=(0.5, 1.0),
            )

    def test_duplicate_quantiles_rejected(self):
        with pytest.raises(ValueError, match="Duplicate quantile"):
            ForecastTask(
                historical_data=({"timestamp": "2024-01-01", "target": 1.0},),
                target_columns=("target",),
                quantile_levels=(0.5, 0.5),
            )

    def test_negative_context_cap_rejected(self):
        with pytest.raises(ValueError, match="context_window_cap"):
            ForecastTask(
                historical_data=({"timestamp": "2024-01-01", "target": 1.0},),
                target_columns=("target",),
                context_window_cap=-1,
            )

    def test_cross_learning_rejected(self):
        with pytest.raises(ValueError, match="cross_learning"):
            ForecastTask(
                historical_data=({"timestamp": "2024-01-01", "target": 1.0},),
                target_columns=("target",),
                cross_learning=True,
            )

    def test_multiple_targets_in_univariate_rejected(self):
        with pytest.raises(ValueError, match="exactly one target"):
            ForecastTask(
                historical_data=({"timestamp": "2024-01-01", "target": 1.0},),
                target_columns=("target1", "target2"),
            )

    def test_quantile_levels_canonicalized_sorted(self):
        task = ForecastTask(
            historical_data=({"timestamp": "2024-01-01", "target": 1.0},),
            target_columns=("target",),
            quantile_levels=(0.9, 0.1, 0.5),
        )
        assert task.quantile_levels == (0.1, 0.5, 0.9)

    def test_quantile_boundary_values_accepted(self):
        task = ForecastTask(
            historical_data=({"timestamp": "2024-01-01", "target": 1.0},),
            target_columns=("target",),
            quantile_levels=(QUANTILE_MIN, QUANTILE_MAX),
        )
        assert task.quantile_levels == (QUANTILE_MIN, QUANTILE_MAX)

    def test_quantile_just_outside_boundary_rejected(self):
        with pytest.raises(ValueError, match="Quantile"):
            ForecastTask(
                historical_data=({"timestamp": "2024-01-01", "target": 1.0},),
                target_columns=("target",),
                quantile_levels=(QUANTILE_MIN - 0.001, 0.5),
            )
        with pytest.raises(ValueError, match="Quantile"):
            ForecastTask(
                historical_data=({"timestamp": "2024-01-01", "target": 1.0},),
                target_columns=("target",),
                quantile_levels=(0.5, QUANTILE_MAX + 0.001),
            )


class TestForecastResult:
    def test_minimal(self):
        result = ForecastResult()
        assert result.run_id == ""
        assert result.forecast_rows == ()
        assert result.model_id == ""

    def test_with_rows(self):
        result = ForecastResult(
            run_id="test123",
            forecast_rows=(
                {"run_id": "test123", "timestamp": "2024-01-01", "point_prediction": 100.0},
            ),
            model_id=MODEL_ID,
            quantile_levels=(0.1, 0.5, 0.9),
        )
        assert result.run_id == "test123"
        assert len(result.forecast_rows) == 1


class TestValidation:
    def test_validation_issue(self):
        issue = ValidationIssue(
            severity=IssueSeverity.ERROR,
            code="missing_timestamps",
            message="Timestamps are missing.",
            field="timestamp",
        )
        assert issue.severity == IssueSeverity.ERROR
        assert issue.code == "missing_timestamps"

    def test_blocking_derived_from_errors(self):
        report = ValidationReport(
            issues=(
                ValidationIssue(
                    severity=IssueSeverity.ERROR,
                    code="test_error",
                    message="Test error",
                ),
            ),
        )
        assert report.is_blocking is True
        assert len(report.errors) == 1
        assert len(report.warnings) == 0

    def test_non_blocking_warning(self):
        report = ValidationReport(
            issues=(
                ValidationIssue(
                    severity=IssueSeverity.WARNING,
                    code="short_history",
                    message="Short history",
                ),
            ),
        )
        assert report.is_blocking is False
        assert len(report.warnings) == 1
        assert len(report.errors) == 0


class TestConfig:
    def test_default_quantiles(self):
        assert DEFAULT_QUANTILES == [0.1, 0.5, 0.9]

    def test_model_id(self):
        assert MODEL_ID == "amazon/chronos-2"

    def test_quantile_bounds(self):
        assert QUANTILE_MIN < QUANTILE_MAX


class TestNewRunId:
    def test_unique(self):
        ids = {new_run_id() for _ in range(100)}
        assert len(ids) == 100

    def test_length(self):
        rid = new_run_id()
        assert len(rid) == 12


class TestRunMetadata:
    def test_defaults(self):
        meta = RunMetadata()
        assert meta.run_id == ""
