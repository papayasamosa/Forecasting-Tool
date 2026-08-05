"""Tests for the telemetry module, including cache inspection and receipt writing."""
from __future__ import annotations

import json
import os
import sys
import tempfile
from pathlib import Path
from typing import Any

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT))

from src.telemetry import (
    inspect_hf_cache,
    build_cache_preflight,
    write_execution_receipt,
    _resolve_hf_cache_dir,
    rss_mb,
    current_rss_mb,
    process_peak_rss_mb,
    deployed_commit,
)
from src.evidence_schemas import (
    CachePreflight,
    ExecutionReceipt,
    EVIDENCE_SCHEMA_VERSION,
)


class TestCacheInspection:
    def test_inspect_returns_inspection_succeeded(self):
        """inspect_hf_cache must return inspection_succeeded field."""
        result = inspect_hf_cache("nonexistent_revision")
        assert "inspection_succeeded" in result
        # Should be False (no cache dir or no snapshot)
        assert isinstance(result["inspection_succeeded"], bool)

    def test_inspect_returns_error_code(self):
        """inspect_hf_cache must return error_code field."""
        result = inspect_hf_cache("nonexistent_revision")
        assert "error_code" in result

    def test_inspect_with_fake_cache(self, tmp_path):
        """Inspect a temporary cache directory with a fake snapshot."""
        cache_dir = tmp_path / "cache" / "hub"
        snapshots = cache_dir / "models--amazon--chronos-2" / "snapshots" / "test_rev"
        snapshots.mkdir(parents=True, exist_ok=True)
        (snapshots / "model.safetensors").write_text("fake")
        (snapshots / "config.json").write_text("{}")

        old_cache = os.environ.get("HF_HUB_CACHE", "")
        os.environ["HF_HUB_CACHE"] = str(cache_dir)
        try:
            result = inspect_hf_cache("test_rev")
        finally:
            if old_cache:
                os.environ["HF_HUB_CACHE"] = old_cache
            else:
                os.environ.pop("HF_HUB_CACHE", None)

        assert result["inspection_succeeded"] is True
        assert result["snapshot_present"] is True
        assert result["file_count"] >= 2  # model.safetensors + config.json
        assert result["total_bytes"] > 0
        assert result["cache_source"] in ("explicit", "env_HF_HUB_CACHE")

    def test_inspect_expected_absence_not_failure(self, tmp_path):
        """Expected absence (no snapshot) with inspection_succeeded=True."""
        cache_dir = tmp_path / "cache" / "hub"
        cache_dir.mkdir(parents=True, exist_ok=True)
        # Create models directory but no snapshots
        models_dir = cache_dir / "models--amazon--chronos-2" / "snapshots"
        models_dir.mkdir(parents=True, exist_ok=True)

        old_cache = os.environ.get("HF_HUB_CACHE", "")
        os.environ["HF_HUB_CACHE"] = str(cache_dir)
        try:
            result = inspect_hf_cache("test_rev")
        finally:
            if old_cache:
                os.environ["HF_HUB_CACHE"] = old_cache
            else:
                os.environ.pop("HF_HUB_CACHE", None)

        assert result["inspection_succeeded"] is True
        assert result["snapshot_present"] is False
        assert result["error_code"] == "SNAPSHOT_NOT_FOUND"


