"""Tests for the benchmarking module.

These tests verify that benchmark scenarios construct correctly and produce
valid output. They do NOT load the Chronos-2 model.
"""
from __future__ import annotations

import os
import json
import tempfile
from typing import Any, Callable

import pytest

from src.config import MODEL_ID
from src.schemas import ForecastMode, ForecastTask, ForecastResult, RunMetadata
from src.benchmarking import (
    BenchmarkResult,
    BenchmarkSample,
    _weekly_fixture,
    _panel_fixture,
    _make_task,
    _write_json,
    _write_markdown,
    run_benchmarks,
    Chronos2Adapter,
)
from tests.test_adapter_contract import FakePipeline


# ---------------------------------------------------------------------------
# Fake adapter factory for testing without model download
# ---------------------------------------------------------------------------


def _fake_adapter_factory() -> Chronos2Adapter:
    """Return a Chronos2Adapter with a pre-injected FakePipeline."""
    return Chronos2Adapter(pipeline_or_provider=FakePipeline())


class TestBenchmarkHelpers:
    def test_weekly_fixture_shape(self):
        df = _weekly_fixture(260)
        assert len(df) == 260
        assert list(df.columns) == ["timestamp", "target"]

    def test_panel_fixture_shape(self):
        df = _panel_fixture(n_series=5, n_points=104)
        assert len(df) == 5 * 104
        assert "item_id" in df.columns

    def test_make_task(self):
        df = _weekly_fixture(50)
        task = _make_task(df, horizon=7)
        assert task.prediction_length == 7
        assert len(task.historical_data) == 50


class TestBenchmarkResult:
    def test_json_round_trip(self):
        r = BenchmarkResult(scenario="test", context_rows=100, horizon=13)
        r.samples.append(BenchmarkSample(label="test", duration_seconds=1.0))
        with tempfile.TemporaryDirectory() as tmp:
            path = os.path.join(tmp, "test.json")
            _write_json([r], path)
            with open(path) as f:
                data = json.load(f)
            assert len(data) == 1
            assert data[0]["scenario"] == "test"
            assert len(data[0]["samples"]) == 1

    def test_markdown_output(self):
        r = BenchmarkResult(scenario="test_md", context_rows=50, horizon=5)
        r.samples.append(BenchmarkSample(label="cold", duration_seconds=2.5))
        with tempfile.TemporaryDirectory() as tmp:
            path = os.path.join(tmp, "test.md")
            _write_markdown([r], path)
            with open(path) as f:
                content = f.read()
            assert "test_md" in content
            assert "cold" in content
            assert "2.500" in content


