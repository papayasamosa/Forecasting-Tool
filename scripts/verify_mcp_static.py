#! /usr/bin/env python3
"""Static MCP configuration verifier — runs on CI without D: drive,
Docker, Node, network access, or live credentials.

Checks:
- JSON validity of template and version files
- Version manifest structure and schema
- Required .gitignore patterns for MCP secrets
- No secret-shaped values in tracked MCP files
- No MCP packages in requirements.txt
- Safe example configuration (no live credentials)
"""

from __future__ import annotations

import json
import os
import re
import sys
from pathlib import Path
from typing import Any

# ---------------------------------------------------------------------------
# Paths
# ---------------------------------------------------------------------------
REPO_ROOT = Path(__file__).resolve().parent.parent

TOOLS_MCP = REPO_ROOT / "tools" / "mcp"
EXAMPLE_JSON = TOOLS_MCP / "mcp.example.json"
VERSIONS_JSON = TOOLS_MCP / "mcp-versions.json"
README_MD = REPO_ROOT / "README.md"
GITIGNORE = REPO_ROOT / ".gitignore"
REQUIREMENTS_TXT = REPO_ROOT / "requirements.txt"

MCP_DOCS_FILES = [
    REPO_ROOT / "docs" / "development" / "mcp_setup.md",
    REPO_ROOT / "docs" / "development" / "mcp_usage_policy.md",
]

# Tracked MCP-related file extensions
MCP_FILE_EXTS = {".json", ".md", ".toml", ".yaml", ".yml", ".env.example", ".ps1"}

# ---------------------------------------------------------------------------
# Results
# ---------------------------------------------------------------------------
_errors: list[str] = []
_warnings: list[str] = []


def error(msg: str) -> None:
    _errors.append(msg)


def warn(msg: str) -> None:
    _warnings.append(msg)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _git_ls_files() -> list[str]:
    """Return list of tracked files relative to repo root."""
    import subprocess
    try:
        result = subprocess.run(
            ["git", "ls-files"],
            capture_output=True, text=True, timeout=10,
            cwd=str(REPO_ROOT),
        )
        if result.returncode == 0:
            return [f.strip() for f in result.stdout.splitlines() if f.strip()]
    except Exception:
        pass
    return []


def _read_file(path: Path) -> str | None:
    try:
        return path.read_text(encoding="utf-8")
    except Exception:
        return None


# ---------------------------------------------------------------------------
# Checks
# ---------------------------------------------------------------------------

def check_json_validity() -> None:
    """Check that template and version JSON files parse correctly."""
    for name, path in [("mcp.example.json", EXAMPLE_JSON), ("mcp-versions.json", VERSIONS_JSON)]:
        content = _read_file(path)
        if content is None:
            error(f"{name}: file not found")
            continue
        try:
            json.loads(content)
        except json.JSONDecodeError as exc:
            error(f"{name}: invalid JSON — {exc}")


def check_version_manifest() -> None:
    """Check that the version manifest has the expected structure."""
    content = _read_file(VERSIONS_JSON)
    if content is None:
        error("mcp-versions.json: file not found")
        return
    try:
        data = json.loads(content)
    except json.JSONDecodeError:
        return  # already reported by check_json_validity

    if not isinstance(data, dict):
        error("mcp-versions.json: root must be a JSON object")
        return

    if "schema_version" not in data:
        error("mcp-versions.json: missing 'schema_version'")
    if "servers" not in data:
        error("mcp-versions.json: missing 'servers'")
        return

    servers = data.get("servers", {})
    for server_name in ("github", "context7", "playwright", "huggingface"):
        if server_name not in servers:
            warn(f"mcp-versions.json: missing server entry '{server_name}'")
            continue
        entry = servers[server_name]
        for key in ("implementation", "transport", "version"):
            if key not in entry:
                warn(f"mcp-versions.json: server '{server_name}' missing '{key}'")

        # Check for REPLACE_AFTER_VERIFICATION placeholder
        version = entry.get("version", "")
        if version == "REPLACE_AFTER_VERIFICATION":
            warn(
                f"mcp-versions.json: server '{server_name}' version is still "
                f"'REPLACE_AFTER_VERIFICATION' — update after functional verification"
            )


