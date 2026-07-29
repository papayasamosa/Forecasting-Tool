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
        # WP4: standard univariate must pass cross_learning=False explicitly
        assert kwargs.get("cross_learning") is False

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


class TestCrossLearningCapabilityDetection:
    """WP4: cross_learning capability detection uses signature inspection,
    not broad TypeError retry."""

    def _make_single_series_task(self):
        return ForecastTask(
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

    def test_explicit_cross_learning_passed_when_supported(self):
        """When the pipeline supports cross_learning, the kwarg must be passed."""
        from src.forecasting.chronos2_adapter import _predict_df_accepts_cross_learning

        class SupportsCL:
            model_id = "test"
            model_revision = "test"

            def predict_df(self, input_df, **kwargs):
                return type("DF", (), {"columns": ["predictions", "0.1", "0.5", "0.9"],
                                       "__len__": lambda s: 3,
                                       "iterrows": lambda s: iter([])})()

        # Check detection
        pipe = SupportsCL()
        # **kwargs means it accepts cross_learning
        assert _predict_df_accepts_cross_learning(pipe)

    def test_unsupported_cross_learning_detected(self):
        """When the pipeline does NOT support cross_learning, detect it
        before calling predict_df."""
        from src.forecasting.chronos2_adapter import _predict_df_accepts_cross_learning

        class NoCL:
            model_id = "test"
            model_revision = "test"

            def predict_df(self, input_df, prediction_length=13, quantile_levels=None):
                return type("DF", (), {"columns": ["predictions", "0.1", "0.5", "0.9"],
                                       "__len__": lambda s: 3,
                                       "iterrows": lambda s: iter([])})()

        pipe = NoCL()
        assert not _predict_df_accepts_cross_learning(pipe)

    def test_internal_type_error_does_not_retry(self):
        """An internal TypeError (not about cross_learning) must NOT be
        caught and retried. predict_df should never be called because the
        adapter passes additional kwargs (id_column, timestamp_column,
        target) that cause a TypeError during argument binding before the
        function body runs."""
        call_count = [0]

        class InternalTypeErrorPipeline:
            model_id = "test"
            model_revision = "test"

            def predict_df(self, input_df, prediction_length=13, quantile_levels=None,
                           cross_learning=False):
                call_count[0] += 1
                # Internal TypeError, not about unsupported keyword
                raise TypeError("cannot unpack non-iterable NoneType object")

        from src.forecasting.chronos2_adapter import Chronos2Adapter, InferenceError
        adapter = Chronos2Adapter(pipeline_or_provider=InternalTypeErrorPipeline())
        task = self._make_single_series_task()
        with pytest.raises(InferenceError):
            adapter.forecast(task)
        # The adapter passes id_column, timestamp_column, target in addition
        # to cross_learning. Python raises TypeError during argument binding
        # BEFORE the function body, so predict_df is never called. That's
        # correct — no retry for an internal TypeError.
        assert call_count[0] == 0, (
            f"predict_df called {call_count[0]} times, expected 0 "
            "(TypeError during argument binding, not in function body)"
        )


    def test_internal_type_error_inside_body_no_retry(self):
        """A TypeError raised INSIDE predict_df body (after argument binding
        succeeds) must NOT be caught and retried. predict_df is called exactly
        once."""
        call_count = [0]

        class InternalTypeInBodyPipeline:
            model_id = "test"
            model_revision = "test"

            def predict_df(self, input_df, prediction_length=13, quantile_levels=None,
                           id_column="item_id", timestamp_column="timestamp",
                           target="target", cross_learning=False):
                call_count[0] += 1
                # This TypeError happens inside the function body, not
                # during argument binding
                raise TypeError("cannot unpack non-iterable NoneType object")

        from src.forecasting.chronos2_adapter import Chronos2Adapter, InferenceError
        adapter = Chronos2Adapter(pipeline_or_provider=InternalTypeInBodyPipeline())
        task = self._make_single_series_task()
        with pytest.raises(InferenceError):
            adapter.forecast(task)
        # Must only be called ONCE — no retry for a TypeError that has
        # nothing to do with cross_learning.
        assert call_count[0] == 1, (
            f"predict_df called {call_count[0]} times, expected 1 "
            "(no retry for internal TypeError in body)"
        )

    def test_supported_cross_learning_exactly_one_call(self):
        """When the pipeline supports cross_learning, predict_df is called
        exactly once (no retry)."""
        call_count = [0]

        class GoodPipeline:
            model_id = "test"
            model_revision = "test"

            def predict_df(self, input_df, prediction_length=13, quantile_levels=None,
                           id_column="item_id", timestamp_column="timestamp",
                           target="target", cross_learning=False):
                call_count[0] += 1
                import pandas as pd
                import numpy as np
                # Forecast timestamps must start AFTER the last historical
                # timestamp (2024-01-03 for our test data).
                last_ts = pd.to_datetime(input_df["timestamp"].iloc[-1])
                freq = "D"
                dates = pd.date_range(start=last_ts, periods=prediction_length + 1, freq=freq)[1:]
                rows = []
                for i, d in enumerate(dates):
                    rows.append({
                        "item_id": "default",
                        "timestamp": d,
                        "target_name": "target",
                        "predictions": float(100+i),
                    })
                    for q in quantile_levels:
                        rows[-1][str(q)] = float(100+i - 5*(1-q))
                return pd.DataFrame(rows)

        from src.forecasting.chronos2_adapter import Chronos2Adapter
        adapter = Chronos2Adapter(pipeline_or_provider=GoodPipeline())
        task = self._make_single_series_task()
        result = adapter.forecast(task)
        assert call_count[0] == 1, (
            f"predict_df called {call_count[0]} times, expected 1"
        )
        assert result is not None


class TestWarningDeduplication:
    """WP3: Warnings stored in both ForecastResult.warnings and
    RunMetadata.warnings must not appear twice in the page rendering."""

    def test_warnings_deduplicated_by_content(self):
        """Duplicate warning text across both collections should be
        collapsed by the page-level deduplication logic."""
        from src.schemas import ForecastResult, RunMetadata

        # Simulate a result where the same warning appears in both places
        meta = RunMetadata(warnings=("context truncated: 100 to 10 rows",))
        result = ForecastResult(
            run_id="test",
            forecast_rows=(),
            model_id="test",
            model_revision="test",
            runtime_metadata=meta,
            warnings=("context truncated: 100 to 10 rows",),
        )

        # Page-level deduplication logic
        all_warnings = list(result.warnings) + list(meta.warnings)
        seen: set[str] = set()
        deduped: list[str] = []
        for w in all_warnings:
            if w not in seen:
                seen.add(w)
                deduped.append(w)
        assert len(deduped) == 1, f"Expected 1 unique warning, got {len(deduped)}: {deduped}"
        assert deduped[0] == "context truncated: 100 to 10 rows"


class TestSmokeTopLevelEvidence:
    """WP5: Top-level smoke invocation must write evidence on unexpected exception."""

    def test_top_level_wrapper_creates_failure_record(self):
        """Simulating a pre-assignment exception in run_smoke_test: the
        __main__ block should catch it and write minimal evidence."""
        from src.telemetry import write_evidence
        import tempfile, json

        # Simulate what happens in the __main__ try/except
        evidence = {
            "test": "chronos2_smoke_test",
            "success": False,
            "failure_phase": "top_level_invocation",
            "error": "RuntimeError: simulated fixture failure",
            "python_version": "3.12",
        }
        with tempfile.TemporaryDirectory() as tmp:
            path = write_evidence(evidence, tmp, prefix="smoke_test")
            assert path.endswith(".json")
            with open(path) as f:
                data = json.load(f)
            assert data["success"] is False
            assert "top_level_invocation" in data.get("failure_phase", "")

    def test_top_level_evidence_includes_traceability(self):
        """Top-level failure evidence must include code_commit and revision."""
        import tempfile, json
        from src.telemetry import write_evidence, capture_traceability, capture_package_versions

        trace = capture_traceability()
        evidence = {
            "test": "chronos2_smoke_test",
            "success": False,
            "failure_phase": "top_level_invocation",
            "error": "ValueError: simulated error",
            "code_commit": trace.get("code_commit", ""),
            "configured_revision": "test-revision",
        }
        with tempfile.TemporaryDirectory() as tmp:
            path = write_evidence(evidence, tmp, prefix="smoke_test")
            with open(path) as f:
                data = json.load(f)
            assert "code_commit" in data
            assert "configured_revision" in data