class TestRunBenchmarks:
    """Test the full benchmark runner with fake adapters."""

    def test_all_scenarios_present(self):
        with tempfile.TemporaryDirectory() as tmp:
            results = run_benchmarks(
                output_dir=tmp,
                adapter_factory=_fake_adapter_factory,
            )
            scenarios = {r.scenario for r in results}
            assert "weekly_260_13" in scenarios
            assert "panel_5_series" in scenarios
            assert "10_rolling_calls" in scenarios
            assert "failure_and_retry" in scenarios

    def test_no_early_termination(self):
        with tempfile.TemporaryDirectory() as tmp:
            results = run_benchmarks(
                output_dir=tmp,
                adapter_factory=_fake_adapter_factory,
            )
            # All 4 scenarios should produce results
            assert len(results) == 4

    def test_failure_and_retry_recorded(self):
        with tempfile.TemporaryDirectory() as tmp:
            results = run_benchmarks(
                output_dir=tmp,
                adapter_factory=_fake_adapter_factory,
            )
            retry_result = [r for r in results if r.scenario == "failure_and_retry"][0]
            labels = {s.label for s in retry_result.samples}
            assert "injection_failure_test" in labels
            assert "retry_success" in labels

            # Failure should be recorded as not success
            fail_sample = [s for s in retry_result.samples if s.label == "injection_failure_test"][0]
            assert fail_sample.success is False

            # Retry should be recorded as success
            retry_sample = [s for s in retry_result.samples if s.label == "retry_success"][0]
            assert retry_sample.success is True

    def test_successful_zero_duration_not_dropped(self):
        """The retry_success sample must not be filtered by duration."""
        with tempfile.TemporaryDirectory() as tmp:
            results = run_benchmarks(
                output_dir=tmp,
                adapter_factory=_fake_adapter_factory,
            )
            for r in results:
                for s in r.samples:
                    if s.success:
                        # All successful samples must be present regardless of duration
                        pass
            # Specifically check retry_success exists
            retry_result = [r for r in results if r.scenario == "failure_and_retry"][0]
            retry_sample = [s for s in retry_result.samples if s.label == "retry_success"]
            assert len(retry_sample) == 1

    def test_output_files_written(self):
        with tempfile.TemporaryDirectory() as tmp:
            results = run_benchmarks(
                output_dir=tmp,
                adapter_factory=_fake_adapter_factory,
            )
            files = os.listdir(tmp)
            json_files = [f for f in files if f.endswith(".json")]
            md_files = [f for f in files if f.endswith(".md")]
            assert len(json_files) >= 1
            assert len(md_files) >= 1

    def test_weekly_scenario_successful(self):
        with tempfile.TemporaryDirectory() as tmp:
            results = run_benchmarks(
                output_dir=tmp,
                adapter_factory=_fake_adapter_factory,
            )
            weekly = [r for r in results if r.scenario == "weekly_260_13"][0]
            # Cold and warm should both succeed
            cold = [s for s in weekly.samples if s.label == "cold_forecast"][0]
            warm = [s for s in weekly.samples if s.label == "warm_forecast"][0]
            assert cold.success is True
            assert warm.success is True
            # Model should not be loaded (pre-injected pipeline)
            assert cold.model_load_seconds == 0

    def test_rolling_calls_count(self):
        with tempfile.TemporaryDirectory() as tmp:
            results = run_benchmarks(
                output_dir=tmp,
                adapter_factory=_fake_adapter_factory,
            )
            rolling = [r for r in results if r.scenario == "10_rolling_calls"][0]
            # There should be folds + total
            fold_labels = [s.label for s in rolling.samples if s.label.startswith("fold_")]
            assert len(fold_labels) == 10
            assert "total_10_folds" in {s.label for s in rolling.samples}

    def test_failure_and_retry_uses_single_adapter_instance(self):
        """Scenario 4 must retry on the SAME adapter/pipeline that failed,
        not construct a fresh one -- so run_benchmarks should only ask the
        factory for adapters for scenario 1 only (panel reuses scenario 1's
        pipeline)."""
        call_log: list[Chronos2Adapter] = []

        def counting_factory() -> Chronos2Adapter:
            a = _fake_adapter_factory()
            call_log.append(a)
            return a

        with tempfile.TemporaryDirectory() as tmp:
            run_benchmarks(output_dir=tmp, adapter_factory=counting_factory)
        # Only one adapter is created (scenario 1); panel scenario reuses it
        assert len(call_log) == 1

    def test_no_test_package_import_in_benchmarking(self):
        """Production code must not depend on the tests/ tree (would break
        under a packaged install that excludes tests/)."""
        import src.benchmarking as benchmarking_module
        src_path = benchmarking_module.__file__
        with open(src_path, encoding="utf-8") as f:
            source = f.read()
        assert "from tests" not in source
        assert "import tests" not in source

    def test_panel_scenario_succeeds_with_valid_pipeline(self):
        with tempfile.TemporaryDirectory() as tmp:
            results = run_benchmarks(output_dir=tmp, adapter_factory=_fake_adapter_factory)
            panel = [r for r in results if r.scenario == "panel_5_series"][0]
            sample = [s for s in panel.samples if s.label == "panel_forecast_direct"][0]
            assert sample.success is True

    def test_panel_scenario_flags_non_monotonic_quantiles(self):
        def broken_factory() -> Chronos2Adapter:
            return Chronos2Adapter(pipeline_or_provider=FakePipeline(non_monotonic_quantiles=True))

        with tempfile.TemporaryDirectory() as tmp:
            results = run_benchmarks(output_dir=tmp, adapter_factory=broken_factory)
            panel = [r for r in results if r.scenario == "panel_5_series"][0]
            sample = [s for s in panel.samples if s.label == "panel_forecast_direct"][0]
            assert sample.success is False
            assert sample.error_type == "ResultSchemaError"

    def test_baseline_rss_recorded(self):
        with tempfile.TemporaryDirectory() as tmp:
            results = run_benchmarks(output_dir=tmp, adapter_factory=_fake_adapter_factory)
            weekly = [r for r in results if r.scenario == "weekly_260_13"][0]
            cold = [s for s in weekly.samples if s.label == "cold_forecast"][0]
            assert isinstance(cold.baseline_rss_mb, float)


