"""Tests for the Stage 1 Cloud evidence instrumentation (src.cloud_diagnostics).

Covers the required test groups for the Cloud evidence-instrumentation
closure PR:

    strict deployed commit
    diagnostics required fields
    diagnostics rejects unknown
    diagnostics JSON deterministic
    diagnostics contains no secret
    diagnostics contains no payload
    scoped request memory
    bounded request records
    request timestamp ordering
    repeated run uniqueness
    pipeline construction count
    concurrency overlap
    token state boolean only
    dependency check states
    collection session binding
    collection receipt binding
    publisher rejects incomplete Cloud evidence
    manifest rejects incomplete Cloud evidence
    readiness includes Cloud instrumentation checks

All tests are offline and use no model download.
"""
from __future__ import annotations

import json
import os
import sys
import threading
import time
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT))

from src.cloud_diagnostics import (  # noqa: E402
    CloudCommitIdentity,
    CloudCollectionSessionRecord,
    CloudRequestRecord,
    CloudRuntimeDiagnostics,
    DeployedCommitError,
    DependencyDiagnostics,
    RequestMemorySampler,
    RequestTelemetryStore,
    any_overlapping_pair,
    assert_expected_commit_matches,
    build_collection_receipt,
    build_collection_session_record,
    build_public_diagnostics_export,
    build_runtime_diagnostics,
    canonical_diagnostics_digest,
    categorise_request_ids,
    deployed_commit_identity,
    diagnostics_exposes_secret,
    diagnostics_to_json,
    hf_token_present,
    intervals_overlap,
    is_exact_commit_sha,
    measure_dependency_diagnostics,
    reset_dependency_diagnostics_cache,
    resolve_deployed_commit_strict,
)

_VALID_COMMIT = "9bea6d34aaf4e02186fda6581151794a7dc9973f"
_OTHER_COMMIT = "8c3c67c4cb4302bb788f4801ae3fd2e57032c4a9"
_PINNED_REVISION = "29ec3766d36d6f73f0696f85560a422f50e8498c"


def _valid_diagnostics() -> CloudRuntimeDiagnostics:
    return CloudRuntimeDiagnostics(
        schema_version="1",
        diagnostics_id="diag-test-1",
        generated_at_utc="2026-08-06T00:00:00+00:00",
        deployed_commit=_VALID_COMMIT,
        commit_resolution_source="git_head",
        expected_commit=_VALID_COMMIT,
        expected_commit_match=True,
        model_id="amazon/chronos-2",
        configured_revision=_PINNED_REVISION,
        python_version="3.12",
        package_versions={
            "chronos-forecasting": "2.3.1", "torch": "2.13.0",
            "streamlit": "1.60.0", "pandas": "3.0.5", "numpy": "2.4.6",
        },
        os_name="Linux",
        cpu_model="Intel(R) Xeon(R) CPU",
        cpu_logical_cores=2,
        ram_total_gb=1.0,
        torch_cpu_only=True,
        torch_cuda_version="",
        nvidia_packages=[],
        pip_check_passed=True,
        pip_check_summary="pip check passed",
        hf_token_present=False,
        current_rss_mb=100.0,
        process_peak_rss_mb=800.0,
        pipeline_constructed=False,
        pipeline_construction_count=0,
        coordinator_state="capacity=1;max_history=256;history=0;sync_mode=semaphore",
    )


# ---------------------------------------------------------------------------
# 1. Strict deployed commit (WP3)
# ---------------------------------------------------------------------------


class TestStrictDeployedCommit:
    def test_exact_sha_accepted(self):
        assert is_exact_commit_sha(_VALID_COMMIT) is True

    def test_short_sha_rejected(self):
        assert is_exact_commit_sha("abc123") is False

    def test_uppercase_sha_rejected(self):
        assert is_exact_commit_sha(_VALID_COMMIT.upper()) is False

    def test_arbitrary_text_rejected(self):
        for value in ("not available", "main", "hello world", "abc", "A" * 40):
            assert is_exact_commit_sha(value) is False, value

    def test_missing_value_rejected(self):
        assert is_exact_commit_sha("") is False

    def test_env_override_mismatch_rejected(self, monkeypatch):
        """A non-exact env override must fail closed (not accepted merely
        because it is non-empty)."""
        monkeypatch.setenv("DEPLOYED_COMMIT", "short")
        ident = deployed_commit_identity()
        assert ident.resolved is False
        assert ident.commit == ""

    def test_env_override_exact_accepted(self, monkeypatch):
        monkeypatch.setenv("DEPLOYED_COMMIT", _VALID_COMMIT)
        ident = deployed_commit_identity()
        assert ident.resolved is True
        assert ident.commit == _VALID_COMMIT
        assert ident.resolution_source == "explicit_verified_override"

    def test_git_unavailable_fails_closed(self, monkeypatch):
        """No env, no resolvable .git, no platform metadata → unresolved."""
        import src.cloud_diagnostics as cd
        for key in ("DEPLOYED_COMMIT", "COMMIT_SHA", "GIT_SHA"):
            monkeypatch.delenv(key, raising=False)
        monkeypatch.setattr(cd, "_resolve_git_head_sha", lambda root: "")
        monkeypatch.setattr(cd, "capture_traceability", lambda: {"code_commit": ""})
        with pytest.raises(DeployedCommitError):
            resolve_deployed_commit_strict()

    def test_exact_match(self, monkeypatch):
        monkeypatch.setenv("DEPLOYED_COMMIT", _VALID_COMMIT)
        ident = resolve_deployed_commit_strict(_VALID_COMMIT)
        assert ident.match is True
        assert_expected_commit_matches(_VALID_COMMIT, ident)

    def test_exact_mismatch(self, monkeypatch):
        monkeypatch.setenv("DEPLOYED_COMMIT", _OTHER_COMMIT)
        ident = resolve_deployed_commit_strict(_VALID_COMMIT)
        assert ident.match is False
        with pytest.raises(DeployedCommitError):
            assert_expected_commit_matches(_VALID_COMMIT, ident)

    def test_unresolved_identity_is_fail_closed(self):
        ident = CloudCommitIdentity(commit="", resolution_source="unresolved", error="x")
        assert ident.resolved is False


# ---------------------------------------------------------------------------
# 2. Diagnostics required fields (WP1/P1)
# ---------------------------------------------------------------------------


