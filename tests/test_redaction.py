"""Tests for src/redaction.py — shared command redaction and exposure detection."""

from src.redaction import REDACTED_MARKER, contains_exposed_secret, sanitise_command


class TestSanitiseCommandFlagEqualsValue:
    def test_redacts_double_dash_token_equals(self):
        out = sanitise_command(["python", "x.py", "--token=hf_abcdef123456"])
        assert "hf_abcdef123456" not in out
        assert REDACTED_MARKER in out

    def test_redacts_hf_token_env_assignment(self):
        out = sanitise_command(["HF_TOKEN=hf_abcdef123456", "python", "x.py"])
        assert "hf_abcdef123456" not in out
        assert REDACTED_MARKER in out

    def test_redacts_password_equals(self):
        out = sanitise_command(["--password=hunter2"])
        assert "hunter2" not in out

    def test_redacts_api_key_equals(self):
        out = sanitise_command(["--api-key=sk-abc123"])
        assert "sk-abc123" not in out


class TestSanitiseCommandFlagSpaceValue:
    def test_redacts_double_dash_token_space(self):
        out = sanitise_command(["python", "x.py", "--token", "hf_abcdef123456"])
        assert "hf_abcdef123456" not in out
        assert REDACTED_MARKER in out

    def test_redacts_hf_dash_token_space(self):
        out = sanitise_command(["--hf-token", "hf_abcdef123456"])
        assert "hf_abcdef123456" not in out

    def test_redacts_secret_space(self):
        out = sanitise_command(["--secret", "topsecretvalue"])
        assert "topsecretvalue" not in out


class TestSanitiseCommandAuthorizationHeader:
    def test_redacts_single_token_header(self):
        out = sanitise_command(["-H", "Authorization: Bearer hf_abcdef123456"])
        assert "hf_abcdef123456" not in out
        assert REDACTED_MARKER in out

    def test_redacts_split_token_header(self):
        out = sanitise_command(["-H", "Authorization:", "Bearer", "hf_abcdef123456"])
        assert "hf_abcdef123456" not in out
        assert REDACTED_MARKER in out


class TestSanitiseCommandLeavesBenignArgsAlone:
    def test_leaves_non_secret_flags_untouched(self):
        out = sanitise_command(["python", "scripts/chronos2_smoke_test.py", "--initial-cache-state", "download_cold"])
        assert out == "python scripts/chronos2_smoke_test.py --initial-cache-state download_cold"

    def test_leaves_compound_token_flag_untouched(self):
        # --token-state and its value are not secrets themselves.
        out = sanitise_command(["--token-state", "present"])
        assert out == "--token-state present"

    def test_leaves_token_present_run_reference_untouched(self):
        out = sanitise_command(["--execution-id", "token-present-run-001"])
        assert out == "--execution-id token-present-run-001"

    def test_never_persists_hf_token_value(self):
        out = sanitise_command(["python", "x.py", "HF_TOKEN=hf_realsecretvalue123"])
        assert "hf_realsecretvalue123" not in out


