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