def check_gitignore_patterns() -> None:
    """Check required .gitignore patterns for MCP secrets."""
    content = _read_file(GITIGNORE)
    if content is None:
        error(".gitignore: file not found")
        return

    required_patterns = [
        ".env.mcp",
        ".mcp.json",
        ".mcp.local.json",
        ".mcp-auth/",
        ".mcp-state/",
        ".mcp-logs/",
        ".playwright-mcp/",
    ]

    for pattern in required_patterns:
        if pattern not in content:
            error(f".gitignore: missing required pattern '{pattern}'")


def check_secret_patterns() -> None:
    """Check tracked MCP-related files for secret-shaped values.

    Never prints the matched value.
    """
    secret_patterns = [
        re.compile(r'gh[pousr]_[A-Za-z0-9]{20,}'),
        re.compile(r'github_pat_[A-Za-z0-9_]{20,}'),
        re.compile(r'hf_[A-Za-z0-9]{20,}'),
        re.compile(r'sk-[A-Za-z0-9]{20,}'),
        re.compile(r'"[A-Za-z0-9+/]{40,}={0,2}"'),
    ]

    # Discover tracked MCP-related files via git ls-files
    tracked = _git_ls_files()
    mcp_files = []
    for f in tracked:
        ext = Path(f).suffix.lower()
        f_lower = f.lower()
        if ext in MCP_FILE_EXTS and (
            "mcp" in f_lower or "context7" in f_lower
            or "playwright" in f_lower or "huggingface" in f_lower
        ):
            mcp_files.append(REPO_ROOT / f)

    hits: list[str] = []
    for filepath in mcp_files:
        if not filepath.exists():
            continue
        lines = _read_file(filepath)
        if lines is None:
            continue
        for line_no, line in enumerate(lines.splitlines(), 1):
            for pattern in secret_patterns:
                if pattern.search(line):
                    hits.append(f"{filepath.name}:{line_no}")
                    break

    if hits:
        error(
            f"Suspicious secret-shaped patterns found in tracked MCP files "
            f"(values not printed): {', '.join(hits)}"
        )


def check_requirements_no_mcp() -> None:
    """Check that requirements.txt has no MCP packages."""
    content = _read_file(REQUIREMENTS_TXT)
    if content is None:
        warn("requirements.txt: file not found")
        return

    mcp_names = [
        "mcp-server", "@playwright/mcp", "playwright-mcp",
        "context7-mcp", "github-mcp", "modelcontextprotocol",
    ]
    for name in mcp_names:
        if name in content:
            error(f"requirements.txt: MCP package '{name}' found in production dependencies")


def check_example_config_safe() -> None:
    """Check that mcp.example.json contains only placeholders, not real credentials."""
    content = _read_file(EXAMPLE_JSON)
    if content is None:
        warn("mcp.example.json: file not found — skipping safety check")
        return

    # Ensure the file contains placeholder markers
    if "${" not in content and "USE_THE_CLIENT" not in content:
        warn(
            "mcp.example.json: does not contain obvious placeholder markers (${VAR}). "
            "Verify it has no live credentials."
        )

    # Ensure no real token-like values
    dangerous_patterns = [
        r'ghp_[A-Za-z0-9]{36}',
        r'github_pat_[A-Za-z0-9_]{36,}',
        r'hf_[A-Za-z0-9]{36,}',
        r'sk-[A-Za-z0-9]{36,}',
        r'xox[baprs]-[A-Za-z0-9-]{24,}',
    ]
    for pattern in dangerous_patterns:
        if re.search(pattern, content):
            error("mcp.example.json: appears to contain a real credential value")


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main() -> int:
    """Run all static MCP checks and return exit code."""
    check_json_validity()
    check_version_manifest()
    check_gitignore_patterns()
    check_secret_patterns()
    check_requirements_no_mcp()
    check_example_config_safe()

    # Print results
    print("=" * 64)
    print("  MCP Static Verification")
    print("=" * 64)

    if not _errors and not _warnings:
        print("\n  All checks passed.")
        print(f"  {len(_warnings)} warnings, {len(_errors)} errors")
        print("=" * 64)
        return 0

    if _warnings:
        print(f"\n  Warnings ({len(_warnings)}):")
        for w in _warnings:
            print(f"    ⚠  {w}")

    if _errors:
        print(f"\n  Errors ({len(_errors)}):")
        for e in _errors:
            print(f"    ❌ {e}")

    print(f"\n  {len(_warnings)} warnings, {len(_errors)} errors")
    print("=" * 64)
    return 1 if _errors else 0


if __name__ == "__main__":
    sys.exit(main())
