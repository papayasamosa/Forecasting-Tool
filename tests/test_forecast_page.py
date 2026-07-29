"""Streamlit page tests for the Forecast page.

These tests use streamlit.testing.v1.AppTest to verify the page renders
without errors, handles file uploads, and does not load the model during
preview. No model weights are downloaded.

Note: AppTest requires a running Streamlit runtime. If AppTest is not
available, these tests are skipped.
"""
from __future__ import annotations

import os
import sys

import pytest
import pandas as pd
import numpy as np

# ---------------------------------------------------------------------------
# Check if AppTest is available
# ---------------------------------------------------------------------------
try:
    from streamlit.testing.v1 import AppTest
    HAS_APPTEST = True
except (ImportError, ModuleNotFoundError):
    HAS_APPTEST = False

# Check if streamlit itself is importable (the page module requires it)
try:
    import streamlit as _st
    HAS_STREAMLIT = True
except (ImportError, ModuleNotFoundError):
    HAS_STREAMLIT = False

# Ensure we can import from src
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_valid_csv_bytes() -> bytes:
    """Return bytes of a valid CSV with timestamp and target columns."""
    rng = np.random.default_rng(seed=42)
    dates = pd.date_range("2024-01-01", periods=20, freq="W")
    df = pd.DataFrame({
        "timestamp": dates,
        "target": 100 + rng.normal(0, 5, size=20),
    })
    return df.to_csv(index=False).encode("utf-8")


class _ExplodingBackend:
    """Backend that fails loudly if forecast() is ever called.

    Used to prove a code path does NOT trigger model inference.
    """

    def forecast(self, task):  # noqa: D401 - test double
        raise AssertionError("forecast() must not be called on this code path")


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------

@pytest.mark.skipif(not HAS_APPTEST, reason="streamlit.testing.v1.AppTest not available")
class TestForecastPageAppTest:
    """Integration tests using Streamlit's AppTest framework."""

    def test_default_page_renders(self):
        """The Forecast page should render without an exception on default settings."""
        at = AppTest.from_file("pages/1_Forecast.py")
        at.run()
        assert not at.exception
        # Should show the demo data preview (emitted via st.info, not st.markdown)
        assert "Using built-in synthetic weekly data" in at.info[0].value

    def test_demo_data_preview_no_model(self):
        """The demo data preview should appear without model loading."""
        at = AppTest.from_file("pages/1_Forecast.py")
        at.session_state["_test_backend_override"] = _ExplodingBackend()
        at.run()
        assert not at.exception
        assert "Using built-in synthetic weekly data" in at.info[0].value
        assert at.session_state["forecast_result"] is None

    def test_upload_csv_preview(self):
        """A valid CSV can be uploaded and previewed."""
        at = AppTest.from_file("pages/1_Forecast.py")
        at.run()

        # Switch to upload mode
        at.radio[0].set_value("Upload CSV")
        at.run()

        # Upload a valid CSV
        csv_bytes = _make_valid_csv_bytes()
        at.file_uploader[0].set_value(("valid.csv", csv_bytes, "text/csv"))
        at.run()

        assert not at.exception
        # Should show the data preview (emitted via st.success, not st.markdown)
        assert "Loaded 20 rows" in at.success[0].value

    def test_oversized_file_rejected(self):
        """An oversized file should be rejected before parsing."""
        at = AppTest.from_file("pages/1_Forecast.py")
        at.run()

        # Switch to upload mode
        at.radio[0].set_value("Upload CSV")
        at.run()

        # Upload a file that exceeds 50 MB
        large_bytes = b"x" * (51 * 1024 * 1024)
        at.file_uploader[0].set_value(("large.csv", large_bytes, "text/csv"))
        at.run()

        assert not at.exception
        assert "exceeds the 50 MB limit" in at.error[0].value
        assert at.session_state["cached_df"] is None
        assert at.session_state["cached_df_hash"] == ""

    def test_invalid_quantiles_blocked(self):
        """Invalid quantile levels should produce an error message."""
        at = AppTest.from_file("pages/1_Forecast.py")
        at.session_state["_test_backend_override"] = _ExplodingBackend()
        at.run()

        # Set invalid quantiles
        at.text_input[0].set_value("1.5, 0.5")
        at.run()

        # Click Run Forecast
        at.button[0].click()
        at.run()

        assert not at.exception
        assert "Invalid quantile levels" in at.error[0].value
        assert at.session_state["forecast_result"] is None

    def test_fake_backend_reuse(self):
        """The same injected backend/pipeline is reused across reruns."""
        from src.forecasting.chronos2_adapter import Chronos2Adapter
        from tests.test_adapter_contract import FakePipeline

        fake_pipeline = FakePipeline()
        adapter = Chronos2Adapter(pipeline_or_provider=fake_pipeline)

        at = AppTest.from_file("pages/1_Forecast.py")
        at.session_state["_test_backend_override"] = adapter
        at.run()

        # Click Run Forecast on demo data
        at.button[0].click()
        at.run()
        assert not at.exception
        assert fake_pipeline.call_count == 1

        # Run again - should reuse the same adapter/pipeline
        at.button[0].click()
        at.run()
        assert not at.exception
        assert fake_pipeline.call_count == 2


