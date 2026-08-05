#! /usr/bin/env python3
"""Build a typed Cloud Stage 0 evidence record from measured inputs.

This script validates measured inputs, rejects incomplete records,
contains no secrets or raw data, and returns non-zero unless all
release requirements pass. It does NOT fake measurements.

Usage:
    python scripts/build_cloud_stage0_evidence.py --input <input.json> [--output <path>]

Input JSON structure (all fields required for a passing record):
{
    "python_version": "3.12",
    "code_commit": "<sha>",
    "deployed_url": "https://...streamlit.app",
    "deployed_commit": "<sha>",
    "deployment_time_utc": "...",
    "hf_token_present": true|false,
    "token_absent_result": { ... },
    "token_present_result": { ... },
    "package_versions": { "torch": "...", ... },
    "machine": { "cpu_model": "...", "cpu_logical_cores": 4, "ram_total_gb": 1.0, "os_name": "Linux" },
    "pip_check_passed": true|false,
    "torch_cuda_none": true|false,
    "nvidia_packages_absent": true|false,
    "dependency_resolver": "pip|uv",
    "cold": { "total_seconds": ..., "model_load_seconds": ..., "inference_seconds": ..., "rss_mb": ..., "pipeline_call_count": 1, "cache_state": "download_cold|process_cold_cached_weights" },
    "warm": { "total_seconds": ..., "model_load_seconds": 0.0, "inference_seconds": ..., "rss_mb": ..., "pipeline_call_count": 1, "pipeline_reused": true, "cache_state": "same_process_warm" },
    "cold_peak_rss_mb": ...,
    "process_peak_rss_mb": ...,
    "resource_limit_exceeded": false,
    "app_restart_occurred": false,
    "concurrent_users": 2,
    "sync_mode": "semaphore",
    "timeout_result": "no_timeout",
    "concurrency_requests": [ ... ],
    "repeated_runs": [ ... ],
    "acceptance_tests": [ { "test_name": "...", "passed": true, "details": "" }, ... ]
}
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
sys.path.insert(0, str(REPO_ROOT))

from src.evidence_schemas import (
    CloudEvidence,
    CANONICAL_CLOUD_TESTS,
    EVIDENCE_SCHEMA_VERSION,
    EVIDENCE_ORIGIN_REAL,
    EVIDENCE_ORIGIN_SYNTHETIC,
    TokenPathResult,
    SmokePhase,
    MachineSummary,
    RepeatedRun,
    ConcurrencyRequest,
    AcceptanceTestResult,
    ExecutionReceipt,
    canonical_evidence_sha256,
)
from src.evidence_validation import validate_recursive
from src.telemetry import capture_traceability


def _check_measured_inputs(data: dict[str, Any]) -> list[str]:
    """Validate that all required measured inputs are present and non-zero
    where appropriate. Returns a list of error messages."""
    errors: list[str] = []

    # Required string fields
    string_fields = [
        "python_version", "code_commit", "deployed_url", "deployed_commit",
        "deployment_time_utc", "dependency_resolver",
    ]
    for field in string_fields:
        val = data.get(field, "")
        if not val:
            errors.append(f"{field}: empty — measurement required")

    # Required boolean/flag fields
    bool_fields = [
        "pip_check_passed", "torch_cuda_none", "nvidia_packages_absent",
    ]
    for field in bool_fields:
        if not isinstance(data.get(field), bool):
            errors.append(f"{field}: must be a boolean")

    # Required numeric measurements
    numeric_fields = [
        ("cold_peak_rss_mb", "must be > 0"),
        ("process_peak_rss_mb", "must be > 0"),
    ]
    for field, hint in numeric_fields:
        val = data.get(field, 0)
        if not isinstance(val, (int, float)) or val <= 0:
            errors.append(f"{field}: {hint}")

    # Resource limit and restart must be explicitly false
    if data.get("resource_limit_exceeded", True):
        errors.append("resource_limit_exceeded: must be false for a passing record")
    if data.get("app_restart_occurred", True):
        errors.append("app_restart_occurred: must be false for a passing record")

    # Package versions must be present
    pkg = data.get("package_versions", {})
    if not pkg or not isinstance(pkg, dict):
        errors.append("package_versions: must be a non-empty dict")

    # Machine summary
    machine = data.get("machine", {})
    if not isinstance(machine, dict) or not machine.get("cpu_model"):
        errors.append("machine.cpu_model: empty")

    # Cold phase
    cold = data.get("cold", {})
    if not isinstance(cold, dict):
        errors.append("cold: must be an object")
    else:
        if cold.get("total_seconds", 0) <= 0:
            errors.append("cold.total_seconds: must be > 0")
        if cold.get("pipeline_call_count", 0) != 1:
            errors.append("cold.pipeline_call_count: must be 1")
        if cold.get("rss_mb", 0) <= 0:
            errors.append("cold.rss_mb: must be > 0")

    # Warm phase
    warm = data.get("warm", {})
    if not isinstance(warm, dict):
        errors.append("warm: must be an object")
    else:
        if warm.get("total_seconds", 0) <= 0:
            errors.append("warm.total_seconds: must be > 0")
        if warm.get("model_load_seconds", 0) > 0.5:
            errors.append("warm.model_load_seconds: must be near-zero (reused pipeline)")
        if not warm.get("pipeline_reused", False):
            errors.append("warm.pipeline_reused: must be true")

    # Token path results
    tar = data.get("token_absent_result", {})
    if not isinstance(tar, dict) or not tar.get("attempted"):
        errors.append("token_absent_result: must be attempted")
    if not tar.get("success"):
        errors.append("token_absent_result: must be successful")
    tpr = data.get("token_present_result", {})
    if not isinstance(tpr, dict) or not tpr.get("attempted"):
        errors.append("token_present_result: must be attempted")
    if not tpr.get("success"):
        errors.append("token_present_result: must be successful")

    # Concurrency
    concurrent_users = data.get("concurrent_users", 0)
    if concurrent_users < 2:
        errors.append(f"concurrent_users: must be >= 2, got {concurrent_users}")
    concurrency_requests = data.get("concurrency_requests", [])
    if not isinstance(concurrency_requests, list) or len(concurrency_requests) < concurrent_users:
        errors.append(f"concurrency_requests: need at least {concurrent_users} entries")

    # Repeated runs — at least 3 successful
    repeated_runs = data.get("repeated_runs", [])
    if not isinstance(repeated_runs, list):
        errors.append("repeated_runs: must be a list")
    else:
        successful = sum(1 for r in repeated_runs if isinstance(r, dict) and r.get("success"))
        if successful < 3:
            errors.append(f"repeated_runs: need at least 3 successful runs, got {successful}")

    # Acceptance tests — all canonical tests must be present and passing
    acceptance_tests = data.get("acceptance_tests", [])
    if not isinstance(acceptance_tests, list):
        errors.append("acceptance_tests: must be a list")
    else:
        seen = {t.get("test_name", "") for t in acceptance_tests if isinstance(t, dict)}
        missing = sorted(set(CANONICAL_CLOUD_TESTS) - seen)
        if missing:
            errors.append(f"acceptance_tests: missing required tests: {missing}")
        for t in acceptance_tests:
            if isinstance(t, dict) and t.get("test_name") in CANONICAL_CLOUD_TESTS:
                if not t.get("passed"):
                    errors.append(f"acceptance_test '{t['test_name']}': must pass")

    return errors


def _check_receipts(data: dict[str, Any], allow_synthetic: bool) -> list[str]:
    """Pre-check that execution receipts look structurally present.

    In production mode (default), all three receipts are required here and
    must contain valid execution data — the builder never fabricates them.

    WP-H: synthetic mode (--allow-synthetic-fixture) skips this early
    presence pre-check, but does NOT tolerate missing receipts overall —
    CloudEvidence.validate() (called later, from _build_cloud_evidence)
    requires all three receipts and collection_session regardless of
    evidence_origin, and additionally requires every receipt's own
    evidence_origin to match the record's. A synthetic-fixture caller must
    supply synthetic receipts (evidence_origin=synthetic_fixture) — use
    tests.fixtures.cloud_valid_fixture.json, or an equivalent fixture
    helper, as the template. This is what makes production mode reject a
    synthetic receipt even if a caller forgets to omit --allow-synthetic-
    fixture: the schema-level origin check fires regardless of this
    pre-check.
    """
    errors: list[str] = []
    if allow_synthetic:
        return errors  # Structural pre-check skipped; schema-level validate() is authoritative.

    # Production mode: all three receipts are mandatory
    receipt_fields = [
        ("token_absent_receipt", "token_absent_result"),
        ("token_present_receipt", "token_present_result"),
        ("collection_receipt", None),
    ]
    for rec_field, result_field in receipt_fields:
        rec = data.get(rec_field)
        if not isinstance(rec, dict) or not rec:
            errors.append(
                f"{rec_field}: missing or empty — execution receipt required "
                f"in production mode. Use --allow-synthetic-fixture for "
                f"testing."
            )
            continue

        # Validate receipt structure
        try:
            receipt_obj = ExecutionReceipt(**rec)
            rec_errors = receipt_obj.validate()
            for re in rec_errors:
                errors.append(f"{rec_field}: {re}")
        except Exception as exc:
            errors.append(f"{rec_field}: receipt construction failed: {exc}")
            continue

        # Verify canonical content digest binds the result data
        if result_field:
            result = data.get(result_field)
            if isinstance(result, dict):
                try:
                    canonical_digest = canonical_evidence_sha256(result)
                    if receipt_obj.canonical_content_sha256:
                        if receipt_obj.canonical_content_sha256 != canonical_digest:
                            errors.append(
                                f"{rec_field}: canonical_content_sha256 "
                                f"'{receipt_obj.canonical_content_sha256}' != "
                                f"computed '{canonical_digest}'"
                            )
                except Exception as exc:
                    errors.append(f"{rec_field}: canonical digest error: {exc}")

    return errors


def _build_cloud_evidence(data: dict[str, Any], allow_synthetic: bool = False) -> CloudEvidence:
    """Build a CloudEvidence from validated input data.

    Parameters
    ----------
    data : dict
        Validated input data with all required measurements.
    allow_synthetic : bool
        If True, marks evidence_origin as synthetic_fixture. If False
        (default), marks as real_measurement.

    Returns
    -------
    CloudEvidence
        The constructed Cloud evidence record.
    """
    # Construct typed objects from raw data
    cold = SmokePhase(**{
        k: data.get("cold", {}).get(k, v)
        for k, v in SmokePhase().__dataclass_fields__.items()
    })
    warm = SmokePhase(**{
        k: data.get("warm", {}).get(k, v)
        for k, v in SmokePhase().__dataclass_fields__.items()
    })
    machine = MachineSummary(**{
        k: data.get("machine", {}).get(k, v)
        for k, v in MachineSummary().__dataclass_fields__.items()
    })
    tar = TokenPathResult(**data.get("token_absent_result", {}))
    tpr = TokenPathResult(**data.get("token_present_result", {}))

    trace = capture_traceability()
    started_utc = datetime.now(timezone.utc).isoformat()

    # Determine evidence origin (constants imported at module scope)
    evidence_origin = EVIDENCE_ORIGIN_SYNTHETIC if allow_synthetic else EVIDENCE_ORIGIN_REAL

    evidence = CloudEvidence(
        evidence_origin=evidence_origin,
        python_version=data.get("python_version", ""),
        code_commit=data.get("code_commit", trace.get("code_commit", "")),  # Prefer input data commit
        git_worktree_clean=trace.get("git_worktree_clean", False),
        started_at_utc=started_utc,
        completed_at_utc=started_utc,
        model_id="amazon/chronos-2",
        configured_revision=data.get("configured_revision", "29ec3766d36d6f73f0696f85560a422f50e8498c"),
        model_revision=data.get("model_revision", ""),
        hf_token_present=data.get("hf_token_present", False),
        token_absent_result=tar,
        token_present_result=tpr,
        package_versions=data.get("package_versions", {}),
        machine=machine,
        pip_check_passed=data.get("pip_check_passed", False),
        torch_cuda_none=data.get("torch_cuda_none", False),
        nvidia_packages_absent=data.get("nvidia_packages_absent", False),
        dependency_resolver=data.get("dependency_resolver", ""),
        deployed_url=data.get("deployed_url", ""),
        deployed_commit=data.get("deployed_commit", ""),
        deployment_time_utc=data.get("deployment_time_utc", ""),
        cold=cold,
        warm=warm,
        cold_peak_rss_mb=data.get("cold_peak_rss_mb", 0.0),
        process_peak_rss_mb=data.get("process_peak_rss_mb", 0.0),
        resource_limit_exceeded=data.get("resource_limit_exceeded", False),
        app_restart_occurred=data.get("app_restart_occurred", False),
        concurrent_users=data.get("concurrent_users", 0),
        sync_mode=data.get("sync_mode", ""),
        timeout_result=data.get("timeout_result", ""),
        concurrency_requests=[
            ConcurrencyRequest(**r) for r in data.get("concurrency_requests", [])
            if isinstance(r, dict)
        ],
        repeated_runs=[
            RepeatedRun(**r) for r in data.get("repeated_runs", [])
            if isinstance(r, dict)
        ],
        acceptance_tests=[
            AcceptanceTestResult(**t) for t in data.get("acceptance_tests", [])
            if isinstance(t, dict)
        ],
        token_absent_receipt=data.get("token_absent_receipt", {}),
        token_present_receipt=data.get("token_present_receipt", {}),
        collection_receipt=data.get("collection_receipt", {}),
        collection_session=data.get("collection_session", {}),
        error=data.get("error", ""),
    )

    # WP5: Production mode NEVER auto-generates receipts.
    # Receipts must come from actual execution measurements.
    # The _check_receipts() function validates them in production mode.

    # P0-1: Build with success=True to avoid circular rejection.
    # CloudEvidence.validate() rejects success=False, so we must start
    # with success=True, then apply the real result after validation.
    evidence.success = True
    v_errors = evidence.validate()
    evidence.success = len(v_errors) == 0
    if not evidence.success:
        evidence.error = "; ".join(v_errors)
    evidence.completed_at_utc = datetime.now(timezone.utc).isoformat()

    return evidence


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Build a typed Cloud Stage 0 evidence record",
    )
    parser.add_argument("--input", required=True, help="Input JSON file with measured values")
    parser.add_argument("--output", default="", help="Output path (default: stdout)")
    parser.add_argument(
        "--allow-synthetic-fixture",
        action="store_true",
        help=(
            "Allow synthetic CI fixture data. The output record will be "
            "marked with evidence_origin=synthetic_fixture and cannot be "
            "published as release evidence. Execution receipts (and "
            "collection_session) are still required, and must themselves "
            "be marked evidence_origin=synthetic_fixture — see "
            "tests/fixtures/cloud_valid_fixture.json for the template."
        ),
    )
    args = parser.parse_args()

    try:
        with open(args.input, encoding="utf-8") as f:
            input_data = json.load(f)
    except (json.JSONDecodeError, OSError) as exc:
        print(f"Error loading input: {exc}")
        return 1

    if not isinstance(input_data, dict):
        print("ERROR: input must be a JSON object")
        return 1

    # Validate measured inputs
    input_errors = _check_measured_inputs(input_data)
    if input_errors:
        print("Input validation errors:")
        for err in input_errors:
            print(f"  [FAIL] {err}")
        return 1

    # Validate receipts (production mode rejects missing receipts)
    receipt_errors = _check_receipts(input_data, allow_synthetic=args.allow_synthetic_fixture)
    if receipt_errors:
        print("Receipt validation errors:")
        for err in receipt_errors:
            print(f"  [FAIL] {err}")
        return 1

    # Build evidence
    try:
        evidence = _build_cloud_evidence(
            input_data, allow_synthetic=args.allow_synthetic_fixture,
        )
    except Exception as exc:
        print(f"Error building evidence: {exc}")
        return 1

    evidence_dict = evidence.to_dict()

    # WP-G/WP-H: report the SPECIFIC receipt/origin/digest errors that
    # actually caused success=False first — once success is False,
    # CloudEvidence.validate() short-circuits its receipt-binding checks
    # (they only run "if self.success"), so re-validating the collapsed
    # dict below would otherwise only ever show a generic "success: false"
    # message and hide the real reason (e.g. a synthetic receipt in
    # production mode, or a digest that doesn't bind its result).
    if not evidence.success:
        print("Cloud evidence validation failed — record is not passing")
        for err in evidence.error.split("; ") if evidence.error else []:
            print(f"  [FAIL] {err}")
        return 1

    # Recursively validate (imported at module scope)
    v_errors = validate_recursive(evidence_dict, label="cloud_stage0")
    if v_errors:
        print("Schema validation errors:")
        for err in v_errors:
            print(f"  [FAIL] {err}")
        return 1

    # Write output
    output = args.output
    if output:
        with open(output, "w", encoding="utf-8") as f:
            json.dump(evidence_dict, f, indent=2, default=str)
        print(f"[OK] Cloud evidence written to: {output}")
    else:
        json.dump(evidence_dict, sys.stdout, indent=2, default=str)
        print()

    print("[OK] Cloud evidence validation passed")
    print(f"  Commit: {evidence.code_commit}")
    print(f"  Model revision: {evidence.model_revision}")
    print(f"  Tests: {len([t for t in evidence.acceptance_tests if t.passed])}/{len(CANONICAL_CLOUD_TESTS)} passed")

    return 0


if __name__ == "__main__":
    sys.exit(main())
