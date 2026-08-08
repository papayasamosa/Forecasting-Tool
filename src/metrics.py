"""Error metrics for Phase 1 rolling-origin backtesting evaluation.

Provides MAE, RMSE and MASE for comparing forecast values against actuals,
plus ``evaluate_fold`` which bundles them into a typed ``MetricsResult``.

MASE (mean absolute scaled error) scales the forecast error by the
in-sample naive error of the training series:

* one-step naive (``seasonal_period=None``): mean absolute first difference;
* seasonal naive (``seasonal_period=k``): mean absolute k-step difference.

When the training series is constant the scaling factor is zero; MASE is then
defined as 0.0 (perfect scaling base) to keep results finite and comparable.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Iterable, Sequence

import numpy as np

from src.config import SEASONAL_PERIODS


# ---------------------------------------------------------------------------
# Types
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class MetricsResult:
    """Error metrics for one forecast-vs-actual comparison."""
    mae: float
    rmse: float
    mase: float
    n: int


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------


def _as_vectors(actual: Sequence[float], forecast: Sequence[float]) -> tuple[np.ndarray, np.ndarray]:
    a = np.asarray(actual, dtype=float).reshape(-1)
    f = np.asarray(forecast, dtype=float).reshape(-1)
    if a.ndim != 1 or f.ndim != 1:
        raise ValueError("actual and forecast must be one-dimensional")
    if len(a) == 0:
        raise ValueError("cannot compute metrics on an empty series")
    if len(a) != len(f):
        raise ValueError(
            f"actual and forecast lengths differ: {len(a)} vs {len(f)}"
        )
    if np.any(np.isnan(a)) or np.any(np.isnan(f)):
        raise ValueError("actual and forecast must not contain NaN values")
    return a, f


def _naive_mae(training_series: Sequence[float], seasonal_period: int | None = None) -> float:
    s = np.asarray(training_series, dtype=float).reshape(-1)
    if len(s) < 2:
        raise ValueError("training series must have at least 2 points to scale MASE")
    if seasonal_period:
        if len(s) < 2 * seasonal_period:
            raise ValueError(
                f"seasonal naive requires at least {2 * seasonal_period} training "
                f"points for period {seasonal_period}, got {len(s)}"
            )
        diff = s[seasonal_period:] - s[:-seasonal_period]
    else:
        diff = s[1:] - s[:-1]
    return float(np.mean(np.abs(diff)))


# ---------------------------------------------------------------------------
# Metrics
# ---------------------------------------------------------------------------


def mae(actual: Sequence[float], forecast: Sequence[float]) -> float:
    """Mean absolute error."""
    a, f = _as_vectors(actual, forecast)
    return float(np.mean(np.abs(a - f)))


def rmse(actual: Sequence[float], forecast: Sequence[float]) -> float:
    """Root mean squared error."""
    a, f = _as_vectors(actual, forecast)
    return float(np.sqrt(np.mean((a - f) ** 2)))


def mase(
    actual: Sequence[float],
    forecast: Sequence[float],
    *,
    naive_mae: float | None = None,
    training_series: Sequence[float] | None = None,
    seasonal_period: int | None = None,
) -> float:
    """Mean absolute scaled error.

    At least one of ``naive_mae`` or ``training_series`` must be provided.
    When ``seasonal_period`` is given (and ``training_series`` provided), the
    scaling uses seasonal-naive differences; a one-step naive scale is used
    otherwise.
    """
    a, f = _as_vectors(actual, forecast)
    if naive_mae is None:
        if training_series is None:
            raise ValueError(
                "mase requires either naive_mae or training_series"
            )
        naive_mae = _naive_mae(training_series, seasonal_period)
    if naive_mae < 0:
        raise ValueError(f"naive_mae must be non-negative, got {naive_mae}")
    if naive_mae == 0:
        # Constant training series: define scaled error as 0 (finite base).
        return 0.0
    return float(np.mean(np.abs(a - f)) / naive_mae)


def evaluate_fold(
    actual: Sequence[float],
    forecast: Sequence[float],
    *,
    training_series: Sequence[float] | None = None,
    seasonal_period: int | None = None,
) -> MetricsResult:
    """Compute MAE/RMSE/MASE for one fold.

    ``training_series`` enables MASE scaling; when omitted MASE is computed
    with ``naive_mae=1.0`` (i.e. an unscaled mean absolute error), documented
    for callers that do not retain training context.
    """
    a, f = _as_vectors(actual, forecast)
    if training_series is None:
        m = 1.0
    else:
        m = _naive_mae(training_series, seasonal_period)
    return MetricsResult(
        mae=mae(a, f),
        rmse=rmse(a, f),
        mase=mase(a, f, naive_mae=m),
        n=len(a),
    )


# ---------------------------------------------------------------------------
# Seasonal period helpers
# ---------------------------------------------------------------------------


def seasonal_period_for_frequency(frequency: str) -> int | None:
    """Map a pandas frequency alias to a seasonal period from
    ``src.config.SEASONAL_PERIODS`` (D→7, W→52, M→12).

    Returns ``None`` for unknown/empty frequencies.
    """
    if not frequency:
        return None
    return SEASONAL_PERIODS.get(frequency)


__all__: Iterable[str] = (
    "MetricsResult",
    "mae",
    "rmse",
    "mase",
    "evaluate_fold",
    "seasonal_period_for_frequency",
)
