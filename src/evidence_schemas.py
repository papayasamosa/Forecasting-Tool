"""Typed evidence schemas for Stage 0 smoke, benchmark, and bundle records.

Schema version 2 — replaces ad hoc dictionary evidence with typed models.

Each model class provides:
- Fields with defaults
- ``validate()`` method returning a list of error messages
- ``to_dict()`` for JSON serialisation
"""

from __future__ import annotations

import dataclasses
import hashlib
import json
import re
from datetime import datetime, timezone
from typing import Any

from src.redaction import contains_exposed_secret

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------
EVIDENCE_SCHEMA_VERSION = "2"

# Evidence-origin enum (WP7: synthetic evidence isolation)
EVIDENCE_ORIGIN_REAL = "real_measurement"
EVIDENCE_ORIGIN_SYNTHETIC = "synthetic_fixture"
VALID_EVIDENCE_ORIGINS = {EVIDENCE_ORIGIN_REAL, EVIDENCE_ORIGIN_SYNTHETIC}

# Attestation types
ATTESTATION_GITHUB = "github_attestation"
ATTESTATION_OPERATOR = "operator_attested"
VALID_ATTESTATION_TYPES = {ATTESTATION_GITHUB, ATTESTATION_OPERATOR}


def canonical_evidence_sha256(data: dict[str, Any]) -> str:
    """Deterministic SHA-256 of a dict using canonical JSON serialisation.

    Rules:
    - UTF-8 JSON serialisation with sorted keys at every nesting level.
    - Fixed separators (no whitespace): ``(',', ':')``.
    - Floats are serialised by the standard library's own ``repr``-equivalent
      float formatter (``json.dumps`` handles native floats directly — the
      ``default`` callback below is never invoked for them).
    - Non-finite floats (``NaN``, ``Infinity``, ``-Infinity``) are rejected
      with ``ValueError`` rather than silently emitted as non-standard JSON
      tokens, since they cannot round-trip deterministically across readers.
    - No timestamps or fields are removed — the full semantic content is
      hashed, so any semantic mutation changes the digest.
    - Returns a lowercase 64-character hex SHA-256 string.

    Parameters
    ----------
    data : dict[str, Any]
        The evidence object to digest.

    Returns
    -------
    str
        Lowercase 64-character hex SHA-256.

    Raises
    ------
    ValueError
        If ``data`` contains a NaN or +/-Infinity float anywhere.
    """
    def _sort(obj: Any) -> Any:
        """Recursively sort keys and convert tuples to lists."""
        if isinstance(obj, dict):
            return {k: _sort(v) for k, v in sorted(obj.items())}
        elif isinstance(obj, list):
            return [_sort(item) for item in obj]
        elif isinstance(obj, tuple):
            return [_sort(item) for item in obj]
        return obj

    sorted_data = _sort(data)

    # allow_nan=False makes json.dumps raise ValueError on NaN/Infinity/
    # -Infinity instead of silently emitting the non-standard JSON tokens
    # `NaN`/`Infinity`/`-Infinity`, which most JSON readers cannot parse.
    canonical = json.dumps(
        sorted_data,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
        allow_nan=False,
        default=_canonical_json_default,
    )
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def _canonical_json_default(obj: Any) -> str:
    """JSON default serialiser for canonical hashing.

    Only invoked for types ``json.dumps`` cannot natively serialise (e.g.
    sets, datetimes) — floats, including non-finite ones, are handled
    natively by ``json.dumps`` before this callback is ever consulted.
    """
    raise TypeError(f"Object of type {type(obj).__name__} is not JSON serialisable")


# ---------------------------------------------------------------------------
# Cache-source constants (safe enum — never a personal path)
# ---------------------------------------------------------------------------
CACHE_SOURCE_EXPLICIT = "explicit"
CACHE_SOURCE_ENV_HF_HUB_CACHE = "env_HF_HUB_CACHE"
CACHE_SOURCE_HF_HUB_CONSTANT = "hf_hub_constant"
CACHE_SOURCE_ENV_HF_HOME = "env_HF_HOME"
CACHE_SOURCE_FALLBACK = "fallback"
VALID_CACHE_SOURCES = {
    CACHE_SOURCE_EXPLICIT, CACHE_SOURCE_ENV_HF_HUB_CACHE,
    CACHE_SOURCE_HF_HUB_CONSTANT, CACHE_SOURCE_ENV_HF_HOME,
    CACHE_SOURCE_FALLBACK,
}

# Synchronisation modes for concurrency
SYNC_MODE_NONE = "none"
SYNC_MODE_LOCK = "lock"
SYNC_MODE_SEMAPHORE = "semaphore"
SYNC_MODE_REMOTE_QUEUE = "remote_queue"
VALID_SYNC_MODES = {SYNC_MODE_NONE, SYNC_MODE_LOCK, SYNC_MODE_SEMAPHORE, SYNC_MODE_REMOTE_QUEUE}

# ---------------------------------------------------------------------------
# Cache-state constants
# ---------------------------------------------------------------------------
CACHE_STATE_DOWNLOAD_COLD = "download_cold"
CACHE_STATE_PROCESS_COLD = "process_cold_cached_weights"
CACHE_STATE_WARM = "same_process_warm"
CACHE_STATE_AGGREGATE = "aggregate"
CACHE_STATE_SYNTHETIC = "synthetic_fake"

VALID_INITIAL_CACHE_STATES = {CACHE_STATE_DOWNLOAD_COLD, CACHE_STATE_PROCESS_COLD}
# ---------------------------------------------------------------------------
# Canonical Cloud acceptance test names (WP9)
# ---------------------------------------------------------------------------
CANONICAL_CLOUD_TESTS: list[str] = [
    "dependency_install",
    "pip_check",
    "cpu_only_torch",
    "no_nvidia_packages",
    "token_absent_load",
    "token_present_load",
    "cold_forecast",
    "warm_forecast",
    "repeated_forecasts",
    "valid_csv_forecast",
    "oversized_csv_rejected",
    "blank_timestamp_rejected",
    "invalid_timestamp_rejected",
    "same_column_rejected",
    "context_truncation_visible",
    "recoverable_failure",
    "configuration_preserved",
    "two_session_concurrency",
    "coordinator_timeout_recovery",
]

VALID_PHASE_CACHE_STATES = {
    CACHE_STATE_DOWNLOAD_COLD, CACHE_STATE_PROCESS_COLD,
    CACHE_STATE_WARM, CACHE_STATE_AGGREGATE, CACHE_STATE_SYNTHETIC,
}

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _utcnow() -> str:
    return datetime.now(timezone.utc).isoformat()


# ---------------------------------------------------------------------------
# Machine summary
# ---------------------------------------------------------------------------


@dataclasses.dataclass
class MachineSummary:
    cpu_model: str = ""
    cpu_logical_cores: int = 0
    ram_total_gb: float = 0.0
    os_name: str = ""

    def validate(self) -> list[str]:
        errors: list[str] = []
        return errors

    def to_dict(self) -> dict[str, Any]:
        return dataclasses.asdict(self)


# ---------------------------------------------------------------------------
# Cache preflight record (WP4, WP7)
# ---------------------------------------------------------------------------


@dataclasses.dataclass
class CachePreflight:
    """Cache preflight inspection record.

    WP7: Release evidence must require all fields below. For download_cold:
    snapshot_present=False, post_run_snapshot_present=True,
    post_run_file_count>0, post_run_total_bytes>0.
    For process_cold_cached_weights: snapshot_present=True,
    file_count>0, total_bytes>0.
    """
    inspection_succeeded: bool = False
    cache_source: str = ""
    initial_cache_state: str = ""
    snapshot_present: bool = False
    file_count: int = 0
    total_bytes: int = 0
    post_run_snapshot_present: bool = False
    post_run_file_count: int = 0
    post_run_total_bytes: int = 0
    error: str = ""

    def validate(self) -> list[str]:
        errors: list[str] = []
        if not self.inspection_succeeded:
            errors.append("cache_preflight: inspection_succeeded is false")
        if not self.cache_source:
            errors.append("cache_preflight: cache_source empty")
        elif self.cache_source not in VALID_CACHE_SOURCES:
            errors.append(f"cache_source: invalid '{self.cache_source}'")
        if not self.initial_cache_state:
            errors.append("cache_preflight: initial_cache_state empty")
        elif self.initial_cache_state not in VALID_INITIAL_CACHE_STATES:
            errors.append(f"cache_preflight: initial_cache_state invalid '{self.initial_cache_state}'")
        if self.initial_cache_state == CACHE_STATE_DOWNLOAD_COLD:
            if self.snapshot_present:
                errors.append("cache_preflight: download_cold but snapshot_present is True")
            if not self.post_run_snapshot_present:
                errors.append("cache_preflight: download_cold but post_run_snapshot_present is False")
            if self.post_run_file_count <= 0:
                errors.append("cache_preflight: download_cold but post_run_file_count is 0")
            if self.post_run_total_bytes <= 0:
                errors.append("cache_preflight: download_cold but post_run_total_bytes is 0")
        elif self.initial_cache_state == CACHE_STATE_PROCESS_COLD:
            if not self.snapshot_present:
                errors.append("cache_preflight: process_cold_cached_weights but snapshot_present is False")
            if self.file_count <= 0:
                errors.append("cache_preflight: process_cold_cached_weights but file_count is 0")
            if self.total_bytes <= 0:
                errors.append("cache_preflight: process_cold_cached_weights but total_bytes is 0")
        return errors

    def to_dict(self) -> dict[str, Any]:
        return dataclasses.asdict(self)


# ---------------------------------------------------------------------------
# Token path result (WP8)
# ---------------------------------------------------------------------------


@dataclasses.dataclass
class TokenPathResult:
    attempted: bool = False
    success: bool = False
    configured_revision: str = ""
    resolved_revision: str = ""
    error_code: str = ""
    timing_seconds: float = 0.0
    # Provenance fields (evidence-integrity closure): a successful attempted
    # path must carry a unique run identity and real timing, so a copied or
    # hand-edited record cannot be mistaken for an independently executed run.
    run_id: str = ""
    started_at_utc: str = ""
    completed_at_utc: str = ""

    def validate(self) -> list[str]:
        errors: list[str] = []
        if self.attempted and not self.success and not self.error_code:
            errors.append("token path: attempted but failed with no error_code")
        if self.attempted and self.success:
            if not self.run_id:
                errors.append("token path: attempted successful run missing run_id")
            if not self.started_at_utc:
                errors.append("token path: attempted successful run missing started_at_utc")
            if not self.completed_at_utc:
                errors.append("token path: attempted successful run missing completed_at_utc")
            if self.timing_seconds <= 0:
                errors.append("token path: attempted successful run must have timing_seconds > 0")
            if not self.configured_revision:
                errors.append("token path: attempted successful run missing configured_revision")
            if not self.resolved_revision:
                errors.append("token path: attempted successful run missing resolved_revision")
            if (
                self.configured_revision
                and self.resolved_revision
                and self.configured_revision != self.resolved_revision
            ):
                errors.append(
                    f"token path: configured_revision '{self.configured_revision}' != "
                    f"resolved_revision '{self.resolved_revision}'"
                )
        return errors

    def to_dict(self) -> dict[str, Any]:
        return dataclasses.asdict(self)


