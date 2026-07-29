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
from dataclasses import dataclass, field, asdict
from datetime import datetime, timezone
from typing import Any, Callable

import numpy as np
import pandas as pd

from src.config import MODEL_ID
from src.schemas import ForecastMode, ForecastTask
from src.telemetry import rss_mb, cpu_info, capture_package_versions, capture_traceability, machine_summary
from src.forecasting.chronos2_adapter import (
    Chronos2Adapter,
    AdapterError,
    ModelLoadError,
    ResultSchemaError,
    _validate_quantile_monotonic,
    InferenceError,
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
# Re-exported from src.telemetry for backward compat with existing imports.
from src.telemetry import MemorySampler as _MemorySampler


# ---------------------------------------------------------------------------
# Panel output validation
# ---------------------------------------------------------------------------


def _validate_panel_output(
    pred_df: pd.DataFrame,
    expected_item_ids: set[str],
    expected_horizon: int,
    quantile_levels: list[float],
    historical_data: pd.DataFrame,
) -> None:
    """Validate panel forecast output against all expected invariants.

    Raises ``ResultSchemaError`` on any violation.
    """
    # --- Required columns ---
    required = {"item_id", "timestamp", "predictions"}
    missing_cols = required - set(pred_df.columns)
    if missing_cols:
        raise ResultSchemaError(
            f"Panel output missing required columns: {sorted(missing_cols)}"
        )

    # --- Expected row count ---
    expected_rows = len(expected_item_ids) * expected_horizon
    if len(pred_df) != expected_rows:
        raise ResultSchemaError(
            f"Panel benchmark expected {expected_rows} rows, got {len(pred_df)}"
        )

    # --- Expected item IDs ---
    actual_ids = set(pred_df["item_id"].unique())
    if actual_ids != expected_item_ids:
        missing_ids = expected_item_ids - actual_ids
        extra_ids = actual_ids - expected_item_ids
        parts = []
        if missing_ids:
            parts.append(f"missing: {sorted(missing_ids)}")
        if extra_ids:
            parts.append(f"unexpected: {sorted(extra_ids)}")
        raise ResultSchemaError(
            "Panel benchmark item_id set mismatch: " + "; ".join(parts)
        )

    # --- Per-item checks ---
    for item_id in expected_item_ids:
        item_rows = pred_df[pred_df["item_id"] == item_id]
        if len(item_rows) != expected_horizon:
            raise ResultSchemaError(
                f"Item '{item_id}' expected {expected_horizon} forecast rows, "
                f"got {len(item_rows)}"
            )

    # --- Finite point predictions ---
    if not np.isfinite(pred_df["predictions"]).all():
        raise ResultSchemaError("Non-finite point predictions in panel output.")

    # --- Quantile columns present and finite ---
    for q in quantile_levels:
        col = str(q)
        if col not in pred_df.columns:
            raise ResultSchemaError(
                f"Missing requested quantile column '{col}' in panel output."
            )
        if not np.isfinite(pred_df[col]).all():
            raise ResultSchemaError(
                f"Non-finite values in quantile column '{col}'."
            )

    # --- Monotonic quantiles per row ---
    for _, prow in pred_df.iterrows():
        _validate_quantile_monotonic(prow, quantile_levels)

    # --- Unique (item_id, timestamp) rows ---
    keys = list(zip(pred_df["item_id"], pred_df["timestamp"].astype(str)))
    if len(keys) != len(set(keys)):
        raise ResultSchemaError("Duplicate (item_id, timestamp) rows in panel output.")

    # --- Timestamps ordered per item (BEFORE sorting — detect returned order) ---
    for item_id in expected_item_ids:
        item_rows = pred_df[pred_df["item_id"] == item_id]
        parsed = pd.to_datetime(item_rows["timestamp"])
        if list(parsed) != sorted(parsed):
            raise ResultSchemaError(
                f"Forecast timestamps for item '{item_id}' are not in order."
            )

    # --- Forecast timestamps after each item's own history ---
    hist_max_by_item = (
        pd.to_datetime(historical_data["timestamp"])
        .groupby(historical_data["item_id"])
        .max()
    )
    for item_id in expected_item_ids:
        if item_id not in hist_max_by_item.index:
            raise ResultSchemaError(
                f"Item '{item_id}' not found in historical data."
            )
        item_forecast_ts = pd.to_datetime(
            pred_df[pred_df["item_id"] == item_id]["timestamp"]
        )
        if item_forecast_ts.min() <= hist_max_by_item[item_id]:
            raise ResultSchemaError(
                f"First forecast timestamp for item '{item_id}' is not after "
                f"its last historical timestamp {hist_max_by_item[item_id]}."
            )


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
    cache_state: str = ""  # Per-sample cache state


@dataclass
class BenchmarkResult:
    """Complete benchmark results for one scenario."""
    scenario: str = ""
    python_version: str = ""
    os_name: str = ""
    cpu_info: str = ""
    model_id: str = ""
    model_revision: str = ""
    configured_revision: str = ""
    package_versions: dict[str, str] = field(default_factory=dict)
    context_rows: int = 0
    horizon: int = 0
    quantile_levels: tuple[float, ...] = ()
    samples: list[BenchmarkSample] = field(default_factory=list)
    hf_token_present: bool = False
    run_timestamp: str = ""
    cross_learning: bool = False
    n_series: int = 1
    expected_outcome: str = "pass"  # pass | expected_failure
    sample_passed: bool = False
    scenario_passed: bool = False
    # Evidence traceability (WP6)
    evidence_schema_version: str = "1"
    code_commit: str = ""
    git_worktree_clean: bool = False
    initial_cache_state: str = ""  # download_cold | process_cold_cached_weights
    cpu_model: str = ""
    cpu_logical_cores: int = 0
    ram_total_gb: float = 0.0


def _evaluate_suite(results: list[BenchmarkResult]) -> bool:
    """Return True if the entire benchmark suite passes.

    Rules:
    - Every scenario with ``expected_outcome == "pass"`` must have
      ``scenario_passed == True``.
    - ``failure_and_retry`` scenario must have ``expected_outcome == "expected_failure"``
      and its injection_failure_test must be a safe failure, followed by a
      successful retry on the same backend.
    - Rolling scenario must have exactly 10 successful folds.
    """
    for r in results:
        if r.expected_outcome == "expected_failure":
            # Injected failure expected: the failure_sample must fail safely,
            # and the retry must succeed.
            if not r.scenario_passed:
                return False
        else:
            if not r.scenario_passed:
                return False
    return True


def _make_sample(
    label: str,
    *,
    success: bool = True,
    duration_seconds: float = 0.0,
    rss_mb: float = 0.0,
    baseline_rss_mb: float = 0.0,
    peak_rss_mb: float = 0.0,
    pipeline_call_count: int = 0,
    model_load_seconds: float = 0.0,
    inference_seconds: float = 0.0,
    error_type: str = "",
    error_message: str = "",
    cache_state: str = "",
) -> BenchmarkSample:
    """Build a BenchmarkSample with the supplied fields."""
    return BenchmarkSample(
        label=label,
        success=success,
        duration_seconds=duration_seconds,
        rss_mb=rss_mb,
        baseline_rss_mb=baseline_rss_mb,
        peak_rss_mb=peak_rss_mb,
        pipeline_call_count=pipeline_call_count,
        model_load_seconds=model_load_seconds,
        inference_seconds=inference_seconds,
        error_type=error_type,
        error_message=error_message,
        cache_state=cache_state,
    )


def _rss_mb() -> float:
    """Delegate to src.telemetry.rss_mb."""
    return rss_mb()


def _cpu_info() -> str:
    """Delegate to src.telemetry.cpu_info."""
    return cpu_info()


def _package_versions() -> dict[str, str]:
    """Delegate to src.telemetry.capture_package_versions."""
    return capture_package_versions()


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
    initial_cache_state: str = "",
) -> list[BenchmarkResult]:
    """Execute all Stage 0 benchmark scenarios and write results.

    Parameters
    ----------
    output_dir : str
        Directory for JSON and Markdown output files.
    adapter_factory : callable or None
        Factory that returns a Chronos2Adapter. Defaults to ``Chronos2Adapter``.
        Use a fake factory for testing without model download.
    initial_cache_state : str
        Model-cache state at the start of the run. One of ``download_cold``,
        ``process_cold_cached_weights``.  Used to label cold samples.

    Returns
    -------
    list[BenchmarkResult]
        One entry per scenario, each with ``scenario_passed`` and
        ``sample_passed`` evaluated. Use ``_evaluate_suite()`` for the
        overall verdict.
    """
    from src.config import MODEL_REVISION as CONFIGURED_REVISION

    if adapter_factory is None:
        adapter_factory = lambda: Chronos2Adapter()

    os.makedirs(output_dir, exist_ok=True)

    all_results: list[BenchmarkResult] = []

    def _base_result(scenario: str, context_rows: int = 0, horizon: int = 13,
                     quantiles: tuple[float, ...] = (0.1, 0.5, 0.9),
                     n_series: int = 1, cross_learning: bool = False,
                     expected_outcome: str = "pass",
                     initial_cache_state: str = "") -> BenchmarkResult:
        _trace = capture_traceability()
        _machine = machine_summary()
        return BenchmarkResult(
            scenario=scenario,
            python_version=sys.version.split()[0],
            os_name=sys.platform,
            cpu_info=_cpu_info(),
            model_id=MODEL_ID,
            configured_revision=CONFIGURED_REVISION,
            package_versions=_package_versions(),
            context_rows=context_rows,
            horizon=horizon,
            quantile_levels=quantiles,
            hf_token_present=bool(os.environ.get("HF_TOKEN")),
            run_timestamp=datetime.now(timezone.utc).isoformat(),
            n_series=n_series,
            cross_learning=cross_learning,
            expected_outcome=expected_outcome,
            code_commit=_trace.get("code_commit", ""),
            git_worktree_clean=_trace.get("git_worktree_clean", False),
            initial_cache_state=initial_cache_state,
            cpu_model=_machine.get("cpu_model", ""),
            cpu_logical_cores=_machine.get("cpu_logical_cores", 0),
            ram_total_gb=_machine.get("ram_total_gb", 0.0),
        )

    def _record_sample(
        result: BenchmarkResult,
        label: str,
        *,
        success: bool = True,
        duration_seconds: float = 0.0,
        rss_mb: float = 0.0,
        baseline_rss_mb: float = 0.0,
        peak_rss_mb: float = 0.0,
        pipeline_call_count: int = 0,
        model_load_seconds: float = 0.0,
        inference_seconds: float = 0.0,
        error_type: str = "",
        error_message: str = "",
        cache_state: str = "",
    ) -> None:
        result.samples.append(_make_sample(
            label=label, success=success,
            duration_seconds=duration_seconds,
            rss_mb=rss_mb, baseline_rss_mb=baseline_rss_mb,
            peak_rss_mb=peak_rss_mb,
            pipeline_call_count=pipeline_call_count,
            model_load_seconds=model_load_seconds,
            inference_seconds=inference_seconds,
            error_type=error_type, error_message=error_message,
            cache_state=cache_state,
        ))

    # ------------------------------------------------------------------
    # Shared measurement context for telemetry capture
    # ------------------------------------------------------------------
    class _Measure:
        """Captures timing and memory for a single measurement block."""
        def __init__(self, sampler: _MemorySampler | None = None):
            self.sampler = sampler or _MemorySampler()
            self.start_time = time.perf_counter()
            self.model_load_seconds = 0.0
            self.inference_seconds = 0.0
            self.sampler.start()

        def record_load(self, seconds: float) -> None:
            self.model_load_seconds = seconds

        def record_inference(self, seconds: float) -> None:
            self.inference_seconds = seconds

        def finish(self) -> dict:
            self.sampler.stop()
            elapsed = time.perf_counter() - self.start_time
            return dict(
                duration_seconds=elapsed,
                rss_mb=_rss_mb(),
                baseline_rss_mb=self.sampler.baseline_mb,
                peak_rss_mb=self.sampler.peak_mb,
                model_load_seconds=self.model_load_seconds,
                inference_seconds=self.inference_seconds,
            )

    # ------------------------------------------------------------------
    # Scenario 1: Weekly series, 260 obs, 13-period horizon
    # ------------------------------------------------------------------
    print("\n=== Scenario 1: Weekly series (260 obs, horizon 13) ===")
    df1 = _weekly_fixture(260)
    task1 = _make_task(df1, horizon=13)
    result1 = _base_result("weekly_260_13", context_rows=260, horizon=13,
                          initial_cache_state=initial_cache_state)

    adapter = adapter_factory()
    pipeline_construction_count_before = adapter.pipeline_call_count

    # Cold forecast
    cold_fr = None
    m = _Measure()
    try:
        cold_fr = adapter.forecast(task1)
        meta = m.finish()
        meta["duration_seconds"] = cold_fr.runtime_metadata.total_runtime_seconds
        meta["model_load_seconds"] = cold_fr.runtime_metadata.model_load_seconds
        meta["inference_seconds"] = cold_fr.runtime_metadata.inference_seconds
        _record_sample(result1, "cold_forecast", **meta,
                       pipeline_call_count=adapter.pipeline_call_count,
                       cache_state=initial_cache_state)
        result1.model_revision = cold_fr.model_revision
    except Exception as e:
        meta = m.finish()
        _record_sample(result1, "cold_forecast", success=False,
                       **meta,
                       error_type=type(e).__name__, error_message=str(e)[:200],
                       cache_state=initial_cache_state)

    # Warm forecast
    warm_fr = None
    m = _Measure()
    try:
        warm_fr = adapter.forecast(task1)
        meta = m.finish()
        meta["duration_seconds"] = warm_fr.runtime_metadata.total_runtime_seconds
        meta["model_load_seconds"] = warm_fr.runtime_metadata.model_load_seconds
        meta["inference_seconds"] = warm_fr.runtime_metadata.inference_seconds
        _record_sample(result1, "warm_forecast", **meta,
                       pipeline_call_count=adapter.pipeline_call_count,
                       cache_state="same_process_warm")
    except Exception as e:
        meta = m.finish()
        _record_sample(result1, "warm_forecast", success=False,
                       **meta,
                       error_type=type(e).__name__, error_message=str(e)[:200],
                       cache_state="same_process_warm")

    # Evaluate scenario 1 (WP3: enforce genuine warm reuse)
    cold_sample = next((s for s in result1.samples if s.label == "cold_forecast"), None)
    warm_sample = next((s for s in result1.samples if s.label == "warm_forecast"), None)

    cold_ok = cold_sample is not None and cold_sample.success
    warm_ok = warm_sample is not None and warm_sample.success

    # Reuse gate conditions (WP3):
    # 1. Warm must report pipeline_reused=True
    # 2. Warm model_load_seconds must be near zero (< 0.001)
    # 3. Pipeline construction count must not have increased during warm
    warm_reused = bool(warm_fr and warm_fr.runtime_metadata.pipeline_reused)
    warm_load_zero = warm_sample is not None and warm_sample.model_load_seconds < 0.001
    pc_after_warm = adapter.pipeline_call_count
    pc_no_growth = pc_after_warm == pipeline_construction_count_before + (
        1 if (cold_fr and cold_fr.runtime_metadata.model_was_loaded_this_run) else 0
    )

    result1.sample_passed = cold_ok and warm_ok
    result1.scenario_passed = (
        cold_ok and warm_ok and warm_reused and warm_load_zero and pc_no_growth
    )
    all_results.append(result1)

    # ------------------------------------------------------------------
    # Scenario 2: Small panel — benchmark-only path
    #
    # Uses the same pipeline instance as Scenario 1 (no second model
    # load). Calls predict_df directly (bypasses the standard-univariate
    # adapter), then validates output with the full panel invariant set.
    # ------------------------------------------------------------------
    print("\n=== Scenario 2: Small panel (5 series, benchmark-only path) ===")
    df2 = _panel_fixture(n_series=5, n_points=104)
    result2 = _base_result("panel_5_series", context_rows=104 * 5, horizon=13,
                          n_series=5, cross_learning=False,
                          initial_cache_state=initial_cache_state)

    m2 = _Measure()
    panel_load_time = 0.0
    try:
        load_t0 = time.perf_counter()
        try:
            pipeline = adapter.get_pipeline()
        except ModelLoadError:
            raise
        panel_load_time = time.perf_counter() - load_t0
        m2.record_load(panel_load_time)

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
            # WP5: explicitly pass cross_learning setting
            cross_learning=False,
        )
        inference_time = time.perf_counter() - t0
        m2.record_inference(inference_time)

        # Full panel invariant validation (WP1)
        _validate_panel_output(
            pred_df=pred_df,
            expected_item_ids=expected_item_ids,
            expected_horizon=expected_horizon,
            quantile_levels=quantile_levels,
            historical_data=df2,
        )

        meta = m2.finish()
        meta["model_load_seconds"] = panel_load_time
        meta["inference_seconds"] = inference_time
        _record_sample(result2, "panel_forecast_direct", **meta,
                       pipeline_call_count=adapter.pipeline_call_count,
                       cache_state="same_process_warm")
        result2.model_revision = getattr(pipeline, "model_revision", "")
        result2.sample_passed = True
    except Exception as e:
        meta = m2.finish()
        meta["model_load_seconds"] = panel_load_time
        _record_sample(result2, "panel_forecast_direct", success=False,
                       **meta,
                       error_type=type(e).__name__, error_message=str(e)[:200],
                       cache_state="same_process_warm")
        result2.sample_passed = False
    result2.scenario_passed = result2.sample_passed
    all_results.append(result2)

    # ------------------------------------------------------------------
    # Scenario 3: 10 rolling forecast calls
    #
    # Requires exactly 10 successful folds for scenario_passed.
    # Uses ONE sampler across all folds, stopped in a finally block (WP3).
    # ------------------------------------------------------------------
    print("\n=== Scenario 3: 10 rolling calls ===")
    df3 = _weekly_fixture(260)
    result3 = _base_result("10_rolling_calls", context_rows=260, horizon=13,
                          initial_cache_state=initial_cache_state)
    rolling_sampler = _MemorySampler()
    rolling_sampler.start()
    total = 0.0
    successful_folds = 0
    try:
        for fold in range(10):
            cutoff = 260 - (10 - fold) * 13
            if cutoff < 13:
                break
            subset = df3.iloc[:cutoff]
            t_task = _make_task(subset, horizon=13)
            fold_m = _Measure()
            try:
                fr3 = adapter.forecast(t_task)
                meta = fold_m.finish()
                d = fr3.runtime_metadata.total_runtime_seconds
                total += d
                meta["duration_seconds"] = d
                meta["inference_seconds"] = fr3.runtime_metadata.inference_seconds
                _record_sample(result3, f"fold_{fold}", **meta,
                               pipeline_call_count=adapter.pipeline_call_count,
                               cache_state="same_process_warm")
                successful_folds += 1
            except Exception as e:
                meta = fold_m.finish()
                _record_sample(result3, f"fold_{fold}", success=False,
                               **meta,
                               error_type=type(e).__name__, error_message=str(e)[:200],
                               cache_state="same_process_warm")
    finally:
        rolling_sampler.stop()

    if result3.samples:
        _record_sample(result3, "total_10_folds",
                       duration_seconds=total,
                       rss_mb=_rss_mb(),
                       baseline_rss_mb=rolling_sampler.baseline_mb,
                       peak_rss_mb=rolling_sampler.peak_mb,
                       cache_state="aggregate")
    result3.sample_passed = successful_folds == 10
    result3.scenario_passed = result3.sample_passed
    all_results.append(result3)

    # ------------------------------------------------------------------
    # Scenario 4: Failure + retry
    #
    # Uses a fake adapter/pipeline that fails, then retries with valid data.
    # The failure is constructed INSIDE the protected block so the suite
    # does NOT terminate before the retry test.
    #
    # expected_outcome is "expected_failure": the injected failure is a
    # pass only when the safe failure occurs AND the same backend recovers.
    # ------------------------------------------------------------------
    print("\n=== Scenario 4: Failure + retry (same adapter instance) ===")
    result4 = _base_result("failure_and_retry", context_rows=0, horizon=13,
                          expected_outcome="expected_failure",
                          initial_cache_state=initial_cache_state)

    # A pipeline that fails its first call, then succeeds -- proves the
    # SAME adapter/cached pipeline recovers and remains usable after an
    # InferenceError, rather than just proving a fresh adapter works.
    flaky_pipeline = _TransientFailurePipeline(fail_first_n_calls=1)
    flaky_adapter = Chronos2Adapter(pipeline_or_provider=flaky_pipeline)
    valid_task = _make_task(_weekly_fixture(50), horizon=13)
    failure_occurred = False
    retry_succeeded = False

    # Use a synthetic state for the failure/retry scenario since it uses a
    # fake pipeline that does not depend on model cache.
    _failure_cache_state = "synthetic_fake"

    m4_fail = _Measure()
    try:
        flaky_adapter.forecast(valid_task)
        meta = m4_fail.finish()
        _record_sample(result4, "injection_failure_test", **meta, success=True,
                       error_type="UnexpectedSuccess",
                       error_message="Flaky pipeline did not fail as expected",
                       pipeline_call_count=flaky_adapter.pipeline_call_count,
                       cache_state=_failure_cache_state)
    except AdapterError as e:
        meta = m4_fail.finish()
        _record_sample(result4, "injection_failure_test", **meta, success=False,
                       error_type=type(e).__name__, error_message=str(e)[:200],
                       pipeline_call_count=flaky_adapter.pipeline_call_count,
                       cache_state=_failure_cache_state)
        failure_occurred = True

    # Retry on the SAME adapter/pipeline (no new adapter is constructed)
    m4_retry = _Measure()
    try:
        retry_result = flaky_adapter.forecast(valid_task)
        meta = m4_retry.finish()
        meta["duration_seconds"] = retry_result.runtime_metadata.total_runtime_seconds
        meta["model_load_seconds"] = retry_result.runtime_metadata.model_load_seconds
        meta["inference_seconds"] = retry_result.runtime_metadata.inference_seconds
        _record_sample(result4, "retry_success", **meta,
                       pipeline_call_count=flaky_adapter.pipeline_call_count,
                       cache_state=_failure_cache_state)
        result4.model_revision = retry_result.model_revision
        retry_succeeded = True
    except Exception as e:
        meta = m4_retry.finish()
        _record_sample(result4, "retry_success", success=False,
                       **meta,
                       error_type=type(e).__name__, error_message=str(e)[:200],
                       cache_state=_failure_cache_state)

    # Scenario 4 passes when: call failed safely AND retry succeeded
    result4.sample_passed = failure_occurred and retry_succeeded
    result4.scenario_passed = result4.sample_passed
    all_results.append(result4)

    # ------------------------------------------------------------------
    # Evaluate suite pass/fail
    # ------------------------------------------------------------------
    suite_ok = _evaluate_suite(all_results)
    started_at = all_results[0].run_timestamp if all_results else datetime.now(timezone.utc).isoformat()
    completed_at = datetime.now(timezone.utc).isoformat()
    for r in all_results:
        # Write configured revision into each result
        r.configured_revision = CONFIGURED_REVISION

    # ------------------------------------------------------------------
    # Write results (suite envelope v2)
    # ------------------------------------------------------------------
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    json_path = os.path.join(output_dir, f"benchmark_{timestamp}.json")
    md_path = os.path.join(output_dir, f"benchmark_{timestamp}.md")

    _write_json(all_results, json_path, suite_passed=suite_ok,
                initial_cache_state=initial_cache_state,
                started_at_utc=started_at, completed_at_utc=completed_at)
    _write_markdown(all_results, md_path)

    print(f"\nResults written to:\n  {json_path}\n  {md_path}")
    print(f"\nSuite passed: {suite_ok}")
    for r in all_results:
        status = "PASS" if r.scenario_passed else "FAIL"
        print(f"  [{status}] {r.scenario} (expected={r.expected_outcome}, "
              f"samples={len(r.samples)})")
    return all_results