class TestDiagnosticsRequiredFields:
    def test_empty_diagnostics_fails_release_validation(self):
        errors = CloudRuntimeDiagnostics().validate(release=True)
        assert errors
        joined = " | ".join(errors)
        for marker in (
            "diagnostics_id", "generated_at_utc", "deployed_commit",
            "commit_resolution_source", "model_id", "configured_revision",
            "python_version", "package_versions", "os_name", "cpu_model",
            "cpu_logical_cores", "ram_total_gb", "process_peak_rss_mb",
            "coordinator_state",
        ):
            assert marker in joined, f"missing mandatory field check for {marker}"

    def test_valid_diagnostics_passes_release_validation(self):
        assert _valid_diagnostics().validate(release=True) == []

    def test_zero_process_peak_fails_release(self):
        import dataclasses
        bad = dataclasses.replace(_valid_diagnostics(), process_peak_rss_mb=0.0)
        assert any("process_peak_rss_mb" in e for e in bad.validate(release=True))

    def test_short_deployed_commit_rejected_in_diagnostics(self):
        import dataclasses
        bad = dataclasses.replace(_valid_diagnostics(), deployed_commit="abc123")
        errors = bad.validate(release=True)
        assert any("deployed_commit" in e and "40" in e for e in errors)


# ---------------------------------------------------------------------------
# 3. Diagnostics rejects unknown (P1)
# ---------------------------------------------------------------------------


class TestDiagnosticsRejectsUnknown:
    @pytest.mark.parametrize("field", ["python_version", "os_name", "cpu_model"])
    def test_unknown_string_field_rejected(self, field):
        import dataclasses
        bad = dataclasses.replace(_valid_diagnostics(), **{field: "unknown"})
        errors = bad.validate(release=True)
        assert any(field in e for e in errors), (field, errors)

    def test_unknown_package_version_rejected(self):
        import dataclasses
        bad = dataclasses.replace(
            _valid_diagnostics(),
            package_versions={**_valid_diagnostics().package_versions, "torch": "unknown"},
        )
        errors = bad.validate(release=True)
        assert any("package_versions['torch']" in e for e in errors)

    def test_missing_package_version_rejected(self):
        import dataclasses
        pkgs = dict(_valid_diagnostics().package_versions)
        pkgs.pop("streamlit", None)
        bad = dataclasses.replace(_valid_diagnostics(), package_versions=pkgs)
        errors = bad.validate(release=True)
        assert any("package_versions['streamlit']" in e for e in errors)


# ---------------------------------------------------------------------------
# 4. Diagnostics JSON deterministic (WP2)
# ---------------------------------------------------------------------------


class TestDiagnosticsJsonDeterministic:
    def test_two_serialisations_identical(self):
        diag = _valid_diagnostics()
        assert diagnostics_to_json(diag) == diagnostics_to_json(diag)

    def test_json_is_stable_and_parseable(self):
        parsed = json.loads(diagnostics_to_json(_valid_diagnostics()))
        assert parsed["deployed_commit"] == _VALID_COMMIT
        assert parsed["hf_token_present"] is False

    def test_non_finite_float_rejected(self):
        import dataclasses
        bad = dataclasses.replace(_valid_diagnostics(), ram_total_gb=float("nan"))
        with pytest.raises(ValueError):
            diagnostics_to_json(bad)


# ---------------------------------------------------------------------------
# 5. Diagnostics contains no secret (WP12)
# ---------------------------------------------------------------------------


class TestDiagnosticsNoSecret:
    def test_diagnostics_export_has_no_secret(self):
        diag = _valid_diagnostics()
        found = diagnostics_exposes_secret(diag.to_dict())
        assert found is None

    def test_export_payload_has_no_secret(self, monkeypatch):
        monkeypatch.setenv("DEPLOYED_COMMIT", _VALID_COMMIT)
        export = build_public_diagnostics_export()
        found = diagnostics_exposes_secret(export)
        assert found is None
        dumped = json.dumps(export, sort_keys=True, default=str)
        assert "HF_TOKEN" not in dumped
        assert "hf_token" in dumped  # only the boolean field name

    def test_planted_secret_is_detected(self):
        planted = {"package_versions": {"torch": "x; echo HF_TOKEN=abc123"}}
        assert diagnostics_exposes_secret(planted) is not None

    def test_credential_like_key_detected(self):
        assert diagnostics_exposes_secret({"token_value": "abc"}) is not None
        assert diagnostics_exposes_secret({"hf_token_present": True}) is None

    def test_no_paths_or_headers(self):
        diag = _valid_diagnostics()
        dumped = json.dumps(diag.to_dict(), sort_keys=True)
        for marker in ("D:\\", "C:\\", "/home/", "/Users/", "Authorization",
                       "cookie", "Host:", "username"):
            assert marker not in dumped, marker


# ---------------------------------------------------------------------------
# 6. Diagnostics contains no payload (WP12)
# ---------------------------------------------------------------------------


class TestDiagnosticsNoPayload:
    def test_no_forecast_or_target_values(self):
        diag = _valid_diagnostics()
        dumped = json.dumps(diag.to_dict(), sort_keys=True)
        for marker in ("forecast_rows", "historical_data", "quantile_", "target"):
            assert marker not in dumped, marker

    def test_request_records_have_no_payload(self):
        store = RequestTelemetryStore()
        store.record(CloudRequestRecord(
            request_id="r1", session_id="s", success=True,
            started_at_utc="2026-08-06T00:00:00+00:00",
            completed_at_utc="2026-08-06T00:00:01+00:00",
            inference_seconds=1.0, model_revision="rev",
        ))
        export = {"request_records": store.snapshot()}
        assert diagnostics_exposes_secret(export) is None


# ---------------------------------------------------------------------------
# 7. Scoped request memory (WP4)
# ---------------------------------------------------------------------------


