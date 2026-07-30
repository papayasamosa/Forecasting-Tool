#! /usr/bin/env python3
"""Verify integrity of the evidence manifest and all referenced files.

Validates:
- Every non-null file entry exists on disk
- SHA-256 hash matches committed bytes
- Filename/hash null consistency (both null = unpublished; one null = error)
- Resolved path stays inside docs/evidence/stage0/
- Internal evidence_type, evidence_schema_version, code_commit match manifest
- Runs the matching typed schema validator on each file

Usage:
    python scripts/verify_evidence_manifest.py

Exit codes:
    0 — All checks passed
    1 — Any check failed
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import sys
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parent.parent
EVIDENCE_DIR = REPO_ROOT / "docs" / "evidence" / "stage0"
MANIFEST_PATH = EVIDENCE_DIR / "evidence_manifest.json"

# Expected evidence types per manifest key
EXPECTED_TYPES: dict[str, str] = {
    "smoke_test": "smoke_test",
    "benchmark_suite": "benchmark_suite",
    "model_artifact": "model_artifact",
    "local_stage0_bundle": "local_stage0_bundle",
    "cloud_summary": "cloud_stage0",
}


def _compute_sha256(path: Path) -> str:
    """Compute SHA-256 hash of a file."""
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(65536), b""):
            h.update(chunk)
    return h.hexdigest()


def _validate_referenced_json(fpath: Path, expected_type: str, expected_commit: str) -> list[str]:
    """Parse a referenced JSON file and validate internal metadata.

    Returns a list of error messages (empty = valid).
    """
    errors: list[str] = []
    try:
        with open(fpath, encoding="utf-8") as f:
            data = json.load(f)
    except (json.JSONDecodeError, OSError) as exc:
        errors.append(f"cannot parse {fpath.name}: {exc}")
        return errors

    if not isinstance(data, dict):
        errors.append(f"{fpath.name}: root must be a JSON object")
        return errors

    # Internal evidence_schema_version
    internal_sv = data.get("evidence_schema_version", "")
    if internal_sv != "2":
        errors.append(f"{fpath.name}: internal evidence_schema_version expected '2', got '{internal_sv}'")

    # Internal evidence_type
    internal_et = data.get("evidence_type", "")
    if internal_et != expected_type:
        errors.append(f"{fpath.name}: internal evidence_type expected '{expected_type}', got '{internal_et}'")

    # Internal code_commit
    internal_cc = data.get("code_commit", "")
    if expected_commit and internal_cc and internal_cc != expected_commit:
        errors.append(
            f"{fpath.name}: internal code_commit '{internal_cc}' "
            f"!= manifest code_commit '{expected_commit}'"
        )

    # Run shared recursive validation (WP9)
    try:
        sys.path.insert(0, str(REPO_ROOT))
        from src.evidence_validation import validate_recursive
        recursive_errors = validate_recursive(data, label=fpath.name)
        for re in recursive_errors:
            errors.append(f"{fpath.name}: {re}")
    except Exception as exc:
        errors.append(f"{fpath.name}: recursive validation error: {exc}")

    return errors


def verify_manifest() -> int:
    """Verify the evidence manifest and return exit code (0=ok, 1=fail)."""
    if not MANIFEST_PATH.exists():
        print(f"ERROR: manifest not found: {MANIFEST_PATH}")
        return 1

    with open(MANIFEST_PATH, encoding="utf-8") as f:
        manifest = json.load(f)

    errors: list[str] = []
    invalidated: list[str] = []

    # Check schema version
    schema_ver = manifest.get("evidence_schema_version", "")
    if schema_ver != "2":
        errors.append(f"evidence_schema_version: expected '2', got '{schema_ver}'")

    # Check each file entry
    files = manifest.get("files", {})
    if not files:
        errors.append("files: manifest has no file entries")

    for key, entry in files.items():
        if isinstance(entry, dict) and entry.get("status") == "invalidated":
            invalidated.append(key)
        if not isinstance(entry, dict):
            errors.append(f"{key}: entry must be a dict, got {type(entry).__name__}")
            continue

        fname = entry.get("filename")
        expected_sha = entry.get("sha256")
        code_commit = entry.get("code_commit")
        evidence_type = entry.get("evidence_type")

        # Consistency: both null = deliberately unpublished; one null = error
        if (fname is None) != (expected_sha is None):
            errors.append(
                f"{key}: inconsistent null state — filename={fname}, sha256={expected_sha}. "
                f"Both must be null (unpublished) or both populated."
            )
            continue

        # Skip deliberately unpublished entries
        if fname is None and expected_sha is None:
            continue

        # WP11: Reject absolute filenames (must be relative to evidence dir)
        if os.path.isabs(fname):
            errors.append(f"{key}: filename must be relative, got absolute path '{fname}'")
            continue

        # WP11: Reject traversal paths (parent dir references)
        # Normalize to POSIX-style separators for pattern matching
        norm_fname = fname.replace("\\", "/")
        if ".." in norm_fname.split("/"):
            errors.append(f"{key}: path traversal detected in filename '{fname}'")
            continue

        # WP11: Reject sibling-prefix paths (e.g. "foo" matches "foobar")
        # Path.is_relative_to() handles containment — but also check that
        # the resolved path is not a sibling with a shared prefix outside
        # the evidence directory.
        resolved = (EVIDENCE_DIR / fname).resolve()
        try:
            resolved.relative_to(EVIDENCE_DIR.resolve())
        except ValueError:
            errors.append(
                f"{key}: resolved '{resolved}' is not under "
                f"'{EVIDENCE_DIR.resolve()}'"
            )
            continue

        # File must exist
        if not resolved.exists():
            errors.append(f"{key}: file not found: {resolved}")
            continue

        # SHA-256 must match
        actual_sha = _compute_sha256(resolved)
        if actual_sha != expected_sha:
            errors.append(
                f"{key}: SHA-256 mismatch for {fname}\n"
                f"  expected: {expected_sha}\n"
                f"  actual:   {actual_sha}"
            )
            # Continue to report all errors even if hash fails

        # evidence_type validation
        expected_type = EXPECTED_TYPES.get(key)
        if expected_type and evidence_type:
            if evidence_type != expected_type:
                errors.append(
                    f"{key}: evidence_type expected '{expected_type}', "
                    f"got '{evidence_type}'"
                )
        elif evidence_type is None:
            errors.append(f"{key}: evidence_type is null")

        # code_commit must be non-empty
        if not code_commit:
            errors.append(f"{key}: code_commit is empty or null")

        # Parse and validate internal JSON content
        if expected_type and fname:
            internal_errors = _validate_referenced_json(resolved, expected_type, code_commit or "")
            errors.extend(internal_errors)

    # Summary
    if errors:
        print("Evidence manifest verification FAILED:")
        for err in errors:
            print(f"  [FAIL] {err}")
        return 1

    print("[OK] Evidence manifest hashes and internal metadata verified.")
    print(f"   Manifest: {MANIFEST_PATH.name}")
    print(f"   Files checked: {sum(1 for e in files.values() if isinstance(e, dict) and e.get('filename'))}")
    if invalidated:
        print()
        print("  [WARNING] The following manifest entries are marked INVALIDATED")
        print("  and must NOT be treated as passing Stage 0 release evidence,")
        print("  even though their hashes and internal schema checks pass:")
        for key in invalidated:
            note = files.get(key, {}).get("notes", "") if isinstance(files.get(key), dict) else ""
            print(f"    - {key}: {note}")
    return 0


def main(argv: list[str] | None = None) -> int:
    # Avoid using module globals in default args to prevent
    # "used prior to global declaration" SyntaxError.
    parser = argparse.ArgumentParser(
        description="Verify integrity of the evidence manifest and all referenced files.",
    )
    parser.add_argument(
        "--manifest-path",
        type=str,
        default="",
        help="Path to the evidence manifest JSON (default: docs/evidence/stage0/evidence_manifest.json)",
    )
    parser.add_argument(
        "--evidence-dir",
        type=str,
        default="",
        help="Path to the evidence directory (default: docs/evidence/stage0)",
    )
    args = parser.parse_args(argv)

    global EVIDENCE_DIR, MANIFEST_PATH  # noqa: PLW0603
    if args.manifest_path:
        MANIFEST_PATH = Path(args.manifest_path)
    if args.evidence_dir:
        EVIDENCE_DIR = Path(args.evidence_dir)

    return verify_manifest()


if __name__ == "__main__":
    sys.exit(main())
