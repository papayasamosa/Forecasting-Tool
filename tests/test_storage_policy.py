"""Tests for the shared D-drive storage policy module (WP12)."""
from __future__ import annotations

import os
import sys
from pathlib import Path

import pytest

from src.storage_policy import (
    LOCAL_ROOT,
    REQUIRED_DIRS,
    REQUIRED_ENV_VARS,
    is_valid_storage_root,
    is_under_local_root,
    assert_d_drive_preflight,
)


class TestStoragePolicy:
    def test_local_root_is_d_drive(self):
        assert LOCAL_ROOT.startswith("D:\\")

    def test_required_dirs_all_under_local_root(self):
        for d in REQUIRED_DIRS:
            assert d.startswith(LOCAL_ROOT), f"{d} not under {LOCAL_ROOT}"

    def test_required_env_vars_all_under_local_root(self):
        for var, val in REQUIRED_ENV_VARS.items():
            assert val.startswith(LOCAL_ROOT), f"{var}={val} not under {LOCAL_ROOT}"

    # ── D-drive validation tests (Windows-only logic) ─────────────────

    def test_is_valid_storage_root_accepts_d_local_root(self):
        assert is_valid_storage_root(LOCAL_ROOT) is True

    def test_is_valid_storage_root_accepts_d_local_root_descendant(self):
        assert is_valid_storage_root(r"D:\Forecasting-Tool-Local\venv") is True

    def test_is_valid_storage_root_rejects_c_drive(self):
        assert is_valid_storage_root(r"C:\Forecasting-Tool-Local") is False

    def test_is_valid_storage_root_rejects_other_drive(self):
        assert is_valid_storage_root(r"E:\Forecasting-Tool-Local") is False

    def test_is_valid_storage_root_rejects_unc_path(self):
        assert is_valid_storage_root(r"\\server\share\Forecasting-Tool-Local") is False

    def test_is_valid_storage_root_rejects_relative_path(self):
        assert is_valid_storage_root("relative\\path") is False

    def test_is_valid_storage_root_rejects_empty(self):
        assert is_valid_storage_root("") is False

    def test_is_under_local_root_accepts_root(self):
        assert is_under_local_root(LOCAL_ROOT) is True

    def test_is_under_local_root_accepts_descendant(self):
        assert is_under_local_root(r"D:\Forecasting-Tool-Local\cache") is True

    def test_is_under_local_root_rejects_c_drive(self):
        assert is_under_local_root(r"C:\Windows") is False

    def test_is_under_local_root_rejects_d_other_path(self):
        assert is_under_local_root(r"D:\Other") is False

    def test_assert_d_drive_preflight_returns_list(self):
        """Preflight should return a list (possibly empty on Windows with D:)."""
        result = assert_d_drive_preflight()
        assert isinstance(result, list)
