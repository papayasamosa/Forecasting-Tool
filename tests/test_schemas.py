"""Tests for canonical schemas and configuration.

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


class TestForecastTask:
    def test_defaults(self):
        task = ForecastTask()
        assert task.mode == ForecastMode.STANDARD_UNIVARIATE
        assert task.prediction_length == 13
        assert task.quantile_levels == (0.1, 0.5, 0.9)
        assert task.cross_learning is False

    def test_custom_values(self):
        task = ForecastTask(
            mode=ForecastMode.STANDARD_UNIVARIATE,
            prediction_length=24,
            quantile_levels=(0.05, 0.5, 0.95),
            frequency="D",
        )
        assert task.prediction_length == 24
        assert task.quantile_levels == (0.05, 0.5, 0.95)
        assert task.frequency == "D"

    def test_horizon_bounds(self):
        assert HORIZON_MIN >= 1
        assert HORIZON_MAX <= 1024


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

    def test_validation_report_blocking(self):
        report = ValidationReport(
            issues=(
                ValidationIssue(
                    severity=IssueSeverity.ERROR,
                    code="test_error",
                    message="Test error",
                ),
            ),
            is_blocking=True,
        )
        assert report.is_blocking is True
        assert len(report.errors) == 1
        assert len(report.warnings) == 0

    def test_validation_report_warning(self):
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
        assert meta.package_versions == {}
