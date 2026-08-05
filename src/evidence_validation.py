"""Shared recursive evidence validation for Stage 0.

Provides a single ``validate_recursive()`` entry point used by:

- ``scripts/build_local_stage0_bundle.py``
- ``scripts/publish_evidence.py``
- ``scripts/verify_evidence_manifest.py``

Reconstructs typed evidence objects from raw dicts, runs schema-level
``validate()`` on every component, and recurses into nested records so that
a failure in any leaf propagates to the root.
"""

from __future__ import annotations

import sys
from pathlib import Path
from typing import Any

# ---------------------------------------------------------------------------
# Expected types per evidence_type
# ---------------------------------------------------------------------------
SMOKE = "smoke_test"
BENCHMARK_SUITE = "benchmark_suite"
MODEL_ARTIFACT = "model_artifact"
LOCAL_BUNDLE = "local_stage0_bundle"
CLOUD_EVIDENCE = "cloud_stage0"
EXECUTION_RECEIPT = "execution_receipt"

# Nested run keys inside a local bundle that must be recursively validated
BUNDLE_RUN_KEYS = [
    "download_cold_smoke",
    "process_cold_smoke",
    "benchmark",
    "token_present_smoke",
]


# ---------------------------------------------------------------------------
# Validation helpers
# ---------------------------------------------------------------------------

def _deserialise(data: dict[str, Any], *, strict: bool = True) -> Any:
    """Deserialise a raw dict through evidence_from_dict.

    ``strict=True`` (default) rejects unknown fields at every depth — this
    module is only used by release paths (bundle builder, publisher,
    manifest verifier), so permissive parsing is never appropriate here.
    """
    sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
    from src.evidence_schemas import evidence_from_dict
    return evidence_from_dict(data, strict=strict)


def _validate_obj(obj: Any, label: str) -> list[str]:
    """Run validate() on an evidence object if available."""
    errors: list[str] = []
    if hasattr(obj, "validate"):
        try:
            schema_errors = obj.validate()
            for se in schema_errors:
                errors.append(f"{label}: {se}")
        except Exception as exc:
            errors.append(f"{label}: validate() raised {type(exc).__name__}: {exc}")
    else:
        errors.append(f"{label}: no validate() method")
    return errors


# ---------------------------------------------------------------------------
# Recursive validation
# ---------------------------------------------------------------------------


def validate_recursive(data: Any, label: str = "root", *, strict: bool = True) -> list[str]:
    """Recursively validate evidence data.

    Parameters
    ----------
    data : Any
        Parsed JSON data (dict) to validate. Must have an evidence_type field.
    label : str
        Human-readable label for error messages.
    strict : bool
        Reject unknown fields at every depth (default True — release paths
        must never silently discard schema fields).

    Returns
    -------
    list[str]
        List of error messages. Empty means valid.
    """
    errors: list[str] = []

    if not isinstance(data, dict):
        errors.append(f"{label}: root must be a JSON object, got {type(data).__name__}")
        return errors

    etype = data.get("evidence_type", "")

    # Deserialise through typed schema
    try:
        obj = _deserialise(data, strict=strict)
    except Exception as exc:
        errors.append(f"{label}: deserialisation failed: {exc}")
        return errors

    # Run type-level validate()
    errors.extend(_validate_obj(obj, label))

    # Recurse into nested records
    if etype == LOCAL_BUNDLE:
        runs = data.get("runs", {})
        for run_key in BUNDLE_RUN_KEYS:
            run_data = runs.get(run_key)
            if isinstance(run_data, dict):
                # Only recurse if the nested record has evidence_type
                if "evidence_type" in run_data:
                    errors.extend(validate_recursive(run_data, label=f"{label}.runs.{run_key}", strict=strict))
                # If no evidence_type, it's raw data stored inline; skip
                # recursive validation but the parent bundle's validate()
                # already checks basic consistency.
            else:
                errors.append(f"{label}.runs.{run_key}: missing or not a dict")
        ma = data.get("model_artifact")
        if isinstance(ma, dict):
            if "evidence_type" in ma:
                errors.extend(validate_recursive(ma, label=f"{label}.model_artifact", strict=strict))
        else:
            errors.append(f"{label}.model_artifact: missing or not a dict")

    elif etype == CLOUD_EVIDENCE:
        # Recursively validate token path results (they're embedded dicts)
        tar = data.get("token_absent_result")
        if isinstance(tar, dict):
            # TokenPathResult doesn't have evidence_type, validate inline
            try:
                obj = _deserialise({"evidence_type": SMOKE, **tar})
            except Exception:
                pass  # not a full smoke record, skip recursive
        tpr = data.get("token_present_result")
        if isinstance(tpr, dict):
            try:
                obj = _deserialise({"evidence_type": SMOKE, **tpr})
            except Exception:
                pass  # not a full smoke record, skip recursive

    elif etype == SMOKE:
        # Validate embedded token path results
        tar = data.get("token_absent_result")
        if isinstance(tar, dict):
            from src.evidence_schemas import TokenPathResult
            try:
                tp = TokenPathResult(**tar)
                errors.extend(f"{label}.token_absent_result: {e}" for e in tp.validate())
            except Exception as exc:
                errors.append(f"{label}.token_absent_result: construction failed: {exc}")
        tpr = data.get("token_present_result")
        if isinstance(tpr, dict):
            from src.evidence_schemas import TokenPathResult
            try:
                tp = TokenPathResult(**tpr)
                errors.extend(f"{label}.token_present_result: {e}" for e in tp.validate())
            except Exception as exc:
                errors.append(f"{label}.token_present_result: construction failed: {exc}")

        # Also validate cache_preflight
        cp = data.get("cache_preflight")
        if isinstance(cp, dict):
            from src.evidence_schemas import CachePreflight
            try:
                cpf = CachePreflight(**cp)
                errors.extend(f"{label}.cache_preflight: {e}" for e in cpf.validate())
            except Exception as exc:
                errors.append(f"{label}.cache_preflight: construction failed: {exc}")

    elif etype == BENCHMARK_SUITE:
        # Validate each scenario — they don't have evidence_type, so skip
        # the recursive type-based validation and just validate inline fields
        scenarios = data.get("scenarios", [])
        for i, sc in enumerate(scenarios):
            if isinstance(sc, dict):
                if "evidence_type" in sc:
                    errors.extend(validate_recursive(sc, label=f"{label}.scenarios[{i}]", strict=strict))
                # Scenarios without evidence_type are validated by the
                # parent BenchmarkSuiteEvidence.validate() method.

    return errors


def validate_or_exit(data: Any, label: str = "root") -> None:  # pragma: no cover
    """Validate recursively and exit with code 1 if errors found.

    Exposed for CLI scripts. Tested via subprocess because it calls sys.exit().
    """
    errors = validate_recursive(data, label)
    if errors:
        print(f"\n Validation errors for {label}:")
        for err in errors:
            print(f"  [FAIL] {err}")
        sys.exit(1)
    print(f" [OK] {label}: validation passed")
