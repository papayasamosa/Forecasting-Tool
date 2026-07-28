"""Streamlit page: Forecast — Stage 0 (not yet Phase 1).

The Chronos-2 model is loaded only when the user clicks "Run Forecast".
The backend is cached at the process level via ``st.cache_resource``.
"""
from __future__ import annotations

import logging
import os
import sys
from io import StringIO, BytesIO

import streamlit as st
import pandas as pd

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from src.schemas import ForecastMode, ForecastTask  # noqa: E402
from src.forecasting.chronos2_adapter import (  # noqa: E402
    Chronos2Adapter,
    AdapterError,
)

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Page config
# ---------------------------------------------------------------------------
st.set_page_config(page_title="Forecast — Chronos-2", page_icon="📈", layout="wide")

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------
MAX_UPLOAD_BYTES = 50 * 1024 * 1024  # 50 MB

# ---------------------------------------------------------------------------
# Helpers (defined BEFORE their first use to avoid NameError)
# ---------------------------------------------------------------------------

def _build_demo_data() -> pd.DataFrame:
    """Return a synthetic weekly time-series fixture (104 periods)."""
    import numpy as np
    rng = np.random.default_rng(seed=42)
    t = np.arange(104)
    values = 100 + 0.05 * t + 5 * np.sin(2 * np.pi * t / 52) + rng.normal(0, 2, size=104)
    dates = pd.date_range("2022-01-03", periods=104, freq="W")
    return pd.DataFrame({"timestamp": dates, "target": values})


@st.cache_resource
def _get_forecast_backend() -> Chronos2Adapter:
    """Return a process-cached Chronos2Adapter (model loads on first forecast)."""
    logger.info("Creating Chronos2Adapter (process-level cache).")
    return Chronos2Adapter()


def _resolve_backend() -> Chronos2Adapter:
    """Return the backend to use for this run.

    Test-only seam: if st.session_state["_test_backend_override"] is set, it
    is returned instead of the process-cached backend. This exists because
    this module's name starts with a digit, so unittest.mock.patch cannot
    target it (pkgutil.resolve_name rejects "pages.1_Forecast" as an invalid
    dotted name), and Streamlit's AppTest executes this script outside
    normal import machinery anyway. Production code paths never set this
    session_state key.
    """
    override = st.session_state.get("_test_backend_override")
    if override is not None:
        return override
    return _get_forecast_backend()


def _parse_csv_bytes(file_bytes: bytes) -> pd.DataFrame:
    """Parse uploaded CSV bytes once and return a DataFrame."""
    return pd.read_csv(BytesIO(file_bytes))


# ---------------------------------------------------------------------------
# Session state (configuration and results, NOT the model)
# ---------------------------------------------------------------------------
_DEFAULT_STATE = {
    "run_id": "",
    "forecast_result": None,
    "error_message": "",
    "is_running": False,
    "cached_df": None,           # parsed DataFrame reused across reruns
    "cached_file_bytes": None,   # raw bytes to avoid re-read
    "cached_columns": [],
    "pipeline_was_loaded": False,  # tracks whether model was loaded this session
}
for k, v in _DEFAULT_STATE.items():
    if k not in st.session_state:
        st.session_state[k] = v

# ---------------------------------------------------------------------------
# Page layout
# ---------------------------------------------------------------------------
st.title("🔮 Chronos-2 Forecast")
st.markdown("_Stage 0 — Technical Feasibility Spike | Not yet Phase 1_")

with st.sidebar:
    st.header("Configuration")

    data_option = st.radio("Data source", ["Use demo data", "Upload CSV"], index=0)

    uploaded_file = None
    ts_col = "timestamp"
    target_col = "target"

    # Reset cached data when switching data sources
    if "last_data_option" not in st.session_state or st.session_state.last_data_option != data_option:
        st.session_state.cached_df = None
        st.session_state.cached_file_bytes = None
        st.session_state.last_data_option = data_option

    if data_option == "Upload CSV":
        uploaded_file = st.file_uploader("Choose a CSV file", type=["csv"])
        if uploaded_file is not None:
            # Check size before reading
            uploaded_file.seek(0, os.SEEK_END)
            size = uploaded_file.tell()
            uploaded_file.seek(0)
            if size > MAX_UPLOAD_BYTES:
                st.error(f"File exceeds the 50 MB limit ({size / 1024 / 1024:.1f} MB).")
                uploaded_file = None
                st.session_state.cached_df = None
                st.session_state.cached_file_bytes = None
            else:
                # Bytes are re-read on every rerun the file stays selected;
                # only the parsed DataFrame below is cached (keyed on
                # content) to avoid re-parsing identical uploads.
                file_bytes = uploaded_file.read()
                if st.session_state.cached_file_bytes != file_bytes:
                    st.session_state.cached_file_bytes = file_bytes
                    try:
                        st.session_state.cached_df = _parse_csv_bytes(file_bytes)
                        st.session_state.cached_columns = st.session_state.cached_df.columns.tolist()
                    except Exception:
                        st.error("Could not parse CSV. Please check the file format.")
                        st.session_state.cached_df = None
                        st.session_state.cached_file_bytes = None

                if st.session_state.cached_df is not None:
                    cols = st.session_state.cached_columns
                    ts_col = st.selectbox("Timestamp column", cols, index=0, key="ts_col")
                    target_col = st.selectbox("Target column", cols, index=min(1, len(cols) - 1), key="target_col")

    st.markdown("---")
    horizon = st.number_input("Forecast horizon (periods)", min_value=1, max_value=1024, value=13, step=1)
    quantiles_str = st.text_input("Quantile levels (comma-separated)", value="0.1, 0.5, 0.9")
    st.markdown("---")
    run_button = st.button("🚀 Run Forecast", type="primary", use_container_width=True,
                          disabled=st.session_state.is_running)

