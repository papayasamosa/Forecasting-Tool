#! /usr/bin/env python3
"""Run the Stage 0 benchmark suite and write results.

Output directory defaults to D:\\Forecasting-Tool-Local\\benchmarks on Windows.

Exits non-zero when the required suite fails (WP2).

Usage:
    D:\Forecasting-Tool-Local\venv\Scripts\python.exe scripts\run_stage0_benchmark.py --initial-cache-state process_cold_cached_weights
"""
from __future__ import annotations

import argparse
import sys
import os

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from src.benchmarking import (
    run_benchmarks,
    _evaluate_suite,
)


def _parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    """Parse CLI arguments for the benchmark runner."""
    parser = argparse.ArgumentParser(
        description="Stage 0 benchmark suite",
    )
    parser.add_argument(
        "--initial-cache-state",
        type=str,
        default=os.environ.get("BENCHMARK_INITIAL_CACHE_STATE", ""),
        choices=["download_cold", "process_cold_cached_weights"],
        help=(
            "Model-cache state at the start of the run. "
            "Required for release-evidence mode. "
            "Environment fallback: BENCHMARK_INITIAL_CACHE_STATE."
        ),
    )
    parser.add_argument(
        "--output-dir",
        type=str,
        default=os.environ.get("BENCHMARK_OUTPUT_DIR", r"D:\Forecasting-Tool-Local\benchmarks"),
        help="Output directory for benchmark results.",
    )
    return parser.parse_args(argv)


def main() -> int:
    args = _parse_args()
    output_dir = args.output_dir
    initial_cache_state = args.initial_cache_state

    if not initial_cache_state:
        print(
            "ERROR: --initial-cache-state is required for release-evidence mode.\n"
            "  Valid values: download_cold, process_cold_cached_weights\n"
            "  Set via --initial-cache-state or BENCHMARK_INITIAL_CACHE_STATE env var."
        )
        return 1

    print(f"Benchmark output directory: {output_dir}")
    print(f"Initial cache state: {initial_cache_state}")
    results = run_benchmarks(
        output_dir=output_dir,
        initial_cache_state=initial_cache_state,
    )

    suite_ok = _evaluate_suite(results)

    # Print summary (WP6: exclude aggregate samples from fold averages)
    print("\n" + "=" * 64)
    print("Benchmark Summary")
    print("=" * 64)
    for r in results:
        status = "PASS" if r.scenario_passed else "FAIL"
        successes = sum(1 for s in r.samples if s.success)
        failures = sum(1 for s in r.samples if not s.success)
        # Exclude aggregate samples (e.g. total_10_folds) from fold averages
        fold_samples = [s for s in r.samples if not s.label.startswith("total_")]
        durations = [s.duration_seconds for s in fold_samples if s.success and s.duration_seconds > 0]
        avg_dur = sum(durations) / len(durations) if durations else 0
        # Separate aggregate reporting
        total_samples = [s for s in r.samples if s.label.startswith("total_")]
        total_line = ""
        if total_samples:
            ts = total_samples[0]
            total_line = f", total={ts.duration_seconds:.3f}s"
        print(f"  [{status}] {r.scenario}: {successes} ok, {failures} fail, "
              f"mean_fold={avg_dur:.3f}s{total_line}")
    print(f"  Suite overall: {'PASS' if suite_ok else 'FAIL'}")
    print("=" * 64)

    # WP3: Validate final envelope recursively
    sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
    from src.evidence_validation import validate_recursive

    # Load the written JSON envelope for validation
    json_files = [
        os.path.join(output_dir, f)
        for f in os.listdir(output_dir)
        if f.startswith("benchmark_") and f.endswith(".json")
    ]
    if json_files:
        import json
        latest = max(json_files, key=os.path.getmtime)
        with open(latest, encoding="utf-8") as f:
            envelope = json.load(f)
        v_errors = validate_recursive(envelope, label="benchmark_suite")
        if v_errors:
            print("\nRelease validation errors:")
            for err in v_errors:
                print(f"  [FAIL] {err}")
            return 1
        print(f"  Release validation: OK")

    return 0 if suite_ok else 1


if __name__ == "__main__":
    sys.exit(main())
