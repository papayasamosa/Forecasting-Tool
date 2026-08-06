"""Typed, deterministic, safe Cloud diagnostics and evidence-export support.

Stage 1 Cloud evidence instrumentation.  This module is the *producer* side
of Cloud Gate C: it turns genuine runtime measurements inside a deployed
Streamlit Community Cloud process into typed, allowlisted records that can
be exported as release evidence.  It deliberately does **not**:

- read or expose ``HF_TOKEN`` (only a boolean ``hf_token_present``)
- dump arbitrary environment variables
- include filesystem paths, hostnames, usernames, cookies, headers,
  uploaded payloads, target values, or forecast values
- fabricate measurements (a value that cannot be measured is a validation
  error, never a silently written zero)
- reuse the process-lifetime peak RSS as every request's peak

Design notes
------------
- ``deployed_commit`` is resolved **strictly**: exactly 40 lowercase
  hexadecimal characters, with the resolution source recorded
  (``explicit_verified_override`` / ``git_head`` /
  ``platform_commit_metadata``).  Short SHAs, arbitrary text,
  ``not available``, and empty values are rejected.
- ``RequestMemorySampler`` is stdlib-only (``/proc/self/status`` +
  ``resource.getrusage``), so it works on the Community Cloud runtime
  where ``psutil`` is not installed (it is a dev-only dependency).
- ``RequestTelemetryStore`` is a process-wide bounded, thread-safe store.
- ``CloudCollectionSessionRecord`` binds every collected request ID,
  token-path execution ID, repeated-run ID, concurrency request ID and
  timeout/recovery ID together with the canonical digest of the runtime
  diagnostics; ``build_collection_receipt`` binds the canonical digest of
  that session record.  The session record never contains its own receipt.
"""
from __future__ import annotations

import collections
import dataclasses
import json
import math
import os
import re
import sys
import threading
import time
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from src.config import MODEL_ID, MODEL_REVISION
from src.evidence_schemas import (
    EVIDENCE_SCHEMA_VERSION,
    EVIDENCE_ORIGIN_REAL,
    ExecutionReceipt,
    canonical_evidence_sha256,
)
from src.redaction import contains_exposed_secret, sanitise_command
from src.telemetry import (
    _resolve_git_head_sha,
    capture_traceability,
    current_rss_mb,
    machine_summary,
    package_versions_metadata,
    process_peak_rss_mb,
)

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------
DIAGNOSTICS_SCHEMA_VERSION = "1"

# Exactly 40 lowercase hexadecimal characters.
_SHA40_RE = re.compile(r"^[0-9a-f]{40}$")

# Resolution sources for the deployed commit (WP3)
COMMIT_SOURCE_EXPLICIT = "explicit_verified_override"
COMMIT_SOURCE_GIT_HEAD = "git_head"
COMMIT_SOURCE_PLATFORM = "platform_commit_metadata"
COMMIT_SOURCE_UNRESOLVED = "unresolved"
VALID_COMMIT_SOURCES = {
    COMMIT_SOURCE_EXPLICIT,
    COMMIT_SOURCE_GIT_HEAD,
    COMMIT_SOURCE_PLATFORM,
}

# Mandatory package versions that must never be "unknown" for release evidence.
MANDATORY_PACKAGES = ("chronos-forecasting", "torch", "streamlit", "pandas", "numpy")

# Package names considered NVIDIA/CUDA runtime packages.
_NVIDIA_MARKERS = ("nvidia", "cuda", "triton")
# Names that merely contain "cuda" as a substring but are safe.
_SAFE_PACKAGE_EXCEPTIONS = {"torch-cuda"}

_DEPLOYED_COMMIT_ENV_KEYS = ("DEPLOYED_COMMIT", "COMMIT_SHA", "GIT_SHA")

# Bounded request store size (matches the coordinator's bounded history).
DEFAULT_MAX_REQUEST_RECORDS = 256


class DeployedCommitError(Exception):
    """Raised when the deployed commit cannot be proven exactly."""


class DiagnosticsValidationError(ValueError):
    """Raised when a diagnostics record fails release validation."""


# ---------------------------------------------------------------------------
# Exact commit identity (WP3)
# ---------------------------------------------------------------------------


def is_exact_commit_sha(value: str) -> bool:
    """Return True only for exactly 40 lowercase hexadecimal characters."""
    return bool(value) and bool(_SHA40_RE.match(value))


@dataclasses.dataclass
class CloudCommitIdentity:
    """Fail-closed identity of the deployed commit.

    ``commit`` is empty and ``resolution_source`` is ``unresolved`` when the
    commit cannot be proven; ``error`` then explains why.  ``match`` is
    ``True``/``False`` when an expected commit was supplied, else ``None``.
    """
    commit: str = ""
    resolution_source: str = COMMIT_SOURCE_UNRESOLVED
    expected_commit: str = ""
    match: bool | None = None
    error: str = ""

    @property
    def resolved(self) -> bool:
        return is_exact_commit_sha(self.commit) and self.resolution_source in VALID_COMMIT_SOURCES

    def to_dict(self) -> dict[str, Any]:
        return {
            "commit": self.commit,
            "resolution_source": self.resolution_source,
            "expected_commit": self.expected_commit,
            "match": self.match,
            "error": self.error,
        }


def _exact_or_raise(value: str, source: str, detail: str) -> tuple[str, str]:
    """Return (value, source) if *value* is an exact commit, else raise."""
    if not value:
        raise DeployedCommitError(
            f"deployed commit: {detail} produced an empty value — cannot prove the deployed commit"
        )
    if not is_exact_commit_sha(value):
        raise DeployedCommitError(
            f"deployed commit: {detail} produced {value!r} which is not exactly "
            "40 lowercase hexadecimal characters — rejecting permissive values"
        )
    return value, source


