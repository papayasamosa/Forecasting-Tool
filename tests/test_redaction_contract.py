"""WP2 contract test: every production receipt-validation path rejects the
same unsafe command, because all of them delegate to the single shared
``src.redaction.contains_exposed_secret()`` implementation rather than
maintaining their own regex list. Uses the exact PR #26 P1-1 bypass string
(a real secret with an unrelated safe marker nearby) that the old
window-based detector let through.
"""

import json

from src.evidence_schemas import EVIDENCE_ORIGIN_REAL, ExecutionReceipt, receipt_is_release_ready

UNSAFE_COMMAND = "HF_TOKEN=abcdef --token-state present"


def _valid_receipt_kwargs(**overrides):
    kwargs = dict(
        execution_id="exec-1",
        attestation_type="operator_attested",
        code_commit="abc123",
        producer_name="chronos2_smoke_test",
        producer_version="1.0",
        sanitised_command=UNSAFE_COMMAND,
        started_at_utc="2026-07-29T00:00:00",
        completed_at_utc="2026-07-29T00:01:00",
        exit_code=0,
        component_sha256="abcdef1234567890abcdef1234567890abcdef1234567890abcdef1234567890",
        model_id="amazon/chronos-2",
        configured_revision="rev1",
        resolved_revision="rev1",
        environment_summary="python=3.12 os=win32",
        evidence_origin=EVIDENCE_ORIGIN_REAL,
        git_worktree_clean=True,
    )
    kwargs.update(overrides)
    return kwargs


class TestSharedRedactionContractAcrossReceiptPaths:
    def test_execution_receipt_validate_rejects_it(self):
        receipt = ExecutionReceipt(**_valid_receipt_kwargs())
        errors = receipt.validate()
        assert any("sanitised_command contains" in e for e in errors), errors

    def test_receipt_is_release_ready_rejects_it(self):
        receipt = ExecutionReceipt(**_valid_receipt_kwargs())
        errors = receipt_is_release_ready(receipt)
        assert any("sanitised_command contains" in e for e in errors), errors

    def test_local_bundle_binding_check_rejects_it(self, tmp_path):
        from scripts.build_local_stage0_bundle import _validate_receipt_binding

        component_path = tmp_path / "component.json"
        with open(component_path, "w", encoding="utf-8") as f:
            json.dump({"evidence_type": "smoke_test"}, f)

        receipt_path = tmp_path / "receipt.json"
        with open(receipt_path, "w", encoding="utf-8") as f:
            json.dump(_valid_receipt_kwargs(), f)

        errors = _validate_receipt_binding(str(receipt_path), str(component_path), "smoke")
        assert any("sanitised_command contains" in e for e in errors), errors

    def test_readiness_verifier_check_rejects_it(self):
        from scripts.verify_stage0_evidence_readiness import _check_secret_redaction
        from src.redaction import contains_exposed_secret

        # The readiness verifier's own check must catch the same string this
        # contract test uses, proving it isn't drifting from the shared
        # detector it claims to call.
        assert contains_exposed_secret(UNSAFE_COMMAND) is not None
        assert _check_secret_redaction() == []

    def test_safe_command_passes_every_path(self, tmp_path):
        from scripts.build_local_stage0_bundle import _validate_receipt_binding

        safe_kwargs = _valid_receipt_kwargs(
            sanitised_command="HF_TOKEN=***REDACTED*** --token-state present"
        )
        receipt = ExecutionReceipt(**safe_kwargs)
        assert not any("sanitised_command contains" in e for e in receipt.validate())
        assert not any("sanitised_command contains" in e for e in receipt_is_release_ready(receipt))

        component_path = tmp_path / "component.json"
        with open(component_path, "w", encoding="utf-8") as f:
            json.dump({"evidence_type": "smoke_test"}, f)
        receipt_path = tmp_path / "receipt.json"
        with open(receipt_path, "w", encoding="utf-8") as f:
            json.dump(safe_kwargs, f)
        errors = _validate_receipt_binding(str(receipt_path), str(component_path), "smoke")
        assert not any("sanitised_command contains" in e for e in errors), errors
