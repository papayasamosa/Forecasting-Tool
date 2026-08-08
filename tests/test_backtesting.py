"""Tests for rolling-origin backtesting — Phase 1 Slice 7.

Covers ``src.backtesting`` (fold construction and ``run_backtest``) using
deterministic predictors — no model weights are involved.
"""
from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from src.backtesting import (
    build_backtest_folds,
    run_backtest,
    validate_backtest_parameters,
)
from src.schemas import BacktestConfiguration, BacktestFold, BacktestResult


def _series(n: int = 60, seed: int = 11) -> tuple[np.ndarray, list]:
    rng = np.random.default_rng(seed=seed)
    values = 100 + np.arange(n) * 0.5 + rng.normal(0, 1.0, size=n)
    timestamps = list(pd.date_range("2024-01-01", periods=n, freq="D"))
    return values, timestamps


class TestValidateBacktestParameters:
    def test_valid(self):
        assert validate_backtest_parameters(
            num_folds=5, prediction_length=13, series_length=100
        ) == []

    def test_num_folds_below_one(self):
        errors = validate_backtest_parameters(
            num_folds=0, prediction_length=13, series_length=100
        )
        assert any("num_folds" in e for e in errors)

    def test_horizon_below_one(self):
        errors = validate_backtest_parameters(
            num_folds=2, prediction_length=13, series_length=100, backtest_horizon=0
        )
        assert any("backtest_horizon" in e for e in errors)

    def test_series_too_short(self):
        errors = validate_backtest_parameters(
            num_folds=2, prediction_length=20, series_length=10
        )
        assert any("too short" in e for e in errors)

    def test_series_single_point(self):
        errors = validate_backtest_parameters(
            num_folds=1, prediction_length=1, series_length=1
        )
        assert errors


class TestBuildBacktestFolds:
    def test_non_overlapping_cutoffs(self):
        timestamps = list(range(100))
        folds = build_backtest_folds(
            timestamps,
            num_folds=5,
            prediction_length=13,
            non_overlapping=True,
        )
        assert len(folds) == 5
        assert [f.fold_id for f in folds] == [0, 1, 2, 3, 4]
        # last cutoff at 86, stepping back by 13
        assert [f.cutoff for f in folds] == [34, 47, 60, 73, 86]
        assert all(f.horizon_steps == tuple(range(1, 14)) for f in folds)

    def test_overlapping_cutoffs(self):
        timestamps = list(range(100))
        folds = build_backtest_folds(
            timestamps,
            num_folds=5,
            prediction_length=13,
            non_overlapping=False,
        )
        assert [f.cutoff for f in folds] == [82, 83, 84, 85, 86]

    def test_custom_horizon(self):
        timestamps = list(range(100))
        folds = build_backtest_folds(
            timestamps,
            num_folds=3,
            prediction_length=13,
            backtest_horizon=7,
        )
        assert [f.cutoff for f in folds] == [78, 85, 92]
        assert all(f.horizon_steps == tuple(range(1, 8)) for f in folds)

    def test_returns_typed_folds(self):
        folds = build_backtest_folds(
            list(range(100)), num_folds=2, prediction_length=5
        )
        assert all(isinstance(f, BacktestFold) for f in folds)

    def test_insufficient_data_raises(self):
        with pytest.raises(ValueError, match="cannot support"):
            build_backtest_folds(
                list(range(10)), num_folds=5, prediction_length=5
            )