# ---------------------------------------------------------------------------
# Constants for SHA-256 validation
# ---------------------------------------------------------------------------
_SHA256_RE = re.compile(r'^[0-9a-f]{64}$')


def _is_valid_sha256(value: str) -> bool:
    """Return True if *value* is a valid lowercase 64-char SHA-256 hex string."""
    return bool(_SHA256_RE.match(value)) if value else False


# ---------------------------------------------------------------------------
# Execution receipt (WP3) — tamper-evident proof that a command ran
# ---------------------------------------------------------------------------


@dataclasses.dataclass
class ExecutionReceipt:
    """Evidence that a specific command was executed.

    Contains three distinct digest fields (WP2):
    - ``source_file_sha256`` — hash of the raw producer output file.
    - ``published_file_sha256`` — hash of the exact final published file
      (after sanitisation).
    - ``canonical_content_sha256`` — deterministic content digest of the
      embedded evidence object (WP1). This is the primary tamper-evident
      binding.

    ``component_sha256`` is kept for backward compatibility but should be
    source_file_sha256 in new evidence.

    When independent attestation (e.g. GitHub-generated) is unavailable,
    the evidence should be labelled "operator-attested and tamper-evident".
    """

    evidence_schema_version: str = EVIDENCE_SCHEMA_VERSION
    evidence_type: str = "execution_receipt"
    execution_id: str = ""
    attestation_type: str = ""  # "github_attestation", "operator_attested"
    code_commit: str = ""
    producer_version: str = ""
    sanitised_command: str = ""
    started_at_utc: str = ""
    completed_at_utc: str = ""
    exit_code: int = 0
    # WP2: Three distinct digest fields
    component_sha256: str = ""  # backward compat — source_file_sha256 preferred
    source_file_sha256: str = ""
    published_file_sha256: str = ""
    canonical_content_sha256: str = ""
    # WP7: Evidence origin
    evidence_origin: str = ""  # WP-D: no real-default; must be set explicitly
    model_id: str = ""
    configured_revision: str = ""
    resolved_revision: str = ""
    environment_summary: str = ""
    immutable_artifact_reference: str = ""
    # WP3: Producer identity and worktree cleanliness. Not structurally
    # required here — a receipt can legitimately describe a failed or
    # dirty-worktree run that is still worth recording as non-passing —
    # but both are required for a receipt to be release-ready; see
    # receipt_is_release_ready() below.
    producer_name: str = ""
    git_worktree_clean: bool = False

    def validate(self) -> list[str]:
        errors: list[str] = []
        if self.evidence_schema_version != EVIDENCE_SCHEMA_VERSION:
            errors.append(f"schema version: expected '{EVIDENCE_SCHEMA_VERSION}', got '{self.evidence_schema_version}'")
        if self.evidence_type != "execution_receipt":
            errors.append(f"evidence_type: expected 'execution_receipt', got '{self.evidence_type}'")
        if not self.execution_id:
            errors.append("execution_receipt: execution_id empty")
        if not self.attestation_type:
            errors.append("execution_receipt: attestation_type empty")
        if self.attestation_type not in VALID_ATTESTATION_TYPES:
            errors.append(
                f"execution_receipt: attestation_type '{self.attestation_type}' "
                f"not recognized"
            )
        if not self.code_commit:
            errors.append("execution_receipt: code_commit empty")
        if not self.producer_version:
            errors.append("execution_receipt: producer_version empty")
        if not self.sanitised_command:
            errors.append("execution_receipt: sanitised_command empty")
        # WP5: Reject exposed secrets stored in the command field
        exposure = contains_exposed_secret(self.sanitised_command)
        if exposure:
            errors.append(f"execution_receipt: sanitised_command contains {exposure}")
        if not self.started_at_utc:
            errors.append("execution_receipt: started_at_utc empty")
        if not self.completed_at_utc:
            errors.append("execution_receipt: completed_at_utc empty")
        # Exit code validation (WP9)
        if self.exit_code < 0:
            errors.append("execution_receipt: exit_code must be >= 0")
        # WP9: SHA-256 format validation
        for field_name, value in [
            ("component_sha256", self.component_sha256),
            ("source_file_sha256", self.source_file_sha256),
            ("published_file_sha256", self.published_file_sha256),
            ("canonical_content_sha256", self.canonical_content_sha256),
        ]:
            if value and not _is_valid_sha256(value):
                errors.append(
                    f"execution_receipt: {field_name} '{value}' is not a "
                    f"valid lowercase 64-character SHA-256"
                )
        # WP9: At least one content digest must be populated
        if not (self.component_sha256 or self.source_file_sha256 or self.canonical_content_sha256):
            errors.append("execution_receipt: no content digest provided")
        if not self.model_id:
            errors.append("execution_receipt: model_id empty")
        if not self.configured_revision:
            errors.append("execution_receipt: configured_revision empty")
        if not self.resolved_revision:
            errors.append("execution_receipt: resolved_revision empty")
        if self.configured_revision and self.resolved_revision and self.configured_revision != self.resolved_revision:
            errors.append(
                f"execution_receipt: configured_revision '{self.configured_revision}' != "
                f"resolved_revision '{self.resolved_revision}'"
            )
        # WP9: Non-empty environment summary
        if not self.environment_summary:
            errors.append("execution_receipt: environment_summary empty")
        # WP7: Evidence origin validation
        if self.evidence_origin not in VALID_EVIDENCE_ORIGINS:
            errors.append(
                f"execution_receipt: evidence_origin '{self.evidence_origin}' "
                f"not recognized"
            )
        # WP9: Immutable artifact reference required for github_attestation
        if self.attestation_type == ATTESTATION_GITHUB and not self.immutable_artifact_reference:
            errors.append(
                "execution_receipt: immutable_artifact_reference required "
                "for github_attestation"
            )
        # Ordered timestamps
        if self.started_at_utc and self.completed_at_utc:
            try:
                if datetime.fromisoformat(self.started_at_utc) > datetime.fromisoformat(self.completed_at_utc):
                    errors.append("execution_receipt: started_at_utc after completed_at_utc")
            except (ValueError, TypeError):
                errors.append("execution_receipt: cannot parse timestamps")
        # WP9: Reject placeholder values in release evidence
        placeholders = {"not_available", "token-absent-auto", "token-present-auto", "collection-auto"}
        for field_name, value in [
            ("execution_id", self.execution_id),
            ("component_sha256", self.component_sha256),
            ("source_file_sha256", self.source_file_sha256),
            ("canonical_content_sha256", self.canonical_content_sha256),
        ]:
            if value in placeholders:
                errors.append(
                    f"execution_receipt: {field_name} contains placeholder "
                    f"'{value}' — not valid for release evidence"
                )
        return errors

    def to_dict(self) -> dict[str, Any]:
        return dataclasses.asdict(self)


def receipt_is_release_ready(receipt: ExecutionReceipt) -> list[str]:
    """Check the stricter gate a receipt must pass to back *passing* release
    evidence (WP3), on top of ``receipt.validate()``'s structural checks.

    A structurally valid receipt can still describe a failed command, a
    synthetic fixture run, or a dirty worktree — none of those are release
    evidence. Returns an empty list only if the receipt is eligible to back
    passing release evidence.
    """
    errors = list(receipt.validate())
    if receipt.exit_code != 0:
        errors.append(
            f"execution_receipt: exit_code {receipt.exit_code} != 0 — "
            f"not eligible for release evidence"
        )
    if receipt.evidence_origin != EVIDENCE_ORIGIN_REAL:
        errors.append(
            f"execution_receipt: evidence_origin '{receipt.evidence_origin}' "
            f"!= '{EVIDENCE_ORIGIN_REAL}' — not eligible for release evidence"
        )
    if not receipt.git_worktree_clean:
        errors.append(
            "execution_receipt: git_worktree_clean is false — "
            "not eligible for release evidence"
        )
    return errors


# ---------------------------------------------------------------------------
# Repeated run record (WP9)
# ---------------------------------------------------------------------------


@dataclasses.dataclass
class RepeatedRun:
    run_number: int = 0
    success: bool = False
    started_at_utc: str = ""
    completed_at_utc: str = ""
    total_seconds: float = 0.0
    inference_seconds: float = 0.0
    cache_state: str = ""
    pipeline_reused: bool = False
    pipeline_construction_count: int = 0
    resolved_revision: str = ""
    rss_mb: float = 0.0
    error_code: str = ""

    def validate(self) -> list[str]:
        errors: list[str] = []
        if self.run_number <= 0:
            errors.append(f"repeated_run: run_number must be >= 1, got {self.run_number}")
        if self.success:
            if not self.started_at_utc:
                errors.append(f"repeated_run {self.run_number}: started_at_utc empty")
            if not self.completed_at_utc:
                errors.append(f"repeated_run {self.run_number}: completed_at_utc empty")
            if self.total_seconds <= 0:
                errors.append(f"repeated_run {self.run_number}: total_seconds must be > 0")
            if not self.resolved_revision:
                errors.append(f"repeated_run {self.run_number}: resolved_revision empty")
        return errors

    def to_dict(self) -> dict[str, Any]:
        return dataclasses.asdict(self)


# ---------------------------------------------------------------------------
# Concurrency request record (WP11)
# ---------------------------------------------------------------------------


@dataclasses.dataclass
class ConcurrencyRequest:
    request_id: str = ""
    start_time_utc: str = ""
    inference_start_utc: str = ""
    completion_time_utc: str = ""
    queue_seconds: float = 0.0
    inference_seconds: float = 0.0
    success: bool = False
    error_code: str = ""
    sync_mode: str = ""

    def validate(self) -> list[str]:
        errors: list[str] = []
        if not self.request_id:
            errors.append("concurrency_request: request_id empty")
        if self.success:
            if self.queue_seconds < 0:
                errors.append(f"concurrency_request {self.request_id}: queue_seconds < 0")
            if self.inference_seconds <= 0:
                errors.append(f"concurrency_request {self.request_id}: inference_seconds must be > 0 for success")
            if not self.start_time_utc:
                errors.append(f"concurrency_request {self.request_id}: start_time_utc empty")
            if not self.completion_time_utc:
                errors.append(f"concurrency_request {self.request_id}: completion_time_utc empty")
        return errors

    def to_dict(self) -> dict[str, Any]:
        return dataclasses.asdict(self)


