"""Stage 0 benchmark harness — runs, measures, and records benchmark scenarios.

All heavy output defaults to D:\Forecasting-Tool-Local\benchmarks.
"""
from __future__ import annotations

import json
import logging
import os
import platform
import sys
import time
from dataclasses import dataclass, field, asdict
from datetime import datetime, timezone
from typing import Any

import numpy as np
import pandas as pd

from src.config import MODEL_ID
from src.schemas import ForecastMode, ForecastTask
from src.forecasting.chronos2_adapter import (
    Chronos2Adapter,
    AdapterError,
    ModelLoadError,
)

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Default output path
# ---------------------------------------------------------------------------
DEFAULT_OUTPUT_DIR = r"D:\Forecasting-Tool-Local\benchmarks"


@dataclass
class BenchmarkSample:
    """Snapshot of a single measurement."""
    label: str
    duration_seconds: float = 0.0
    rss_mb: float = 0.0
    pipeline_call_count: int = 0
    success: bool = True
    error_type: str = ""
    error_message: str = ""


@dataclass
class BenchmarkResult:
    """Complete benchmark results for one scenario."""
    scenario: str = ""
    python_version: str = ""
    os_name: str = ""
    cpu_info: str = ""
    model_id: str = ""
    model_revision: str = ""
    package_versions: dict[str, str] = field(default_factory=dict)
    context_rows: int = 0
    horizon: int = 0
    quantile_levels: tuple[float, ...] = ()
    samples: list[BenchmarkSample] = field(default_factory=list)
    hf_token_present: bool = False
    run_timestamp: str = ""


def _rss_mb() -> float:
    try:
        import psutil
        return psutil.Process().memory_info().rss / 1024 / 1024
    except ImportError:
        return 0.0


def _cpu_info() -> str:
    try:
        import psutil
        return f"{psutil.cpu_count()} logical cores"
    except ImportError:
        return "unknown"


def _package_versions() -> dict[str, str]:
    versions: dict[str, str] = {}
    for mod_name, alias in [("torch", "torch"), ("chronos", "chronos-forecasting"),
                            ("pandas", "pandas"), ("numpy", "numpy"),
                            ("streamlit", "streamlit")]:
        try:
            mod = __import__(mod_name)
            versions[alias] = getattr(mod, "__version__", "unknown")
        except ImportError:
            versions[alias] = "not found"
    versions["python"] = sys.version.split()[0]
    return versions


def _weekly_fixture(n_points: int = 260) -> pd.DataFrame:
    rng = np.random.default_rng(seed=42)
    t = np.arange(n_points)
    values = 100 + 0.1 * t + 10 * np.sin(2 * np.pi * t / 52) + rng.normal(0, 2, size=n_points)
    dates = pd.date_range("2020-01-06", periods=n_points, freq="W")
    return pd.DataFrame({"timestamp": dates, "target": values})


def _panel_fixture(n_series: int = 5, n_points: int = 104) -> pd.DataFrame:
    rng = np.random.default_rng(seed=42)
    rows = []
    for s in range(n_series):
        t = np.arange(n_points)
        values = 100 + s * 20 + 0.05 * t + 5 * np.sin(2 * np.pi * t / 52) + rng.normal(0, 2, size=n_points)
        dates = pd.date_range("2022-01-03", periods=n_points, freq="W")
        for i in range(n_points):
            rows.append({"item_id": f"series_{s}", "timestamp": dates[i], "target": values[i]})
    return pd.DataFrame(rows)


def _make_task(df: pd.DataFrame, horizon: int = 13,
               quantiles: tuple[float, ...] = (0.1, 0.5, 0.9),
               freq: str = "W") -> ForecastTask:
    return ForecastTask(
        mode=ForecastMode.STANDARD_UNIVARIATE,
        historical_data=tuple(df.to_dict("records")),
        timestamp_column="timestamp",
        target_columns=("target",),
        prediction_length=horizon,
        quantile_levels=quantiles,
        frequency=freq,
    )


