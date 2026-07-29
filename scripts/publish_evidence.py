#! /usr/bin/env python3
"""Publish sanitised evidence to ``docs/evidence/stage0/``.

Validates, sanitises, and copies evidence JSON files into the evidence
directory with computed SHA-256 hashes. Updates ``evidence_manifest.json``
atomically.

Usage:
    python scripts/publish_evidence.py <evidence-file> --type <no_token|token_present|cloud>
    python scripts/publish_evidence.py <evidence-file> --type no_token --initial-cache-state download_cold

Requirements:
    - Evidence file must be valid JSON with required fields.
    - ``code_commit`` must be non-empty.
    - ``git_worktree_clean`` must be ``true``.
    - ``initial_cache_state`` must be non-empty and match ``--initial-cache-state``.
    - Produces a sanitised copy with personal paths removed.
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

EVIDENCE_SCHEMA_VERSION = "1"

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


def _load_json(path: Path) -> dict[str, Any]:
    """Load and parse a JSON file."""
    with open(path, encoding="utf-8") as f:
        return dict(json.load(f))


def _sanitise_evidence(data: dict[str, Any]) -> dict[str, Any]:
    """Remove personal paths and sensitive values from evidence dict.

    Returns a new dict with sanitised string values.
    """
    result: dict[str, Any] = {}

    for key, value in data.items():
        if isinstance(value, str):
            sanitised = value
            for pattern, replacement in _SANITISE_PATTERNS:
                sanitised = pattern.sub(replacement, sanitised)
            result[key] = sanitised
        elif isinstance(value, dict):
            result[key] = _sanitise_evidence(value)
        elif isinstance(value, list):
            result[key] = [
                _sanitise_evidence(item) if isinstance(item, dict) else item
                for item in value
            ]
        else:
            result[key] = value

    return result


def _load_manifest() -> dict[str, Any]:
    """Load the existing manifest or return default structure."""
    if MANIFEST_PATH.exists():
        try:
            return _load_json(MANIFEST_PATH)
        except (json.JSONDecodeError, OSError):
            pass
    return {
        "evidence_schema_version": EVIDENCE_SCHEMA_VERSION,
        "last_updated": None,
        "files": {},
    }


def _validate_evidence(
    data: dict[str, Any],
    expected_type: str,
    expected_initial_cache_state: str | None,
) -> list[str]:
    """Validate evidence dict against required fields.

    Returns a list of error messages (empty if valid).
    """
    errors: list[str] = []

    # Schema version
    if data.get("evidence_schema_version") != EVIDENCE_SCHEMA_VERSION:
        errors.append(
            f"evidence_schema_version mismatch: "
            f"expected '{EVIDENCE_SCHEMA_VERSION}', got '{data.get('evidence_schema_version')}'"
        )

    # code_commit must be non-empty
    code_commit = data.get("code_commit", "")
    if not code_commit:
        errors.append("code_commit is empty — cannot publish untraceable evidence")

    # git_worktree_clean must be true
    if not data.get("git_worktree_clean", False):
        errors.append("git_worktree_clean is false or missing — worktree must be clean")

    # initial_cache_state
    initial_cache_state = data.get("initial_cache_state", "")
    if not initial_cache_state:
        errors.append("initial_cache_state is empty — must be set for release evidence")
    elif expected_initial_cache_state and initial_cache_state != expected_initial_cache_state:
        errors.append(
            f"initial_cache_state mismatch: expected '{expected_initial_cache_state}', "
            f"got '{initial_cache_state}'"
        )

    return errors


# ---------------------------------------------------------------------------
# Main
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
        choices=["no_token", "token_present", "cloud"],
        help="Evidence type",
    )
    parser.add_argument(
        "--initial-cache-state",
        type=str,
        default="",
        choices=["download_cold", "process_cold_cached_weights", ""],
        help="Expected initial cache state for validation",
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

    # Load
    try:
        evidence = _load_json(evidence_path)
    except (json.JSONDecodeError, OSError) as exc:
        print(f"Error: cannot load evidence file: {exc}")
        return 1

    # Validate
    errors = _validate_evidence(evidence, args.type, args.initial_cache_state)
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
    sanitised = _sanitise_evidence(evidence)
    print("✅ Evidence sanitised")

    # Determine type key
    type_key_map = {
        "no_token": "local_no_token_summary",
        "token_present": "local_token_present_summary",
        "cloud": "cloud_summary",
    }
    type_key = type_key_map[args.type]

    # Write sanitised copy
    EVIDENCE_DIR.mkdir(parents=True, exist_ok=True)
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    dest_filename = f"evidence_{args.type}_{timestamp}.json"
    dest_path = EVIDENCE_DIR / dest_filename

    with open(dest_path, "w", encoding="utf-8") as f:
        json.dump(sanitised, f, indent=2, default=str)
    print(f"✅ Sanitised evidence written to: {dest_path}")

    # Compute SHA-256
    sha256 = _compute_sha256(dest_path)
    print(f"✅ SHA-256: {sha256}")

    # Update manifest
    manifest = _load_manifest()
    manifest["last_updated"] = datetime.now(timezone.utc).isoformat()
    manifest["files"][type_key] = {
        "filename": dest_filename,
        "sha256": sha256,
        "cache_state": evidence.get("initial_cache_state", ""),
        "code_commit": evidence.get("code_commit", ""),
        "notes": f"Published {timestamp}",
    }

    # Write manifest atomically
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
    print(f"  File: {dest_filename}")
    print(f"  SHA-256: {sha256}")
    print(f"  Code commit: {evidence.get('code_commit', '')}")
    print(f"  Cache state: {evidence.get('initial_cache_state', '')}")

    return 0


if __name__ == "__main__":
    sys.exit(main())
