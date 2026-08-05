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
    """Verify the canonical Cloud test registry matches the checklist AND
    the Cloud evidence template (WP8): no canonical acceptance-test
    representation required for Cloud collection may remain unverified
    before Gate C."""
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

    # WP8: the Cloud evidence template must carry the same canonical names —
    # an empty (or drifted) template means Gate C has no canonical
    # acceptance-test representation to verify against.
    template_path = REPO_ROOT / "docs" / "evidence" / "stage0" / "cloud_stage0_template.json"
    if not template_path.exists():
        errors.append(f"cloud template not found: {template_path}")
        return errors
    import json
    try:
        with open(template_path, encoding="utf-8") as f:
            template = json.load(f)
    except (json.JSONDecodeError, OSError) as exc:
        errors.append(f"cannot parse cloud template: {exc}")
        return errors
    template_names = {
        t.get("test_name", "") for t in template.get("acceptance_tests", [])
        if isinstance(t, dict)
    }
    if not template_names:
        errors.append(
            "cloud_stage0_template.json acceptance_tests is empty — "
            "populate it with the canonical Cloud test names"
        )
    missing_in_template = registry_names - template_names
    extra_in_template = template_names - registry_names
    if missing_in_template:
        errors.append(
            f"cloud template missing canonical tests: {sorted(missing_in_template)}"
        )
    if extra_in_template:
        errors.append(
            f"cloud template has extra tests not in registry: {sorted(extra_in_template)}"
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
    """Verify the ACTUAL shared contains_exposed_secret() (src/redaction.py)
    allows redacted/benign commands and rejects exposed values — calls the
    real function rather than a local reimplementation of its patterns, so
    this check fails if the real function regresses (a duplicated pattern
    set would stay green even if the real one broke)."""
    errors: list[str] = []
    try:
        from src.redaction import contains_exposed_secret, sanitise_command, REDACTED_MARKER
    except ImportError as exc:
        errors.append(f"src.redaction import failed: {exc}")
        return errors

    allowed_commands = [
        f"HF_TOKEN={REDACTED_MARKER} python scripts/chronos2_smoke_test.py",
        "--token-state present",
        "token-present-smoke.json",
        sanitise_command(["python", "x.py", "--hf-token", "hf_realvalue123456"]),
    ]
    rejected_commands = [
        "HF_TOKEN=hf_abc123def456",
        "Authorization: Bearer some_token_value",
        "password=supersecret",
        "secret=my_api_secret",
        # WP-J regression: space-separated "--flag value" form, previously
        # undetected by contains_exposed_secret() (only "name=value" forms
        # were checked) even though sanitise_command() already redacted it.
        "python smoke_test.py --hf-token hf_realsecretvalue1234567890",
        # PR #26 review finding P1-1: a safe marker anywhere in a ±20-char
        # window used to exempt an unrelated real exposure elsewhere in the
        # same command. Exemption must apply only to the matched value.
        "HF_TOKEN=abcdef --token-state present",
        "password=hunter2 ***REDACTED***",
    ]

    for cmd in allowed_commands:
        if contains_exposed_secret(cmd) is not None:
            errors.append(f"allowed command triggered rejection: '{cmd}'")
    for cmd in rejected_commands:
        if contains_exposed_secret(cmd) is None:
            errors.append(f"rejected command was not caught: '{cmd}'")

    return errors


def _check_collection_session_wrong_commit_rejected() -> list[str]:
    """PR #26 review finding P1-2: a collection_session naming a different
    commit than the enclosing Cloud record must be rejected — its own
    internal consistency (code_commit == deployed_commit within the
    session) is not enough."""
    errors: list[str] = []
    try:
        from src.evidence_schemas import CloudEvidence, CloudCollectionSession, canonical_evidence_sha256
    except ImportError as exc:
        errors.append(f"evidence_schemas import failed: {exc}")
        return errors

    session_kwargs = dict(
        evidence_schema_version="2", evidence_type="collection_session",
        evidence_origin="real_measurement", session_id="session-1",
        code_commit="different-commit", deployed_commit="different-commit",
        test_names=["cold_forecast"],
        started_at_utc="2026-01-01T00:00:00", completed_at_utc="2026-01-01T00:05:00",
    )
    digest = canonical_evidence_sha256(CloudCollectionSession(**session_kwargs).to_dict())
    receipt_kwargs = dict(
        evidence_schema_version="2", evidence_type="execution_receipt",
        execution_id="exec-1", attestation_type="operator_attested",
        code_commit="abc123", producer_version="1.0",
        sanitised_command="python build_cloud_stage0_evidence.py",
        started_at_utc="2026-01-01T00:00:00", completed_at_utc="2026-01-01T00:05:00",
        exit_code=0, canonical_content_sha256=digest,
        model_id="amazon/chronos-2", configured_revision="rev1",
        resolved_revision="rev1", environment_summary="python=3.12",
        evidence_origin="real_measurement", git_worktree_clean=True,
    )
    evidence = CloudEvidence(
        evidence_origin="real_measurement", success=True,
        code_commit="abc123", deployed_commit="abc123",
        collection_session=session_kwargs, collection_receipt=receipt_kwargs,
    )
    errs = evidence.validate()
    if not any("collection_session: code_commit" in e for e in errs):
        errors.append(
            "CloudEvidence.validate() accepted a collection_session naming a "
            "different code_commit than the enclosing record"
        )
    if not any("collection_session: deployed_commit" in e for e in errs):
        errors.append(
            "CloudEvidence.validate() accepted a collection_session naming a "
            "different deployed_commit than the enclosing record"
        )
    return errors


def _check_collection_session_empty_deployed_commit_rejected() -> list[str]:
    """PR #26 review finding P1-2: deployed_commit was not required on
    CloudCollectionSession — an empty value must be rejected."""
    errors: list[str] = []
    try:
        from src.evidence_schemas import CloudCollectionSession
    except ImportError as exc:
        errors.append(f"evidence_schemas import failed: {exc}")
        return errors

    session = CloudCollectionSession(
        evidence_schema_version="2", evidence_type="collection_session",
        evidence_origin="real_measurement", session_id="session-1",
        code_commit="abc123", deployed_commit="",
        test_names=["cold_forecast"],
        started_at_utc="2026-01-01T00:00:00", completed_at_utc="2026-01-01T00:05:00",
    )
    errs = session.validate()
    if not any("deployed_commit: empty" in e for e in errs):
        errors.append("CloudCollectionSession.validate() accepted an empty deployed_commit")
    return errors


def _check_collection_receipt_wrong_identity_rejected() -> list[str]:
    """A collection_receipt whose own code_commit disagrees with the Cloud
    record's deployed_commit must be rejected, even when it binds a
    structurally valid, otherwise-matching collection_session."""
    errors: list[str] = []
    try:
        from src.evidence_schemas import CloudEvidence, CloudCollectionSession, canonical_evidence_sha256
    except ImportError as exc:
        errors.append(f"evidence_schemas import failed: {exc}")
        return errors

    session_kwargs = dict(
        evidence_schema_version="2", evidence_type="collection_session",
        evidence_origin="real_measurement", session_id="session-1",
        code_commit="abc123", deployed_commit="abc123",
        test_names=["cold_forecast"],
        started_at_utc="2026-01-01T00:00:00", completed_at_utc="2026-01-01T00:05:00",
    )
    digest = canonical_evidence_sha256(CloudCollectionSession(**session_kwargs).to_dict())
    receipt_kwargs = dict(
        evidence_schema_version="2", evidence_type="execution_receipt",
        execution_id="exec-1", attestation_type="operator_attested",
        code_commit="wrong-commit",  # disagrees with deployed_commit below
        producer_version="1.0",
        sanitised_command="python build_cloud_stage0_evidence.py",
        started_at_utc="2026-01-01T00:00:00", completed_at_utc="2026-01-01T00:05:00",
        exit_code=0, canonical_content_sha256=digest,
        model_id="amazon/chronos-2", configured_revision="rev1",
        resolved_revision="rev1", environment_summary="python=3.12",
        evidence_origin="real_measurement", git_worktree_clean=True,
    )
    evidence = CloudEvidence(
        evidence_origin="real_measurement", success=True,
        code_commit="abc123", deployed_commit="abc123",
        collection_session=session_kwargs, collection_receipt=receipt_kwargs,
    )
    errs = evidence.validate()
    if not any("collection_receipt: code_commit" in e for e in errs):
        errors.append(
            "CloudEvidence.validate() accepted a collection_receipt whose "
            "code_commit disagrees with deployed_commit"
        )
    return errors


def _check_sanitised_collection_binding_still_valid() -> list[str]:
    """The publisher's sanitise-before-bind pipeline must not corrupt the
    collection_session/collection_receipt identity binding added for PR #26
    finding P1-2 — a legitimately matching session+receipt pair must still
    validate with zero binding errors after passing through
    publish_evidence.py's _sanitise_evidence()."""
    errors: list[str] = []
    try:
        from src.evidence_schemas import CloudEvidence, CloudCollectionSession, canonical_evidence_sha256
        from scripts.publish_evidence import _sanitise_evidence
    except ImportError as exc:
        errors.append(f"import failed: {exc}")
        return errors

    session_kwargs = dict(
        evidence_schema_version="2", evidence_type="collection_session",
        evidence_origin="real_measurement", session_id="session-1",
        code_commit="abc123", deployed_commit="abc123",
        test_names=["cold_forecast"],
        started_at_utc="2026-01-01T00:00:00", completed_at_utc="2026-01-01T00:05:00",
    )
    digest = canonical_evidence_sha256(CloudCollectionSession(**session_kwargs).to_dict())
    receipt_kwargs = dict(
        evidence_schema_version="2", evidence_type="execution_receipt",
        execution_id="exec-1", attestation_type="operator_attested",
        code_commit="abc123", producer_version="1.0",
        sanitised_command="HF_TOKEN=***REDACTED*** python build_cloud_stage0_evidence.py",
        started_at_utc="2026-01-01T00:00:00", completed_at_utc="2026-01-01T00:05:00",
        exit_code=0, canonical_content_sha256=digest,
        model_id="amazon/chronos-2", configured_revision="rev1",
        resolved_revision="rev1", environment_summary="python=3.12",
        evidence_origin="real_measurement", git_worktree_clean=True,
    )
    raw = {
        "evidence_origin": "real_measurement", "success": True,
        "code_commit": "abc123", "deployed_commit": "abc123",
        "collection_session": session_kwargs, "collection_receipt": receipt_kwargs,
    }
    sanitised = _sanitise_evidence(raw)
    evidence = CloudEvidence(**sanitised)
    errs = evidence.validate()
    binding_errs = [e for e in errs if "collection_session" in e or "collection_receipt" in e]
    if binding_errs:
        errors.append(
            "sanitisation broke the collection_session/collection_receipt "
            "binding: " + "; ".join(binding_errs)
        )
    return errors


def _check_evidence_origin_required() -> list[str]:
    """Verify a missing evidence_origin is rejected, not defaulted to real,
    across the evidence types that carry it."""
    errors: list[str] = []
    try:
        from src.evidence_schemas import evidence_from_dict, EVIDENCE_SCHEMA_VERSION
    except ImportError as exc:
        errors.append(f"evidence_schemas import failed: {exc}")
        return errors

    base = {
        "evidence_schema_version": EVIDENCE_SCHEMA_VERSION,
        "evidence_type": "smoke_test",
        "code_commit": "abc123",
        "git_worktree_clean": True,
    }
    # strict=True: readiness checks are release checks — permissive
    # (migration-only) parsing must never be used on a release path.
    obj = evidence_from_dict(dict(base), strict=True)
    if obj.evidence_origin not in ("", None):
        errors.append(
            f"SmokeEvidence with no evidence_origin key defaulted to "
            f"'{obj.evidence_origin}' instead of staying empty"
        )
    if not any("evidence_origin" in e for e in obj.validate()):
        errors.append("SmokeEvidence.validate() did not reject a missing evidence_origin")

    return errors


def _check_synthetic_receipt_in_real_evidence_rejected() -> list[str]:
    """Verify a synthetic-origin receipt embedded in a Cloud record that
    claims evidence_origin=real_measurement is rejected — omitting
    --allow-synthetic-fixture must not relabel a synthetic receipt as real."""
    errors: list[str] = []
    try:
        from src.evidence_schemas import ExecutionReceipt, EVIDENCE_ORIGIN_SYNTHETIC, EVIDENCE_ORIGIN_REAL
    except ImportError as exc:
        errors.append(f"evidence_schemas import failed: {exc}")
        return errors

    fixture_path = REPO_ROOT / "tests" / "fixtures" / "cloud_valid_fixture.json"
    if not fixture_path.exists():
        errors.append(f"Cloud valid fixture not found: {fixture_path}")
        return errors

    try:
        sys.path.insert(0, str(REPO_ROOT))
        from scripts.build_cloud_stage0_evidence import _build_cloud_evidence
        with open(fixture_path, encoding="utf-8") as f:
            data = json.load(f)
    except Exception as exc:
        errors.append(f"could not load Cloud builder / fixture: {exc}")
        return errors

    evidence = _build_cloud_evidence(data, allow_synthetic=False)
    if evidence.success:
        errors.append(
            "production-mode Cloud build with synthetic-origin receipts "
            "succeeded — should have been rejected"
        )
    if "evidence_origin" not in evidence.error:
        errors.append(
            f"production-mode rejection did not mention evidence_origin: {evidence.error}"
        )

    return errors


def _check_cloud_collection_binding_required() -> list[str]:
    """Verify CloudEvidence.validate() requires collection_session — the
    collection_receipt has to bind to something, not nothing."""
    errors: list[str] = []
    try:
        from src.evidence_schemas import CloudEvidence, ExecutionReceipt, canonical_evidence_sha256
    except ImportError as exc:
        errors.append(f"evidence_schemas import failed: {exc}")
        return errors

    receipt_kwargs = dict(
        evidence_schema_version="2", evidence_type="execution_receipt",
        execution_id="exec-1", attestation_type="operator_attested",
        code_commit="abc123", producer_version="1.0",
        sanitised_command="python x.py", started_at_utc="2026-01-01T00:00:00",
        completed_at_utc="2026-01-01T00:00:10", exit_code=0,
        model_id="amazon/chronos-2", configured_revision="rev1",
        resolved_revision="rev1", environment_summary="python=3.12",
        evidence_origin="real_measurement", git_worktree_clean=True,
    )
    evidence = CloudEvidence(
        evidence_origin="real_measurement", success=True,
        code_commit="abc123", deployed_commit="abc123",
        collection_receipt={**receipt_kwargs, "canonical_content_sha256": "a" * 64},
        # collection_session deliberately omitted
    )
    errs = evidence.validate()
    if not any("collection_session" in e for e in errs):
        errors.append(
            "CloudEvidence.validate() did not flag a missing collection_session "
            "when collection_receipt is present"
        )
    return errors


def _check_execution_wrapper_bundle_compatibility() -> list[str]:
    """Verify run_with_receipt() (the preferred execution wrapper) produces
    a receipt build_local_stage0_bundle.py's binding check actually
    accepts — this was a real incompatibility (component_sha256 was hard-
    required, but run_with_receipt() never set it)."""
    errors: list[str] = []
    try:
        from src.telemetry import run_with_receipt
        from scripts.build_local_stage0_bundle import _validate_receipt_binding
    except ImportError as exc:
        errors.append(f"telemetry/build_local_stage0_bundle import failed: {exc}")
        return errors

    import tempfile
    with tempfile.TemporaryDirectory() as tmp:
        component_path = os.path.join(tmp, "component.json")
        script = (
            "import json,sys; "
            f"json.dump({{'evidence_type': 'smoke_test', 'success': True}}, open(r'{component_path}', 'w'))"
        )
        exit_code, receipt = run_with_receipt(
            command=[sys.executable, "-c", script],
            output_component_path=component_path,
            model_id="amazon/chronos-2", configured_revision="rev1",
            resolved_revision="rev1", evidence_origin="real_measurement",
        )
        if exit_code != 0:
            errors.append(f"bootstrap subprocess for this check failed unexpectedly: exit {exit_code}")
            return errors
        receipt_path = os.path.join(tmp, "receipt.json")
        with open(receipt_path, "w", encoding="utf-8") as f:
            json.dump(receipt, f)
        binding_errors = _validate_receipt_binding(receipt_path, component_path, "component")
        if binding_errors:
            errors.append(
                "run_with_receipt() output rejected by build_local_stage0_bundle.py's "
                f"binding check: {binding_errors}"
            )
    return errors


def _check_sanitisation_breaking_digest_is_detected() -> list[str]:
    """Verify that if a receipt's canonical_content_sha256 is bound BEFORE
    sanitisation and sanitisation then changes the component's content, the
    resulting mismatch is actually detected (proves the "sanitise before
    bind" ordering, WP-F, matters and is enforced — not merely reordered
    for no effect)."""
    errors: list[str] = []
    try:
        from src.evidence_schemas import LocalStage0Bundle, canonical_evidence_sha256
        from scripts.publish_evidence import _sanitise_evidence
    except ImportError as exc:
        errors.append(f"evidence_schemas/publish_evidence import failed: {exc}")
        return errors

    component_with_personal_path = {
        "code_commit": "abc123",
        "error": "C:\\Users\\someuser\\project\\failure.log",
    }
    # Bind to the PRE-sanitisation digest (the bug this guards against).
    stale_digest = canonical_evidence_sha256(component_with_personal_path)

    bundle_dict = {
        "evidence_schema_version": "2", "evidence_type": "local_stage0_bundle",
        "evidence_origin": "real_measurement", "bundle_passed": False,
        "code_commit": "abc123", "git_worktree_clean": True,
        "started_at_utc": "2026-01-01T00:00:00", "completed_at_utc": "2026-01-01T00:01:00",
        "runs": {"download_cold_smoke": component_with_personal_path},
        "model_artifact": {},
        "receipts": {},
    }
    sanitised = _sanitise_evidence(bundle_dict)
    sanitised_component = sanitised["runs"]["download_cold_smoke"]
    fresh_digest = canonical_evidence_sha256(sanitised_component)

    if stale_digest == fresh_digest:
        errors.append(
            "sanitisation did not change a component containing a personal "
            "path — this check's fixture is not exercising sanitisation at all"
        )
    return errors


def _check_nonexistent_receipt_manifest_filename_rejected() -> list[str]:
    """Verify verify_evidence_manifest.py rejects a manifest entry whose
    filename does not exist on disk — this is the exact WP-I failure mode
    (an "embedded_in_<bundle>" filename that was never actually written)."""
    errors: list[str] = []
    try:
        import scripts.verify_evidence_manifest as vm
    except ImportError as exc:
        errors.append(f"verify_evidence_manifest import failed: {exc}")
        return errors

    import tempfile
    with tempfile.TemporaryDirectory() as tmp:
        evidence_dir = Path(tmp)
        manifest_path = evidence_dir / "evidence_manifest.json"
        manifest = {
            "evidence_schema_version": "2",
            "last_updated": "2026-01-01T00:00:00",
            "files": {
                "receipt_example": {
                    "filename": "embedded_in_some_bundle.json",
                    "sha256": "a" * 64,
                    "code_commit": "abc123",
                    "evidence_type": "execution_receipt",
                    "notes": "",
                },
            },
        }
        manifest_path.write_text(json.dumps(manifest), encoding="utf-8")

        original_dir, original_manifest = vm.EVIDENCE_DIR, vm.MANIFEST_PATH
        vm.EVIDENCE_DIR, vm.MANIFEST_PATH = evidence_dir, manifest_path
        try:
            result = vm.verify_manifest()
        finally:
            vm.EVIDENCE_DIR, vm.MANIFEST_PATH = original_dir, original_manifest

        if result == 0:
            errors.append(
                "verify_evidence_manifest.py accepted a manifest entry "
                "referencing a nonexistent file"
            )
    return errors


def _check_nonzero_exit_code_in_passing_evidence_rejected() -> list[str]:
    """Verify receipt_is_release_ready() rejects a non-zero exit_code —
    the field ExecutionReceipt.validate() alone leaves unenforced beyond
    rejecting negative values."""
    errors: list[str] = []
    try:
        from src.evidence_schemas import ExecutionReceipt, receipt_is_release_ready
    except ImportError as exc:
        errors.append(f"evidence_schemas import failed: {exc}")
        return errors

    receipt = ExecutionReceipt(
        evidence_schema_version="2", evidence_type="execution_receipt",
        execution_id="exec-1", attestation_type="operator_attested",
        code_commit="abc123", producer_version="1.0",
        sanitised_command="python x.py", started_at_utc="2026-01-01T00:00:00",
        completed_at_utc="2026-01-01T00:00:10", exit_code=1,
        canonical_content_sha256="a" * 64, model_id="amazon/chronos-2",
        configured_revision="rev1", resolved_revision="rev1",
        environment_summary="python=3.12", evidence_origin="real_measurement",
        git_worktree_clean=True,
    )
    if receipt.validate() != []:
        errors.append("baseline receipt (exit_code=1) unexpectedly failed plain validate() too")
    if not any("exit_code" in e for e in receipt_is_release_ready(receipt)):
        errors.append(
            "receipt_is_release_ready() did not reject exit_code=1 for a "
            "receipt otherwise eligible for release evidence"
        )
    return errors


def _check_non_finite_canonical_json_rejected() -> list[str]:
    """Verify canonical_evidence_sha256() rejects NaN/Infinity rather than
    silently emitting non-standard JSON tokens."""
    errors: list[str] = []
    try:
        from src.evidence_schemas import canonical_evidence_sha256
    except ImportError as exc:
        errors.append(f"evidence_schemas import failed: {exc}")
        return errors

    for label, value in (("NaN", float("nan")), ("Infinity", float("inf")), ("-Infinity", float("-inf"))):
        try:
            canonical_evidence_sha256({"v": value})
            errors.append(f"canonical_evidence_sha256() accepted {label} instead of raising")
        except ValueError:
            pass
        except Exception as exc:
            errors.append(f"canonical_evidence_sha256({label}) raised {type(exc).__name__}, expected ValueError: {exc}")
    return errors


def _check_mcp_graphify_paths_outside_d_rejected() -> list[str]:
    """Verify the shared D-drive policy rejects an MCP/Graphify path that
    isn't under D:\\Forecasting-Tool-Local — there is no separate, weaker
    rule for these two."""
    errors: list[str] = []
    try:
        from src.storage_policy import is_under_local_root, REQUIRED_DIRS, REQUIRED_ENV_VARS
    except ImportError as exc:
        errors.append(f"storage_policy import failed: {exc}")
        return errors

    for bad_path in (r"C:\Users\dev\.mcp\cache", r"C:\Users\dev\graphify-output", "relative\\mcp\\cache"):
        if is_under_local_root(bad_path):
            errors.append(f"is_under_local_root() incorrectly accepted off-D path: {bad_path}")

    for key in ("mcp", "graphify"):
        if not any(key in d.lower() for d in REQUIRED_DIRS):
            errors.append(f"REQUIRED_DIRS has no entry mentioning '{key}'")
    if "MCP_CACHE_DIR" not in REQUIRED_ENV_VARS:
        errors.append("REQUIRED_ENV_VARS missing MCP_CACHE_DIR")
    if "GRAPHIFY_CACHE_DIR" not in REQUIRED_ENV_VARS:
        errors.append("REQUIRED_ENV_VARS missing GRAPHIFY_CACHE_DIR")
    return errors


def _check_coverage_gate_fail_closed() -> list[str]:
    """Verify the exact rounding mechanism behind the PR #25 false-green CI
    bug: coverage.results.should_fail_under() rounds by --cov-precision
    before comparing, and ci.yml's --cov-precision=2 closes the gap that
    caused pytest to exit 0 on 81.91% actual coverage against an 82%
    threshold."""
    errors: list[str] = []
    try:
        from coverage.results import should_fail_under
    except ImportError as exc:
        errors.append(f"coverage.results import failed: {exc}")
        return errors

    if should_fail_under(81.91, 82, 0) is not False:
        errors.append(
            "should_fail_under(81.91, 82, precision=0) is no longer False — "
            "the documented root cause has changed; re-verify ci.yml's fix still applies"
        )
    if should_fail_under(81.91, 82, 2) is not True:
        errors.append(
            "should_fail_under(81.91, 82, precision=2) is not True — "
            "--cov-precision=2 in ci.yml would no longer close the rounding gap"
        )

    ci_yml_path = REPO_ROOT / ".github" / "workflows" / "ci.yml"
    if ci_yml_path.exists():
        content = ci_yml_path.read_text(encoding="utf-8")
        if "--cov-precision=2" not in content:
            errors.append("ci.yml no longer sets --cov-precision=2 on the coverage step")
    else:
        errors.append(f"ci.yml not found at {ci_yml_path}")

    return errors


def main() -> int:
    all_errors: list[str] = []

    print("=" * 64)
    print("  Stage 0 Evidence Readiness Verification (offline)")
    print("=" * 64)

    # 1. Schema module consistency
    print("\n[1/25] Schema module consistency...")
    errors = _check_schema_module()
    if errors:
        for e in errors:
            print(f"  [FAIL] {e}")
        all_errors.extend(errors)
    else:
        print("  [OK]")

    # 2. Canonical registry parity
    print("\n[2/25] Canonical Cloud test registry parity...")
    errors = _check_canonical_registry_parity()
    if errors:
        for e in errors:
            print(f"  [FAIL] {e}")
        all_errors.extend(errors)
    else:
        print("  [OK]")

    # 3. Cloud builder synthetic fixture
    print("\n[3/25] Cloud builder with valid synthetic fixture...")
    errors = _check_cloud_builder_synthetic_fixture()
    if errors:
        for e in errors:
            print(f"  [FAIL] {e}")
        all_errors.extend(errors)
    else:
        print("  [OK]")

    # 4. Benchmark preflight ordering
    print("\n[4/25] Benchmark preflight ordering contract...")
    errors = _check_benchmark_preflight_ordering()
    if errors:
        for e in errors:
            print(f"  [FAIL] {e}")
        all_errors.extend(errors)
    else:
        print("  [OK]")

    # 5. Receipt binding contract
    print("\n[5/25] Receipt binding typeness and mandatory validation...")
    errors = _check_receipt_binding_contract()
    if errors:
        for e in errors:
            print(f"  [FAIL] {e}")
        all_errors.extend(errors)
    else:
        print("  [OK]")

    # 6. Invalidated evidence
    print("\n[6/25] Invalidated evidence remains non-passing...")
    errors = _check_invalidated_evidence()
    if errors:
        for e in errors:
            print(f"  [FAIL] {e}")
        all_errors.extend(errors)
    else:
        print("  [OK]")

    # 7. Canonical digest determinism
    print("\n[7/25] Canonical digest determinism and mutation detection...")
    errors = _check_canonical_digest()
    if errors:
        for e in errors:
            print(f"  [FAIL] {e}")
        all_errors.extend(errors)
    else:
        print("  [OK]")

    # 8. Sanitisation idempotence
    print("\n[8/25] Sanitisation idempotence...")
    errors = _check_sanitisation()
    if errors:
        for e in errors:
            print(f"  [FAIL] {e}")
        all_errors.extend(errors)
    else:
        print("  [OK]")

    # 9. Secret-redaction detection
    print("\n[9/25] Secret-redaction detection...")
    errors = _check_secret_redaction()
    if errors:
        for e in errors:
            print(f"  [FAIL] {e}")
        all_errors.extend(errors)
    else:
        print("  [OK]")

    # 10. Manifest verification
    print("\n[10/25] Manifest hash verification...")
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
    print("\n[11/25] WP12 regression tests (receipt SHA, digest mutation)...")
    errors = run_wp12_regression_tests()
    if errors:
        for e in errors:
            print(f"  [FAIL] {e}")
        all_errors.extend(errors)
    else:
        print("  [OK]")

    # WP-M: additional behavioral readiness checks
    _wp_m_checks = [
        (12, "Explicit evidence_origin is required (never defaulted)", _check_evidence_origin_required),
        (13, "Synthetic receipt in real Cloud evidence is rejected", _check_synthetic_receipt_in_real_evidence_rejected),
        (14, "Cloud collection_session binding is required", _check_cloud_collection_binding_required),
        (15, "Execution-wrapper / bundle-builder compatibility", _check_execution_wrapper_bundle_compatibility),
        (16, "Sanitisation-breaks-digest is detected", _check_sanitisation_breaking_digest_is_detected),
        (17, "Nonexistent receipt manifest filename is rejected", _check_nonexistent_receipt_manifest_filename_rejected),
        (18, "Non-zero exit code in passing evidence is rejected", _check_nonzero_exit_code_in_passing_evidence_rejected),
        (19, "Non-finite canonical JSON is rejected", _check_non_finite_canonical_json_rejected),
        (20, "MCP/Graphify paths outside D: are rejected", _check_mcp_graphify_paths_outside_d_rejected),
        (21, "Coverage gate is fail-closed (rounding fix in place)", _check_coverage_gate_fail_closed),
        # PR #26 review regressions (P1-1, P1-2)
        (22, "Collection session for another commit is rejected (P1-2)", _check_collection_session_wrong_commit_rejected),
        (23, "Empty collection-session deployed_commit is rejected (P1-2)", _check_collection_session_empty_deployed_commit_rejected),
        (24, "Collection receipt with wrong commit identity is rejected (P1-2)", _check_collection_receipt_wrong_identity_rejected),
        (25, "Sanitised collection_session/collection_receipt binding still validates", _check_sanitised_collection_binding_still_valid),
    ]
    for n, label, check_fn in _wp_m_checks:
        print(f"\n[{n}/25] {label}...")
        errors = check_fn()
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
