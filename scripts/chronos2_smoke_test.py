#! /usr/bin/env python3
"""Stage 0.1 — Minimal Local Proof for Chronos-2.

Usage:
    python scripts/chronos2_smoke_test.py

Emits a JSON evidence record alongside console output (P1-6).
"""
from __future__ import annotations

import json
import os
import sys
import time
from datetime import datetime, timezone

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import numpy as np  # noqa: E402
import pandas as pd  # noqa: E402

from src.config import MODEL_ID, DEFAULT_QUANTILES  # noqa: E402
from src.schemas import ForecastTask, ForecastMode  # noqa: E402
from src.forecasting.chronos2_adapter import (  # noqa: E402
    Chronos2Adapter,
    _capture_package_versions,
)
from src.benchmarking import _rss_mb  # noqa: E402

# ---------------------------------------------------------------------------
# Default evidence output path
# ---------------------------------------------------------------------------
DEFAULT_EVIDENCE_DIR = r"D:\Forecasting-Tool-Local\benchmarks"


def _build_weekly_fixture(n_points: int = 260) -> pd.DataFrame:
    rng = np.random.default_rng(seed=42)
    t = np.arange(n_points)
    trend = 100 + 0.1 * t
    seasonality = 10 * np.sin(2 * np.pi * t / 52)
    noise = rng.normal(0, 2, size=n_points)
    values = trend + seasonality + noise
    dates = pd.date_range("2020-01-06", periods=n_points, freq="W")
    return pd.DataFrame({"timestamp": dates, "target": values})


def run_smoke_test(evidence_dir: str = DEFAULT_EVIDENCE_DIR) -> dict:
    """Run the smoke test and return/export a structured evidence dict.

    Returns a JSON-serialisable dict with all measurements, or a dict
    with ``success=False`` and error details on failure.
    """
    evidence: dict = {
        "test": "chronos2_smoke_test",
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "success": False,
        "python_version": sys.version.split()[0],
        "model_id": MODEL_ID,
        "model_revision": "",
        "hf_token_present": bool(os.environ.get("HF_TOKEN")),
        "cold": {},
        "warm": {},
        "package_versions": {},
        "error": "",
    }

    print("=" * 64)
    print("  Chronos-2 Smoke Test — Stage 0.1")
    print("=" * 64)

    baseline_rss = _rss_mb()
    print(f"\n  Python version : {evidence['python_version']}")
    print(f"  Model ID       : {evidence['model_id']}")
    print(f"  HF_TOKEN       : {evidence['hf_token_present']}")
    print(f"  Baseline RSS   : {baseline_rss:.1f} MB")

    df = _build_weekly_fixture(260)
    context_rows = len(df)
    print(f"  Context rows   : {context_rows}")

    horizon = 13
    quantiles = DEFAULT_QUANTILES
    print(f"  Horizon        : {horizon}")
    print(f"  Quantiles      : {quantiles}")

    task = ForecastTask(
        mode=ForecastMode.STANDARD_UNIVARIATE,
        historical_data=tuple(df.to_dict("records")),
        timestamp_column="timestamp",
        target_columns=("target",),
        prediction_length=horizon,
        quantile_levels=tuple(quantiles),
        frequency="W",
    )

    # Cold load + forecast
    print("\n  --- Cold (first) forecast ---")
    adapter = Chronos2Adapter()
    t0 = time.perf_counter()
    try:
        result = adapter.forecast(task)
    except Exception as exc:
        print(f"  FAILED: {exc}")
        evidence["error"] = f"{type(exc).__name__}: {exc}"
        _write_evidence(evidence, evidence_dir)
        return evidence
    cold_time = time.perf_counter() - t0
    cold_rss = _rss_mb()

    evidence["cold"] = {
        "total_seconds": round(cold_time, 3),
        "model_load_seconds": result.runtime_metadata.model_load_seconds,
        "inference_seconds": result.runtime_metadata.inference_seconds,
        "result_conversion_seconds": result.runtime_metadata.result_conversion_seconds,
        "rss_mb": round(cold_rss, 1),
        "pipeline_call_count": adapter.pipeline_call_count,
        "model_revision": result.model_revision,
    }
    evidence["model_revision"] = result.model_revision

    print(f"  Cold time      : {cold_time:.3f}s")
    print(f"  Pipeline calls : {adapter.pipeline_call_count}")
    print(f"  RSS            : {cold_rss:.1f} MB")
    print(f"  Run ID         : {result.run_id}")
    print(f"  Model revision : {result.model_revision}")
    print(f"  # Forecast rows: {len(result.forecast_rows)}")

    # Warm forecast
    print("\n  --- Warm forecast ---")
    t1 = time.perf_counter()
    warm_result = adapter.forecast(task)
    warm_time = time.perf_counter() - t1
    warm_rss = _rss_mb()

    evidence["warm"] = {
        "total_seconds": round(warm_time, 3),
        "model_load_seconds": warm_result.runtime_metadata.model_load_seconds,
        "inference_seconds": warm_result.runtime_metadata.inference_seconds,
        "result_conversion_seconds": warm_result.runtime_metadata.result_conversion_seconds,
        "rss_mb": round(warm_rss, 1),
        "pipeline_call_count": adapter.pipeline_call_count,
        "pipeline_reused": warm_result.runtime_metadata.pipeline_reused,
    }

    print(f"  Warm time      : {warm_time:.3f}s")
    print(f"  Pipeline calls : {adapter.pipeline_call_count} (should be 1)")
    print(f"  RSS            : {warm_rss:.1f} MB")

    # Output verification
    assert len(result.forecast_rows) == horizon
    first = result.forecast_rows[0]
    assert "run_id" in first
    assert "point_prediction" in first
    assert "quantile_0_1" in first
    assert "quantile_0_5" in first
    assert "quantile_0_9" in first
    print("\n  Output schema OK")

    # Package versions
    pkg = _capture_package_versions()
    evidence["package_versions"] = pkg
    print("\n  Package versions:")
    for k, v in pkg.items():
        print(f"    {k}: {v}")

    evidence["success"] = True
    print(f"\n{'=' * 64}")
    print("  Smoke test completed successfully!")
    print("=" * 64)

    _write_evidence(evidence, evidence_dir)
    return evidence


def _write_evidence(evidence: dict, evidence_dir: str) -> str:
    """Write evidence dict to a JSON file and return the path."""
    os.makedirs(evidence_dir, exist_ok=True)
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    path = os.path.join(evidence_dir, f"smoke_test_{timestamp}.json")
    with open(path, "w", encoding="utf-8") as f:
        json.dump(evidence, f, indent=2, default=str)
    print(f"\n  Evidence written to: {path}")
    return path


if __name__ == "__main__":
    evidence_dir = os.environ.get(
        "BENCHMARK_OUTPUT_DIR", DEFAULT_EVIDENCE_DIR
    )
    run_smoke_test(evidence_dir=evidence_dir)