def _write_json(results: list[BenchmarkResult], path: str, *,
                suite_passed: bool = False,
                initial_cache_state: str = "",
                started_at_utc: str = "",
                completed_at_utc: str = "") -> None:
    """Write benchmark results as a v2 suite envelope."""
    trace = capture_traceability()
    scenarios = []
    for r in results:
        d = asdict(r)
        d["samples"] = [asdict(s) for s in r.samples]
        # Add traceability fields if not already present
        if not d.get("code_commit"):
            d["code_commit"] = trace.get("code_commit", "")
        if not d.get("git_worktree_clean"):
            d["git_worktree_clean"] = trace.get("git_worktree_clean", False)
        scenarios.append(d)

    envelope = {
        "evidence_schema_version": "2",
        "evidence_type": "benchmark_suite",
        "suite_passed": suite_passed,
        "code_commit": trace.get("code_commit", ""),
        "git_worktree_clean": trace.get("git_worktree_clean", False),
        "git_traceability_error": trace.get("git_traceability_error", ""),
        "initial_cache_state": initial_cache_state,
        "started_at_utc": started_at_utc,
        "completed_at_utc": completed_at_utc,
        "python_version": sys.version.split()[0] if scenarios else "",
        "model_id": MODEL_ID,
        "configured_revision": results[0].configured_revision if results else "",
        "scenarios": scenarios,
    }
    with open(path, "w", encoding="utf-8") as f:
        json.dump(envelope, f, indent=2, default=str)


