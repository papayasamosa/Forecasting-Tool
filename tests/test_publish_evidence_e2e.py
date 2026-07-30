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
from tests.test_evidence import _valid_smoke_dict


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