def resolve_deployed_commit_strict(expected_commit: str = "") -> CloudCommitIdentity:
    """Strictly resolve the exact deployed commit.

    Resolution order (fail-closed at every step):

    1. **Explicit override** (``DEPLOYED_COMMIT`` / ``COMMIT_SHA`` /
       ``GIT_SHA``): accepted *only* when it is exactly 40 lowercase hex
       characters.  A non-empty-but-invalid override is a hard error — it is
       never accepted merely because it is non-empty.
    2. **git_head**: file-based ``.git/HEAD`` resolution relative to this
       module's repository root.
    3. **platform_commit_metadata**: ``capture_traceability()`` git
       subprocess result.

    When *expected_commit* is supplied it must itself be an exact SHA;
    ``match`` reports whether the resolved commit equals it.
    """
    expected_commit = (expected_commit or "").strip()
    if expected_commit and not is_exact_commit_sha(expected_commit):
        raise DeployedCommitError(
            f"expected_commit {expected_commit!r} is not exactly 40 lowercase "
            "hexadecimal characters"
        )

    # 1. Explicit, verified override.
    for key in _DEPLOYED_COMMIT_ENV_KEYS:
        raw = os.environ.get(key, "")
        if raw:
            value = raw.strip()
            if not is_exact_commit_sha(value):
                raise DeployedCommitError(
                    f"deployed commit: environment override {key} is {value!r} "
                    "which is not exactly 40 lowercase hexadecimal characters — "
                    "an override is not accepted merely because it is non-empty"
                )
            return _identity(value, COMMIT_SOURCE_EXPLICIT, expected_commit)

    # 2. Git HEAD file resolution (stdlib, safe on every render).
    module_dir = Path(os.path.dirname(os.path.abspath(__file__)))
    git_value = _resolve_git_head_sha(module_dir.parent)
    if git_value:
        value, source = _exact_or_raise(
            git_value, COMMIT_SOURCE_GIT_HEAD, "git HEAD resolution"
        )
        return _identity(value, source, expected_commit)

    # 3. Platform commit metadata (git subprocess fallback).
    trace = capture_traceability()
    platform_value = trace.get("code_commit", "")
    if platform_value:
        value, source = _exact_or_raise(
            platform_value, COMMIT_SOURCE_PLATFORM, "platform commit metadata"
        )
        return _identity(value, source, expected_commit)

    raise DeployedCommitError(
        "deployed commit: no exact 40-character SHA could be resolved from "
        "an explicit override, git HEAD, or platform commit metadata"
    )


def _identity(commit: str, source: str, expected_commit: str) -> CloudCommitIdentity:
    match: bool | None = None
    if expected_commit:
        match = commit == expected_commit
    return CloudCommitIdentity(
        commit=commit,
        resolution_source=source,
        expected_commit=expected_commit,
        match=match,
    )


def deployed_commit_identity(expected_commit: str = "") -> CloudCommitIdentity:
    """Non-raising wrapper of :func:`resolve_deployed_commit_strict`.

    Returns an ``unresolved`` identity with an ``error`` message on failure.
    """
    try:
        return resolve_deployed_commit_strict(expected_commit)
    except DeployedCommitError as exc:
        return CloudCommitIdentity(
            commit="",
            resolution_source=COMMIT_SOURCE_UNRESOLVED,
            expected_commit=(expected_commit or "").strip(),
            match=False if (expected_commit or "").strip() else None,
            error=str(exc),
        )


def assert_expected_commit_matches(
    expected_commit: str, identity: CloudCommitIdentity
) -> None:
    """Raise ``DeployedCommitError`` unless the resolved commit equals the
    expected collection commit.  Used by the collector *before* forecast
    collection (WP3: mismatch fails before forecast collection)."""
    if not identity.resolved:
        raise DeployedCommitError(
            f"deployed commit not proven: {identity.error or 'unresolved'}"
        )
    if not is_exact_commit_sha(expected_commit):
        raise DeployedCommitError(
            f"expected commit {expected_commit!r} is not an exact SHA"
        )
    if identity.commit != expected_commit:
        raise DeployedCommitError(
            f"deployed commit {identity.commit} != expected collection commit "
            f"{expected_commit} — refusing to collect against a different deployment"
        )


# ---------------------------------------------------------------------------
# Request-scoped memory sampling (WP4) — stdlib only
# ---------------------------------------------------------------------------


@dataclasses.dataclass
class RequestMemorySample:
    """A scoped per-request memory sample.

    Captures memory *before* the request, the request-scoped peak RSS (from
    its own sampler thread, never the process-lifetime high-water mark),
    memory *after* the request, and the process peak RSS at completion, plus
    sampler start/stop times and the request ID.
    """
    request_id: str = ""
    session_id: str = ""
    started_at_utc: str = ""
    stopped_at_utc: str = ""
    rss_before_mb: float = 0.0
    request_peak_rss_mb: float = 0.0
    rss_after_mb: float = 0.0
    process_peak_rss_mb: float = 0.0

    def validate(self) -> list[str]:
        errors: list[str] = []
        if not self.request_id:
            errors.append("memory sample: request_id empty")
        if not self.started_at_utc:
            errors.append("memory sample: started_at_utc empty")
        if not self.stopped_at_utc:
            errors.append("memory sample: stopped_at_utc empty")
        for name, value in (
            ("rss_before_mb", self.rss_before_mb),
            ("request_peak_rss_mb", self.request_peak_rss_mb),
            ("rss_after_mb", self.rss_after_mb),
            ("process_peak_rss_mb", self.process_peak_rss_mb),
        ):
            if not isinstance(value, (int, float)) or not math.isfinite(value):
                errors.append(f"memory sample: {name} must be a finite number, got {value!r}")
                continue
            if value < 0:
                errors.append(f"memory sample: {name} must be >= 0, got {value}")
        if self.started_at_utc and self.stopped_at_utc:
            try:
                if datetime.fromisoformat(self.started_at_utc) > datetime.fromisoformat(self.stopped_at_utc):
                    errors.append("memory sample: stopped_at_utc before started_at_utc")
            except (ValueError, TypeError):
                errors.append("memory sample: cannot parse sampler timestamps")
        return errors

    def to_dict(self) -> dict[str, Any]:
        return dataclasses.asdict(self)


