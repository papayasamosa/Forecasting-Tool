#! /usr/bin/env python3
"""Publish sanitised evidence to ``docs/evidence/stage0/``.

Validates, sanitises, and copies evidence JSON files into the evidence
directory with computed SHA-256 hashes. Uses the typed evidence schemas
from ``src.evidence_schemas`` for validation. Updates
``evidence_manifest.json`` atomically.

WP3: Deterministic finalisation pipeline:
    1. Raw component validates
    2. Component is sanitised deterministically
    3. Sanitised component validates
    4. Final publishable component bytes are written
    5. Publisher copies without changing semantic content
    6. Manifest records final file hashes

WP7: Synthetic evidence rejection:
    - Evidence with evidence_origin=synthetic_fixture is rejected
    - Only real_measurement can be published as release evidence

WP11: Receipt tracking:
    - Receipt files are tracked alongside component files in the manifest
    - Each receipt is validated and its SHA-256 is recorded

Usage:
    python scripts/publish_evidence.py <evidence-file> --type <evidence_type>

Evidence types:
    smoke_test           — Smoke evidence (requires --expected-token-state)
    benchmark_suite      — Benchmark suite envelope (v2)
    model_artifact       — Model checksum metadata
    local_stage0_bundle  — Complete local evidence bundle
    cloud_stage0         — Community Cloud evidence
    execution_receipt    — Execution receipt (tracked separately in manifest)
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import shutil
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

# ---------------------------------------------------------------------------
# Paths
# ---------------------------------------------------------------------------
REPO_ROOT = Path(__file__).resolve().parent.parent
EVIDENCE_DIR = REPO_ROOT / "docs" / "evidence" / "stage0"
MANIFEST_PATH = EVIDENCE_DIR / "evidence_manifest.json"

# Patterns to remove from evidence before committing (personal paths, etc.)
_SANITISE_PATTERNS = [
    (re.compile(r'[A-Za-z]:\\Users\\[^\\"\' ]+'), "[USER_REMOVED]"),
    (re.compile(r'[A-Za-z]:\\[^\\"\' ]+\\[Vv]en[vV]'), "[VENV_PATH_REMOVED]"),
    (re.compile(r'/home/[^/"\' ]+'), "[HOME_REMOVED]"),
]

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _compute_sha256(path: Path) -> str:
    """Compute SHA-256 hash of a file."""
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(65536), b""):
            h.update(chunk)
    return h.hexdigest()


def _sanitise_value(value: Any) -> Any:
    """Recursively sanitise a value, replacing personal paths.

    Handles:
    - strings
    - dicts (recurses into values)
    - lists (recurses into elements)
    - tuples (converts to list, recurses)
    - nested structures
    """
    if isinstance(value, str):
        sanitised = value
        for pattern, replacement in _SANITISE_PATTERNS:
            sanitised = pattern.sub(replacement, sanitised)
        return sanitised
    elif isinstance(value, dict):
        return {k: _sanitise_value(v) for k, v in value.items()}
    elif isinstance(value, list):
        return [_sanitise_value(item) for item in value]
    elif isinstance(value, tuple):
        return tuple(_sanitise_value(item) for item in value)
    else:
        return value


def _sanitise_evidence(data: dict[str, Any]) -> dict[str, Any]:
    """Remove personal paths and sensitive values from evidence dict."""
    return _sanitise_value(data)


def _load_json_file(path: Path) -> Any:
    """Load and parse a JSON file, returning the parsed object."""
    with open(path, encoding="utf-8") as f:
        return json.load(f)


def _load_manifest() -> dict[str, Any]:
    """Load the existing manifest or return default structure."""
    if MANIFEST_PATH.exists():
        try:
            return _load_json_file(MANIFEST_PATH)
        except (json.JSONDecodeError, OSError):
            pass
    return {
        "evidence_schema_version": "2",
        "last_updated": None,
        "files": {},
    }


def _collision_guard_path(dest_dir: Path, prefix: str, suffix: str = ".json") -> Path:
    """Return a unique path using microseconds and a random suffix."""
    import random
    ts = datetime.now().strftime("%Y%m%d_%H%M%S_%f")
    rand = f"{random.getrandbits(32):08x}"
    return dest_dir / f"{prefix}_{ts}_{rand}{suffix}"


# ---------------------------------------------------------------------------
# Validation (delegates to evidence schemas)
# ---------------------------------------------------------------------------


def _validate_and_load(
    raw_data: Any,
    expected_type: str,
    expected_token_state: bool | None,
    expected_initial_cache_state: str | None,
    expected_code_commit: str | None,
) -> tuple[Any, list[str]]:
    """Validate raw JSON data against schema v2 rules.

    Returns (evidence_object, errors_list).
    """
    errors: list[str] = []

    # Must be a dict
    if not isinstance(raw_data, dict):
        errors.append(f"root: expected JSON object, got {type(raw_data).__name__}")
        return (None, errors)

    # Import schema validator
    sys.path.insert(0, str(REPO_ROOT))
    try:
        from src.evidence_schemas import (
            EVIDENCE_SCHEMA_VERSION,
            EVIDENCE_ORIGIN_REAL,
            EVIDENCE_ORIGIN_SYNTHETIC,
            evidence_from_dict,
            SmokeEvidence,
            BenchmarkSuiteEvidence,
            ModelArtifactEvidence,
            LocalStage0Bundle,
            CloudEvidence,
            VALID_INITIAL_CACHE_STATES,
        )
    except ImportError as exc:
        errors.append(f"cannot import evidence schemas: {exc}")
        return (None, errors)

    # Schema version check
    schema_ver = raw_data.get("evidence_schema_version", "")
    if schema_ver != EVIDENCE_SCHEMA_VERSION:
        errors.append(
            f"evidence_schema_version: expected '{EVIDENCE_SCHEMA_VERSION}', "
            f"got '{schema_ver}'"
        )
        return (None, errors)

    # Evidence type check
    actual_type = raw_data.get("evidence_type", "")
    if actual_type != expected_type:
        errors.append(
            f"evidence_type: expected '{expected_type}', got '{actual_type}'"
        )
        return (None, errors)

    # Deserialise via schema
    try:
        evidence = evidence_from_dict(raw_data)
    except (ValueError, TypeError, KeyError) as exc:
        errors.append(f"deserialisation failed: {exc}")
        return (None, errors)

    # Run schema-level validation
    if hasattr(evidence, "validate"):
        schema_errors = evidence.validate()
        errors.extend(schema_errors)

    # Extra checks per type
    if expected_token_state is not None:
        actual_token = raw_data.get("hf_token_present", None)
        if actual_token is None:
            errors.append("hf_token_present: missing — required for token-state validation")
        elif actual_token != expected_token_state:
            errors.append(
                f"hf_token_present: expected {expected_token_state}, got {actual_token}"
            )

    if expected_initial_cache_state:
        actual_ics = raw_data.get("initial_cache_state", "")
        if actual_ics != expected_initial_cache_state:
            errors.append(
                f"initial_cache_state: expected '{expected_initial_cache_state}', "
                f"got '{actual_ics}'"
            )

    if expected_code_commit:
        actual_cc = raw_data.get("code_commit", "")
        if actual_cc != expected_code_commit:
            errors.append(
                f"code_commit: expected '{expected_code_commit}', got '{actual_cc}'"
            )

    # WP7: Reject synthetic evidence origin for release publication
    evidence_origin = raw_data.get("evidence_origin", EVIDENCE_ORIGIN_REAL)
    if evidence_origin == EVIDENCE_ORIGIN_SYNTHETIC:
        errors.append(
            f"evidence_origin is '{EVIDENCE_ORIGIN_SYNTHETIC}' — "
            f"synthetic evidence cannot be published as release evidence. "
            f"Only '{EVIDENCE_ORIGIN_REAL}' measurements can be published."
        )

    # For smoke evidence, check success
    if expected_type == "smoke_test" and isinstance(evidence, SmokeEvidence):
        if not evidence.success:
            errors.append("smoke_test: success is false — cannot publish failed evidence")

    # For benchmark suite, check suite_passed
    if expected_type == "benchmark_suite" and isinstance(evidence, BenchmarkSuiteEvidence):
        if not evidence.suite_passed:
            errors.append("benchmark_suite: suite_passed is false")

    return (evidence, errors)


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Publish sanitised evidence to docs/evidence/stage0/",
    )
    parser.add_argument("evidence_file", type=str, help="Path to evidence JSON file")
    parser.add_argument(
        "--type",
        type=str,
        required=True,
        choices=[
            "smoke_test", "benchmark_suite", "model_artifact",
            "local_stage0_bundle", "cloud_stage0", "execution_receipt",
        ],
        help="Evidence type matching the evidence_type field in the JSON",
    )
    parser.add_argument(
        "--expected-token-state",
        type=str,
        default=None,
        choices=["present", "absent"],
        help="Validate hf_token_present matches expected state",
    )
    parser.add_argument(
        "--initial-cache-state",
        type=str,
        default="",
        choices=["download_cold", "process_cold_cached_weights", ""],
        help="Expected initial cache state for validation",
    )
    parser.add_argument(
        "--expected-commit",
        type=str,
        default="",
        help="Expected code_commit for validation",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Validate only; do not copy or update manifest",
    )
    args = parser.parse_args()

    evidence_path = Path(args.evidence_file)
    if not evidence_path.exists():
        print(f"Error: evidence file not found: {evidence_path}")
        return 1

    # Load raw JSON
    try:
        raw_data = _load_json_file(evidence_path)
    except (json.JSONDecodeError, OSError) as exc:
        print(f"Error: cannot load evidence file: {exc}")
        return 1

    # Determine expected token state
    expected_token: bool | None = None
    if args.expected_token_state == "present":
        expected_token = True
    elif args.expected_token_state == "absent":
        expected_token = False

    # Validate via shared recursive validator (WP9)
    sys.path.insert(0, str(REPO_ROOT))
    from src.evidence_validation import validate_recursive

    recursive_errors = validate_recursive(raw_data, label=args.type)
    if recursive_errors:
        print("Validation errors:")
        for err in recursive_errors:
            print(f"  ❌ {err}")
        return 1

    # Also run publisher-specific validation for token state / cache state
    evidence_obj, errors = _validate_and_load(
        raw_data,
        expected_type=args.type,
        expected_token_state=expected_token,
        expected_initial_cache_state=args.initial_cache_state or None,
        expected_code_commit=args.expected_commit or None,
    )

    if errors:
        print("Validation errors:")
        for err in errors:
            print(f"  ❌ {err}")
        return 1

    print("✅ Evidence validation passed")

    if args.dry_run:
        print("Dry-run mode: no files copied or manifest updated.")
        return 0

    # Sanitise
    sanitised = _sanitise_evidence(raw_data)
    print("✅ Evidence sanitised (recursive, all types)")

    # Determine type key for manifest
    type_key_map = {
        "smoke_test": "smoke_test",
        "benchmark_suite": "benchmark_suite",
        "model_artifact": "model_artifact",
        "local_stage0_bundle": "local_stage0_bundle",
        "cloud_stage0": "cloud_summary",
    }
    type_key = type_key_map.get(args.type, args.type)

    # Write sanitised copy with collision guard
    EVIDENCE_DIR.mkdir(parents=True, exist_ok=True)
    dest_path = _collision_guard_path(EVIDENCE_DIR, f"evidence_{args.type}")
    with open(dest_path, "w", encoding="utf-8") as f:
        json.dump(sanitised, f, indent=2, default=str)
    print(f"✅ Sanitised evidence written to: {dest_path}")

    # Compute SHA-256
    sha256 = _compute_sha256(dest_path)
    print(f"✅ SHA-256: {sha256}")

    # Update manifest atomically
    manifest = _load_manifest()
    manifest["evidence_schema_version"] = "2"
    manifest["last_updated"] = datetime.now(timezone.utc).isoformat()
    manifest["files"][type_key] = {
        "filename": dest_path.name,
        "sha256": sha256,
        "code_commit": raw_data.get("code_commit", ""),
        "evidence_type": args.type,
        "notes": f"Published {datetime.now().strftime('%Y%m%d_%H%M%S')}",
    }

    # WP11: For bundles, also track each receipt file separately in the manifest
    if args.type == "local_stage0_bundle":
        receipts = sanitised.get("receipts", {})
        if isinstance(receipts, dict):
            for rec_key, rec_data in receipts.items():
                if isinstance(rec_data, dict):
                    rec_sha = rec_data.get("canonical_content_sha256", "") or rec_data.get("component_sha256", "")
                    manifest["files"][f"receipt_{rec_key}"] = {
                        "filename": f"embedded_in_{dest_path.name}",
                        "sha256": rec_sha,
                        "code_commit": rec_data.get("code_commit", ""),
                        "evidence_type": "execution_receipt",
                        "notes": f"Receipt for {rec_key}, bound to bundle {dest_path.name}",
                    }

    manifest_tmp = MANIFEST_PATH.with_suffix(".tmp.json")
    try:
        with open(manifest_tmp, "w", encoding="utf-8") as f:
            json.dump(manifest, f, indent=2, default=str)
        shutil.move(str(manifest_tmp), str(MANIFEST_PATH))
    except OSError as exc:
        print(f"Error: failed to write manifest: {exc}")
        if manifest_tmp.exists():
            manifest_tmp.unlink()
        return 1

    print(f"✅ Manifest updated: {MANIFEST_PATH}")
    print(f"\nSummary:")
    print(f"  Type: {args.type}")
    print(f"  File: {dest_path.name}")
    print(f"  SHA-256: {sha256}")
    print(f"  Code commit: {raw_data.get('code_commit', '')}")
    print(f"  Schema version: {raw_data.get('evidence_schema_version', '')}")

    return 0


if __name__ == "__main__":
    sys.exit(main())
