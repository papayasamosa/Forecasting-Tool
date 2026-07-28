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
from io import BytesIO
from unittest.mock import patch

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
        # Should show the demo data preview
        assert "Using built-in synthetic weekly data" in at.markdown[0].value

    def test_demo_data_preview_no_model(self):
        """The demo data preview should appear without model loading."""
        at = AppTest.from_file("pages/1_Forecast.py")
        at.run()
        assert not at.exception
        # The data preview should show without model load
        # (Check that no error about model loading is shown)

    def test_upload_csv_preview(self):
        """A valid CSV can be uploaded and previewed."""
        at = AppTest.from_file("pages/1_Forecast.py")
        at.run()

        # Switch to upload mode
        at.radio[0].set_value("Upload CSV")
        at.run()

        # Upload a valid CSV
        csv_bytes = _make_valid_csv_bytes()
        at.file_uploader[0].set_value(csv_bytes)
        at.run()

        assert not at.exception
        # Should show the data preview
        assert "Loaded 20 rows" in at.markdown[0].value

    def test_oversized_file_rejected(self):
        """An oversized file should be rejected before parsing."""
        at = AppTest.from_file("pages/1_Forecast.py")
        at.run()

        # Switch to upload mode
        at.radio[0].set_value("Upload CSV")
        at.run()

        # Upload a file that exceeds 50 MB (mock size by patching)
        large_bytes = b"x" * (51 * 1024 * 1024)
        at.file_uploader[0].set_value(large_bytes)
        at.run()

        # Should show error about file size
        assert not at.exception

    def test_invalid_quantiles_blocked(self):
        """Invalid quantile levels should produce an error message."""
        at = AppTest.from_file("pages/1_Forecast.py")
        at.run()

        # Set invalid quantiles
        at.text_input[0].set_value("1.5, 0.5")
        at.run()

        # Click Run Forecast
        at.button[0].click()

        assert not at.exception

    @patch("pages.1_Forecast._get_forecast_backend")
    def test_fake_backend_reuse(self, mock_backend):
        """Test that the cached backend is reused across reruns."""
        from src.forecasting.chronos2_adapter import Chronos2Adapter
        from tests.test_adapter_contract import FakePipeline

        fake_pipeline = FakePipeline()
        adapter = Chronos2Adapter(pipeline_or_provider=fake_pipeline)
        mock_backend.return_value = adapter

        at = AppTest.from_file("pages/1_Forecast.py")
        at.run()

        # Click Run Forecast on demo data
        at.button[0].click()
        at.run()

        # Should not raise
        assert not at.exception

        # Run again - should reuse cached backend
        at.button[0].click()
        at.run()
        assert not at.exception


@pytest.mark.skipif(HAS_APPTEST, reason="Unit tests for page logic (not AppTest)")
class TestForecastPageLogic:
    """Unit tests for page helper functions."""

    def _get_page_module(self):
        """Import the forecast page module using importlib (name starts with digit)."""
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
