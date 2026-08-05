"""WP9: behavioural coverage for scripts/verify_evidence_manifest.py failure
paths — unknown evidence fields, wrong nested shapes, missing files, wrong
digests, wrong semantic types, path traversal, and the CLI entry point.

These tests build small temporary manifests and referenced files so every
error branch of verify_manifest() / _validate_referenced_json() is
exercised with real data.
"""
from __future__ import annotations

import hashlib
import json
import subprocess
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT))


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _make_manifest(entries: dict, schema_version: str = "2") -> dict:
    return {
        "evidence_schema_version": schema_version,
        "last_updated": "2026-08-01T00:00:00+00:00",
        "files": entries,
    }


def _smoke_entry() -> dict:
    return {
        "evidence_schema_version": "2",
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
            "run_id": "run-absent-1",
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


class TestVerifyEvidenceManifestBehaviour:
    def _run(self, tmp_path: Path, manifest: dict, filename: str | None = None,
             content: dict | None = None) -> tuple[int, str]:
        from scripts import verify_evidence_manifest as vm
        evdir = tmp_path / "evidence"
        evdir.mkdir(exist_ok=True)
        mpath = evdir / "evidence_manifest.json"
        fname = None
        if filename is not None and content is not None:
            fpath = evdir / filename
            fpath.write_text(json.dumps(content), encoding="utf-8")
            fname = filename
            # bind hash into manifest
            entry = manifest["files"].get("smoke_test")
            if isinstance(entry, dict):
                entry["filename"] = fname
                entry["sha256"] = _sha256(fpath)
        mpath.write_text(json.dumps(manifest), encoding="utf-8")
        import contextlib
        import io
        buf = io.StringIO()
        with contextlib.redirect_stdout(buf):
            code = vm.main(["--manifest-path", str(mpath), "--evidence-dir", str(evdir)])
        return code, buf.getvalue()

    def test_valid_entry_passes(self, tmp_path):
        entries = {"smoke_test": dict(_smoke_entry(), filename=None, sha256=None,
                                     code_commit="abc123", evidence_type="smoke_test")}
        code, _ = self._run(tmp_path, _make_manifest(entries), "smoke.json", _smoke_entry())
        assert code == 0

    def test_wrong_internal_schema_version(self, tmp_path):
        data = dict(_smoke_entry(), evidence_schema_version="1")
        entries = {"smoke_test": dict(_smoke_entry(), filename=None, sha256=None,
                                     code_commit=None, evidence_type="smoke_test")}
        code, out = self._run(tmp_path, _make_manifest(entries), "smoke.json", data)
        assert code == 1
        assert "evidence_schema_version" in out

    def test_wrong_internal_evidence_type(self, tmp_path):
        data = dict(_smoke_entry(), evidence_type="benchmark_suite")
        entries = {"smoke_test": dict(_smoke_entry(), filename=None, sha256=None,
                                     code_commit=None, evidence_type="smoke_test")}
        code, out = self._run(tmp_path, _make_manifest(entries), "smoke.json", data)
        assert code == 1
        assert "evidence_type" in out

    def test_invalid_json_referenced_file(self, tmp_path):
        entries = {"smoke_test": dict(_smoke_entry(), filename=None, sha256=None,
                                     code_commit=None, evidence_type="smoke_test")}
        evdir = tmp_path / "evidence"
        evdir.mkdir(exist_ok=True)
        fpath = evdir / "smoke.json"
        fpath.write_text("{not valid json", encoding="utf-8")
        mpath = evdir / "evidence_manifest.json"
        entries["smoke_test"].update({"filename": "smoke.json", "sha256": _sha256(fpath)})
        mpath.write_text(json.dumps(_make_manifest(entries)), encoding="utf-8")
        from scripts import verify_evidence_manifest as vm
        code = vm.main(["--manifest-path", str(mpath), "--evidence-dir", str(evdir)])
        assert code == 1

    def test_non_dict_root_referenced_file(self, tmp_path):
        entries = {"smoke_test": dict(_smoke_entry(), filename=None, sha256=None,
                                     code_commit=None, evidence_type="smoke_test")}
        evdir = tmp_path / "evidence"
        evdir.mkdir(exist_ok=True)
        fpath = evdir / "smoke.json"
        fpath.write_text("[1,2,3]", encoding="utf-8")
        mpath = evdir / "evidence_manifest.json"
        entries["smoke_test"].update({"filename": "smoke.json", "sha256": _sha256(fpath)})
        mpath.write_text(json.dumps(_make_manifest(entries)), encoding="utf-8")
        from scripts import verify_evidence_manifest as vm
        code, out = _run_with_capture(vm.main, ["--manifest-path", str(mpath), "--evidence-dir", str(evdir)])
        assert code == 1
        assert "root must be a JSON object" in out

    def test_unknown_evidence_field_rejected_by_recursive_validator(self, tmp_path):
        """A misspelled/unknown field inside release evidence must fail the
        manifest verifier (strict recursive validation), not be silently
        discarded."""
        data = dict(_smoke_entry(), bogus_field="oops")
        entries = {"smoke_test": dict(_smoke_entry(), filename=None, sha256=None,
                                     code_commit=None, evidence_type="smoke_test")}
        code, out = self._run(tmp_path, _make_manifest(entries), "smoke.json", data)
        assert code == 1
        assert "unknown field" in out

    def test_wrong_nested_shape_rejected(self, tmp_path):
        """A wrong nested evidence shape (e.g. cold phase carrying an
        unknown field) must fail the manifest verifier."""
        data = dict(_smoke_entry(), cold={"cache_state": "download_cold", "nope": 1})
        entries = {"smoke_test": dict(_smoke_entry(), filename=None, sha256=None,
                                     code_commit=None, evidence_type="smoke_test")}
        code, out = self._run(tmp_path, _make_manifest(entries), "smoke.json", data)
        assert code == 1
        assert "unknown field" in out

    def test_manifest_missing(self, tmp_path):
        from scripts import verify_evidence_manifest as vm
        evdir = tmp_path / "evidence"
        evdir.mkdir(exist_ok=True)
        mpath = evdir / "evidence_manifest.json"
        # do NOT write the manifest
        code, out = _run_with_capture(vm.main, ["--manifest-path", str(mpath), "--evidence-dir", str(evdir)])
        assert code == 1
        assert "manifest not found" in out

    def test_manifest_wrong_schema_version(self, tmp_path):
        entries = {"smoke_test": dict(_smoke_entry(), filename=None, sha256=None,
                                     code_commit=None, evidence_type="smoke_test")}
        code, out = self._run(tmp_path, _make_manifest(entries, schema_version="1"),
                              "smoke.json", _smoke_entry())
        assert code == 1
        assert "evidence_schema_version" in out

    def test_manifest_empty_files(self, tmp_path):
        from scripts import verify_evidence_manifest as vm
        evdir = tmp_path / "evidence"
        evdir.mkdir(exist_ok=True)
        mpath = evdir / "evidence_manifest.json"
        mpath.write_text(json.dumps(_make_manifest({})), encoding="utf-8")
        code, out = _run_with_capture(vm.main, ["--manifest-path", str(mpath), "--evidence-dir", str(evdir)])
        assert code == 1
        assert "no file entries" in out

    def test_entry_not_a_dict(self, tmp_path):
        from scripts import verify_evidence_manifest as vm
        evdir = tmp_path / "evidence"
        evdir.mkdir(exist_ok=True)
        mpath = evdir / "evidence_manifest.json"
        mpath.write_text(json.dumps(_make_manifest({"smoke_test": "not-a-dict"})), encoding="utf-8")
        code, out = _run_with_capture(vm.main, ["--manifest-path", str(mpath), "--evidence-dir", str(evdir)])
        assert code == 1
        assert "entry must be a dict" in out

    def test_inconsistent_null_state(self, tmp_path):
        """filename present but sha256 null (or vice versa) must fail."""
        from scripts import verify_evidence_manifest as vm
        evdir = tmp_path / "evidence"
        evdir.mkdir(exist_ok=True)
        mpath = evdir / "evidence_manifest.json"
        entry = dict(_smoke_entry(), filename="smoke.json", sha256=None,
                     code_commit="abc123", evidence_type="smoke_test")
        mpath.write_text(json.dumps(_make_manifest({"smoke_test": entry})), encoding="utf-8")
        code, out = _run_with_capture(vm.main, ["--manifest-path", str(mpath), "--evidence-dir", str(evdir)])
        assert code == 1
        assert "inconsistent null state" in out

    def test_absolute_filename_rejected(self, tmp_path):
        from scripts import verify_evidence_manifest as vm
        evdir = tmp_path / "evidence"
        evdir.mkdir(exist_ok=True)
        mpath = evdir / "evidence_manifest.json"
        entry = dict(_smoke_entry(), filename=str(evdir / "smoke.json"), sha256="a" * 64,
                     code_commit="abc123", evidence_type="smoke_test")
        mpath.write_text(json.dumps(_make_manifest({"smoke_test": entry})), encoding="utf-8")
        code, out = _run_with_capture(vm.main, ["--manifest-path", str(mpath), "--evidence-dir", str(evdir)])
        assert code == 1
        assert "absolute" in out

    def test_path_traversal_rejected(self, tmp_path):
        from scripts import verify_evidence_manifest as vm
        evdir = tmp_path / "evidence"
        evdir.mkdir(exist_ok=True)
        mpath = evdir / "evidence_manifest.json"
        entry = dict(_smoke_entry(), filename="../../etc/passwd", sha256="a" * 64,
                     code_commit="abc123", evidence_type="smoke_test")
        mpath.write_text(json.dumps(_make_manifest({"smoke_test": entry})), encoding="utf-8")
        code, out = _run_with_capture(vm.main, ["--manifest-path", str(mpath), "--evidence-dir", str(evdir)])
        assert code == 1
        assert "traversal" in out

    def test_resolved_path_outside_evidence_dir_rejected(self, tmp_path):
        from scripts import verify_evidence_manifest as vm
        evdir = tmp_path / "evidence"
        evdir.mkdir(exist_ok=True)
        outside = tmp_path / "outside.json"
        outside.write_text(json.dumps(_smoke_entry()), encoding="utf-8")
        mpath = evdir / "evidence_manifest.json"
        entry = dict(_smoke_entry(), filename=str(outside), sha256=_sha256(outside),
                     code_commit="abc123", evidence_type="smoke_test")
        mpath.write_text(json.dumps(_make_manifest({"smoke_test": entry})), encoding="utf-8")
        code, out = _run_with_capture(vm.main, ["--manifest-path", str(mpath), "--evidence-dir", str(evdir)])
        # The absolute-path defense fires first and must reject it; the
        # resolved-under-evidence-dir check is the second layer.
        assert code == 1
        assert "absolute" in out or "not under" in out

    def test_referenced_file_missing_on_disk(self, tmp_path):
        from scripts import verify_evidence_manifest as vm
        evdir = tmp_path / "evidence"
        evdir.mkdir(exist_ok=True)
        mpath = evdir / "evidence_manifest.json"
        entry = dict(_smoke_entry(), filename="smoke.json", sha256="a" * 64,
                     code_commit="abc123", evidence_type="smoke_test")
        mpath.write_text(json.dumps(_make_manifest({"smoke_test": entry})), encoding="utf-8")
        code, out = _run_with_capture(vm.main, ["--manifest-path", str(mpath), "--evidence-dir", str(evdir)])
        assert code == 1
        assert "file not found" in out

    def test_wrong_digest_rejected(self, tmp_path):
        from scripts import verify_evidence_manifest as vm
        evdir = tmp_path / "evidence"
        evdir.mkdir(exist_ok=True)
        fpath = evdir / "smoke.json"
        fpath.write_text(json.dumps(_smoke_entry()), encoding="utf-8")
        mpath = evdir / "evidence_manifest.json"
        entry = dict(_smoke_entry(), filename="smoke.json", sha256="b" * 64,
                     code_commit="abc123", evidence_type="smoke_test")
        mpath.write_text(json.dumps(_make_manifest({"smoke_test": entry})), encoding="utf-8")
        code, out = _run_with_capture(vm.main, ["--manifest-path", str(mpath), "--evidence-dir", str(evdir)])
        assert code == 1
        assert "SHA-256 mismatch" in out

    def test_evidence_type_null_rejected(self, tmp_path):
        from scripts import verify_evidence_manifest as vm
        evdir = tmp_path / "evidence"
        evdir.mkdir(exist_ok=True)
        fpath = evdir / "smoke.json"
        fpath.write_text(json.dumps(_smoke_entry()), encoding="utf-8")
        mpath = evdir / "evidence_manifest.json"
        entry = dict(_smoke_entry(), filename="smoke.json", sha256=_sha256(fpath),
                     code_commit="abc123", evidence_type=None)
        mpath.write_text(json.dumps(_make_manifest({"smoke_test": entry})), encoding="utf-8")
        code, out = _run_with_capture(vm.main, ["--manifest-path", str(mpath), "--evidence-dir", str(evdir)])
        assert code == 1
        assert "evidence_type is null" in out

    def test_empty_code_commit_rejected(self, tmp_path):
        from scripts import verify_evidence_manifest as vm
        evdir = tmp_path / "evidence"
        evdir.mkdir(exist_ok=True)
        fpath = evdir / "smoke.json"
        fpath.write_text(json.dumps(_smoke_entry()), encoding="utf-8")
        mpath = evdir / "evidence_manifest.json"
        entry = dict(_smoke_entry(), filename="smoke.json", sha256=_sha256(fpath),
                     code_commit=None, evidence_type="smoke_test")
        mpath.write_text(json.dumps(_make_manifest({"smoke_test": entry})), encoding="utf-8")
        code, out = _run_with_capture(vm.main, ["--manifest-path", str(mpath), "--evidence-dir", str(evdir)])
        assert code == 1
        assert "code_commit is empty" in out

    def test_invalidated_entry_skips_recursive_validation(self, tmp_path):
        """An invalidated entry still verifies its hash but skips the
        recursive schema validation (older schema may not conform)."""
        from scripts import verify_evidence_manifest as vm
        evdir = tmp_path / "evidence"
        evdir.mkdir(exist_ok=True)
        data = {"evidence_type": "local_stage0_bundle", "old": True}
        fpath = evdir / "bundle.json"
        fpath.write_text(json.dumps(data), encoding="utf-8")
        mpath = evdir / "evidence_manifest.json"
        entry = dict(filename="bundle.json", sha256=_sha256(fpath),
                     code_commit="abc123", evidence_type="local_stage0_bundle",
                     status="invalidated", notes="old")
        mpath.write_text(json.dumps(_make_manifest({"local_stage0_bundle": entry})), encoding="utf-8")
        code, out = _run_with_capture(vm.main, ["--manifest-path", str(mpath), "--evidence-dir", str(evdir)])
        assert code == 0
        assert "INVALIDATED" in out

    def test_cli_entry_point_module_main(self, tmp_path):
        """Invoking the script as __main__ must reach main() and return 0
        for a valid manifest."""
        entries = {"smoke_test": dict(_smoke_entry(), filename=None, sha256=None,
                                     code_commit=None, evidence_type="smoke_test")}
        evdir = tmp_path / "evidence"
        evdir.mkdir(exist_ok=True)
        mpath = evdir / "evidence_manifest.json"
        mpath.write_text(json.dumps(_make_manifest(entries)), encoding="utf-8")
        result = subprocess.run(
            [sys.executable, str(REPO_ROOT / "scripts" / "verify_evidence_manifest.py"),
             "--manifest-path", str(mpath), "--evidence-dir", str(evdir)],
            capture_output=True, text=True, timeout=60,
        )
        assert result.returncode == 0, result.stdout + result.stderr


def _run_with_capture(func, args):
    import contextlib
    import io
    buf = io.StringIO()
    with contextlib.redirect_stdout(buf):
        code = func(args)
    return code, buf.getvalue()