class TestMarkdownReport:
    def test_includes_baseline_and_error_columns(self):
        r = BenchmarkResult(scenario="test_err", context_rows=10, horizon=3)
        r.samples.append(BenchmarkSample(
            label="failing_sample", success=False,
            error_type="InferenceError", error_message="boom",
            baseline_rss_mb=123.4,
        ))
        with tempfile.TemporaryDirectory() as tmp:
            path = os.path.join(tmp, "test.md")
            _write_markdown([r], path)
            with open(path, encoding="utf-8") as f:
                content = f.read()
            assert "Baseline RSS (MB)" in content
            assert "Error Type" in content
            assert "InferenceError" in content
            assert "boom" in content


class TestPanelValidation:
    """Tests for the _validate_panel_output function."""

    def _make_valid_panel_output(self, n_series=5, horizon=13):
        """Build a valid panel output DataFrame."""
        import pandas as pd
        import numpy as np
        rows = []
        quantile_levels = [0.1, 0.5, 0.9]
        for s in range(n_series):
            item_id = f"series_{s}"
            last_ts = pd.Timestamp("2024-04-07")
            dates = pd.date_range(start=last_ts, periods=horizon + 1, freq="W")[1:]
            for i, d in enumerate(dates):
                row = {
                    "item_id": item_id,
                    "timestamp": d,
                    "predictions": float(100 + i),
                }
                for q in quantile_levels:
                    row[str(q)] = float(100 + i - 5 * (1 - q))
                rows.append(row)
        return pd.DataFrame(rows)

    def _make_historical_data(self, n_series=5):
        """Build matching historical data ending before the forecast."""
        import pandas as pd
        import numpy as np
        rows = []
        for s in range(n_series):
            dates = pd.date_range("2022-01-03", periods=104, freq="W")
            for i, d in enumerate(dates):
                rows.append({
                    "item_id": f"series_{s}",
                    "timestamp": d,
                    "target": float(100 + s * 20 + i),
                })
        return pd.DataFrame(rows)

    def test_valid_panel_passes(self):
        df = self._make_valid_panel_output()
        hist = self._make_historical_data()
        expected_ids = set(hist["item_id"].unique())
        from src.benchmarking import _validate_panel_output
        # Should not raise
        _validate_panel_output(
            pred_df=df,
            expected_item_ids=expected_ids,
            expected_horizon=13,
            quantile_levels=[0.1, 0.5, 0.9],
            historical_data=hist,
        )

    def test_missing_quantile_column(self):
        df = self._make_valid_panel_output()
        df = df.drop(columns=["0.5"])
        hist = self._make_historical_data()
        expected_ids = set(hist["item_id"].unique())
        from src.benchmarking import _validate_panel_output, ResultSchemaError
        with pytest.raises(ResultSchemaError, match="Missing requested quantile column"):
            _validate_panel_output(
                pred_df=df, expected_item_ids=expected_ids,
                expected_horizon=13, quantile_levels=[0.1, 0.5, 0.9],
                historical_data=hist,
            )

    def test_nan_in_quantile_column(self):
        df = self._make_valid_panel_output()
        df.loc[0, "0.5"] = float("nan")
        hist = self._make_historical_data()
        expected_ids = set(hist["item_id"].unique())
        from src.benchmarking import _validate_panel_output, ResultSchemaError
        with pytest.raises(ResultSchemaError, match="Non-finite values in quantile column"):
            _validate_panel_output(
                pred_df=df, expected_item_ids=expected_ids,
                expected_horizon=13, quantile_levels=[0.1, 0.5, 0.9],
                historical_data=hist,
            )

    def test_wrong_row_count(self):
        df = self._make_valid_panel_output()
        df = df.iloc[:-5]  # drop 5 rows
        hist = self._make_historical_data()
        expected_ids = set(hist["item_id"].unique())
        from src.benchmarking import _validate_panel_output, ResultSchemaError
        with pytest.raises(ResultSchemaError, match="expected.*rows"):
            _validate_panel_output(
                pred_df=df, expected_item_ids=expected_ids,
                expected_horizon=13, quantile_levels=[0.1, 0.5, 0.9],
                historical_data=hist,
            )

    def test_wrong_item_ids(self):
        df = self._make_valid_panel_output()
        df.loc[df["item_id"] == "series_0", "item_id"] = "unknown_series"
        hist = self._make_historical_data()
        expected_ids = set(hist["item_id"].unique())
        from src.benchmarking import _validate_panel_output, ResultSchemaError
        with pytest.raises(ResultSchemaError, match="item_id set mismatch"):
            _validate_panel_output(
                pred_df=df, expected_item_ids=expected_ids,
                expected_horizon=13, quantile_levels=[0.1, 0.5, 0.9],
                historical_data=hist,
            )

    def test_non_finite_predictions(self):
        df = self._make_valid_panel_output()
        df.loc[0, "predictions"] = float("inf")
        hist = self._make_historical_data()
        expected_ids = set(hist["item_id"].unique())
        from src.benchmarking import _validate_panel_output, ResultSchemaError
        with pytest.raises(ResultSchemaError, match="Non-finite point predictions"):
            _validate_panel_output(
                pred_df=df, expected_item_ids=expected_ids,
                expected_horizon=13, quantile_levels=[0.1, 0.5, 0.9],
                historical_data=hist,
            )

    def test_duplicate_item_timestamp_rows(self):
        import pandas as pd
        df = self._make_valid_panel_output()
        # Make the last row's timestamp match the second-to-last (same item)
        last_idx = df.index[-1]
        second_last_idx = df.index[-2]
        df.loc[last_idx, "timestamp"] = df.loc[second_last_idx, "timestamp"]
        hist = self._make_historical_data()
        expected_ids = set(hist["item_id"].unique())
        from src.benchmarking import _validate_panel_output, ResultSchemaError
        with pytest.raises(ResultSchemaError, match="Duplicate"):
            _validate_panel_output(
                pred_df=df, expected_item_ids=expected_ids,
                expected_horizon=13, quantile_levels=[0.1, 0.5, 0.9],
                historical_data=hist,
            )

    def test_timestamps_not_after_history(self):
        import pandas as pd
        df = self._make_valid_panel_output()
        # Shift all timestamps back so they overlap with history
        df["timestamp"] = pd.to_datetime(df["timestamp"]) - pd.DateOffset(years=1)
        hist = self._make_historical_data()
        expected_ids = set(hist["item_id"].unique())
        from src.benchmarking import _validate_panel_output, ResultSchemaError
        with pytest.raises(ResultSchemaError, match="not after"):
            _validate_panel_output(
                pred_df=df, expected_item_ids=expected_ids,
                expected_horizon=13, quantile_levels=[0.1, 0.5, 0.9],
                historical_data=hist,
            )