# ---------------------------------------------------------------------------
# Acceptance test result (WP12)
# ---------------------------------------------------------------------------


@dataclasses.dataclass
class AcceptanceTestResult:
    test_name: str = ""
    passed: bool = False
    details: str = ""

    def validate(self) -> list[str]:
        errors: list[str] = []
        if not self.test_name:
            errors.append("acceptance_test: test_name empty")
        return errors

    def to_dict(self) -> dict[str, Any]:
        return dataclasses.asdict(self)


# ---------------------------------------------------------------------------
# Smoke phase record
# ---------------------------------------------------------------------------


@dataclasses.dataclass
class SmokePhase:
    total_seconds: float = 0.0
    model_load_seconds: float = 0.0
    inference_seconds: float = 0.0
    result_conversion_seconds: float = 0.0
    rss_mb: float = 0.0
    pipeline_call_count: int = 0
    model_revision: str = ""
    cache_state: str = ""
    pipeline_reused: bool = False
    error: str = ""

    def validate(self) -> list[str]:
        errors: list[str] = []
        return errors

    def to_dict(self) -> dict[str, Any]:
        return {k: v for k, v in dataclasses.asdict(self).items() if v or k == "cache_state"}


# ---------------------------------------------------------------------------
# Smoke evidence (schema v2)
# ---------------------------------------------------------------------------


@dataclasses.dataclass
class SmokeEvidence:
    evidence_schema_version: str = EVIDENCE_SCHEMA_VERSION
    evidence_type: str = "smoke_test"
    # WP7: Evidence origin
    evidence_origin: str = ""  # WP-D: no real-default; must be set explicitly
    test: str = "chronos2_smoke_test"
    success: bool = False
    code_commit: str = ""
    git_worktree_clean: bool = False
    git_traceability_error: str = ""
    started_at_utc: str = ""
    completed_at_utc: str = ""
    python_version: str = ""
    model_id: str = ""
    configured_revision: str = ""
    model_revision: str = ""
    # Token path results (WP8) — replaces single hf_token_present bool
    hf_token_present: bool = False  # kept for backward compat
    token_absent_result: TokenPathResult = dataclasses.field(default_factory=TokenPathResult)
    token_present_result: TokenPathResult = dataclasses.field(default_factory=TokenPathResult)
    initial_cache_state: str = ""
    cold: SmokePhase = dataclasses.field(default_factory=SmokePhase)
    warm: SmokePhase = dataclasses.field(default_factory=SmokePhase)
    package_versions: dict[str, str] = dataclasses.field(default_factory=dict)
    machine: MachineSummary = dataclasses.field(default_factory=MachineSummary)
    cache_preflight: CachePreflight = dataclasses.field(default_factory=CachePreflight)
    error: str = ""
    evidence_path: str = ""
    # Producer-emitted field (not used in validation, preserved for round-trip)
    timestamp: str = ""
    # Flat machine fields (backward compat with smoke test output)
    cpu_model: str = ""
    cpu_logical_cores: int = 0
    ram_total_gb: float = 0.0

    def validate(self) -> list[str]:
        errors: list[str] = []

        if self.evidence_schema_version != EVIDENCE_SCHEMA_VERSION:
            errors.append(f"schema version: expected '{EVIDENCE_SCHEMA_VERSION}', got '{self.evidence_schema_version}'")
        if self.evidence_type != "smoke_test":
            errors.append(f"evidence_type: expected 'smoke_test', got '{self.evidence_type}'")
        if self.evidence_origin not in VALID_EVIDENCE_ORIGINS:
            errors.append(
                f"evidence_origin: expected one of {VALID_EVIDENCE_ORIGINS}, "
                f"got '{self.evidence_origin}'"
            )
        if not self.code_commit:
            errors.append("code_commit: empty — cannot publish")
        if not self.git_worktree_clean:
            errors.append("git_worktree_clean: false — worktree must be clean")
        if self.git_traceability_error:
            errors.append(f"git_traceability_error: {self.git_traceability_error}")
        if not self.initial_cache_state:
            errors.append("initial_cache_state: empty")
        elif self.initial_cache_state not in VALID_INITIAL_CACHE_STATES:
            errors.append(f"initial_cache_state: invalid '{self.initial_cache_state}'")

        # Token path provenance: the flag and the two attempted-path results
        # must agree, and each nested result must satisfy its own rules
        # (evidence-integrity closure — prevents a duplicated/hand-edited
        # token-present record from being accepted as an independent run).
        errors.extend(f"token_absent_result: {e}" for e in self.token_absent_result.validate())
        errors.extend(f"token_present_result: {e}" for e in self.token_present_result.validate())
        if self.success:
            if self.hf_token_present and self.token_absent_result.attempted:
                errors.append(
                    "token_absent_result: attempted=true but hf_token_present=true "
                    "for this run"
                )
            if self.hf_token_present and not self.token_present_result.attempted:
                errors.append(
                    "token_present_result: attempted=false but hf_token_present=true "
                    "for this run"
                )
            if not self.hf_token_present and self.token_present_result.attempted:
                errors.append(
                    "token_present_result: attempted=true but hf_token_present=false "
                    "for this run"
                )
            if not self.hf_token_present and not self.token_absent_result.attempted:
                errors.append(
                    "token_absent_result: attempted=false but hf_token_present=false "
                    "for this run"
                )

        # Cache preflight required (WP4)
        if self.success:
            cp_errors = self.cache_preflight.validate()
            errors.extend(f"cache_preflight: {e}" for e in cp_errors)
            if self.initial_cache_state == CACHE_STATE_DOWNLOAD_COLD and self.cache_preflight.snapshot_present:
                errors.append("cache_preflight: download_cold but snapshot is already cached")
            if self.initial_cache_state == CACHE_STATE_PROCESS_COLD and not self.cache_preflight.snapshot_present:
                errors.append("cache_preflight: process_cold_cached_weights but snapshot is not cached")

        if self.success:
            if not self.started_at_utc:
                errors.append("started_at_utc: empty")
            if not self.completed_at_utc:
                errors.append("completed_at_utc: empty")
            if not self.model_revision:
                errors.append("model_revision: empty on successful run")
            if self.configured_revision and self.model_revision and self.configured_revision != self.model_revision:
                errors.append(
                    f"revision mismatch: configured '{self.configured_revision}', "
                    f"resolved '{self.model_revision}'"
                )
            # Cold phase checks
            if not self.cold.cache_state:
                errors.append("cold.cache_state: empty")
            elif self.cold.cache_state not in VALID_PHASE_CACHE_STATES:
                errors.append(f"cold.cache_state: invalid '{self.cold.cache_state}'")
            # Warm phase checks
            if not self.warm.cache_state:
                errors.append("warm.cache_state: empty")
            elif self.warm.cache_state not in VALID_PHASE_CACHE_STATES:
                errors.append(f"warm.cache_state: invalid '{self.warm.cache_state}'")
            # Pipeline count must be 1 if model was loaded (cold)
            if self.cold.pipeline_call_count > 1:
                errors.append(f"cold.pipeline_call_count: expected 1, got {self.cold.pipeline_call_count}")

        return errors

    def to_dict(self) -> dict[str, Any]:
        d = dataclasses.asdict(self)
        d["cold"] = self.cold.to_dict()
        d["warm"] = self.warm.to_dict()
        d["machine"] = self.machine.to_dict()
        d["cache_preflight"] = self.cache_preflight.to_dict()
        d["token_absent_result"] = self.token_absent_result.to_dict()
        d["token_present_result"] = self.token_present_result.to_dict()
        return d


# ---------------------------------------------------------------------------
# Benchmark sample
# ---------------------------------------------------------------------------


@dataclasses.dataclass
class BenchmarkSampleRecord:
    label: str = ""
    duration_seconds: float = 0.0
    rss_mb: float = 0.0
    baseline_rss_mb: float = 0.0
    peak_rss_mb: float = 0.0
    pipeline_call_count: int = 0
    success: bool = True
    error_type: str = ""
    error_message: str = ""
    model_load_seconds: float = 0.0
    inference_seconds: float = 0.0
    cache_state: str = ""

    def to_dict(self) -> dict[str, Any]:
        return dataclasses.asdict(self)


# ---------------------------------------------------------------------------
# Benchmark scenario
# ---------------------------------------------------------------------------


@dataclasses.dataclass
class BenchmarkScenarioRecord:
    scenario: str = ""
    python_version: str = ""
    os_name: str = ""
    cpu_info: str = ""
    model_id: str = ""
    model_revision: str = ""
    configured_revision: str = ""
    package_versions: dict[str, str] = dataclasses.field(default_factory=dict)
    context_rows: int = 0
    horizon: int = 0
    quantile_levels: list[float] = dataclasses.field(default_factory=list)
    samples: list[BenchmarkSampleRecord] = dataclasses.field(default_factory=list)
    hf_token_present: bool = False
    run_timestamp: str = ""
    cross_learning: bool = False
    n_series: int = 1
    expected_outcome: str = "pass"
    sample_passed: bool = False
    scenario_passed: bool = False
    code_commit: str = ""
    git_worktree_clean: bool = False
    initial_cache_state: str = ""
    cpu_model: str = ""
    cpu_logical_cores: int = 0
    ram_total_gb: float = 0.0
    git_traceability_error: str = ""
    # Producer-emitted field — accepted for round-trip compatibility (WP7)
    evidence_schema_version: str = ""

    def validate(self) -> list[str]:
        errors: list[str] = []
        if self.expected_outcome == "pass" and not self.scenario_passed:
            errors.append(f"scenario '{self.scenario}': expected pass but scenario_passed=false")
        if self.expected_outcome == "expected_failure" and not self.scenario_passed:
            errors.append(f"scenario '{self.scenario}': expected failure gate not met")
        for s in self.samples:
            if s.label.startswith("total_"):
                if s.cache_state and s.cache_state not in VALID_PHASE_CACHE_STATES:
                    errors.append(f"sample '{s.label}': invalid cache_state '{s.cache_state}'")
            else:
                if not s.cache_state:
                    errors.append(f"sample '{s.label}': missing cache_state")
                elif s.cache_state not in VALID_PHASE_CACHE_STATES:
                    errors.append(f"sample '{s.label}': invalid cache_state '{s.cache_state}'")
        return errors

    def to_dict(self) -> dict[str, Any]:
        d = dataclasses.asdict(self)
        d["samples"] = [s.to_dict() for s in self.samples]
        return d


# ---------------------------------------------------------------------------
# Benchmark suite evidence (schema v2)
# ---------------------------------------------------------------------------


