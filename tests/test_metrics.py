"""Tests for error metrics — Phase 1 rolling-origin evaluation (Slice 9 core).

Covers ``src.metrics`` (MAE, RMSE, MASE, ``evaluate_fold``, seasonal-period
mapping).
"""
from __future__ import annotations

import numpy as np
import pytest

from src.metrics import (
    MetricsResult,
    evaluate_fold,
    mae,
    mase,
    rmse,
    seasonal_period_for_frequency,
)


class TestMae:
    def test_perfect_forecast_zero(self):
        assert mae([1.0, 2.0, 3.0], [1.0, 2.0, 3.0]) == 0.0

    def test_known_value(self):
        # errors: 1, 0, 1 -> mean 2/3
        assert mae([1.0, 2.0, 3.0], [2.0, 2.0, 2.0]) == pytest.approx(2.0 / 3.0)

    def test_length_mismatch_raises(self):
        with pytest.raises(ValueError, match="lengths differ"):
            mae([1.0, 2.0], [1.0])

    def test_empty_raises(self):
        with pytest.raises(ValueError, match="empty"):
            mae([], [])

    def test_nan_raises(self):
        with pytest.raises(ValueError, match="NaN"):
            mae([1.0, np.nan], [1.0, 1.0])


class TestRmse:
    def test_perfect_forecast_zero(self):
        assert rmse([1.0, 2.0], [1.0, 2.0]) == 0.0

    def test_known_value(self):
        # errors: 1, -1 -> sq mean 1 -> rmse 1
        assert rmse([1.0, 3.0], [2.0, 2.0]) == pytest.approx(1.0)

    def test_known_value_2(self):
        # errors: 0, 2 -> sq mean 2 -> rmse sqrt(2)
        assert rmse([1.0, 2.0], [1.0, 4.0]) == pytest.approx(np.sqrt(2.0))


class TestMase:
    def test_requires_scale_source(self):
        with pytest.raises(ValueError, match="naive_mae or training_series"):
            mase([1.0, 2.0], [1.0, 2.0])

    def test_with_naive_mae(self):
        # errors all 1.0 -> mae 1.0; scale 2.0 -> mase 0.5
        assert mase([0.0, 1.0], [1.0, 2.0], naive_mae=2.0) == pytest.approx(0.5)

    def test_with_training_series_one_step(self):
        # training [0,2,4,6] naive diffs 2,2,2 -> naive mae 2
        # actual [8,10], forecast [9,9] -> mae 1 -> mase 0.5
        assert mase(
            [8.0, 10.0], [9.0, 9.0], training_series=[0.0, 2.0, 4.0, 6.0]
        ) == pytest.approx(0.5)

    def test_with_seasonal_scaling(self):
        # seasonal period 2: diffs s[2:]-s[:-2] -> [4-0,6-2] -> 4,4 -> naive 4
        # actual [8,10] forecast [9,9] -> mae 1 -> mase 0.25
        assert mase(
            [8.0, 10.0], [9.0, 9.0],
            training_series=[0.0, 2.0, 4.0, 6.0],
            seasonal_period=2,
        ) == pytest.approx(0.25)

    def test_constant_series_returns_zero(self):
        # constant training -> naive mae 0 -> scaled error defined as 0
        assert mase(
            [1.0, 1.0], [1.5, 1.5], training_series=[2.0, 2.0, 2.0]
        ) == 0.0

    def test_too_short_training_raises(self):
        with pytest.raises(ValueError, match="at least 2 points"):
            mase([1.0], [1.0], training_series=[1.0])

    def test_negative_naive_mae_raises(self):
        with pytest.raises(ValueError, match="non-negative"):
            mase([1.0], [1.0], naive_mae=-1.0)


class TestEvaluateFold:
    def test_returns_typed_result(self):
        result = evaluate_fold(
            [1.0, 2.0, 3.0], [1.0, 2.0, 3.0], training_series=[1.0, 2.0, 3.0]
        )
        assert isinstance(result, MetricsResult)
        assert result.mae == 0.0
        assert result.rmse == 0.0
        assert result.mase == 0.0
        assert result.n == 3

    def test_without_training_uses_unit_scale(self):
        result = evaluate_fold([1.0, 2.0], [2.0, 3.0])
        assert result.mae == pytest.approx(1.0)
        assert result.mase == pytest.approx(1.0)  # naive_mae=1.0

    def test_seasonal_period_scaling(self):
        result = evaluate_fold(
            [8.0, 10.0],
            [9.0, 9.0],
            training_series=[0.0, 2.0, 4.0, 6.0],
            seasonal_period=2,
        )
        assert result.mase == pytest.approx(0.25)


class TestSeasonalPeriodForFrequency:
    def test_daily(self):
        assert seasonal_period_for_frequency("D") == 7

    def test_weekly(self):
        assert seasonal_period_for_frequency("W") == 52

    def test_monthly(self):
        assert seasonal_period_for_frequency("M") == 12

    def test_unknown(self):
        assert seasonal_period_for_frequency("Q") is None

    def test_empty(self):
        assert seasonal_period_for_frequency("") is None

