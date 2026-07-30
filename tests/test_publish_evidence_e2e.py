"""End-to-end tests for scripts/publish_evidence.py's main() CLI entry point.

main() previously had no direct test coverage (only its internal helpers
were unit-tested), leaving the WP-F/WP-I pipeline it drives — sanitise,
prove idempotence, re-validate the sanitised object, write the file,
write receipt files, update the manifest — almost entirely unexercised.
Every test here monkeypatches EVIDENCE_DIR/MANIFEST_PATH to a tmp_path so
nothing touches the real docs/evidence/stage0/ directory or manifest.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT))

import scripts.publish_evidence as publish_evidence
from tests.test_evidence import _valid_smoke_dict, _valid_benchmark_suite_dict, _valid_model_artifact_dict


@pytest.fixture
def isolated_evidence_dir(tmp_path, monkeypatch):
    """Redirect publish_evidence's module-level output paths into tmp_path."""
    evidence_dir = tmp_path / "evidence"
    manifest_path = evidence_dir / "evidence_manifest.json"
    monkeypatch.setattr(publish_evidence, "EVIDENCE_DIR", evidence_dir)
    monkeypatch.setattr(publish_evidence, "MANIFEST_PATH", manifest_path)
    return evidence_dir, manifest_path


def _write_input(tmp_path, data) -> Path:
    path = tmp_path / "input.json"
    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f)
    return path


class TestPublishMainSmokeTest:
    def test_valid_smoke_test_publishes_and_updates_manifest(self, tmp_path, isolated_evidence_dir, monkeypatch):
        evidence_dir, manifest_path = isolated_evidence_dir
        input_path = _write_input(tmp_path, _valid_smoke_dict())
        monkeypatch.setattr(sys, "argv", [
            "publish_evidence.py", str(input_path), "--type", "smoke_test",
            "--expected-token-state", "absent",
        ])

        rc = publish_evidence.main()

        assert rc == 0
        assert manifest_path.exists()
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        entry = manifest["files"]["smoke_test"]
        assert entry["evidence_type"] == "smoke_test"
        assert entry["code_commit"] == "abc123"
        published = evidence_dir / entry["filename"]
        assert published.exists()
        # The manifest's hash must match the actual published bytes
        import hashlib
        assert hashlib.sha256(published.read_bytes()).hexdigest() == entry["sha256"]

    def test_dry_run_validates_but_does_not_write(self, tmp_path, isolated_evidence_dir, monkeypatch):
        evidence_dir, manifest_path = isolated_evidence_dir
        input_path = _write_input(tmp_path, _valid_smoke_dict())
        monkeypatch.setattr(sys, "argv", [
            "publish_evidence.py", str(input_path), "--type", "smoke_test",
            "--expected-token-state", "absent", "--dry-run",
        ])

        rc = publish_evidence.main()

        assert rc == 0
        assert not manifest_path.exists()

    def test_missing_input_file_fails(self, tmp_path, isolated_evidence_dir, monkeypatch):
        monkeypatch.setattr(sys, "argv", [
            "publish_evidence.py", str(tmp_path / "does_not_exist.json"), "--type", "smoke_test",
        ])
        assert publish_evidence.main() == 1

    def test_invalid_json_input_fails(self, tmp_path, isolated_evidence_dir, monkeypatch):
        bad_path = tmp_path / "bad.json"
        bad_path.write_text("{not valid json", encoding="utf-8")
        monkeypatch.setattr(sys, "argv", [
            "publish_evidence.py", str(bad_path), "--type", "smoke_test",
        ])
        assert publish_evidence.main() == 1

    def test_missing_evidence_origin_fails(self, tmp_path, isolated_evidence_dir, monkeypatch):
        data = _valid_smoke_dict()
        del data["evidence_origin"]
        input_path = _write_input(tmp_path, data)
        monkeypatch.setattr(sys, "argv", [
            "publish_evidence.py", str(input_path), "--type", "smoke_test",
            "--expected-token-state", "absent",
        ])
        assert publish_evidence.main() == 1

    def test_synthetic_origin_rejected(self, tmp_path, isolated_evidence_dir, monkeypatch):
        data = _valid_smoke_dict({"evidence_origin": "synthetic_fixture"})
        input_path = _write_input(tmp_path, data)
        monkeypatch.setattr(sys, "argv", [
            "publish_evidence.py", str(input_path), "--type", "smoke_test",
            "--expected-token-state", "absent",
        ])
        assert publish_evidence.main() == 1

    def test_wrong_token_state_rejected(self, tmp_path, isolated_evidence_dir, monkeypatch):
        data = _valid_smoke_dict()
        input_path = _write_input(tmp_path, data)
        monkeypatch.setattr(sys, "argv", [
            "publish_evidence.py", str(input_path), "--type", "smoke_test",
            "--expected-token-state", "present",
        ])
        assert publish_evidence.main() == 1

    def test_second_publish_gets_distinct_filename(self, tmp_path, isolated_evidence_dir, monkeypatch):
        """Collision guard: publishing twice must not overwrite the first file."""
        evidence_dir, manifest_path = isolated_evidence_dir
        input_path = _write_input(tmp_path, _valid_smoke_dict())
        monkeypatch.setattr(sys, "argv", [
            "publish_evidence.py", str(input_path), "--type", "smoke_test",
            "--expected-token-state", "absent",
        ])
        assert publish_evidence.main() == 0
        first_files = set(evidence_dir.glob("evidence_smoke_test_*.json"))
        assert publish_evidence.main() == 0
        second_files = set(evidence_dir.glob("evidence_smoke_test_*.json"))
        assert len(second_files) == len(first_files) + 1