class TestRunBacktest:
    def test_perfect_linear_predictor_zero_error(self):
        values, timestamps = _series(60, seed=1)
        # A perfectly aligned linear continuation predictor.
        def perfect(train, horizon):
            return train[-1] + np.arange(1, horizon + 1)

        # Use a pure linear series so predictions are exact.
        v = np.arange(60, dtype=float)
        result = run_backtest(
            v, list(range(60)), perfect,
            num_folds=3, prediction_length=5,
        )
        assert isinstance(result, BacktestResult)
        assert len(result.folds) == 3
        assert len(result.fold_results) == 3
        assert len(result.fold_predictions) == 3 * 5
        for rec in result.fold_predictions:
            assert rec["actual"] == pytest.approx(rec["predicted"])
        assert result.configuration.num_folds == 3
        assert result.configuration.expanding_window is True
        assert result.configuration.non_overlapping is True

    def test_last_value_predictor(self):
        values, timestamps = _series(60)
        result = run_backtest(
            values, timestamps, lambda train, h: np.full(h, float(train[-1])),
            num_folds=3, prediction_length=5,
        )
        assert len(result.fold_predictions) == 15
        assert all(0 <= rec["actual"] for rec in result.fold_predictions)

    def test_sliding_window_mode(self):
        values, timestamps = _series(60)
        result = run_backtest(
            values, timestamps, lambda train, h: np.full(h, float(train[-1])),
            num_folds=3, prediction_length=5, expanding_window=False,
        )
        assert len(result.folds) == 3
        assert len(result.fold_results) == 3
        assert result.configuration.expanding_window is False

    def test_overlapping_mode(self):
        values, timestamps = _series(60)
        result = run_backtest(
            values, timestamps, lambda train, h: np.full(h, float(train[-1])),
            num_folds=3, prediction_length=5, non_overlapping=False,
        )
        assert result.configuration.non_overlapping is False
        # overlapping cutoffs step by 1 day (daily timestamps)
        cutoffs = [f.cutoff for f in result.folds]
        assert all((b - a) == pd.Timedelta(days=1) for a, b in zip(cutoffs, cutoffs[1:]))

    def test_few_folds_warning(self):
        values, timestamps = _series(60)
        result = run_backtest(
            values, timestamps, lambda train, h: np.full(h, float(train[-1])),
            num_folds=1, prediction_length=5,
        )
        assert any("fold" in w.lower() and "recommended" in w.lower() for w in result.warnings)

    def test_no_warning_for_adequate_folds(self):
        values, timestamps = _series(60)
        result = run_backtest(
            values, timestamps, lambda train, h: np.full(h, float(train[-1])),
            num_folds=3, prediction_length=5,
        )
        assert result.warnings == ()

    def test_wrong_prediction_length_raises(self):
        values, timestamps = _series(60)
        with pytest.raises(ValueError, match="returned"):
            run_backtest(
                values, timestamps, lambda train, h: np.full(h - 1, 1.0),
                num_folds=2, prediction_length=5,
            )

    def test_non_callable_raises(self):
        values, timestamps = _series(60)
        with pytest.raises(TypeError, match="callable"):
            run_backtest(values, timestamps, 42, num_folds=2, prediction_length=5)

    def test_length_mismatch_raises(self):
        with pytest.raises(ValueError, match="lengths differ"):
            run_backtest(
                [1.0, 2.0, 3.0], [1, 2], lambda t, h: [1.0] * h,
                num_folds=1, prediction_length=1,
            )

    def test_empty_series_raises(self):
        with pytest.raises(ValueError, match="empty"):
            run_backtest(
                [], [], lambda t, h: [1.0] * h,
                num_folds=1, prediction_length=1,
            )

    def test_insufficient_data_raises(self):
        with pytest.raises(ValueError):
            run_backtest(
                list(range(10)), list(range(10)), lambda t, h: [1.0] * h,
                num_folds=5, prediction_length=5,
            )

    def test_seasonal_scaling_runs(self):
        values, timestamps = _series(60)
        result = run_backtest(
            values, timestamps, lambda train, h: np.full(h, float(train[-1])),
            num_folds=2, prediction_length=5, seasonal_period=7,
        )
        assert len(result.fold_predictions) == 10

    def test_forecast_rows_well_formed(self):
        values, timestamps = _series(60)
        result = run_backtest(
            values, timestamps, lambda train, h: np.full(h, float(train[-1])),
            num_folds=2, prediction_length=5,
        )
        for fr in result.fold_results:
            assert len(fr.forecast_rows) == 5
            first = fr.forecast_rows[0]
            assert "fold_id" in first
            assert "timestamp" in first
            assert "point_prediction" in first

