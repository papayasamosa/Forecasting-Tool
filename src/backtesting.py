"""Rolling-origin backtesting for Phase 1 (Slice 7).

Implements rolling-origin evaluation with the two orthogonal knobs declared in
``src.schemas.BacktestConfiguration``:

* **expanding vs sliding** training window;
* **overlapping vs non-overlapping** folds.

``build_backtest_folds`` derives the fold cut-offs (and their horizon steps);
``run_backtest`` executes a caller-supplied ``predict_fn(train, horizon) ->
predictions`` over every fold, scores each fold with ``src.metrics``, and
returns a typed ``BacktestResult`` containing per-fold ``ForecastResult``s and
long-format scored observations (``fold_predictions``).

The prediction function is deliberately decoupled from any concrete backend so
the backtest harness is unit-testable without the Chronos-2 model; wiring a
real adapter (e.g. ``Chronos2Adapter``) as ``predict_fn`` is a later
integration step.
"""
from __future__ import annotations

from typing import Callable, Iterable, Sequence

import numpy as np

from src.config import MIN_RECOMMENDED_FOLDS
from src.metrics import evaluate_fold
from src.schemas import (
    BacktestConfiguration,
    BacktestFold,
    BacktestResult,
    ForecastResult,
    WarningCode,
    new_run_id,
)


# ---------------------------------------------------------------------------
# Fold construction (rolling origin)
# ---------------------------------------------------------------------------


def validate_backtest_parameters(
    *,
    num_folds: int,
    prediction_length: int,
    series_length: int,
    backtest_horizon: int | None = None,
) -> list[str]:
    """Return a list of configuration/data problems (empty when valid)."""
    errors: list[str] = []
    if num_folds < 1:
        errors.append(f"num_folds must be >= 1, got {num_folds}")
    if prediction_length < 1:
        errors.append(f"prediction_length must be >= 1, got {prediction_length}")
    horizon = backtest_horizon or prediction_length
    if backtest_horizon is not None and backtest_horizon < 1:
        errors.append(f"backtest_horizon must be >= 1, got {backtest_horizon}")
    if series_length < 2:
        errors.append("series must contain at least 2 observations")
    if errors:
        return errors
    if series_length < horizon + 1:
        errors.append(
            f"series length {series_length} is too short for horizon {horizon} "
            "(need at least one training point plus the horizon)"
        )
    return errors


def build_backtest_folds(
    timestamps: Sequence,
    *,
    num_folds: int,
    prediction_length: int,
    expanding_window: bool = True,
    non_overlapping: bool = True,
    backtest_horizon: int | None = None,
) -> tuple[BacktestFold, ...]:
    """Derive rolling-origin fold cut-offs from the timestamp sequence.

    The last fold's cut-off is chosen so its full test window fits within the
    series; preceding folds step back by ``horizon`` (non-overlapping) or by
    one observation (overlapping).  Raises ``ValueError`` when the series is
    too short for the requested configuration.
    """
    errors = validate_backtest_parameters(
        num_folds=num_folds,
        prediction_length=prediction_length,
        series_length=len(timestamps),
        backtest_horizon=backtest_horizon,
    )
    if errors:
        raise ValueError("; ".join(errors))

    horizon = backtest_horizon or prediction_length
    n = len(timestamps)
    step = horizon if non_overlapping else 1

    last_cutoff_idx = n - 1 - horizon
    first_cutoff_idx = last_cutoff_idx - (num_folds - 1) * step
    if first_cutoff_idx < 0:
        raise ValueError(
            f"series length {n} cannot support {num_folds} folds of horizon "
            f"{horizon} (need at least {(num_folds - 1) * step + horizon + 1})"
        )

    folds = []
    for fold_id in range(num_folds):
        cutoff_idx = first_cutoff_idx + fold_id * step
        folds.append(
            BacktestFold(
                fold_id=fold_id,
                cutoff=timestamps[cutoff_idx],
                horizon_steps=tuple(range(1, horizon + 1)),
            )
        )
    return tuple(folds)


# ---------------------------------------------------------------------------
# Backtest execution
# ---------------------------------------------------------------------------


def _sliding_window_size(
    series_length: int,
    num_folds: int,
    horizon: int,
    non_overlapping: bool,
) -> int:
    step = horizon if non_overlapping else 1
    return series_length - (num_folds - 1) * step - horizon


