#! /usr/bin/env python3
"""Stage 0.1 — Minimal Local Proof for Chronos-2.

Usage:
    python scripts/chronos2_smoke_test.py --initial-cache-state download_cold
    python scripts/chronos2_smoke_test.py --initial-cache-state process_cold_cached_weights

Emits a JSON evidence record alongside console output.
Every failure phase attempts JSON evidence writing (WP7, P1-5).

The ``--initial-cache-state`` argument is required for release-evidence mode.
It describes the model-cache state before the run:

- ``download_cold`` — First-ever run on a machine; no model files cached.
- ``process_cold_cached_weights`` — Weight files already cached from a
  previous run; cold phase still constructs the pipeline fresh.

The warm phase always records ``same_process_warm``.
"""
from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
import time
import uuid
from datetime import datetime, timezone

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import numpy as np  # noqa: E402
import pandas as pd  # noqa: E402

from src.config import MODEL_ID, MODEL_REVISION, DEFAULT_QUANTILES  # noqa: E402
from src.schemas import ForecastTask, ForecastMode  # noqa: E402
from src.forecasting.chronos2_adapter import (  # noqa: E402
    Chronos2Adapter,
)
from src.telemetry import (  # noqa: E402
    rss_mb,
    write_evidence,
    capture_package_versions,
    capture_traceability,
    machine_summary,
)

# ---------------------------------------------------------------------------
# Default evidence output path (platform-aware)
# ---------------------------------------------------------------------------
if sys.platform == "win32":
    DEFAULT_EVIDENCE_DIR = r"D:\Forecasting-Tool-Local\benchmarks"
else:
    DEFAULT_EVIDENCE_DIR = os.path.join(os.path.expanduser("~"), "forecast-benchmarks")


def _build_weekly_fixture(n_points: int = 260) -> pd.DataFrame:
    rng = np.random.default_rng(seed=42)
    t = np.arange(n_points)
    trend = 100 + 0.1 * t
    seasonality = 10 * np.sin(2 * np.pi * t / 52)
    noise = rng.normal(0, 2, size=n_points)
    values = trend + seasonality + noise
    dates = pd.date_range("2020-01-06", periods=n_points, freq="W")
    return pd.DataFrame({"timestamp": dates, "target": values})


def _apply_token_result(evidence: dict, result: dict) -> None:
    """Populate whichever token-path slot matches this run's HF_TOKEN state.

    Only the attempted path is ever populated with real data; the other path
    is always recorded as not attempted. This is producer-emitted from the
    actual runtime environment and forecast outcome — evidence fields must
    never be hand-edited or copied from a different run to simulate a path
    that was not exercised.
    """
    if evidence["hf_token_present"]:
        evidence["token_present_result"] = result
        evidence["token_absent_result"] = {"attempted": False}
    else:
        evidence["token_absent_result"] = result
        evidence["token_present_result"] = {"attempted": False}


