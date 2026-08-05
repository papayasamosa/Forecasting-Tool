"""WP9: behavioural coverage for src/telemetry.py failure paths — psutil
absence, subprocess exceptions/timeouts, git failures, cache-resolution
fallbacks, cache-inspection errors, and the receipt-writer OSError branch.
"""
from __future__ import annotations

import json
import os
import sys
import subprocess
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT))


class _FakeSys:
    """A sys-like object with an overridden ``platform`` that delegates
    every other attribute to the real ``sys`` module. Used instead of
    mutating the real sys.platform, which poisons sysconfig's cached
    config vars and breaks coverage on Linux runners."""

    def __init__(self, platform: str):
        self.platform = platform

    def __getattr__(self, name):
        return getattr(sys, name)


@pytest.fixture
def no_psutil(monkeypatch):
    """Make `import psutil` raise ImportError by blocking it in
    sys.modules (never patch builtins.__import__ — a global patch that can
    interfere with coverage's own imports on Linux runners)."""
    monkeypatch.setitem(sys.modules, "psutil", None)


class TestRssMemoryWithoutPsutil:
    def test_rss_mb_returns_zero_without_psutil(self, no_psutil):
        from src.telemetry import rss_mb
        assert rss_mb() == 0.0

    def test_memory_sampler_start_is_noop_without_psutil(self, no_psutil):
        from src.telemetry import MemorySampler
        sampler = MemorySampler()
        sampler.start()
        assert sampler.peak_mb == 0.0
        assert sampler.baseline_mb == 0.0
        sampler.stop()

    def test_cpu_info_returns_unknown_without_psutil(self, no_psutil):
        from src.telemetry import cpu_info
        assert cpu_info() == "unknown"


class TestCapturePackageVersionsFailures:
    def test_all_imports_failing_returns_unknown(self, monkeypatch):
        # Block the packages in sys.modules (never patch __import__).
        for mod in ("chronos", "torch", "pandas", "numpy", "streamlit"):
            monkeypatch.setitem(sys.modules, mod, None)
        from src.telemetry import capture_package_versions
        versions = capture_package_versions()
        for key in ("chronos-forecasting", "torch", "pandas", "numpy", "streamlit"):
            assert versions[key] == "unknown"
        assert versions["python"]


class TestRunWithReceiptFailurePaths:
    def test_subprocess_oserror_yields_exit_code_1(self, tmp_path, monkeypatch):
        from src.telemetry import run_with_receipt

        def boom(*args, **kwargs):
            raise OSError("no such executable")

        monkeypatch.setattr(subprocess, "run", boom)
        out_path = str(tmp_path / "out.json")
        exit_code, receipt = run_with_receipt(
            command=[sys.executable, "-c", "pass"],
            output_component_path=out_path,
            evidence_origin="real_measurement",
        )
        assert exit_code == 1
        assert receipt["exit_code"] == 1

    def test_subprocess_timeout_yields_exit_code_minus_1(self, tmp_path, monkeypatch):
        from src.telemetry import run_with_receipt

        def timeout(*args, **kwargs):
            raise subprocess.TimeoutExpired("cmd", 3600)

        monkeypatch.setattr(subprocess, "run", timeout)
        out_path = str(tmp_path / "out.json")
        exit_code, receipt = run_with_receipt(
            command=[sys.executable, "-c", "pass"],
            output_component_path=out_path,
            evidence_origin="real_measurement",
        )
        assert exit_code == -1
        assert receipt["exit_code"] == -1

    def test_missing_output_component_yields_empty_digest(self, tmp_path):
        from src.telemetry import run_with_receipt
        out_path = str(tmp_path / "does_not_exist.json")
        exit_code, receipt = run_with_receipt(
            command=[sys.executable, "-c", "pass"],
            output_component_path=out_path,
            evidence_origin="real_measurement",
        )
        assert exit_code == 0
        assert receipt["canonical_content_sha256"] == ""


class TestFindRepoRoot:
    def test_returns_none_when_no_git_and_no_dotgit(self, tmp_path, monkeypatch):
        from src.telemetry import _find_repo_root

        def git_fails(*args, **kwargs):
            return subprocess.CompletedProcess(args[0], 1, stdout="", stderr="")

        monkeypatch.setattr(subprocess, "run", git_fails)
        empty_dir = tmp_path / "no_git_here"
        empty_dir.mkdir()
        assert _find_repo_root(str(empty_dir)) is None

    def test_falls_back_to_dotgit_climb(self, tmp_path, monkeypatch):
        from src.telemetry import _find_repo_root

        def git_fails(*args, **kwargs):
            return subprocess.CompletedProcess(args[0], 1, stdout="", stderr="")

        monkeypatch.setattr(subprocess, "run", git_fails)
        repo = tmp_path / "repo"
        (repo / ".git").mkdir(parents=True)
        nested = repo / "a" / "b"
        nested.mkdir(parents=True)
        assert _find_repo_root(str(nested)) == str(repo)

    def test_uses_git_toplevel_when_available(self, tmp_path, monkeypatch):
        from src.telemetry import _find_repo_root
        repo = tmp_path / "repo"
        (repo / ".git").mkdir(parents=True)

        def git_ok(*args, **kwargs):
            return subprocess.CompletedProcess(args[0], 0, stdout=str(repo) + "\n", stderr="")

        monkeypatch.setattr(subprocess, "run", git_ok)
        assert _find_repo_root(str(repo)) == str(repo)


