"""Tests for baseline forecast models — Phase 1 Slice 8.

Covers ``src.baselines`` (last-value persistence and seasonal naive).
"""
from __future__ import annotations

import numpy as np
import pytest

from src.baselines import (
    baseline_predict_fn,
    forecast_baseline,
    last_value_forecast,
    seasonal_naive_eligible,
    seasonal_naive_forecast,
)
from src.schemas import BaselineModel


class TestLastValueForecast:
    def test_repeats_last_value(self):
        pred = last_value_forecast([1.0, 2.0, 3.0], 4)
        assert list(pred) == [3.0, 3.0, 3.0, 3.0]

    def test_horizon_one(self):
        assert list(last_value_forecast([5.0], 1)) == [5.0]

    def test_invalid_horizon_raises(self):
        with pytest.raises(ValueError, match="horizon"):
            last_value_forecast([1.0], 0)

    def test_empty_series_raises(self):
        with pytest.raises(ValueError, match="empty"):
            last_value_forecast([], 3)


class TestSeasonalNaive:
    def test_eligibility(self):
        assert seasonal_naive_eligible([1.0] * 6, 3) is True
        assert seasonal_naive_eligible([1.0] * 5, 3) is False
        assert seasonal_naive_eligible([1.0] * 6, 0) is False

    def test_forecast_repeats_season(self):
        pred = seasonal_naive_forecast([1.0, 2.0, 3.0, 4.0, 5.0, 6.0], 4, period=3)
        assert list(pred) == [4.0, 5.0, 6.0, 4.0]

    def test_forecast_multi_cycle(self):
        # v=[1..6], period=3, horizon=5 -> repeats cycle [4,5,6,4,5]
        pred = seasonal_naive_forecast(
            [1.0, 2.0, 3.0, 4.0, 5.0, 6.0], 5, period=3
        )
        assert list(pred) == [4.0, 5.0, 6.0, 4.0, 5.0]

    def test_ineligible_raises(self):
        with pytest.raises(ValueError, match="ineligible"):
            seasonal_naive_forecast([1.0, 2.0, 3.0], 3, period=3)

    def test_invalid_horizon_raises(self):
        with pytest.raises(ValueError, match="horizon"):
            seasonal_naive_forecast([1.0] * 6, 0, period=3)


class TestForecastBaseline:
    def test_last_value_dispatch(self):
        pred = forecast_baseline([1.0, 2.0, 3.0], 2, BaselineModel.LAST_VALUE)
        assert list(pred) == [3.0, 3.0]

    def test_seasonal_naive_dispatch(self):
        pred = forecast_baseline(
            [1.0, 2.0, 3.0, 4.0, 5.0, 6.0], 2, BaselineModel.SEASONAL_NAIVE, period=3
        )
        assert list(pred) == [4.0, 5.0]

    def test_seasonal_naive_requires_period(self):
        with pytest.raises(ValueError, match="seasonal period"):
            forecast_baseline(
                [1.0] * 6, 2, BaselineModel.SEASONAL_NAIVE, period=None
            )

    def test_unsupported_model_raises(self):
        with pytest.raises(ValueError, match="unsupported baseline"):
            forecast_baseline([1.0], 1, "bogus_model")


class TestBaselinePredictFn:
    def test_last_value_predict_fn(self):
        fn = baseline_predict_fn(BaselineModel.LAST_VALUE)
        assert list(fn([1.0, 2.0, 9.0], 3)) == [9.0, 9.0, 9.0]

    def test_seasonal_naive_predict_fn(self):
        fn = baseline_predict_fn(BaselineModel.SEASONAL_NAIVE, period=3)
        assert list(fn([1.0, 2.0, 3.0, 4.0, 5.0, 6.0], 3)) == [4.0, 5.0, 6.0]

    def test_predict_fn_returns_numpy(self):
        fn = baseline_predict_fn(BaselineModel.LAST_VALUE)
        out = fn([1.0, 2.0], 2)
        assert isinstance(out, np.ndarray)

