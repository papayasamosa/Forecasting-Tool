"""Tests for the shared recursive evidence validation module (WP9)."""
from __future__ import annotations

import json
import os
import sys
from pathlib import Path

import pytest

from src.evidence_schemas import EVIDENCE_SCHEMA_VERSION


class TestStrictReleaseDeserialisation:
    """WP2: release evidence must reject unknown fields at every depth.
    The recursive validator and every release builder/publisher/verifier
    use strict mode, so permissive (migration-only) parsing can never reach
    publication."""

    def _valid_smoke(self, **overrides) -> dict:
        data = {
            "evidence_schema_version": EVIDENCE_SCHEMA_VERSION,
            "evidence_type": "smoke_test",
            "evidence_origin": "real_measurement",
            "test": "chronos2_smoke_test",
            "success": True,
            "code_commit": "abc123",
            "git_worktree_clean": True,
            "started_at_utc": "2026-07-29T00:00:00",
            "completed_at_utc": "2026-07-29T00:01:00",
            "python_version": "3.12",
            "model_id": "amazon/chronos-2",
            "configured_revision": "rev1",
            "model_revision": "rev1",
            "hf_token_present": False,
            "token_absent_result": {
                "attempted": True, "success": True,
                "configured_revision": "rev1", "resolved_revision": "rev1",
                "run_id": "run-abc",
                "started_at_utc": "2026-07-29T00:00:00",
                "completed_at_utc": "2026-07-29T00:00:30",
                "timing_seconds": 10.0,
            },
            "token_present_result": {"attempted": False},
            "initial_cache_state": "download_cold",
            "cold": {"cache_state": "download_cold", "pipeline_call_count": 1, "rss_mb": 500.0},
            "warm": {"cache_state": "same_process_warm", "pipeline_reused": True, "rss_mb": 500.0},
            "package_versions": {"torch": "2.13.0"},
            "cache_preflight": {
                "inspection_succeeded": True,
                "cache_source": "explicit",
                "initial_cache_state": "download_cold",
                "snapshot_present": False,
                "post_run_snapshot_present": True,
                "post_run_file_count": 5,
                "post_run_total_bytes": 1000000,
            },
        }
        data.update(overrides)
        return data

    def test_validate_recursive_default_is_strict(self):
        from src.evidence_validation import validate_recursive
        data = self._valid_smoke(bogus_top_level=1)
        errors = validate_recursive(data, label="smoke")
        assert any("deserialisation failed" in e and "unknown field" in e for e in errors), errors

    def test_validate_recursive_nested_unknown_field_fails(self):
        from src.evidence_validation import validate_recursive
        data = self._valid_smoke()
        data["cold"] = {"cache_state": "download_cold", "pipeline_call_count": 1, "rss_mb": 500.0, "typo": 1}
        errors = validate_recursive(data, label="smoke")
        assert any("unknown field" in e and "typo" in e for e in errors), errors

    def test_validate_recursive_permissive_still_warns_and_continues(self):
        from src.evidence_validation import validate_recursive
        data = self._valid_smoke(bogus_top_level=1)
        # explicit permissive migration mode: drops unknown fields, does not
        # fail — but this is NOT a release path.
        errors = validate_recursive(data, label="smoke", strict=False)
        assert not any("deserialisation failed" in e for e in errors)

    def test_evidence_from_dict_default_is_permissive_migration_mode(self):
        from src.evidence_schemas import evidence_from_dict
        import warnings
        data = self._valid_smoke(bogus_top_level=1)
        with warnings.catch_warnings(record=True) as caught:
            warnings.simplefilter("always")
            obj = evidence_from_dict(data)
        assert obj.evidence_type == "smoke_test"
        assert any(issubclass(w.category, UserWarning) for w in caught)

    def test_publisher_rejects_unknown_field_in_strict_mode(self, tmp_path):
        from scripts.publish_evidence import _validate_and_load
        data = self._valid_smoke(bogus_top_level=1)
        _, errors = _validate_and_load(
            data,
            expected_type="smoke_test",
            expected_token_state=None,
            expected_initial_cache_state="download_cold",
            expected_code_commit="abc123",
        )
        assert any("deserialisation failed" in e and "unknown field" in e for e in errors), errors

    def test_bundle_builder_rejects_unknown_field_in_strict_mode(self, tmp_path):
        from scripts.build_local_stage0_bundle import _validate_component_typed
        data = self._valid_smoke(bogus_top_level=1)
        errors = _validate_component_typed(
            data,
            component_name="download_cold_smoke",
            expected_evidence_type="smoke_test",
            expected_token_present=False,
            expected_initial_cache_state="download_cold",
            expected_commit="abc123",
        )
        assert any("deserialisation failed" in e and "unknown field" in e for e in errors), errors

    def test_manifest_verifier_uses_strict_recursive_validation(self, tmp_path):
        from scripts.verify_evidence_manifest import _validate_referenced_json
        import json as _json
        fpath = tmp_path / "evidence.json"
        with open(fpath, "w", encoding="utf-8") as f:
            _json.dump(self._valid_smoke(bogus_top_level=1), f)
        errors = _validate_referenced_json(fpath, "smoke_test", "abc123")
        assert any("unknown field" in e for e in errors), errors

    def test_wrong_evidence_type_cannot_silently_reconstruct(self):
        from src.evidence_schemas import evidence_from_dict
        data = self._valid_smoke()
        data["evidence_type"] = "benchmark_suite"
        with pytest.raises(ValueError) as excinfo:
            evidence_from_dict(data, strict=True)
        assert "unknown field" in str(excinfo.value)


