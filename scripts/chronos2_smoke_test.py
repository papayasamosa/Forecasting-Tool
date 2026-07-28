#! /usr/bin/env python3
"""Stage 0.1 — Minimal Local Proof for Chronos-2.

Loads ``amazon/chronos-2`` on CPU, reads a small weekly synthetic series,
produces a 13-period forecast with quantiles 0.1, 0.5, 0.9, and prints only
output schema, dimensions, timings, and package metadata.

Usage:
    python scripts/chronos2_smoke_test.py
"""
from __future__ import annotations

import sys
import time
import os

# Add project root to path
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import numpy as np
import pandas as pd

from src.config import MODEL_ID, DEFAULT_QUANTILES
from src.schemas import ForecastTask, ForecastMode
from src.forecasting.chronos2_adapter import (
    create_forecast,
    load_pipeline,
    get_pipeline_info,
    reset_pipeline,
)


def _build_weekly_fixture(n_points: int = 260) -> pd.DataFrame:
    """Create a simple synthetic weekly series with trend + seasonality + noise."""
    rng = np.random.default_rng(seed=42)
    t = np.arange(n_points)
    trend = 100 + 0.1 * t
    seasonality = 10 * np.sin(2 * np.pi * t / 52)
    noise = rng.normal(0, 2, size=n_points)
    values = trend + seasonality + noise
    dates = pd.date_range("2020-01-06", periods=n_points, freq="W")
    return pd.DataFrame({"timestamp": dates, "target": values})


def run_smoke_test() -> None:
    """Execute the smoke test and print results."""

    print("=" * 64)
    print("  Chronos-2 Smoke Test — Stage 0.1")
    print("=" * 64)

    # ---- Record pre-load memory -----------------------------------------
    try:
        import psutil
        proc = psutil.Process()
        mem_before_mb = proc.memory_info().rss / 1024 / 1024
    except ImportError:
        mem_before_mb = None

    # ---- Python & package versions --------------------------------------
    print(f"\n  Python version : {sys.version.split()[0]}")
    try:
        import torch as t
        print(f"  PyTorch version: {t.__version__}")
    except ImportError:
        print("  PyTorch       : not found")

    try:
        import chronos as c
        print(f"  chronos-forecasting : {getattr(c, '__version__', 'unknown')}")
    except ImportError:
        print("  chronos-forecasting : not found")

    print(f"  Model ID       : {MODEL_ID}")

    # ---- Build fixture --------------------------------------------------
    print("\n  --- Building fixture ---")
    df = _build_weekly_fixture(260)
    context_rows = len(df)
    print(f"  Context rows   : {context_rows}")

    # ---- Load model (timed) ---------------------------------------------
    print("\n  --- Loading model (cold) ---")
    t0 = time.perf_counter()
    try:
        pipeline = load_pipeline(device_map="cpu")
    except Exception as exc:
        print(f"  FAILED: {exc}")
        sys.exit(1)
    load_time = time.perf_counter() - t0

    # Record post-load memory
    try:
        import psutil
        mem_after_mb = proc.memory_info().rss / 1024 / 1024
    except ImportError:
        mem_after_mb = None

    info = get_pipeline_info()
    print(f"  Model revision : {info.get('model_revision', 'N/A')}")
    print(f"  Load time      : {load_time:.2f}s")
    if mem_before_mb is not None:
        print(f"  Memory before  : {mem_before_mb:.1f} MB")
    if mem_after_mb is not None:
        print(f"  Memory after   : {mem_after_mb:.1f} MB")

    # ---- Build forecast task --------------------------------------------
    horizon = 13
    quantiles = DEFAULT_QUANTILES
    print(f"\n  --- Running forecast ---")
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

    # ---- Run forecast ---------------------------------------------------
    t1 = time.perf_counter()
    try:
        result = create_forecast(task)
    except Exception as exc:
        print(f"  FAILED: {exc}")
        sys.exit(1)
    inference_time = time.perf_counter() - t1

    # ---- Print output summary -------------------------------------------
    print(f"\n  --- Results ---")
    print(f"  Inference time : {inference_time:.3f}s")
    print(f"  Total (load+infer) : {load_time + inference_time:.2f}s")
    print(f"  Run ID         : {result.run_id}")
    print(f"  Backend        : {result.backend_name}")
    print(f"  Model ID       : {result.model_id}")
    print(f"  Model revision : {result.model_revision}")
    print(f"  # Forecast rows: {len(result.forecast_rows)}")
    print(f"  Quantile cols  : {[k for k in (result.forecast_rows[0] if result.forecast_rows else {}).keys() if k.startswith('quantile_')]}")
    print(f"  Point pred col : {result.point_prediction_name}")

    # Show first 3 forecast rows
    if result.forecast_rows:
        print(f"\n  --- Sample forecast rows (first 3) ---")
        for i, row in enumerate(result.forecast_rows[:3]):
            print(f"    [{i}] ts={row.get('timestamp','')}  "
                  f"pred={row.get('point_prediction', 'N/A'):.2f}  "
                  f"target={row.get('target_name','')}")

    # ---- Package metadata from result -----------------------------------
    pkg = result.runtime_metadata.package_versions
    print(f"\n  --- Package versions (from run metadata) ---")
    for k, v in pkg.items():
        print(f"    {k}: {v}")

    # ---- Warm forecast --------------------------------------------------
    print(f"\n  --- Warm forecast (should reuse cached model) ---")
    warm_task = ForecastTask(
        mode=ForecastMode.STANDARD_UNIVARIATE,
        historical_data=task.historical_data,
        timestamp_column="timestamp",
        target_columns=("target",),
        prediction_length=horizon,
        quantile_levels=tuple(quantiles),
        frequency="W",
    )
    t2 = time.perf_counter()
    warm_result = create_forecast(warm_task)
    warm_time = time.perf_counter() - t2
    print(f"  Warm inference : {warm_time:.3f}s  (should be faster than cold)")

    # ---- Verify output structure ----------------------------------------
    print(f"\n  --- Output schema verification ---")
    assert len(result.forecast_rows) == horizon, f"Expected {horizon} rows, got {len(result.forecast_rows)}"
    first = result.forecast_rows[0]
    assert "run_id" in first, "Missing run_id"
    assert "timestamp" in first, "Missing timestamp"
    assert "point_prediction" in first, "Missing point_prediction"
    assert "quantile_0_1" in first, "Missing quantile_0_1"
    assert "quantile_0_5" in first, "Missing quantile_0_5"
    assert "quantile_0_9" in first, "Missing quantile_0_9"
    print("  All assertions passed.")

    # ---- Cleanup --------------------------------------------------------
    reset_pipeline()
    print(f"\n{'=' * 64}")
    print("  Smoke test completed successfully!")
    print("=" * 64)


if __name__ == "__main__":
    run_smoke_test()
