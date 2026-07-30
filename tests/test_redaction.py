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