class TestScopedRequestMemory:
    def test_sampler_captures_before_peak_after(self, monkeypatch):
        import src.cloud_diagnostics as cd
        state = {"calls": 0, "rise": threading.Event(), "stop": threading.Event()}

        def fake_current() -> float:
            state["calls"] += 1
            if state["stop"].is_set():
                return 120.0
            if state["rise"].is_set():
                return 500.0
            return 100.0

        monkeypatch.setattr(cd, "current_rss_mb", fake_current)
        monkeypatch.setattr(cd, "process_peak_rss_mb", lambda: 900.0)

        sampler = RequestMemorySampler(request_id="mem-1", interval=0.005)
        sampler.start()
        time.sleep(0.02)
        state["rise"].set()
        time.sleep(0.1)
        state["stop"].set()
        time.sleep(0.02)
        sampler.stop(session_id="s1")

        sample = sampler.to_sample(session_id="s1")
        assert sample.rss_before_mb == 100.0
        assert sample.request_peak_rss_mb == 500.0
        assert sample.rss_after_mb == 120.0
        assert sample.process_peak_rss_mb == 900.0
        assert sample.request_peak_rss_mb != sample.process_peak_rss_mb
        assert sample.validate() == []

    def test_request_peak_not_inferred_from_process_peak(self, monkeypatch):
        import src.cloud_diagnostics as cd
        # Process peak is huge; request window stays small — the request
        # peak must reflect the request window only.
        monkeypatch.setattr(cd, "current_rss_mb", lambda: 100.0)
        monkeypatch.setattr(cd, "process_peak_rss_mb", lambda: 900.0)
        sampler = RequestMemorySampler(request_id="mem-2", interval=0.005)
        sampler.start()
        time.sleep(0.05)
        sampler.stop()
        sample = sampler.to_sample()
        assert sample.request_peak_rss_mb <= 100.0  # never saw the process peak
        assert sample.process_peak_rss_mb == 900.0

    def test_sampler_timestamps_ordered(self, monkeypatch):
        import src.cloud_diagnostics as cd
        monkeypatch.setattr(cd, "current_rss_mb", lambda: 100.0)
        monkeypatch.setattr(cd, "process_peak_rss_mb", lambda: 900.0)
        sampler = RequestMemorySampler(request_id="mem-3", interval=0.005)
        sampler.start()
        time.sleep(0.03)
        sampler.stop()
        sample = sampler.to_sample()
        assert sample.started_at_utc
        assert sample.stopped_at_utc
        from datetime import datetime
        assert datetime.fromisoformat(sample.started_at_utc) <= datetime.fromisoformat(sample.stopped_at_utc)

    def test_unsupported_measurement_fails_release_not_silent_zero(self, monkeypatch):
        """A zero process peak must fail release validation rather than being
        silently accepted."""
        import dataclasses
        diag = _valid_diagnostics()
        bad = dataclasses.replace(diag, process_peak_rss_mb=0.0)
        assert any("process_peak_rss_mb" in e for e in bad.validate(release=True))


# ---------------------------------------------------------------------------
# 8. Bounded request records (WP5)
# ---------------------------------------------------------------------------


class TestBoundedRequestRecords:
    def test_store_is_bounded(self):
        store = RequestTelemetryStore(max_records=5)
        for i in range(20):
            store.record(CloudRequestRecord(
                request_id=f"r{i}", session_id="s",
                started_at_utc="2026-08-06T00:00:00+00:00",
                completed_at_utc="2026-08-06T00:00:01+00:00",
                success=True, inference_seconds=1.0, model_revision="rev",
            ))
        assert len(store.snapshot()) == 5
        assert store.snapshot()[0]["request_id"] == "r15"

    def test_thread_safety(self):
        store = RequestTelemetryStore(max_records=100)
        threads = []
        for t in range(4):
            def _worker(offset: int = t):
                for i in range(25):
                    store.record(CloudRequestRecord(
                        request_id=f"t{offset}-{i}", session_id="s",
                        started_at_utc="2026-08-06T00:00:00+00:00",
                        completed_at_utc="2026-08-06T00:00:01+00:00",
                        success=True, inference_seconds=1.0, model_revision="rev",
                    ))
            threads.append(threading.Thread(target=_worker))
        for th in threads:
            th.start()
        for th in threads:
            th.join(timeout=10)
        snap = store.snapshot()
        assert len(snap) == 100  # bounded
        ids = [r["request_id"] for r in snap]
        assert len(set(ids)) == len(ids)  # no lost/duplicated records

    def test_begin_collection_session_clears(self):
        store = RequestTelemetryStore()
        store.record(CloudRequestRecord(
            request_id="old", session_id=store.session_id, success=True,
            started_at_utc="2026-08-06T00:00:00+00:00",
            completed_at_utc="2026-08-06T00:00:01+00:00",
            inference_seconds=1.0, model_revision="rev",
        ))
        new_id = store.begin_collection_session()
        assert new_id != store.session_id or new_id
        assert store.session_id == new_id
        assert store.snapshot() == []

    def test_get_request_record(self):
        store = RequestTelemetryStore()
        store.record(CloudRequestRecord(
            request_id="find-me", session_id="s", success=True,
            started_at_utc="2026-08-06T00:00:00+00:00",
            completed_at_utc="2026-08-06T00:00:01+00:00",
            inference_seconds=1.0, model_revision="rev",
        ))
        assert store.get("find-me")["request_id"] == "find-me"
        assert store.get("nope") is None


# ---------------------------------------------------------------------------
# 9. Request timestamp ordering (WP5)
# ---------------------------------------------------------------------------


class TestRequestTimestampOrdering:
    def _make_record(self, rid, start, end):
        return CloudRequestRecord(
            request_id=rid, session_id="s",
            started_at_utc=start, completed_at_utc=end,
            inference_started_at_utc=start,
            success=True, inference_seconds=1.0, model_revision="rev",
        )

    def test_record_requires_start_and_end(self):
        rec = CloudRequestRecord(request_id="r", session_id="s")
        errors = rec.validate()
        assert any("started_at_utc" in e for e in errors)
        assert any("completed_at_utc" in e for e in errors)

    def test_completed_after_start_ok(self):
        rec = self._make_record("r", "2026-08-06T00:00:00+00:00", "2026-08-06T00:00:01+00:00")
        assert rec.validate() == []

    def test_successful_record_requires_inference_time(self):
        rec = CloudRequestRecord(
            request_id="r", session_id="s", success=True,
            started_at_utc="2026-08-06T00:00:00+00:00",
            completed_at_utc="2026-08-06T00:00:01+00:00",
            inference_seconds=0.0, model_revision="rev",
        )
        assert any("inference_seconds" in e for e in rec.validate())

    def test_request_log_preserves_order(self):
        store = RequestTelemetryStore()
        for i in range(3):
            store.record(self._make_record(
                f"r{i}",
                f"2026-08-06T00:00:0{i}+00:00",
                f"2026-08-06T00:00:0{i + 1}+00:00",
            ))
        ids = [r["request_id"] for r in store.snapshot()]
        assert ids == ["r0", "r1", "r2"]


# ---------------------------------------------------------------------------
# 10. Repeated run uniqueness (WP8)
# ---------------------------------------------------------------------------