def run_benchmarks(output_dir: str = DEFAULT_OUTPUT_DIR) -> list[BenchmarkResult]:
    """Execute all Stage 0 benchmark scenarios and write results."""
    os.makedirs(output_dir, exist_ok=True)

    all_results: list[BenchmarkResult] = []
    rss_before = _rss_mb()

    # ------------------------------------------------------------------
    # Scenario 1: Weekly series, 260 obs, 13-period horizon
    # ------------------------------------------------------------------
    print("\n=== Scenario 1: Weekly series (260 obs, horizon 13) ===")
    df1 = _weekly_fixture(260)
    task1 = _make_task(df1, horizon=13)
    result1 = BenchmarkResult(
        scenario="weekly_260_13",
        python_version=sys.version.split()[0],
        os_name=sys.platform,
        cpu_info=_cpu_info(),
        model_id=MODEL_ID,
        package_versions=_package_versions(),
        context_rows=260,
        horizon=13,
        quantile_levels=(0.1, 0.5, 0.9),
        hf_token_present=bool(os.environ.get("HF_TOKEN")),
        run_timestamp=datetime.now(timezone.utc).isoformat(),
    )

    adapter = Chronos2Adapter()
    t0 = time.perf_counter()
    try:
        fr = adapter.forecast(task1)
        result1.samples.append(BenchmarkSample(
            label="cold_forecast",
            duration_seconds=time.perf_counter() - t0,
            rss_mb=_rss_mb(),
            pipeline_call_count=adapter.pipeline_call_count,
        ))
        result1.model_revision = fr.model_revision
    except Exception as e:
        result1.samples.append(BenchmarkSample(
            label="cold_forecast", success=False,
            error_type=type(e).__name__, error_message=str(e)[:200],
        ))

    # Warm forecast
    t0 = time.perf_counter()
    try:
        adapter.forecast(task1)
        result1.samples.append(BenchmarkSample(
            label="warm_forecast",
            duration_seconds=time.perf_counter() - t0,
            rss_mb=_rss_mb(),
            pipeline_call_count=adapter.pipeline_call_count,
        ))
    except Exception as e:
        result1.samples.append(BenchmarkSample(
            label="warm_forecast", success=False,
            error_type=type(e).__name__, error_message=str(e)[:200],
        ))
    all_results.append(result1)

    # ------------------------------------------------------------------
    # Scenario 2: Small panel (5 series)
    # ------------------------------------------------------------------
    print("\n=== Scenario 2: Small panel (5 series) ===")
    df2 = _panel_fixture(n_series=5, n_points=104)
    task2 = _make_task(df2, horizon=13, freq="W")
    result2 = BenchmarkResult(
        scenario="panel_5_series",
        context_rows=104 * 5,
        horizon=13,
        quantile_levels=(0.1, 0.5, 0.9),
        os_name=sys.platform,
        cpu_info=_cpu_info(),
        model_id=MODEL_ID,
        package_versions=_package_versions(),
        python_version=sys.version.split()[0],
        run_timestamp=datetime.now(timezone.utc).isoformat(),
    )
    t0 = time.perf_counter()
    try:
        adapter.forecast(task2)
        result2.samples.append(BenchmarkSample(
            label="panel_forecast",
            duration_seconds=time.perf_counter() - t0,
            rss_mb=_rss_mb(),
        ))
    except Exception as e:
        result2.samples.append(BenchmarkSample(
            label="panel_forecast", success=False,
            error_type=type(e).__name__, error_message=str(e)[:200],
        ))
    all_results.append(result2)

    # ------------------------------------------------------------------
    # Scenario 3: 10 rolling forecast calls
    # ------------------------------------------------------------------
    print("\n=== Scenario 3: 10 rolling calls ===")
    df3 = _weekly_fixture(260)
    result3 = BenchmarkResult(
        scenario="10_rolling_calls",
        context_rows=260,
        horizon=13,
        quantile_levels=(0.1, 0.5, 0.9),
        os_name=sys.platform, cpu_info=_cpu_info(),
        model_id=MODEL_ID, package_versions=_package_versions(),
        python_version=sys.version.split()[0],
        run_timestamp=datetime.now(timezone.utc).isoformat(),
    )
    total = 0.0
    for fold in range(10):
        cutoff = 260 - (10 - fold) * 13
        if cutoff < 13:
            break
        subset = df3.iloc[:cutoff]
        t_task = _make_task(subset, horizon=13)
        t0 = time.perf_counter()
        try:
            adapter.forecast(t_task)
            d = time.perf_counter() - t0
            total += d
            result3.samples.append(BenchmarkSample(
                label=f"fold_{fold}", duration_seconds=d,
                rss_mb=_rss_mb(),
            ))
        except Exception as e:
            result3.samples.append(BenchmarkSample(
                label=f"fold_{fold}", success=False,
                error_type=type(e).__name__, error_message=str(e)[:200],
            ))
    if result3.samples:
        result3.samples.append(BenchmarkSample(
            label="total_10_folds", duration_seconds=total,
            rss_mb=_rss_mb(),
        ))
    all_results.append(result3)

    # ------------------------------------------------------------------
    # Scenario 4: Failure + retry
    # ------------------------------------------------------------------
    print("\n=== Scenario 4: Failure + retry ===")
    result4 = BenchmarkResult(
        scenario="failure_and_retry",
        context_rows=0,
        horizon=13,
        quantile_levels=(0.1, 0.5, 0.9),
        os_name=sys.platform, cpu_info=_cpu_info(),
        model_id=MODEL_ID, package_versions=_package_versions(),
        python_version=sys.version.split()[0],
        run_timestamp=datetime.now(timezone.utc).isoformat(),
    )
    # Controlled failure: empty data
    bad_task = _make_task(pd.DataFrame(columns=["timestamp", "target"]), horizon=13)
    try:
        adapter.forecast(bad_task)
    except AdapterError as e:
        result4.samples.append(BenchmarkSample(
            label="empty_data_rejection",
            success=False, error_type=type(e).__name__,
        ))
    # Retry with valid data
    try:
        retry = adapter.forecast(task1)
        result4.samples.append(BenchmarkSample(
            label="retry_success",
            duration_seconds=0,
            rss_mb=_rss_mb(),
            pipeline_call_count=adapter.pipeline_call_count,
        ))
        result4.model_revision = retry.model_revision
    except Exception as e:
        result4.samples.append(BenchmarkSample(
            label="retry_success",
            success=False, error_type=type(e).__name__, error_message=str(e)[:200],
        ))
    all_results.append(result4)

    # ------------------------------------------------------------------
    # Write results
    # ------------------------------------------------------------------
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    json_path = os.path.join(output_dir, f"benchmark_{timestamp}.json")
    md_path = os.path.join(output_dir, f"benchmark_{timestamp}.md")

    for br in all_results:
        br.samples = [s for s in br.samples if s.duration_seconds > 0 or not s.success]

    _write_json(all_results, json_path)
    _write_markdown(all_results, md_path)

    print(f"\nResults written to:\n  {json_path}\n  {md_path}")
    return all_results


