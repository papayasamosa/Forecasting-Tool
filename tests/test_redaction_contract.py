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


# PR #27 review finding P1: colon-delimited sensitive values were not
# detected after the equals-only detector rewrite. Every release path that
# delegates to the shared detector must reject a colon-delimited exposure,
# and run_with_receipt must redact colon-delimited argv.
COLON_UNSAFE_COMMAND = "HF_TOKEN:abcdef --token-state present"


class TestColonDelimitedContractAcrossReceiptPaths:
    """The same cross-path contract as above, but for the colon-delimited
    form that PR #27's P1 finding said the equals-only rewrite dropped."""

    def test_execution_receipt_validate_rejects_colon_secret(self):
        receipt = ExecutionReceipt(**_valid_receipt_kwargs(sanitised_command=COLON_UNSAFE_COMMAND))
        errors = receipt.validate()
        assert any("sanitised_command contains" in e for e in errors), errors

    def test_receipt_is_release_ready_rejects_colon_secret(self):
        receipt = ExecutionReceipt(**_valid_receipt_kwargs(sanitised_command=COLON_UNSAFE_COMMAND))
        errors = receipt_is_release_ready(receipt)
        assert any("sanitised_command contains" in e for e in errors), errors

    def test_local_bundle_binding_rejects_colon_secret(self, tmp_path):
        from scripts.build_local_stage0_bundle import _validate_receipt_binding

        component_path = tmp_path / "component.json"
        with open(component_path, "w", encoding="utf-8") as f:
            json.dump({"evidence_type": "smoke_test"}, f)
        receipt_path = tmp_path / "receipt.json"
        with open(receipt_path, "w", encoding="utf-8") as f:
            json.dump(_valid_receipt_kwargs(sanitised_command=COLON_UNSAFE_COMMAND), f)

        errors = _validate_receipt_binding(str(receipt_path), str(component_path), "smoke")
        assert any("sanitised_command contains" in e for e in errors), errors

    def test_publisher_validation_rejects_colon_secret(self):
        from scripts.publish_evidence import _validate_and_load

        raw = dict(_valid_receipt_kwargs(sanitised_command=COLON_UNSAFE_COMMAND))
        raw["evidence_type"] = "execution_receipt"
        raw["evidence_schema_version"] = "2"
        _, errors = _validate_and_load(
            raw,
            expected_type="execution_receipt",
            expected_token_state=None,
            expected_initial_cache_state=None,
            expected_code_commit=None,
        )
        assert any("sanitised_command contains" in e for e in errors), errors

    def test_run_with_receipt_redacts_colon_delimited_argv(self, tmp_path):
        import sys
        from src.telemetry import run_with_receipt
        from src.redaction import contains_exposed_secret

        component_path = str(tmp_path / "out.json")
        with open(component_path, "w", encoding="utf-8") as f:
            json.dump({"x": 1}, f)

        _, receipt = run_with_receipt(
            command=["HF_TOKEN:hf_realsecretvalue123456", sys.executable, "-c", "pass"],
            output_component_path=component_path,
            evidence_origin="real_measurement",
        )
        assert "hf_realsecretvalue123456" not in receipt["sanitised_command"]
        assert contains_exposed_secret(receipt["sanitised_command"]) is None

    def test_receipt_context_redacts_colon_delimited_argv(self, tmp_path):
        from src.telemetry import ReceiptContext
        from src.redaction import sanitise_command, contains_exposed_secret

        component_path = str(tmp_path / "out.json")
        with open(component_path, "w", encoding="utf-8") as f:
            json.dump({"x": 1}, f)

        with open(component_path, encoding="utf-8") as f:
            component = json.load(f)

        with ReceiptContext() as ctx:
            receipt = ctx.build_receipt(
                output_component=component,
                sanitised_command=sanitise_command(
                    ["api_key:supersecretvalue123", "python", "x.py"]
                ),
                evidence_origin="real_measurement",
            )
        assert "supersecretvalue123" not in receipt["sanitised_command"]
        assert contains_exposed_secret(receipt["sanitised_command"]) is None

    def test_receipt_context_receipt_with_unsanitised_colon_secret_rejected(self, tmp_path):
        from src.telemetry import ReceiptContext
        from src.evidence_schemas import ExecutionReceipt, receipt_is_release_ready

        component_path = str(tmp_path / "out.json")
        with open(component_path, "w", encoding="utf-8") as f:
            json.dump({"x": 1}, f)
        with open(component_path, encoding="utf-8") as f:
            component = json.load(f)

        with ReceiptContext() as ctx:
            receipt_dict = ctx.build_receipt(
                output_component=component,
                sanitised_command="HF_TOKEN:abcdef --token-state present",
                evidence_origin="real_measurement",
            )
        receipt = ExecutionReceipt(**receipt_dict)
        errors = receipt.validate()
        assert any("sanitised_command contains" in e for e in errors), errors
        assert any("sanitised_command contains" in e for e in receipt_is_release_ready(receipt))

    def test_cloud_evidence_validation_rejects_colon_secret_receipt(self):
        from src.evidence_schemas import CloudEvidence, EVIDENCE_ORIGIN_REAL

        ev = CloudEvidence(
            evidence_schema_version="2",
            evidence_type="cloud_stage0",
            success=True,
            code_commit="abc123",
            evidence_origin=EVIDENCE_ORIGIN_REAL,
            token_absent_receipt=_valid_receipt_kwargs(sanitised_command=COLON_UNSAFE_COMMAND),
        )
        errors = ev.validate()
        assert any("sanitised_command contains" in e for e in errors), errors

    def test_readiness_verifier_catches_colon_form(self):
        from scripts.verify_stage0_evidence_readiness import _check_secret_redaction
        from src.redaction import contains_exposed_secret

        assert contains_exposed_secret(COLON_UNSAFE_COMMAND) is not None
        assert _check_secret_redaction() == []
