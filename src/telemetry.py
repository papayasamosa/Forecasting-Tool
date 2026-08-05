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
import uuid
from datetime import datetime, timezone
from pathlib import Path
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


def current_rss_mb() -> float:
    """Current resident set size of this process in MB (stdlib first).

    Reads ``VmRSS`` from ``/proc/self/status`` (available on Linux — the
    Streamlit Community Cloud runtime), falling back to the psutil-based
    ``rss_mb()`` when ``/proc`` is unavailable. Never raises; returns 0.0
    when the value cannot be determined.
    """
    try:
        with open("/proc/self/status", encoding="utf-8") as fh:
            for line in fh:
                if line.startswith("VmRSS:"):
                    return float(line.split()[1]) / 1024.0
    except Exception:
        pass
    return rss_mb()


def process_peak_rss_mb() -> float:
    """Peak resident set size of this process in MB (stdlib only).

    Uses ``resource.getrusage(RUSAGE_SELF).ru_maxrss`` — the process
    high-water mark — which needs no third-party dependency and works on
    the Linux Cloud runtime. Units differ by platform (KiB on Linux, bytes
    on macOS). Never raises; returns 0.0 when unavailable (e.g. Windows).
    """
    try:
        import resource
        peak = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss
        if sys.platform == "darwin":
            return peak / (1024.0 * 1024.0)
        return peak / 1024.0
    except Exception:
        return 0.0


def _resolve_git_head_sha(repo_root: Path) -> str:
    """Resolve the commit SHA at ``repo_root/.git/HEAD`` via file reads only.

    Fast and dependency-free (no subprocess), so it is safe to call on
    every render. Returns "" when the checkout has no resolvable HEAD.
    """
    try:
        head_file = repo_root / ".git" / "HEAD"
        if head_file.exists():
            ref = head_file.read_text(encoding="utf-8").strip()
            if ref.startswith("ref:"):
                ref_path = repo_root / ".git" / ref[len("ref:"):].strip()
                if ref_path.exists():
                    return ref_path.read_text(encoding="utf-8").strip()[:40]
                return ref
            return ref[:40]
    except Exception:
        pass
    return ""


def deployed_commit() -> str:
    """Best-effort SHA of the checkout the running code was deployed from.

    Resolution order (never raises; returns "" when undetermined):
    1. Explicit env override: ``DEPLOYED_COMMIT``, ``COMMIT_SHA``, ``GIT_SHA``.
    2. ``.git/HEAD`` ref resolution relative to this module — pure file
       reads, fast, and works on runtimes (e.g. Streamlit Community Cloud)
       that ship the git checkout, so it is safe to call on every render.
    3. ``capture_traceability()`` git subprocess as a last resort.
    """
    for key in ("DEPLOYED_COMMIT", "COMMIT_SHA", "GIT_SHA"):
        value = os.environ.get(key, "").strip()
        if value:
            return value
    module_dir = Path(os.path.dirname(os.path.abspath(__file__)))
    resolved = _resolve_git_head_sha(module_dir.parent)
    if resolved:
        return resolved
    return capture_traceability().get("code_commit", "")


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
# Execution wrapper (WP6) — captures real execution context for receipts
# ---------------------------------------------------------------------------