@dataclasses.dataclass
class BenchmarkSuiteEvidence:
    evidence_schema_version: str = EVIDENCE_SCHEMA_VERSION
    evidence_type: str = "benchmark_suite"
    evidence_origin: str = ""  # WP-D: no real-default; must be set explicitly
    suite_passed: bool = False
    code_commit: str = ""
    git_worktree_clean: bool = False
    git_traceability_error: str = ""
    initial_cache_state: str = ""
    started_at_utc: str = ""
    completed_at_utc: str = ""
    python_version: str = ""
    model_id: str = ""
    configured_revision: str = ""
    # Suite-level revision and resource fields (WP5)
    resolved_revision: str = ""
    pipeline_construction_count: int = 0
    peak_rss_mb: float = 0.0
    cache_preflight: CachePreflight = dataclasses.field(default_factory=CachePreflight)
    scenarios: list[BenchmarkScenarioRecord] = dataclasses.field(default_factory=list)

    def validate(self) -> list[str]:
        errors: list[str] = []

        if self.evidence_schema_version != EVIDENCE_SCHEMA_VERSION:
            errors.append(f"schema version: expected '{EVIDENCE_SCHEMA_VERSION}', got '{self.evidence_schema_version}'")
        if self.evidence_type != "benchmark_suite":
            errors.append(f"evidence_type: expected 'benchmark_suite', got '{self.evidence_type}'")
        if self.evidence_origin not in VALID_EVIDENCE_ORIGINS:
            errors.append(
                f"evidence_origin: expected one of {VALID_EVIDENCE_ORIGINS}, "
                f"got '{self.evidence_origin}'"
            )
        if not self.code_commit:
            errors.append("code_commit: empty")
        if not self.git_worktree_clean:
            errors.append("git_worktree_clean: false")
        if self.git_traceability_error:
            errors.append(f"git_traceability_error: {self.git_traceability_error}")
        if not self.initial_cache_state:
            errors.append("initial_cache_state: empty")
        elif self.initial_cache_state not in VALID_INITIAL_CACHE_STATES:
            errors.append(f"initial_cache_state: invalid '{self.initial_cache_state}'")

        # Cache preflight validation (WP8)
        cp_errors = self.cache_preflight.validate()
        errors.extend(f"cache_preflight: {e}" for e in cp_errors)

        if self.suite_passed:
            if not self.started_at_utc:
                errors.append("started_at_utc: empty")
            if not self.completed_at_utc:
                errors.append("completed_at_utc: empty")

            # WP8: Mandatory benchmark identity and resources
            if not self.configured_revision:
                errors.append("configured_revision: empty")
            if not self.resolved_revision:
                errors.append("resolved_revision: empty")
            if self.configured_revision and self.resolved_revision:
                if self.configured_revision != self.resolved_revision:
                    errors.append(
                        f"revision mismatch: configured '{self.configured_revision}', "
                        f"resolved '{self.resolved_revision}'"
                    )
            if self.pipeline_construction_count != 1:
                errors.append(
                    f"pipeline_construction_count: expected 1, "
                    f"got {self.pipeline_construction_count}"
                )
            if self.peak_rss_mb <= 0:
                errors.append("peak_rss_mb: must be > 0 for successful suite")

            # Validate required scenarios
            scenario_names = {s.scenario for s in self.scenarios}
            required = {"weekly_260_13", "panel_5_series", "10_rolling_calls", "failure_and_retry"}
            missing = required - scenario_names
            if missing:
                errors.append(f"missing required scenarios: {sorted(missing)}")

            for sc in self.scenarios:
                errors.extend(sc.validate())

                # Check scenario-level revision consistency (WP5)
                if sc.scenario in {"weekly_260_13", "panel_5_series", "10_rolling_calls"}:
                    if not sc.model_revision:
                        errors.append(f"scenario '{sc.scenario}': model_revision empty — must match suite revision")
                    elif self.resolved_revision and sc.model_revision != self.resolved_revision:
                        errors.append(
                            f"scenario '{sc.scenario}': model_revision '{sc.model_revision}' "
                            f"!= suite resolved_revision '{self.resolved_revision}'"
                        )

            # Check rolling scenario has 10 successful folds
            rolling = next((s for s in self.scenarios if s.scenario == "10_rolling_calls"), None)
            if rolling:
                fold_successes = sum(
                    1 for s in rolling.samples
                    if s.label.startswith("fold_") and s.success
                )
                if fold_successes != 10:
                    errors.append(f"10_rolling_calls: expected 10 successful folds, got {fold_successes}")

            # Check weekly scenario warm reuse
            weekly = next((s for s in self.scenarios if s.scenario == "weekly_260_13"), None)
            if weekly:
                warm = next((s for s in weekly.samples if s.label == "warm_forecast"), None)
                if warm and warm.cache_state != CACHE_STATE_WARM:
                    errors.append(f"weekly_260_13 warm_forecast: expected cache_state '{CACHE_STATE_WARM}', got '{warm.cache_state}'")

        return errors

    def to_dict(self) -> dict[str, Any]:
        d = dataclasses.asdict(self)
        d["scenarios"] = [s.to_dict() for s in self.scenarios]
        d["cache_preflight"] = self.cache_preflight.to_dict()
        return d


# ---------------------------------------------------------------------------
# Model artifact evidence
# ---------------------------------------------------------------------------


@dataclasses.dataclass
class ModelArtifactFile:
    filename: str = ""
    size_bytes: int = 0
    sha256: str = ""

    def to_dict(self) -> dict[str, Any]:
        return dataclasses.asdict(self)


@dataclasses.dataclass
class ModelArtifactEvidence:
    evidence_schema_version: str = EVIDENCE_SCHEMA_VERSION
    evidence_type: str = "model_artifact"
    evidence_origin: str = ""  # WP-D: no real-default; must be set explicitly
    code_commit: str = ""
    git_worktree_clean: bool = False
    model_id: str = ""
    configured_revision: str = ""
    resolved_revision: str = ""
    snapshot_commit: str = ""
    # Artifact inventory — unambiguous field naming (WP8)
    snapshot_file_count: int = 0  # total files in snapshot (config + weights)
    weight_file_count: int = 0  # number of model weight files only
    weight_shard_count: int = 0  # number of weight shards (safetensors parts)
    total_bytes: int = 0
    files: list[ModelArtifactFile] = dataclasses.field(default_factory=list)
    manifest_sha256: str = ""
    # Deprecated alias (backward compat) — use snapshot_file_count in new evidence
    shard_count: int = 0

    def validate(self) -> list[str]:
        errors: list[str] = []
        import re
        if self.evidence_schema_version != EVIDENCE_SCHEMA_VERSION:
            errors.append(f"schema version: expected '{EVIDENCE_SCHEMA_VERSION}'")
        if self.evidence_type != "model_artifact":
            errors.append("evidence_type: expected 'model_artifact'")
        if self.evidence_origin not in VALID_EVIDENCE_ORIGINS:
            errors.append(
                f"evidence_origin: expected one of {VALID_EVIDENCE_ORIGINS}, "
                f"got '{self.evidence_origin}'"
            )
        if not self.code_commit:
            errors.append("code_commit: empty")
        if not self.git_worktree_clean:
            errors.append("git_worktree_clean: false")
        # WP10: model ID must be exactly amazon/chronos-2
        if self.model_id != "amazon/chronos-2":
            errors.append(f"model_id: expected 'amazon/chronos-2', got '{self.model_id}'")
        if not self.configured_revision:
            errors.append("configured_revision: empty")
        if not self.resolved_revision:
            errors.append("resolved_revision: empty")
        if self.configured_revision and self.resolved_revision and self.configured_revision != self.resolved_revision:
            errors.append(
                f"revision mismatch: configured '{self.configured_revision}', "
                f"resolved '{self.resolved_revision}'"
            )
        # WP10: snapshot_commit must equal resolved_revision
        if not self.snapshot_commit:
            errors.append("snapshot_commit: empty")
        elif self.resolved_revision and self.snapshot_commit != self.resolved_revision:
            errors.append(
                f"snapshot_commit '{self.snapshot_commit}' != "
                f"resolved_revision '{self.resolved_revision}'"
            )
        if not self.files:
            errors.append("files: empty — no weight files recorded")
        if not self.manifest_sha256:
            errors.append("manifest_sha256: empty")
        # WP10: at least one weight file and one weight shard
        if self.weight_file_count < 1:
            errors.append("weight_file_count: must be >= 1 for real model evidence")
        if self.weight_shard_count < 1:
            errors.append("weight_shard_count: must be >= 1 for real model evidence")
        # WP10: valid lowercase 64-character SHA-256 for every file
        sha256_re = re.compile(r'^[0-9a-f]{64}$')
        for f in self.files:
            if not f.sha256:
                errors.append(f"file '{f.filename}': sha256 is empty")
            elif not sha256_re.match(f.sha256):
                errors.append(f"file '{f.filename}': sha256 '{f.sha256}' is not a valid 64-char hex hash")
        # Verify declared counts match actual files
        sc = self.snapshot_file_count if self.snapshot_file_count > 0 else self.shard_count
        if self.files:
            actual_count = len(self.files)
            if sc > 0 and actual_count != sc:
                errors.append(
                    f"snapshot_file_count mismatch: declared {sc}, "
                    f"actual files listed {actual_count}"
                )
            weight_files = [f for f in self.files if "safetensors" in f.filename or "weights" in f.filename.lower()]
            actual_weight_count = len(weight_files)
            if self.weight_file_count > 0 and actual_weight_count != self.weight_file_count:
                errors.append(
                    f"weight_file_count mismatch: declared {self.weight_file_count}, "
                    f"actual weight files {actual_weight_count}"
                )
            # WP10: declared total_bytes must equal inventory
            actual_total = sum(f.size_bytes for f in self.files)
            if self.total_bytes > 0 and actual_total != self.total_bytes:
                errors.append(
                    f"total_bytes mismatch: declared {self.total_bytes}, "
                    f"actual inventory {actual_total}"
                )
        return errors

    def to_dict(self) -> dict[str, Any]:
        d = dataclasses.asdict(self)
        d["files"] = [f.to_dict() for f in self.files]
        return d


# ---------------------------------------------------------------------------
# Local Stage 0 bundle
# ---------------------------------------------------------------------------


