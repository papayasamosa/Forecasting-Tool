"""Telemetry helpers for benchmarking and smoke tests.

Reusable functions moved here from ``scripts/chronos2_smoke_test.py``,
``src/benchmarking.py`` and ``src/forecasting/chronos2_adapter.py`` so
they can be imported by both production and test code without duplication.
"""
from __future__ import annotations

import json
import os
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
