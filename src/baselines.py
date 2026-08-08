"""Baseline forecast models for Phase 1 (Slice 8).

Implements the two canonical baselines declared in ``src.schemas.BaselineModel``:

* ``LAST_VALUE`` — naive persistence: the forecast is the last observed value;
* ``SEASONAL_NAIVE`` — the forecast repeats the value observed one season ago
  (requires ``seasonal_period``; a series shorter than ``2 * period`` is
  ineligible — see ``WarningCode.SEASONAL_NAIVE_INELIGIBLE``).

``baseline_predict_fn`` returns a ``(train, horizon) -> predictions`` callable
that plugs directly into ``backtesting.run_backtest``.
"""
from __future__ import annotations

from typing import Callable, Iterable, Sequence

import numpy as np

from src.schemas import BaselineModel


# ---------------------------------------------------------------------------
# Individual baselines
# ---------------------------------------------------------------------------


def last_value_forecast(values: Sequence[float], horizon: int) -> np.ndarray:
    """Naive persistence forecast: repeat the last observed value."""
    if horizon < 1:
        raise ValueError(f"horizon must be >= 1, got {horizon}")
    v = np.asarray(values, dtype=float)
    if len(v) == 0:
        raise ValueError("cannot forecast an empty series")
    return np.full(horizon, float(v[-1]))


def seasonal_naive_eligible(values: Sequence[float], period: int) -> bool:
    """Whether a seasonal naive forecast is possible for this series/period.

    Requires ``period >= 1`` and at least ``2 * period`` observations (one
    full cycle to forecast from plus one to validate the season).
    """
    if period < 1:
        return False
    return len(np.asarray(values)) >= 2 * period


def seasonal_naive_forecast(
    values: Sequence[float],
    horizon: int,
    period: int,
) -> np.ndarray:
    """Seasonal naive forecast: repeat the value from one season ago.

    Raises ``ValueError`` when ineligible (see ``seasonal_naive_eligible``).
    """
    if horizon < 1:
        raise ValueError(f"horizon must be >= 1, got {horizon}")
    if not seasonal_naive_eligible(values, period):
        raise ValueError(
            f"seasonal naive requires at least {2 * period} observations for "
            f"period {period}, got {len(np.asarray(values))} (ineligible — "
            "WarningCode.SEASONAL_NAIVE_INELIGIBLE)"
        )
    v = np.asarray(values, dtype=float)
    result = np.empty(horizon)
    for step in range(1, horizon + 1):
        # k-th step ahead uses the value from k seasons ago.
        result[step - 1] = v[-period + ((step - 1) % period)]
    return result


# ---------------------------------------------------------------------------
# Dispatcher / predict_fn
# ---------------------------------------------------------------------------


def forecast_baseline(
    values: Sequence[float],
    horizon: int,
    model: BaselineModel,
    *,
    period: int | None = None,
) -> np.ndarray:
    """Dispatch a baseline forecast by ``BaselineModel``."""
    if not isinstance(model, BaselineModel):
        raise ValueError(
            f"unsupported baseline model '{model}'; "
            f"valid: {[m.value for m in BaselineModel]}"
        )
    if model is BaselineModel.LAST_VALUE:
        return last_value_forecast(values, horizon)
    if model is BaselineModel.SEASONAL_NAIVE:
        if period is None or period < 1:
            raise ValueError(
                "seasonal naive requires a positive seasonal period"
            )
        return seasonal_naive_forecast(values, horizon, period)
    raise ValueError(f"unsupported baseline model '{model}'")


def baseline_predict_fn(
    model: BaselineModel,
    *,
    period: int | None = None,
) -> Callable[[Sequence[float], int], np.ndarray]:
    """Return a ``(train, horizon) -> predictions`` callable for backtesting.

    Parameters
    ----------
    model : BaselineModel
        Baseline to use.
    period : int or None
        Seasonal period (required for ``SEASONAL_NAIVE``).

    Returns
    -------
    Callable[[Sequence[float], int], np.ndarray]
        Suitable for ``backtesting.run_backtest(predict_fn=...)``.
    """
    def _predict(train: Sequence[float], horizon: int) -> np.ndarray:
        return forecast_baseline(train, horizon, model, period=period)

    return _predict


__all__: Iterable[str] = (
    "last_value_forecast",
    "seasonal_naive_eligible",
    "seasonal_naive_forecast",
    "forecast_baseline",
    "baseline_predict_fn",
)