class TestPublishMainReceiptFiles:
    def test_local_stage0_bundle_writes_real_receipt_files(self, tmp_path, isolated_evidence_dir, monkeypatch):
        """WP-I: publishing a bundle must write each receipt as its own
        real file with a byte-accurate SHA-256 in the manifest, never a
        synthetic embedded_in_<bundle> filename."""
        evidence_dir, manifest_path = isolated_evidence_dir
        from src.evidence_schemas import canonical_evidence_sha256

        receipt = {
            "evidence_schema_version": "2",
            "evidence_type": "execution_receipt",
            "execution_id": "exec-1",
            "attestation_type": "operator_attested",
            "code_commit": "abc123",
            "producer_version": "1.0",
            "sanitised_command": "python smoke_test.py",
            "started_at_utc": "2026-07-29T00:00:00",
            "completed_at_utc": "2026-07-29T00:00:30",
            "exit_code": 0,
            "canonical_content_sha256": "a" * 64,
            "model_id": "amazon/chronos-2",
            "configured_revision": "rev1",
            "resolved_revision": "rev1",
            "environment_summary": "python=3.12",
            "evidence_origin": "real_measurement",
        }
        data = {
            "evidence_schema_version": "2",
            "evidence_type": "local_stage0_bundle",
            "evidence_origin": "real_measurement",
            "bundle_passed": False,
            "code_commit": "abc123",
            "git_worktree_clean": True,
            "started_at_utc": "2026-07-29T00:00:00",
            "completed_at_utc": "2026-07-29T00:01:00",
            "runs": {
                "download_cold_smoke": {"code_commit": "abc123"},
                "process_cold_smoke": {"code_commit": "abc123"},
                "benchmark": {"code_commit": "abc123"},
                "token_present_smoke": {"code_commit": "abc123"},
            },
            "model_artifact": {"code_commit": "abc123"},
            "receipts": {"download_cold_smoke_receipt": receipt},
        }
        input_path = _write_input(tmp_path, data)
        monkeypatch.setattr(sys, "argv", [
            "publish_evidence.py", str(input_path), "--type", "local_stage0_bundle",
        ])

        rc = publish_evidence.main()

        assert rc == 0
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        rec_entry = manifest["files"]["receipt_download_cold_smoke_receipt"]
        assert rec_entry["evidence_type"] == "execution_receipt"
        assert not rec_entry["filename"].startswith("embedded_in_")
        receipt_file = evidence_dir / rec_entry["filename"]
        assert receipt_file.exists()
        import hashlib
        assert hashlib.sha256(receipt_file.read_bytes()).hexdigest() == rec_entry["sha256"]