class TestCaptureTraceabilityFailures:
    def test_git_commands_failing_sets_error(self, monkeypatch):
        from src.telemetry import capture_traceability

        def git_raises(*args, **kwargs):
            raise OSError("git unavailable")

        monkeypatch.setattr(subprocess, "run", git_raises)
        result = capture_traceability()
        assert result["code_commit"] == ""
        assert result["git_worktree_clean"] is False
        assert result["git_traceability_error"]

    def test_repo_root_not_found(self, tmp_path, monkeypatch):
        from src.telemetry import capture_traceability
        # Force _find_repo_root to return None by monkeypatching subprocess
        # to fail and pointing it at a .git-free directory.
        def git_fails(*args, **kwargs):
            return subprocess.CompletedProcess(args[0], 1, stdout="", stderr="")

        monkeypatch.setattr(subprocess, "run", git_fails)
        monkeypatch.setattr("src.telemetry._find_repo_root", lambda *a, **k: None)
        result = capture_traceability()
        assert result["git_traceability_error"] == "repo_root_not_found"


class TestMachineSummaryFailures:
    def test_without_psutil_returns_zero_metrics(self, no_psutil):
        from src.telemetry import machine_summary
        result = machine_summary()
        assert result.get("cpu_logical_cores") == 0
        assert result.get("ram_total_gb") == 0.0

    def test_darwin_platform_uses_platform_processor(self, monkeypatch, no_psutil):
        from src.telemetry import machine_summary
        import platform as _platform
        monkeypatch.setattr(_platform, "processor", lambda: "Apple M1")
        # Replace src.telemetry.sys with a delegating fake so the REAL sys
        # module is never mutated (patching sys.platform poisons sysconfig's
        # cached vars, breaking coverage on Linux runners).
        monkeypatch.setattr("src.telemetry.sys", _FakeSys(platform="darwin"))
        result = machine_summary()
        assert result.get("cpu_model") == "Apple M1"

    def test_cpu_model_windows_fallback_empty(self, monkeypatch):
        from src.telemetry import _cpu_model_windows
        import platform as _platform
        monkeypatch.delenv("PROCESSOR_IDENTIFIER", raising=False)
        monkeypatch.setattr(_platform, "processor", lambda: "")
        assert _cpu_model_windows() == ""

    def test_cpu_model_linux_missing_proc(self, monkeypatch):
        from src.telemetry import _cpu_model_linux
        import builtins
        real_open = builtins.open

        def no_open(path, *args, **kwargs):
            if str(path).startswith("/proc/cpuinfo"):
                raise FileNotFoundError(path)
            return real_open(path, *args, **kwargs)

        monkeypatch.setattr(builtins, "open", no_open)
        assert _cpu_model_linux() == ""


class TestBuildCachePreflightMismatch:
    def test_cache_source_mismatch_rejected(self):
        from src.telemetry import build_cache_preflight
        pre = {"inspection_succeeded": True, "cache_source": "explicit",
               "snapshot_present": False, "file_count": 0, "total_bytes": 0}
        post = {"inspection_succeeded": True, "cache_source": "env_HF_HUB_CACHE",
                "snapshot_present": True, "file_count": 5, "total_bytes": 100}
        result = build_cache_preflight(pre, post, "download_cold")
        assert result["inspection_succeeded"] is False
        assert "mismatch" in result["error"]


