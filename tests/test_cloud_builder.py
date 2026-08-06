"""Tests for scripts/build_cloud_stage0_evidence.py — WP-G/WP-H.

Covers: schema-level receipt digest binding (WP-G), the CloudCollectionSession
record collection_receipt binds to (WP-G), and synthetic-mode behaviour
(WP-H) — production mode rejects synthetic receipts even if the CLI flag is
omitted by mistake, synthetic mode requires synthetic receipts rather than
silently tolerating missing ones, and synthetic fixture values are obviously
fake. No network access, no model download.
"""
from __future__ import annotations

import copy
import json
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent
FIXTURE_PATH = REPO_ROOT / "tests" / "fixtures" / "cloud_valid_fixture.json"


def _load_fixture() -> dict:
    with open(FIXTURE_PATH, encoding="utf-8") as f:
        return json.load(f)


class TestCloudCollectionSession:
    def test_valid_session_passes(self):
        from src.evidence_schemas import CloudCollectionSession
        session = CloudCollectionSession(
            evidence_origin="real_measurement",
            session_id="s1",
            code_commit="8c3c67c4cb4302bb788f4801ae3fd2e57032c4a9",
            deployed_commit="8c3c67c4cb4302bb788f4801ae3fd2e57032c4a9",
            deployment_url="https://example.streamlit.app",
            diagnostics_digest="d" * 64,
            test_names=["dependency_install"],
            started_at_utc="2026-07-30T00:00:00",
            completed_at_utc="2026-07-30T00:01:00",
        )
        assert session.validate() == []

    def test_real_session_requires_exact_deployed_commit(self):
        """WP3: real collection sessions must carry an exact 40-char SHA —
        short SHAs and arbitrary text are rejected for release evidence."""
        from src.evidence_schemas import CloudCollectionSession
        session = CloudCollectionSession(
            evidence_origin="real_measurement",
            session_id="s1",
            code_commit="abc123",
            deployed_commit="abc123",
            deployment_url="https://example.streamlit.app",
            diagnostics_digest="d" * 64,
            test_names=["dependency_install"],
            started_at_utc="2026-07-30T00:00:00",
            completed_at_utc="2026-07-30T00:01:00",
        )
        errors = session.validate()
        assert any("deployed_commit" in e and "not exactly 40" in e for e in errors)

    def test_real_session_requires_deployment_binding(self):
        """WP11: a real collection session must bind the deployment URL and
        the runtime-diagnostics digest."""
        from src.evidence_schemas import CloudCollectionSession
        session = CloudCollectionSession(
            evidence_origin="real_measurement",
            session_id="s1",
            code_commit="8c3c67c4cb4302bb788f4801ae3fd2e57032c4a9",
            deployed_commit="8c3c67c4cb4302bb788f4801ae3fd2e57032c4a9",
            test_names=["dependency_install"],
            started_at_utc="2026-07-30T00:00:00",
            completed_at_utc="2026-07-30T00:01:00",
        )
        errors = session.validate()
        assert any("deployment_url" in e for e in errors)
        assert any("diagnostics_digest" in e for e in errors)

    def test_missing_test_names_rejected(self):
        from src.evidence_schemas import CloudCollectionSession
        session = CloudCollectionSession(
            evidence_origin="real_measurement",
            session_id="s1",
            code_commit="abc123",
            started_at_utc="2026-07-30T00:00:00",
            completed_at_utc="2026-07-30T00:01:00",
        )
        errors = session.validate()
        assert any("test_names" in e for e in errors)

    def test_missing_session_id_rejected(self):
        from src.evidence_schemas import CloudCollectionSession
        session = CloudCollectionSession(
            evidence_origin="real_measurement",
            code_commit="abc123",
            test_names=["dependency_install"],
            started_at_utc="2026-07-30T00:00:00",
            completed_at_utc="2026-07-30T00:01:00",
        )
        errors = session.validate()
        assert any("session_id" in e for e in errors)

    def test_invalid_origin_rejected(self):
        from src.evidence_schemas import CloudCollectionSession
        session = CloudCollectionSession(
            evidence_origin="not_a_real_origin",
            session_id="s1",
            code_commit="abc123",
            test_names=["dependency_install"],
            started_at_utc="2026-07-30T00:00:00",
            completed_at_utc="2026-07-30T00:01:00",
        )
        errors = session.validate()
        assert any("evidence_origin" in e for e in errors)

    def test_completed_before_started_rejected(self):
        from src.evidence_schemas import CloudCollectionSession
        session = CloudCollectionSession(
            evidence_origin="real_measurement",
            session_id="s1",
            code_commit="abc123",
            test_names=["dependency_install"],
            started_at_utc="2026-07-30T01:00:00",
            completed_at_utc="2026-07-30T00:00:00",
        )
        errors = session.validate()
        assert any("completed_at_utc before started_at_utc" in e for e in errors)


