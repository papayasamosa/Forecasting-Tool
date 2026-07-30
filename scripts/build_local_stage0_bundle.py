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
import hashlib
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


def _sha256_file(path: str) -> str:
    """Compute the SHA-256 of a file's raw bytes."""
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(65536), b""):
            h.update(chunk)
    return h.hexdigest()


def _check_distinct_token_evidence(
    process_cold_path: str,
    token_present_path: str,
    pc_smoke: Any,
    tp_smoke: Any,
) -> list[str]:
    """Reject a token-present smoke file that duplicates the no-token
    process-cold file (the Gate B3 defect: identical timestamps and
    measurements with only ``hf_token_present`` and the token-result objects
    flipped).

    Uses immutable provenance — distinct file bytes, distinct run IDs, and
    distinct start/completion identities — rather than comparing timing
    values, since two genuinely independent real-model runs can coincidentally
    round to the same duration.
    """
    errors: list[str] = []

    if os.path.abspath(process_cold_path) == os.path.abspath(token_present_path):
        errors.append(
            "token_present_smoke: same file path as process_cold_smoke — a "
            "token-present run must be a separate, independently executed "
            "evidence file"
        )
        return errors

    try:
        pc_hash = _sha256_file(process_cold_path)
        tp_hash = _sha256_file(token_present_path)
    except OSError as exc:
        errors.append(f"token_present_smoke: could not hash evidence files: {exc}")
        return errors

    if pc_hash == tp_hash:
        errors.append(
            "token_present_smoke: byte-identical to process_cold_smoke "
            f"(sha256={pc_hash}) — cannot be an independently executed run"
        )

    if not isinstance(pc_smoke, dict) or not isinstance(tp_smoke, dict):
        return errors

    pc_started = pc_smoke.get("started_at_utc", "")
    tp_started = tp_smoke.get("started_at_utc", "")
    if pc_started and tp_started and pc_started == tp_started:
        errors.append(
            "token_present_smoke: started_at_utc identical to "
            f"process_cold_smoke ('{tp_started}') — not an independent run"
        )

    pc_completed = pc_smoke.get("completed_at_utc", "")
    tp_completed = tp_smoke.get("completed_at_utc", "")
    if pc_completed and tp_completed and pc_completed == tp_completed:
        errors.append(
            "token_present_smoke: completed_at_utc identical to "
            f"process_cold_smoke ('{tp_completed}') — not an independent run"
        )

    pc_run_id = (pc_smoke.get("token_absent_result") or {}).get("run_id", "")
    tp_run_id = (tp_smoke.get("token_present_result") or {}).get("run_id", "")
    if not pc_run_id:
        errors.append("process_cold_smoke: token_absent_result.run_id is empty")
    if not tp_run_id:
        errors.append("token_present_smoke: token_present_result.run_id is empty")
    if pc_run_id and tp_run_id and pc_run_id == tp_run_id:
        errors.append(
            "token_present_smoke: token_present_result.run_id identical to "
            f"process_cold_smoke's token_absent_result.run_id ('{tp_run_id}') "
            "— not an independent run"
        )

    return errors


