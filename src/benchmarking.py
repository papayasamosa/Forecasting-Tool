"""Stage 0 benchmark harness -- runs, measures, and records benchmark scenarios.

All heavy output defaults to D:\\Forecasting-Tool-Local\\benchmarks on Windows,
or a platform-appropriate path elsewhere.
"""
from __future__ import annotations

import json
import logging
import os
import sys
import time
import threading
from dataclasses import dataclass, field, asdict
from datetime import datetime, timezone
from typing import Any, Callable

import numpy as np
import pandas as pd

from src.config import MODEL_ID
from src.schemas import ForecastMode, ForecastTask
from src.forecasting.chronos2_adapter import (
    Chronos2Adapter,
    AdapterError,
    ModelLoadError,
    ResultSchemaError,
    _validate_quantile_monotonic,
)

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Default output path (platform-aware)
# ---------------------------------------------------------------------------
if sys.platform == "win32":
    DEFAULT_OUTPUT_DIR = r"D:\Forecasting-Tool-Local\benchmarks"
else:
    DEFAULT_OUTPUT_DIR = os.path.join(os.path.expanduser("~"), "forecast-benchmarks")


# ---------------------------------------------------------------------------
# Lightweight RSS monitor thread (approximate peak)
# ---------------------------------------------------------------------------


class _MemorySampler:
    """Samples process RSS in a background thread to approximate peak memory."""

    def __init__(self, interval: float = 0.05):
        self._interval = interval
        self._peak_mb: float = 0.0
        self._baseline_mb: float = 0.0
        self._running = False
        self._thread: threading.Thread | None = None
        self._imported_psutil = False
        self._process = None
        try:
            import psutil
            self._process = psutil.Process()
            self._imported_psutil = True
        except ImportError:
            pass

    def start(self) -> None:
        if not self._imported_psutil:
            return
        self._baseline_mb = self._process.memory_info().rss / 1024 / 1024  # type: ignore[union-attr]
        self._peak_mb = self._baseline_mb
        self._running = True
        self._thread = threading.Thread(target=self._sample, daemon=True)
        self._thread.start()

    def _sample(self) -> None:
        while self._running:
            try:
                rss = self._process.memory_info().rss / 1024 / 1024  # type: ignore[union-attr]
                if rss > self._peak_mb:
                    self._peak_mb = rss
            except Exception:
                pass
            time.sleep(self._interval)

    def stop(self) -> None:
        self._running = False
        if self._thread:
            self._thread.join(timeout=2)

    @property
    def peak_mb(self) -> float:
        return self._peak_mb

    @property
    def baseline_mb(self) -> float:
        return self._baseline_mb


# ---------------------------------------------------------------------------
# Data classes
# ---------------------------------------------------------------------------


@dataclass
class BenchmarkSample:
    """Snapshot of a single measurement."""
    label: str
    duration_seconds: float = 0.0
    rss_mb: float = 0.0
    baseline_rss_mb: float = 0.0
    peak_rss_mb: float = 0.0
    pipeline_call_count: int = 0
    success: bool = True
    error_type: str = ""
    error_message: str = ""
    model_load_seconds: float = 0.0
    inference_seconds: float = 0.0


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
    cross_learning: bool = False
    n_series: int = 1


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


class _TransientFailurePipeline:
    """Fails on its first N ``predict_df`` calls, then succeeds with a
    valid synthetic single-series forecast.

    Used only by the failure/retry benchmark scenario. Defined here (not
    imported from ``tests/``) so this production module has no dependency
    on the tests package under a packaged/installed deployment.
    """
    model_id = MODEL_ID
    model_revision = ""

    def __init__(self, fail_first_n_calls: int = 1):
        self._fail_first_n_calls = fail_first_n_calls
        self.call_count = 0

    def predict_df(self, input_df: pd.DataFrame, **kwargs: Any) -> pd.DataFrame:
        self.call_count += 1
        if self.call_count <= self._fail_first_n_calls:
            raise RuntimeError("Simulated transient inference failure")

        prediction_length = kwargs.get("prediction_length", 13)
        quantile_levels = kwargs.get("quantile_levels", [0.1, 0.5, 0.9])
        item_id = input_df["item_id"].iloc[0]
        last_ts = pd.to_datetime(input_df["timestamp"].iloc[-1])
        try:
            freq = pd.infer_freq(input_df["timestamp"])
        except (ValueError, TypeError):
            freq = "D"
        if freq is None:
            freq = "D"
        dates = pd.date_range(start=last_ts, periods=prediction_length + 1, freq=freq)[1:]

        rows = []
        for i, d in enumerate(dates):
            row: dict[str, Any] = {
                "item_id": item_id,
                "timestamp": d,
                "target_name": "target",
                "predictions": float(100 + i),
            }
            for q in quantile_levels:
                row[str(q)] = float(100 + i - 5 * (1 - q))
            rows.append(row)
        return pd.DataFrame(rows)


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