def run_smoke_test(
    evidence_dir: str = DEFAULT_EVIDENCE_DIR,
    initial_cache_state: str = "",
) -> dict:
    """Run the smoke test and return/export a structured evidence dict.

    Parameters
    ----------
    evidence_dir : str
        Directory for evidence JSON output.
    initial_cache_state : str
        One of ``download_cold``, ``process_cold_cached_weights``, or
        ``same_process_warm``.  Describes the model-cache state before
        the run.  Must be non-empty for release-evidence mode.

    Returns a JSON-serialisable dict with all measurements, or a dict
    with ``success=False`` and error details on failure.
    """
    _started = datetime.now(timezone.utc)
    _run_id = str(uuid.uuid4())

    # WP1: Cache inspection before the run
    from src.telemetry import inspect_hf_cache, build_cache_preflight
    pre_run_inspection = inspect_hf_cache(MODEL_REVISION)

    if initial_cache_state == "download_cold" and pre_run_inspection.get("snapshot_present", False):
        print("  ERROR: --initial-cache-state=download_cold but snapshot is already cached.")
        print(f"    Use a fresh cache directory or --initial-cache-state=process_cold_cached_weights")
        evidence = {
            "evidence_schema_version": "2",
            "evidence_type": "smoke_test",
            "test": "chronos2_smoke_test",
            "timestamp": _started.isoformat(),
            "started_at_utc": _started.isoformat(),
            "completed_at_utc": _started.isoformat(),
            "success": False,
            "failure_phase": "cache_preflight",
            "error": f"Cache state mismatch: labeled '{initial_cache_state}' but snapshot is already cached",
            "python_version": sys.version.split()[0],
            "model_id": MODEL_ID,
            "configured_revision": MODEL_REVISION,
            "model_revision": "",
            "hf_token_present": bool(os.environ.get("HF_TOKEN")),
            "cold": {},
            "warm": {},
            "package_versions": {},
            "initial_cache_state": initial_cache_state,
        }
        evidence.update(capture_traceability())
        evidence.update(machine_summary())
        evidence["evidence_path"] = write_evidence(evidence, evidence_dir, prefix="smoke_test")
        return evidence
    if initial_cache_state == "process_cold_cached_weights" and not pre_run_inspection.get("snapshot_present", False):
        print("  ERROR: --initial-cache-state=process_cold_cached_weights but snapshot is not cached.")
        print(f"    Run with --initial-cache-state=download_cold first.")
        evidence = {
            "evidence_schema_version": "2",
            "evidence_type": "smoke_test",
            "test": "chronos2_smoke_test",
            "timestamp": _started.isoformat(),
            "started_at_utc": _started.isoformat(),
            "completed_at_utc": _started.isoformat(),
            "success": False,
            "failure_phase": "cache_preflight",
            "error": f"Cache state mismatch: labeled '{initial_cache_state}' but snapshot is not cached",
            "python_version": sys.version.split()[0],
            "model_id": MODEL_ID,
            "configured_revision": MODEL_REVISION,
            "model_revision": "",
            "hf_token_present": bool(os.environ.get("HF_TOKEN")),
            "cold": {},
            "warm": {},
            "package_versions": {},
            "initial_cache_state": initial_cache_state,
        }
        evidence.update(capture_traceability())
        evidence.update(machine_summary())
        evidence["evidence_path"] = write_evidence(evidence, evidence_dir, prefix="smoke_test")
        return evidence

    evidence: dict = {
        "evidence_schema_version": "2",
        "evidence_type": "smoke_test",
        "test": "chronos2_smoke_test",
        "timestamp": _started.isoformat(),
        "started_at_utc": _started.isoformat(),
        "completed_at_utc": "",
        "success": False,
        "python_version": sys.version.split()[0],
        "model_id": MODEL_ID,
        "configured_revision": MODEL_REVISION,
        "model_revision": "",
        "hf_token_present": bool(os.environ.get("HF_TOKEN")),
        "cold": {},
        "cache_preflight": pre_run_inspection,
        "warm": {},
        "package_versions": {},
        "error": "",
        "initial_cache_state": initial_cache_state,
    }
    # Capture traceability & machine info upfront
    evidence.update(capture_traceability())
    evidence.update(machine_summary())

    print("=" * 64)
    print("  Chronos-2 Smoke Test — Stage 0.1")
    print("=" * 64)

    baseline_rss = rss_mb()
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
        evidence["completed_at_utc"] = datetime.now(timezone.utc).isoformat()
        _apply_token_result(evidence, {
            "attempted": True,
            "success": False,
            "configured_revision": MODEL_REVISION,
            "resolved_revision": "",
            "timing_seconds": round(time.perf_counter() - t0, 3),
            "error_code": type(exc).__name__,
            "run_id": _run_id,
            "started_at_utc": evidence["started_at_utc"],
            "completed_at_utc": evidence["completed_at_utc"],
        })
        evidence["evidence_path"] = write_evidence(evidence, evidence_dir, prefix="smoke_test")
        return evidence
    cold_time = time.perf_counter() - t0
    cold_rss = rss_mb()
    _cold_completed_at = datetime.now(timezone.utc).isoformat()

    evidence["cold"] = {
        "total_seconds": round(cold_time, 3),
        "model_load_seconds": result.runtime_metadata.model_load_seconds,
        "inference_seconds": result.runtime_metadata.inference_seconds,
        "result_conversion_seconds": result.runtime_metadata.result_conversion_seconds,
        "rss_mb": round(cold_rss, 1),
        "pipeline_call_count": adapter.pipeline_call_count,
        "model_revision": result.model_revision,
        "cache_state": initial_cache_state,
    }
    evidence["model_revision"] = result.model_revision

    # Token path result (WP8): the cold phase is where the model is resolved
    # under the current HF_TOKEN state, so a successful cold forecast means
    # this token path succeeded — independent of whether the warm phase or
    # schema checks below later fail the overall smoke test.
    _apply_token_result(evidence, {
        "attempted": True,
        "success": True,
        "configured_revision": MODEL_REVISION,
        "resolved_revision": result.model_revision,
        "timing_seconds": round(cold_time, 3),
        "run_id": _run_id,
        "started_at_utc": evidence["started_at_utc"],
        "completed_at_utc": _cold_completed_at,
    })

    print(f"  Cold time      : {cold_time:.3f}s")
    print(f"  Pipeline calls : {adapter.pipeline_call_count}")
    print(f"  RSS            : {cold_rss:.1f} MB")
    print(f"  Run ID         : {result.run_id}")
    print(f"  Model revision : {result.model_revision}")
    print(f"  # Forecast rows: {len(result.forecast_rows)}")

    # Warm forecast (WP7: wrapped for evidence on failure)
    print("\n  --- Warm forecast ---")
    warm_result = None
    try:
        t1 = time.perf_counter()
        warm_result = adapter.forecast(task)
        warm_time = time.perf_counter() - t1
        warm_rss = rss_mb()

        evidence["warm"] = {
            "total_seconds": round(warm_time, 3),
            "model_load_seconds": warm_result.runtime_metadata.model_load_seconds,
            "inference_seconds": warm_result.runtime_metadata.inference_seconds,
            "result_conversion_seconds": warm_result.runtime_metadata.result_conversion_seconds,
            "rss_mb": round(warm_rss, 1),
            "pipeline_call_count": adapter.pipeline_call_count,
            "pipeline_reused": warm_result.runtime_metadata.pipeline_reused,
            "cache_state": "same_process_warm",
        }

        print(f"  Warm time      : {warm_time:.3f}s")
        print(f"  Pipeline calls : {adapter.pipeline_call_count} (should be 1)")
        print(f"  RSS            : {warm_rss:.1f} MB")
    except Exception as exc:
        warm_time = time.perf_counter() - t1 if 't1' in dir() else 0
        warm_rss = rss_mb()
        evidence["warm"] = {
            "total_seconds": round(warm_time, 3),
            "rss_mb": round(warm_rss, 1),
            "pipeline_call_count": adapter.pipeline_call_count,
            "error": f"{type(exc).__name__}: {exc}",
            "failure_phase": "warm_forecast",
            "cache_state": "same_process_warm",
        }
        evidence["error"] = f"warm_forecast: {type(exc).__name__}: {exc}"
        evidence["completed_at_utc"] = datetime.now(timezone.utc).isoformat()
        evidence["evidence_path"] = write_evidence(evidence, evidence_dir, prefix="smoke_test")
        print(f"  WARM FAILED: {exc}")
        # Preserve cold evidence — return with warm failure recorded
        return evidence

    # Output verification (WP7: wrapped for evidence on failure)
    try:
        assert len(result.forecast_rows) == horizon, f"Expected {horizon} rows, got {len(result.forecast_rows)}"
        first = result.forecast_rows[0]
        assert "run_id" in first
        assert "point_prediction" in first
        assert "quantile_0_1" in first
        assert "quantile_0_5" in first
        assert "quantile_0_9" in first
        print("\n  Output schema OK")
    except AssertionError as exc:
        evidence["error"] = f"schema_check: {exc}"
        evidence["failure_phase"] = "schema_verification"
        evidence["completed_at_utc"] = datetime.now(timezone.utc).isoformat()
        evidence["evidence_path"] = write_evidence(evidence, evidence_dir, prefix="smoke_test")
        print(f"  SCHEMA CHECK FAILED: {exc}")
        return evidence

    # Package versions
    pkg = capture_package_versions()
    evidence["package_versions"] = pkg
    print("\n  Package versions:")
    for k, v in pkg.items():
        print(f"    {k}: {v}")

    # WP1: Post-run cache inspection and build complete CachePreflight
    from src.telemetry import build_cache_preflight
    post_run_inspection = inspect_hf_cache(MODEL_REVISION)
    evidence["cache_preflight"] = build_cache_preflight(
        pre_run_inspection, post_run_inspection, initial_cache_state,
    )

    evidence["success"] = True
    evidence["completed_at_utc"] = datetime.now(timezone.utc).isoformat()
    print(f"\n{'=' * 64}")
    print("  Smoke test completed successfully!")
    print("=" * 64)

    # WP2: Validate final evidence recursively before writing
    from src.evidence_validation import validate_recursive
    v_errors = validate_recursive(evidence, label="smoke_test")
    if v_errors:
        print("\n  Evidence validation errors (preserving partial evidence):")
        for err in v_errors:
            print(f"    [FAIL] {err}")
        evidence["error"] = f"evidence_validation: {'; '.join(v_errors)}"
        evidence["evidence_path"] = write_evidence(evidence, evidence_dir, prefix="smoke_test")
        return evidence

    evidence["evidence_path"] = write_evidence(evidence, evidence_dir, prefix="smoke_test")
    return evidence