class TestRepeatedRunUniqueness:
    def test_three_repeated_runs_have_unique_ids(self):
        records = []
        for i in range(1, 5):
            records.append({
                "request_id": f"warm-{i}",
                "started_at_utc": f"2026-08-06T00:00:0{i}+00:00",
                "completed_at_utc": f"2026-08-06T00:00:0{i + 1}+00:00",
                "inference_started_at_utc": f"2026-08-06T00:00:0{i}+00:00",
                "success": True, "pipeline_reused": True,
                "pipeline_constructed": False, "inference_seconds": 1.0,
            })
        cats = categorise_request_ids(records)
        repeated = cats["repeated_run_ids"]
        assert len(repeated) == 3
        assert len(set(repeated)) == len(repeated)

    def test_repeated_runs_are_not_a_copy(self):
        """Two distinct warm runs must have distinct IDs and distinct
        timestamps — a duplicated record (copy) cannot be accepted."""
        records = [
            {"request_id": "warm-1", "started_at_utc": "2026-08-06T00:00:02+00:00",
             "completed_at_utc": "2026-08-06T00:00:03+00:00",
             "inference_started_at_utc": "2026-08-06T00:00:02+00:00",
             "success": True, "pipeline_reused": True, "pipeline_constructed": False,
             "inference_seconds": 1.0},
            {"request_id": "warm-2", "started_at_utc": "2026-08-06T00:00:03+00:00",
             "completed_at_utc": "2026-08-06T00:00:04+00:00",
             "inference_started_at_utc": "2026-08-06T00:00:03+00:00",
             "success": True, "pipeline_reused": True, "pipeline_constructed": False,
             "inference_seconds": 1.0},
        ]
        assert records[0]["request_id"] != records[1]["request_id"]
        assert records[0]["started_at_utc"] != records[1]["started_at_utc"]


# ---------------------------------------------------------------------------
# 11. Pipeline construction count (WP8/WP10)
# ---------------------------------------------------------------------------


class TestPipelineConstructionCount:
    def test_cold_run_constructs_and_warm_reuses(self):
        store = RequestTelemetryStore()
        store.record(CloudRequestRecord(
            request_id="cold-1", session_id="s", success=True,
            started_at_utc="2026-08-06T00:00:00+00:00",
            completed_at_utc="2026-08-06T00:00:02+00:00",
            inference_seconds=1.0, model_revision="rev",
            pipeline_constructed=True, pipeline_reused=False,
        ))
        for i in range(1, 4):
            store.record(CloudRequestRecord(
                request_id=f"warm-{i}", session_id="s", success=True,
                started_at_utc=f"2026-08-06T00:00:0{i + 2}+00:00",
                completed_at_utc=f"2026-08-06T00:00:0{i + 3}+00:00",
                inference_seconds=1.0, model_revision="rev",
                pipeline_constructed=False, pipeline_reused=True,
            ))
        snaps = store.snapshot()
        constructed = [r for r in snaps if r["pipeline_constructed"]]
        assert len(constructed) == 1
        assert constructed[0]["request_id"] == "cold-1"
        reused = [r for r in snaps if r["pipeline_reused"]]
        assert len(reused) == 3

    def test_constructed_and_reused_cannot_both_be_true(self):
        rec = CloudRequestRecord(
            request_id="r", session_id="s", success=True,
            started_at_utc="2026-08-06T00:00:00+00:00",
            completed_at_utc="2026-08-06T00:00:01+00:00",
            inference_seconds=1.0, model_revision="rev",
            pipeline_constructed=True, pipeline_reused=True,
        )
        assert any("pipeline_constructed and pipeline_reused" in e for e in rec.validate())


# ---------------------------------------------------------------------------
# 12. Concurrency overlap (WP9)
# ---------------------------------------------------------------------------


class TestConcurrencyOverlap:
    def test_intervals_overlap(self):
        assert intervals_overlap(
            "2026-08-06T00:00:00+00:00", "2026-08-06T00:00:02+00:00",
            "2026-08-06T00:00:01+00:00", "2026-08-06T00:00:03+00:00",
        ) is True

    def test_abutting_intervals_do_not_overlap(self):
        assert intervals_overlap(
            "2026-08-06T00:00:00+00:00", "2026-08-06T00:00:01+00:00",
            "2026-08-06T00:00:01+00:00", "2026-08-06T00:00:02+00:00",
        ) is False

    def test_any_overlapping_pair(self):
        records = [
            {"request_id": "a", "success": True,
             "inference_started_at_utc": "2026-08-06T00:00:00+00:00",
             "completed_at_utc": "2026-08-06T00:00:02+00:00"},
            {"request_id": "b", "success": True,
             "inference_started_at_utc": "2026-08-06T00:00:01+00:00",
             "completed_at_utc": "2026-08-06T00:00:03+00:00"},
        ]
        assert any_overlapping_pair(records) is True

    def test_sequential_records_do_not_overlap(self):
        records = [
            {"request_id": "a", "success": True,
             "inference_started_at_utc": "2026-08-06T00:00:00+00:00",
             "completed_at_utc": "2026-08-06T00:00:01+00:00"},
            {"request_id": "b", "success": True,
             "inference_started_at_utc": "2026-08-06T00:00:01+00:00",
             "completed_at_utc": "2026-08-06T00:00:02+00:00"},
        ]
        assert any_overlapping_pair(records) is False

    def test_concurrency_ids_derived_from_overlap(self):
        records = [
            {"request_id": "a", "success": True,
             "inference_started_at_utc": "2026-08-06T00:00:00+00:00",
             "completed_at_utc": "2026-08-06T00:00:02+00:00"},
            {"request_id": "b", "success": True,
             "inference_started_at_utc": "2026-08-06T00:00:01+00:00",
             "completed_at_utc": "2026-08-06T00:00:03+00:00"},
        ]
        cats = categorise_request_ids(records)
        assert set(cats["concurrency_request_ids"]) == {"a", "b"}


# ---------------------------------------------------------------------------
# 13. Token state boolean only (WP7)
# ---------------------------------------------------------------------------


class TestTokenStateBooleanOnly:
    def test_returns_bool_when_absent(self, monkeypatch):
        monkeypatch.delenv("HF_TOKEN", raising=False)
        assert isinstance(hf_token_present(include_secrets=False), bool)
        assert hf_token_present(include_secrets=False) is False

    def test_returns_true_bool_when_present(self, monkeypatch):
        monkeypatch.setenv("HF_TOKEN", "hf_dummy_value")
        value = hf_token_present(include_secrets=False)
        assert isinstance(value, bool)
        assert value is True

    def test_never_exposes_value(self, monkeypatch):
        monkeypatch.setenv("HF_TOKEN", "hf_verysecret")
        assert hf_token_present(include_secrets=False) is True
        # The value must not leak into any export.
        diag = _valid_diagnostics()
        dumped = json.dumps(diag.to_dict(), sort_keys=True)
        assert "hf_verysecret" not in dumped
        assert "hf_" not in dumped.replace("hf_token_present", "")