def _validate_component_typed(
    data: dict[str, Any],
    component_name: str,
    expected_evidence_type: str,
    expected_token_present: bool | None,
    expected_initial_cache_state: str | None,
    expected_commit: str | None,
) -> list[str]:
    """Validate a single component through the typed evidence schemas (WP3).

    Deserialises via evidence_from_dict, calls validate(), and checks
    top-level field consistency. Returns a list of error messages.
    """
    errors: list[str] = []

    if not isinstance(data, dict):
        errors.append(f"{component_name}: root must be a JSON object")
        return errors

    # Deserialise through typed schema
    try:
        sys.path.insert(0, str(REPO_ROOT))
        from src.evidence_schemas import evidence_from_dict
        evidence_obj = evidence_from_dict(data)
    except Exception as exc:
        errors.append(f"{component_name}: deserialisation failed: {exc}")
        return errors

    # Run typed validate()
    if hasattr(evidence_obj, "validate"):
        schema_errors = evidence_obj.validate()
        for se in schema_errors:
            errors.append(f"{component_name}: {se}")

    # Evidence type check
    actual_type = getattr(evidence_obj, "evidence_type", "")
    if actual_type != expected_evidence_type:
        errors.append(
            f"{component_name}: expected evidence_type '{expected_evidence_type}', "
            f"got '{actual_type}'"
        )

    # Schema version
    actual_sv = getattr(evidence_obj, "evidence_schema_version", "")
    if actual_sv != "2":
        errors.append(f"{component_name}: expected evidence_schema_version '2', got '{actual_sv}'")

    # Code commit
    actual_cc = getattr(evidence_obj, "code_commit", "")
    if not actual_cc:
        errors.append(f"{component_name}: code_commit is empty")
    elif expected_commit and actual_cc != expected_commit:
        errors.append(f"{component_name}: code_commit '{actual_cc}' != expected '{expected_commit}'")

    # Worktree must be clean
    actual_wt = getattr(evidence_obj, "git_worktree_clean", False)
    if not actual_wt:
        errors.append(f"{component_name}: git_worktree_clean is false")

    # Git traceability must not have errors
    actual_gte = getattr(evidence_obj, "git_traceability_error", "")
    if actual_gte:
        errors.append(f"{component_name}: git_traceability_error: {actual_gte}")

    # Token validation
    if expected_token_present is not None:
        actual_token = getattr(evidence_obj, "hf_token_present", None)
        if actual_token is None:
            errors.append(f"{component_name}: hf_token_present missing")
        elif actual_token != expected_token_present:
            errors.append(
                f"{component_name}: hf_token_present expected {expected_token_present}, "
                f"got {actual_token}"
            )
        # Also check token path results for release evidence
        if expected_token_present is False:
            tar = getattr(evidence_obj, "token_absent_result", None)
            if tar and hasattr(tar, "attempted") and not tar.attempted:
                errors.append(f"{component_name}: token_absent_result not attempted")
        elif expected_token_present is True:
            tpr = getattr(evidence_obj, "token_present_result", None)
            if tpr and hasattr(tpr, "attempted") and not tpr.attempted:
                errors.append(f"{component_name}: token_present_result not attempted")

    # Cache state validation
    if expected_initial_cache_state:
        actual_ics = getattr(evidence_obj, "initial_cache_state", "")
        if actual_ics != expected_initial_cache_state:
            errors.append(
                f"{component_name}: initial_cache_state expected "
                f"'{expected_initial_cache_state}', got '{actual_ics}'"
            )

    # Model ID must match
    actual_mid = getattr(evidence_obj, "model_id", "")
    if actual_mid and actual_mid != "amazon/chronos-2":
        errors.append(f"{component_name}: unexpected model_id '{actual_mid}'")

    # Configured revision must be present
    actual_cr = getattr(evidence_obj, "configured_revision", "")
    if not actual_cr:
        errors.append(f"{component_name}: configured_revision missing")

    # Success/passed for smoke/benchmark
    if expected_evidence_type == "smoke_test" and not getattr(evidence_obj, "success", False):
        errors.append(f"{component_name}: success is false")
    if expected_evidence_type == "benchmark_suite" and not getattr(evidence_obj, "suite_passed", False):
        errors.append(f"{component_name}: suite_passed is false")

    return errors


def _validate_model_artifact_typed(
    data: dict[str, Any],
    expected_commit: str | None,
    expected_cr: str | None,
    expected_mr: str | None,
) -> list[str]:
    """Validate model artifact through typed schemas (WP3)."""
    errors: list[str] = []

    if not isinstance(data, dict):
        errors.append("model_artifact: root must be a JSON object")
        return errors

    try:
        sys.path.insert(0, str(REPO_ROOT))
        from src.evidence_schemas import evidence_from_dict
        art = evidence_from_dict(data)
    except Exception as exc:
        errors.append(f"model_artifact: deserialisation failed: {exc}")
        return errors

    # Run typed validate()
    if hasattr(art, "validate"):
        schema_errors = art.validate()
        for se in schema_errors:
            errors.append(f"model_artifact: {se}")

    # Field-level checks
    if not getattr(art, "code_commit", ""):
        errors.append("model_artifact: code_commit empty")
    elif expected_commit and getattr(art, "code_commit", "") != expected_commit:
        errors.append(
            f"model_artifact: code_commit '{getattr(art, 'code_commit', '')}' "
            f"!= expected '{expected_commit}'"
        )
    if not getattr(art, "git_worktree_clean", False):
        errors.append("model_artifact: git_worktree_clean is false")
    if getattr(art, "model_id", "") != "amazon/chronos-2":
        errors.append(f"model_artifact: unexpected model_id '{getattr(art, 'model_id', '')}'")
    if not getattr(art, "configured_revision", ""):
        errors.append("model_artifact: configured_revision empty")
    if not getattr(art, "resolved_revision", ""):
        errors.append("model_artifact: resolved_revision empty")
    actual_sc = getattr(art, "snapshot_commit", "")
    if not actual_sc:
        errors.append("model_artifact: snapshot_commit empty")
    elif expected_mr and actual_sc != expected_mr:
        errors.append(
            f"model_artifact: snapshot_commit '{actual_sc}' != "
            f"expected model_revision '{expected_mr}'"
        )
    # File hashes must be present
    files = getattr(art, "files", [])
    for f in files:
        if not f.sha256:
            errors.append(f"model_artifact: file '{f.filename}' missing sha256")
    # Manifest SHA-256
    if not getattr(art, "manifest_sha256", ""):
        errors.append("model_artifact: manifest_sha256 empty")

    return errors