@pytest.mark.skipif(not HAS_STREAMLIT, reason="streamlit not installed")
class TestForecastPageLogic:
    """Unit tests for page helper functions.

    These import the page module directly via importlib (its name starts
    with a digit, so a normal `import pages.1_Forecast` is not valid
    syntax) and run regardless of whether AppTest is available.
    """

    def _get_page_module(self):
        import importlib
        return importlib.import_module("pages.1_Forecast")

    def test_build_demo_data_shape(self):
        """_build_demo_data should return a DataFrame with 104 rows."""
        mod = self._get_page_module()
        df = mod._build_demo_data()
        assert len(df) == 104
        assert list(df.columns) == ["timestamp", "target"]

    def test_parse_csv_bytes(self):
        """_parse_csv_bytes should parse valid CSV bytes into a DataFrame."""
        mod = self._get_page_module()
        csv_bytes = _make_valid_csv_bytes()
        df = mod._parse_csv_bytes(csv_bytes)
        assert len(df) == 20
        assert "timestamp" in df.columns
        assert "target" in df.columns

    def test_parse_csv_bytes_empty(self):
        """_parse_csv_bytes should raise on empty data."""
        mod = self._get_page_module()
        with pytest.raises(Exception):
            mod._parse_csv_bytes(b"")


@pytest.mark.skipif(not HAS_APPTEST, reason="streamlit.testing.v1.AppTest not available")
class TestForecastPageEmptyData:
    """WP1: Headers-only / zero-row CSV must not crash or leave button disabled."""

    def _make_headers_only_csv_bytes(self) -> bytes:
        return b"timestamp,target\n"

    def test_headers_only_csv_does_not_crash(self):
        """A headers-only CSV should not raise IndexError or leave button disabled."""
        at = AppTest.from_file("pages/1_Forecast.py")
        at.session_state["_test_backend_override"] = _ExplodingBackend()
        at.run()

        # Switch to upload mode
        at.radio[0].set_value("Upload CSV")
        at.run()

        # Upload a headers-only CSV
        csv_bytes = self._make_headers_only_csv_bytes()
        at.file_uploader[0].set_value(("empty.csv", csv_bytes, "text/csv"))
        at.run()
        assert not at.exception

        # Try to run forecast (should fail gracefully)
        at.button[0].click()
        at.run()
        assert not at.exception

    def test_headers_only_csv_shows_error(self):
        """A headers-only CSV should show a specific error about zero rows."""
        at = AppTest.from_file("pages/1_Forecast.py")
        at.session_state["_test_backend_override"] = _ExplodingBackend()
        at.run()

        at.radio[0].set_value("Upload CSV")
        at.run()

        csv_bytes = self._make_headers_only_csv_bytes()
        at.file_uploader[0].set_value(("empty.csv", csv_bytes, "text/csv"))
        at.run()

        at.button[0].click()
        at.run()
        assert not at.exception
        # Should show zero-rows error
        error_texts = [e.value for e in at.error]
        has_zero_error = any("zero valid rows" in e.lower() or "0 rows" in e for e in error_texts)
        assert has_zero_error, f"No zero-rows error found in: {error_texts}"

    def test_headers_only_csv_button_re_enabled(self):
        """The run button should be re-enabled after a zero-rows error."""
        at = AppTest.from_file("pages/1_Forecast.py")
        at.session_state["_test_backend_override"] = _ExplodingBackend()
        at.run()

        at.radio[0].set_value("Upload CSV")
        at.run()

        csv_bytes = self._make_headers_only_csv_bytes()
        at.file_uploader[0].set_value(("empty.csv", csv_bytes, "text/csv"))
        at.run()

        at.button[0].click()
        at.run()
        assert not at.exception

        # is_running should be reset to False
        assert at.session_state["is_running"] is False, "Button should be re-enabled after error"

    def test_headers_only_csv_no_backend_construction(self):
        """Backend forecast should not be called for headers-only data."""
        call_count = [0]

        class TrackingBackend:
            def forecast(self, task):
                call_count[0] += 1
                raise AssertionError("forecast() must not be called")

        at = AppTest.from_file("pages/1_Forecast.py")
        at.session_state["_test_backend_override"] = TrackingBackend()
        at.run()

        at.radio[0].set_value("Upload CSV")
        at.run()

        csv_bytes = self._make_headers_only_csv_bytes()
        at.file_uploader[0].set_value(("empty.csv", csv_bytes, "text/csv"))
        at.run()

        at.button[0].click()
        at.run()
        assert not at.exception
        assert call_count[0] == 0, "forecast() should not be called for empty dataset"