class RequestMemorySampler:
    """Scoped memory sampler for a single request (stdlib only).

    Polls ``current_rss_mb()`` (``/proc/self/status`` on Linux, psutil
    fallback elsewhere) on a daemon thread and records the request-scoped
    peak.  ``process_peak_rss_mb`` is captured from the OS at stop time and
    is explicitly *not* used as the request peak.
    """

    def __init__(self, request_id: str = "", interval: float = 0.05):
        self.request_id = request_id or f"sampler_{uuid.uuid4().hex}"
        self._interval = max(0.005, interval)
        self._running = False
        self._thread: threading.Thread | None = None
        self._peak_mb = 0.0
        self._started_at_utc = ""
        self._stopped_at_utc = ""
        self.rss_before_mb = 0.0
        self.rss_after_mb = 0.0
        self.process_peak_at_stop_mb = 0.0

    def start(self) -> None:
        if self._running:
            return
        self._started_at_utc = _utcnow()
        self.rss_before_mb = current_rss_mb()
        self._peak_mb = self.rss_before_mb
        self._running = True
        self._thread = threading.Thread(target=self._sample, daemon=True)
        self._thread.start()

    def _sample(self) -> None:
        while self._running:
            try:
                rss = current_rss_mb()
                if rss > self._peak_mb:
                    self._peak_mb = rss
            except Exception:  # pragma: no cover - defensive
                pass
            time.sleep(self._interval)

    def stop(self, session_id: str = "") -> None:
        if not self._running and self._stopped_at_utc:
            return
        self._running = False
        if self._thread:
            self._thread.join(timeout=2)
            self._thread = None
        self.rss_after_mb = current_rss_mb()
        self.process_peak_at_stop_mb = process_peak_rss_mb()
        self._stopped_at_utc = _utcnow()

    @property
    def started_at_utc(self) -> str:
        return self._started_at_utc

    @property
    def stopped_at_utc(self) -> str:
        return self._stopped_at_utc

    @property
    def request_peak_rss_mb(self) -> float:
        return self._peak_mb

    def to_sample(self, session_id: str = "") -> RequestMemorySample:
        """Return the typed sample (must call ``stop()`` first)."""
        return RequestMemorySample(
            request_id=self.request_id,
            session_id=session_id,
            started_at_utc=self._started_at_utc,
            stopped_at_utc=self._stopped_at_utc,
            rss_before_mb=round(self.rss_before_mb, 3),
            request_peak_rss_mb=round(self._peak_mb, 3),
            rss_after_mb=round(self.rss_after_mb, 3),
            process_peak_rss_mb=round(self.process_peak_at_stop_mb, 3),
        )


# ---------------------------------------------------------------------------
# Typed request records + bounded store (WP5)
# ---------------------------------------------------------------------------


@dataclasses.dataclass
class CloudRequestRecord:
    """Typed, sanitised record for one forecast request.

    Never contains raw uploaded data, target values, forecast rows,
    filenames, CSV bytes, or exception strings containing local paths.
    """
    request_id: str = ""
    session_id: str = ""
    started_at_utc: str = ""
    queued_at_utc: str = ""
    inference_started_at_utc: str = ""
    completed_at_utc: str = ""
    queue_seconds: float = 0.0
    model_load_seconds: float = 0.0
    inference_seconds: float = 0.0
    result_conversion_seconds: float = 0.0
    total_seconds: float = 0.0
    success: bool = False
    error_category: str = ""
    pipeline_constructed: bool = False
    pipeline_reused: bool = False
    model_revision: str = ""
    context_rows_used: int = 0
    context_truncated: bool = False
    memory: dict[str, Any] = dataclasses.field(default_factory=dict)

    def validate(self) -> list[str]:
        errors: list[str] = []
        if not self.request_id:
            errors.append("request record: request_id empty")
        if not self.session_id:
            errors.append("request record: session_id empty")
        if not self.started_at_utc:
            errors.append("request record: started_at_utc empty")
        if not self.completed_at_utc:
            errors.append("request record: completed_at_utc empty")
        for name in ("queue_seconds", "model_load_seconds", "inference_seconds",
                     "result_conversion_seconds", "total_seconds"):
            value = getattr(self, name)
            if not isinstance(value, (int, float)) or not math.isfinite(value):
                errors.append(f"request record: {name} must be finite, got {value!r}")
            elif value < 0:
                errors.append(f"request record: {name} must be >= 0, got {value}")
        if self.success and self.inference_seconds <= 0:
            errors.append("request record: inference_seconds must be > 0 for a successful run")
        if self.success and not self.model_revision:
            errors.append("request record: model_revision empty for a successful run")
        if self.success and self.pipeline_constructed and self.pipeline_reused:
            errors.append("request record: pipeline_constructed and pipeline_reused both true")
        if self.memory:
            try:
                sample = RequestMemorySample(**self.memory)
                errors.extend(f"request record memory: {e}" for e in sample.validate())
            except Exception as exc:
                errors.append(f"request record memory: construction failed: {exc}")
        return errors

    def to_dict(self) -> dict[str, Any]:
        return dataclasses.asdict(self)


class RequestTelemetryStore:
    """Process-wide, bounded, thread-safe store of typed request records.

    ``begin_collection_session()`` is the deliberate reset action (invoked
    by the app under a local UI button with no secret input) that starts a
    fresh session and clears previous records so each collection window is
    bounded and unambiguous.
    """

    def __init__(self, max_records: int = DEFAULT_MAX_REQUEST_RECORDS, session_id: str = ""):
        self._max_records = max(1, int(max_records))
        self._records: collections.deque[dict[str, Any]] = collections.deque(maxlen=self._max_records)
        self._lock = threading.Lock()
        self._session_id = session_id or f"session_{uuid.uuid4().hex[:12]}"

    @property
    def session_id(self) -> str:
        return self._session_id

    @property
    def max_records(self) -> int:
        return self._max_records

    def begin_collection_session(self) -> str:
        """Start a new collection session: new ID, empty history."""
        with self._lock:
            self._session_id = f"session_{uuid.uuid4().hex[:12]}"
            self._records.clear()
            return self._session_id

    def record(self, record: CloudRequestRecord) -> None:
        with self._lock:
            record.session_id = record.session_id or self._session_id
            self._records.append(record.to_dict())

    def record_dict(self, data: dict[str, Any]) -> None:
        self.record(CloudRequestRecord(**data))

    def snapshot(self) -> list[dict[str, Any]]:
        with self._lock:
            return list(self._records)

    def get(self, request_id: str) -> dict[str, Any] | None:
        with self._lock:
            for entry in self._records:
                if entry.get("request_id") == request_id:
                    return dict(entry)
            return None

    def clear(self) -> None:
        with self._lock:
            self._records.clear()

    def request_ids(self) -> list[str]:
        return [r.get("request_id", "") for r in self.snapshot() if r.get("request_id")]


# ---------------------------------------------------------------------------
# Dependency diagnostics (WP6) — measured once per process, cached
# ---------------------------------------------------------------------------