@dataclasses.dataclass
class LocalStage0Bundle:
    evidence_schema_version: str = EVIDENCE_SCHEMA_VERSION
    evidence_type: str = "local_stage0_bundle"
    evidence_origin: str = ""  # WP-D: no real-default; must be set explicitly
    bundle_passed: bool = False
    code_commit: str = ""
    git_worktree_clean: bool = False
    started_at_utc: str = ""
    completed_at_utc: str = ""
    python_version: str = ""
    runs: dict[str, Any] = dataclasses.field(default_factory=dict)
    model_artifact: dict[str, Any] = dataclasses.field(default_factory=dict)
    # WP3: Typed receipt container — required for passing bundles
    receipts: dict[str, Any] = dataclasses.field(default_factory=dict)

    def validate(self) -> list[str]:
        errors: list[str] = []

        if self.evidence_schema_version != EVIDENCE_SCHEMA_VERSION:
            errors.append(f"schema version: expected '{EVIDENCE_SCHEMA_VERSION}'")
        if self.evidence_type != "local_stage0_bundle":
            errors.append("evidence_type: expected 'local_stage0_bundle'")
        if self.evidence_origin not in VALID_EVIDENCE_ORIGINS:
            errors.append(
                f"evidence_origin: expected one of {VALID_EVIDENCE_ORIGINS}, "
                f"got '{self.evidence_origin}'"
            )
        if not self.code_commit:
            errors.append("code_commit: empty")
        if not self.git_worktree_clean:
            errors.append("git_worktree_clean: false")

        expected_runs = [
            "download_cold_smoke",
            "process_cold_smoke",
            "benchmark",
            "token_present_smoke",
        ]
        missing = [r for r in expected_runs if r not in self.runs]
        if missing:
            errors.append(f"missing runs: {missing}")

        if not self.model_artifact:
            errors.append("model_artifact: missing or empty")

        if self.bundle_passed:
            if not self.started_at_utc:
                errors.append("started_at_utc: empty")
            if not self.completed_at_utc:
                errors.append("completed_at_utc: empty")

            # Verify consistent commit across all runs
            for run_name, run_data in self.runs.items():
                rc = run_data.get("code_commit", "") if isinstance(run_data, dict) else ""
                if rc and rc != self.code_commit:
                    errors.append(f"commit mismatch in '{run_name}': expected '{self.code_commit}', got '{rc}'")

            # WP3: All 5 receipts required for passing bundle
            receipt_errors = self._validate_receipts()
            errors.extend(receipt_errors)

            # Verify consistent model_id, configured_revision, model_revision (P1-2)
            model_ids: set[str] = set()
            configured_revisions: set[str] = set()
            model_revisions: set[str] = set()
            for run_name, run_data in self.runs.items():
                if not isinstance(run_data, dict):
                    continue
                mid = run_data.get("model_id", "")
                if mid:
                    model_ids.add(mid)
                cr = run_data.get("configured_revision", "")
                if cr:
                    configured_revisions.add(cr)
                mr = run_data.get("model_revision", "")
                if mr:
                    model_revisions.add(mr)

            if len(model_ids) > 1:
                errors.append(f"inconsistent model_id across runs: {model_ids}")
            if len(configured_revisions) > 1:
                errors.append(f"inconsistent configured_revision across runs: {configured_revisions}")
            if len(model_revisions) > 1:
                errors.append(f"inconsistent model_revision across runs: {model_revisions}")

            # Also check model_artifact revisions
            if isinstance(self.model_artifact, dict):
                ma_cr = self.model_artifact.get("configured_revision", "")
                ma_mr = self.model_artifact.get("resolved_revision", "")
                if ma_cr and configured_revisions and ma_cr not in configured_revisions:
                    errors.append(
                        f"model_artifact configured_revision '{ma_cr}' not in "
                        f"run configured_revisions {configured_revisions}"
                    )
                if ma_mr and model_revisions and ma_mr not in model_revisions:
                    errors.append(
                        f"model_artifact resolved_revision '{ma_mr}' not in "
                        f"run model_revisions {model_revisions}"
                    )

        return errors

    def _validate_receipts(self) -> list[str]:
        """Validate receipt bindings for a passing bundle.

        WP4: For each required bundle component, this method:
        1. Validates the receipt schema.
        2. Computes the canonical digest of the embedded component.
        3. Compares it with the receipt's ``canonical_content_sha256``.
        4. Verifies commit, model ID, configured revision, resolved revision.
        5. Requires distinct execution IDs.
        6. Requires the receipt's attestation type.
        7. Rejects missing, extra, malformed, or mismatched bindings.
        """
        errors: list[str] = []
        from src.evidence_schemas import ExecutionReceipt, canonical_evidence_sha256

        expected_receipts = [
            "download_cold_smoke",
            "process_cold_smoke",
            "benchmark",
            "token_present_smoke",
            "model_artifact",
        ]

        seen_execution_ids: set[str] = set()

        for key in expected_receipts:
            receipt_data = self.receipts.get(key)
            if receipt_data is None:
                errors.append(f"receipts.{key}: missing — required for passing bundle")
                continue

            # Handle both raw dict (from direct construction) and
            # typed ExecutionReceipt (from evidence_from_dict deserialization)
            if isinstance(receipt_data, dict):
                try:
                    receipt = ExecutionReceipt(**receipt_data)
                except Exception as exc:
                    errors.append(f"receipts.{key}: deserialisation failed: {exc}")
                    continue
            elif isinstance(receipt_data, ExecutionReceipt):
                receipt = receipt_data
            else:
                errors.append(
                    f"receipts.{key}: unexpected type {type(receipt_data).__name__}"
                )
                continue

            # WP-J: a passing, real-measurement bundle must bind receipts
            # that are actually release-ready (exit_code == 0,
            # evidence_origin == real_measurement, git_worktree_clean ==
            # true) — not just structurally valid. receipt.validate() alone
            # would accept a receipt describing a failed or synthetic run.
            if self.evidence_origin == EVIDENCE_ORIGIN_REAL:
                r_errors = receipt_is_release_ready(receipt)
            else:
                r_errors = receipt.validate()
            for r_err in r_errors:
                errors.append(f"receipts.{key}: {r_err}")

            # WP4: Compute canonical digest of embedded component
            comp_data = None
            if key in self.runs:
                comp_data = self.runs[key]
            elif key == "model_artifact":
                comp_data = self.model_artifact

            if comp_data and isinstance(comp_data, dict):
                # Compute canonical content digest of the embedded component
                try:
                    canonical_digest = canonical_evidence_sha256(comp_data)
                except Exception as exc:
                    errors.append(
                        f"receipts.{key}: canonical digest computation failed: {exc}"
                    )
                    continue

                # Compare with receipt's canonical_content_sha256
                if receipt.canonical_content_sha256:
                    if receipt.canonical_content_sha256 != canonical_digest:
                        errors.append(
                            f"receipts.{key}: canonical_content_sha256 "
                            f"'{receipt.canonical_content_sha256}' != computed "
                            f"'{canonical_digest}' — component content mutated"
                        )
                else:
                    errors.append(
                        f"receipts.{key}: canonical_content_sha256 empty — "
                        f"required for content binding"
                    )

                # Check source_file_sha256 if present (transport hash)
                if receipt.source_file_sha256:
                    if not _is_valid_sha256(receipt.source_file_sha256):
                        errors.append(
                            f"receipts.{key}: source_file_sha256 "
                            f"'{receipt.source_file_sha256}' is not a valid "
                            f"SHA-256"
                        )

                # Verify commit, model ID, revisions from embedded component
                comp_commit = comp_data.get("code_commit", "")
                if comp_commit and receipt.code_commit and receipt.code_commit != comp_commit:
                    errors.append(
                        f"receipts.{key}: code_commit '{receipt.code_commit}' "
                        f"!= component code_commit '{comp_commit}'"
                    )
                comp_mid = comp_data.get("model_id", "")
                if comp_mid and receipt.model_id and receipt.model_id != comp_mid:
                    errors.append(
                        f"receipts.{key}: model_id '{receipt.model_id}' "
                        f"!= component model_id '{comp_mid}'"
                    )
                comp_cr = comp_data.get("configured_revision", "")
                if comp_cr and receipt.configured_revision and receipt.configured_revision != comp_cr:
                    errors.append(
                        f"receipts.{key}: configured_revision '{receipt.configured_revision}' "
                        f"!= component configured_revision '{comp_cr}'"
                    )
                comp_rev = comp_data.get("model_revision", "") or comp_data.get("resolved_revision", "")
                if comp_rev and receipt.resolved_revision and receipt.resolved_revision != comp_rev:
                    errors.append(
                        f"receipts.{key}: resolved_revision '{receipt.resolved_revision}' "
                        f"!= component revision '{comp_rev}'"
                    )

            # Legacy component_sha256 check (backward compat transport hash)
            if not receipt.component_sha256 and not receipt.canonical_content_sha256:
                errors.append(f"receipts.{key}: no content digest provided")

            # receipt commit must equal bundle commit
            if receipt.code_commit and receipt.code_commit != self.code_commit:
                errors.append(
                    f"receipts.{key}: code_commit '{receipt.code_commit}' "
                    f"!= bundle commit '{self.code_commit}'"
                )

            # Model ID must match
            if receipt.model_id and receipt.model_id != "amazon/chronos-2":
                errors.append(f"receipts.{key}: model_id '{receipt.model_id}' != amazon/chronos-2")

            # Execution ID uniqueness
            if receipt.execution_id:
                if receipt.execution_id in seen_execution_ids:
                    errors.append(
                        f"receipts.{key}: duplicate execution_id '{receipt.execution_id}'"
                    )
                seen_execution_ids.add(receipt.execution_id)

        return errors

    def to_dict(self) -> dict[str, Any]:
        return dataclasses.asdict(self)


# ---------------------------------------------------------------------------
# Cloud collection session (WP-G)
# ---------------------------------------------------------------------------


@dataclasses.dataclass
class CloudCollectionSession:
    """What a Cloud evidence-collection run actually collected.

    ``collection_receipt`` on ``CloudEvidence`` previously bound to nothing
    — unlike the token-path receipts, which bind their canonical digest to
    ``token_absent_result``/``token_present_result``, there was no record
    for the collection receipt to describe. This is that record: naming the
    session, the code/deployment it ran against, and which of the canonical
    Cloud tests it collected, so ``collection_receipt.canonical_content_sha256``
    has real content to bind.
    """
    evidence_schema_version: str = EVIDENCE_SCHEMA_VERSION
    evidence_type: str = "collection_session"
    evidence_origin: str = ""
    session_id: str = ""
    code_commit: str = ""
    deployed_commit: str = ""
    test_names: list[str] = dataclasses.field(default_factory=list)
    started_at_utc: str = ""
    completed_at_utc: str = ""

    def validate(self) -> list[str]:
        errors: list[str] = []
        if self.evidence_schema_version != EVIDENCE_SCHEMA_VERSION:
            errors.append(f"collection_session: schema version: expected '{EVIDENCE_SCHEMA_VERSION}'")
        if self.evidence_type != "collection_session":
            errors.append("collection_session: evidence_type: expected 'collection_session'")
        if self.evidence_origin not in VALID_EVIDENCE_ORIGINS:
            errors.append(
                f"collection_session: evidence_origin: expected one of "
                f"{VALID_EVIDENCE_ORIGINS}, got '{self.evidence_origin}'"
            )
        if not self.session_id:
            errors.append("collection_session: session_id: empty")
        if not self.code_commit:
            errors.append("collection_session: code_commit: empty")
        # PR #26 review finding P1-2: deployed_commit was not required, so a
        # session describing a different (or no) deployment could still
        # validate as long as its receipt digest was updated to match.
        if not self.deployed_commit:
            errors.append("collection_session: deployed_commit: empty")
        if (
            self.evidence_origin == EVIDENCE_ORIGIN_REAL
            and self.code_commit
            and self.deployed_commit
            and self.code_commit != self.deployed_commit
        ):
            errors.append(
                f"collection_session: code_commit '{self.code_commit}' != "
                f"deployed_commit '{self.deployed_commit}' — a real collection "
                f"session must describe a single deployment"
            )
        if not self.test_names:
            errors.append("collection_session: test_names: empty — must name what was collected")
        else:
            seen_test_names: set[str] = set()
            for name in self.test_names:
                if name not in CANONICAL_CLOUD_TESTS:
                    errors.append(f"collection_session: test_names: unexpected test '{name}'")
                if name in seen_test_names:
                    errors.append(f"collection_session: test_names: duplicate test '{name}'")
                seen_test_names.add(name)
        if not self.started_at_utc:
            errors.append("collection_session: started_at_utc: empty")
        if not self.completed_at_utc:
            errors.append("collection_session: completed_at_utc: empty")
        # Parsed, timezone-aware comparison — not lexical string comparison,
        # which silently mis-orders timestamps with differing UTC offset
        # notation (e.g. "+00:00" vs "Z" vs no offset at all).
        if self.started_at_utc and self.completed_at_utc:
            try:
                if datetime.fromisoformat(self.started_at_utc) > datetime.fromisoformat(self.completed_at_utc):
                    errors.append("collection_session: completed_at_utc before started_at_utc")
            except (ValueError, TypeError):
                errors.append("collection_session: cannot parse timestamps")
        return errors

    def to_dict(self) -> dict[str, Any]:
        return dataclasses.asdict(self)


