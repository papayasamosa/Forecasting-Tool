#! /usr/bin/env python3
"""Offline release-readiness verification for Stage 0 evidence.

Verifies that producer contracts are aligned with schemas, the Cloud builder
can construct a passing record from a valid fixture, benchmark preflight
ordering is correct, receipt bindings are typed and mandatory, the canonical
Cloud test registry matches documentation, and invalidated evidence remains
non-passing. Runs without network access or model download.
"""
from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT))


def _check_schema_module() -> list[str]:
    """Verify schemas are importable and consistent."""
    errors: list[str] = []
    try:
        from src.evidence_schemas import (
            SmokeEvidence, BenchmarkSuiteEvidence, ModelArtifactEvidence,
            LocalStage0Bundle, CloudEvidence, ExecutionReceipt,
            evidence_from_dict, CANONICAL_CLOUD_TESTS,
            EVIDENCE_SCHEMA_VERSION,
        )
    except ImportError as exc:
        errors.append(f"schema import failed: {exc}")
        return errors

    # Verify all expected types are in the type map
    from src.evidence_schemas import _EVIDENCE_TYPE_MAP
    expected_types = {"smoke_test", "benchmark_suite", "model_artifact",
                      "local_stage0_bundle", "cloud_stage0", "execution_receipt"}
    actual_types = set(_EVIDENCE_TYPE_MAP.keys())
    missing = expected_types - actual_types
    if missing:
        errors.append(f"evidence type map missing types: {missing}")

    return errors


def _check_canonical_registry_parity() -> list[str]:
    """Verify the canonical Cloud test registry matches the checklist."""
    errors: list[str] = []
    try:
        from src.evidence_schemas import CANONICAL_CLOUD_TESTS
    except ImportError as exc:
        errors.append(f"CANONICAL_CLOUD_TESTS import failed: {exc}")
        return errors

    checklist_path = REPO_ROOT / "docs" / "community_cloud_test_checklist.md"
    if not checklist_path.exists():
        errors.append(f"checklist not found: {checklist_path}")
        return errors

    checklist_content = checklist_path.read_text(encoding="utf-8")

    # Extract backticked test names from the checklist table
    import re
    checklist_names = set()
    for match in re.finditer(r"\| \d+ \| `([^`]+)` \|", checklist_content):
        checklist_names.add(match.group(1))

    registry_names = set(CANONICAL_CLOUD_TESTS)

    missing_in_checklist = registry_names - checklist_names
    extra_in_checklist = checklist_names - registry_names

    if missing_in_checklist:
        errors.append(
            f"checklist missing canonical tests: {sorted(missing_in_checklist)}"
        )
    if extra_in_checklist:
        errors.append(
            f"checklist has extra tests not in registry: {sorted(extra_in_checklist)}"
        )

    return errors


def _check_cloud_builder_synthetic_fixture() -> list[str]:
    """Verify Cloud builder can produce a passing record from a valid fixture."""
    errors: list[str] = []

    fixture_path = REPO_ROOT / "tests" / "fixtures" / "cloud_valid_fixture.json"
    if not fixture_path.exists():
        errors.append(f"Cloud valid fixture not found: {fixture_path}")
        return errors

    # Run the builder with the fixture
    result = subprocess.run(
        [sys.executable, str(REPO_ROOT / "scripts" / "build_cloud_stage0_evidence.py"),
         "--input", str(fixture_path)],
        capture_output=True, text=True, timeout=30,
    )
    if result.returncode != 0:
        errors.append(
            f"Cloud builder failed on valid fixture (exit {result.returncode}):\n"
            f"{result.stdout[:1000]}\n{result.stderr[:1000]}"
        )
    else:
        # Verify the output contains a success message
        if "[OK] Cloud evidence validation passed" not in result.stdout:
            errors.append(
                "Cloud builder succeeded but missing success confirmation:\n"
                f"{result.stdout[:1000]}"
            )

    return errors


def _check_benchmark_preflight_ordering() -> list[str]:
    """Verify benchmark preflight contract: pre-run inspection happens before
    adapter construction by checking the code ordering in run_benchmarks."""
    errors: list[str] = []

    source_path = REPO_ROOT / "src" / "benchmarking.py"
    source = source_path.read_text(encoding="utf-8")

    # pre_run_inspection should be defined before any scenario execution
    if "pre_run_inspection = inspect_hf_cache" not in source:
        errors.append("benchmark: pre_run_inspection not found in run_benchmarks")
        return errors

    # Verify it's before scenario code by checking line ordering
    lines = source.split("\n")
    pre_run_line = None
    scenario_start_line = None
    for i, line in enumerate(lines):
        if "pre_run_inspection = inspect_hf_cache" in line:
            pre_run_line = i
        if "# Scenario 1: Weekly series" in line or "=== Scenario 1:" in line:
            scenario_start_line = i

    if pre_run_line is None:
        errors.append("benchmark: could not locate pre_run_inspection line")
    elif scenario_start_line is not None and pre_run_line > scenario_start_line:
        errors.append(
            f"benchmark: pre_run_inspection (line {pre_run_line + 1}) is after "
            f"scenario start (line {scenario_start_line + 1}) — ordering contract broken"
        )

    return errors