def _parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    """Parse CLI arguments for the smoke test.

    Returns
    -------
    argparse.Namespace
        Parsed arguments with ``initial_cache_state`` and
        ``evidence_dir`` attributes.
    """
    parser = argparse.ArgumentParser(
        description="Chronos-2 smoke test — Stage 0.1",
    )
    parser.add_argument(
        "--initial-cache-state",
        type=str,
        default=os.environ.get("SMOKE_INITIAL_CACHE_STATE", ""),
        choices=["download_cold", "process_cold_cached_weights"],
        help=(
            "Model-cache state before the run. "
            "Required for release-evidence mode. "
            "Environment fallback: SMOKE_INITIAL_CACHE_STATE."
        ),
    )
    parser.add_argument(
        "--evidence-dir",
        type=str,
        default=os.environ.get("BENCHMARK_OUTPUT_DIR", DEFAULT_EVIDENCE_DIR),
        help="Directory for evidence JSON output.",
    )
    return parser.parse_args(argv)


if __name__ == "__main__":
    args = _parse_args()
    evidence_dir = args.evidence_dir
    initial_cache_state = args.initial_cache_state

    if not initial_cache_state:
        print(
            "ERROR: --initial-cache-state is required for release-evidence mode.\n"
            "  Valid values: download_cold, process_cold_cached_weights\n"
            "  Set via --initial-cache-state or SMOKE_INITIAL_CACHE_STATE env var.\n"
            "  Warm phase always records same_process_warm."
        )
        sys.exit(1)

    try:
        evidence = run_smoke_test(
            evidence_dir=evidence_dir,
            initial_cache_state=initial_cache_state,
        )
    except Exception as exc:
        # WP5: Wrap the invocation itself to catch pre-assignment failures
        # (fixture construction, task creation, package capture, etc.).
        # Preserve parsed initial_cache_state even on failure (WP6).
        _now = datetime.now(timezone.utc)
        evidence = {
            "test": "chronos2_smoke_test",
            "timestamp": _now.isoformat(),
            "started_at_utc": _now.isoformat(),
            "completed_at_utc": _now.isoformat(),
            "success": False,
            "evidence_schema_version": "2",
            "evidence_type": "smoke_test",
            "failure_phase": "top_level_invocation",
            "error": f"{type(exc).__name__}: {exc}",
            "python_version": sys.version.split()[0],
            "model_id": MODEL_ID,
            "configured_revision": MODEL_REVISION,
            "model_revision": "",
            "hf_token_present": bool(os.environ.get("HF_TOKEN")),
            "cold": {},
            "warm": {},
            "package_versions": {},
            "initial_cache_state": initial_cache_state,
        }
        evidence.update(capture_traceability())
        evidence.update(machine_summary())
        print(f"\n  TOP-LEVEL FAILURE: {type(exc).__name__}: {exc}")
        evidence["evidence_path"] = write_evidence(
            evidence, evidence_dir, prefix="smoke_test"
        )
        sys.exit(1)

    if not evidence.get("success"):
        # Ensure evidence is written even on unexpected top-level failure
        # within run_smoke_test.
        if "evidence_path" not in evidence:
            evidence["failure_phase"] = "top_level"
            evidence["evidence_path"] = write_evidence(
                evidence, evidence_dir, prefix="smoke_test"
            )
        sys.exit(1)