@dataclasses.dataclass
class DependencyDiagnostics:
    dependency_install_succeeded: bool = False
    pip_check_passed: bool = False
    pip_check_summary: str = ""
    torch_cpu_only: bool = False
    torch_cuda_version: str = ""
    nvidia_packages: list[str] = dataclasses.field(default_factory=list)
    package_versions: dict[str, str] = dataclasses.field(default_factory=dict)
    checked_at_utc: str = ""

    def to_dict(self) -> dict[str, Any]:
        return dataclasses.asdict(self)


_dependency_cache: dict[str, Any] | None = None
_dependency_cache_lock = threading.Lock()


def reset_dependency_diagnostics_cache() -> None:
    """Clear the once-per-process dependency diagnostics cache (tests)."""
    global _dependency_cache
    with _dependency_cache_lock:
        _dependency_cache = None


def _run_pip_check() -> tuple[bool, str]:
    """Run ``pip check`` in a subprocess and return (passed, sanitised summary).

    No secrets are ever passed on the command line; the summary is
    sanitised through the shared redaction grammar before being reported.
    """
    try:
        import subprocess
        result = subprocess.run(
            [sys.executable, "-m", "pip", "check"],
            capture_output=True, text=True, timeout=120,
        )
        passed = result.returncode == 0
        body = (result.stdout or result.stderr or "").strip()
        summary = body[:500] if body else ("pip check passed" if passed else "pip check failed")
        return passed, sanitise_command([summary])
    except Exception as exc:
        return False, f"pip check could not be executed: {type(exc).__name__}"


def _installed_nvidia_packages() -> list[str]:
    """Names of installed distributions that are NVIDIA/CUDA runtime packages."""
    found: list[str] = []
    try:
        from importlib.metadata import distributions
        for dist in distributions():
            name = (dist.metadata.get("Name") or dist.metadata.get("name") or "").strip().lower()
            if not name:
                continue
            if name in _SAFE_PACKAGE_EXCEPTIONS:
                continue
            if any(marker in name for marker in _NVIDIA_MARKERS):
                found.append(name)
    except Exception:  # pragma: no cover - defensive
        pass
    return sorted(found)


def _measure_torch_state() -> tuple[bool, str, dict[str, str]]:
    """Return (torch_cpu_only, torch_cuda_version, package_versions)."""
    versions = package_versions_metadata()
    torch_version = versions.get("torch", "unknown")
    if torch_version == "unknown":
        # torch not importable via metadata — attempt a direct import.
        try:
            import torch as _torch
            torch_version = str(_torch.__version__)
        except Exception:
            return False, "unknown", versions
    try:
        import torch as _torch
        cuda_version = _torch.version.cuda
        torch_cpu_only = cuda_version is None
        return torch_cpu_only, ("" if cuda_version is None else str(cuda_version)), versions
    except Exception:
        return False, "unknown", versions


def measure_dependency_diagnostics() -> DependencyDiagnostics:
    """Measure dependency installation, pip check, CPU-only Torch, and the
    absence of NVIDIA packages.  Cached once per process."""
    global _dependency_cache
    with _dependency_cache_lock:
        if _dependency_cache is not None:
            return DependencyDiagnostics(**_dependency_cache)

        pip_passed, pip_summary = _run_pip_check()
        torch_cpu_only, torch_cuda_version, versions = _measure_torch_state()
        nvidia = _installed_nvidia_packages()
        # dependency_install_succeeded mirrors the version-metadata lookup
        # succeeding for every mandatory package (an "unknown" means the
        # dependency is not installed).
        dependency_install_succeeded = all(
            versions.get(name, "") not in ("", "unknown") for name in MANDATORY_PACKAGES
        )
        result = DependencyDiagnostics(
            dependency_install_succeeded=dependency_install_succeeded,
            pip_check_passed=pip_passed,
            pip_check_summary=pip_summary,
            torch_cpu_only=torch_cpu_only,
            torch_cuda_version=torch_cuda_version,
            nvidia_packages=nvidia,
            package_versions=dict(versions),
            checked_at_utc=_utcnow(),
        )
        _dependency_cache = result.to_dict()
        return result


# ---------------------------------------------------------------------------
# Token state (WP7) — boolean only, never a value
# ---------------------------------------------------------------------------


def hf_token_present(include_secrets: bool = True) -> bool:
    """Boolean observation of whether an ``HF_TOKEN`` is configured.

    Checks ``HF_TOKEN`` in the process environment and (when available)
    Streamlit secrets.  Never returns or logs the token, its length, a
    prefix, suffix, fingerprint, or hash.
    """
    if os.environ.get("HF_TOKEN"):
        return True
    if include_secrets:
        try:
            import streamlit as st
            if getattr(st, "secrets", None) and "HF_TOKEN" in st.secrets:
                return True
        except Exception:
            pass
    return False


# ---------------------------------------------------------------------------
# Runtime diagnostics snapshot (WP1 / WP2 / WP12)
# ---------------------------------------------------------------------------


