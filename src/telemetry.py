"""Telemetry helpers for benchmarking and smoke tests.

Reusable functions moved here from ``scripts/chronos2_smoke_test.py``,
``src/benchmarking.py`` and ``src/forecasting/chronos2_adapter.py`` so
they can be imported by both production and test code without duplication.
"""
from __future__ import annotations

import json
import os
import subprocess
import sys
import time
import threading
from datetime import datetime, timezone
from typing import Any


# ---------------------------------------------------------------------------
# Memory sampling
# ---------------------------------------------------------------------------


def rss_mb() -> float:
    """Approximate current process RSS in MB."""
    try:
        import psutil
        return psutil.Process().memory_info().rss / 1024 / 1024
    except ImportError:
        return 0.0


class MemorySampler:
    """Samples process RSS in a background thread to approximate peak memory."""

    def __init__(self, interval: float = 0.05):
        self._interval = interval
        self._peak_mb: float = 0.0
        self._baseline_mb: float = 0.0
        self._running = False
        self._thread: threading.Thread | None = None
        self._imported_psutil = False
        self._process = None
        try:
            import psutil
            self._process = psutil.Process()
            self._imported_psutil = True
        except ImportError:
            pass

    def start(self) -> None:
        if not self._imported_psutil:
            return
        self._baseline_mb = self._process.memory_info().rss / 1024 / 1024  # type: ignore[union-attr]
        self._peak_mb = self._baseline_mb
        self._running = True
        self._thread = threading.Thread(target=self._sample, daemon=True)
        self._thread.start()

    def _sample(self) -> None:
        while self._running:
            try:
                rss = self._process.memory_info().rss / 1024 / 1024  # type: ignore[union-attr]
                if rss > self._peak_mb:
                    self._peak_mb = rss
            except Exception:
                pass
            time.sleep(self._interval)

    def stop(self) -> None:
        self._running = False
        if self._thread:
            self._thread.join(timeout=2)

    @property
    def peak_mb(self) -> float:
        return self._peak_mb

    @property
    def baseline_mb(self) -> float:
        return self._baseline_mb


# ---------------------------------------------------------------------------
# Package versions
# ---------------------------------------------------------------------------


def capture_package_versions() -> dict[str, str]:
    """Return a dict of relevant package versions for run metadata."""
    versions: dict[str, str] = {}
    try:
        import chronos as _c
        versions["chronos-forecasting"] = getattr(_c, "__version__", "unknown")
    except ImportError:
        versions["chronos-forecasting"] = "unknown"
    try:
        import torch as _t
        versions["torch"] = _t.__version__
    except ImportError:
        versions["torch"] = "unknown"
    try:
        import pandas as _pd
        versions["pandas"] = _pd.__version__
    except ImportError:
        versions["pandas"] = "unknown"
    try:
        import numpy as _np
        versions["numpy"] = _np.__version__
    except ImportError:
        versions["numpy"] = "unknown"
    try:
        import streamlit as _st
        versions["streamlit"] = _st.__version__
    except ImportError:
        versions["streamlit"] = "unknown"
    versions["python"] = sys.version.split()[0]
    return versions


# ---------------------------------------------------------------------------
# CPU info
# ---------------------------------------------------------------------------


def cpu_info() -> str:
    try:
        import psutil
        return f"{psutil.cpu_count()} logical cores"
    except ImportError:
        return "unknown"


# ---------------------------------------------------------------------------
# Evidence writing
# ---------------------------------------------------------------------------


def write_evidence(
    evidence: dict,
    evidence_dir: str,
    prefix: str = "evidence",
) -> str:
    """Write evidence dict to a timestamped JSON file and return the path.

    Parameters
    ----------
    evidence : dict
        JSON-serialisable dict.
    evidence_dir : str
        Directory to write into (created if missing).
    prefix : str
        File name prefix (e.g. "smoke_test", "benchmark").

    Returns
    -------
    str
        Absolute path to the written file.
    """
    os.makedirs(evidence_dir, exist_ok=True)
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    path = os.path.join(evidence_dir, f"{prefix}_{timestamp}.json")
    with open(path, "w", encoding="utf-8") as f:
        json.dump(evidence, f, indent=2, default=str)
    return path


# ---------------------------------------------------------------------------
# Traceability helpers (WP6: evidence reproducibility)
# ---------------------------------------------------------------------------