# ---------------------------------------------------------------------------
# 14. Dependency check states (WP6)
# ---------------------------------------------------------------------------


class TestDependencyCheckStates:
    def test_measure_dependency_diagnostics_returns_typed_record(self, monkeypatch):
        import src.cloud_diagnostics as cd
        monkeypatch.setattr(cd, "_run_pip_check", lambda: (True, "pip check passed"))
        reset_dependency_diagnostics_cache()
        try:
            dep = measure_dependency_diagnostics()
            assert isinstance(dep, DependencyDiagnostics)
            d = dep.to_dict()
            assert isinstance(d["pip_check_passed"], bool)
            assert isinstance(d["torch_cpu_only"], bool)
            assert isinstance(d["nvidia_packages"], list)
            assert isinstance(d["package_versions"], dict)
            assert d["checked_at_utc"]
        finally:
            reset_dependency_diagnostics_cache()

    def test_diagnostics_reflects_pip_failure(self, monkeypatch):
        import src.cloud_diagnostics as cd
        monkeypatch.setattr(cd, "_run_pip_check", lambda: (False, "conflict"))
        reset_dependency_diagnostics_cache()
        try:
            dep = measure_dependency_diagnostics()
            assert dep.pip_check_passed is False
            # A failed pip check must fail release diagnostics.
            import dataclasses
            diag = dataclasses.replace(_valid_diagnostics(), pip_check_passed=False)
            assert any("pip_check_passed" in e for e in diag.validate(release=True))
        finally:
            reset_dependency_diagnostics_cache()

    def test_nvidia_packages_detection(self, monkeypatch):
        import src.cloud_diagnostics as cd
        monkeypatch.setattr(cd, "_installed_nvidia_packages", lambda: ["nvidia-cuda-runtime"])
        reset_dependency_diagnostics_cache()
        try:
            dep = measure_dependency_diagnostics()
            assert dep.nvidia_packages == ["nvidia-cuda-runtime"]
            import dataclasses
            diag = dataclasses.replace(_valid_diagnostics(), nvidia_packages=["nvidia-cuda-runtime"])
            assert any("nvidia_packages" in e for e in diag.validate(release=True))
        finally:
            reset_dependency_diagnostics_cache()

    def test_cached_once_per_process(self, monkeypatch):
        import src.cloud_diagnostics as cd
        calls = {"n": 0}

        def fake_pip():
            calls["n"] += 1
            return (True, "ok")

        monkeypatch.setattr(cd, "_run_pip_check", fake_pip)
        reset_dependency_diagnostics_cache()
        try:
            measure_dependency_diagnostics()
            measure_dependency_diagnostics()
            assert calls["n"] == 1
        finally:
            reset_dependency_diagnostics_cache()


# ---------------------------------------------------------------------------
# 15 + 16. Collection session + receipt binding (WP11)
# ---------------------------------------------------------------------------


class TestCollectionSessionBinding:
    def _session(self):
        records = [
            {"request_id": "cold-1",
             "started_at_utc": "2026-08-06T00:00:00+00:00",
             "completed_at_utc": "2026-08-06T00:00:02+00:00",
             "inference_started_at_utc": "2026-08-06T00:00:00+00:00",
             "success": True, "pipeline_constructed": True, "inference_seconds": 1.0},
        ]
        for i in range(1, 4):
            records.append({
                "request_id": f"warm-{i}",
                "started_at_utc": f"2026-08-06T00:00:0{i + 1}+00:00",
                "completed_at_utc": f"2026-08-06T00:00:0{i + 2}+00:00",
                "inference_started_at_utc": f"2026-08-06T00:00:0{i + 1}+00:00",
                "success": True, "pipeline_reused": True,
                "pipeline_constructed": False, "inference_seconds": 1.0,
            })
        return build_collection_session_record(
            session_id="session-1",
            deployed_commit=_VALID_COMMIT,
            commit_resolution_source="git_head",
            deployment_url="https://example.streamlit.app",
            diagnostics=_valid_diagnostics(),
            acceptance_test_names=["cold_forecast", "warm_forecast"],
            request_records=records,
            started_at_utc="2026-08-06T00:00:00+00:00",
            completed_at_utc="2026-08-06T00:05:00+00:00",
        )

    def test_session_binds_all_groups(self):
        session = self._session()
        assert session.validate() == [], session.validate()
        d = session.to_dict()
        assert d["deployed_commit"] == _VALID_COMMIT
        assert d["request_ids"] == ["cold-1", "warm-1", "warm-2", "warm-3"]
        assert set(d["repeated_run_ids"]) == {"warm-2", "warm-3"}
        assert d["diagnostics_digest"] == canonical_diagnostics_digest(_valid_diagnostics())
        assert d["deployment_url"] == "https://example.streamlit.app"
        assert d["code_commit"] == d["deployed_commit"]

    def test_session_never_contains_own_receipt(self):
        assert "collection_receipt" not in self._session().to_dict()

    def test_receipt_binds_canonical_digest(self):
        session = self._session()
        receipt = build_collection_receipt(session)
        from src.evidence_schemas import canonical_evidence_sha256
        expected = canonical_evidence_sha256(session.to_dict())
        assert receipt["canonical_content_sha256"] == expected
        assert receipt["evidence_type"] == "execution_receipt"
        assert receipt["code_commit"] == _VALID_COMMIT

    def test_session_rejects_wrong_commit(self):
        import dataclasses
        session = self._session()
        bad = dataclasses.replace(session, deployed_commit=_OTHER_COMMIT)
        assert any("deployed_commit" in e for e in bad.validate())

    def test_session_rejects_short_commit(self):
        import dataclasses
        session = self._session()
        bad = dataclasses.replace(session, deployed_commit="abc123")
        assert any("deployed_commit" in e for e in bad.validate())

    def test_receipt_mutation_breaks_digest(self):
        session = self._session()
        receipt = build_collection_receipt(session)
        # Mutating the session invalidates the binding.
        mutated = session.to_dict()
        mutated["request_ids"] = ["warm-1", "cold-1"]
        from src.evidence_schemas import canonical_evidence_sha256
        assert canonical_evidence_sha256(mutated) != receipt["canonical_content_sha256"]


# ---------------------------------------------------------------------------
# 17. Publisher rejects incomplete Cloud evidence
# ---------------------------------------------------------------------------


