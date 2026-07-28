"""Tests for the benchmarking module.

These tests verify that benchmark scenarios construct correctly and produce
valid output. They do NOT load the Chronos-2 model.
"""
from __future__ import annotations

import os
import json
import tempfile

import pytest

from src.benchmarking import (
    BenchmarkResult,
    BenchmarkSample,
    _weekly_fixture,
    _panel_fixture,
    _make_task,
    _write_json,
    _write_markdown,
)


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