# ---------------------------------------------------------------------------
# Cloud evidence
# ---------------------------------------------------------------------------


@dataclasses.dataclass
class CloudEvidence:
    evidence_schema_version: str = EVIDENCE_SCHEMA_VERSION
    evidence_type: str = "cloud_stage0"
    evidence_origin: str = ""  # WP-D: no real-default; must be set explicitly
    success: bool = False
    code_commit: str = ""
    git_worktree_clean: bool = False
    started_at_utc: str = ""
    completed_at_utc: str = ""
    python_version: str = ""
    model_id: str = ""
    configured_revision: str = ""
    model_revision: str = ""
    # Token path results (WP8)
    hf_token_present: bool = False  # kept for backward compat
    token_absent_result: TokenPathResult = dataclasses.field(default_factory=TokenPathResult)
    token_present_result: TokenPathResult = dataclasses.field(default_factory=TokenPathResult)
    package_versions: dict[str, str] = dataclasses.field(default_factory=dict)
    machine: MachineSummary = dataclasses.field(default_factory=MachineSummary)
    # Dependency verification
    pip_check_passed: bool = False
    torch_cuda_none: bool = False
    nvidia_packages_absent: bool = False
    dependency_resolver: str = ""
    # Deployment identity (WP6)
    deployed_url: str = ""
    deployed_commit: str = ""
    deployment_time_utc: str = ""
    # Cold and warm phases (WP7)
    cold: SmokePhase = dataclasses.field(default_factory=SmokePhase)
    warm: SmokePhase = dataclasses.field(default_factory=SmokePhase)
    # Resource evidence (WP7) — warm.rss_mb is the canonical warm RSS field
    cold_peak_rss_mb: float = 0.0
    process_peak_rss_mb: float = 0.0
    resource_limit_exceeded: bool = False
    app_restart_occurred: bool = False
    # Concurrency (WP11)
    concurrent_users: int = 0
    sync_mode: str = ""
    timeout_result: str = ""
    concurrency_requests: list[ConcurrencyRequest] = dataclasses.field(default_factory=list)
    # Repeated runs (WP9)
    repeated_runs: list[RepeatedRun] = dataclasses.field(default_factory=list)
    # Acceptance test results (WP12)
    acceptance_tests: list[AcceptanceTestResult] = dataclasses.field(default_factory=list)
    # WP4: Execution bindings — typed receipts for token paths and collection session
    token_absent_receipt: dict[str, Any] = dataclasses.field(default_factory=dict)
    token_present_receipt: dict[str, Any] = dataclasses.field(default_factory=dict)
    collection_receipt: dict[str, Any] = dataclasses.field(default_factory=dict)
    # WP-G: what collection_receipt actually describes — without this,
    # collection_receipt bound to nothing (see CloudCollectionSession above).
    collection_session: dict[str, Any] = dataclasses.field(default_factory=dict)
    error: str = ""

    def validate(self) -> list[str]:
        errors: list[str] = []
        if self.evidence_schema_version != EVIDENCE_SCHEMA_VERSION:
            errors.append(f"schema version: expected '{EVIDENCE_SCHEMA_VERSION}'")
        if self.evidence_type != "cloud_stage0":
            errors.append("evidence_type: expected 'cloud_stage0'")
        if self.evidence_origin not in VALID_EVIDENCE_ORIGINS:
            errors.append(
                f"evidence_origin: expected one of {VALID_EVIDENCE_ORIGINS}, "
                f"got '{self.evidence_origin}'"
            )
        if not self.success:
            errors.append("success: false — cannot publish failed Cloud evidence")
        if not self.code_commit:
            errors.append("code_commit: empty")
        if not self.started_at_utc:
            errors.append("started_at_utc: empty")
        if not self.completed_at_utc:
            errors.append("completed_at_utc: empty")
        if not self.model_id:
            errors.append("model_id: empty")
        if not self.configured_revision:
            errors.append("configured_revision: empty")
        if not self.model_revision:
            errors.append("model_revision: empty")
        if self.configured_revision and self.model_revision and self.configured_revision != self.model_revision:
            errors.append(
                f"revision mismatch: configured '{self.configured_revision}', "
                f"resolved '{self.model_revision}'"
            )
        if not self.package_versions:
            errors.append("package_versions: empty")
        if not self.pip_check_passed:
            errors.append("pip_check_passed: false — dependency verification required")
        if not self.torch_cuda_none:
            errors.append("torch_cuda_none: false — CPU-only Torch required")
        if not self.nvidia_packages_absent:
            errors.append("nvidia_packages_absent: false — no NVIDIA packages allowed")

        # Deployment identity (WP6): code_commit must match deployed_commit
        if not self.deployed_url:
            errors.append("deployed_url: empty — must identify the deployment")
        if not self.deployed_commit:
            errors.append("deployed_commit: empty — must identify the deployed commit")
        if not self.deployment_time_utc:
            errors.append("deployment_time_utc: empty")
        if self.code_commit and self.deployed_commit and self.code_commit != self.deployed_commit:
            errors.append(
                f"deployment identity mismatch: code_commit '{self.code_commit}' != "
                f"deployed_commit '{self.deployed_commit}'"
            )

        # WP4/WP-G/WP-H: Receipt bindings — validate typed execution receipts
        # (only when successful). This is the schema-level check shared by
        # the builder, the publisher, and verify_evidence_manifest.py's
        # recursive validation, so none of them can disagree about what
        # counts as a bound receipt.
        if self.success:
            receipt_fields = [
                ("token_absent_receipt", "token_absent_result"),
                ("token_present_receipt", "token_present_result"),
                ("collection_receipt", None),
            ]
            seen_rec_exec_ids: set[str] = set()
            for rec_field, result_field in receipt_fields:
                rec = getattr(self, rec_field, {})
                if not isinstance(rec, dict) or not rec:
                    errors.append(f"{rec_field}: missing or empty — execution binding required")
                    continue
                try:
                    receipt_obj = ExecutionReceipt(**rec)
                    # WP-J: a passing, real-measurement Cloud record must
                    # bind release-ready receipts (exit_code == 0,
                    # evidence_origin == real_measurement,
                    # git_worktree_clean == true), not merely structurally
                    # valid ones — plain validate() would accept a receipt
                    # describing a failed command.
                    if self.evidence_origin == EVIDENCE_ORIGIN_REAL:
                        rec_errors = receipt_is_release_ready(receipt_obj)
                    else:
                        rec_errors = receipt_obj.validate()
                    for r_err in rec_errors:
                        errors.append(f"{rec_field}: {r_err}")
                    # WP-H: a synthetic receipt can never bind real Cloud
                    # evidence, regardless of the top-level CLI flag used to
                    # build this record — production mode is defined by
                    # every nested receipt's own origin agreeing with it.
                    if receipt_obj.evidence_origin != self.evidence_origin:
                        errors.append(
                            f"{rec_field}: evidence_origin "
                            f"'{receipt_obj.evidence_origin}' != Cloud record "
                            f"evidence_origin '{self.evidence_origin}'"
                        )
                    # Check commit matches deployed_commit
                    if receipt_obj.code_commit and self.deployed_commit and receipt_obj.code_commit != self.deployed_commit:
                        errors.append(
                            f"{rec_field}: code_commit '{receipt_obj.code_commit}' "
                            f"!= deployed_commit '{self.deployed_commit}'"
                        )
                    # Check model ID
                    if receipt_obj.model_id and receipt_obj.model_id != "amazon/chronos-2":
                        errors.append(f"{rec_field}: model_id '{receipt_obj.model_id}' != amazon/chronos-2")
                    # Check revision matches
                    if receipt_obj.resolved_revision and self.model_revision and receipt_obj.resolved_revision != self.model_revision:
                        errors.append(
                            f"{rec_field}: resolved_revision '{receipt_obj.resolved_revision}' "
                            f"!= Cloud model_revision '{self.model_revision}'"
                        )
                    # WP-G: token receipts bind the canonical digest of the
                    # token path result they describe; the collection
                    # receipt binds the canonical digest of collection_session.
                    if result_field:
                        result = getattr(self, result_field, None)
                        if result and hasattr(result, "run_id") and result.run_id:
                            if receipt_obj.execution_id and receipt_obj.execution_id != result.run_id:
                                errors.append(
                                    f"{rec_field}: execution_id '{receipt_obj.execution_id}' "
                                    f"!= {result_field}.run_id '{result.run_id}'"
                                )
                        if result is not None and hasattr(result, "to_dict"):
                            expected_digest = canonical_evidence_sha256(result.to_dict())
                            if not receipt_obj.canonical_content_sha256:
                                errors.append(
                                    f"{rec_field}: canonical_content_sha256 empty — "
                                    f"required to bind {result_field}"
                                )
                            elif receipt_obj.canonical_content_sha256 != expected_digest:
                                errors.append(
                                    f"{rec_field}: canonical_content_sha256 "
                                    f"'{receipt_obj.canonical_content_sha256}' != "
                                    f"computed '{expected_digest}' from {result_field}"
                                )
                    else:
                        # collection_receipt: bind against collection_session
                        session_data = self.collection_session
                        if not isinstance(session_data, dict) or not session_data:
                            errors.append(
                                "collection_session: missing or empty — "
                                "collection_receipt has nothing to bind to"
                            )
                        else:
                            try:
                                session_obj = CloudCollectionSession(**session_data)
                            except Exception as exc:
                                errors.append(f"collection_session: construction failed: {exc}")
                                session_obj = None
                            if session_obj is not None:
                                for se in session_obj.validate():
                                    errors.append(f"collection_session: {se}")
                                if session_obj.evidence_origin != self.evidence_origin:
                                    errors.append(
                                        f"collection_session: evidence_origin "
                                        f"'{session_obj.evidence_origin}' != Cloud "
                                        f"record evidence_origin '{self.evidence_origin}'"
                                    )
                                # PR #26 review finding P1-2: a collection
                                # session naming a different deployment could
                                # still validate as long as its receipt
                                # digest was updated to match — bind both
                                # commit fields to the enclosing record, not
                                # just the session's own internal consistency.
                                if session_obj.code_commit != self.code_commit:
                                    errors.append(
                                        f"collection_session: code_commit "
                                        f"'{session_obj.code_commit}' != Cloud "
                                        f"record code_commit '{self.code_commit}'"
                                    )
                                if session_obj.deployed_commit != self.deployed_commit:
                                    errors.append(
                                        f"collection_session: deployed_commit "
                                        f"'{session_obj.deployed_commit}' != Cloud "
                                        f"record deployed_commit '{self.deployed_commit}'"
                                    )
                                expected_digest = canonical_evidence_sha256(session_obj.to_dict())
                                if not receipt_obj.canonical_content_sha256:
                                    errors.append(
                                        "collection_receipt: canonical_content_sha256 "
                                        "empty — required to bind collection_session"
                                    )
                                elif receipt_obj.canonical_content_sha256 != expected_digest:
                                    errors.append(
                                        f"collection_receipt: canonical_content_sha256 "
                                        f"'{receipt_obj.canonical_content_sha256}' != "
                                        f"computed '{expected_digest}' from collection_session"
                                    )
                    # Execution ID uniqueness
                    if receipt_obj.execution_id:
                        if receipt_obj.execution_id in seen_rec_exec_ids:
                            errors.append(
                                f"{rec_field}: duplicate execution_id '{receipt_obj.execution_id}'"
                            )
                        seen_rec_exec_ids.add(receipt_obj.execution_id)
                except Exception as exc:
                    errors.append(f"{rec_field}: receipt construction failed: {exc}")

        # WP8: Resource-limit and restart checks — must not have exceeded limits
        if self.resource_limit_exceeded:
            errors.append("resource_limit_exceeded: true — resource limits were exceeded")
        if self.app_restart_occurred:
            errors.append("app_restart_occurred: true — application restarted unexpectedly")

        # WP8: Dependency resolver must be non-empty
        if not self.dependency_resolver:
            errors.append("dependency_resolver: empty — must identify the resolver used")

        # WP2: Strict Cloud token-path validation — both paths must be
        # attempted and successful for a successful Cloud evidence record.
        # The legacy hf_token_present Boolean is NOT used as the release gate.
        errors.extend(f"token_absent_result: {e}" for e in self.token_absent_result.validate())
        errors.extend(f"token_present_result: {e}" for e in self.token_present_result.validate())
        if self.success:
            if not self.token_absent_result.attempted:
                errors.append("token_absent_result: must be attempted for successful Cloud evidence")
            if not self.token_absent_result.success:
                errors.append("token_absent_result: must be successful for successful Cloud evidence")
            if not self.token_present_result.attempted:
                errors.append("token_present_result: must be attempted for successful Cloud evidence")
            if not self.token_present_result.success:
                errors.append("token_present_result: must be successful for successful Cloud evidence")
            # Both token path revisions must equal the Cloud model revision
            tar_cr = self.token_absent_result.configured_revision
            tar_rr = self.token_absent_result.resolved_revision
            tpr_cr = self.token_present_result.configured_revision
            tpr_rr = self.token_present_result.resolved_revision
            if tar_cr and tar_cr != self.model_revision:
                errors.append(
                    f"token_absent_result configured_revision '{tar_cr}' != "
                    f"Cloud model_revision '{self.model_revision}'"
                )
            if tar_rr and tar_rr != self.model_revision:
                errors.append(
                    f"token_absent_result resolved_revision '{tar_rr}' != "
                    f"Cloud model_revision '{self.model_revision}'"
                )
            if tpr_cr and tpr_cr != self.model_revision:
                errors.append(
                    f"token_present_result configured_revision '{tpr_cr}' != "
                    f"Cloud model_revision '{self.model_revision}'"
                )
            if tpr_rr and tpr_rr != self.model_revision:
                errors.append(
                    f"token_present_result resolved_revision '{tpr_rr}' != "
                    f"Cloud model_revision '{self.model_revision}'"
                )
            # Unique run IDs across both paths
            if (self.token_absent_result.run_id
                    and self.token_present_result.run_id
                    and self.token_absent_result.run_id == self.token_present_result.run_id):
                errors.append("token paths: run_ids must be distinct across token-absent and token-present runs")

        # Cold phase
        if self.cold.total_seconds <= 0:
            errors.append("cold.total_seconds: missing — cold forecast required")
        if self.cold.cache_state not in {CACHE_STATE_DOWNLOAD_COLD, CACHE_STATE_PROCESS_COLD}:
            errors.append(
                f"cold.cache_state: must be '{CACHE_STATE_DOWNLOAD_COLD}' or "
                f"'{CACHE_STATE_PROCESS_COLD}', got '{self.cold.cache_state}'"
            )
        if self.cold.pipeline_call_count != 1:
            errors.append(f"cold.pipeline_call_count: expected 1, got {self.cold.pipeline_call_count}")
        if self.cold.rss_mb <= 0:
            errors.append("cold.rss_mb: must be > 0 — memory measurement required (WP7)")

        # Warm phase
        if self.warm.total_seconds <= 0:
            errors.append("warm.total_seconds: missing — warm forecast required")
        if self.warm.cache_state != CACHE_STATE_WARM:
            errors.append(
                f"warm.cache_state: must be '{CACHE_STATE_WARM}', "
                f"got '{self.warm.cache_state}'"
            )
        if not self.warm.pipeline_reused:
            errors.append("warm.pipeline_reused: false — pipeline must be reused")
        if self.warm.pipeline_call_count != 1:
            errors.append(f"warm.pipeline_call_count: expected 1, got {self.warm.pipeline_call_count}")
        if self.warm.model_load_seconds > 0.5:
            errors.append(
                f"warm.model_load_seconds: expected near-zero (reused pipeline), "
                f"got {self.warm.model_load_seconds}"
            )
        if self.warm.rss_mb <= 0:
            errors.append("warm.rss_mb: must be > 0 — memory measurement required (WP7)")

        # Resource evidence (WP7)
        if self.cold_peak_rss_mb <= 0:
            errors.append("cold_peak_rss_mb: must be > 0 — peak memory required")
        if self.process_peak_rss_mb <= 0:
            errors.append("process_peak_rss_mb: must be > 0 — process peak memory required")

        # WP5: Successful concurrency gate — at least 2 successful overlapping
        # requests with pairwise interval intersection.
        if self.concurrent_users < 2:
            errors.append(
                f"concurrent_users: expected >= 2, got {self.concurrent_users} "
                f"— concurrency measurement required before public sharing"
            )
        if self.concurrent_users >= 2:
            if len(self.concurrency_requests) < self.concurrent_users:
                errors.append(
                    f"concurrency_requests: expected at least {self.concurrent_users}, "
                    f"got {len(self.concurrency_requests)}"
                )
            for req in self.concurrency_requests:
                errors.extend(f"concurrency_request: {e}" for e in req.validate())

            # Prove concurrency using pairwise interval intersection across
            # successful request windows (WP5). Independent of input order.
            successful_reqs = [r for r in self.concurrency_requests if r.success]
            if len(successful_reqs) >= 2:
                # Check every pair for overlap
                any_overlap = False
                for i in range(len(successful_reqs)):
                    for j in range(i + 1, len(successful_reqs)):
                        a, b = successful_reqs[i], successful_reqs[j]
                        if a.start_time_utc and a.completion_time_utc and b.start_time_utc and b.completion_time_utc:
                            a_start = datetime.fromisoformat(a.start_time_utc)
                            a_end = datetime.fromisoformat(a.completion_time_utc)
                            b_start = datetime.fromisoformat(b.start_time_utc)
                            b_end = datetime.fromisoformat(b.completion_time_utc)
                            if min(a_end, b_end) > max(a_start, b_start):
                                any_overlap = True
                                break
                    if any_overlap:
                        break
                if not any_overlap:
                    errors.append(
                        "concurrency: no overlapping pair found among successful "
                        "requests — genuine concurrency not proven"
                    )
            elif len(successful_reqs) < 2:
                errors.append(
                    f"concurrency: need at least 2 successful requests for "
                    f"overlap check, got {len(successful_reqs)}"
                )

            # Also require: one process pipeline construction, no crash,
            # timeout outcome recorded, semaphore release after failure
            if not self.cold.pipeline_call_count == 1:
                errors.append("concurrency: cold pipeline must be constructed exactly once")
            if self.app_restart_occurred:
                errors.append("concurrency: app restart occurred — process crash detected")
            # WP8: Timeout semantics — must be a known outcome
            valid_timeout_results = {"no_timeout", "timeout_occurred", "timeout_recovered"}
            if not self.timeout_result:
                errors.append("concurrency: timeout_result must be recorded")
            elif self.timeout_result not in valid_timeout_results:
                errors.append(
                    f"concurrency: timeout_result '{self.timeout_result}' not in "
                    f"{valid_timeout_results}"
                )
            if self.timeout_result == "timeout_occurred":
                # Timeout without recovery is a failure
                if not self.error:
                    errors.append("concurrency: timeout_occurred but no recovery error recorded")
            if self.timeout_result == "timeout_recovered":
                # Must have recovery evidence: configuration_preserved must pass
                conf_test = next(
                    (t for t in self.acceptance_tests if t.test_name == "configuration_preserved"),
                    None,
                )
                if conf_test and not conf_test.passed:
                    errors.append("concurrency: timeout_recovered but configuration_preserved test failed")

        # WP4: Successful repeated-run gate — at least 3 successful warm runs
        if self.success:
            counted = 0
            seen_run_numbers: set[int] = set()
            for run in self.repeated_runs:
                errors.extend(f"repeated_run: {e}" for e in run.validate())
                if run.run_number <= 0:
                    errors.append(f"repeated_run: run_number must be >= 1, got {run.run_number}")
                if run.run_number in seen_run_numbers:
                    errors.append(f"repeated_run: duplicate run_number {run.run_number}")
                seen_run_numbers.add(run.run_number)
                # A counted warm run must satisfy ALL of the following conditions
                is_countable = (
                    run.success
                    and run.started_at_utc
                    and run.completed_at_utc
                    and run.total_seconds > 0
                    and run.inference_seconds > 0
                    and run.cache_state == CACHE_STATE_WARM
                    and run.pipeline_reused
                    and run.pipeline_construction_count == 1
                    and run.resolved_revision == self.model_revision
                    and run.rss_mb > 0
                    and run.error_code == ""
                )
                if is_countable:
                    counted += 1
            if counted < 3:
                errors.append(
                    f"repeated_runs: need at least 3 counted successful warm runs, "
                    f"got {counted} out of {len(self.repeated_runs)}"
                )

        # WP6 + WP9: Complete acceptance-test gate — every required test must pass
        if self.success:
            required_tests = list(CANONICAL_CLOUD_TESTS)
            seen_tests: set[str] = set()
            for t in self.acceptance_tests:
                t_errors = t.validate()
                errors.extend(f"acceptance_test '{t.test_name}': {e}" for e in t_errors)
                if not t.test_name:
                    continue
                if t.test_name in seen_tests:
                    errors.append(f"acceptance_test: duplicate test_name '{t.test_name}'")
                seen_tests.add(t.test_name)
                if t.test_name in required_tests and not t.passed:
                    errors.append(f"acceptance_test '{t.test_name}': must pass")
                if t.test_name not in required_tests:
                    errors.append(f"acceptance_test: unexpected test_name '{t.test_name}'")
            missing = sorted(set(required_tests) - seen_tests)
            if missing:
                errors.append(f"acceptance_tests: missing required tests: {missing}")

        return errors

    def to_dict(self) -> dict[str, Any]:
        d = dataclasses.asdict(self)
        d["machine"] = self.machine.to_dict()
        d["cold"] = self.cold.to_dict()
        d["warm"] = self.warm.to_dict()
        d["token_absent_result"] = self.token_absent_result.to_dict()
        d["token_present_result"] = self.token_present_result.to_dict()
        d["concurrency_requests"] = [r.to_dict() for r in self.concurrency_requests]
        d["repeated_runs"] = [r.to_dict() for r in self.repeated_runs]
        d["acceptance_tests"] = [t.to_dict() for t in self.acceptance_tests]
        return d