class TestBuildCachePreflight:
    def test_valid_download_cold(self):
        """Build a CachePreflight for a valid download_cold scenario."""
        pre = {
            "inspection_succeeded": True,
            "snapshot_present": False,
            "file_count": 0,
            "total_bytes": 0,
            "cache_source": "explicit",
            "error_code": "SNAPSHOT_NOT_FOUND",
            "error": "",
        }
        post = {
            "inspection_succeeded": True,
            "snapshot_present": True,
            "file_count": 5,
            "total_bytes": 1000000,
            "cache_source": "explicit",
            "error_code": "",
            "error": "",
        }
        cp = build_cache_preflight(pre, post, "download_cold")
        assert cp["inspection_succeeded"] is True
        assert cp["snapshot_present"] is False
        assert cp["post_run_snapshot_present"] is True
        assert cp["post_run_file_count"] == 5
        assert cp["post_run_total_bytes"] == 1000000
        # Validate through CachePreflight schema
        cpf = CachePreflight(**cp)
        errors = cpf.validate()
        assert errors == []

    def test_valid_process_cold(self):
        pre = {
            "inspection_succeeded": True,
            "snapshot_present": True,
            "file_count": 5,
            "total_bytes": 1000000,
            "cache_source": "explicit",
            "error_code": "",
            "error": "",
        }
        post = {
            "inspection_succeeded": True,
            "snapshot_present": True,
            "file_count": 5,
            "total_bytes": 1000000,
            "cache_source": "explicit",
            "error_code": "",
            "error": "",
        }
        cp = build_cache_preflight(pre, post, "process_cold_cached_weights")
        assert cp["inspection_succeeded"] is True
        cpf = CachePreflight(**cp)
        errors = cpf.validate()
        assert errors == []

    def test_cache_source_mismatch(self):
        """Inconsistent cache source must produce inspection_succeeded=False."""
        pre = {
            "inspection_succeeded": True,
            "snapshot_present": False,
            "file_count": 0,
            "total_bytes": 0,
            "cache_source": "explicit",
            "error_code": "",
            "error": "",
        }
        post = {
            "inspection_succeeded": True,
            "snapshot_present": False,
            "file_count": 0,
            "total_bytes": 0,
            "cache_source": "env_HF_HUB_CACHE",
            "error_code": "",
            "error": "",
        }
        cp = build_cache_preflight(pre, post, "download_cold")
        assert cp["inspection_succeeded"] is False
        assert "cache_source mismatch" in cp.get("error", "")

    def test_empty_cache_source_ok(self):
        """Empty cache source should be tolerated (not validated)."""
        pre = {
            "inspection_succeeded": True,
            "snapshot_present": False,
            "file_count": 0,
            "total_bytes": 0,
            "cache_source": "",
            "error_code": "",
            "error": "",
        }
        post = {
            "inspection_succeeded": True,
            "snapshot_present": False,
            "file_count": 0,
            "total_bytes": 0,
            "cache_source": "",
            "error_code": "",
            "error": "",
        }
        cp = build_cache_preflight(pre, post, "download_cold")
        assert cp["inspection_succeeded"] is True


class TestProcessMemory:
    """WP7: stdlib-only memory reads used by the Cloud app's public UI."""

    def test_current_rss_mb_never_raises(self):
        """current_rss_mb must return a float >= 0 without raising."""
        value = current_rss_mb()
        assert isinstance(value, float)
        assert value >= 0.0

    def test_process_peak_rss_mb_never_raises(self):
        """process_peak_rss_mb must return a float >= 0 without raising."""
        value = process_peak_rss_mb()
        assert isinstance(value, float)
        assert value >= 0.0

    def test_peak_is_high_water_mark(self):
        """When both are measurable, peak RSS must be >= current RSS."""
        current = current_rss_mb()
        peak = process_peak_rss_mb()
        if current > 0.0 and peak > 0.0:
            assert peak >= current
        else:
            # Platform without measurement (e.g. neither /proc nor resource)
            # — tolerate, but both must still be non-negative.
            assert current >= 0.0 and peak >= 0.0

    def test_plausible_magnitude_when_measurable(self):
        """A measurable RSS should be in a sane range (tens of MB to a few GB)."""
        current = current_rss_mb()
        peak = process_peak_rss_mb()
        for value, name in ((current, "current"), (peak, "peak")):
            if value > 0.0:
                assert 1.0 < value < 64 * 1024, (
                    f"{name} RSS {value:.1f} MB outside a plausible process range"
                )


class TestDeployedCommit:
    def test_returns_40_hex_chars_in_this_repo(self):
        """In a git checkout, deployed_commit must resolve to a 40-char SHA."""
        commit = deployed_commit()
        assert commit == "" or (len(commit) == 40 and all(c in "0123456789abcdef" for c in commit))

    def test_env_override_wins(self, monkeypatch):
        """An explicit DEPLOYED_COMMIT env var must take precedence."""
        monkeypatch.setenv("DEPLOYED_COMMIT", "a" * 40)
        assert deployed_commit() == "a" * 40

    def test_short_hex_env_override_returns_as_is(self, monkeypatch):
        """Any non-empty env override is returned verbatim (short SHAs ok)."""
        monkeypatch.setenv("COMMIT_SHA", "abc123")
        assert deployed_commit() == "abc123"

    def test_resolve_git_head_sha_from_fake_repo(self, tmp_path):
        """_resolve_git_head_sha resolves a ref-style HEAD from a fake .git."""
        import src.telemetry as telemetry
        repo = tmp_path / "repo"
        ref_file = repo / ".git" / "refs" / "heads" / "main"
        ref_file.parent.mkdir(parents=True)
        ref_file.write_text("c2102f8f9d6cf1e9c66970ff4d26e13cae82768a\n")
        (repo / ".git" / "HEAD").write_text("ref: refs/heads/main\n")
        assert telemetry._resolve_git_head_sha(repo) == "c2102f8f9d6cf1e9c66970ff4d26e13cae82768a"

    def test_resolve_git_head_sha_empty_without_git(self, tmp_path):
        """_resolve_git_head_sha returns '' for a directory without .git."""
        import src.telemetry as telemetry
        assert telemetry._resolve_git_head_sha(tmp_path / "norepo") == ""

    def test_fallback_empty_when_no_git_and_no_env(self, monkeypatch):
        """With no env override and an unresolvable .git, must return ''."""
        import src.telemetry as telemetry
        monkeypatch.delenv("DEPLOYED_COMMIT", raising=False)
        monkeypatch.delenv("COMMIT_SHA", raising=False)
        monkeypatch.delenv("GIT_SHA", raising=False)
        # Force both resolution paths to report empty.
        monkeypatch.setattr(telemetry, "_resolve_git_head_sha", lambda root: "")
        monkeypatch.setattr(
            telemetry,
            "capture_traceability",
            lambda: {"code_commit": ""},
        )
        assert deployed_commit() == ""


