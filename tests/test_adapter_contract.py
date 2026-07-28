"""Tests for the Chronos2Adapter using an injected fake pipeline.

No model weights are downloaded during these tests.
"""
from __future__ import annotations

import pytest
from typing import Any, Callable

from src.schemas import ForecastMode, ForecastTask, ForecastResult
from src.forecasting.base import ForecastBackend
from src.forecasting.chronos2_adapter import (
    Chronos2Adapter,
    ConfigurationError,
    InferenceError,
    ResultSchemaError,
)


# ---------------------------------------------------------------------------
# Fake pipeline
# ---------------------------------------------------------------------------

class FakePipeline:
    """Simulates Chronos2Pipeline.predict_df without downloading weights.

    Groups input by item_id and emits one forecast block per distinct
    series, so this fake works for both single-series adapter tests and
    multi-series (panel) benchmark tests. Optional flags produce
    deliberately-invalid output shapes to exercise Chronos2Adapter's
    output-schema validation.
    """
    model_id = "amazon/chronos-2-test"
    model_revision = "fake-revision-001"

    def __init__(
        self,
        fail_on_call: bool = False,
        drop_columns: set[str] | None = None,
        duplicate_row: bool = False,
        non_monotonic_quantiles: bool = False,
        timestamp_before_history: bool = False,
    ):
        self.call_count = 0
        self.fail_on_call = fail_on_call
        self.drop_columns = drop_columns or set()
        self.duplicate_row = duplicate_row
        self.non_monotonic_quantiles = non_monotonic_quantiles
        self.timestamp_before_history = timestamp_before_history
        self.last_kwargs: dict[str, Any] = {}

    def predict_df(self, input_df: Any, **kwargs: Any) -> Any:
        import pandas as pd
        self.call_count += 1
        self.last_kwargs = kwargs

        if self.fail_on_call:
            raise RuntimeError("Fake pipeline simulated failure")

        prediction_length = kwargs.get("prediction_length", 13)
        quantile_levels = kwargs.get("quantile_levels", [0.1, 0.5, 0.9])

        all_rows: list[dict[str, Any]] = []
        for item_id, group in input_df.groupby("item_id", sort=False):
            last_ts = pd.to_datetime(group["timestamp"].iloc[-1])
            try:
                freq = pd.infer_freq(group["timestamp"])
            except (ValueError, TypeError):
                freq = "D"
            if freq is None:
                freq = "D"

            dates = list(pd.date_range(start=last_ts, periods=prediction_length + 1, freq=freq)[1:])
            if self.timestamp_before_history:
                # Shift the whole forecast back by one step so it starts
                # at (not after) the last historical timestamp.
                step = dates[0] - last_ts
                dates = [d - step for d in dates]
            if self.duplicate_row and len(dates) >= 2:
                dates[-1] = dates[-2]

            for i, d in enumerate(dates):
                row: dict[str, Any] = {
                    "item_id": item_id,
                    "timestamp": d,
                    "target_name": "target",
                    "predictions": float(100 + i),
                }
                for q in quantile_levels:
                    if self.non_monotonic_quantiles:
                        row[str(q)] = float(100 - i - 5 * q)  # decreasing with q
                    else:
                        row[str(q)] = float(100 + i - 5 * (1 - q))
                all_rows.append(row)

        df = pd.DataFrame(all_rows)
        for col in self.drop_columns:
            if col in df.columns:
                df = df.drop(columns=[col])
        return df


def _provider(fake: FakePipeline) -> Callable[[], Any]:
    def provider() -> Any:
        return fake
    return provider


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------

