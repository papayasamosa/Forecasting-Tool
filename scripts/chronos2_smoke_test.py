#! /usr/bin/env python3
"""Stage 0.1 — Minimal Local Proof for Chronos-2.

Usage:
    python scripts/chronos2_smoke_test.py
"""
from __future__ import annotations

import sys
import time
import os

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import numpy as np  # noqa: E402
import pandas as pd  # noqa: E402

from src.config import MODEL_ID, DEFAULT_QUANTILES  # noqa: E402
from src.schemas import ForecastTask, ForecastMode  # noqa: E402
from src.forecasting.chronos2_adapter import Chronos2Adapter  # noqa: E402


def _build_weekly_fixture(n_points: int = 260) -> pd.DataFrame:
    rng = np.random.default_rng(seed=42)
    t = np.arange(n_points)
    trend = 100 + 0.1 * t
    seasonality = 10 * np.sin(2 * np.pi * t / 52)
    noise = rng.normal(0, 2, size=n_points)
    values = trend + seasonality + noise
    dates = pd.date_range("2020-01-06", periods=n_points, freq="W")
    return pd.DataFrame({"timestamp": dates, "target": values})


def run_smoke_test() -> None:
    print("=" * 64)
    print("  Chronos-2 Smoke Test — Stage 0.1")
    print("=" * 64)

    # Memory before
    try:
        import psutil
        proc = psutil.Process()
        mem_before_mb = proc.memory_info().rss / 1024 / 1024
    except ImportError:
        mem_before_mb = None

    print(f"\n  Python version : {sys.version.split()[0]}")
    print(f"  Model ID       : {MODEL_ID}")

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
        sys.exit(1)
    cold_time = time.perf_counter() - t0

    try:
        import psutil
        mem_after_mb = proc.memory_info().rss / 1024 / 1024
    except ImportError:
        mem_after_mb = None

    print(f"  Cold time      : {cold_time:.3f}s")
    print(f"  Pipeline calls : {adapter.pipeline_call_count}")
    if mem_before_mb is not None:
        print(f"  Memory before  : {mem_before_mb:.1f} MB")
    if mem_after_mb is not None:
        print(f"  Memory after   : {mem_after_mb:.1f} MB")

    print(f"  Run ID         : {result.run_id}")
    print(f"  Model revision : {result.model_revision}")
    print(f"  # Forecast rows: {len(result.forecast_rows)}")

    # Warm forecast
    print("\n  --- Warm forecast ---")
    t1 = time.perf_counter()
    warm_result = adapter.forecast(task)
    warm_time = time.perf_counter() - t1
    print(f"  Warm time      : {warm_time:.3f}s")
    print(f"  Pipeline calls : {adapter.pipeline_call_count} (should be 1)")

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
    pkg = result.runtime_metadata.package_versions
    print("\n  Package versions:")
    for k, v in pkg.items():
        print(f"    {k}: {v}")

    print(f"\n{'=' * 64}")
    print("  Smoke test completed successfully!")
    print("=" * 64)


if __name__ == "__main__":
    run_smoke_test()