class TestCloudBuilderSyntheticMode:
    """WP-H: production mode rejects synthetic receipts; synthetic mode
    requires synthetic receipts rather than tolerating missing ones."""

    def test_synthetic_fixture_passes_in_synthetic_mode(self):
        from scripts.build_cloud_stage0_evidence import _build_cloud_evidence
        data = _load_fixture()
        evidence = _build_cloud_evidence(data, allow_synthetic=True)
        assert evidence.success, evidence.error
        assert evidence.evidence_origin == "synthetic_fixture"

    def test_synthetic_fixture_rejected_in_production_mode(self):
        """Omitting --allow-synthetic-fixture must not relabel synthetic
        receipts as real — the schema-level origin check must catch it
        even though the CLI flag alone no longer gates rejection."""
        from scripts.build_cloud_stage0_evidence import _build_cloud_evidence
        data = _load_fixture()
        evidence = _build_cloud_evidence(data, allow_synthetic=False)
        assert not evidence.success
        assert "evidence_origin" in evidence.error
        assert "synthetic_fixture" in evidence.error

    def test_synthetic_mode_does_not_tolerate_missing_receipts(self):
        """Synthetic mode skips the early structural pre-check, but
        CloudEvidence.validate() still requires all three receipts and
        collection_session regardless of evidence_origin — synthetic mode
        must supply synthetic receipts, not omit them."""
        from scripts.build_cloud_stage0_evidence import _build_cloud_evidence
        data = _load_fixture()
        for key in ("token_absent_receipt", "token_present_receipt", "collection_receipt", "collection_session"):
            data.pop(key, None)
        evidence = _build_cloud_evidence(data, allow_synthetic=True)
        assert not evidence.success
        assert "missing or empty" in evidence.error

    def test_check_receipts_production_mode_requires_all_three(self):
        from scripts.build_cloud_stage0_evidence import _check_receipts
        errors = _check_receipts({}, allow_synthetic=False)
        assert len(errors) == 3
        assert any("token_absent_receipt" in e for e in errors)
        assert any("token_present_receipt" in e for e in errors)
        assert any("collection_receipt" in e for e in errors)

    def test_check_receipts_synthetic_mode_skips_precheck(self):
        from scripts.build_cloud_stage0_evidence import _check_receipts
        errors = _check_receipts({}, allow_synthetic=True)
        assert errors == []

    def test_fixture_values_are_obviously_synthetic(self):
        """Synthetic fixture content must be unmistakably fake, not just
        structurally valid — so it can never be confused for a real
        execution even if evidence_origin were stripped by accident."""
        data = _load_fixture()
        for key in ("token_absent_receipt", "token_present_receipt", "collection_receipt"):
            rec = data[key]
            assert "SYNTHETIC" in rec["sanitised_command"]
            assert "SYNTHETIC" in rec["environment_summary"]
            assert rec["evidence_origin"] == "synthetic_fixture"


class TestCloudBuilderDigestBinding:
    """WP-G: token/collection receipts must bind the canonical digest of
    the exact result/session they describe — schema-level, not just in
    the builder script."""

    def test_token_absent_digest_mismatch_rejected(self):
        from scripts.build_cloud_stage0_evidence import _build_cloud_evidence
        data = _load_fixture()
        data["token_absent_receipt"]["canonical_content_sha256"] = "f" * 64
        evidence = _build_cloud_evidence(data, allow_synthetic=True)
        assert not evidence.success
        assert "token_absent_receipt" in evidence.error
        assert "canonical_content_sha256" in evidence.error

    def test_token_present_digest_mismatch_rejected(self):
        from scripts.build_cloud_stage0_evidence import _build_cloud_evidence
        data = _load_fixture()
        data["token_present_receipt"]["canonical_content_sha256"] = "f" * 64
        evidence = _build_cloud_evidence(data, allow_synthetic=True)
        assert not evidence.success
        assert "token_present_receipt" in evidence.error

    def test_collection_receipt_digest_mismatch_rejected(self):
        from scripts.build_cloud_stage0_evidence import _build_cloud_evidence
        data = _load_fixture()
        data["collection_receipt"]["canonical_content_sha256"] = "f" * 64
        evidence = _build_cloud_evidence(data, allow_synthetic=True)
        assert not evidence.success
        assert "collection_receipt" in evidence.error

    def test_missing_collection_session_rejected(self):
        from scripts.build_cloud_stage0_evidence import _build_cloud_evidence
        data = _load_fixture()
        del data["collection_session"]
        evidence = _build_cloud_evidence(data, allow_synthetic=True)
        assert not evidence.success
        assert "collection_session" in evidence.error

    def test_mutated_result_after_receipt_bound_is_detected(self):
        """If token_absent_result content changes after the receipt was
        bound, the digest no longer matches — this is the tamper-evidence
        property the canonical digest exists to provide."""
        from scripts.build_cloud_stage0_evidence import _build_cloud_evidence
        data = _load_fixture()
        data["token_absent_result"]["timing_seconds"] = 999.0
        evidence = _build_cloud_evidence(data, allow_synthetic=True)
        assert not evidence.success
        assert "token_absent_receipt" in evidence.error

    def test_valid_fixture_digests_are_real_not_placeholder(self):
        """Regression guard: the fixture's digests must be genuine
        canonical_evidence_sha256 outputs, not copy-pasted placeholder
        hex strings — otherwise this test file and the fixture drift
        apart silently the next time either changes."""
        from src.evidence_schemas import TokenPathResult, CloudCollectionSession, canonical_evidence_sha256
        data = _load_fixture()
        expected_tar = canonical_evidence_sha256(TokenPathResult(**data["token_absent_result"]).to_dict())
        expected_tpr = canonical_evidence_sha256(TokenPathResult(**data["token_present_result"]).to_dict())
        expected_session = canonical_evidence_sha256(
            CloudCollectionSession(**data["collection_session"]).to_dict()
        )
        assert data["token_absent_receipt"]["canonical_content_sha256"] == expected_tar
        assert data["token_present_receipt"]["canonical_content_sha256"] == expected_tpr
        assert data["collection_receipt"]["canonical_content_sha256"] == expected_session