class ReceiptContext:
    """Context manager that captures real execution metadata for a receipt.

    Records:
    - Execution ID before process start
    - Start UTC before execution
    - Completion UTC after execution
    - Exit code
    - Exact Git commit before execution
    - Worktree state before execution
    - Model ID and revisions
    - Producer version

    Usage::

        with ReceiptContext() as ctx:
            # do work
            pass

        receipt_dict = ctx.build_receipt(
            output_component=component_dict,
            sanitised_command="...",
            environment_allowlist=["python", "os"],
        )
    """

    def __init__(self) -> None:
        self.execution_id: str = str(uuid.uuid4())
        self.started_at_utc: str = datetime.now(timezone.utc).isoformat()
        self.completed_at_utc: str = ""
        self.exit_code: int = -1
        self.trace: dict[str, Any] = {}

    def __enter__(self) -> ReceiptContext:
        self.trace = capture_traceability()
        self.started_at_utc = datetime.now(timezone.utc).isoformat()
        return self

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc_val: BaseException | None,
        exc_tb: Any,
    ) -> None:
        self.completed_at_utc = datetime.now(timezone.utc).isoformat()
        self.exit_code = 0 if exc_type is None else 1

    def build_receipt(
        self,
        output_component: dict[str, Any],
        sanitised_command: str,
        model_id: str = "",
        configured_revision: str = "",
        resolved_revision: str = "",
        environment_summary: str = "",
        attestation_type: str = "operator_attested",
        *,
        evidence_origin: str,
    ) -> dict[str, Any]:
        """Build an ExecutionReceipt dict with captured execution metadata.

        Parameters
        ----------
        output_component : dict
            The final published component data. Its canonical digest will
            be computed and stored in ``canonical_content_sha256``.
        sanitised_command : str
            The sanitised command string that produced the component.
        model_id : str
            Model identifier (e.g. ``amazon/chronos-2``).
        configured_revision : str
            Pinned model revision.
        resolved_revision : str
            Resolved model revision.
        environment_summary : str
            Summary of the execution environment.
        attestation_type : str
            ``github_attestation`` or ``operator_attested``.
        evidence_origin : str
            ``real_measurement`` or ``synthetic_fixture``.

        Returns
        -------
        dict
            The receipt dict.
        """
        from src.evidence_schemas import (
            ExecutionReceipt, canonical_evidence_sha256,
        )

        # Compute canonical content digest of the output component
        canonical_digest = canonical_evidence_sha256(output_component)

        receipt = ExecutionReceipt(
            execution_id=self.execution_id,
            attestation_type=attestation_type,
            code_commit=self.trace.get("code_commit", ""),
            producer_name="ReceiptContext.build_receipt",
            producer_version="1.0",
            git_worktree_clean=self.trace.get("git_worktree_clean", False),
            sanitised_command=sanitised_command,
            started_at_utc=self.started_at_utc,
            completed_at_utc=self.completed_at_utc,
            exit_code=self.exit_code,
            canonical_content_sha256=canonical_digest,
            model_id=model_id,
            configured_revision=configured_revision,
            resolved_revision=resolved_revision,
            environment_summary=environment_summary or f"python={sys.version.split()[0]} os={sys.platform}",
            evidence_origin=evidence_origin,
        )
        return receipt.to_dict()


def run_with_receipt(
    command: list[str],
    output_component_path: str,
    model_id: str = "",
    configured_revision: str = "",
    resolved_revision: str = "",
    attestation_type: str = "operator_attested",
    *,
    evidence_origin: str,
    cwd: str | None = None,
) -> tuple[int, dict[str, Any]]:
    """Run a subprocess command and capture execution metadata for a receipt.

    This is the WP6 execution wrapper: it captures real start/end times,
    exit code, Git state, model identity, and component digests.

    Parameters
    ----------
    command : list[str]
        The command to run (as a list of arguments).
    output_component_path : str
        Path where the output component JSON will be written.
    model_id : str
        Model identifier.
    configured_revision : str
        Pinned model revision.
    resolved_revision : str
        Resolved model revision.
    attestation_type : str
        Attestation type.
    evidence_origin : str
        Evidence origin.
    cwd : str or None
        Working directory for the subprocess.

    Returns
    -------
    tuple[int, dict]
        (exit_code, receipt_dict)
    """
    now = datetime.now(timezone.utc)
    execution_id = str(uuid.uuid4())
    trace = capture_traceability()

    # Run the command
    try:
        result = subprocess.run(
            command,
            capture_output=True, text=True, timeout=3600,
            cwd=cwd,
        )
        exit_code = result.returncode
    except subprocess.TimeoutExpired:
        exit_code = -1
    except Exception:
        exit_code = 1

    completed = datetime.now(timezone.utc)

    # Load output component and compute canonical digest
    from src.evidence_schemas import (
        ExecutionReceipt, canonical_evidence_sha256,
    )
    try:
        with open(output_component_path, encoding="utf-8") as f:
            import json
            component_data = json.load(f)
        canonical_digest = canonical_evidence_sha256(component_data)
    except Exception:
        canonical_digest = ""

    # Build receipt
    from src.redaction import sanitise_command
    receipt = ExecutionReceipt(
        execution_id=execution_id,
        attestation_type=attestation_type,
        code_commit=trace.get("code_commit", ""),
        producer_name="run_with_receipt",
        producer_version="1.0",
        git_worktree_clean=trace.get("git_worktree_clean", False),
        sanitised_command=sanitise_command(command),
        started_at_utc=now.isoformat(),
        completed_at_utc=completed.isoformat(),
        exit_code=exit_code,
        canonical_content_sha256=canonical_digest,
        model_id=model_id,
        configured_revision=configured_revision,
        resolved_revision=resolved_revision,
        environment_summary=f"python={sys.version.split()[0]} os={sys.platform}",
        evidence_origin=evidence_origin,
    )

    return exit_code, receipt.to_dict()


# ---------------------------------------------------------------------------
# Receipt writer (legacy — use ReceiptContext or run_with_receipt for new code)
# ---------------------------------------------------------------------------