def run_benchmarks(
    output_dir: str = DEFAULT_OUTPUT_DIR,
    adapter_factory: Callable[[], Chronos2Adapter] | None = None,
) -> list[BenchmarkResult]:
    """Execute all Stage 0 benchmark scenarios and write results.

    Parameters
    ----------
    output_dir : str
        Directory for JSON and Markdown output files.
    adapter_factory : callable or None
        Factory that returns a Chronos2Adapter. Defaults to ``Chronos2Adapter``.
        Use a fake factory for testing without model download.
    """
    if adapter_factory is None:
        adapter_factory = lambda: Chronos2Adapter()

    os.makedirs(output_dir, exist_ok=True)

    mem_sampler = _MemorySampler()
    all_results: list[BenchmarkResult] = []

    def _base_result(scenario: str, context_rows: int = 0, horizon: int = 13,
                     quantiles: tuple[float, ...] = (0.1, 0.5, 0.9),
                     n_series: int = 1, cross_learning: bool = False) -> BenchmarkResult:
        return BenchmarkResult(
            scenario=scenario,
            python_version=sys.version.split()[0],
            os_name=sys.platform,
            cpu_info=_cpu_info(),
            model_id=MODEL_ID,
            package_versions=_package_versions(),
            context_rows=context_rows,
            horizon=horizon,
            quantile_levels=quantiles,
            hf_token_present=bool(os.environ.get("HF_TOKEN")),
            run_timestamp=datetime.now(timezone.utc).isoformat(),
            n_series=n_series,
            cross_learning=cross_learning,
        )

    # ------------------------------------------------------------------
    # Scenario 1: Weekly series, 260 obs, 13-period horizon
    # ------------------------------------------------------------------
    print("\n=== Scenario 1: Weekly series (260 obs, horizon 13) ===")
    df1 = _weekly_fixture(260)
    task1 = _make_task(df1, horizon=13)
    result1 = _base_result("weekly_260_13", context_rows=260, horizon=13)

    adapter = adapter_factory()
    mem_sampler.start()
    try:
        fr = adapter.forecast(task1)
        mem_sampler.stop()
        result1.samples.append(BenchmarkSample(
            label="cold_forecast",
            duration_seconds=fr.runtime_metadata.total_runtime_seconds,
            rss_mb=_rss_mb(),
            baseline_rss_mb=mem_sampler.baseline_mb,
            peak_rss_mb=mem_sampler.peak_mb,
            pipeline_call_count=adapter.pipeline_call_count,
            model_load_seconds=fr.runtime_metadata.model_load_seconds,
            inference_seconds=fr.runtime_metadata.inference_seconds,
        ))
        result1.model_revision = fr.model_revision
    except Exception as e:
        mem_sampler.stop()
        result1.samples.append(BenchmarkSample(
            label="cold_forecast", success=False,
            error_type=type(e).__name__, error_message=str(e)[:200],
        ))

    # Warm forecast
    mem_sampler = _MemorySampler()
    mem_sampler.start()
    try:
        fr2 = adapter.forecast(task1)
        mem_sampler.stop()
        result1.samples.append(BenchmarkSample(
            label="warm_forecast",
            duration_seconds=fr2.runtime_metadata.total_runtime_seconds,
            rss_mb=_rss_mb(),
            baseline_rss_mb=mem_sampler.baseline_mb,
            peak_rss_mb=mem_sampler.peak_mb,
            pipeline_call_count=adapter.pipeline_call_count,
            model_load_seconds=fr2.runtime_metadata.model_load_seconds,
            inference_seconds=fr2.runtime_metadata.inference_seconds,
        ))
    except Exception as e:
        mem_sampler.stop()
        result1.samples.append(BenchmarkSample(
            label="warm_forecast", success=False,
            error_type=type(e).__name__, error_message=str(e)[:200],
        ))
    all_results.append(result1)

    # ------------------------------------------------------------------
    # Scenario 2: Small panel — benchmark-only path
    #
    # Uses the real Chronos-2 predict_df API directly (bypasses the
    # standard-univariate adapter). This is a benchmark-only measurement
    # and does not expose panel forecasting in the product UI.
    # ------------------------------------------------------------------
    print("\n=== Scenario 2: Small panel (5 series, benchmark-only path) ===")
    df2 = _panel_fixture(n_series=5, n_points=104)
    result2 = _base_result("panel_5_series", context_rows=104 * 5, horizon=13,
                          n_series=5, cross_learning=False)

    panel_adapter = adapter_factory()
    panel_mem_sampler = _MemorySampler()
    try:
        panel_mem_sampler.start()  # started before pipeline acquisition
        pipeline = panel_adapter.get_pipeline()
        input_df = df2.copy()
        input_df.columns = ["item_id", "timestamp", "target"]
        quantile_levels = [0.1, 0.5, 0.9]
        expected_horizon = 13
        expected_item_ids = set(input_df["item_id"].unique())

        t0 = time.perf_counter()
        pred_df = pipeline.predict_df(
            input_df,
            prediction_length=expected_horizon,
            quantile_levels=quantile_levels,
            id_column="item_id",
            timestamp_column="timestamp",
            target="target",
        )
        inference_time = time.perf_counter() - t0
        panel_mem_sampler.stop()

        expected_rows = len(expected_item_ids) * expected_horizon
        if len(pred_df) != expected_rows:
            raise ResultSchemaError(
                f"Panel benchmark expected {expected_rows} rows, got {len(pred_df)}"
            )
        if set(pred_df["item_id"].unique()) != expected_item_ids:
            raise ResultSchemaError("Panel benchmark item_id set mismatch.")
        for _, prow in pred_df.iterrows():
            _validate_quantile_monotonic(prow, quantile_levels)

        result2.samples.append(BenchmarkSample(
            label="panel_forecast_direct",
            duration_seconds=inference_time,
            rss_mb=_rss_mb(),
            baseline_rss_mb=panel_mem_sampler.baseline_mb,
            peak_rss_mb=panel_mem_sampler.peak_mb,
            inference_seconds=inference_time,
        ))
        result2.model_revision = getattr(pipeline, "model_revision", "")
    except Exception as e:
        panel_mem_sampler.stop()
        result2.samples.append(BenchmarkSample(
            label="panel_forecast_direct", success=False,
            error_type=type(e).__name__, error_message=str(e)[:200],
        ))
    all_results.append(result2)

    # ------------------------------------------------------------------
    # Scenario 3: 10 rolling forecast calls
    # ------------------------------------------------------------------
    print("\n=== Scenario 3: 10 rolling calls ===")
    df3 = _weekly_fixture(260)
    result3 = _base_result("10_rolling_calls", context_rows=260, horizon=13)
    rolling_mem_sampler = _MemorySampler()
    rolling_mem_sampler.start()
    total = 0.0
    for fold in range(10):
        cutoff = 260 - (10 - fold) * 13
        if cutoff < 13:
            break
        subset = df3.iloc[:cutoff]
        t_task = _make_task(subset, horizon=13)
        try:
            fr3 = adapter.forecast(t_task)
            d = fr3.runtime_metadata.total_runtime_seconds
            total += d
            result3.samples.append(BenchmarkSample(
                label=f"fold_{fold}", duration_seconds=d,
                rss_mb=_rss_mb(),
                baseline_rss_mb=rolling_mem_sampler.baseline_mb,
                peak_rss_mb=rolling_mem_sampler.peak_mb,
                inference_seconds=fr3.runtime_metadata.inference_seconds,
            ))
        except Exception as e:
            result3.samples.append(BenchmarkSample(
                label=f"fold_{fold}", success=False,
                error_type=type(e).__name__, error_message=str(e)[:200],
            ))
    rolling_mem_sampler.stop()
    if result3.samples:
        result3.samples.append(BenchmarkSample(
            label="total_10_folds", duration_seconds=total,
            rss_mb=_rss_mb(),
            baseline_rss_mb=rolling_mem_sampler.baseline_mb,
            peak_rss_mb=rolling_mem_sampler.peak_mb,
        ))
    all_results.append(result3)

    # ------------------------------------------------------------------
    # Scenario 4: Failure + retry
    #
    # Uses a fake adapter/pipeline that fails, then retries with valid data.
    # The failure is constructed INSIDE the protected block so the suite
    # does NOT terminate before the retry test.
    # ------------------------------------------------------------------
    print("\n=== Scenario 4: Failure + retry (same adapter instance) ===")
    result4 = _base_result("failure_and_retry", context_rows=0, horizon=13)
    retry_mem_sampler = _MemorySampler()
    retry_mem_sampler.start()

    # A pipeline that fails its first call, then succeeds -- proves the
    # SAME adapter/cached pipeline recovers and remains usable after an
    # InferenceError, rather than just proving a fresh adapter works.
    flaky_pipeline = _TransientFailurePipeline(fail_first_n_calls=1)
    flaky_adapter = Chronos2Adapter(pipeline_or_provider=flaky_pipeline)
    valid_task = _make_task(_weekly_fixture(50), horizon=13)
    try:
        flaky_adapter.forecast(valid_task)
        result4.samples.append(BenchmarkSample(
            label="injection_failure_test", success=True,
            error_type="UnexpectedSuccess",
            error_message="Flaky pipeline did not fail as expected",
        ))
    except AdapterError as e:
        result4.samples.append(BenchmarkSample(
            label="injection_failure_test", success=False,
            error_type=type(e).__name__,
        ))

    # Retry on the SAME adapter/pipeline (no new adapter is constructed)
    try:
        retry_result = flaky_adapter.forecast(valid_task)
        retry_mem_sampler.stop()
        result4.samples.append(BenchmarkSample(
            label="retry_success",
            duration_seconds=retry_result.runtime_metadata.total_runtime_seconds,
            rss_mb=_rss_mb(),
            baseline_rss_mb=retry_mem_sampler.baseline_mb,
            peak_rss_mb=retry_mem_sampler.peak_mb,
            pipeline_call_count=flaky_adapter.pipeline_call_count,
            model_load_seconds=retry_result.runtime_metadata.model_load_seconds,
            inference_seconds=retry_result.runtime_metadata.inference_seconds,
        ))
        result4.model_revision = retry_result.model_revision
    except Exception as e:
        retry_mem_sampler.stop()
        result4.samples.append(BenchmarkSample(
            label="retry_success",
            success=False, error_type=type(e).__name__, error_message=str(e)[:200],
        ))
    all_results.append(result4)

    # ------------------------------------------------------------------
    # Write results (do NOT filter successful zero-duration samples)
    # ------------------------------------------------------------------
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    json_path = os.path.join(output_dir, f"benchmark_{timestamp}.json")
    md_path = os.path.join(output_dir, f"benchmark_{timestamp}.md")

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
    with open(path, "w", encoding="utf-8") as f:
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
            f"- HF_TOKEN present: {r.hf_token_present}",
            "",
            "| Sample | Duration (s) | Baseline RSS (MB) | RSS (MB) | Peak RSS (MB) | Model Load (s) | Inference (s) | Success | Error Type | Error Message |",
            "|--------|-------------|--------------------|---------|--------------|----------------|--------------|---------|-----------|---------------|",
        ])
        for s in r.samples:
            lines.append(
                f"| {s.label} | {s.duration_seconds:.3f} | {s.baseline_rss_mb:.1f} | "
                f"{s.rss_mb:.1f} | {s.peak_rss_mb:.1f} | {s.model_load_seconds:.3f} | "
                f"{s.inference_seconds:.3f} | {s.success} | {s.error_type} | {s.error_message} |"
            )
        lines.append("")

    with open(path, "w", encoding="utf-8") as f:
        f.write("\n".join(lines))


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    run_benchmarks()