def _find_repo_root(path: str | None = None) -> str | None:
    """Determine the repository root directory from a starting path.

    Uses ``git rev-parse --show-toplevel`` if Git is available, falling
    back to climbing up from the caller's location looking for a ``.git``
    directory. Returns ``None`` if no repository root can be found.
    """
    try:
        cwd = path or os.path.dirname(os.path.abspath(__file__))
        out = subprocess.run(
            ["git", "rev-parse", "--show-toplevel"],
            capture_output=True, text=True, timeout=10, cwd=cwd,
        )
        if out.returncode == 0:
            root = out.stdout.strip()
            if root:
                return root
    except Exception:
        pass
    # Fallback: climb up from the script location
    try:
        cwd = path or os.path.dirname(os.path.abspath(__file__))
        while True:
            if os.path.isdir(os.path.join(cwd, ".git")):
                return cwd
            parent = os.path.dirname(cwd)
            if parent == cwd:
                return None
            cwd = parent
    except Exception:
        return None


def capture_traceability() -> dict[str, Any]:
    """Return Git commit, worktree status, and evidence schema version.

    Determines the repository root explicitly and runs all Git commands
    with ``cwd`` set to that root. Requires return code zero from each
    command.

    Never raises; returns safe defaults on failure.
    """
    result: dict[str, Any] = {
        "code_commit": "",
        "git_worktree_clean": False,
        "git_traceability_error": "",
    }

    repo_root = _find_repo_root()
    if repo_root is None:
        result["git_traceability_error"] = "repo_root_not_found"
        return result

    try:
        out = subprocess.run(
            ["git", "rev-parse", "HEAD"],
            capture_output=True, text=True, timeout=10, cwd=repo_root,
        )
        if out.returncode == 0:
            result["code_commit"] = out.stdout.strip()
        else:
            result["git_traceability_error"] = "git_rev_parse_failed"
            result["code_commit"] = ""
    except Exception as exc:
        result["git_traceability_error"] = f"git_rev_parse_error: {exc}"
        result["code_commit"] = ""

    try:
        out = subprocess.run(
            ["git", "status", "--porcelain"],
            capture_output=True, text=True, timeout=10, cwd=repo_root,
        )
        if out.returncode == 0:
            result["git_worktree_clean"] = out.stdout.strip() == ""
        else:
            result["git_traceability_error"] = (
                result.get("git_traceability_error") or ""
            ) + "; git_status_failed"
            result["git_worktree_clean"] = False
    except Exception as exc:
        result["git_traceability_error"] = (
            result.get("git_traceability_error") or ""
        ) + f"; git_status_error: {exc}"
        result["git_worktree_clean"] = False

    # code_commit empty implies not clean (safety invariant)
    if not result["code_commit"]:
        result["git_worktree_clean"] = False
        if not result["git_traceability_error"]:
            result["git_traceability_error"] = "code_commit_empty"

    return result


def _cpu_model_windows() -> str:
    """Get CPU model on Windows using environment variables.

    Falls back to ``platform.processor()``. Never raises.
    """
    try:
        # Windows environment variable set by the OS
        proc_id = os.environ.get("PROCESSOR_IDENTIFIER", "")
        if proc_id:
            return proc_id.strip()
        import platform
        proc = platform.processor()
        if proc:
            return proc.strip()
    except Exception:
        pass
    return ""


def _cpu_model_linux() -> str:
    """Get CPU model on Linux via /proc/cpuinfo."""
    try:
        with open("/proc/cpuinfo") as f:
            for line in f:
                if line.startswith("model name"):
                    return line.split(":", 1)[1].strip()
    except Exception:
        pass
    return ""


def machine_summary() -> dict[str, Any]:
    """Return CPU model, logical core count, and total RAM.

    Platform-aware CPU model detection. Never raises; returns empty
    strings on failure. Does not include hostnames, usernames, or
    serial numbers.
    """
    result: dict[str, Any] = {}
    try:
        import psutil
        result["cpu_logical_cores"] = psutil.cpu_count(logical=True)
        result["ram_total_gb"] = round(psutil.virtual_memory().total / (1024**3), 1)
    except ImportError:
        result["cpu_logical_cores"] = 0
        result["ram_total_gb"] = 0.0

    try:
        if sys.platform == "win32":
            result["cpu_model"] = _cpu_model_windows()
        elif sys.platform == "linux":
            result["cpu_model"] = _cpu_model_linux()
        else:
            import platform
            result["cpu_model"] = platform.processor() or ""
    except Exception:
        result["cpu_model"] = ""

    return result