def write_execution_receipt(
    component_path: str,
    sanitised_command: str,
    model_id: str = "",
    configured_revision: str = "",
    resolved_revision: str = "",
    evidence_dir: str = "",
    attestation_type: str = "operator_attested",
    *,
    evidence_origin: str,
) -> dict[str, Any]:
    """Write an ``ExecutionReceipt`` for a completed component file.

    Parameters
    ----------
    component_path : str
        Path to the final component evidence file.
    sanitised_command : str
        The command that produced the component.
    model_id : str
        Model identifier (e.g. ``amazon/chronos-2``).
    configured_revision : str
        Pinned model revision.
    resolved_revision : str
        Resolved model revision.
    evidence_dir : str
        Directory for the receipt JSON output.
    attestation_type : str
        ``github_attestation`` or ``operator_attested``.
    evidence_origin : str
        ``real_measurement`` or ``synthetic_fixture``. Never defaulted.

    Returns
    -------
    dict
        The receipt dict, also written to ``<evidence_dir>/<prefix>_receipt.json``.
    """
    from src.evidence_schemas import ExecutionReceipt, canonical_evidence_sha256
    import hashlib

    # Compute component SHA-256 (transport hash)
    component_sha256 = ""
    try:
        h = hashlib.sha256()
        with open(component_path, "rb") as f:
            for chunk in iter(lambda: f.read(65536), b""):
                h.update(chunk)
        component_sha256 = h.hexdigest()
    except OSError:
        component_sha256 = ""

    # Compute canonical content digest from the component JSON
    canonical_digest = ""
    try:
        with open(component_path, encoding="utf-8") as f:
            import json
            component_data = json.load(f)
        if isinstance(component_data, dict):
            canonical_digest = canonical_evidence_sha256(component_data)
    except Exception:
        canonical_digest = ""

    # Capture traceability
    trace = capture_traceability()

    started = datetime.now(timezone.utc)
    receipt = ExecutionReceipt(
        execution_id=str(uuid.uuid4()),
        attestation_type=attestation_type,
        code_commit=trace.get("code_commit", ""),
        producer_name="write_execution_receipt",
        producer_version="1.0",
        git_worktree_clean=trace.get("git_worktree_clean", False),
        sanitised_command=sanitised_command,
        started_at_utc=started.isoformat(),
        completed_at_utc=started.isoformat(),
        exit_code=0,
        component_sha256=component_sha256,
        source_file_sha256=component_sha256,
        canonical_content_sha256=canonical_digest,
        evidence_origin=evidence_origin,
        model_id=model_id,
        configured_revision=configured_revision,
        resolved_revision=resolved_revision,
        environment_summary=f"python={sys.version.split()[0]} os={sys.platform}",
        immutable_artifact_reference="",
    )

    receipt_dict = receipt.to_dict()
    if evidence_dir:
        receipt_path = write_evidence(
            receipt_dict, evidence_dir, prefix=f"{Path(component_path).stem}_receipt"
        )
        receipt_dict["evidence_path"] = receipt_path

    return receipt_dict


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


def build_cache_preflight(
    pre_run_inspection: dict[str, Any],
    post_run_inspection: dict[str, Any],
    initial_cache_state: str,
) -> dict[str, Any]:
    """Build a ``CachePreflight`` dict from pre/post cache inspections.

    Parameters
    ----------
    pre_run_inspection : dict
        Result of ``inspect_hf_cache()`` before the run.
    post_run_inspection : dict
        Result of ``inspect_hf_cache()`` after the run.
    initial_cache_state : str
        One of ``download_cold`` or ``process_cold_cached_weights``.

    Returns
    -------
    dict
        A ``CachePreflight``-compatible dict with all required fields.
    """
    pre_succeeded = pre_run_inspection.get("inspection_succeeded", False)
    post_succeeded = post_run_inspection.get("inspection_succeeded", False)
    cache_source = pre_run_inspection.get("cache_source", "")

    # Require consistent cache source
    post_source = post_run_inspection.get("cache_source", "")
    if cache_source and post_source and cache_source != post_source:
        return {
            "inspection_succeeded": False,
            "cache_source": cache_source,
            "initial_cache_state": initial_cache_state,
            "snapshot_present": pre_run_inspection.get("snapshot_present", False),
            "file_count": pre_run_inspection.get("file_count", 0),
            "total_bytes": pre_run_inspection.get("total_bytes", 0),
            "post_run_snapshot_present": post_run_inspection.get("snapshot_present", False),
            "post_run_file_count": post_run_inspection.get("file_count", 0),
            "post_run_total_bytes": post_run_inspection.get("total_bytes", 0),
            "error": f"cache_source mismatch: pre='{cache_source}', post='{post_source}'",
        }

    return {
        "inspection_succeeded": pre_succeeded and post_succeeded,
        "cache_source": cache_source,
        "initial_cache_state": initial_cache_state,
        "snapshot_present": pre_run_inspection.get("snapshot_present", False),
        "file_count": pre_run_inspection.get("file_count", 0),
        "total_bytes": pre_run_inspection.get("total_bytes", 0),
        "post_run_snapshot_present": post_run_inspection.get("snapshot_present", False),
        "post_run_file_count": post_run_inspection.get("file_count", 0),
        "post_run_total_bytes": post_run_inspection.get("total_bytes", 0),
        "error": "",
    }


