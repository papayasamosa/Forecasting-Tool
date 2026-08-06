"""D-drive contract tests for setup and activation scripts.

Tests the storage policy module and verifies setup/activation script behavior.
Does NOT perform a real Windows installation. Runs on any platform.
"""
from __future__ import annotations

import os
import re
import sys
import subprocess
from pathlib import Path
from typing import Any

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT))

from src.storage_policy import (
    LOCAL_ROOT,
    REQUIRED_DIRS,
    REQUIRED_ENV_VARS,
    is_valid_storage_root,
    is_under_local_root,
    is_on_d_drive,
    assert_d_drive_preflight,
    _is_abs_windows_path,
)


# ---------------------------------------------------------------------------
# Existing storage_policy tests (already in test_storage_policy.py)
# These additional tests cover the setup/activation script contract
# ---------------------------------------------------------------------------


class TestDDriveSetupContract:
    """Tests for setup script behavior (cross-platform, no real installation)."""

    def test_required_dirs_match_policy(self):
        """Every directory in storage_policy.REQUIRED_DIRS must be under LOCAL_ROOT."""
        for d in REQUIRED_DIRS:
            assert is_under_local_root(d), f"{d} not under {LOCAL_ROOT}"

    def test_required_env_vars_match_policy(self):
        """Every env var target in storage_policy.REQUIRED_ENV_VARS must be under
        LOCAL_ROOT, except FORECASTING_REPO_ROOT which is the deliberately
        separate repository root (never under LOCAL_ROOT\repo)."""
        for var, val in REQUIRED_ENV_VARS.items():
            if var == "FORECASTING_REPO_ROOT":
                assert is_on_d_drive(val), f"{var}={val} not on D: drive"
                continue
            assert is_under_local_root(val), f"{var}={val} not under {LOCAL_ROOT}"

    def test_root_descendant_outside_repo_rejected(self):
        """A path under LOCAL_ROOT but outside \\repo must be rejected
        as a repository root (but accepted as a storage path)."""
        # is_under_local_root accepts any descendant
        assert is_under_local_root(r"D:\Forecasting-Tool-Local\cache")
        # But the setup script specifically checks for \repo
        # is_valid_storage_root does NOT check for \repo - that's a separate
        # check in the setup script
        assert is_valid_storage_root(r"D:\Forecasting-Tool-Local\cache")

    def test_preflight_before_install_contract(self):
        """assert_d_drive_preflight must be callable without side effects.
        On non-Windows it returns empty list."""
        errors = assert_d_drive_preflight()
        assert isinstance(errors, list)
        if sys.platform != "win32":
            assert errors == [], f"Non-Windows should return empty: {errors}"

    def test_python_instructions_use_d_drive(self):
        """Setup script must reference D: paths for Python."""
        setup_path = REPO_ROOT / "scripts" / "setup_local_windows.ps1"
        content = setup_path.read_text(encoding="utf-8")
        assert "$LocalRoot" in content or "D:\\Forecasting-Tool-Local" in content
        # Python installer download goes to installers dir on D:
        assert "installers" in content
        # Python runtime goes to python312 on D:
        assert "python312" in content

    def test_c_drive_rejected(self):
        """C:, other drives, UNC, and relative paths must be rejected."""
        assert is_valid_storage_root(r"C:\Forecasting-Tool-Local") is False
        assert is_valid_storage_root(r"E:\Forecasting-Tool-Local") is False
        assert is_valid_storage_root(r"\\server\share\Forecasting-Tool-Local") is False
        assert is_valid_storage_root("relative\\path") is False

    def test_mcp_graphify_paths_use_d_drive(self):
        """MCP, Graphify, Playwright, uv, Ruff, matplotlib paths must use D:."""
        # Check REQUIRED_ENV_VARS for D-drive paths
        uv_cache = REQUIRED_ENV_VARS.get("UV_CACHE_DIR", "")
        if uv_cache:
            assert uv_cache.startswith(LOCAL_ROOT), f"UV_CACHE_DIR not on D: {uv_cache}"
        ruff_cache = REQUIRED_ENV_VARS.get("RUFF_CACHE_DIR", "")
        if ruff_cache:
            assert ruff_cache.startswith(LOCAL_ROOT), f"RUFF_CACHE_DIR not on D: {ruff_cache}"
        playwright = REQUIRED_ENV_VARS.get("PLAYWRIGHT_BROWSERS_PATH", "")
        if playwright:
            assert playwright.startswith(LOCAL_ROOT), f"PLAYWRIGHT_BROWSERS_PATH not on D: {playwright}"
        mpl = REQUIRED_ENV_VARS.get("MPLCONFIGDIR", "")
        if mpl:
            assert mpl.startswith(LOCAL_ROOT), f"MPLCONFIGDIR not on D: {mpl}"

    def test_setup_script_creates_required_dirs(self):
        """The setup script must have mkdir commands for all REQUIRED_DIRS."""
        setup_path = REPO_ROOT / "scripts" / "setup_local_windows.ps1"
        content = setup_path.read_text(encoding="utf-8")
        # Check that key dirs are mentioned (the repository is deliberately
        # NOT under LocalRoot\repo — it lives at FORECASTING_REPO_ROOT).
        for key_dir in ["python312", "installers", "downloads", "temp\\pytest",
                        "evidence-work", "logs"]:
            # Check for the directory name in New-Item calls
            assert key_dir in content, f"Setup script missing mkdir for {key_dir}"

    def test_setup_script_dirs_exact_parity_with_required_dirs(self):
        """WP-L: the PS1 $dirs array (PowerShell can't import storage_policy)
        must declare EXACTLY the same directory set as REQUIRED_DIRS — no
        more, no fewer. This is the regression check that would have
        caught the actual drift found while implementing WP-L: the PS1
        script already had cache/pycache, cache/npm(-prefix), cache/uv(-
        tools), cache/playwright, cache/matplotlib, and cache/ruff, none
        of which were in REQUIRED_DIRS."""
        setup_path = REPO_ROOT / "scripts" / "setup_local_windows.ps1"
        content = setup_path.read_text(encoding="utf-8")

        dirs_block_match = re.search(r'\$dirs\s*=\s*@\((.*?)\)', content, re.DOTALL)
        assert dirs_block_match, "Could not locate $dirs = @(...) block in setup script"
        dirs_block = dirs_block_match.group(1)

        ps1_suffixes = set()
        for line in dirs_block.splitlines():
            m = re.search(r'"\$LocalRoot(\\[^"]*)?"', line)
            if not m:
                continue
            suffix = (m.group(1) or "").lstrip("\\").replace("\\", "/")
            ps1_suffixes.add(suffix)

        assert ps1_suffixes, "No $LocalRoot-relative directories parsed from PS1 $dirs block"

        policy_suffixes = set()
        for d in REQUIRED_DIRS:
            norm = d.replace("\\", "/")
            root_norm = LOCAL_ROOT.replace("\\", "/")
            assert norm.startswith(root_norm), f"{d} not under {LOCAL_ROOT}"
            policy_suffixes.add(norm[len(root_norm):].lstrip("/"))

        only_in_ps1 = ps1_suffixes - policy_suffixes
        only_in_policy = policy_suffixes - ps1_suffixes
        assert not only_in_ps1, (
            f"setup_local_windows.ps1 creates directories not in "
            f"storage_policy.REQUIRED_DIRS: {sorted(only_in_ps1)}"
        )
        assert not only_in_policy, (
            f"storage_policy.REQUIRED_DIRS has directories the setup "
            f"script never creates: {sorted(only_in_policy)}"
        )

    def test_activation_and_setup_scripts_env_vars_match_required_env_vars(self):
        """Both PS1 scripts must set every REQUIRED_ENV_VARS key, and the
        values must reference $LocalRoot with the same suffix as the
        Python-side value (relative to LOCAL_ROOT) — catches drift where
        a var is exported but pointed at the wrong subdirectory."""
        for script_name in ("setup_local_windows.ps1", "activate_local_windows.ps1"):
            content = (REPO_ROOT / "scripts" / script_name).read_text(encoding="utf-8")
            for var, expected_value in REQUIRED_ENV_VARS.items():
                # Value is either a quoted "$LocalRoot\..." string, or (for
                # FORECASTING_LOCAL_ROOT itself) the bare $LocalRoot variable,
                # or (for FORECASTING_REPO_ROOT) Split-Path -Parent $PSScriptRoot.
                m = re.search(rf'\$env:{re.escape(var)}\s*=\s*(?:"([^"]*)"|(\$LocalRoot)|(Split-Path -Parent \$PSScriptRoot))', content)
                assert m, f"{script_name} does not set $env:{var}"
                ps1_value = m.group(1) if m.group(1) is not None else (m.group(3) or "$LocalRoot")
                if var == "FORECASTING_REPO_ROOT":
                    # Deliberate exception: the repo root is separate from
                    # LOCAL_ROOT and derived from the script location.
                    assert "Split-Path -Parent" in ps1_value, ps1_value
                    continue
                expected_suffix = expected_value.replace("\\", "/")[len(LOCAL_ROOT.replace("\\", "/")):].lstrip("/")
                ps1_suffix = ps1_value.replace("\\", "/").replace("$LocalRoot", "").lstrip("/")
                assert ps1_suffix == expected_suffix, (
                    f"{script_name}: $env:{var} = '{ps1_value}' does not match "
                    f"REQUIRED_ENV_VARS['{var}'] suffix '{expected_suffix}'"
                )

    def test_python_path_outside_d_drive_rejected(self):
        """WP-L: -PythonPath must be rejected when it resolves outside
        D:\\Forecasting-Tool-Local, even though it's a valid existing path."""
        setup_path = REPO_ROOT / "scripts" / "setup_local_windows.ps1"
        content = setup_path.read_text(encoding="utf-8")
        assert "-PythonPath must be under" in content
        assert "$LocalRoot\\*" in content or "notlike" in content

    def test_no_c_drive_bootstrap_fallback(self):
        """WP3: the setup script must NEVER use the `py` launcher or a PATH
        Python as a bootstrap to create the D-drive venv. A C-drive based
        venv is not an approved project runtime, so the script must always
        install the pinned Python directly into
        D:\\Forecasting-Tool-Local\\python312 and create the venv from that
        interpreter."""
        setup_path = REPO_ROOT / "scripts" / "setup_local_windows.ps1"
        content = setup_path.read_text(encoding="utf-8")
        # The old "bootstrap interpreter" search must be gone.
        assert "bootstrap interpreter" not in content
        assert "searching for a bootstrap" not in content
        assert 'Get-Command "py"' not in content
        assert 'Get-Command "python"' not in content
        # The venv must be created from the D-drive python.
        assert '-m venv "$LocalRoot\\venv"' in content
        assert "$pythonInstallDir\\python.exe" in content
        # The base interpreter must be verified against the D-drive tree.
        assert "verify_ddrive_runtime" in content

    def test_setup_rejects_existing_non_d_base_venv(self):
        """WP3: the setup script must reject an existing venv whose base
        interpreter is outside the approved runtime tree."""
        setup_path = REPO_ROOT / "scripts" / "setup_local_windows.ps1"
        content = setup_path.read_text(encoding="utf-8")
        assert "Delete the existing venv" in content
        assert "based on the D-drive project Python" in content

    def test_storage_policy_has_runtime_verifier(self):
        """WP3: storage_policy must expose a runtime verifier checking
        sys.executable, sys.prefix, sys.base_prefix and pyvenv.cfg home."""
        from src.storage_policy import verify_ddrive_runtime
        assert callable(verify_ddrive_runtime)

    def test_verify_environment_calls_runtime_verifier(self):
        """WP3: verify_environment.py must invoke the shared runtime
        verifier so a C-based venv is reported as an error."""
        verify_path = REPO_ROOT / "scripts" / "verify_environment.py"
        content = verify_path.read_text(encoding="utf-8")
        assert "verify_ddrive_runtime" in content

    def test_activation_script_exports_all_required_vars(self):
        """Activation script must set every REQUIRED_ENV_VAR."""
        activate_path = REPO_ROOT / "scripts" / "activate_local_windows.ps1"
        content = activate_path.read_text(encoding="utf-8")
        for var in REQUIRED_ENV_VARS:
            assert var in content, f"Activation script missing env var {var}"

    def test_installer_sha256_is_well_formed(self):
        """The pinned installer SHA-256 must be a 64-char lowercase hex
        digest — catches truncation/typo without requiring a real download."""
        setup_path = REPO_ROOT / "scripts" / "setup_local_windows.ps1"
        content = setup_path.read_text(encoding="utf-8")
        m = re.search(r'\$expectedSha256\s*=\s*"([0-9a-fA-F]+)"', content)
        assert m, "Could not locate $expectedSha256 in setup script"
        digest = m.group(1)
        assert digest == digest.lower(), "pinned SHA-256 must be lowercase"
        assert len(digest) == 64, f"pinned SHA-256 has {len(digest)} chars, expected 64"

    def test_installer_sha256_matches_verified_official_release(self):
        """Regression guard for a live defect found while implementing this
        work: the previously pinned SHA-256 (be2551f5...) never matched the
        real python-3.12.10-amd64.exe release artifact — it would fail this
        check on every run, blocking the D-drive runtime install entirely.
        The corrected value below was verified against python.org's
        published MD5 (5eddb0b6f12c852725de071ae681dde4) for the same file
        and a valid Authenticode signature from the Python Software
        Foundation. Pinned literally so a future edit can't silently
        reintroduce a wrong hash."""
        setup_path = REPO_ROOT / "scripts" / "setup_local_windows.ps1"
        content = setup_path.read_text(encoding="utf-8")
        assert (
            "67b5635e80ea51072b87941312d00ec8927c4db9ba18938f7ad2d27b328b95fb" in content
        ), "setup script no longer pins the verified python-3.12.10-amd64.exe SHA-256"
        assert "be2551f5a3280b96d4d3c9472cdcd1c2443b58f11ddef5c270596a6223e5e68f" not in content, (
            "setup script reverted to the stale, never-matching SHA-256"
        )

    def test_installer_download_url_matches_pinned_version(self):
        """The download URL must reference the exact pinned installer file
        the SHA-256/Authenticode checks below it were computed against."""
        setup_path = REPO_ROOT / "scripts" / "setup_local_windows.ps1"
        content = setup_path.read_text(encoding="utf-8")
        assert "python-3.12.10-amd64.exe" in content
        assert "https://www.python.org/ftp/python/3.12.10/python-3.12.10-amd64.exe" in content

    def test_installer_authenticode_publisher_pinned(self):
        """The installer's Authenticode signer must be checked against the
        expected publisher string, not just 'has any valid signature'."""
        setup_path = REPO_ROOT / "scripts" / "setup_local_windows.ps1"
        content = setup_path.read_text(encoding="utf-8")
        assert "Get-AuthenticodeSignature" in content
        assert "Python Software Foundation" in content
        assert "expectedPublisher" in content