class TestOnePipeline:
    """WP3: The panel and rolling scenarios reuse the same adapter/pipeline."""

    def test_panel_reuses_weekly_adapter(self):
        """The panel scenario should NOT create a second adapter instance."""
        call_log: list[Chronos2Adapter] = []

        def counting_factory() -> Chronos2Adapter:
            a = Chronos2Adapter(pipeline_or_provider=FakePipeline())
            call_log.append(a)
            return a

        with tempfile.TemporaryDirectory() as tmp:
            run_benchmarks(output_dir=tmp, adapter_factory=counting_factory)
        # Only 1 adapter: the weekly + rolling + panel all share it
        assert len(call_log) == 1

    def test_rolling_reuses_weekly_adapter(self):
        """The rolling scenario reuses the weekly adapter (tests already
        pass since rolling uses adapter.forecast() directly)."""
        call_log: list[Chronos2Adapter] = []

        def counting_factory() -> Chronos2Adapter:
            a = Chronos2Adapter(pipeline_or_provider=FakePipeline())
            call_log.append(a)
            return a

        with tempfile.TemporaryDirectory() as tmp:
            run_benchmarks(output_dir=tmp, adapter_factory=counting_factory)
        assert len(call_log) == 1


class TestPanelFailureEvidence:
    """WP2: Failed panel runs preserve memory and timing evidence."""

    def test_failed_panel_retains_memory_fields(self):
        """When panel inference fails, memory fields must be populated."""

        class FailingPipeline:
            model_id = "amazon/chronos-2-test"
            model_revision = "fake-revision-001"

            def predict_df(self, input_df, **kwargs):
                raise RuntimeError("Panel inference simulated failure")

        def failing_factory() -> Chronos2Adapter:
            return Chronos2Adapter(pipeline_or_provider=FailingPipeline())

        with tempfile.TemporaryDirectory() as tmp:
            results = run_benchmarks(output_dir=tmp, adapter_factory=failing_factory)
            panel = [r for r in results if r.scenario == "panel_5_series"][0]
            sample = [s for s in panel.samples if s.label == "panel_forecast_direct"][0]
            assert sample.success is False
            # Memory fields should be populated
            assert isinstance(sample.baseline_rss_mb, float)
            assert isinstance(sample.rss_mb, float)
            assert isinstance(sample.peak_rss_mb, float)
            assert isinstance(sample.duration_seconds, float)
            assert sample.error_type == "RuntimeError"
            assert "simulated failure" in sample.error_message


