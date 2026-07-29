#! /usr/bin/env python3
"""Run the Stage 0 benchmark suite and write results.

Output directory defaults to D:\\Forecasting-Tool-Local\\benchmarks on Windows.

Exits non-zero when the required suite fails (WP2).

Usage:
    D:\Forecasting-Tool-Local\venv\Scripts\python.exe scripts\run_stage0_benchmark.py
"""
from __future__ import annotations

import sys
import os

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from src.benchmarking import (
    run_benchmarks,
    _evaluate_suite,
)


def main() -> int:
    output_dir = os.environ.get(
        "BENCHMARK_OUTPUT_DIR",
        r"D:\Forecasting-Tool-Local\benchmarks",
    )
    print(f"Benchmark output directory: {output_dir}")
    results = run_benchmarks(output_dir=output_dir)

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

    return 0 if suite_ok else 1


if __name__ == "__main__":
    sys.exit(main())
