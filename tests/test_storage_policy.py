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
    verify_ddrive_runtime,
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

    def test_is_under_local_root_case_insensitive_on_windows_paths(self):
        """Windows paths are case-insensitive — Path.resolve() may return
        lowercase while the constant is mixed-case; both must be accepted
        (regression: a case-sensitive startswith comparison rejected the
        real D:\\forecasting-tool-local\\repo during local verification)."""
        assert is_under_local_root(r"D:\forecasting-tool-local\repo") is True
        assert is_under_local_root(r"D:\FORECASTING-TOOL-LOCAL\cache") is True
        assert is_under_local_root(r"D:\Forecasting-Tool-Local\repo") is True

    def test_assert_d_drive_preflight_returns_list(self):
        """Preflight should return a list (possibly empty on Windows with D:)."""
        result = assert_d_drive_preflight()
        assert isinstance(result, list)


class TestVerifyDDdriveRuntime:
    """WP3: the venv must be based on the D-drive project Python. These
    tests monkeypatch the interpreter facts so they run on any platform
    (CI is Linux; the D-drive policy does not apply there but the failure
    branches are the same code paths)."""

    def _patch(self, monkeypatch, base_prefix, prefix, executable):
        import src.storage_policy as sp
        monkeypatch.setattr(sp.sys, "platform", "win32")
        monkeypatch.setattr(sp.sys, "base_prefix", base_prefix)
        monkeypatch.setattr(sp.sys, "prefix", prefix)
        monkeypatch.setattr(sp.sys, "executable", executable)
        return sp

    def _stub_cfg(self, monkeypatch, home):
        """Stub the module-level pyvenv.cfg reader — never patch the global
        builtins.open, which would corrupt coverage.py's own file reads on
        Linux runners (a real CI INTERNALERROR observed with coverage 7.15.3)."""
        import src.storage_policy as sp
        monkeypatch.setattr(sp, "_read_pyvenv_cfg_home", lambda prefix: home)

    def test_non_windows_returns_empty(self, monkeypatch):
        import src.storage_policy as sp
        monkeypatch.setattr(sp.sys, "platform", "linux")
        assert verify_ddrive_runtime() == []

    def test_d_drive_based_runtime_passes(self, monkeypatch):
        self._patch(monkeypatch,
                    base_prefix=r"D:\Forecasting-Tool-Local\python312",
                    prefix=r"D:\Forecasting-Tool-Local\venv",
                    executable=r"D:\Forecasting-Tool-Local\venv\Scripts\python.exe")
        self._stub_cfg(monkeypatch, r"D:\Forecasting-Tool-Local\python312")
        errors = verify_ddrive_runtime()
        assert errors == [], errors

    def test_c_drive_base_prefix_rejected(self, monkeypatch):
        self._patch(monkeypatch,
                    base_prefix=r"C:\Users\dev\AppData\Local\Programs\Python\Python312",
                    prefix=r"D:\Forecasting-Tool-Local\venv",
                    executable=r"D:\Forecasting-Tool-Local\venv\Scripts\python.exe")
        self._stub_cfg(monkeypatch, r"C:\Users\dev\AppData\Local\Programs\Python\Python312")
        errors = verify_ddrive_runtime()
        assert any("sys.base_prefix" in e for e in errors), errors
        assert any("D:\\Forecasting-Tool-Local" in e for e in errors), errors

    def test_wrong_executable_rejected(self, monkeypatch):
        self._patch(monkeypatch,
                    base_prefix=r"D:\Forecasting-Tool-Local\python312",
                    prefix=r"D:\Forecasting-Tool-Local\venv",
                    executable=r"C:\Python312\python.exe")
        self._stub_cfg(monkeypatch, r"D:\Forecasting-Tool-Local\python312")
        errors = verify_ddrive_runtime()
        assert any("Active interpreter" in e for e in errors), errors

    def test_prefix_outside_local_root_rejected(self, monkeypatch):
        self._patch(monkeypatch,
                    base_prefix=r"D:\Forecasting-Tool-Local\python312",
                    prefix=r"C:\SomewhereElse\venv",
                    executable=r"D:\Forecasting-Tool-Local\venv\Scripts\python.exe")
        self._stub_cfg(monkeypatch, r"D:\Forecasting-Tool-Local\python312")
        errors = verify_ddrive_runtime()
        assert any("sys.prefix" in e for e in errors), errors

    def test_pyvenv_cfg_home_outside_d_rejected(self, monkeypatch):
        self._patch(monkeypatch,
                    base_prefix=r"D:\Forecasting-Tool-Local\python312",
                    prefix=r"D:\Forecasting-Tool-Local\venv",
                    executable=r"D:\Forecasting-Tool-Local\venv\Scripts\python.exe")
        self._stub_cfg(monkeypatch, r"C:\Python312")
        errors = verify_ddrive_runtime()
        assert any("pyvenv.cfg home" in e for e in errors), errors

    def test_pyvenv_cfg_reader_reads_home_line(self, tmp_path):
        """The real _read_pyvenv_cfg_home helper parses the home line and
        tolerates missing/unreadable files without raising."""
        from src.storage_policy import _read_pyvenv_cfg_home
        venv = tmp_path / "venv"
        venv.mkdir()
        (venv / "pyvenv.cfg").write_text(
            "home = D:\\Forecasting-Tool-Local\\python312\n"
            "version = 3.12.10\n",
            encoding="utf-8",
        )
        assert _read_pyvenv_cfg_home(str(venv)) == r"D:\Forecasting-Tool-Local\python312"
        # Missing pyvenv.cfg -> ""
        assert _read_pyvenv_cfg_home(str(tmp_path / "nope")) == ""
