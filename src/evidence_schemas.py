"""Typed evidence schemas for Stage 0 smoke, benchmark, and bundle records.

Schema version 2 — replaces ad hoc dictionary evidence with typed models.

Each model class provides:
- Fields with defaults
- ``validate()`` method returning a list of error messages
- ``to_dict()`` for JSON serialisation
"""

from __future__ import annotations

import dataclasses
import json
from datetime import datetime, timezone
from typing import Any

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------
EVIDENCE_SCHEMA_VERSION = "2"


# ---------------------------------------------------------------------------
# Cache-state constants
# ---------------------------------------------------------------------------
CACHE_STATE_DOWNLOAD_COLD = "download_cold"
CACHE_STATE_PROCESS_COLD = "process_cold_cached_weights"
CACHE_STATE_WARM = "same_process_warm"
CACHE_STATE_AGGREGATE = "aggregate"
CACHE_STATE_SYNTHETIC = "synthetic_fake"

VALID_INITIAL_CACHE_STATES = {CACHE_STATE_DOWNLOAD_COLD, CACHE_STATE_PROCESS_COLD}
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
    hf_token_present: bool = False
    initial_cache_state: str = ""
    cold: SmokePhase = dataclasses.field(default_factory=SmokePhase)
    warm: SmokePhase = dataclasses.field(default_factory=SmokePhase)
    package_versions: dict[str, str] = dataclasses.field(default_factory=dict)
    machine: MachineSummary = dataclasses.field(default_factory=MachineSummary)
    cache_preflight: dict[str, Any] = dataclasses.field(default_factory=dict)
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
    scenarios: list[BenchmarkScenarioRecord] = dataclasses.field(default_factory=list)

    def validate(self) -> list[str]:
        errors: list[str] = []

        if self.evidence_schema_version != EVIDENCE_SCHEMA_VERSION:
            errors.append(f"schema version: expected '{EVIDENCE_SCHEMA_VERSION}', got '{self.evidence_schema_version}'")
        if self.evidence_type != "benchmark_suite":
            errors.append(f"evidence_type: expected 'benchmark_suite', got '{self.evidence_type}'")
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

        if self.suite_passed:
            if not self.started_at_utc:
                errors.append("started_at_utc: empty")
            if not self.completed_at_utc:
                errors.append("completed_at_utc: empty")

            # Validate required scenarios
            scenario_names = {s.scenario for s in self.scenarios}
            required = {"weekly_260_13", "panel_5_series", "10_rolling_calls", "failure_and_retry"}
            missing = required - scenario_names
            if missing:
                errors.append(f"missing required scenarios: {sorted(missing)}")

            for sc in self.scenarios:
                errors.extend(sc.validate())

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
    code_commit: str = ""
    git_worktree_clean: bool = False
    model_id: str = ""
    configured_revision: str = ""
    resolved_revision: str = ""
    snapshot_commit: str = ""
    shard_count: int = 0  # total files in snapshot (config + weights)
    weight_shard_count: int = 0  # number of model weight files only
    total_bytes: int = 0
    files: list[ModelArtifactFile] = dataclasses.field(default_factory=list)
    manifest_sha256: str = ""

    def validate(self) -> list[str]:
        errors: list[str] = []
        if self.evidence_schema_version != EVIDENCE_SCHEMA_VERSION:
            errors.append(f"schema version: expected '{EVIDENCE_SCHEMA_VERSION}'")
        if self.evidence_type != "model_artifact":
            errors.append(f"evidence_type: expected 'model_artifact'")
        if not self.code_commit:
            errors.append("code_commit: empty")
        if not self.model_id:
            errors.append("model_id: empty")
        if not self.configured_revision:
            errors.append("configured_revision: empty")
        if not self.resolved_revision:
            errors.append("resolved_revision: empty")
        if self.configured_revision and self.resolved_revision and self.configured_revision != self.resolved_revision:
            errors.append(
                f"revision mismatch: configured '{self.configured_revision}', "
                f"resolved '{self.resolved_revision}'"
            )
        if not self.files:
            errors.append("files: empty — no weight files recorded")
        if not self.manifest_sha256:
            errors.append("manifest_sha256: empty")
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
    bundle_passed: bool = False
    code_commit: str = ""
    git_worktree_clean: bool = False
    started_at_utc: str = ""
    completed_at_utc: str = ""
    python_version: str = ""
    runs: dict[str, Any] = dataclasses.field(default_factory=dict)
    model_artifact: dict[str, Any] = dataclasses.field(default_factory=dict)

    def validate(self) -> list[str]:
        errors: list[str] = []

        if self.evidence_schema_version != EVIDENCE_SCHEMA_VERSION:
            errors.append(f"schema version: expected '{EVIDENCE_SCHEMA_VERSION}'")
        if self.evidence_type != "local_stage0_bundle":
            errors.append(f"evidence_type: expected 'local_stage0_bundle'")
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
    success: bool = False
    code_commit: str = ""
    git_worktree_clean: bool = False
    started_at_utc: str = ""
    completed_at_utc: str = ""
    python_version: str = ""
    model_id: str = ""
    configured_revision: str = ""
    model_revision: str = ""
    hf_token_present: bool = False
    package_versions: dict[str, str] = dataclasses.field(default_factory=dict)
    machine: MachineSummary = dataclasses.field(default_factory=MachineSummary)
    cold: SmokePhase = dataclasses.field(default_factory=SmokePhase)
    warm: SmokePhase = dataclasses.field(default_factory=SmokePhase)
    concurrent_users: int = 0
    queue_time_seconds: float = 0.0
    error: str = ""
    # Dependency verification
    pip_check_passed: bool = False
    torch_cuda_none: bool = False
    nvidia_packages_absent: bool = False

    def validate(self) -> list[str]:
        errors: list[str] = []
        if self.evidence_schema_version != EVIDENCE_SCHEMA_VERSION:
            errors.append(f"schema version: expected '{EVIDENCE_SCHEMA_VERSION}'")
        if self.evidence_type != "cloud_stage0":
            errors.append(f"evidence_type: expected 'cloud_stage0'")
        if not self.success:
            errors.append("success: false — cannot publish failed Cloud evidence")
        if not self.code_commit:
            errors.append("code_commit: empty")
        if not self.git_worktree_clean:
            errors.append("git_worktree_clean: false — worktree must be clean")
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
        # Cold phase must have timing
        if self.cold.total_seconds <= 0:
            errors.append("cold.total_seconds: missing — cold forecast required")
        if not self.cold.cache_state:
            errors.append("cold.cache_state: empty")
        # Warm phase must have timing and reuse
        if self.warm.total_seconds <= 0:
            errors.append("warm.total_seconds: missing — warm forecast required")
        if not self.warm.cache_state:
            errors.append("warm.cache_state: empty")
        if not self.warm.pipeline_reused:
            errors.append("warm.pipeline_reused: false — pipeline must be reused")
        # Concurrency must be recorded
        if self.concurrent_users <= 0:
            errors.append("concurrent_users: must be at least 1")
        return errors

    def to_dict(self) -> dict[str, Any]:
        d = dataclasses.asdict(self)
        d["machine"] = self.machine.to_dict()
        d["cold"] = self.cold.to_dict()
        d["warm"] = self.warm.to_dict()
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
}