class TestChronos2AdapterContract:

    def test_protocol_compatible(self):
        adapter = Chronos2Adapter(pipeline_or_provider=FakePipeline())
        assert isinstance(adapter, ForecastBackend)

    def test_forecast_returns_correct_type(self):
        task = ForecastTask(
            mode=ForecastMode.STANDARD_UNIVARIATE,
            historical_data=(
                {"timestamp": "2024-01-01", "target": 100.0},
                {"timestamp": "2024-01-02", "target": 102.0},
                {"timestamp": "2024-01-03", "target": 101.0},
            ),
            timestamp_column="timestamp",
            target_columns=("target",),
            prediction_length=5,
            quantile_levels=(0.1, 0.5, 0.9),
        )
        adapter = Chronos2Adapter(pipeline_or_provider=FakePipeline())
        result = adapter.forecast(task)
        assert isinstance(result, ForecastResult)
        assert result.backend_name == "Chronos2Adapter"
        assert len(result.forecast_rows) == 5

    def test_output_columns(self):
        task = ForecastTask(
            mode=ForecastMode.STANDARD_UNIVARIATE,
            historical_data=(
                {"timestamp": "2024-01-01", "target": 100.0},
                {"timestamp": "2024-01-02", "target": 102.0},
                {"timestamp": "2024-01-03", "target": 101.0},
            ),
            timestamp_column="timestamp",
            target_columns=("target",),
            prediction_length=3,
            quantile_levels=(0.1, 0.5, 0.9),
        )
        adapter = Chronos2Adapter(pipeline_or_provider=FakePipeline())
        result = adapter.forecast(task)
        row = result.forecast_rows[0]
        assert "run_id" in row
        assert "timestamp" in row
        assert "point_prediction" in row
        assert "quantile_0_1" in row
        assert "quantile_0_5" in row
        assert "quantile_0_9" in row

    def test_rejects_unknown_mode(self):
        # ForecastTask.__post_init__ validates `mode` at construction time,
        # so an invalid mode is rejected by dataclasses.replace() itself
        # (which re-runs __post_init__) -- it never reaches the adapter.
        import dataclasses
        valid = ForecastTask(
            mode=ForecastMode.STANDARD_UNIVARIATE,
            historical_data=({"timestamp": "2024-01-01", "target": 1.0},),
            timestamp_column="timestamp",
            target_columns=("target",),
            prediction_length=3,
            quantile_levels=(0.1, 0.9),
        )
        with pytest.raises(ValueError, match="Unsupported mode"):
            dataclasses.replace(valid, mode="invalid_mode")  # type: ignore[arg-type]

    def test_pipeline_reuse(self):
        fake = FakePipeline()
        adapter = Chronos2Adapter(pipeline_or_provider=_provider(fake))
        task = ForecastTask(
            mode=ForecastMode.STANDARD_UNIVARIATE,
            historical_data=(
                {"timestamp": "2024-01-01", "target": 100.0},
                {"timestamp": "2024-01-02", "target": 102.0},
                {"timestamp": "2024-01-03", "target": 101.0},
            ),
            timestamp_column="timestamp",
            target_columns=("target",),
            prediction_length=3,
            quantile_levels=(0.1, 0.5, 0.9),
        )
        adapter.forecast(task)
        assert adapter.pipeline_call_count == 1
        assert fake.call_count == 1
        adapter.forecast(task)
        assert adapter.pipeline_call_count == 1
        assert fake.call_count == 2

    def test_predict_df_receives_correct_args(self):
        fake = FakePipeline()
        adapter = Chronos2Adapter(pipeline_or_provider=fake)
        task = ForecastTask(
            mode=ForecastMode.STANDARD_UNIVARIATE,
            historical_data=(
                {"timestamp": "2024-01-01", "target": 100.0},
                {"timestamp": "2024-01-02", "target": 102.0},
                {"timestamp": "2024-01-03", "target": 101.0},
            ),
            timestamp_column="timestamp",
            target_columns=("target",),
            prediction_length=7,
            quantile_levels=(0.05, 0.5, 0.95),
        )
        adapter.forecast(task)
        kwargs = fake.last_kwargs
        assert kwargs["prediction_length"] == 7
        assert kwargs["quantile_levels"] == [0.05, 0.5, 0.95]

    def test_context_truncation(self):
        fake = FakePipeline()
        adapter = Chronos2Adapter(pipeline_or_provider=fake)
        rows = tuple(
            {"timestamp": f"2024-01-{i+1:02d}", "target": float(100 + i)}
            for i in range(20)
        )
        task = ForecastTask(
            mode=ForecastMode.STANDARD_UNIVARIATE,
            historical_data=rows,
            timestamp_column="timestamp",
            target_columns=("target",),
            prediction_length=3,
            quantile_levels=(0.1, 0.5, 0.9),
            context_window_cap=10,
        )
        result = adapter.forecast(task)
        assert result.runtime_metadata.context_rows_used == 10

    def test_run_id_uniqueness(self):
        fake = FakePipeline()
        adapter = Chronos2Adapter(pipeline_or_provider=fake)
        task = ForecastTask(
            mode=ForecastMode.STANDARD_UNIVARIATE,
            historical_data=(
                {"timestamp": "2024-01-01", "target": 100.0},
                {"timestamp": "2024-01-02", "target": 102.0},
                {"timestamp": "2024-01-03", "target": 101.0},
            ),
            timestamp_column="timestamp",
            target_columns=("target",),
            prediction_length=3,
            quantile_levels=(0.1, 0.5, 0.9),
        )
        r1 = adapter.forecast(task)
        r2 = adapter.forecast(task)
        assert r1.run_id != r2.run_id
        for row in r1.forecast_rows:
            assert row["run_id"] == r1.run_id

    def test_inference_error_mapped(self):
        failing = FakePipeline(fail_on_call=True)
        adapter = Chronos2Adapter(pipeline_or_provider=failing)
        task = ForecastTask(
            mode=ForecastMode.STANDARD_UNIVARIATE,
            historical_data=(
                {"timestamp": "2024-01-01", "target": 100.0},
                {"timestamp": "2024-01-02", "target": 102.0},
                {"timestamp": "2024-01-03", "target": 101.0},
            ),
            timestamp_column="timestamp",
            target_columns=("target",),
            prediction_length=3,
            quantile_levels=(0.1, 0.5, 0.9),
        )
        with pytest.raises(InferenceError):
            adapter.forecast(task)

    def test_missing_output_columns_detected(self):
        fake = FakePipeline(drop_columns={"predictions"})
        adapter = Chronos2Adapter(pipeline_or_provider=fake)
        task = ForecastTask(
            mode=ForecastMode.STANDARD_UNIVARIATE,
            historical_data=(
                {"timestamp": "2024-01-01", "target": 100.0},
                {"timestamp": "2024-01-02", "target": 102.0},
                {"timestamp": "2024-01-03", "target": 101.0},
            ),
            timestamp_column="timestamp",
            target_columns=("target",),
            prediction_length=3,
            quantile_levels=(0.1, 0.5, 0.9),
        )
        with pytest.raises(ResultSchemaError):
            adapter.forecast(task)

    def test_metadata_contains_required_fields(self):
        fake = FakePipeline()
        adapter = Chronos2Adapter(pipeline_or_provider=fake)
        task = ForecastTask(
            mode=ForecastMode.STANDARD_UNIVARIATE,
            historical_data=(
                {"timestamp": "2024-01-01", "target": 100.0},
                {"timestamp": "2024-01-02", "target": 102.0},
                {"timestamp": "2024-01-03", "target": 101.0},
            ),
            timestamp_column="timestamp",
            target_columns=("target",),
            prediction_length=5,
            quantile_levels=(0.1, 0.5, 0.9),
        )
        result = adapter.forecast(task)
        meta = result.runtime_metadata
        assert meta.run_id != ""
        assert meta.model_id == "amazon/chronos-2"
        assert meta.prediction_length == 5
        assert len(meta.package_versions) > 0
        assert "python" in meta.package_versions
        assert meta.inference_seconds > 0
        assert meta.total_runtime_seconds > 0
        assert meta.model_load_seconds == 0  # pre-injected pipeline
        assert meta.pipeline_reused is True
        # First call with pre-injected pipeline: model not loaded
        assert meta.model_was_loaded_this_run is False

    def test_rejects_multiple_items(self):
        fake = FakePipeline()
        adapter = Chronos2Adapter(pipeline_or_provider=fake)
        task = ForecastTask(
            mode=ForecastMode.STANDARD_UNIVARIATE,
            historical_data=(
                {"timestamp": "2024-01-01", "target": 100.0, "item_id": "A"},
                {"timestamp": "2024-01-01", "target": 200.0, "item_id": "B"},
            ),
            timestamp_column="timestamp",
            target_columns=("target",),
            item_id_column="item_id",
            prediction_length=3,
            quantile_levels=(0.1, 0.5, 0.9),
        )
        with pytest.raises(ConfigurationError, match="requires exactly one time series"):
            adapter.forecast(task)

    def test_pipeline_reused_after_cold_start(self):
        """Cold-then-warm same-adapter case: the exact gap the review flagged
        (pipeline_reused was previously always False after a real cold load,
        the opposite of what "reused" should mean)."""
        fake = FakePipeline()
        adapter = Chronos2Adapter(pipeline_or_provider=_provider(fake))
        task = ForecastTask(
            mode=ForecastMode.STANDARD_UNIVARIATE,
            historical_data=(
                {"timestamp": "2024-01-01", "target": 100.0},
                {"timestamp": "2024-01-02", "target": 102.0},
                {"timestamp": "2024-01-03", "target": 101.0},
            ),
            timestamp_column="timestamp",
            target_columns=("target",),
            prediction_length=3,
            quantile_levels=(0.1, 0.5, 0.9),
        )
        cold = adapter.forecast(task)
        assert cold.runtime_metadata.model_was_loaded_this_run is True
        assert cold.runtime_metadata.pipeline_reused is False

        warm = adapter.forecast(task)
        assert warm.runtime_metadata.model_was_loaded_this_run is False
        assert warm.runtime_metadata.pipeline_reused is True

    def test_get_pipeline_public_accessor(self):
        fake = FakePipeline()
        adapter = Chronos2Adapter(pipeline_or_provider=fake)
        assert adapter.get_pipeline() is fake

    def test_duplicate_forecast_rows_detected(self):
        fake = FakePipeline(duplicate_row=True)
        adapter = Chronos2Adapter(pipeline_or_provider=fake)
        task = ForecastTask(
            mode=ForecastMode.STANDARD_UNIVARIATE,
            historical_data=(
                {"timestamp": "2024-01-01", "target": 100.0},
                {"timestamp": "2024-01-02", "target": 102.0},
                {"timestamp": "2024-01-03", "target": 101.0},
            ),
            timestamp_column="timestamp",
            target_columns=("target",),
            prediction_length=5,
            quantile_levels=(0.1, 0.5, 0.9),
        )
        with pytest.raises(ResultSchemaError, match="Duplicate forecast row"):
            adapter.forecast(task)

    def test_quantile_monotonicity_violation_detected(self):
        fake = FakePipeline(non_monotonic_quantiles=True)
        adapter = Chronos2Adapter(pipeline_or_provider=fake)
        task = ForecastTask(
            mode=ForecastMode.STANDARD_UNIVARIATE,
            historical_data=(
                {"timestamp": "2024-01-01", "target": 100.0},
                {"timestamp": "2024-01-02", "target": 102.0},
                {"timestamp": "2024-01-03", "target": 101.0},
            ),
            timestamp_column="timestamp",
            target_columns=("target",),
            prediction_length=3,
            quantile_levels=(0.1, 0.5, 0.9),
        )
        with pytest.raises(ResultSchemaError, match="not monotonic"):
            adapter.forecast(task)

    def test_forecast_timestamp_before_history_rejected(self):
        fake = FakePipeline(timestamp_before_history=True)
        adapter = Chronos2Adapter(pipeline_or_provider=fake)
        task = ForecastTask(
            mode=ForecastMode.STANDARD_UNIVARIATE,
            historical_data=(
                {"timestamp": "2024-01-01", "target": 100.0},
                {"timestamp": "2024-01-02", "target": 102.0},
                {"timestamp": "2024-01-03", "target": 101.0},
            ),
            timestamp_column="timestamp",
            target_columns=("target",),
            prediction_length=3,
            quantile_levels=(0.1, 0.5, 0.9),
        )
        with pytest.raises(ResultSchemaError, match="not after"):
            adapter.forecast(task)

    def test_context_truncation_warning_emitted(self):
        from src.schemas import WarningCode
        fake = FakePipeline()
        adapter = Chronos2Adapter(pipeline_or_provider=fake)
        rows = tuple(
            {"timestamp": f"2024-01-{i+1:02d}", "target": float(100 + i)}
            for i in range(20)
        )
        task = ForecastTask(
            mode=ForecastMode.STANDARD_UNIVARIATE,
            historical_data=rows,
            timestamp_column="timestamp",
            target_columns=("target",),
            prediction_length=3,
            quantile_levels=(0.1, 0.5, 0.9),
            context_window_cap=10,
        )
        result = adapter.forecast(task)
        assert any(WarningCode.CONTEXT_TRUNCATION.value in w for w in result.warnings)


class TestForecastBackendProtocol:
    def test_backend_is_protocol_compatible(self):
        adapter = Chronos2Adapter(pipeline_or_provider=FakePipeline())
        assert isinstance(adapter, ForecastBackend)

    def test_default_provider_not_invoked(self):
        """Ensure the real Chronos-2 model provider is never invoked during tests.

        All tests must inject a fake pipeline. This test confirms the default
        provider raises ModelLoadError (no model weights available in CI).
        """
        adapter = Chronos2Adapter()  # No fake injected
        task = ForecastTask(
            mode=ForecastMode.STANDARD_UNIVARIATE,
            historical_data=(
                {"timestamp": "2024-01-01", "target": 100.0},
                {"timestamp": "2024-01-02", "target": 102.0},
                {"timestamp": "2024-01-03", "target": 101.0},
            ),
            timestamp_column="timestamp",
            target_columns=("target",),
            prediction_length=3,
            quantile_levels=(0.1, 0.5, 0.9),
        )
        from src.forecasting.chronos2_adapter import ModelLoadError
        with pytest.raises(ModelLoadError):
            adapter.forecast(task)