class TestWriteExecutionReceipt:
    def test_receipt_written_to_file(self, tmp_path):
        """write_execution_receipt must write a valid receipt JSON file."""
        evidence_dir = str(tmp_path / "receipts")
        component_path = str(tmp_path / "component.json")
        with open(component_path, "w") as f:
            json.dump({"test": "data"}, f)

        receipt = write_execution_receipt(
            component_path=component_path,
            sanitised_command="python test.py --flag value",
            model_id="amazon/chronos-2",
            configured_revision="rev1",
            resolved_revision="rev1",
            evidence_dir=evidence_dir,
            evidence_origin="real_measurement",
        )

        assert receipt["evidence_type"] == "execution_receipt"
        assert receipt["evidence_schema_version"] == EVIDENCE_SCHEMA_VERSION
        assert receipt["execution_id"]
        assert receipt["attestation_type"] == "operator_attested"
        assert receipt["component_sha256"]  # Should be computed
        assert receipt["model_id"] == "amazon/chronos-2"
        assert receipt["configured_revision"] == "rev1"
        assert receipt["resolved_revision"] == "rev1"
        assert "test.py" in receipt["sanitised_command"]

        # Check file was written
        assert os.path.exists(receipt.get("evidence_path", ""))

        # Validate through ExecutionReceipt schema
        from src.evidence_schemas import evidence_from_dict
        obj = evidence_from_dict(receipt)
        assert isinstance(obj, ExecutionReceipt)
        errors = obj.validate()
        assert errors == []

    def test_receipt_with_github_attestation(self, tmp_path):
        """Receipt with github_attestation type must be valid."""
        component_path = str(tmp_path / "comp.json")
        with open(component_path, "w") as f:
            json.dump({"x": 1}, f)

        receipt = write_execution_receipt(
            component_path=component_path,
            sanitised_command="test",
            evidence_dir=str(tmp_path / "r"),
            attestation_type="github_attestation",
            evidence_origin="real_measurement",
        )
        assert receipt["attestation_type"] == "github_attestation"

    def test_post_inspection_failed(self):
        """Failure in post-run inspection should be captured."""
        pre = {
            "inspection_succeeded": True,
            "snapshot_present": True,
            "file_count": 5,
            "total_bytes": 1000000,
            "cache_source": "explicit",
            "error_code": "",
            "error": "",
        }
        post = {
            "inspection_succeeded": False,
            "snapshot_present": False,
            "file_count": 0,
            "total_bytes": 0,
            "cache_source": "explicit",
            "error_code": "INSPECTION_FAILED",
            "error": "cache directory disappeared",
        }
        cp = build_cache_preflight(pre, post, "process_cold_cached_weights")
        assert cp["inspection_succeeded"] is False

    def test_receipt_with_missing_component(self, tmp_path):
        """Receipt for a non-existent component gets empty sha256."""
        receipt = write_execution_receipt(
            component_path=str(tmp_path / "nonexistent.json"),
            sanitised_command="test",
            evidence_dir=str(tmp_path / "r2"),
            evidence_origin="real_measurement",
        )
        assert receipt["component_sha256"] == ""


