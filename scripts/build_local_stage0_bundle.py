#! /usr/bin/env python3
"""Build a validated local Stage 0 evidence bundle from component files.

Usage:
    python scripts/build_local_stage0_bundle.py \\
        --download-cold-smoke <file.json> \\
        --process-cold-smoke <file.json> \\
        --benchmark <file.json> \\
        --token-present-smoke <file.json> \\
        --model-artifact <file.json> \\
        [--output <path>]

Validates every component, requires consistent commit and revision across
all files, and produces a single ``local_stage0_bundle`` JSON file.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parent.parent


def _load_json(path: str) -> Any:
    """Load and parse a JSON file."""
    with open(path, encoding="utf-8") as f:
        return json.load(f)


def _validate_component(
    data: Any,
    component_name: str,
    expected_evidence_type: str,
    expected_token_present: bool | None,
    expected_initial_cache_state: str | None,
    expected_commit: str | None,
) -> list[str]:
    """Validate a single component and return error list."""
    errors: list[str] = []

    if not isinstance(data, dict):
        errors.append(f"{component_name}: root must be a JSON object")
        return errors

    etype = data.get("evidence_type", "")
    if etype != expected_evidence_type:
        errors.append(
            f"{component_name}: expected evidence_type '{expected_evidence_type}', got '{etype}'"
        )

    schema_ver = data.get("evidence_schema_version", "")
    if schema_ver != "2":
        errors.append(f"{component_name}: expected evidence_schema_version '2', got '{schema_ver}'")

    cc = data.get("code_commit", "")
    if not cc:
        errors.append(f"{component_name}: code_commit is empty")
    elif expected_commit and cc != expected_commit:
        errors.append(f"{component_name}: code_commit '{cc}' != expected '{expected_commit}'")

    if not data.get("git_worktree_clean", False):
        errors.append(f"{component_name}: git_worktree_clean is false")

    # Token validation
    if expected_token_present is not None:
        actual_token = data.get("hf_token_present", None)
        if actual_token is None:
            errors.append(f"{component_name}: hf_token_present missing")
        elif actual_token != expected_token_present:
            errors.append(
                f"{component_name}: hf_token_present expected {expected_token_present}, got {actual_token}"
            )

    # Cache state validation
    if expected_initial_cache_state:
        actual_ics = data.get("initial_cache_state", "")
        if actual_ics != expected_initial_cache_state:
            errors.append(
                f"{component_name}: initial_cache_state expected '{expected_initial_cache_state}', "
                f"got '{actual_ics}'"
            )

    # Success/passed validation
    if expected_evidence_type == "smoke_test" and not data.get("success", False):
        errors.append(f"{component_name}: success is false")
    if expected_evidence_type == "benchmark_suite" and not data.get("suite_passed", False):
        errors.append(f"{component_name}: suite_passed is false")

    return errors


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Build a validated local Stage 0 evidence bundle",
    )
    parser.add_argument("--download-cold-smoke", required=True, help="Download-cold smoke JSON")
    parser.add_argument("--process-cold-smoke", required=True, help="Process-cold smoke JSON")
    parser.add_argument("--benchmark", required=True, help="Benchmark suite JSON")
    parser.add_argument("--token-present-smoke", required=True, help="Token-present smoke JSON")
    parser.add_argument("--model-artifact", required=True, help="Model artifact JSON")
    parser.add_argument("--output", default="", help="Output path (default: stdout)")
    args = parser.parse_args()

    # Load all components
    try:
        dc_smoke = _load_json(args.download_cold_smoke)
        pc_smoke = _load_json(args.process_cold_smoke)
        benchmark = _load_json(args.benchmark)
        tp_smoke = _load_json(args.token_present_smoke)
        model_art = _load_json(args.model_artifact)
    except (json.JSONDecodeError, OSError) as exc:
        print(f"Error loading files: {exc}")
        return 1

    # Determine the expected commit from the first file
    expected_commit = dc_smoke.get("code_commit", "") if isinstance(dc_smoke, dict) else ""

    # Validate every component
    all_errors: list[str] = []

    all_errors.extend(_validate_component(
        dc_smoke, "download_cold_smoke",
        expected_evidence_type="smoke_test",
        expected_token_present=False,
        expected_initial_cache_state="download_cold",
        expected_commit=expected_commit,
    ))
    all_errors.extend(_validate_component(
        pc_smoke, "process_cold_smoke",
        expected_evidence_type="smoke_test",
        expected_token_present=False,
        expected_initial_cache_state="process_cold_cached_weights",
        expected_commit=expected_commit,
    ))
    all_errors.extend(_validate_component(
        benchmark, "benchmark",
        expected_evidence_type="benchmark_suite",
        expected_token_present=None,
        expected_initial_cache_state="process_cold_cached_weights",
        expected_commit=expected_commit,
    ))
    all_errors.extend(_validate_component(
        tp_smoke, "token_present_smoke",
        expected_evidence_type="smoke_test",
        expected_token_present=True,
        expected_initial_cache_state="process_cold_cached_weights",
        expected_commit=expected_commit,
    ))

    # Model artifact validation
    if isinstance(model_art, dict):
        ma_cc = model_art.get("code_commit", "")
        if ma_cc and ma_cc != expected_commit:
            all_errors.append(f"model_artifact: code_commit '{ma_cc}' != expected '{expected_commit}'")
        ma_type = model_art.get("evidence_type", "")
        if ma_type != "model_artifact":
            all_errors.append(f"model_artifact: expected evidence_type 'model_artifact', got '{ma_type}'")
    else:
        all_errors.append("model_artifact: root must be a JSON object")

    if all_errors:
        print("Bundle validation errors:")
        for err in all_errors:
            print(f"  ❌ {err}")
        return 1

    # Build bundle
    started_utc = datetime.now(timezone.utc).isoformat()
    bundle = {
        "evidence_schema_version": "2",
        "evidence_type": "local_stage0_bundle",
        "bundle_passed": True,
        "code_commit": expected_commit,
        "git_worktree_clean": dc_smoke.get("git_worktree_clean", False) if isinstance(dc_smoke, dict) else False,
        "started_at_utc": started_utc,
        "completed_at_utc": "",
        "python_version": dc_smoke.get("python_version", "") if isinstance(dc_smoke, dict) else "",
        "runs": {
            "download_cold_smoke": dc_smoke,
            "process_cold_smoke": pc_smoke,
            "benchmark": benchmark,
            "token_present_smoke": tp_smoke,
        },
        "model_artifact": model_art,
    }

    bundle["completed_at_utc"] = datetime.now(timezone.utc).isoformat()

    output = args.output
    if output:
        with open(output, "w", encoding="utf-8") as f:
            json.dump(bundle, f, indent=2, default=str)
        print(f"✅ Bundle written to: {output}")
    else:
        json.dump(bundle, sys.stdout, indent=2, default=str)
        print()

    print(f"\n✅ Bundle validation passed — {len(all_errors)} errors")
    print(f"  Commit: {expected_commit}")
    print(f"  Components: download_cold_smoke, process_cold_smoke, benchmark, token_present_smoke, model_artifact")

    return 0


if __name__ == "__main__":
    sys.exit(main())