class TestContainsExposedSecret:
    def test_detects_exposed_hf_token(self):
        assert contains_exposed_secret("HF_TOKEN=hf_realsecretvalue123") is not None

    def test_detects_exposed_bearer_header(self):
        assert contains_exposed_secret("Authorization: Bearer hf_realsecretvalue123") is not None

    def test_detects_exposed_password(self):
        assert contains_exposed_secret("password=hunter2") is not None

    def test_detects_exposed_api_key(self):
        assert contains_exposed_secret("api_key=sk-abc123") is not None

    def test_accepts_redacted_marker(self):
        assert contains_exposed_secret(f"HF_TOKEN={REDACTED_MARKER}") is None

    def test_accepts_sanitise_command_output(self):
        out = sanitise_command(["HF_TOKEN=hf_realsecretvalue123", "python", "x.py"])
        assert contains_exposed_secret(out) is None

    def test_accepts_benign_command(self):
        assert contains_exposed_secret("python scripts/chronos2_smoke_test.py --initial-cache-state download_cold") is None

    def test_accepts_token_state_reference(self):
        assert contains_exposed_secret("--token-state present") is None

    def test_accepts_empty_string(self):
        assert contains_exposed_secret("") is None

    def test_detects_exposed_space_separated_token_flag(self):
        # Regression: contains_exposed_secret() previously only matched
        # "name=value" assignment forms — a space-separated "--flag value"
        # (the form sanitise_command() already redacts) slipped through
        # undetected, found via a WP-J mutation test that mutated a
        # receipt's sanitised_command and expected publish_evidence.py to
        # reject it, but it didn't.
        assert contains_exposed_secret("python smoke_test.py --hf-token hf_realsecretvalue1234567890") is not None

    def test_detects_exposed_space_separated_secret_flag(self):
        assert contains_exposed_secret("python x.py --secret topsecretvalue") is not None

    def test_detects_raw_hf_token_literal_without_any_flag(self):
        assert contains_exposed_secret("some log line mentioning hf_realsecretvalue1234567890 in passing") is not None

    def test_accepts_space_separated_compound_token_flag(self):
        assert contains_exposed_secret("--token-state present") is None
        assert contains_exposed_secret("--token-present-run run-001") is None

    def test_accepts_space_separated_non_sensitive_flag(self):
        assert contains_exposed_secret("--initial-cache-state download_cold") is None

    def test_accepts_space_separated_redacted_marker(self):
        assert contains_exposed_secret(f"--hf-token {REDACTED_MARKER}") is None


class TestNearbySafeMarkerCannotSuppressExposure:
    """PR #26 review finding P1-1: a safe marker anywhere in a ±20-char
    window used to exempt an unrelated real exposure. Exemption must apply
    only to the matched value itself."""

    def test_hf_token_exposed_despite_nearby_token_state_marker(self):
        assert contains_exposed_secret("HF_TOKEN=abcdef --token-state present") is not None

    def test_password_exposed_despite_trailing_redacted_marker(self):
        assert contains_exposed_secret("password=hunter2 ***REDACTED***") is not None

    def test_password_exposed_despite_leading_redacted_marker(self):
        assert contains_exposed_secret("***REDACTED*** password=hunter2") is not None

    def test_secret_exposed_between_two_safe_markers(self):
        text = f"HF_TOKEN={REDACTED_MARKER} password=hunter2 HF_TOKEN={REDACTED_MARKER}"
        assert contains_exposed_secret(text) is not None

    def test_adjacent_safe_and_unsafe_assignments(self):
        assert contains_exposed_secret(f"HF_TOKEN={REDACTED_MARKER} password=hunter2") is not None
        assert contains_exposed_secret(f"password=hunter2 HF_TOKEN={REDACTED_MARKER}") is not None


class TestSafeRedactionMarkerVariants:
    def test_accepts_bracket_redacted(self):
        assert contains_exposed_secret("HF_TOKEN=[REDACTED]") is None

    def test_accepts_angle_bracket_redacted(self):
        assert contains_exposed_secret("HF_TOKEN=<redacted>") is None

    def test_accepts_mixed_case_redacted(self):
        assert contains_exposed_secret("hf_token=[Redacted]") is None

    def test_accepts_token_present_smoke_reference(self):
        assert contains_exposed_secret("token-present-smoke.json") is None

    def test_accepts_token_absent_smoke_reference(self):
        assert contains_exposed_secret("--evidence-file token-absent-smoke.json") is None


class TestQuotedAndCompoundValues:
    def test_detects_quoted_password(self):
        assert contains_exposed_secret('--password="hunter2"') is not None

    def test_accepts_quoted_redacted_marker(self):
        assert contains_exposed_secret(f'--password="{REDACTED_MARKER}"') is None

    def test_detects_quoted_space_separated_secret(self):
        assert contains_exposed_secret('--secret "topsecretvalue"') is not None

    def test_detects_env_style_assignment_without_dashes(self):
        assert contains_exposed_secret("PASSWORD=hunter2") is not None

    def test_mixed_case_name_is_still_sensitive(self):
        assert contains_exposed_secret("Password=hunter2") is not None

    def test_multiple_sensitive_arguments_first_exposure_reported(self):
        exposure = contains_exposed_secret("--token=abc123456 --password=def")
        assert exposure is not None