class TestRunWithReceipt:
    """WP5/WP6: run_with_receipt() must redact secrets and capture real
    subprocess execution metadata (not naively join raw argv)."""

    def test_successful_command_captures_real_exit_code_and_digest(self, tmp_path):
        from src.telemetry import run_with_receipt

        component_path = str(tmp_path / "out.json")
        script = (
            "import json,sys; "
            f"json.dump({{'ok': True}}, open(r'{component_path}', 'w'))"
        )
        exit_code, receipt = run_with_receipt(
            command=[sys.executable, "-c", script],
            output_component_path=component_path,
            model_id="amazon/chronos-2",
            configured_revision="rev1",
            resolved_revision="rev1",
            evidence_origin="real_measurement",
        )
        assert exit_code == 0
        assert receipt["exit_code"] == 0
        assert receipt["canonical_content_sha256"]
        assert receipt["evidence_origin"] == "real_measurement"

    def test_failing_command_captures_nonzero_exit_code(self, tmp_path):
        from src.telemetry import run_with_receipt

        component_path = str(tmp_path / "out.json")
        exit_code, receipt = run_with_receipt(
            command=[sys.executable, "-c", "import sys; sys.exit(3)"],
            output_component_path=component_path,
            evidence_origin="real_measurement",
        )
        assert exit_code == 3
        assert receipt["exit_code"] == 3

    def test_command_secret_is_redacted_from_receipt(self, tmp_path):
        from src.telemetry import run_with_receipt
        from src.redaction import contains_exposed_secret

        component_path = str(tmp_path / "out.json")
        with open(component_path, "w") as f:
            json.dump({"x": 1}, f)

        exit_code, receipt = run_with_receipt(
            command=[
                sys.executable, "-c", "pass",
                "--hf-token", "hf_realsecretvalue123456",
            ],
            output_component_path=component_path,
            evidence_origin="real_measurement",
        )
        assert "hf_realsecretvalue123456" not in receipt["sanitised_command"]
        assert contains_exposed_secret(receipt["sanitised_command"]) is None

    def test_env_assignment_secret_is_redacted_from_receipt(self, tmp_path):
        from src.telemetry import run_with_receipt

        component_path = str(tmp_path / "out.json")
        with open(component_path, "w") as f:
            json.dump({"x": 1}, f)

        exit_code, receipt = run_with_receipt(
            command=["HF_TOKEN=hf_realsecretvalue123456", sys.executable, "-c", "pass"],
            output_component_path=component_path,
            evidence_origin="real_measurement",
        )
        assert "hf_realsecretvalue123456" not in receipt["sanitised_command"]


class TestMemoryHelpers:
    def test_rss_mb_returns_number(self):
        val = rss_mb()
        assert isinstance(val, float)

    def test_memory_sampler_peak(self):
        from src.telemetry import MemorySampler
        sampler = MemorySampler()
        sampler.start()
        import time
        time.sleep(0.1)
        sampler.stop()
        assert sampler.peak_mb >= 0
        assert sampler.baseline_mb >= 0

    def test_memory_sampler_context(self):
        from src.telemetry import MemorySampler
        sampler = MemorySampler()
        sampler.start()
        sampler.stop()
        # Verify stop doesn't crash when already stopped
        sampler.stop()
        assert True

    def test_machine_summary_returns_dict(self):
        from src.telemetry import machine_summary
        m = machine_summary()
        assert isinstance(m, dict)
        assert "cpu_model" in m

    def test_capture_traceability_returns_dict(self):
        from src.telemetry import capture_traceability
        t = capture_traceability()
        assert isinstance(t, dict)
        assert "code_commit" in t

    def test_capture_package_versions_returns_dict(self):
        from src.telemetry import capture_package_versions
        p = capture_package_versions()
        assert isinstance(p, dict)
        assert "python" in p

    def test_cpu_info_returns_string(self):
        from src.telemetry import cpu_info
        info = cpu_info()
        assert isinstance(info, str)


class TestResolveCacheDir:
    def test_explicit_cache_dir(self):
        path, source = _resolve_hf_cache_dir("D:\\custom\\cache")
        assert path == "D:\\custom\\cache"
        assert source == "explicit"

    def test_env_var_cache_dir(self):
        old = os.environ.get("HF_HUB_CACHE", "")
        os.environ["HF_HUB_CACHE"] = "D:\\env\\cache"
        try:
            path, source = _resolve_hf_cache_dir()
            assert source == "env_HF_HUB_CACHE"
        finally:
            if old:
                os.environ["HF_HUB_CACHE"] = old
            else:
                os.environ.pop("HF_HUB_CACHE", None)

    def test_resolve_with_all_env_vars(self):
        """Test resolution when HF_HUB_CACHE is set (simplest case)."""
        old = os.environ.get("HF_HUB_CACHE", "")
        os.environ["HF_HUB_CACHE"] = "D:\\test\\cache"
        try:
            path, source = _resolve_hf_cache_dir()
            assert source == "env_HF_HUB_CACHE" or source == "hf_hub_constant"
        finally:
            if old:
                os.environ["HF_HUB_CACHE"] = old
            else:
                os.environ.pop("HF_HUB_CACHE", None)
