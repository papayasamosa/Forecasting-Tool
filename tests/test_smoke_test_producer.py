"""Tests for the chronos2 smoke-test producer's token-path evidence.

These tests exercise ``scripts/chronos2_smoke_test.py`` with a fake adapter
(no model download) and monkeypatched HF cache/env state, verifying that
``token_absent_result`` / ``token_present_result`` are emitted automatically
from the runtime environment and forecast outcome rather than requiring
post-processing or hand-editing.
"""
from __future__ import annotations

import tempfile
import time

import pytest

from scripts.chronos2_smoke_test import run_smoke_test, _apply_token_result
from src.schemas import ForecastResult, RunMetadata


class _FakeAdapter:
    """Minimal stand-in for Chronos2Adapter — no model download."""

    def __init__(self, model_revision: str = "fake-revision-abc", fail: bool = False):
        self.pipeline_call_count = 1
        self._model_revision = model_revision
        self._fail = fail

    def forecast(self, task):
        if self._fail:
            raise RuntimeError("simulated inference failure")
        # Small sleep so timing_seconds rounds to a non-zero value, as a real
        # model load always would.
        time.sleep(0.01)
        rows = tuple(
            {
                "run_id": "fake-run",
                "item_id": "series_0",
                "timestamp": f"2026-01-{i + 1:02d}",
                "target_name": "target",
                "point_prediction": 1.0,
                "quantile_0_1": 0.9,
                "quantile_0_5": 1.0,
                "quantile_0_9": 1.1,
            }
            for i in range(task.prediction_length)
        )
        meta = RunMetadata(
            run_id="fake-run",
            model_load_seconds=0.01,
            inference_seconds=0.005,
            result_conversion_seconds=0.001,
            pipeline_reused=False,
        )
        return ForecastResult(
            run_id="fake-run",
            forecast_rows=rows,
            model_id="amazon/chronos-2",
            model_revision=self._model_revision,
            runtime_metadata=meta,
        )


def _fake_cache_preflight(snapshot_present: bool):
    def _inspect(configured_revision, cache_dir=None):
        return {
            "snapshot_present": snapshot_present,
            "file_count": 2 if snapshot_present else 0,
            "total_bytes": 12345 if snapshot_present else 0,
            "cache_source": "env_HF_HUB_CACHE",
            "error": "",
        }
    return _inspect


@pytest.fixture
def fake_env(monkeypatch):
    """Patch the adapter and cache preflight so no model download occurs."""
    monkeypatch.setattr(
        "src.telemetry.inspect_hf_cache", _fake_cache_preflight(snapshot_present=True)
    )
    monkeypatch.setattr(
        "scripts.chronos2_smoke_test.Chronos2Adapter",
        lambda: _FakeAdapter(model_revision="fake-revision-abc"),
    )


class TestProducerEmitsTokenPathAutomatically:
    def test_no_token_run_populates_token_absent_result(self, fake_env, monkeypatch):
        monkeypatch.delenv("HF_TOKEN", raising=False)
        with tempfile.TemporaryDirectory() as tmp:
            evidence = run_smoke_test(
                evidence_dir=tmp, initial_cache_state="process_cold_cached_weights"
            )

        assert evidence["success"] is True
        assert evidence["hf_token_present"] is False
        assert evidence["token_absent_result"]["attempted"] is True
        assert evidence["token_absent_result"]["success"] is True
        assert evidence["token_absent_result"]["run_id"]
        assert evidence["token_absent_result"]["started_at_utc"]
        assert evidence["token_absent_result"]["completed_at_utc"]
        assert evidence["token_absent_result"]["timing_seconds"] > 0
        assert evidence["token_absent_result"]["resolved_revision"] == "fake-revision-abc"
        assert evidence["token_present_result"] == {"attempted": False}

    def test_token_present_run_populates_token_present_result(self, fake_env, monkeypatch):
        monkeypatch.setenv("HF_TOKEN", "hf_fake_token_value_not_persisted")
        with tempfile.TemporaryDirectory() as tmp:
            evidence = run_smoke_test(
                evidence_dir=tmp, initial_cache_state="process_cold_cached_weights"
            )

        assert evidence["success"] is True
        assert evidence["hf_token_present"] is True
        assert evidence["token_present_result"]["attempted"] is True
        assert evidence["token_present_result"]["success"] is True
        assert evidence["token_present_result"]["run_id"]
        assert evidence["token_present_result"]["timing_seconds"] > 0
        assert evidence["token_absent_result"] == {"attempted": False}
        # The token value itself must never be written into evidence.
        dumped = str(evidence)
        assert "hf_fake_token_value_not_persisted" not in dumped

    def test_two_runs_of_same_path_get_distinct_run_ids(self, fake_env, monkeypatch):
        """Two independently executed runs must never collide on run_id —
        this is the provenance signal that stops a copied record (Gate B3's
        duplicated token-present record) from being mistaken for a fresh run."""
        monkeypatch.delenv("HF_TOKEN", raising=False)
        with tempfile.TemporaryDirectory() as tmp:
            ev1 = run_smoke_test(evidence_dir=tmp, initial_cache_state="process_cold_cached_weights")
            ev2 = run_smoke_test(evidence_dir=tmp, initial_cache_state="process_cold_cached_weights")

        assert ev1["token_absent_result"]["run_id"] != ev2["token_absent_result"]["run_id"]

    def test_cold_failure_records_failed_token_path(self, monkeypatch):
        monkeypatch.setattr(
            "src.telemetry.inspect_hf_cache", _fake_cache_preflight(snapshot_present=True)
        )
        monkeypatch.setattr(
            "scripts.chronos2_smoke_test.Chronos2Adapter",
            lambda: _FakeAdapter(fail=True),
        )
        monkeypatch.delenv("HF_TOKEN", raising=False)
        with tempfile.TemporaryDirectory() as tmp:
            evidence = run_smoke_test(
                evidence_dir=tmp, initial_cache_state="process_cold_cached_weights"
            )

        assert evidence["success"] is False
        assert evidence["token_absent_result"]["attempted"] is True
        assert evidence["token_absent_result"]["success"] is False
        assert evidence["token_absent_result"]["error_code"] == "RuntimeError"
        assert evidence["token_present_result"] == {"attempted": False}


class TestApplyTokenResultHelper:
    def test_token_present_true_routes_to_present_slot(self):
        evidence = {"hf_token_present": True}
        _apply_token_result(evidence, {"attempted": True, "success": True})
        assert evidence["token_present_result"] == {"attempted": True, "success": True}
        assert evidence["token_absent_result"] == {"attempted": False}

    def test_token_present_false_routes_to_absent_slot(self):
        evidence = {"hf_token_present": False}
        _apply_token_result(evidence, {"attempted": True, "success": True})
        assert evidence["token_absent_result"] == {"attempted": True, "success": True}
        assert evidence["token_present_result"] == {"attempted": False}