@dataclasses.dataclass
class CloudRuntimeDiagnostics:
    """Allowlisted, typed runtime diagnostics snapshot.

    Only these fields may be exported; there is no arbitrary environment
    dump.  ``validate(release=True)`` rejects ``unknown`` / empty / short
    SHA / non-finite values for every mandatory release field.
    """
    schema_version: str = DIAGNOSTICS_SCHEMA_VERSION
    diagnostics_id: str = ""
    generated_at_utc: str = ""
    deployed_commit: str = ""
    commit_resolution_source: str = ""
    expected_commit: str = ""
    expected_commit_match: bool | None = None
    model_id: str = ""
    configured_revision: str = ""
    python_version: str = ""
    package_versions: dict[str, str] = dataclasses.field(default_factory=dict)
    os_name: str = ""
    cpu_model: str = ""
    cpu_logical_cores: int = 0
    ram_total_gb: float = 0.0
    torch_cpu_only: bool = False
    torch_cuda_version: str = ""
    nvidia_packages: list[str] = dataclasses.field(default_factory=list)
    pip_check_passed: bool = False
    pip_check_summary: str = ""
    hf_token_present: bool = False
    current_rss_mb: float = 0.0
    process_peak_rss_mb: float = 0.0
    pipeline_constructed: bool = False
    pipeline_construction_count: int = 0
    coordinator_state: str = ""

    def validate(self, *, release: bool = False) -> list[str]:
        errors: list[str] = []
        if self.schema_version != DIAGNOSTICS_SCHEMA_VERSION:
            errors.append(f"diagnostics: schema_version expected '{DIAGNOSTICS_SCHEMA_VERSION}', got '{self.schema_version}'")
        if not self.diagnostics_id:
            errors.append("diagnostics: diagnostics_id empty")
        if not self.generated_at_utc:
            errors.append("diagnostics: generated_at_utc empty")
        else:
            try:
                datetime.fromisoformat(self.generated_at_utc)
            except (ValueError, TypeError):
                errors.append("diagnostics: generated_at_utc not parseable")

        # Exact deployed commit (fail closed).
        if not self.deployed_commit:
            errors.append("diagnostics: deployed_commit empty — must be exactly 40 lowercase hex characters")
        elif not is_exact_commit_sha(self.deployed_commit):
            errors.append(
                f"diagnostics: deployed_commit {self.deployed_commit!r} is not exactly "
                "40 lowercase hexadecimal characters — short SHAs, uppercase SHAs, "
                "'not available' and arbitrary text are rejected"
            )
        if not self.commit_resolution_source:
            errors.append("diagnostics: commit_resolution_source empty")
        elif self.commit_resolution_source not in VALID_COMMIT_SOURCES:
            errors.append(f"diagnostics: commit_resolution_source '{self.commit_resolution_source}' not in {sorted(VALID_COMMIT_SOURCES)}")
        if self.expected_commit and not is_exact_commit_sha(self.expected_commit):
            errors.append("diagnostics: expected_commit is not exactly 40 lowercase hex characters")
        if self.expected_commit and self.expected_commit_match is None:
            errors.append("diagnostics: expected_commit supplied but expected_commit_match not recorded")
        if self.expected_commit and self.expected_commit_match is not None and self.deployed_commit and self.expected_commit != self.deployed_commit and self.expected_commit_match:
            errors.append("diagnostics: expected_commit_match true but commits differ")
        if release and self.expected_commit and self.expected_commit_match is False:
            errors.append(
                "diagnostics: deployed commit does not match the expected "
                "collection commit — release collection fails closed on a mismatch"
            )

        if not self.model_id:
            errors.append("diagnostics: model_id empty")
        elif self.model_id != MODEL_ID:
            errors.append(f"diagnostics: model_id '{self.model_id}' != production model '{MODEL_ID}'")
        if not self.configured_revision:
            errors.append("diagnostics: configured_revision empty")
        elif self.configured_revision != MODEL_REVISION:
            errors.append(
                f"diagnostics: configured_revision '{self.configured_revision}' != "
                f"pinned revision '{MODEL_REVISION}'"
            )

        # Python version.
        if not self.python_version or self.python_version == "unknown":
            errors.append("diagnostics: python_version empty or 'unknown'")

        # Package versions: all mandatory packages must be known.
        if not self.package_versions:
            errors.append("diagnostics: package_versions empty")
        else:
            for name in MANDATORY_PACKAGES:
                value = self.package_versions.get(name, "")
                if not value or value == "unknown":
                    errors.append(f"diagnostics: package_versions['{name}'] empty or 'unknown'")

        # Machine fields.
        if not self.os_name or self.os_name == "unknown":
            errors.append("diagnostics: os_name empty or 'unknown'")
        if not self.cpu_model or self.cpu_model == "unknown":
            errors.append("diagnostics: cpu_model empty or 'unknown'")
        if not isinstance(self.cpu_logical_cores, int) or self.cpu_logical_cores <= 0:
            errors.append(f"diagnostics: cpu_logical_cores must be a positive int, got {self.cpu_logical_cores!r}")
        if not isinstance(self.ram_total_gb, (int, float)) or not math.isfinite(self.ram_total_gb) or self.ram_total_gb <= 0:
            errors.append(f"diagnostics: ram_total_gb must be a finite positive number, got {self.ram_total_gb!r}")

        # Torch / dependency state.
        if not isinstance(self.torch_cpu_only, bool):
            errors.append("diagnostics: torch_cpu_only must be a boolean")
        if self.torch_cuda_version not in ("", "None"):
            errors.append(f"diagnostics: torch_cuda_version '{self.torch_cuda_version}' — CPU-only Torch requires no CUDA")
        if not isinstance(self.nvidia_packages, list):
            errors.append("diagnostics: nvidia_packages must be a list")
        elif self.nvidia_packages:
            errors.append(f"diagnostics: nvidia_packages non-empty {self.nvidia_packages} — NVIDIA runtime packages must be absent")
        if not isinstance(self.pip_check_passed, bool):
            errors.append("diagnostics: pip_check_passed must be a boolean")
        elif release and not self.pip_check_passed:
            errors.append("diagnostics: pip_check_passed false — dependency verification required for release evidence")
        if not isinstance(self.torch_cpu_only, bool):
            errors.append("diagnostics: torch_cpu_only must be a boolean")
        elif release and not self.torch_cpu_only:
            errors.append("diagnostics: torch_cpu_only false — CPU-only Torch required for release evidence")
        if not isinstance(self.hf_token_present, bool):
            errors.append("diagnostics: hf_token_present must be a boolean")

        # Memory values.
        for name in ("current_rss_mb", "process_peak_rss_mb"):
            value = getattr(self, name)
            if not isinstance(value, (int, float)) or not math.isfinite(value):
                errors.append(f"diagnostics: {name} must be finite, got {value!r}")
        if release and self.process_peak_rss_mb <= 0:
            errors.append("diagnostics: process_peak_rss_mb must be > 0 for release evidence")

        if not isinstance(self.pipeline_construction_count, int) or self.pipeline_construction_count < 0:
            errors.append(f"diagnostics: pipeline_construction_count must be a non-negative int, got {self.pipeline_construction_count!r}")
        if not isinstance(self.pipeline_constructed, bool):
            errors.append("diagnostics: pipeline_constructed must be a boolean")
        if self.pipeline_constructed and self.pipeline_construction_count <= 0:
            errors.append("diagnostics: pipeline_constructed true but construction_count is 0")
        if not self.coordinator_state:
            errors.append("diagnostics: coordinator_state empty")

        return errors

    def to_dict(self) -> dict[str, Any]:
        return dataclasses.asdict(self)


def _utcnow() -> str:
    return datetime.now(timezone.utc).isoformat()


