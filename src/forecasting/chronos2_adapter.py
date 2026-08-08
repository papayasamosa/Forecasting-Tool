"""Chronos-2 forecasting backend adapter.

``Chronos2Adapter`` is a concrete class that implements ``ForecastBackend``
and can be tested with an injected fake pipeline.
"""
from __future__ import annotations

import inspect
import logging
import time
import warnings as stdlib_warnings
from datetime import datetime, timezone
from typing import Any, Callable

import numpy as np
import pandas as pd

from src.config import MODEL_ID, MODEL_REVISION
from src.schemas import (
    ForecastMode,
    ForecastResult,
    ForecastTask,
    RunMetadata,
    WarningCode,
    new_run_id,
)
from src.telemetry import capture_package_versions
from src.forecasting.base import ForecastBackend
from src.fingerprinting import fingerprint_forecast_task

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
# Cross-learning capability detection (WP4, P1-2)
# ---------------------------------------------------------------------------

def _predict_df_accepts_cross_learning(pipeline: Any) -> bool:
    """Return True if ``pipeline.predict_df`` accepts a ``cross_learning``
    keyword argument.

    Inspects the callable signature before the expensive inference call so
    we never retry an arbitrary model ``TypeError``.
    """
    try:
        sig = inspect.signature(pipeline.predict_df)
    except (ValueError, TypeError):
        return False
    for name, param in sig.parameters.items():
        if name == "cross_learning":
            return True
        if param.kind == inspect.Parameter.VAR_KEYWORD:
            # Accepts **kwargs — assume it may accept cross_learning
            return True
    return False


# ---------------------------------------------------------------------------
# Shared validation helpers (also used by src.benchmarking)
# ---------------------------------------------------------------------------