class TestSuiteEvaluation:
    """Tests for _evaluate_suite and scenario pass/fail."""

    def test_suite_passes_with_valid_factory(self):
        """The full suite should pass with a valid fake pipeline."""
        with tempfile.TemporaryDirectory() as tmp:
            results = run_benchmarks(output_dir=tmp, adapter_factory=_fake_adapter_factory)
            from src.benchmarking import _evaluate_suite
            assert _evaluate_suite(results) is True
            for r in results:
                assert r.scenario_passed is True

    def test_cold_failure_causes_scenario_fail(self):
        """If cold forecast fails, scenario should fail."""

        class FailOncePipeline:
            model_id = "amazon/chronos-2-test"
            model_revision = "fake-revision-001"
            call_count = 0

            def predict_df(self, input_df, **kwargs):
                self.__class__.call_count += 1
                if self.__class__.call_count == 1:
                    raise RuntimeError("Cold forecast failure")
                import pandas as pd
                prediction_length = kwargs.get("prediction_length", 13)
                quantile_levels = kwargs.get("quantile_levels", [0.1, 0.5, 0.9])
                rows = []
                for i in range(prediction_length):
                    row = {"item_id": "default", "timestamp": pd.Timestamp("2024-01-01") + pd.Timedelta(days=7*i),
                           "target_name": "target", "predictions": float(100+i)}
                    for q in quantile_levels:
                        row[str(q)] = float(100+i-5*(1-q))
                    rows.append(row)
                return pd.DataFrame(rows)

        def factory() -> Chronos2Adapter:
            return Chronos2Adapter(pipeline_or_provider=FailOncePipeline())

        with tempfile.TemporaryDirectory() as tmp:
            results = run_benchmarks(output_dir=tmp, adapter_factory=factory)
            weekly = [r for r in results if r.scenario == "weekly_260_13"][0]
            assert weekly.scenario_passed is False
            from src.benchmarking import _evaluate_suite
            assert _evaluate_suite(results) is False

    def test_failure_and_retry_scenario_passed(self):
        """Failure+retry scenario should pass when failure occurs and retry succeeds."""
        with tempfile.TemporaryDirectory() as tmp:
            results = run_benchmarks(output_dir=tmp, adapter_factory=_fake_adapter_factory)
            retry_scenario = [r for r in results if r.scenario == "failure_and_retry"][0]
            assert retry_scenario.scenario_passed is True

    def test_rolling_requires_exactly_ten_successes(self):
        """Rolling scenario must have exactly 10 successful folds for scenario_passed."""

        class FailingRollPipeline:
            model_id = "amazon/chronos-2-test"
            model_revision = "fake-revision-001"
            call_count = 0

            def predict_df(self, input_df, **kwargs):
                self.__class__.call_count += 1
                if self.__class__.call_count == 5:
                    raise RuntimeError("Rolling fold 4 failure")
                import pandas as pd
                prediction_length = kwargs.get("prediction_length", 13)
                quantile_levels = kwargs.get("quantile_levels", [0.1, 0.5, 0.9])
                rows = []
                for i in range(prediction_length):
                    row = {"item_id": "default", "timestamp": pd.Timestamp("2024-01-01") + pd.Timedelta(days=7*i),
                           "target_name": "target", "predictions": float(100+i)}
                    for q in quantile_levels:
                        row[str(q)] = float(100+i-5*(1-q))
                    rows.append(row)
                return pd.DataFrame(rows)

        def factory() -> Chronos2Adapter:
            return Chronos2Adapter(pipeline_or_provider=FailingRollPipeline())

        with tempfile.TemporaryDirectory() as tmp:
            results = run_benchmarks(output_dir=tmp, adapter_factory=factory)
            rolling = [r for r in results if r.scenario == "10_rolling_calls"][0]
            assert rolling.scenario_passed is False