def _check_revision_consistency(all_data: dict[str, dict[str, Any]]) -> list[str]:
    """Verify consistent model_id, configured_revision, model_revision across
    all components."""
    errors: list[str] = []
    model_ids: set[str] = set()
    configured_revisions: set[str] = set()
    model_revisions: set[str] = set()

    for label, comp in all_data.items():
        if not isinstance(comp, dict):
            continue
        mid = comp.get("model_id", "")
        if mid:
            model_ids.add(mid)
        cr = comp.get("configured_revision", "") or comp.get("resolved_revision", "")
        if cr:
            configured_revisions.add(cr)
        mr = comp.get("model_revision", "") or comp.get("resolved_revision", "")
        if mr:
            model_revisions.add(mr)

    if len(model_ids) > 1:
        errors.append(f"inconsistent model_id across components: {model_ids}")
    if len(configured_revisions) > 1:
        errors.append(f"inconsistent configured_revision across components: {configured_revisions}")
    if len(model_revisions) > 1:
        errors.append(f"inconsistent model_revision across components: {model_revisions}")

    return errors


def _validate_receipt_binding(
    receipt_path: str,
    component_path: str,
    component_label: str,
) -> list[str]:
    """Strictly validate that a receipt matches a component file.

    P0-3: For a passing bundle, receipts must be fully verified:
    - valid ExecutionReceipt schema
    - non-empty valid component SHA-256 matching the actual file
    - receipt commit equals component commit
    - model ID matches
    - configured and resolved revisions match
    - ordered timestamps
    - non-empty producer version
    - sanitized command contains no token or secret
    """
    errors: list[str] = []
    try:
        receipt_data = _load_json(receipt_path)
    except (json.JSONDecodeError, OSError) as exc:
        errors.append(f"{component_label}_receipt: could not load '{receipt_path}': {exc}")
        return errors

    if not isinstance(receipt_data, dict):
        errors.append(f"{component_label}_receipt: root must be a JSON object")
        return errors

    # Deserialize as ExecutionReceipt and run schema validation
    sys.path.insert(0, str(REPO_ROOT))
    from src.evidence_schemas import ExecutionReceipt
    try:
        receipt = ExecutionReceipt(**receipt_data)
    except Exception as exc:
        errors.append(f"{component_label}_receipt: deserialisation failed: {exc}")
        return errors

    receipt_errors = receipt.validate()
    for re in receipt_errors:
        errors.append(f"{component_label}_receipt: {re}")

    # Component SHA-256 must be non-empty and match actual file
    if not receipt.component_sha256:
        errors.append(f"{component_label}_receipt: component_sha256 empty — required for binding")
    else:
        try:
            actual_sha = _sha256_file(component_path)
        except OSError as exc:
            errors.append(f"{component_label}_receipt: could not hash component '{component_path}': {exc}")
            return errors
        if receipt.component_sha256 != actual_sha:
            errors.append(
                f"{component_label}_receipt: component_sha256 '{receipt.component_sha256}' "
                f"!= actual '{actual_sha}'"
            )

    # Load component to cross-check
    try:
        comp_data = _load_json(component_path)
    except (json.JSONDecodeError, OSError) as exc:
        errors.append(f"{component_label}_receipt: could not load component '{component_path}': {exc}")
        return errors

    if isinstance(comp_data, dict):
        # Commit match
        comp_commit = comp_data.get("code_commit", "")
        if comp_commit and receipt.code_commit and receipt.code_commit != comp_commit:
            errors.append(
                f"{component_label}_receipt: code_commit '{receipt.code_commit}' "
                f"!= component code_commit '{comp_commit}'"
            )
        # Model ID match
        comp_mid = comp_data.get("model_id", "")
        if comp_mid and receipt.model_id and receipt.model_id != comp_mid:
            errors.append(
                f"{component_label}_receipt: model_id '{receipt.model_id}' "
                f"!= component model_id '{comp_mid}'"
            )
        # Configured revision match
        comp_cr = comp_data.get("configured_revision", "")
        if comp_cr and receipt.configured_revision and receipt.configured_revision != comp_cr:
            errors.append(
                f"{component_label}_receipt: configured_revision '{receipt.configured_revision}' "
                f"!= component configured_revision '{comp_cr}'"
            )
        # Resolved revision match
        comp_mr = comp_data.get("model_revision", "") or comp_data.get("resolved_revision", "")
        if comp_mr and receipt.resolved_revision and receipt.resolved_revision != comp_mr:
            errors.append(
                f"{component_label}_receipt: resolved_revision '{receipt.resolved_revision}' "
                f"!= component model/resolved_revision '{comp_mr}'"
            )

    # WP10: Safe secret-redaction validation
    # Allow redacted patterns and legitimate references; reject exposed values
    import re as _re
    cmd = receipt.sanitised_command

    # Allowed patterns (redacted or legitimate references)
    allowed_patterns = [
        _re.compile(r'HF_TOKEN=\[REDACTED\]', _re.IGNORECASE),
        _re.compile(r'HF_TOKEN=<redacted>', _re.IGNORECASE),
        _re.compile(r'HF_TOKEN=\$\(.*\)', _re.IGNORECASE),  # script variable
        _re.compile(r'--token-state\s+present', _re.IGNORECASE),
        _re.compile(r'token-present-smoke\.json', _re.IGNORECASE),
        _re.compile(r'token-absent-run', _re.IGNORECASE),
        _re.compile(r'token-present-run', _re.IGNORECASE),
    ]
    # If the entire command matches an allowed pattern, skip exposed-value check
    is_allowed = any(p.search(cmd) for p in allowed_patterns)

    # Rejected patterns (exposed values)
    rejected_patterns = [
        (_re.compile(r'HF_TOKEN=[a-zA-Z0-9_]{10,}', _re.IGNORECASE), "exposed HF_TOKEN value"),
        (_re.compile(r'Authorization:\s*Bearer\s+\S+', _re.IGNORECASE), "exposed Authorization header"),
        (_re.compile(r'password=\S+', _re.IGNORECASE), "exposed password value"),
        (_re.compile(r'secret=\S+', _re.IGNORECASE), "exposed secret value"),
        (_re.compile(r'api[_-]?key[=:]\s*\S+', _re.IGNORECASE), "exposed API key"),
        (_re.compile(r'token=\S+', _re.IGNORECASE) if not is_allowed else None, "exposed token value"),
    ]

    for pattern, description in rejected_patterns:
        if pattern is None:
            continue
        if pattern.search(cmd):
            errors.append(
                f"{component_label}_receipt: sanitised_command contains "
                f"{description}"
            )

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
    parser.add_argument("--download-cold-smoke-receipt", default="", help="Receipt for download-cold smoke")
    parser.add_argument("--process-cold-smoke-receipt", default="", help="Receipt for process-cold smoke")
    parser.add_argument("--benchmark-receipt", default="", help="Receipt for benchmark")
    parser.add_argument("--token-present-smoke-receipt", default="", help="Receipt for token-present smoke")
    parser.add_argument("--model-artifact-receipt", default="", help="Receipt for model artifact")
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

    expected_commit = dc_smoke.get("code_commit", "") if isinstance(dc_smoke, dict) else ""

    # Collect expected revisions from smoke data
    expected_cr = dc_smoke.get("configured_revision", "") if isinstance(dc_smoke, dict) else ""
    expected_mr = dc_smoke.get("model_revision", "") if isinstance(dc_smoke, dict) else ""

    # Recursive typed validation (WP9) — every component goes through
    # the shared recursive validator from src.evidence_validation.
    sys.path.insert(0, str(REPO_ROOT))
    from src.evidence_validation import validate_recursive

    all_errors: list[str] = []

    # Validate individual components
    all_errors.extend(validate_recursive(dc_smoke, label="download_cold_smoke"))
    all_errors.extend(validate_recursive(pc_smoke, label="process_cold_smoke"))
    all_errors.extend(validate_recursive(benchmark, label="benchmark"))
    all_errors.extend(validate_recursive(tp_smoke, label="token_present_smoke"))
    all_errors.extend(validate_recursive(model_art, label="model_artifact"))

    # Cross-component revision consistency
    all_errors.extend(_check_revision_consistency({
        "download_cold_smoke": dc_smoke,
        "process_cold_smoke": pc_smoke,
        "benchmark": benchmark,
        "token_present_smoke": tp_smoke,
        "model_artifact": model_art,
    }))

    # Evidence-integrity closure: reject a token-present record that
    # duplicates the no-token process-cold record (Gate B3 defect).
    all_errors.extend(_check_distinct_token_evidence(
        args.process_cold_smoke, args.token_present_smoke, pc_smoke, tp_smoke,
    ))

    # WP6: Validate receipt bindings
    receipt_args = [
        ("download_cold_smoke", args.download_cold_smoke_receipt, args.download_cold_smoke),
        ("process_cold_smoke", args.process_cold_smoke_receipt, args.process_cold_smoke),
        ("benchmark", args.benchmark_receipt, args.benchmark),
        ("token_present_smoke", args.token_present_smoke_receipt, args.token_present_smoke),
        ("model_artifact", args.model_artifact_receipt, args.model_artifact),
    ]
    receipts: dict[str, Any] = {}
    seen_exec_ids: set[str] = set()
    for label, receipt_path, component_path in receipt_args:
        if receipt_path:
            r_errors = _validate_receipt_binding(receipt_path, component_path, label)
            all_errors.extend(r_errors)
            if not r_errors:
                receipt_data = _load_json(receipt_path)
                # Check execution ID uniqueness across all receipts
                exec_id = receipt_data.get("execution_id", "")
                if exec_id:
                    if exec_id in seen_exec_ids:
                        all_errors.append(
                            f"{label}_receipt: duplicate execution_id '{exec_id}'"
                        )
                    seen_exec_ids.add(exec_id)
                receipts[label] = receipt_data
        else:
            receipts[label] = None

    # WP7: Explicitly require all smoke runs successful and benchmark.suite_passed == true
    smoke_success = all(
        isinstance(c, dict) and c.get("evidence_type") == "smoke_test" and c.get("success", False)
        for c in [dc_smoke, pc_smoke, tp_smoke]
        if isinstance(c, dict)
    )
    benchmark_passed = isinstance(benchmark, dict) and benchmark.get("suite_passed", False)
    # WP3: Receipts are mandatory for a passing bundle — all 5 must be provided
    all_receipts_provided = all(
        getattr(args, f"{label.replace('-', '_')}_receipt", "")
        for label in ["download_cold_smoke", "process_cold_smoke", "benchmark",
                       "token_present_smoke", "model_artifact"]
    )
    bundle_passed = len(all_errors) == 0 and smoke_success and benchmark_passed and all_receipts_provided

    if not smoke_success:
        all_errors.append("bundle: not all smoke runs are successful")
    if not benchmark_passed:
        all_errors.append("bundle: benchmark.suite_passed is false")
    if not all_receipts_provided:
        all_errors.append("bundle: all 5 receipt files are required for a passing bundle")

    if all_errors:
        print("Bundle validation errors:")
        for err in all_errors:
            print(f"  [FAIL] {err}")
        return 1

    # Build bundle
    started_utc = datetime.now(timezone.utc).isoformat()
    # Only include non-None receipts
    bundle_receipts = {k: v for k, v in receipts.items() if v is not None}
    bundle = {
        "evidence_schema_version": "2",
        "evidence_type": "local_stage0_bundle",
        "bundle_passed": bundle_passed,
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
        "receipts": bundle_receipts if bundle_receipts else {},
    }

    bundle["completed_at_utc"] = datetime.now(timezone.utc).isoformat()

    # WP7: Recursively validate the final assembled bundle before writing
    final_errors = validate_recursive(bundle, label="local_stage0_bundle")
    if final_errors:
        print("Final bundle recursive validation errors:")
        for err in final_errors:
            print(f"  [FAIL] {err}")
        return 1

    output = args.output
    if output:
        with open(output, "w", encoding="utf-8") as f:
            json.dump(bundle, f, indent=2, default=str)
        print(f"[OK] Bundle written to: {output}")
    else:
        json.dump(bundle, sys.stdout, indent=2, default=str)
        print()

    print(f"\n[OK] Bundle validation passed — {len(all_errors)} errors")
    print(f"  Commit: {expected_commit}")
    print(f"  Components: download_cold_smoke, process_cold_smoke, benchmark, token_present_smoke, model_artifact")

    return 0


if __name__ == "__main__":
    sys.exit(main())