def _write_markdown(results: list[BenchmarkResult], path: str) -> None:
    suite_ok = _evaluate_suite(results)
    lines = [
        "# Stage 0 Benchmark Report",
        f"Generated: {datetime.now(timezone.utc).isoformat()}",
        "",
        "## Suite verdict",
        f"- **Suite passed:** {suite_ok}",
        "",
        "## Environment",
        f"- Python: {sys.version.split()[0]}",
        f"- OS: {sys.platform}",
        f"- Model: {MODEL_ID}",
        f"- Configured revision: {results[0].configured_revision if results else ''}",
        "",
    ]
    for r in results:
        status = "PASS" if r.scenario_passed else "FAIL"
        lines.extend([
            f"## Scenario: {r.scenario}  [{status}]",
            f"- Expected outcome: {r.expected_outcome}",
            f"- Scenario passed: {r.scenario_passed}",
            f"- Context rows: {r.context_rows}",
            f"- Horizon: {r.horizon}",
            f"- Quantiles: {r.quantile_levels}",
            f"- HF_TOKEN present: {r.hf_token_present}",
            f"- Cross-learning: {r.cross_learning}",
            f"- Model revision: {r.model_revision}",
            f"- Initial cache state: {r.initial_cache_state}",
            "",
            "| Sample | Duration (s) | Baseline RSS (MB) | RSS (MB) | Peak RSS (MB) | Model Load (s) | Inference (s) | Cache State | Success | Error Type | Error Message |",
            "|--------|-------------|--------------------|---------|--------------|----------------|--------------|-----------|---------|-----------|---------------|",
        ])
        for s in r.samples:
            lines.append(
                f"| {s.label} | {s.duration_seconds:.3f} | {s.baseline_rss_mb:.1f} | "
                f"{s.rss_mb:.1f} | {s.peak_rss_mb:.1f} | {s.model_load_seconds:.3f} | "
                f"{s.inference_seconds:.3f} | {s.cache_state} | {s.success} | "
                f"{s.error_type} | {s.error_message} |"
            )
        lines.append("")

    with open(path, "w", encoding="utf-8") as f:
        f.write("\n".join(lines))


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    run_benchmarks()