def _write_json(results: list[BenchmarkResult], path: str) -> None:
    data = []
    for r in results:
        d = asdict(r)
        d["samples"] = [asdict(s) for s in r.samples]
        data.append(d)
    with open(path, "w") as f:
        json.dump(data, f, indent=2, default=str)


def _write_markdown(results: list[BenchmarkResult], path: str) -> None:
    lines = [
        "# Stage 0 Benchmark Report",
        f"Generated: {datetime.now(timezone.utc).isoformat()}",
        "",
        "## Environment",
        f"- Python: {sys.version.split()[0]}",
        f"- OS: {sys.platform}",
        f"- Model: {MODEL_ID}",
        "",
    ]
    for r in results:
        lines.extend([
            f"## Scenario: {r.scenario}",
            f"- Context rows: {r.context_rows}",
            f"- Horizon: {r.horizon}",
            f"- Quantiles: {r.quantile_levels}",
            "",
            "| Sample | Duration (s) | RSS (MB) | Success |",
            "|--------|-------------|---------|---------|",
        ])
        for s in r.samples:
            lines.append(
                f"| {s.label} | {s.duration_seconds:.3f} | {s.rss_mb:.1f} | {s.success} |"
            )
        lines.append("")

    with open(path, "w") as f:
        f.write("\n".join(lines))


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    run_benchmarks()