# ---------------------------------------------------------------------------
# Deserialisation helpers
# ---------------------------------------------------------------------------

_EVIDENCE_TYPE_MAP: dict[str, type] = {
    "smoke_test": SmokeEvidence,
    "benchmark_suite": BenchmarkSuiteEvidence,
    "model_artifact": ModelArtifactEvidence,
    "local_stage0_bundle": LocalStage0Bundle,
    "cloud_stage0": CloudEvidence,
    "execution_receipt": ExecutionReceipt,
    "collection_session": CloudCollectionSession,
}


def _filter_known_fields(
    data: dict[str, Any],
    cls: type,
    *,
    strict: bool = False,
    path: str = "",
) -> dict[str, Any]:
    """Filter a dict to only include fields that exist in the dataclass.

    Two modes:

    - ``strict=False`` (migration-only, permissive): unknown fields are
      dropped with a ``UserWarning``. This mode must never be used to
      publish release evidence, mark evidence release-ready, or update the
      release manifest — the publisher, bundle builder, Cloud builder,
      recursive validator, and manifest verifier all call strict mode.
    - ``strict=True`` (release): any unknown field is a hard ``ValueError``
      with a path-qualified message, so schema drift, a wrong
      ``evidence_type``, a misspelled field, or a nested record attached to
      the wrong type can never be silently discarded.

    ``path`` is the human-readable location of *data* (e.g.
    ``scenarios[2].samples``) used to qualify error messages.
    """
    if not hasattr(cls, "__dataclass_fields__"):
        return data
    known = set(cls.__dataclass_fields__.keys())
    unknown = set(data.keys()) - known
    if unknown:
        label = f"{path}.{cls.__name__}" if path else cls.__name__
        if strict:
            raise ValueError(
                f"{label}: unknown field(s) {sorted(unknown)} — strict "
                f"release deserialisation rejects unknown fields"
            )
        import warnings
        warnings.warn(
            f"evidence_from_dict: dropping unknown fields from {cls.__name__}: "
            f"{sorted(unknown)}", UserWarning, stacklevel=2
        )
    return {k: v for k, v in data.items() if k in known}