class TestResolveHfCacheDir:
    def test_explicit_wins(self):
        from src.telemetry import _resolve_hf_cache_dir
        path, source = _resolve_hf_cache_dir("C:/custom/cache")
        assert path == "C:/custom/cache"
        assert source == "explicit"

    def test_env_var(self, monkeypatch):
        from src.telemetry import _resolve_hf_cache_dir
        monkeypatch.setenv("HF_HUB_CACHE", "D:/cache/hf")
        path, source = _resolve_hf_cache_dir()
        assert path == "D:/cache/hf"
        assert source == "env_HF_HUB_CACHE"

    def test_hf_home_fallback(self, monkeypatch):
        from src.telemetry import _resolve_hf_cache_dir
        monkeypatch.delenv("HF_HUB_CACHE", raising=False)
        monkeypatch.setenv("HF_HOME", "D:/hfhome")
        monkeypatch.setattr("src.telemetry.sys", _FakeSys(platform="linux"))
        # Block huggingface_hub in sys.modules (never patch __import__).
        monkeypatch.setitem(sys.modules, "huggingface_hub", None)
        monkeypatch.setitem(sys.modules, "huggingface_hub.constants", None)
        path, source = _resolve_hf_cache_dir()
        assert source == "env_HF_HOME"
        assert path == os.path.join("D:/hfhome", "hub")

    def test_platform_fallback_linux(self, monkeypatch):
        from src.telemetry import _resolve_hf_cache_dir
        monkeypatch.delenv("HF_HUB_CACHE", raising=False)
        monkeypatch.delenv("HF_HOME", raising=False)
        monkeypatch.setattr("src.telemetry.sys", _FakeSys(platform="linux"))
        monkeypatch.setitem(sys.modules, "huggingface_hub", None)
        monkeypatch.setitem(sys.modules, "huggingface_hub.constants", None)
        path, source = _resolve_hf_cache_dir()
        assert source == "fallback"
        assert path.endswith(os.path.join(".cache", "huggingface", "hub"))

    def test_platform_fallback_windows(self, monkeypatch):
        from src.telemetry import _resolve_hf_cache_dir
        monkeypatch.delenv("HF_HUB_CACHE", raising=False)
        monkeypatch.delenv("HF_HOME", raising=False)
        monkeypatch.setattr("src.telemetry.sys", _FakeSys(platform="win32"))
        monkeypatch.setenv("USERPROFILE", "C:/Users/test")
        monkeypatch.setitem(sys.modules, "huggingface_hub", None)
        monkeypatch.setitem(sys.modules, "huggingface_hub.constants", None)
        path, source = _resolve_hf_cache_dir()
        assert source == "fallback"
        assert path.startswith("C:/Users/test")


class TestInspectHfCache:
    def test_cache_dir_not_found(self, tmp_path):
        from src.telemetry import inspect_hf_cache
        result = inspect_hf_cache("rev1", cache_dir=str(tmp_path / "missing"))
        assert result["inspection_succeeded"] is False
        assert result["error_code"] == "CACHE_DIR_NOT_FOUND"

    def test_snapshot_not_found(self, tmp_path):
        from src.telemetry import inspect_hf_cache
        cache = tmp_path / "hub"
        cache.mkdir()
        result = inspect_hf_cache("rev1", cache_dir=str(cache))
        assert result["inspection_succeeded"] is True
        assert result["snapshot_present"] is False
        assert result["error_code"] == "SNAPSHOT_NOT_FOUND"

    def test_snapshot_present_counts_files(self, tmp_path):
        from src.telemetry import inspect_hf_cache
        from src.config import MODEL_ID
        model_dir = tmp_path / "hub" / f"models--{MODEL_ID.replace('/', '--')}" / "snapshots" / "rev1"
        model_dir.mkdir(parents=True)
        (model_dir / "a.safetensors").write_bytes(b"x" * 100)
        (model_dir / "b.safetensors").write_bytes(b"y" * 200)
        result = inspect_hf_cache("rev1", cache_dir=str(tmp_path / "hub"))
        assert result["snapshot_present"] is True
        assert result["inspection_succeeded"] is True
        assert result["file_count"] == 2
        assert result["total_bytes"] == 300

    def test_inspection_exception_sets_error(self, tmp_path, monkeypatch):
        from src.telemetry import inspect_hf_cache
        monkeypatch.setattr("src.telemetry._resolve_hf_cache_dir",
                            lambda *a, **k: (_ for _ in ()).throw(RuntimeError("boom")))
        result = inspect_hf_cache("rev1", cache_dir="")
        assert result["error_code"] == "INSPECTION_FAILED"
        assert "boom" in result["error"]


class TestWriteExecutionReceiptFailures:
    def test_missing_component_yields_empty_hashes(self, tmp_path):
        from src.telemetry import write_execution_receipt
        receipt = write_execution_receipt(
            str(tmp_path / "missing.json"),
            "python x.py",
            evidence_origin="real_measurement",
        )
        assert receipt["component_sha256"] == ""
        assert receipt["canonical_content_sha256"] == ""

    def test_writes_receipt_file_when_evidence_dir_given(self, tmp_path):
        from src.telemetry import write_execution_receipt
        comp = tmp_path / "comp.json"
        comp.write_text(json.dumps({"evidence_type": "smoke_test", "success": True}), encoding="utf-8")
        evdir = tmp_path / "evidence"
        receipt = write_execution_receipt(
            str(comp), "python x.py",
            evidence_origin="real_measurement",
            evidence_dir=str(evdir),
        )
        assert receipt["component_sha256"]
        assert receipt["evidence_path"]
        assert Path(receipt["evidence_path"]).exists()
