"""Chronos-2 forecasting backend adapter.

``Chronos2Adapter`` is a concrete class that implements ``ForecastBackend``
and can be tested with an injected fake pipeline.
"""
from __future__ import annotations

import logging
import sys
import time
import warnings as stdlib_warnings
from datetime import datetime, timezone
from typing import Any, Callable

import numpy as np
import pandas as pd

from src.config import MODEL_ID
from src.schemas import (
    ForecastMode,
    ForecastResult,
    ForecastTask,
    RunMetadata,
    new_run_id,
)
from src.forecasting.base import ForecastBackend

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Safe exception types
# ---------------------------------------------------------------------------

class AdapterError(RuntimeError):
    """Base adapter exception."""


class ConfigurationError(AdapterError):
    """Raised when the task configuration is invalid."""


class ModelLoadError(AdapterError):
    """Raised when the Chronos-2 model cannot be loaded."""


class InferenceError(AdapterError):
    """Raised when Chronos-2 inference fails."""


class ResultSchemaError(AdapterError):
    """Raised when the model output does not match the expected schema."""


# ---------------------------------------------------------------------------
# Adapter class
# ---------------------------------------------------------------------------

class Chronos2Adapter:
    """Concrete Chronos-2 forecasting backend.

    Parameters
    ----------
    pipeline_or_provider : Any or Callable, optional
        Either an already-constructed ``Chronos2Pipeline`` instance, or a
        zero-argument callable that returns one.
    """

    def __init__(
        self,
        pipeline_or_provider: Any | Callable[[], Any] | None = None,
    ):
        self._pipeline: Any | None = None
        self._provider: Callable[[], Any] | None = None
        self._pipeline_call_count: int = 0

        if pipeline_or_provider is None:
            self._provider = self._default_provider
        elif callable(pipeline_or_provider):
            self._provider = pipeline_or_provider  # type: ignore[assignment]
        else:
            self._pipeline = pipeline_or_provider

    # ------------------------------------------------------------------
    # ForecastBackend compliance
    # ------------------------------------------------------------------

    def forecast(self, task: ForecastTask) -> ForecastResult:
        """Produce a canonical ``ForecastResult`` for ``task``."""
        if task.mode != ForecastMode.STANDARD_UNIVARIATE:
            raise ConfigurationError(
                f"Chronos2Adapter supports '{ForecastMode.STANDARD_UNIVARIATE}' "
                f"mode only. Got '{task.mode}'."
            )

        df = pd.DataFrame(task.historical_data)
        if df.empty:
            raise ConfigurationError("historical_data is empty after conversion.")

        target_col = task.target_columns[0]
        ts_col = task.timestamp_column

        # Parse timestamps and sort
        df[ts_col] = pd.to_datetime(df[ts_col])
        df = df.sort_values(ts_col).reset_index(drop=True)

        # Context truncation
        if task.context_window_cap is not None and len(df) > task.context_window_cap:
            df = df.iloc[-task.context_window_cap:].reset_index(drop=True)

        context_rows = len(df)

        # Validate single series for standard univariate mode
        id_col = task.item_id_column or "item_id"
        if id_col in df.columns:
            unique_ids = df[id_col].nunique()
            if unique_ids > 1:
                raise ConfigurationError(
                    "Standard univariate mode requires exactly one time series. "
                    f"Found {unique_ids} distinct item IDs in column '{id_col}'. "
                    "Select one item or use a single-series file."
                )

        if id_col not in df.columns:
            df[id_col] = "default"
        input_df = df[[id_col, ts_col, target_col]].copy()
        input_df.columns = ["item_id", "timestamp", "target"]

        # Obtain pipeline
        t0 = time.perf_counter()
        try:
            pipeline = self._get_pipeline()
        except ModelLoadError:
            raise

        # Call Chronos-2
        try:
            with stdlib_warnings.catch_warnings():
                stdlib_warnings.simplefilter("ignore")
                pred_df = pipeline.predict_df(
                    input_df,
                    prediction_length=task.prediction_length,
                    quantile_levels=list(task.quantile_levels),
                    id_column="item_id",
                    timestamp_column="timestamp",
                    target="target",
                )
        except Exception as exc:
            raise InferenceError(
                "Chronos-2 inference failed. Check the configuration and try again."
            ) from exc

        inference_time = time.perf_counter() - t0

        # Validate output schema
        expected_quant_cols = {str(q) for q in task.quantile_levels}
        actual_cols = set(pred_df.columns)
        if "predictions" not in actual_cols:
            raise ResultSchemaError("Model output is missing the 'predictions' column.")
        missing = expected_quant_cols - actual_cols
        if missing:
            raise ResultSchemaError(
                f"Model output is missing quantile columns: {sorted(missing)}"
            )

        # Convert to canonical long format
        forecast_rows: list[dict[str, Any]] = []
        quant_cols = [str(q) for q in task.quantile_levels]

        for _, row in pred_df.iterrows():
            out: dict[str, Any] = {
                "run_id": "",
                "item_id": str(row.get("item_id", "default")),
                "timestamp": str(row.get("timestamp", "")),
                "target_name": str(row.get("target_name", target_col)),
                "point_prediction": float(row.get("predictions", np.nan)),
                "source_type": "forecast",
            }
            for q_col in quant_cols:
                if q_col in row:
                    key = f"quantile_{q_col.replace('.', '_')}"
                    out[key] = float(row[q_col])
            forecast_rows.append(out)

        # Build metadata
        run_id = new_run_id()
        now_iso = datetime.now(timezone.utc).isoformat()

        pkg_versions = _capture_package_versions()
        model_revision = (
            getattr(self._pipeline, "model_revision", "")
            if self._pipeline is not None
            else getattr(pipeline, "model_revision", "") or ""
        )

        meta = RunMetadata(
            run_id=run_id,
            run_timestamp=now_iso,
            model_id=MODEL_ID,
            model_revision=model_revision,
            forecast_mode=task.mode.value,
            resolved_frequency=task.frequency,
            prediction_length=task.prediction_length,
            quantile_levels=task.quantile_levels,
            context_rows_used=context_rows,
            data_fingerprint="",
            warnings=(),
            runtime_seconds=round(inference_time, 3),
            package_versions=pkg_versions,
            backend_name="Chronos2Adapter",
        )

        for row in forecast_rows:
            row["run_id"] = run_id

        return ForecastResult(
            run_id=run_id,
            forecast_rows=tuple(forecast_rows),
            model_id=MODEL_ID,
            model_revision=model_revision,
            point_prediction_name="predictions",
            quantile_levels=task.quantile_levels,
            runtime_metadata=meta,
            warnings=(),
            backend_name="Chronos2Adapter",
        )

    # ------------------------------------------------------------------
    # Query helpers
    # ------------------------------------------------------------------

    @property
    def pipeline_call_count(self) -> int:
        """Number of times the pipeline was constructed (0 if pre-injected)."""
        return self._pipeline_call_count

    # ------------------------------------------------------------------
    # Internal
    # ------------------------------------------------------------------

    def _get_pipeline(self) -> Any:
        if self._pipeline is not None:
            return self._pipeline
        if self._provider is None:
            raise ModelLoadError("No pipeline provider configured.")
        self._pipeline = self._provider()
        self._pipeline_call_count += 1
        return self._pipeline

    @staticmethod
    def _default_provider() -> Any:
        try:
            from chronos import Chronos2Pipeline
            logger.info("Loading Chronos-2 model (cold start)...")
            pipeline = Chronos2Pipeline.from_pretrained(MODEL_ID, device_map="cpu")
            logger.info("Chronos-2 model loaded.")
            return pipeline
        except Exception as exc:
            raise ModelLoadError(
                f"Failed to load Chronos-2 model '{MODEL_ID}'. "
                "Check your internet connection, disk space, and HF token."
            ) from exc


def _capture_package_versions() -> dict[str, str]:
    """Return a dict of relevant package versions for run metadata."""
    versions: dict[str, str] = {}
    try:
        import chronos as _c
        versions["chronos-forecasting"] = getattr(_c, "__version__", "unknown")
    except ImportError:
        versions["chronos-forecasting"] = "unknown"
    try:
        import torch as _t
        versions["torch"] = _t.__version__
    except ImportError:
        versions["torch"] = "unknown"
    try:
        import pandas as _pd
        versions["pandas"] = _pd.__version__
    except ImportError:
        versions["pandas"] = "unknown"
    try:
        import numpy as _np
        versions["numpy"] = _np.__version__
    except ImportError:
        versions["numpy"] = "unknown"
    try:
        import streamlit as _st
        versions["streamlit"] = _st.__version__
    except ImportError:
        versions["streamlit"] = "unknown"
    versions["python"] = sys.version.split()[0]
    return versions
