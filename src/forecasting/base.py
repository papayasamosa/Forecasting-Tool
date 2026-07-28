"""Abstract forecasting backend interface.

All forecasting backends (Chronos-2, naive baselines, etc.) must implement the
``ForecastBackend`` protocol so that the application can swap implementations
without changing calling code.
"""
from __future__ import annotations

from typing import Protocol, runtime_checkable

from src.schemas import ForecastResult, ForecastTask


@runtime_checkable
class ForecastBackend(Protocol):
    """Protocol that every forecasting backend must satisfy."""

    def forecast(self, task: ForecastTask) -> ForecastResult:
        """Return a canonical ForecastResult for the given ForecastTask.

        Parameters
        ----------
        task : ForecastTask
            Validated and normalised forecast request.

        Returns
        -------
        ForecastResult
            Frozen result with long-format rows and metadata.

        Raises
        ------
        ForecastError
            If the backend cannot produce a forecast (e.g. model load failure,
            inference error, unsupported configuration).
        """
        ...
