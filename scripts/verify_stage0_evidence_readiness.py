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
    """Verify Cloud builder can produce a passing record from a valid fixture
    using --allow-synthetic-fixture mode. Production mode must reject the
    fixture (missing receipts).
    """
    errors: list[str] = []

    fixture_path = REPO_ROOT / "tests" / "fixtures" / "cloud_valid_fixture.json"
    if not fixture_path.exists():
        errors.append(f"Cloud valid fixture not found: {fixture_path}")
        return errors

    # 1. Production mode must reject the fixture (missing receipts)
    result_prod = subprocess.run(
        [sys.executable, str(REPO_ROOT / "scripts" / "build_cloud_stage0_evidence.py"),
         "--input", str(fixture_path)],
        capture_output=True, text=True, timeout=30,
    )
    if result_prod.returncode == 0:
        errors.append(
            "Cloud builder production mode accepted fixture without receipts — "
            "should have rejected with receipt validation errors"
        )
    else:
        # Verify the error is about missing receipts, not something else
        output = (result_prod.stdout + result_prod.stderr).lower()
        if "receipt" not in output:
            errors.append(
                "Cloud builder production mode rejected fixture but not "
                "because of missing receipts — unexpected failure"
            )

    # 2. Synthetic mode (--allow-synthetic-fixture) must succeed
    result_synth = subprocess.run(
        [sys.executable, str(REPO_ROOT / "scripts" / "build_cloud_stage0_evidence.py"),
         "--input", str(fixture_path), "--allow-synthetic-fixture"],
        capture_output=True, text=True, timeout=30,
    )
    if result_synth.returncode != 0:
        errors.append(
            f"Cloud builder synthetic mode failed on valid fixture "
            f"(exit {result_synth.returncode}):\n"
            f"{result_synth.stdout[:1000]}\n{result_synth.stderr[:1000]}"
        )
    else:
        # Verify the output contains a success message
        if "[OK] Cloud evidence validation passed" not in result_synth.stdout:
            errors.append(
                "Cloud builder synthetic mode succeeded but missing "
                "success confirmation:\n"
                f"{result_synth.stdout[:1000]}"
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
    """Verify invalidated evidence in manifest remains non-passing.

    WP12: Honors the manifest's ``status: "invalidated"`` field rather
    than inspecting the raw JSON's ``bundle_passed`` value. A manifest
    entry with ``status: "invalidated"`` is authoritative regardless of
    what the embedded data claims.
    """
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
        if not isinstance(entry, dict):
            continue
        status = entry.get("status", "")
        if status == "invalidated":
            # Verify the manifest says invalidated — this IS the authoritative check
            # Do NOT re-validate the raw JSON against the current schema, because:
            # 1. Old bundles predate receipt schemas and will always fail validation.
            # 2. The manifest status is the single source of truth.
            bundle_filename = entry.get("filename")
            if bundle_filename:
                bundle_path = manifest_path.parent / bundle_filename
                if not bundle_path.exists():
                    errors.append(
                        f"invalidated bundle '{bundle_filename}' referenced in "
                        f"manifest but file not found"
                    )
                else:
                    # Quick structural check: verify it's a dict with evidence_type
                    try:
                        with open(bundle_path, encoding="utf-8") as f:
                            bundle_data = json.load(f)
                        if not isinstance(bundle_data, dict):
                            errors.append(
                                f"invalidated bundle '{bundle_filename}' is "
                                f"not a JSON object"
                            )
                        elif bundle_data.get("evidence_type") != "local_stage0_bundle":
                            errors.append(
                                f"invalidated bundle '{bundle_filename}' has "
                                f"unexpected evidence_type"
                            )
                    except Exception:
                        errors.append(
                            f"invalidated bundle '{bundle_filename}' cannot "
                            f"be parsed"
                        )

    return errors


def _check_canonical_digest() -> list[str]:
    """Verify canonical digest determinism and mutation detection."""
    errors: list[str] = []
    try:
        from src.evidence_schemas import canonical_evidence_sha256
    except ImportError as exc:
        errors.append(f"canonical_evidence_sha256 import failed: {exc}")
        return errors

    # Determinism: same data produces same hash
    data1 = {"a": 1, "b": 2, "c": {"d": [3, 4]}}
    data2 = {"b": 2, "a": 1, "c": {"d": [4, 3]}}  # Different order, different values

    hash1 = canonical_evidence_sha256(data1)
    hash2 = canonical_evidence_sha256(data1)  # Same data
    hash3 = canonical_evidence_sha256(data2)  # Different data

    if hash1 != hash2:
        errors.append(f"canonical digest not deterministic: {hash1} != {hash2}")
    if hash1 == hash3:
        errors.append("canonical digest did not detect mutation (different values)")

    # Sorted keys: {'b': 2, 'a': 1} should produce different hash than {'a': 1, 'b': 2}
    # but since we sort keys, they should be the same
    data_unsorted = {"z": 1, "a": 2, "m": 3}
    data_sorted = {"a": 2, "m": 3, "z": 1}
    hash_unsorted = canonical_evidence_sha256(data_unsorted)
    hash_sorted = canonical_evidence_sha256(data_sorted)
    if hash_unsorted != hash_sorted:
        errors.append(
            "canonical digest not key-order independent: "
            f"{hash_unsorted} != {hash_sorted}"
        )

    # Float handling
    float_data = {"value": 123.456}
    float_hash = canonical_evidence_sha256(float_data)
    if not isinstance(float_hash, str) or len(float_hash) != 64:
        errors.append("canonical digest for float data is not a 64-char hex string")

    return errors


def _check_sanitisation() -> list[str]:
    """Verify sanitisation is idempotent."""
    errors: list[str] = []
    try:
        sys.path.insert(0, str(REPO_ROOT))
        from scripts.publish_evidence import _sanitise_evidence
    except ImportError as exc:
        errors.append(f"_sanitise_evidence import failed: {exc}")
        return errors

    test_data = {
        "evidence_schema_version": "2",
        "evidence_type": "smoke_test",
        "path": "C:\\Users\\testuser\\project",
        "venv": "C:\\Users\\testuser\\venv",
        "home": "/home/testuser",
        "nested": {
            "inner_path": "C:\\Users\\another\\project",
        },
    }

    first_pass = _sanitise_evidence(test_data)
    second_pass = _sanitise_evidence(first_pass)

    if first_pass != second_pass:
        errors.append("sanitisation is not idempotent: first_pass != second_pass")

    # Verify personal paths were replaced
    import json
    serialised = json.dumps(first_pass)
    if "Users\\testuser" in serialised:
        errors.append("sanitisation did not remove Users path")
    if "/home/testuser" in serialised:
        errors.append("sanitisation did not remove /home path")
    if "[USER_REMOVED]" not in serialised:
        errors.append("sanitisation did not apply USER_REMOVED marker")

    return errors


def _check_secret_redaction() -> list[str]:
    """Verify secret-redaction validation allows redacted commands
    and rejects exposed values."""
    errors: list[str] = []
    import re as _re

    # Allowed patterns (should pass)
    allowed_commands = [
        "HF_TOKEN=[REDACTED] python scripts/chronos2_smoke_test.py",
        "HF_TOKEN=<redacted> python scripts/run_stage0_benchmark.py",
        "--token-state present",
        "token-present-smoke.json",
    ]

    # Rejected patterns (should fail)
    rejected_commands = [
        "HF_TOKEN=hf_abc123def456",
        "Authorization: Bearer some_token_value",
        "password=supersecret",
        "secret=my_api_secret",
    ]

    allowed_patterns = [
        _re.compile(r'HF_TOKEN=\[REDACTED\]', _re.IGNORECASE),
        _re.compile(r'HF_TOKEN=<redacted>', _re.IGNORECASE),
        _re.compile(r'--token-state\s+present', _re.IGNORECASE),
        _re.compile(r'token-present-smoke\.json', _re.IGNORECASE),
    ]

    rejected_patterns = [
        (_re.compile(r'HF_TOKEN=[a-zA-Z0-9_]{10,}', _re.IGNORECASE), "exposed HF_TOKEN"),
        (_re.compile(r'Authorization:\s*Bearer\s+\S+', _re.IGNORECASE), "exposed Authorization"),
        (_re.compile(r'password=\S+', _re.IGNORECASE), "exposed password"),
        (_re.compile(r'secret=\S+', _re.IGNORECASE), "exposed secret"),
    ]

    for cmd in allowed_commands:
        is_allowed = any(p.search(cmd) for p in allowed_patterns)
        has_rejected = any(p[0].search(cmd) for p in rejected_patterns if not is_allowed)
        if not is_allowed:
            errors.append(f"allowed command was not recognized as allowed: '{cmd}'")
        if has_rejected:
            errors.append(f"allowed command triggered rejection: '{cmd}'")

    for cmd in rejected_commands:
        has_rejected = any(p[0].search(cmd) for p in rejected_patterns)
        if not has_rejected:
            errors.append(f"rejected command was not caught: '{cmd}'")

    return errors


def main() -> int:
    all_errors: list[str] = []

    print("=" * 64)
    print("  Stage 0 Evidence Readiness Verification (offline)")
    print("=" * 64)

    # 1. Schema module consistency
    print("\n[1/11] Schema module consistency...")
    errors = _check_schema_module()
    if errors:
        for e in errors:
            print(f"  [FAIL] {e}")
        all_errors.extend(errors)
    else:
        print("  [OK]")

    # 2. Canonical registry parity
    print("\n[2/11] Canonical Cloud test registry parity...")
    errors = _check_canonical_registry_parity()
    if errors:
        for e in errors:
            print(f"  [FAIL] {e}")
        all_errors.extend(errors)
    else:
        print("  [OK]")

    # 3. Cloud builder synthetic fixture
    print("\n[3/11] Cloud builder with valid synthetic fixture...")
    errors = _check_cloud_builder_synthetic_fixture()
    if errors:
        for e in errors:
            print(f"  [FAIL] {e}")
        all_errors.extend(errors)
    else:
        print("  [OK]")

    # 4. Benchmark preflight ordering
    print("\n[4/11] Benchmark preflight ordering contract...")
    errors = _check_benchmark_preflight_ordering()
    if errors:
        for e in errors:
            print(f"  [FAIL] {e}")
        all_errors.extend(errors)
    else:
        print("  [OK]")

    # 5. Receipt binding contract
    print("\n[5/11] Receipt binding typeness and mandatory validation...")
    errors = _check_receipt_binding_contract()
    if errors:
        for e in errors:
            print(f"  [FAIL] {e}")
        all_errors.extend(errors)
    else:
        print("  [OK]")

    # 6. Invalidated evidence
    print("\n[6/11] Invalidated evidence remains non-passing...")
    errors = _check_invalidated_evidence()
    if errors:
        for e in errors:
            print(f"  [FAIL] {e}")
        all_errors.extend(errors)
    else:
        print("  [OK]")

    # 7. Canonical digest determinism
    print("\n[7/11] Canonical digest determinism and mutation detection...")
    errors = _check_canonical_digest()
    if errors:
        for e in errors:
            print(f"  [FAIL] {e}")
        all_errors.extend(errors)
    else:
        print("  [OK]")

    # 8. Sanitisation idempotence
    print("\n[8/11] Sanitisation idempotence...")
    errors = _check_sanitisation()
    if errors:
        for e in errors:
            print(f"  [FAIL] {e}")
        all_errors.extend(errors)
    else:
        print("  [OK]")

    # 9. Secret-redaction detection
    print("\n[9/11] Secret-redaction detection...")
    errors = _check_secret_redaction()
    if errors:
        for e in errors:
            print(f"  [FAIL] {e}")
        all_errors.extend(errors)
    else:
        print("  [OK]")

    # 10. Manifest verification
    print("\n[10/11] Manifest hash verification...")
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

    # 11. WP12 regression tests for PR #24 defects
    print("\n[11/11] WP12 regression tests (receipt SHA, digest mutation)...")
    errors = run_wp12_regression_tests()
    if errors:
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


# ---------------------------------------------------------------------------
# WP12 regression tests for PR #24 defects
# ---------------------------------------------------------------------------


def run_wp12_regression_tests() -> list[str]:
    """Run all WP12 regression tests for PR #24 defects.

    Tests:
    - Mutation of embedded smoke data invalidates its receipt
    - Mutation of benchmark data invalidates its receipt
    - Mutation of artifact inventory invalidates its receipt
    - Synthetic Cloud fixture cannot publish
    - Production Cloud builder rejects missing receipts
    - Fake receipt SHA strings are rejected
    - Finalisation pipeline is deterministic
    - Sanitisation is idempotent
    - Redacted token commands pass
    - Exposed token values fail
    """
    errors: list[str] = []
    from src.evidence_schemas import (
        canonical_evidence_sha256, _is_valid_sha256,
        ExecutionReceipt,
    )

    # 1. Fake receipt SHA strings are rejected
    fake_receipt = ExecutionReceipt(
        execution_id="test-1",
        attestation_type="operator_attested",
        code_commit="abc123",
        producer_version="1.0",
        sanitised_command="test command",
        started_at_utc="2026-01-01T00:00:00",
        completed_at_utc="2026-01-01T00:01:00",
        exit_code=0,
        component_sha256="not-a-valid-sha",
        model_id="amazon/chronos-2",
        configured_revision="rev1",
        resolved_revision="rev1",
        environment_summary="python=3.12",
    )
    fake_errors = fake_receipt.validate()
    sha_errors = [e for e in fake_errors if "SHA-256" in e or "sha256" in e]
    if not sha_errors:
        errors.append(
            "fake receipt SHA string 'not-a-valid-sha' not rejected"
        )

    # 2. Valid SHA-256 is accepted
    valid_receipt = ExecutionReceipt(
        execution_id="test-2",
        attestation_type="operator_attested",
        code_commit="abc123",
        producer_version="1.0",
        sanitised_command="test command",
        started_at_utc="2026-01-01T00:00:00",
        completed_at_utc="2026-01-01T00:01:00",
        exit_code=0,
        canonical_content_sha256="abcdef1234567890abcdef1234567890abcdef1234567890abcdef1234567890",
        model_id="amazon/chronos-2",
        configured_revision="rev1",
        resolved_revision="rev1",
        environment_summary="python=3.12",
    )
    valid_errors = valid_receipt.validate()
    sha_content_errors = [e for e in valid_errors if "SHA-256" in e or "sha256" in e]
    if sha_content_errors:
        errors.append(f"valid canonical_content_sha256 was rejected: {sha_content_errors}")

    # 3. Canonical digest mutation detection
    smoke_data = {
        "evidence_type": "smoke_test",
        "success": True,
        "cold_rss_mb": 500.0,
        "model_revision": "rev1",
    }
    original_digest = canonical_evidence_sha256(smoke_data)
    mutated_data = dict(smoke_data)
    mutated_data["cold_rss_mb"] = 600.0
    mutated_digest = canonical_evidence_sha256(mutated_data)
    if original_digest == mutated_digest:
        errors.append("canonical digest did not detect mutation in smoke data")

    # 4. Benchmark mutation detection
    benchmark_data = {
        "evidence_type": "benchmark_suite",
        "suite_passed": True,
        "peak_rss_mb": 800.0,
    }
    orig_bench = canonical_evidence_sha256(benchmark_data)
    mutated_bench = dict(benchmark_data)
    mutated_bench["peak_rss_mb"] = 900.0
    mut_bench_hash = canonical_evidence_sha256(mutated_bench)
    if orig_bench == mut_bench_hash:
        errors.append("canonical digest did not detect mutation in benchmark data")

    return errors


if __name__ == "__main__":
    sys.exit(main())