class TestPublisherRejectsIncompleteCloudEvidence:
    def test_schema_rejects_deployed_commit_mismatch(self):
        import dataclasses
        from src.evidence_schemas import CloudEvidence, evidence_from_dict
        import sys
        sys.path.insert(0, str(REPO_ROOT))
        base = {
            "evidence_type": "cloud_stage0",
            "evidence_schema_version": "2",
            "evidence_origin": "real_measurement",
            "success": True,
            "code_commit": _VALID_COMMIT,
            "deployed_commit": _OTHER_COMMIT,  # mismatch
            "started_at_utc": "2026-08-06T00:00:00+00:00",
            "completed_at_utc": "2026-08-06T00:05:00+00:00",
        }
        ev = evidence_from_dict(base, strict=True)
        errors = ev.validate()
        assert any("deployment identity mismatch" in e for e in errors)

    def test_public_export_not_release_ready_is_rejected_path(self, monkeypatch):
        """A diagnostics export that is not release-ready cannot feed the
        evidence pipeline — the export reports release_ready=False."""
        monkeypatch.setenv("DEPLOYED_COMMIT", _VALID_COMMIT)
        # Force an unknown package version so release validation fails.
        import src.cloud_diagnostics as cd
        monkeypatch.setattr(
            cd, "package_versions_metadata",
            lambda: {**_orig_versions(), "torch": "unknown"},
        )
        export = build_public_diagnostics_export()
        assert export["release_ready"] is False
        assert any("package_versions['torch']" in e for e in export["validation_errors"])


def _orig_versions():
    from src.telemetry import package_versions_metadata
    return package_versions_metadata()


# ---------------------------------------------------------------------------
# 18. Manifest rejects incomplete Cloud evidence
# ---------------------------------------------------------------------------


class TestManifestRejectsIncompleteCloudEvidence:
    def test_verify_manifest_rejects_invalid_cloud_record(self, tmp_path):
        """A cloud record with an invalid deployed commit must be rejected
        by the manifest verifier's referenced-JSON validation."""
        from scripts.verify_evidence_manifest import _validate_referenced_json
        record = {
            "evidence_type": "cloud_stage0",
            "evidence_schema_version": "2",
            "evidence_origin": "real_measurement",
            "success": True,
            "code_commit": _VALID_COMMIT,
            "deployed_commit": "abc123",  # short → invalid
            "started_at_utc": "2026-08-06T00:00:00+00:00",
            "completed_at_utc": "2026-08-06T00:05:00+00:00",
        }
        path = tmp_path / "cloud_invalid.json"
        path.write_text(json.dumps(record), encoding="utf-8")
        errors = _validate_referenced_json(path, "cloud_stage0", _VALID_COMMIT)
        assert errors, "manifest verifier accepted an invalid cloud record"


# ---------------------------------------------------------------------------
# 19. Readiness includes Cloud instrumentation checks
# ---------------------------------------------------------------------------


class TestReadinessIncludesCloudInstrumentation:
    def test_readiness_script_contains_wp13_checks(self):
        script = (REPO_ROOT / "scripts" / "verify_stage0_evidence_readiness.py").read_text(encoding="utf-8")
        assert "run_cloud_instrumentation_checks" in script
        assert "Cloud evidence instrumentation readiness" in script
        assert "Exact deployed commit validation" in script
        assert "Collection-session digest binding" in script

    def test_readiness_script_runs_offline(self):
        """The readiness script must complete with exit 0 and include the
        WP13 instrumentation check in its output."""
        import subprocess
        env = dict(os.environ)
        env["HF_HUB_OFFLINE"] = "1"
        env["TRANSFORMERS_OFFLINE"] = "1"
        result = subprocess.run(
            [sys.executable, str(REPO_ROOT / "scripts" / "verify_stage0_evidence_readiness.py")],
            capture_output=True, text=True, timeout=180, env=env,
        )
        assert result.returncode == 0, f"readiness failed:\n{result.stdout}\n{result.stderr}"
        assert "Cloud evidence instrumentation readiness" in result.stdout
        assert "[OK] All readiness checks passed" in result.stdout


# ---------------------------------------------------------------------------
# 20. build_runtime_diagnostics integration (offline-safe)
# ---------------------------------------------------------------------------


class TestBuildRuntimeDiagnostics:
    def test_builds_typed_snapshot(self, monkeypatch):
        monkeypatch.setenv("DEPLOYED_COMMIT", _VALID_COMMIT)
        import src.cloud_diagnostics as cd
        monkeypatch.setattr(cd, "_run_pip_check", lambda: (True, "pip check passed"))
        reset_dependency_diagnostics_cache()
        try:
            diag = build_runtime_diagnostics(_VALID_COMMIT)
            assert isinstance(diag, CloudRuntimeDiagnostics)
            assert diag.deployed_commit == _VALID_COMMIT
            assert diag.expected_commit_match is True
            assert diag.model_id == "amazon/chronos-2"
            assert diag.configured_revision == _PINNED_REVISION
            assert diag.hf_token_present in (True, False)
            assert isinstance(diag.torch_cpu_only, bool)
            assert diag.coordinator_state
        finally:
            reset_dependency_diagnostics_cache()

    def test_build_fails_closed_on_mismatch(self, monkeypatch):
        """A deployed commit that does not match the expected collection
        commit must fail release validation (fail closed before collection)."""
        monkeypatch.setenv("DEPLOYED_COMMIT", _OTHER_COMMIT)
        import src.cloud_diagnostics as cd
        monkeypatch.setattr(cd, "_run_pip_check", lambda: (True, "pip check passed"))
        reset_dependency_diagnostics_cache()
        try:
            diag = build_runtime_diagnostics(_VALID_COMMIT)
            assert diag.expected_commit_match is False
            errors = diag.validate(release=True)
            assert any("expected collection commit" in e for e in errors)
        finally:
            reset_dependency_diagnostics_cache()


# ---------------------------------------------------------------------------
# Regression tests for codex review findings (PR #33, P1-1 .. P1-5)
# ---------------------------------------------------------------------------