def _validate_quantile_monotonic(row: Any, quantile_levels: list[float]) -> None:
    """Raise ResultSchemaError if quantile columns are not non-decreasing
    when read in ascending quantile-level order.

    Requires every requested quantile column to be present, contain numeric
    finite values, and be monotonic non-decreasing.
    """
    prev_val: float | None = None
    prev_q: float | None = None
    for q in sorted(quantile_levels):
        col = str(q)
        if col not in row:
            raise ResultSchemaError(
                f"Missing requested quantile column '{col}' in prediction row."
            )
        val = float(row[col])
        if not np.isfinite(val):
            raise ResultSchemaError(
                f"Non-finite quantile value for q={q}: {val}"
            )
        if prev_val is not None and val < prev_val:
            raise ResultSchemaError(
                f"Quantile values are not monotonic: q={q} value={val} < "
                f"q={prev_q} value={prev_val}"
            )
        prev_val = val
        prev_q = q


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

        captured_warnings: list[str] = []

        # Context truncation
        if task.context_window_cap is not None and len(df) > task.context_window_cap:
            original_rows = len(df)
            df = df.iloc[-task.context_window_cap:].reset_index(drop=True)
            captured_warnings.append(
                f"{WarningCode.CONTEXT_TRUNCATION.value}: truncated context from "
                f"{original_rows} to {task.context_window_cap} rows"
            )

        context_rows = len(df)
        last_historical_ts = df[ts_col].iloc[-1]

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

        # Separate timing for model load vs inference
        pipeline_call_count_before = self._pipeline_call_count
        model_load_start = time.perf_counter()
        try:
            pipeline = self._get_pipeline()
        except ModelLoadError:
            raise
        model_load_time = time.perf_counter() - model_load_start
        # Model was actually loaded if the provider was invoked this call
        model_was_loaded = self._pipeline_call_count > pipeline_call_count_before

        # Capture warnings during inference rather than silencing them
        inference_start = time.perf_counter()
        try:
            with stdlib_warnings.catch_warnings(record=True) as w:
                stdlib_warnings.simplefilter("always")
                predict_kwargs: dict[str, Any] = dict(
                    prediction_length=task.prediction_length,
                    quantile_levels=list(task.quantile_levels),
                    id_column="item_id",
                    timestamp_column="timestamp",
                    target="target",
                )
                # WP4: Explicitly pass cross_learning=False for standard
                # univariate to match the PRD default. The panel benchmark
                # path (outside forecast()) also passes it explicitly.
                # Inspect the pipeline signature before calling so we never
                # retry an arbitrary model TypeError (P1-2).
                _supports_cross_learning = _predict_df_accepts_cross_learning(pipeline)
                if _supports_cross_learning:
                    predict_kwargs["cross_learning"] = task.cross_learning
                else:
                    captured_warnings.append(
                        "cross_learning parameter not supported by this "
                        "Chronos-2 version; using default."
                    )
                pred_df = pipeline.predict_df(input_df, **predict_kwargs)
                for warning in w:
                    cat = warning.category.__name__ if warning.category else "Warning"
                    msg = str(warning.message)[:200]
                    captured_warnings.append(f"{cat}: {msg}")
        except Exception as exc:
            raise InferenceError(
                "Chronos-2 inference failed. Check the configuration and try again."
            ) from exc
        inference_time = time.perf_counter() - inference_start

        # Validate output schema (stronger checks)
        expected_quant_cols = {str(q) for q in task.quantile_levels}
        actual_cols = set(pred_df.columns)
        if "predictions" not in actual_cols:
            raise ResultSchemaError("Model output is missing the 'predictions' column.")
        missing = expected_quant_cols - actual_cols
        if missing:
            raise ResultSchemaError(
                f"Model output is missing quantile columns: {sorted(missing)}"
            )

        # Check row count matches horizon
        if len(pred_df) != task.prediction_length:
            raise ResultSchemaError(
                f"Expected {task.prediction_length} forecast rows, "
                f"got {len(pred_df)}."
            )

        # Convert to canonical long format
        result_conversion_start = time.perf_counter()
        forecast_rows: list[dict[str, Any]] = []
        quant_cols = [str(q) for q in task.quantile_levels]

        item_id_seen: str | None = None
        seen_row_keys: set[tuple[str, str]] = set()
        for idx, row in pred_df.iterrows():
            out: dict[str, Any] = {
                "run_id": "",
                "item_id": str(row.get("item_id", "default")),
                "timestamp": str(row.get("timestamp", "")),
                "target_name": str(row.get("target_name", target_col)),
                "point_prediction": float(row.get("predictions", np.nan)),
                "source_type": "forecast",
            }
            # Validate finite point predictions
            point_val = out["point_prediction"]
            if not np.isfinite(point_val):
                raise ResultSchemaError(
                    f"Non-finite point prediction at row {idx}: {point_val}"
                )

            # Validate timestamps are non-empty
            if not out["timestamp"]:
                raise ResultSchemaError(f"Empty timestamp at row {idx}.")

            # Validate same item_id across all rows
            if item_id_seen is None:
                item_id_seen = out["item_id"]
            elif out["item_id"] != item_id_seen:
                raise ResultSchemaError(
                    f"Multiple item IDs in output: '{item_id_seen}' and '{out['item_id']}'."
                )

            # Validate no duplicate (item_id, timestamp) rows
            row_key = (out["item_id"], out["timestamp"])
            if row_key in seen_row_keys:
                raise ResultSchemaError(
                    f"Duplicate forecast row for item_id={out['item_id']!r}, "
                    f"timestamp={out['timestamp']!r}."
                )
            seen_row_keys.add(row_key)

            for q_col in quant_cols:
                if q_col in row:
                    key = f"quantile_{q_col.replace('.', '_')}"
                    q_val = float(row[q_col])
                    if not np.isfinite(q_val):
                        raise ResultSchemaError(
                            f"Non-finite quantile {q_col} at row {idx}: {q_val}"
                        )
                    out[key] = q_val

            _validate_quantile_monotonic(row, list(task.quantile_levels))
            forecast_rows.append(out)

        # Validate timestamp ordering (parsed, not string-sorted) and that the
        # forecast starts strictly after the last historical observation.
        parsed_timestamps = [pd.Timestamp(r["timestamp"]) for r in forecast_rows]
        if parsed_timestamps != sorted(parsed_timestamps):
            raise ResultSchemaError("Forecast timestamps are not in order.")
        if parsed_timestamps and parsed_timestamps[0] <= last_historical_ts:
            raise ResultSchemaError(
                f"First forecast timestamp {parsed_timestamps[0]} is not after "
                f"the last historical timestamp {last_historical_ts}."
            )

        result_conversion_time = time.perf_counter() - result_conversion_start

        # Build metadata
        run_id = new_run_id()
        now_iso = datetime.now(timezone.utc).isoformat()
        total_runtime = model_load_time + inference_time + result_conversion_time
        # "Reused" means this call did not trigger a fresh model load -- the
        # logical complement of model_was_loaded, covering both a
        # pre-injected pipeline and a warm call after an earlier cold start.
        pipeline_reused = not model_was_loaded

        pkg_versions = capture_package_versions()
        model_revision = getattr(pipeline, "model_revision", "") or MODEL_REVISION

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
            data_fingerprint=fingerprint_forecast_task(task),
            warnings=tuple(captured_warnings),
            runtime_seconds=round(inference_time, 3),
            model_load_seconds=round(model_load_time, 3),
            inference_seconds=round(inference_time, 3),
            result_conversion_seconds=round(result_conversion_time, 3),
            total_runtime_seconds=round(total_runtime, 3),
            model_was_loaded_this_run=model_was_loaded,
            pipeline_reused=pipeline_reused,
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
            warnings=tuple(captured_warnings),
            backend_name="Chronos2Adapter",
        )

    # ------------------------------------------------------------------
    # Query helpers
    # ------------------------------------------------------------------

    @property
    def pipeline_call_count(self) -> int:
        """Number of times the pipeline was constructed (0 if pre-injected)."""
        return self._pipeline_call_count

    def get_pipeline(self) -> Any:
        """Return the underlying pipeline instance, loading it if needed.

        This is a diagnostic/benchmark accessor for code that needs direct
        pipeline access outside the standard ``forecast()`` flow (e.g.
        multi-series panel measurement, which ``forecast()`` intentionally
        rejects in Stage 0). Prefer ``forecast()`` for all production
        paths -- it is the only path that performs schema/output validation.
        """
        return self._get_pipeline()

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
            pipeline = Chronos2Pipeline.from_pretrained(
                MODEL_ID, revision=MODEL_REVISION, device_map="cpu",
            )
            logger.info("Chronos-2 model loaded.")
            return pipeline
        except Exception as exc:
            raise ModelLoadError(
                f"Failed to load Chronos-2 model '{MODEL_ID}'. "
                "Check your internet connection, disk space, and HF token."
            ) from exc


def _capture_package_versions() -> dict[str, str]:
    """Return a dict of relevant package versions for run metadata.

    Delegates to ``src.telemetry.capture_package_versions``. Kept as a
    local alias for backward compatibility with existing imports from
    other modules and scripts.
    """
    return capture_package_versions()