class TestPanelChronology:
    """WP4: Panel chronology validation tests."""

    def _make_panel_output(self, n_series=5, horizon=13, shuffle_order=False):
        """Build a valid panel output, optionally with shuffled row order."""
        import pandas as pd
        import numpy as np
        rows = []
        quantile_levels = [0.1, 0.5, 0.9]
        for s in range(n_series):
            item_id = f"series_{s}"
            last_ts = pd.Timestamp("2024-04-07")
            dates = pd.date_range(start=last_ts, periods=horizon + 1, freq="W")[1:]
            for i, d in enumerate(dates):
                row = {
                    "item_id": item_id,
                    "timestamp": d,
                    "predictions": float(100 + i),
                }
                for q in quantile_levels:
                    row[str(q)] = float(100 + i - 5 * (1 - q))
                rows.append(row)
        df = pd.DataFrame(rows)
        if shuffle_order:
            df = df.sample(frac=1, random_state=42).reset_index(drop=True)
        return df

    def _make_historical_data(self, n_series=5, staggered=False):
        """Build historical data, optionally with staggered end dates."""
        import pandas as pd
        import numpy as np
        rows = []
        for s in range(n_series):
            if staggered:
                # Each series ends at a different time
                n_points = 104 - s * 10
            else:
                n_points = 104
            dates = pd.date_range("2022-01-03", periods=n_points, freq="W")
            for i, d in enumerate(dates):
                rows.append({
                    "item_id": f"series_{s}",
                    "timestamp": d,
                    "target": float(100 + s * 20 + i),
                })
        return pd.DataFrame(rows)

    def test_unsorted_panel_rows_detected(self):
        """Rows returned out of order should be detected (not sorted first)."""
        df = self._make_panel_output(shuffle_order=True)
        hist = self._make_historical_data()
        expected_ids = set(hist["item_id"].unique())
        from src.benchmarking import _validate_panel_output, ResultSchemaError
        with pytest.raises(ResultSchemaError, match="not in order"):
            _validate_panel_output(
                pred_df=df, expected_item_ids=expected_ids,
                expected_horizon=13, quantile_levels=[0.1, 0.5, 0.9],
                historical_data=hist,
            )

    def test_staggered_history_per_item(self):
        """Each item's forecast must be after its own historical end."""
        import pandas as pd
        df = self._make_panel_output()
        # Use series_2 which has shorter history (104-20=84 weeks).
        # Its forecast starts at 2024-04-07, history ends ~2023-09-17.
        # Shift forecast by 1 year back so it overlaps with history.
        mask = df["item_id"] == "series_2"
        df.loc[mask, "timestamp"] = pd.to_datetime(df.loc[mask, "timestamp"]) - pd.DateOffset(years=1)
        hist = self._make_historical_data(staggered=True)
        expected_ids = set(hist["item_id"].unique())
        from src.benchmarking import _validate_panel_output, ResultSchemaError
        with pytest.raises(ResultSchemaError, match="not after"):
            _validate_panel_output(
                pred_df=df, expected_item_ids=expected_ids,
                expected_horizon=13, quantile_levels=[0.1, 0.5, 0.9],
                historical_data=hist,
            )

    def test_valid_staggered_history_passes(self):
        """Staggered histories with valid forecasts should pass."""
        df = self._make_panel_output()
        hist = self._make_historical_data(staggered=True)
        expected_ids = set(hist["item_id"].unique())
        from src.benchmarking import _validate_panel_output
        _validate_panel_output(
            pred_df=df, expected_item_ids=expected_ids,
            expected_horizon=13, quantile_levels=[0.1, 0.5, 0.9],
            historical_data=hist,
        )


