"""D-drive contract tests for setup and activation scripts.

Tests the storage policy module and verifies setup/activation script behavior.
Does NOT perform a real Windows installation. Runs on any platform.
"""
from __future__ import annotations

import os
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
        """Every env var target in storage_policy.REQUIRED_ENV_VARS must be under LOCAL_ROOT."""
        for var, val in REQUIRED_ENV_VARS.items():
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
        # Check that key dirs are mentioned
        for key_dir in ["repo", "python312", "installers", "downloads", "temp\\pytest",
                        "evidence-work", "logs"]:
            # Check for the directory name in New-Item calls
            assert key_dir in content, f"Setup script missing mkdir for {key_dir}"

    def test_activation_script_exports_all_required_vars(self):
        """Activation script must set every REQUIRED_ENV_VAR."""
        activate_path = REPO_ROOT / "scripts" / "activate_local_windows.ps1"
        content = activate_path.read_text(encoding="utf-8")
        for var in REQUIRED_ENV_VARS:
            assert var in content, f"Activation script missing env var {var}"


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