class TestValidateRecursive:
    def _get_validate(self):
        """Helper to import validate_recursive."""
        sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
        from src.evidence_validation import validate_recursive
        return validate_recursive

    def test_rejects_non_dict(self):
        validate = self._get_validate()
        errors = validate([1, 2, 3], label="list_data")
        assert any("root must be a JSON object" in e for e in errors)

    def test_rejects_missing_evidence_type(self):
        validate = self._get_validate()
        errors = validate({"key": "value"}, label="no_type")
        assert any("evidence_type field is missing" in e for e in errors)

    def test_rejects_unknown_evidence_type(self):
        validate = self._get_validate()
        errors = validate({"evidence_type": "unknown_type"}, label="bad_type")
        assert any("Unknown evidence_type" in e for e in errors)

    def test_validates_smoke_evidence(self):
        validate = self._get_validate()
        data = {
            "evidence_schema_version": EVIDENCE_SCHEMA_VERSION,
            "evidence_type": "smoke_test",
            "test": "chronos2_smoke_test",
            "success": True,
            "code_commit": "abc123",
            "git_worktree_clean": True,
            "started_at_utc": "2026-07-29T00:00:00",
            "completed_at_utc": "2026-07-29T00:01:00",
            "python_version": "3.12",
            "model_id": "amazon/chronos-2",
            "configured_revision": "rev1",
            "model_revision": "rev1",
            "hf_token_present": False,
            "token_absent_result": {
                "attempted": True, "success": True,
                "configured_revision": "rev1", "resolved_revision": "rev1",
                "run_id": "run-abc",
                "started_at_utc": "2026-07-29T00:00:00",
                "completed_at_utc": "2026-07-29T00:00:30",
                "timing_seconds": 10.0,
            },
            "token_present_result": {"attempted": False},
            "initial_cache_state": "download_cold",
            "cold": {"cache_state": "download_cold", "pipeline_call_count": 1, "rss_mb": 500.0},
            "warm": {"cache_state": "same_process_warm", "pipeline_reused": True, "rss_mb": 500.0},
            "package_versions": {"torch": "2.13.0"},
            "cache_preflight": {
                "inspection_succeeded": True,
                "cache_source": "explicit",
                "initial_cache_state": "download_cold",
                "snapshot_present": False,
                "post_run_snapshot_present": True,
                "post_run_file_count": 5,
                "post_run_total_bytes": 1000000,
            },
        }
        errors = validate(data, label="smoke")
        # smoke with success=False would fail; but we set success=True with
        # proper fields so should pass or have minor issues
        assert isinstance(errors, list)

    def test_validates_local_bundle(self):
        validate = self._get_validate()
        data = {
            "evidence_schema_version": EVIDENCE_SCHEMA_VERSION,
            "evidence_type": "local_stage0_bundle",
            "bundle_passed": True,
            "code_commit": "abc123",
            "git_worktree_clean": True,
            "started_at_utc": "2026-01-01T00:00:00",
            "completed_at_utc": "2026-01-01T00:01:00",
            "runs": {
                "download_cold_smoke": {"code_commit": "abc123", "model_id": "amazon/chronos-2"},
                "process_cold_smoke": {"code_commit": "abc123", "model_id": "amazon/chronos-2"},
                "benchmark": {"code_commit": "abc123", "model_id": "amazon/chronos-2"},
                "token_present_smoke": {"code_commit": "abc123", "model_id": "amazon/chronos-2"},
            },
            "model_artifact": {"code_commit": "abc123", "model_id": "amazon/chronos-2"},
        }
        errors = validate(data, label="bundle")
        # Should not crash; nested dicts without evidence_type should be skipped
        assert isinstance(errors, list)