class TestCrossLearningControl:
    """WP5: Cross-learning is explicitly controlled."""

    def test_predict_df_receives_cross_learning_false(self):
        """The panel predict_df call should pass cross_learning=False."""
        from tests.test_adapter_contract import FakePipeline
        from src.benchmarking import run_benchmarks
        # Use a pipeline that records all kwargs per call
        class TrackingPipeline:
            model_id = "amazon/chronos-2-test"
            model_revision = "fake-revision-001"
            all_kwargs: list[dict] = []

            def predict_df(self, input_df, **kwargs):
                self.__class__.all_kwargs.append(dict(kwargs))
                import pandas as pd
                prediction_length = kwargs.get("prediction_length", 13)
                quantile_levels = kwargs.get("quantile_levels", [0.1, 0.5, 0.9])
                rows = []
                for item_id in input_df["item_id"].unique():
                    last_ts = pd.to_datetime(input_df["timestamp"].iloc[-1])
                    dates = pd.date_range(start=last_ts, periods=prediction_length+1, freq="W")[1:]
                    for i, d in enumerate(dates):
                        row = {"item_id": item_id, "timestamp": d, "target_name": "target",
                               "predictions": float(100+i)}
                        for q in quantile_levels:
                            row[str(q)] = float(100+i-5*(1-q))
                        rows.append(row)
                return pd.DataFrame(rows)

        TrackingPipeline.all_kwargs = []

        def factory() -> Chronos2Adapter:
            return Chronos2Adapter(pipeline_or_provider=TrackingPipeline())

        with tempfile.TemporaryDirectory() as tmp:
            run_benchmarks(output_dir=tmp, adapter_factory=factory)
        # Find the panel predict_df call (it has cross_learning kwarg)
        panel_calls = [k for k in TrackingPipeline.all_kwargs if "cross_learning" in k]
        assert len(panel_calls) >= 1, "No predict_df call received cross_learning"
        assert panel_calls[0]["cross_learning"] is False
