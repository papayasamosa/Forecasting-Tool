#! /usr/bin/env python3
"""Verify integrity of the evidence manifest and all referenced files.

Validates:
- Every non-null file entry exists on disk
- SHA-256 hash matches committed bytes
- evidence_type matches expected values
- code_commit is non-empty
- evidence_schema_version matches

Usage:
    python scripts/verify_evidence_manifest.py

Exit codes:
    0 — All checks passed
    1 — Any check failed
"""

from __future__ import annotations

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


def verify_manifest() -> int:
    """Verify the evidence manifest and return exit code (0=ok, 1=fail)."""
    if not MANIFEST_PATH.exists():
        print(f"ERROR: manifest not found: {MANIFEST_PATH}")
        return 1

    with open(MANIFEST_PATH, encoding="utf-8") as f:
        manifest = json.load(f)

    errors: list[str] = []

    # Check schema version
    schema_ver = manifest.get("evidence_schema_version", "")
    if schema_ver != "2":
        errors.append(f"evidence_schema_version: expected '2', got '{schema_ver}'")

    # Check each file entry
    files = manifest.get("files", {})
    if not files:
        errors.append("files: manifest has no file entries")

    for key, entry in files.items():
        if not isinstance(entry, dict):
            errors.append(f"{key}: entry must be a dict, got {type(entry).__name__}")
            continue

        fname = entry.get("filename")
        expected_sha = entry.get("sha256")
        code_commit = entry.get("code_commit")
        evidence_type = entry.get("evidence_type")

        # Skip null entries (not yet populated)
        if fname is None or expected_sha is None:
            continue

        # File must exist
        fpath = EVIDENCE_DIR / fname
        if not fpath.exists():
            errors.append(f"{key}: file not found: {fpath}")
            continue

        # SHA-256 must match
        actual_sha = _compute_sha256(fpath)
        if actual_sha != expected_sha:
            errors.append(
                f"{key}: SHA-256 mismatch for {fname}\n"
                f"  expected: {expected_sha}\n"
                f"  actual:   {actual_sha}"
            )

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

    # Summary
    if errors:
        print("Evidence manifest verification FAILED:")
        for err in errors:
            print(f"  [FAIL] {err}")
        return 1

    print("[OK] Evidence manifest verified — all files match their hashes.")
    print(f"   Manifest: {MANIFEST_PATH.name}")
    print(f"   Files checked: {sum(1 for e in files.values() if isinstance(e, dict) and e.get('filename'))}")
    return 0


def main() -> int:
    return verify_manifest()


if __name__ == "__main__":
    sys.exit(main())