# ---------------------------------------------------------------------------
# Data preview (no model loading here)
# ---------------------------------------------------------------------------
st.subheader("📊 Data")

if data_option == "Use demo data":
    df = _build_demo_data()
    st.info("Using built-in synthetic weekly data (104 periods).")
    st.dataframe(df.head(10), use_container_width=True)
elif st.session_state.cached_df is not None:
    df = st.session_state.cached_df
    st.success(f"Loaded {len(df)} rows, {len(df.columns)} columns.")
    st.dataframe(df.head(10), use_container_width=True)
else:
    df = None
    st.info("Upload a CSV or use demo data to continue.")

# ---------------------------------------------------------------------------
# Run forecast (lazy — model not loaded until first click)
# ---------------------------------------------------------------------------
if run_button and df is not None and not st.session_state.is_running:
    st.session_state.is_running = True
    st.session_state.error_message = ""
    st.session_state.forecast_result = None

    # Parse quantiles
    try:
        q_levels = [float(q.strip()) for q in quantiles_str.split(",") if q.strip()]
        if not q_levels:
            raise ValueError("No quantile levels provided.")
        for q in q_levels:
            if q <= 0.0 or q >= 1.0:
                raise ValueError(f"Quantile must be between 0 and 1, got {q}")
    except ValueError as e:
        st.error(f"Invalid quantile levels: {e}")
        st.session_state.is_running = False
        st.stop()

    # Build task (validated at construction)
    try:
        task = ForecastTask(
            mode=ForecastMode.STANDARD_UNIVARIATE,
            historical_data=tuple(df.to_dict("records")),
            timestamp_column=ts_col,
            target_columns=(target_col,),
            prediction_length=int(horizon),
            quantile_levels=tuple(q_levels),
        )
    except ValueError as e:
        st.error(f"Configuration error: {e}")
        st.session_state.is_running = False
        st.stop()

    # Get or create the process-cached backend (model loads lazily on first forecast)
    try:
        backend = _resolve_backend()
        if not st.session_state.pipeline_was_loaded:
            # First call triggers model loading inside forecast()
            st.session_state.pipeline_was_loaded = True
        # Run forecast
        with st.spinner("Running Chronos-2 forecast (may load model on first call)..."):
            result = backend.forecast(task)
            st.session_state.forecast_result = result
            st.session_state.run_id = result.run_id
    except AdapterError as e:
        st.session_state.error_message = str(e)
        logger.warning("Forecast failed", exc_info=True)
    except Exception:
        st.session_state.error_message = "An unexpected error occurred. Please check your data and try again."
        logger.error("Unexpected forecast error", exc_info=True)

    st.session_state.is_running = False

# ---------------------------------------------------------------------------
# Results
# ---------------------------------------------------------------------------
if st.session_state.forecast_result:
    result = st.session_state.forecast_result
    meta = result.runtime_metadata
    label = "cold" if meta.model_was_loaded_this_run else "warm"

    st.subheader("✅ Forecast Complete")
    c1, c2, c3, c4 = st.columns(4)
    c1.metric("Run ID", result.run_id)
    c2.metric("Horizon", meta.prediction_length)
    c3.metric("Backend", f"{result.backend_name} ({label})")
    c4.metric("Inference", f"{meta.inference_seconds:.2f}s")

    # Show timing breakdown
    with st.expander("⏱ Timing & model details", expanded=False):
        st.write(f"- **Model load:** {meta.model_load_seconds:.3f}s")
        st.write(f"- **Inference:** {meta.inference_seconds:.3f}s")
        st.write(f"- **Result conversion:** {meta.result_conversion_seconds:.3f}s")
        st.write(f"- **Total runtime:** {meta.total_runtime_seconds:.3f}s")
        st.write(f"- **Pipeline reused:** {meta.pipeline_reused}")
        st.write(f"- **Model revision:** {result.model_revision}")
        st.write(f"- **Context rows used:** {meta.context_rows_used}")

    st.subheader("📋 Forecast Table")
    rows_df = pd.DataFrame(result.forecast_rows)
    display_cols = [c for c in rows_df.columns if c not in ("run_id", "target_name")]
    st.dataframe(rows_df[display_cols], use_container_width=True)

    csv_buffer = StringIO()
    rows_df.to_csv(csv_buffer, index=False)
    st.download_button("Download forecast CSV", data=csv_buffer.getvalue(),
                       file_name=f"forecast_{result.run_id}.csv", mime="text/csv")

elif st.session_state.error_message:
    st.error(st.session_state.error_message)
    st.info("Your configuration has been preserved. Adjust and try again.")