def run_backtest(
    values: Sequence[float],
    timestamps: Sequence,
    predict_fn: Callable[[Sequence[float], int], Sequence[float]],
    *,
    num_folds: int = 5,
    prediction_length: int = 13,
    expanding_window: bool = True,
    non_overlapping: bool = True,
    backtest_horizon: int | None = None,
    seasonal_period: int | None = None,
) -> BacktestResult:
    """Run a rolling-origin backtest with a caller-supplied predictor.

    Parameters
    ----------
    values : sequence of float
        Target observations, chronological (same length as ``timestamps``).
    timestamps : sequence
        Timestamps aligned with ``values``.
    predict_fn : callable
        ``predict_fn(train, horizon) -> predictions``.  Must return exactly
        ``horizon`` numeric values.
    num_folds / prediction_length / expanding_window / non_overlapping /
    backtest_horizon : see ``BacktestConfiguration``.
    seasonal_period : int or None
        When provided, MASE is scaled by the seasonal-naive error of the
        training window (see ``src.metrics``).

    Returns
    -------
    BacktestResult
        Typed folds, per-fold ``ForecastResult``s, scored fold predictions and
        advisory warnings (e.g. ``FEW_FOLDS``).
    """
    if not callable(predict_fn):
        raise TypeError("predict_fn must be callable")

    v = np.asarray(values, dtype=float).reshape(-1)
    ts = list(timestamps)
    if len(v) != len(ts):
        raise ValueError(
            f"values ({len(v)}) and timestamps ({len(ts)}) lengths differ"
        )
    if len(v) == 0:
        raise ValueError("cannot backtest an empty series")

    errors = validate_backtest_parameters(
        num_folds=num_folds,
        prediction_length=prediction_length,
        series_length=len(v),
        backtest_horizon=backtest_horizon,
    )
    if errors:
        raise ValueError("; ".join(errors))

    horizon = backtest_horizon or prediction_length
    folds = build_backtest_folds(
        ts,
        num_folds=num_folds,
        prediction_length=prediction_length,
        expanding_window=expanding_window,
        non_overlapping=non_overlapping,
        backtest_horizon=backtest_horizon,
    )

    window = _sliding_window_size(
        len(v), num_folds, horizon, non_overlapping
    )

    fold_results: list[ForecastResult] = []
    fold_predictions: list[dict] = []
    cutoff_indices = {
        fold.cutoff: np.searchsorted(ts, fold.cutoff) for fold in folds
    }

    for fold in folds:
        cutoff_idx = cutoff_indices[fold.cutoff]
        if expanding_window:
            train = v[: cutoff_idx + 1]
        else:
            start = cutoff_idx + 1 - window
            train = v[max(start, 0): cutoff_idx + 1]

        test = v[cutoff_idx + 1: cutoff_idx + 1 + horizon]
        pred = np.asarray(predict_fn(train, horizon), dtype=float).reshape(-1)
        if len(pred) != horizon:
            raise ValueError(
                f"predict_fn returned {len(pred)} values for horizon {horizon}"
            )

        metrics = evaluate_fold(
            test, pred, training_series=train, seasonal_period=seasonal_period
        )

        rows = []
        for step, (actual, predicted) in enumerate(zip(test, pred), start=1):
            ts_val = ts[cutoff_idx + step]
            fold_predictions.append(
                {
                    "fold_id": fold.fold_id,
                    "timestamp": ts_val,
                    "actual": float(actual),
                    "predicted": float(predicted),
                }
            )
            rows.append(
                {
                    "fold_id": fold.fold_id,
                    "timestamp": ts_val,
                    "target_name": "target",
                    "point_prediction": float(predicted),
                    "mae": metrics.mae,
                    "rmse": metrics.rmse,
                    "mase": metrics.mase,
                }
            )

        fold_results.append(
            ForecastResult(
                run_id=new_run_id(),
                forecast_rows=tuple(rows),
                quantile_levels=(),
            )
        )

    warnings: list[str] = []
    if num_folds < MIN_RECOMMENDED_FOLDS:
        warnings.append(
            f"Only {num_folds} backtest fold(s) requested; fewer than the "
            f"recommended {MIN_RECOMMENDED_FOLDS} can produce unstable "
            f"evaluation (WarningCode.{WarningCode.FEW_FOLDS.value})"
        )

    return BacktestResult(
        folds=folds,
        fold_results=tuple(fold_results),
        fold_predictions=tuple(fold_predictions),
        configuration=BacktestConfiguration(
            num_folds=num_folds,
            expanding_window=expanding_window,
            non_overlapping=non_overlapping,
            backtest_horizon=backtest_horizon,
        ),
        warnings=tuple(warnings),
    )


__all__: Iterable[str] = (
    "validate_backtest_parameters",
    "build_backtest_folds",
    "run_backtest",
)