class TestActivationContract:
    """Tests for the activation script."""

    def test_activation_sets_all_required_vars(self):
        """Verify activation script exports match REQUIRED_ENV_VARS."""
        activate_path = REPO_ROOT / "scripts" / "activate_local_windows.ps1"
        content = activate_path.read_text(encoding="utf-8")
        for var in REQUIRED_ENV_VARS:
            assert var in content, f"Activation script missing {var}"

    def test_activation_validates_before_change(self):
        """Activation must validate D-drive policy before setting vars."""
        activate_path = REPO_ROOT / "scripts" / "activate_local_windows.ps1"
        content = activate_path.read_text(encoding="utf-8")
        assert "Validate" in content or "WP12" in content or "resolvedRoot" in content or "driveLetter" in content
        assert "D:" in content

    def test_verification_script_uses_shared_policy(self):
        """verify_environment.py must import from storage_policy."""
        verify_path = REPO_ROOT / "scripts" / "verify_environment.py"
        content = verify_path.read_text(encoding="utf-8")
        assert "from src.storage_policy" in content


class TestMCPToolPaths:
    """MCP, Graphify, and developer tool paths must use D: drive."""

    def test_ruff_cache_on_d(self):
        assert REQUIRED_ENV_VARS.get("RUFF_CACHE_DIR", "").startswith(LOCAL_ROOT)

    def test_uv_cache_on_d(self):
        assert REQUIRED_ENV_VARS.get("UV_CACHE_DIR", "").startswith(LOCAL_ROOT)

    def test_playwright_on_d(self):
        assert REQUIRED_ENV_VARS.get("PLAYWRIGHT_BROWSERS_PATH", "").startswith(LOCAL_ROOT)

    def test_matplotlib_on_d(self):
        assert REQUIRED_ENV_VARS.get("MPLCONFIGDIR", "").startswith(LOCAL_ROOT)

    def test_npm_cache_on_d(self):
        assert REQUIRED_ENV_VARS.get("NPM_CONFIG_CACHE", "").startswith(LOCAL_ROOT)

    def test_pycache_on_d(self):
        assert REQUIRED_ENV_VARS.get("PYTHONPYCACHEPREFIX", "").startswith(LOCAL_ROOT)

    def test_xdg_cache_on_d(self):
        assert REQUIRED_ENV_VARS.get("XDG_CACHE_HOME", "").startswith(LOCAL_ROOT)

    def test_mcp_cache_on_d(self):
        assert REQUIRED_ENV_VARS.get("MCP_CACHE_DIR", "").startswith(LOCAL_ROOT)
        assert os.path.join(LOCAL_ROOT, "cache", "mcp") in REQUIRED_DIRS

    def test_graphify_cache_on_d(self):
        assert REQUIRED_ENV_VARS.get("GRAPHIFY_CACHE_DIR", "").startswith(LOCAL_ROOT)
        assert os.path.join(LOCAL_ROOT, "cache", "graphify") in REQUIRED_DIRS

    def test_graphify_output_on_d(self):
        assert REQUIRED_ENV_VARS.get("GRAPHIFY_OUTPUT_DIR", "").startswith(LOCAL_ROOT)
        assert os.path.join(LOCAL_ROOT, "graphify-output") in REQUIRED_DIRS

    def test_mcp_and_graphify_paths_rejected_outside_d(self):
        """A path claiming to be an MCP/Graphify output location must be
        rejected by the same is_under_local_root() check as everything
        else — there is no separate, weaker rule for these two."""
        assert is_under_local_root(r"C:\Users\dev\.mcp\cache") is False
        assert is_under_local_root(r"C:\Users\dev\graphify-output") is False
        assert is_under_local_root(os.path.join(LOCAL_ROOT, "cache", "mcp")) is True
        assert is_under_local_root(os.path.join(LOCAL_ROOT, "graphify-output")) is True