def _coordinator_state_string(coordinator: Any | None) -> str:
    if coordinator is None:
        return "unavailable"
    try:
        history = len(coordinator.request_log)
    except Exception:
        history = -1
    try:
        max_history = coordinator.max_history
    except Exception:
        max_history = -1
    try:
        sync_mode = coordinator.sync_mode
    except Exception:
        sync_mode = "unknown"
    return f"capacity={coordinator.capacity};max_history={max_history};history={history};sync_mode={sync_mode}"


def build_runtime_diagnostics(
    expected_commit: str = "",
    *,
    adapter: Any | None = None,
    coordinator: Any | None = None,
) -> CloudRuntimeDiagnostics:
    """Build a typed runtime diagnostics snapshot from real measurements.

    Fails closed: an unprovable deployed commit raises
    ``DeployedCommitError``.
    """
    identity = resolve_deployed_commit_strict(expected_commit)
    versions = package_versions_metadata()
    machine = machine_summary()
    dep = measure_dependency_diagnostics()

    pipeline_construction_count = 0
    pipeline_constructed = False
    if adapter is not None:
        try:
            pipeline_construction_count = int(adapter.pipeline_call_count)
        except Exception:
            pipeline_construction_count = 0
        pipeline_constructed = pipeline_construction_count > 0

    return CloudRuntimeDiagnostics(
        schema_version=DIAGNOSTICS_SCHEMA_VERSION,
        diagnostics_id=f"diag_{uuid.uuid4().hex[:12]}",
        generated_at_utc=_utcnow(),
        deployed_commit=identity.commit,
        commit_resolution_source=identity.resolution_source,
        expected_commit=identity.expected_commit,
        expected_commit_match=identity.match,
        model_id=MODEL_ID,
        configured_revision=MODEL_REVISION,
        python_version=versions.get("python", "unknown"),
        package_versions={
            k: v for k, v in versions.items() if k in MANDATORY_PACKAGES or k == "python"
        },
        os_name=machine.get("os_name", ""),
        cpu_model=machine.get("cpu_model", ""),
        cpu_logical_cores=int(machine.get("cpu_logical_cores", 0) or 0),
        ram_total_gb=float(machine.get("ram_total_gb", 0.0) or 0.0),
        torch_cpu_only=dep.torch_cpu_only,
        torch_cuda_version=dep.torch_cuda_version,
        nvidia_packages=list(dep.nvidia_packages),
        pip_check_passed=dep.pip_check_passed,
        pip_check_summary=dep.pip_check_summary,
        hf_token_present=hf_token_present(),
        current_rss_mb=round(current_rss_mb(), 3),
        process_peak_rss_mb=round(process_peak_rss_mb(), 3),
        pipeline_constructed=pipeline_constructed,
        pipeline_construction_count=pipeline_construction_count,
        coordinator_state=_coordinator_state_string(coordinator),
    )


# ---------------------------------------------------------------------------
# Deterministic JSON export (WP2)
# ---------------------------------------------------------------------------


def diagnostics_to_json(diagnostics: CloudRuntimeDiagnostics) -> str:
    """Deterministic JSON serialisation of the diagnostics snapshot."""
    return json.dumps(
        diagnostics.to_dict(),
        sort_keys=True,
        indent=2,
        allow_nan=False,
        ensure_ascii=False,
    )


def canonical_diagnostics_digest(diagnostics: CloudRuntimeDiagnostics) -> str:
    """Canonical SHA-256 of the typed diagnostics snapshot."""
    return canonical_evidence_sha256(diagnostics.to_dict())


# ---------------------------------------------------------------------------
# Request-record categorisation helpers (WP8 / WP9 / WP10)
# ---------------------------------------------------------------------------


def _parse_ts(value: str) -> datetime | None:
    try:
        return datetime.fromisoformat(value)
    except (ValueError, TypeError):
        return None


def intervals_overlap(
    a_start: str, a_end: str, b_start: str, b_end: str
) -> bool:
    """True when the two [start, end) windows genuinely overlap in time."""
    a_s, a_e = _parse_ts(a_start), _parse_ts(a_end)
    b_s, b_e = _parse_ts(b_start), _parse_ts(b_end)
    if None in (a_s, a_e, b_s, b_e):
        return False
    return min(a_e, b_e) > max(a_s, b_s)  # type: ignore[operator]


def any_overlapping_pair(records: list[dict[str, Any]]) -> bool:
    """True when at least one pair of successful request inference windows
    overlaps (proves genuine concurrency from typed intervals)."""
    successful = [
        r for r in records
        if r.get("success") and r.get("inference_started_at_utc") and r.get("completed_at_utc")
    ]
    for i in range(len(successful)):
        for j in range(i + 1, len(successful)):
            a, b = successful[i], successful[j]
            if intervals_overlap(
                a["inference_started_at_utc"], a["completed_at_utc"],
                b["inference_started_at_utc"], b["completed_at_utc"],
            ):
                return True
    return False


def categorise_request_ids(records: list[dict[str, Any]]) -> dict[str, list[str]]:
    """Derive repeated-run, concurrency and timeout/recovery ID groups.

    - ``repeated_run_ids``: successful warm (pipeline reused) requests after
      the first request of the session.
    - ``concurrency_request_ids``: requests participating in an overlapping
      pair.
    - ``timeout_recovery_ids``: the timed-out request plus the immediately
      subsequent successful request (recovery).
    """
    repeated: list[str] = []
    concurrency: list[str] = []
    timeout_recovery: list[str] = []

    ordered = sorted(
        records,
        key=lambda r: (r.get("started_at_utc") or ""),
    )

    warm_seen = 0
    for i, r in enumerate(ordered):
        if r.get("success") and r.get("pipeline_reused") and not r.get("pipeline_constructed"):
            warm_seen += 1
            if warm_seen > 1:
                repeated.append(r.get("request_id", ""))
        if not r.get("success") and r.get("error_category") == "CoordinatorTimeoutError":
            timeout_recovery.append(r.get("request_id", ""))
            # The next successful request is the recovery.
            for nxt in ordered[i + 1:]:
                if nxt.get("success"):
                    timeout_recovery.append(nxt.get("request_id", ""))
                    break

    successful = [r for r in records if r.get("success")]
    for i in range(len(successful)):
        for j in range(i + 1, len(successful)):
            a, b = successful[i], successful[j]
            if intervals_overlap(
                a.get("inference_started_at_utc", ""), a.get("completed_at_utc", ""),
                b.get("inference_started_at_utc", ""), b.get("completed_at_utc", ""),
            ):
                for rid in (a.get("request_id", ""), b.get("request_id", "")):
                    if rid and rid not in concurrency:
                        concurrency.append(rid)

    return {
        "repeated_run_ids": repeated,
        "concurrency_request_ids": concurrency,
        "timeout_recovery_ids": timeout_recovery,
    }