def evidence_from_dict(data: dict[str, Any]) -> Any:
    """Deserialise a dict into the appropriate evidence type based on
    ``evidence_type`` field.

    Operates on a deep copy — does NOT mutate the caller's data (WP3).

    Raises ``ValueError`` for unknown types or missing evidence_type.
    """
    import copy
    d = copy.deepcopy(data)
    etype = d.get("evidence_type", "")
    if not etype:
        raise ValueError("evidence_type field is missing from evidence data")
    cls = _EVIDENCE_TYPE_MAP.get(etype)
    if cls is None:
        raise ValueError(f"Unknown evidence_type: '{etype}'")

    # Recursively convert nested dicts into typed objects
    if etype == "smoke_test":
        if "cold" in d and isinstance(d["cold"], dict):
            d["cold"] = SmokePhase(**d["cold"])
        if "warm" in d and isinstance(d["warm"], dict):
            d["warm"] = SmokePhase(**d["warm"])
        if "machine" in d and isinstance(d["machine"], dict):
            d["machine"] = MachineSummary(**d["machine"])
    elif etype == "benchmark_suite":
        if "scenarios" in d:
            scenarios = []
            for sc in d["scenarios"]:
                if "samples" in sc:
                    scr = copy.deepcopy(sc)
                    scr["samples"] = [BenchmarkSampleRecord(**s) for s in scr["samples"]]
                else:
                    scr = copy.deepcopy(sc)
                scenarios.append(BenchmarkScenarioRecord(**scr))
            d["scenarios"] = scenarios
    elif etype == "model_artifact":
        if "files" in d:
            d["files"] = [ModelArtifactFile(**f) for f in d["files"]]
    elif etype == "cloud_stage0":
        if "cold" in d and isinstance(d["cold"], dict):
            d["cold"] = SmokePhase(**d["cold"])
        if "warm" in d and isinstance(d["warm"], dict):
            d["warm"] = SmokePhase(**d["warm"])
        if "machine" in d and isinstance(d["machine"], dict):
            d["machine"] = MachineSummary(**d["machine"])

    return cls(**d)