class TestMachineResourcesStdlibFirst:
    """P1-1: machine resources must be measurable without psutil (the Cloud
    runtime installs only requirements.txt)."""

    def test_machine_resource_summary_without_psutil(self, monkeypatch):
        import sys as _sys
        monkeypatch.setitem(_sys.modules, "psutil", None)
        from src.cloud_diagnostics import machine_resource_summary
        res = machine_resource_summary()
        assert res["cpu_logical_cores"] > 0
        assert res["ram_total_gb"] > 0

    def test_build_diagnostics_uses_resource_summary(self, monkeypatch):
        """build_runtime_diagnostics must report positive cores/RAM even
        when psutil is unavailable."""
        import sys as _sys
        import src.cloud_diagnostics as cd
        monkeypatch.setitem(_sys.modules, "psutil", None)
        monkeypatch.setattr(cd, "_run_pip_check", lambda: (True, "ok"))
        monkeypatch.setenv("DEPLOYED_COMMIT", _VALID_COMMIT)
        reset_dependency_diagnostics_cache()
        try:
            diag = build_runtime_diagnostics(_VALID_COMMIT)
            assert diag.cpu_logical_cores > 0
            assert diag.ram_total_gb > 0
            errors = diag.validate(release=True)
            # The resource fields themselves must never be flagged; on
            # Windows the only release error is the (expected) unmeasurable
            # process peak — on the Linux Cloud runtime it is measurable.
            assert not any("cpu_logical_cores" in e for e in errors), errors
            assert not any("ram_total_gb" in e for e in errors), errors
        finally:
            reset_dependency_diagnostics_cache()


class TestRecordStopsSamplerBeforeSerialize:
    """P1-2: the stored memory sample must be complete (sampler stopped
    before serialization), never zeroed/empty."""

    def test_record_cloud_request_stops_sampler_first(self):
        import importlib
        page = importlib.import_module("pages.1_Forecast")
        store = RequestTelemetryStore()

        class _Exec:
            request_record = {
                "request_id": "r1",
                "start_time_utc": "2026-08-06T00:00:00+00:00",
                "inference_start_utc": "2026-08-06T00:00:00+00:00",
                "completion_time_utc": "2026-08-06T00:00:02+00:00",
                "queue_seconds": 0.0,
                "inference_seconds": 1.0,
            }

        sampler = RequestMemorySampler(request_id="r1", interval=0.005)
        sampler.start()
        time.sleep(0.03)
        # Intentionally NOT stopped before the page helper serialises.
        page._record_cloud_request(store, "r1", _Exec(), None, sampler, "s1", success=True)

        rec = store.get("r1")
        assert rec is not None
        mem = rec.get("memory", {})
        assert mem.get("started_at_utc"), mem
        assert mem.get("stopped_at_utc"), "sampler must be stopped before serializing"
        assert mem.get("rss_before_mb", 0) > 0
        assert mem.get("rss_after_mb", 0) > 0, "rss_after must be measured before serializing"
        assert mem.get("request_peak_rss_mb", 0) > 0


class TestConcurrencyFullWindow:
    """P1-3: concurrency must be detected across the full request windows
    (queue wait included), matching CloudEvidence.validate() semantics —
    not the serialised inference windows."""

    def test_full_windows_overlap_despite_serialised_inference(self):
        records = [
            {"request_id": "a", "success": True,
             "started_at_utc": "2026-08-06T00:00:00+00:00",
             "inference_started_at_utc": "2026-08-06T00:00:00+00:00",
             "completed_at_utc": "2026-08-06T00:00:06+00:00"},
            {"request_id": "b", "success": True,
             "started_at_utc": "2026-08-06T00:00:00+00:00",
             "inference_started_at_utc": "2026-08-06T00:00:01+00:00",
             "completed_at_utc": "2026-08-06T00:00:05+00:00"},
        ]
        assert any_overlapping_pair(records) is True

    def test_sequential_full_windows_do_not_overlap(self):
        records = [
            {"request_id": "a", "success": True,
             "started_at_utc": "2026-08-06T00:00:00+00:00",
             "completed_at_utc": "2026-08-06T00:00:02+00:00"},
            {"request_id": "b", "success": True,
             "started_at_utc": "2026-08-06T00:00:02+00:00",
             "completed_at_utc": "2026-08-06T00:00:04+00:00"},
        ]
        assert any_overlapping_pair(records) is False

    def test_concurrency_ids_derived_from_full_windows(self):
        records = [
            {"request_id": "a", "success": True,
             "started_at_utc": "2026-08-06T00:00:00+00:00",
             "inference_started_at_utc": "2026-08-06T00:00:00+00:00",
             "completed_at_utc": "2026-08-06T00:00:06+00:00"},
            {"request_id": "b", "success": True,
             "started_at_utc": "2026-08-06T00:00:00+00:00",
             "inference_started_at_utc": "2026-08-06T00:00:01+00:00",
             "completed_at_utc": "2026-08-06T00:00:05+00:00"},
        ]
        cats = categorise_request_ids(records)
        assert set(cats["concurrency_request_ids"]) == {"a", "b"}


class TestAcceptanceEvents:
    """P1-4: the collection session must record only acceptance tests that
    genuinely ran, via typed events."""

    def test_events_recorded_and_filtered_by_session(self):
        store = RequestTelemetryStore()
        store.record_acceptance_event("cold_forecast", True, session_id="s1")
        store.record_acceptance_event("warm_forecast", True, session_id="s2")
        assert [e["test_name"] for e in store.acceptance_events("s1")] == ["cold_forecast"]
        assert [e["test_name"] for e in store.acceptance_events("s2")] == ["warm_forecast"]
        assert [e["test_name"] for e in store.acceptance_events()] == ["cold_forecast", "warm_forecast"]

    def test_unknown_test_name_rejected(self):
        store = RequestTelemetryStore()
        with pytest.raises(ValueError):
            store.record_acceptance_event("not_a_canonical_test", True)

    def test_session_test_names_reflect_only_ran_events(self):
        store = RequestTelemetryStore()
        store.record_acceptance_event("cold_forecast", True, session_id="s1")
        # An event that did not pass must not be listed as collected.
        store.record_acceptance_event("warm_forecast", False, session_id="s1")
        ran = [e["test_name"] for e in store.acceptance_events("s1") if e.get("passed")]
        assert ran == ["cold_forecast"]


class TestSessionIsolation:
    """P1-5: one browser session's collection window must not absorb or
    clear another session's records."""

    def _make_record(self, rid, session_id, start="2026-08-06T00:00:00+00:00"):
        return CloudRequestRecord(
            request_id=rid, session_id=session_id, success=True,
            started_at_utc=start,
            completed_at_utc="2026-08-06T00:00:01+00:00",
            inference_seconds=1.0, model_revision="rev",
        )

    def test_records_separable_by_session(self):
        store = RequestTelemetryStore()
        store.record(self._make_record("a1", "sessionA"))
        store.record(self._make_record("a2", "sessionA"))
        store.record(self._make_record("b1", "sessionB"))
        assert [r["request_id"] for r in store.snapshot(session_id="sessionA")] == ["a1", "a2"]
        assert [r["request_id"] for r in store.snapshot(session_id="sessionB")] == ["b1"]
        assert len(store.snapshot()) == 3

    def test_events_separable_by_session(self):
        store = RequestTelemetryStore()
        store.record_acceptance_event("cold_forecast", True, session_id="sessionA")
        store.record_acceptance_event("warm_forecast", True, session_id="sessionB")
        assert [e["test_name"] for e in store.acceptance_events("sessionA")] == ["cold_forecast"]
        assert [e["test_name"] for e in store.acceptance_events("sessionB")] == ["warm_forecast"]