def evidence_from_dict(data: dict[str, Any], *, strict: bool = False) -> Any:
    """Deserialise a dict into the appropriate evidence type based on
    ``evidence_type`` field.

    Operates on a deep copy — does NOT mutate the caller's data (WP3).

    ``strict=False`` (default) is the migration-only permissive mode:
    unknown producer-only fields are silently dropped with a warning. It
    is NOT a release path — it cannot publish evidence, cannot mark
    evidence release-ready, and cannot update the release manifest (all
    release callers pass ``strict=True``).

    ``strict=True`` rejects unknown fields at every depth with a
    path-qualified ``ValueError``, so a wrong ``evidence_type`` can never
    silently discard fields and construct another type, and a misspelled
    field or a nested record attached to the wrong type fails loudly.

    Raises ``ValueError`` for unknown types, missing evidence_type, or (in
    strict mode) unknown fields.
    """
    import copy
    d = copy.deepcopy(data)
    etype = d.get("evidence_type", "")
    if not etype:
        raise ValueError("evidence_type field is missing from evidence data")
    cls = _EVIDENCE_TYPE_MAP.get(etype)
    if cls is None:
        raise ValueError(f"Unknown evidence_type: '{etype}'")

    def _strict_filter(nested: dict[str, Any], nested_cls: type, nested_path: str) -> dict[str, Any]:
        return _filter_known_fields(nested, nested_cls, strict=strict, path=nested_path)

    # Recursively convert nested dicts into typed objects
    if etype == "smoke_test":
        if "cold" in d and isinstance(d["cold"], dict):
            d["cold"] = SmokePhase(**_strict_filter(d["cold"], SmokePhase, "cold"))
        if "warm" in d and isinstance(d["warm"], dict):
            d["warm"] = SmokePhase(**_strict_filter(d["warm"], SmokePhase, "warm"))
        if "machine" in d and isinstance(d["machine"], dict):
            d["machine"] = MachineSummary(**_strict_filter(d["machine"], MachineSummary, "machine"))
        if "cache_preflight" in d and isinstance(d["cache_preflight"], dict):
            d["cache_preflight"] = CachePreflight(**_strict_filter(d["cache_preflight"], CachePreflight, "cache_preflight"))
        if "token_absent_result" in d and isinstance(d["token_absent_result"], dict):
            d["token_absent_result"] = TokenPathResult(**_strict_filter(d["token_absent_result"], TokenPathResult, "token_absent_result"))
        if "token_present_result" in d and isinstance(d["token_present_result"], dict):
            d["token_present_result"] = TokenPathResult(**_strict_filter(d["token_present_result"], TokenPathResult, "token_present_result"))
    elif etype == "benchmark_suite":
        if "cache_preflight" in d and isinstance(d["cache_preflight"], dict):
            d["cache_preflight"] = CachePreflight(**_strict_filter(d["cache_preflight"], CachePreflight, "cache_preflight"))
        if "scenarios" in d:
            scenarios = []
            for i, sc in enumerate(d["scenarios"]):
                scr = copy.deepcopy(sc)
                if "samples" in scr:
                    scr["samples"] = [
                        BenchmarkSampleRecord(
                            **_strict_filter(s, BenchmarkSampleRecord, f"scenarios[{i}].samples")
                        )
                        for s in scr["samples"]
                    ]
                scenarios.append(
                    BenchmarkScenarioRecord(
                        **_strict_filter(scr, BenchmarkScenarioRecord, f"scenarios[{i}]")
                    )
                )
            d["scenarios"] = scenarios
    elif etype == "model_artifact":
        if "files" in d:
            d["files"] = [
                ModelArtifactFile(
                    **_strict_filter(f, ModelArtifactFile, f"files[{i}]")
                )
                for i, f in enumerate(d["files"])
            ]
    elif etype == "cloud_stage0":
        if "cold" in d and isinstance(d["cold"], dict):
            d["cold"] = SmokePhase(**_strict_filter(d["cold"], SmokePhase, "cold"))
        if "warm" in d and isinstance(d["warm"], dict):
            d["warm"] = SmokePhase(**_strict_filter(d["warm"], SmokePhase, "warm"))
        if "machine" in d and isinstance(d["machine"], dict):
            d["machine"] = MachineSummary(**_strict_filter(d["machine"], MachineSummary, "machine"))
        if "token_absent_result" in d and isinstance(d["token_absent_result"], dict):
            d["token_absent_result"] = TokenPathResult(**_strict_filter(d["token_absent_result"], TokenPathResult, "token_absent_result"))
        if "token_present_result" in d and isinstance(d["token_present_result"], dict):
            d["token_present_result"] = TokenPathResult(**_strict_filter(d["token_present_result"], TokenPathResult, "token_present_result"))
        # WP4: Receipt fields — preserve as dicts for construction
        # These are stored as dict[str, Any] in CloudEvidence and validated
        # inline rather than deserialized to typed objects here (the validate
        # method constructs ExecutionReceipt from the raw dict).
        if "repeated_runs" in d and isinstance(d["repeated_runs"], list):
            d["repeated_runs"] = [
                RepeatedRun(
                    **_strict_filter(r, RepeatedRun, f"repeated_runs[{i}]")
                )
                for i, r in enumerate(d["repeated_runs"])
            ]
        if "concurrency_requests" in d and isinstance(d["concurrency_requests"], list):
            d["concurrency_requests"] = [
                ConcurrencyRequest(
                    **_strict_filter(r, ConcurrencyRequest, f"concurrency_requests[{i}]")
                )
                for i, r in enumerate(d["concurrency_requests"])
            ]
        if "acceptance_tests" in d and isinstance(d["acceptance_tests"], list):
            d["acceptance_tests"] = [
                AcceptanceTestResult(
                    **_strict_filter(t, AcceptanceTestResult, f"acceptance_tests[{i}]")
                )
                for i, t in enumerate(d["acceptance_tests"])
            ]

    elif etype == "local_stage0_bundle":
        if "receipts" in d and isinstance(d["receipts"], dict):
            receipts = {}
            for rec_key, rec_data in d["receipts"].items():
                if isinstance(rec_data, dict):
                    receipts[rec_key] = ExecutionReceipt(
                        **_strict_filter(rec_data, ExecutionReceipt, f"receipts.{rec_key}")
                    )
                else:
                    receipts[rec_key] = rec_data
            d["receipts"] = receipts

    return cls(**_filter_known_fields(d, cls, strict=strict, path=""))