# ---------------------------------------------------------------------------
# Cache-state verification helpers (WP5)
# ---------------------------------------------------------------------------


def _resolve_hf_cache_dir(cache_dir: str | None = None) -> tuple[str, str]:
    """Resolve the Hugging Face Hub cache directory.

    Resolution order:
    1. Explicit ``cache_dir`` argument
    2. ``HF_HUB_CACHE`` environment variable
    3. ``huggingface_hub.constants.HF_HUB_CACHE`` (official constant)
    4. ``os.path.join(HF_HOME, "hub")`` if HF_HOME is set
    5. Documented fallback (platform default)

    Returns (resolved_path, cache_source) where cache_source is one of:
    "explicit", "env_HF_HUB_CACHE", "hf_hub_constant", "env_HF_HOME", "fallback"

    Never raises; returns safe defaults on failure.
    """
    # 1. Explicit argument
    if cache_dir:
        return cache_dir, "explicit"

    # 2. Environment variable
    env_cache = os.environ.get("HF_HUB_CACHE", "")
    if env_cache:
        return env_cache, "env_HF_HUB_CACHE"

    # 3. Official huggingface_hub constant
    try:
        from huggingface_hub.constants import HF_HUB_CACHE as _HF_HUB_CACHE
        if _HF_HUB_CACHE:
            return str(_HF_HUB_CACHE), "hf_hub_constant"
    except (ImportError, AttributeError):
        pass

    # 4. HF_HOME fallback
    hf_home = os.environ.get("HF_HOME", "")
    if hf_home:
        return os.path.join(hf_home, "hub"), "env_HF_HOME"

    # 5. Platform default fallback (never relative)
    if sys.platform == "win32":
        fallback = os.path.join(os.environ.get("USERPROFILE", ""), ".cache", "huggingface", "hub")
    else:
        fallback = os.path.join(os.path.expanduser("~"), ".cache", "huggingface", "hub")
    return fallback, "fallback"


def inspect_hf_cache(
    configured_revision: str,
    cache_dir: str | None = None,
) -> dict[str, Any]:
    """Inspect the Hugging Face Hub cache for a pinned revision.

    Parameters
    ----------
    configured_revision : str
        The pinned revision to look for in the cache.
    cache_dir : str or None
        Explicit cache directory. If None, resolved via
        ``_resolve_hf_cache_dir()``.

    Returns a dict with:
    - ``snapshot_present``: bool
    - ``file_count``: int
    - ``total_bytes``: int
    - ``cache_source``: str (safe enum, never a personal path)
    - ``error``: str or ""

    Never raises; returns safe defaults on failure.
    Does not return personal paths.
    """
    result: dict[str, Any] = {
        "inspection_succeeded": False,
        "snapshot_present": False,
        "file_count": 0,
        "total_bytes": 0,
        "cache_source": "",
        "error_code": "",
        "error": "",
    }
    try:
        from src.config import MODEL_ID
        hub_cache, cache_source = _resolve_hf_cache_dir(cache_dir)
        result["cache_source"] = cache_source
        if not hub_cache or not os.path.isdir(hub_cache):
            result["error"] = "HF_HUB_CACHE not found"
            result["error_code"] = "CACHE_DIR_NOT_FOUND"
            return result

        model_dir = os.path.join(
            hub_cache,
            f"models--{MODEL_ID.replace('/', '--')}",
            "snapshots",
            configured_revision,
        )
        if os.path.isdir(model_dir):
            result["snapshot_present"] = True
            result["inspection_succeeded"] = True
            total_bytes = 0
            file_count = 0
            for dirpath, _dirnames, filenames in os.walk(model_dir):
                for fname in filenames:
                    fpath = os.path.join(dirpath, fname)
                    try:
                        total_bytes += os.path.getsize(fpath)
                        file_count += 1
                    except OSError:
                        pass
            result["file_count"] = file_count
            result["total_bytes"] = total_bytes
        else:
            result["snapshot_present"] = False
            result["inspection_succeeded"] = True
            # Expected absence for download_cold is not a failure
            result["error_code"] = "SNAPSHOT_NOT_FOUND"
            result["error"] = f"snapshot for revision '{configured_revision}' not found"
    except Exception as exc:
        result["error"] = f"cache inspection failed: {exc}"
        result["error_code"] = "INSPECTION_FAILED"

    return result
