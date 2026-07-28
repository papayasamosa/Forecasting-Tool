"""Chronos-2 forecasting backend adapter.

All Chronos-specific API calls live here.  The adapter translates between
the canonical ``ForecastTask`` / ``ForecastResult`` schemas and the
``chronos-forecasting`` library API.

In Stage 0 the adapter supports only:

- Standard univariate mode
- CPU inference (``device_map="cpu"``)
- Configurable horizon, quantiles, and context window cap
- Cross-learning is *off* (default)
- No future-data / covariates
"""
from __future__ import annotations

import time
import warnings as stdlib_warnings
from datetime import datetime, timezone
from typing import Any

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


class ModelLoadError(RuntimeError):
    """Raised when the Chronos-2 model cannot be loaded."""


class ForecastError(RuntimeError):
    """Raised when inference fails."""


# ---------------------------------------------------------------------------
# Singleton-like pipeline holder (used by Streamlit's st.cache_resource)
# ---------------------------------------------------------------------------

_PIPELINE_INSTANCE: Any = None
_PIPELINE_LOADED: bool = False


def load_pipeline(
    model_id: str = MODEL_ID,
    device_map: str = "cpu",
) -> Any:
    """Load and return the Chronos-2 pipeline (cached globally)."""
    global _PIPELINE_INSTANCE, _PIPELINE_LOADED

    if _PIPELINE_LOADED and _PIPELINE_INSTANCE is not None:
        return _PIPELINE_INSTANCE

    try:
        from chronos import Chronos2Pipeline

        _PIPELINE_INSTANCE = Chronos2Pipeline.from_pretrained(
            model_id,
            device_map=device_map,
        )
        _PIPELINE_LOADED = True
        return _PIPELINE_INSTANCE
    except Exception as exc:
        _PIPELINE_LOADED = False
        _PIPELINE_INSTANCE = None
        raise ModelLoadError(
            f"Failed to load Chronos-2 model '{model_id}': {exc}"
        ) from exc


def reset_pipeline() -> None:
    """Reset the cached pipeline (useful in tests)."""
    global _PIPELINE_INSTANCE, _PIPELINE_LOADED
    _PIPELINE_INSTANCE = None
    _PIPELINE_LOADED = False


def get_pipeline_info() -> dict[str, Any]:
    """Return metadata about the currently loaded pipeline (or empty dict)."""
    if _PIPELINE_INSTANCE is None:
        return {}
    try:
        return {
            "model_id": getattr(_PIPELINE_INSTANCE, "model_id", MODEL_ID),
            "model_revision": getattr(
                _PIPELINE_INSTANCE, "model_revision", ""
            ),
            "pipeline_loaded": _PIPELINE_LOADED,
        }
    except Exception:
        return {}


# ---------------------------------------------------------------------------
# Main adapter function
# ---------------------------------------------------------------------------

def create_forecast(task: ForecastTask) -> ForecastResult:
    """Run a Chronos-2 forecast for the given ``task``.

    This is the primary entry point called by the application layer.
    """
    # --- Validate mode ---------------------------------------------------
    if task.mode != ForecastMode.STANDARD_UNIVARIATE:
        raise ForecastError(
            f"Chronos2Adapter only supports {ForecastMode.STANDARD_UNIVARIATE}"
            f" mode in Phase 1. Got '{task.mode}'."
        )

    # --- Convert historical data to DataFrame ----------------------------
    df = pd.DataFrame(task.historical_data)
    if df.empty:
        raise ForecastError("No historical data provided.")

    target_col = task.target_columns[0]

    # Sort by timestamp
    ts_col = task.timestamp_column
    df = df.sort_values(ts_col).reset_index(drop=True)

    # Select the last ``context_window_cap`` rows if set
    if task.context_window_cap is not None and len(df) > task.context_window_cap:
        df = df.iloc[-task.context_window_cap :].reset_index(drop=True)

    context_rows = len(df)

    # Build the input DataFrame for Chronos-2's predict_df API
    # The API expects columns: id_column, timestamp_column, target
    item_id_col = task.item_id_column or "item_id"
    if item_id_col not in df.columns:
        df[item_id_col] = "default"

    input_df = df[[item_id_col, ts_col, target_col]].copy()
    input_df.columns = ["item_id", "timestamp", "target"]

    # --- Timing -----------------------------------------------------------
    t0 = time.perf_counter()

    # --- Load model -------------------------------------------------------
    try:
        pipeline = load_pipeline()
    except ModelLoadError:
        raise

    # --- Call Chronos-2 ---------------------------------------------------
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
        raise ForecastError(
            f"Chronos-2 inference failed: {exc}"
        ) from exc

    elapsed = time.perf_counter() - t0

    # --- Convert to canonical long format ---------------------------------
    forecast_rows: list[dict[str, Any]] = []
    quant_cols = [str(q) for q in task.quantile_levels]

    for _, row in pred_df.iterrows():
        out: dict[str, Any] = {
            "run_id": "",
            "item_id": row.get("item_id", "default"),
            "timestamp": str(row.get("timestamp", "")),
            "target_name": row.get("target_name", target_col),
            "point_prediction": float(row.get("predictions", np.nan)),
            "source_type": "forecast",
        }
        for q_col in quant_cols:
            if q_col in row:
                out[f"quantile_{q_col.replace('.', '_')}"] = float(row[q_col])
        forecast_rows.append(out)

    # --- Metadata ----------------------------------------------------------
    run_id = new_run_id()
    now_iso = datetime.now(timezone.utc).isoformat()

    pkg_versions: dict[str, str] = {}
    try:
        import chronos as _c
        pkg_versions["chronos-forecasting"] = getattr(_c, "__version__", "")
    except ImportError:
        pkg_versions["chronos-forecasting"] = "unknown"
    try:
        import torch as _t
        pkg_versions["torch"] = _t.__version__
    except ImportError:
        pkg_versions["torch"] = "unknown"

    meta = RunMetadata(
        run_id=run_id,
        run_timestamp=now_iso,
        model_id=MODEL_ID,
        model_revision=get_pipeline_info().get("model_revision", ""),
        forecast_mode=task.mode.value,
        resolved_frequency=task.frequency,
        prediction_length=task.prediction_length,
        quantile_levels=task.quantile_levels,
        context_rows_used=context_rows,
        data_fingerprint="",
        warnings=(),
        runtime_seconds=round(elapsed, 3),
        package_versions=pkg_versions,
        backend_name="Chronos2Adapter",
    )

    # Attach run_id to rows
    for row in forecast_rows:
        row["run_id"] = run_id

    return ForecastResult(
        run_id=run_id,
        forecast_rows=tuple(forecast_rows),
        model_id=MODEL_ID,
        model_revision=meta.model_revision,
        point_prediction_name="predictions",
        quantile_levels=task.quantile_levels,
        runtime_metadata=meta,
        warnings=(),
        backend_name="Chronos2Adapter",
    )