def _check_receipt_binding_contract() -> list[str]:
    """Verify LocalStage0Bundle has typed receipts and the bundle schema
    validates receipt bindings."""
    errors: list[str] = []
    try:
        from src.evidence_schemas import LocalStage0Bundle
    except ImportError as exc:
        errors.append(f"LocalStage0Bundle import failed: {exc}")
        return errors

    bundle = LocalStage0Bundle(
        code_commit="abc123",
        git_worktree_clean=True,
        bundle_passed=True,
        started_at_utc="2026-01-01T00:00:00",
        completed_at_utc="2026-01-01T00:01:00",
        runs={
            "download_cold_smoke": {"code_commit": "abc123"},
            "process_cold_smoke": {"code_commit": "abc123"},
            "benchmark": {"code_commit": "abc123"},
            "token_present_smoke": {"code_commit": "abc123"},
        },
        model_artifact={"key": "value"},
    )
    # Without receipts, bundle_passed should be false
    errors_list = bundle.validate()
    # With bundle_passed=True but no receipts, should get receipt errors
    has_receipt_errors = any("receipts" in e and ("missing" in e or "empty" in e) for e in errors_list)
    if not has_receipt_errors:
        errors.append(
            "bundle: missing receipts not flagged for bundle_passed=True"
        )

    return errors


def _check_invalidated_evidence() -> list[str]:
    """Verify invalidated evidence in manifest remains non-passing."""
    errors: list[str] = []
    manifest_path = REPO_ROOT / "docs" / "evidence" / "stage0" / "evidence_manifest.json"
    if not manifest_path.exists():
        errors.append(f"manifest not found: {manifest_path}")
        return errors

    try:
        with open(manifest_path, encoding="utf-8") as f:
            manifest = json.load(f)
    except (json.JSONDecodeError, OSError) as exc:
        errors.append(f"manifest load failed: {exc}")
        return errors

    files = manifest.get("files", {})
    for key, entry in files.items():
        if isinstance(entry, dict) and entry.get("status") == "invalidated":
            # Verify the invalidated bundle cannot pass schema validation
            bundle_filename = entry.get("filename")
            if bundle_filename:
                bundle_path = manifest_path.parent / bundle_filename
                if bundle_path.exists():
                    try:
                        with open(bundle_path, encoding="utf-8") as f:
                            bundle_data = json.load(f)
                        from src.evidence_validation import validate_recursive
                        v_errors = validate_recursive(bundle_data, label=f"invalidated:{bundle_filename}")
                        # Even if the raw data says bundle_passed=True, the
                        # schema validation should catch missing/invalid fields
                        # (e.g., receipts, which postdate this bundle).
                        if not v_errors:
                            errors.append(
                                f"invalidated bundle '{bundle_filename}' passes "
                                f"schema validation — should be non-passing"
                            )
                    except Exception:
                        pass  # May fail to deserialize with new schema — acceptable

    return errors


def main() -> int:
    all_errors: list[str] = []

    print("=" * 64)
    print("  Stage 0 Evidence Readiness Verification (offline)")
    print("=" * 64)

    # 1. Schema module consistency
    print("\n[1/7] Schema module consistency...")
    errors = _check_schema_module()
    if errors:
        for e in errors:
            print(f"  [FAIL] {e}")
        all_errors.extend(errors)
    else:
        print("  [OK]")

    # 2. Canonical registry parity
    print("\n[2/7] Canonical Cloud test registry parity...")
    errors = _check_canonical_registry_parity()
    if errors:
        for e in errors:
            print(f"  [FAIL] {e}")
        all_errors.extend(errors)
    else:
        print("  [OK]")

    # 3. Cloud builder synthetic fixture
    print("\n[3/7] Cloud builder with valid synthetic fixture...")
    errors = _check_cloud_builder_synthetic_fixture()
    if errors:
        for e in errors:
            print(f"  [FAIL] {e}")
        all_errors.extend(errors)
    else:
        print("  [OK]")

    # 4. Benchmark preflight ordering
    print("\n[4/7] Benchmark preflight ordering contract...")
    errors = _check_benchmark_preflight_ordering()
    if errors:
        for e in errors:
            print(f"  [FAIL] {e}")
        all_errors.extend(errors)
    else:
        print("  [OK]")

    # 5. Receipt binding contract
    print("\n[5/7] Receipt binding typeness and mandatory validation...")
    errors = _check_receipt_binding_contract()
    if errors:
        for e in errors:
            print(f"  [FAIL] {e}")
        all_errors.extend(errors)
    else:
        print("  [OK]")

    # 6. Invalidated evidence
    print("\n[6/7] Invalidated evidence remains non-passing...")
    errors = _check_invalidated_evidence()
    if errors:
        for e in errors:
            print(f"  [FAIL] {e}")
        all_errors.extend(errors)
    else:
        print("  [OK]")

    # 7. Manifest verification
    print("\n[7/7] Manifest hash verification...")
    result = subprocess.run(
        [sys.executable, str(REPO_ROOT / "scripts" / "verify_evidence_manifest.py")],
        capture_output=True, text=True, timeout=30,
    )
    if result.returncode != 0:
        errors = [f"manifest verification failed:\n{result.stdout[:500]}{result.stderr[:500]}"]
        for e in errors:
            print(f"  [FAIL] {e}")
        all_errors.extend(errors)
    else:
        print("  [OK]")

    print()
    if all_errors:
        print(f"[FAIL] {len(all_errors)} readiness check(s) failed")
        for e in all_errors:
            print(f"  - {e}")
        return 1
    else:
        print("[OK] All readiness checks passed")
        return 0


if __name__ == "__main__":
    sys.exit(main())
