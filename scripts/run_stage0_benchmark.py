#! /usr/bin/env python3
"""Run the Stage 0 benchmark suite and write results to D:\Forecasting-Tool-Local\benchmarks.

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

    # Print summary
    print("\n" + "=" * 64)
    print("Benchmark Summary")
    print("=" * 64)
    for r in results:
        status = "PASS" if r.scenario_passed else "FAIL"
        successes = sum(1 for s in r.samples if s.success)
        failures = sum(1 for s in r.samples if not s.success)
        durations = [s.duration_seconds for s in r.samples if s.success and s.duration_seconds > 0]
        avg_dur = sum(durations) / len(durations) if durations else 0
        print(f"  [{status}] {r.scenario}: {successes} ok, {failures} fail, avg_dur={avg_dur:.3f}s")
    print(f"  Suite overall: {'PASS' if suite_ok else 'FAIL'}")
    print("=" * 64)

    return 0 if suite_ok else 1


if __name__ == "__main__":
    sys.exit(main())