# ---------------------------------------------------------------------------
# Collection session + receipt binding (WP11)
# ---------------------------------------------------------------------------


@dataclasses.dataclass
class CloudCollectionSessionRecord:
    """Typed collection-session record.

    Binds the deployed commit, deployment URL, runtime diagnostics digest,
    acceptance-test names, request IDs, token-path execution IDs,
    repeated-run IDs, concurrency request IDs and timeout/recovery IDs.

    The session record never contains its own receipt; the collection
    receipt (see :func:`build_collection_receipt`) binds this record's
    canonical digest.
    """
    evidence_schema_version: str = EVIDENCE_SCHEMA_VERSION
    evidence_type: str = "collection_session"
    evidence_origin: str = ""
    session_id: str = ""
    code_commit: str = ""
    deployed_commit: str = ""
    deployment_url: str = ""
    diagnostics_digest: str = ""
    diagnostics_id: str = ""
    test_names: list[str] = dataclasses.field(default_factory=list)
    request_ids: list[str] = dataclasses.field(default_factory=list)
    token_absent_execution_ids: list[str] = dataclasses.field(default_factory=list)
    token_present_execution_ids: list[str] = dataclasses.field(default_factory=list)
    repeated_run_ids: list[str] = dataclasses.field(default_factory=list)
    concurrency_request_ids: list[str] = dataclasses.field(default_factory=list)
    timeout_recovery_ids: list[str] = dataclasses.field(default_factory=list)
    started_at_utc: str = ""
    completed_at_utc: str = ""

    def validate(self) -> list[str]:
        errors: list[str] = []
        if self.evidence_schema_version != EVIDENCE_SCHEMA_VERSION:
            errors.append(f"collection session: schema version expected '{EVIDENCE_SCHEMA_VERSION}'")
        if self.evidence_type != "collection_session":
            errors.append("collection session: evidence_type must be 'collection_session'")
        if not self.session_id:
            errors.append("collection session: session_id empty")
        if not is_exact_commit_sha(self.deployed_commit):
            errors.append("collection session: deployed_commit not exactly 40 lowercase hex chars")
        if self.code_commit and self.code_commit != self.deployed_commit:
            errors.append("collection session: code_commit != deployed_commit")
        if not self.deployment_url:
            errors.append("collection session: deployment_url empty")
        if not self.diagnostics_digest:
            errors.append("collection session: diagnostics_digest empty — must bind the runtime diagnostics")
        if not self.diagnostics_id:
            errors.append("collection session: diagnostics_id empty")
        if not self.started_at_utc:
            errors.append("collection session: started_at_utc empty")
        if not self.completed_at_utc:
            errors.append("collection session: completed_at_utc empty")
        if self.started_at_utc and self.completed_at_utc:
            try:
                if datetime.fromisoformat(self.started_at_utc) > datetime.fromisoformat(self.completed_at_utc):
                    errors.append("collection session: completed_at_utc before started_at_utc")
            except (ValueError, TypeError):
                errors.append("collection session: cannot parse session timestamps")
        # Within-group uniqueness (repeated/concurrency/timeout IDs are
        # subsets of request_ids, so cross-group duplication is expected).
        for group_name in ("request_ids", "token_absent_execution_ids",
                           "token_present_execution_ids", "repeated_run_ids",
                           "concurrency_request_ids", "timeout_recovery_ids"):
            group = getattr(self, group_name)
            if not isinstance(group, list):
                errors.append(f"collection session: {group_name} must be a list")
                continue
            seen_in_group: set[str] = set()
            for rid in group:
                if not rid:
                    errors.append(f"collection session: {group_name} contains an empty id")
                if rid in seen_in_group:
                    errors.append(f"collection session: duplicate id '{rid}' in {group_name}")
                seen_in_group.add(rid)
        # Category IDs must be a subset of the request IDs they describe.
        request_id_set = set(self.request_ids)
        for group_name in ("token_absent_execution_ids", "token_present_execution_ids",
                           "repeated_run_ids", "concurrency_request_ids",
                           "timeout_recovery_ids"):
            for rid in getattr(self, group_name):
                if rid and request_id_set and rid not in request_id_set:
                    errors.append(
                        f"collection session: {group_name} id '{rid}' not in request_ids"
                    )
        return errors

    def to_dict(self) -> dict[str, Any]:
        return dataclasses.asdict(self)


def build_collection_session_record(
    *,
    session_id: str,
    deployed_commit: str,
    commit_resolution_source: str,
    deployment_url: str,
    diagnostics: CloudRuntimeDiagnostics,
    acceptance_test_names: list[str],
    request_records: list[dict[str, Any]],
    token_absent_execution_ids: list[str] | None = None,
    token_present_execution_ids: list[str] | None = None,
    repeated_run_ids: list[str] | None = None,
    concurrency_request_ids: list[str] | None = None,
    timeout_recovery_ids: list[str] | None = None,
    started_at_utc: str = "",
    completed_at_utc: str = "",
    evidence_origin: str = EVIDENCE_ORIGIN_REAL,
) -> CloudCollectionSessionRecord:
    """Build a typed collection-session record from the measured pieces.

    Request IDs are taken from ``request_records`` (typed, bounded).  When a
    category list is not supplied it is derived deterministically from the
    records via :func:`categorise_request_ids` (repeated warm runs,
    overlapping concurrency pairs, timeout + recovery).
    """
    request_ids = [r.get("request_id", "") for r in request_records if r.get("request_id")]
    if repeated_run_ids is None or concurrency_request_ids is None or timeout_recovery_ids is None:
        derived = categorise_request_ids(request_records)
        repeated_run_ids = repeated_run_ids if repeated_run_ids is not None else derived["repeated_run_ids"]
        concurrency_request_ids = concurrency_request_ids if concurrency_request_ids is not None else derived["concurrency_request_ids"]
        timeout_recovery_ids = timeout_recovery_ids if timeout_recovery_ids is not None else derived["timeout_recovery_ids"]
    return CloudCollectionSessionRecord(
        evidence_schema_version=EVIDENCE_SCHEMA_VERSION,
        evidence_type="collection_session",
        evidence_origin=evidence_origin,
        session_id=session_id,
        code_commit=deployed_commit,
        deployed_commit=deployed_commit,
        deployment_url=deployment_url,
        diagnostics_digest=canonical_diagnostics_digest(diagnostics),
        diagnostics_id=diagnostics.diagnostics_id,
        test_names=list(acceptance_test_names),
        request_ids=request_ids,
        token_absent_execution_ids=list(token_absent_execution_ids or []),
        token_present_execution_ids=list(token_present_execution_ids or []),
        repeated_run_ids=list(repeated_run_ids),
        concurrency_request_ids=list(concurrency_request_ids),
        timeout_recovery_ids=list(timeout_recovery_ids),
        started_at_utc=started_at_utc,
        completed_at_utc=completed_at_utc,
    )