class TestPublishMainMutations:
    """WP-J: for each evidence type/field category the spec calls out —
    smoke, benchmark, artifact, receipt origin, receipt command, exit
    code, digest — start from a value main() accepts, mutate exactly one
    field, and prove main() rejects the mutated version. Each test's
    first assertion (rc == 0 on the unmutated baseline) is what makes
    this a mutation test rather than an isolated negative-path test: it
    proves the rejection is caused by the mutation, not by some other
    defect in the fixture."""

    def _publish(self, tmp_path, isolated_evidence_dir, monkeypatch, data, evidence_type, extra_args=()):
        input_path = _write_input(tmp_path, data)
        monkeypatch.setattr(sys, "argv", [
            "publish_evidence.py", str(input_path), "--type", evidence_type, *extra_args,
        ])
        return publish_evidence.main()

    def test_benchmark_suite_baseline_passes_then_missing_origin_fails(self, tmp_path, isolated_evidence_dir, monkeypatch):
        baseline = _valid_benchmark_suite_dict()
        assert self._publish(tmp_path, isolated_evidence_dir, monkeypatch, baseline, "benchmark_suite") == 0

        mutated = _valid_benchmark_suite_dict()
        del mutated["evidence_origin"]
        assert self._publish(tmp_path, isolated_evidence_dir, monkeypatch, mutated, "benchmark_suite") == 1

    def test_benchmark_suite_baseline_passes_then_synthetic_origin_fails(self, tmp_path, isolated_evidence_dir, monkeypatch):
        baseline = _valid_benchmark_suite_dict()
        assert self._publish(tmp_path, isolated_evidence_dir, monkeypatch, baseline, "benchmark_suite") == 0

        mutated = _valid_benchmark_suite_dict({"evidence_origin": "synthetic_fixture"})
        assert self._publish(tmp_path, isolated_evidence_dir, monkeypatch, mutated, "benchmark_suite") == 1

    def test_model_artifact_baseline_passes_then_missing_origin_fails(self, tmp_path, isolated_evidence_dir, monkeypatch):
        baseline = _valid_model_artifact_dict()
        assert self._publish(tmp_path, isolated_evidence_dir, monkeypatch, baseline, "model_artifact") == 0

        mutated = _valid_model_artifact_dict()
        del mutated["evidence_origin"]
        assert self._publish(tmp_path, isolated_evidence_dir, monkeypatch, mutated, "model_artifact") == 1

    def test_model_artifact_baseline_passes_then_malformed_digest_fails(self, tmp_path, isolated_evidence_dir, monkeypatch):
        """Digest-field mutation: each file's sha256 must be a well-formed
        64-hex-char SHA-256 — a truncated/malformed value must fail
        publication even though every other field is unchanged."""
        baseline = _valid_model_artifact_dict()
        assert self._publish(tmp_path, isolated_evidence_dir, monkeypatch, baseline, "model_artifact") == 0

        mutated = _valid_model_artifact_dict()
        mutated["files"][0]["sha256"] = "not-a-valid-sha256"
        assert self._publish(tmp_path, isolated_evidence_dir, monkeypatch, mutated, "model_artifact") == 1

    def test_smoke_baseline_passes_then_missing_origin_fails(self, tmp_path, isolated_evidence_dir, monkeypatch):
        baseline = _valid_smoke_dict()
        assert self._publish(
            tmp_path, isolated_evidence_dir, monkeypatch, baseline, "smoke_test",
            extra_args=["--expected-token-state", "absent"],
        ) == 0

        mutated = _valid_smoke_dict()
        del mutated["evidence_origin"]
        assert self._publish(
            tmp_path, isolated_evidence_dir, monkeypatch, mutated, "smoke_test",
            extra_args=["--expected-token-state", "absent"],
        ) == 1

    @staticmethod
    def _passing_bundle(receipt_overrides: dict | None = None) -> dict:
        """Build a fully valid, bundle_passed=True local_stage0_bundle with
        all 5 required receipts correctly keyed (LocalStage0Bundle._validate_
        receipts()'s expected_receipts list — no "_receipt" suffix) and
        digest-bound. ``receipt_overrides`` is applied to every receipt, so
        a single-field mutation stays isolated to that one field."""
        from src.evidence_schemas import canonical_evidence_sha256

        run = {"code_commit": "abc123", "success": True}
        receipt_common = {
            "evidence_schema_version": "2",
            "evidence_type": "execution_receipt",
            "attestation_type": "operator_attested",
            "code_commit": "abc123",
            "producer_version": "1.0",
            "sanitised_command": "python smoke_test.py --initial-cache-state download_cold",
            "started_at_utc": "2026-07-29T00:00:00",
            "completed_at_utc": "2026-07-29T00:00:30",
            "exit_code": 0,
            "model_id": "amazon/chronos-2",
            "configured_revision": "rev1",
            "resolved_revision": "rev1",
            "environment_summary": "python=3.12",
            "evidence_origin": "real_measurement",
            "git_worktree_clean": True,
            **(receipt_overrides or {}),
        }
        receipts: dict = {}
        runs: dict = {}
        for key in ("download_cold_smoke", "process_cold_smoke", "benchmark", "token_present_smoke"):
            runs[key] = dict(run)
            receipts[key] = {
                **receipt_common,
                "execution_id": f"exec-{key}",
                "canonical_content_sha256": canonical_evidence_sha256(runs[key]),
                **(receipt_overrides or {}),
            }
        model_artifact = {"code_commit": "abc123"}
        receipts["model_artifact"] = {
            **receipt_common,
            "execution_id": "exec-model_artifact",
            "canonical_content_sha256": canonical_evidence_sha256(model_artifact),
            **(receipt_overrides or {}),
        }
        return {
            "evidence_schema_version": "2",
            "evidence_type": "local_stage0_bundle",
            "evidence_origin": "real_measurement",
            "bundle_passed": True,
            "code_commit": "abc123",
            "git_worktree_clean": True,
            "started_at_utc": "2026-07-29T00:00:00",
            "completed_at_utc": "2026-07-29T00:01:00",
            "runs": runs,
            "model_artifact": model_artifact,
            "receipts": receipts,
        }

    def test_bundle_receipt_command_exposure_mutation_fails(self, tmp_path, isolated_evidence_dir, monkeypatch):
        """Receipt-command mutation: a receipt whose sanitised_command
        carries an unredacted secret must fail publication, even though
        every other field is otherwise valid."""
        baseline = self._passing_bundle()
        assert self._publish(tmp_path, isolated_evidence_dir, monkeypatch, baseline, "local_stage0_bundle") == 0

        mutated = self._passing_bundle({
            "sanitised_command": "python smoke_test.py --hf-token hf_realsecretvalue1234567890",
        })
        assert self._publish(tmp_path, isolated_evidence_dir, monkeypatch, mutated, "local_stage0_bundle") == 1

    def test_bundle_receipt_exit_code_mutation_fails_when_passing(self, tmp_path, isolated_evidence_dir, monkeypatch):
        """Receipt exit-code mutation: once a bundle claims bundle_passed
        and evidence_origin=real_measurement, a receipt with a non-zero
        exit_code must fail publication (receipt_is_release_ready)."""
        baseline = self._passing_bundle()
        assert self._publish(tmp_path, isolated_evidence_dir, monkeypatch, baseline, "local_stage0_bundle") == 0

        mutated = self._passing_bundle({"exit_code": 1})
        assert self._publish(tmp_path, isolated_evidence_dir, monkeypatch, mutated, "local_stage0_bundle") == 1

    def test_bundle_receipt_origin_mutation_fails_when_passing(self, tmp_path, isolated_evidence_dir, monkeypatch):
        """Receipt evidence_origin mutation: a synthetic receipt embedded
        in a bundle claiming real_measurement/bundle_passed must fail
        publication."""
        baseline = self._passing_bundle()
        assert self._publish(tmp_path, isolated_evidence_dir, monkeypatch, baseline, "local_stage0_bundle") == 0

        mutated = self._passing_bundle({"evidence_origin": "synthetic_fixture"})
        assert self._publish(tmp_path, isolated_evidence_dir, monkeypatch, mutated, "local_stage0_bundle") == 1

    def test_bundle_receipt_digest_mutation_fails_when_passing(self, tmp_path, isolated_evidence_dir, monkeypatch):
        """Digest-field mutation: a receipt's canonical_content_sha256 that
        no longer matches its bound component must fail publication —
        this is the tamper-evidence property WP-F/WP-I exist to provide."""
        baseline = self._passing_bundle()
        assert self._publish(tmp_path, isolated_evidence_dir, monkeypatch, baseline, "local_stage0_bundle") == 0

        mutated = self._passing_bundle({"canonical_content_sha256": "f" * 64})
        assert self._publish(tmp_path, isolated_evidence_dir, monkeypatch, mutated, "local_stage0_bundle") == 1