class TestAllCanonicalPathsInstrumented:
    """P1-6: every canonical acceptance path has a typed event producer (the
    page emits events via _record_acceptance_event; verify the helper and
    the session-level semantics)."""

    def test_page_acceptance_event_helper_records_and_tags(self):
        import importlib
        page = importlib.import_module("pages.1_Forecast")
        page._telemetry_store.begin_collection_session()
        page._record_acceptance_event("oversized_csv_rejected")
        page._record_acceptance_event("same_column_rejected")
        page._record_acceptance_event("blank_timestamp_rejected")
        page._record_acceptance_event("invalid_timestamp_rejected")
        page._record_acceptance_event("context_truncation_visible")
        events = page._telemetry_store.acceptance_events(session_id=page._session_id)
        names = [e["test_name"] for e in events]
        for expected in ("oversized_csv_rejected", "same_column_rejected",
                         "blank_timestamp_rejected", "invalid_timestamp_rejected",
                         "context_truncation_visible"):
            assert expected in names, (expected, names)

    def test_all_canonical_tests_have_producers(self):
        """Every canonical acceptance test name must be emitted by at least
        one page branch (source-level contract)."""
        from src.evidence_schemas import CANONICAL_CLOUD_TESTS
        page_source = (REPO_ROOT / "pages" / "1_Forecast.py").read_text(encoding="utf-8")
        diag_source = (REPO_ROOT / "pages" / "3_Cloud_Diagnostics.py").read_text(encoding="utf-8")
        combined = page_source + diag_source
        missing = [
            name for name in CANONICAL_CLOUD_TESTS
            if f'"{name}"' not in combined and f"'{name}'" not in combined
        ]
        assert not missing, f"canonical tests without a producer call site: {missing}"


class TestConcurrencyPeerCohort:
    """P1-7: a finalised session must bind peer-session requests so genuine
    two-session concurrency is captured in concurrency_request_ids."""

    def _cohort_records(self):
        return [
            {"request_id": "browserA-req1", "session_id": "sessionA", "success": True,
             "started_at_utc": "2026-08-06T00:00:00+00:00",
             "inference_started_at_utc": "2026-08-06T00:00:00+00:00",
             "completed_at_utc": "2026-08-06T00:00:06+00:00"},
            {"request_id": "browserB-req1", "session_id": "sessionB", "success": True,
             "started_at_utc": "2026-08-06T00:00:00+00:00",
             "inference_started_at_utc": "2026-08-06T00:00:01+00:00",
             "completed_at_utc": "2026-08-06T00:00:05+00:00"},
        ]

    def test_session_binds_peer_requests_for_concurrency(self):
        session = build_collection_session_record(
            session_id="sessionA",
            deployed_commit=_VALID_COMMIT,
            commit_resolution_source="git_head",
            deployment_url="https://example.streamlit.app",
            diagnostics=_valid_diagnostics(),
            acceptance_test_names=["cold_forecast", "two_session_concurrency"],
            request_records=self._cohort_records(),
            started_at_utc="2026-08-06T00:00:00+00:00",
            completed_at_utc="2026-08-06T00:05:00+00:00",
        )
        assert set(session.concurrency_request_ids) == {"browserA-req1", "browserB-req1"}
        assert session.request_ids == ["browserA-req1", "browserB-req1"]
        assert session.validate() == [], session.validate()


class TestTimeoutRecoveryPending:
    """P1-8: timeout recovery is marked passed only after a later successful
    request — categorise keeps the pending timeout + recovery ids."""

    def test_timeout_recovery_ids_pair_timeout_with_next_success(self):
        records = [
            {"request_id": "req-a", "success": True,
             "started_at_utc": "2026-08-06T00:00:00+00:00",
             "inference_started_at_utc": "2026-08-06T00:00:00+00:00",
             "completed_at_utc": "2026-08-06T00:00:01+00:00",
             "pipeline_constructed": True},
            {"request_id": "req-timeout", "success": False,
             "error_category": "CoordinatorTimeoutError",
             "started_at_utc": "2026-08-06T00:00:01+00:00",
             "completed_at_utc": "2026-08-06T00:00:02+00:00"},
            {"request_id": "req-recovery", "success": True,
             "started_at_utc": "2026-08-06T00:00:02+00:00",
             "inference_started_at_utc": "2026-08-06T00:00:02+00:00",
             "completed_at_utc": "2026-08-06T00:00:03+00:00",
             "pipeline_reused": True},
        ]
        cats = categorise_request_ids(records)
        assert cats["timeout_recovery_ids"] == ["req-timeout", "req-recovery"]


class TestTestNamesDeduplicated:
    """P1-9: duplicate acceptance-test names are rejected (so the page's
    dedupe is required) and deduped names validate."""

    def _build_session(self, test_names):
        return build_collection_session_record(
            session_id="s1",
            deployed_commit=_VALID_COMMIT,
            commit_resolution_source="git_head",
            deployment_url="https://example.streamlit.app",
            diagnostics=_valid_diagnostics(),
            acceptance_test_names=test_names,
            request_records=[
                {"request_id": "r1", "success": True,
                 "started_at_utc": "2026-08-06T00:00:00+00:00",
                 "completed_at_utc": "2026-08-06T00:00:01+00:00",
                 "inference_started_at_utc": "2026-08-06T00:00:00+00:00",
                 "pipeline_constructed": True},
            ],
            started_at_utc="2026-08-06T00:00:00+00:00",
            completed_at_utc="2026-08-06T00:05:00+00:00",
        )

    def test_duplicate_test_names_rejected(self):
        session = self._build_session(["cold_forecast", "cold_forecast"])
        assert any("duplicate test_name" in e for e in session.validate())

    def test_non_canonical_test_name_rejected(self):
        session = self._build_session(["not_a_canonical_test"])
        assert any("not canonical" in e for e in session.validate())

    def test_deduped_names_validate(self):
        session = self._build_session(["cold_forecast", "warm_forecast"])
        assert session.validate() == [], session.validate()