def build_collection_receipt(
    session_record: CloudCollectionSessionRecord,
    *,
    execution_id: str = "",
    sanitised_command: str = "cloud collection session finalise",
    evidence_origin: str = EVIDENCE_ORIGIN_REAL,
) -> dict[str, Any]:
    """Build an ``ExecutionReceipt`` whose ``canonical_content_sha256``
    binds the canonical digest of the collection-session record.

    The receipt is a separate object; the session record never contains it.
    """
    session_dict = session_record.to_dict()
    digest = canonical_evidence_sha256(session_dict)
    now = _utcnow()
    receipt = ExecutionReceipt(
        execution_id=execution_id or f"collection_{uuid.uuid4().hex[:12]}",
        attestation_type="operator_attested",
        code_commit=session_record.deployed_commit,
        producer_name="src.cloud_diagnostics.build_collection_receipt",
        producer_version="1.0",
        git_worktree_clean=False,
        sanitised_command=sanitise_command([sanitised_command]),
        started_at_utc=now,
        completed_at_utc=now,
        exit_code=0,
        canonical_content_sha256=digest,
        model_id=MODEL_ID,
        configured_revision=MODEL_REVISION,
        resolved_revision=MODEL_REVISION,
        environment_summary=f"python={sys.version.split()[0]} os={sys.platform}",
        evidence_origin=evidence_origin,
    )
    return receipt.to_dict()


# ---------------------------------------------------------------------------
# Secret / payload scanning (WP12)
# ---------------------------------------------------------------------------


def diagnostics_exposes_secret(data: dict[str, Any]) -> str | None:
    """Return a description if *data* (or any nested value) exposes a secret.

    Checks for the ``HF_TOKEN`` env key name, any ``=``/``:`` assignment that
    looks like a credential through the shared redaction grammar, hostnames,
    usernames, home directories, repository paths, cookie/header markers and
    payload markers.  Returns ``None`` when nothing suspicious is found.
    """
    path_markers = (
        "D:\\",
        "C:\\",
        "/home/",
        "/Users/",
        "\\Users\\",
        "\\home\\",
    )
    payload_markers = (
        '"forecast_rows"',
        '"target"',
        '"historical_data"',
        "predictions",
        "quantile_",
    )

    def _scan(value: Any, path: str) -> str | None:
        if isinstance(value, dict):
            for k, v in value.items():
                found = _scan(v, f"{path}.{k}")
                if found:
                    return found
                key = str(k).lower()
                if any(marker.lower() in key for marker in ("token", "password", "secret", "authorization", "api_key", "cookie")):
                    # Only flag credential-like keys; "hf_token_present" is
                    # the allowlisted boolean and is safe.
                    if key not in ("hf_token_present", "hf_token_present_2"):
                        return f"credential-like key '{k}' at {path}"
            return None
        if isinstance(value, (list, tuple)):
            for i, item in enumerate(value):
                found = _scan(item, f"{path}[{i}]")
                if found:
                    return found
            return None
        if isinstance(value, str):
            low = value.lower()
            if "hf_token" in low and "present" not in low:
                return f"HF_TOKEN-like string at {path}"
            if any(marker.lower() in low for marker in ("authorization: bearer", "password=", "api_key=", "token=")):
                return f"credential assignment at {path}"
            if any(marker in value for marker in path_markers):
                return f"path-like value at {path}"
            if any(marker in value for marker in ("@",)) and "://" in value and "streamlit.app" not in value:
                # URLs with userinfo can embed credentials; only flag non-app URLs.
                if "user:" in value.split("://")[-1].split("/")[0]:
                    return f"credential-bearing URL at {path}"
            return None
        return None

    found = _scan(data, "root")
    if found:
        return found

    # Payload markers at the top level of the export only (request records
    # must not contain forecast values).
    dumped = json.dumps(data, sort_keys=True, default=str)
    for marker in payload_markers:
        if marker in dumped:
            return f"payload marker {marker!r} present in export"
    return None


# ---------------------------------------------------------------------------
# Composite public export (WP2 / WP5 / WP11)
# ---------------------------------------------------------------------------


def build_public_diagnostics_export(
    expected_commit: str = "",
    *,
    adapter: Any | None = None,
    coordinator: Any | None = None,
    store: RequestTelemetryStore | None = None,
    deployment_url: str = "",
) -> dict[str, Any]:
    """Build the composite, allowlisted public export.

    Returns a dict with the typed diagnostics snapshot, the bounded request
    records, a canonical digest of the exact payload, and an explicit
    ``release_ready`` flag plus ``validation_errors`` so the public surface
    can render on any platform while the release path still fails closed
    (Stage 3 refuses to build evidence from a non-release-ready export).
    Deterministic key order and deterministic canonical digest.
    """
    diagnostics = build_runtime_diagnostics(
        expected_commit, adapter=adapter, coordinator=coordinator
    )
    validation_errors = diagnostics.validate(release=True)

    request_records = store.snapshot() if store is not None else []

    export = {
        "diagnostics": diagnostics.to_dict(),
        "request_records": request_records,
        "request_count": len(request_records),
        "release_ready": not validation_errors,
        "validation_errors": validation_errors,
    }
    digest = canonical_evidence_sha256(export)

    return {
        "diagnostics": diagnostics.to_dict(),
        "request_records": request_records,
        "request_count": len(request_records),
        "release_ready": not validation_errors,
        "validation_errors": validation_errors,
        "canonical_digest": digest,
    }
