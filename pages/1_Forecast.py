"""Streamlit page: Forecast — Step-by-step workflow.

Stage 0 minimal proof: loads Chronos-2 pipeline, accepts CSV upload or demo
data, runs a forecast, and shows results.
"""
from __future__ import annotations

import os
import sys
from io import StringIO

import streamlit as st
import pandas as pd

# Ensure project root is on sys.path
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from src.config import MODEL_ID, DEFAULT_QUANTILES
from src.schemas import ForecastMode, ForecastTask, new_run_id
from src.forecasting.chronos2_adapter import (
    create_forecast,
    get_pipeline_info,
    ModelLoadError,
    ForecastError,
)


# ---------------------------------------------------------------------------
# Page config
# ---------------------------------------------------------------------------
st.set_page_config(
    page_title="Forecast — Chronos-2",
    page_icon="📈",
    layout="wide",
)


# ---------------------------------------------------------------------------
# Cached model loader
# ---------------------------------------------------------------------------
@st.cache_resource(show_spinner="Loading Chronos-2 model (cold start)...")
def _cached_load_pipeline():
    """Load the Chronos-2 pipeline.  Streamlit caches this across runs."""
    from src.forecasting.chronos2_adapter import load_pipeline as _load
    return _load(device_map="cpu")


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def build_demo_data() -> pd.DataFrame:
    """Return a small synthetic weekly series."""
    import numpy as np
    rng = np.random.default_rng(seed=42)
    t = np.arange(104)
    values = 100 + 0.05 * t + 5 * np.sin(2 * np.pi * t / 52) + rng.normal(0, 2, size=104)
    dates = pd.date_range("2022-01-03", periods=104, freq="W")
    return pd.DataFrame({"timestamp": dates, "target": values})


# ---------------------------------------------------------------------------
# UI State
# ---------------------------------------------------------------------------
if "run_id" not in st.session_state:
    st.session_state.run_id = ""
if "forecast_result" not in st.session_state:
    st.session_state.forecast_result = None
if "error_message" not in st.session_state:
    st.session_state.error_message = ""
if "pipeline_loaded" not in st.session_state:
    st.session_state.pipeline_loaded = False


# ---------------------------------------------------------------------------
# Page layout
# ---------------------------------------------------------------------------

st.title("🔮 Chronos-2 Forecast")
st.markdown(
    "_Zero-shot forecasting with Amazon Chronos-2 | Phase 1 — Univariate MVP_"
)

# --- Sidebar config -------------------------------------------------------
with st.sidebar:
    st.header("Configuration")

    # Data source
    data_option = st.radio(
        "Data source",
        ["Use demo data", "Upload CSV"],
        index=0,
        help="Choose built-in demo data or upload your own CSV.",
    )

    uploaded_file = None
    if data_option == "Upload CSV":
        uploaded_file = st.file_uploader(
            "Choose a CSV file",
            type=["csv"],
            help="CSV must have at least two columns: timestamp and target value.",
        )

    # Column mapping (shown when CSV uploaded)
    ts_col = "timestamp"
    target_col = "target"

    if uploaded_file is not None:
        try:
            raw_df = pd.read_csv(uploaded_file)
            cols = raw_df.columns.tolist()
            ts_col = st.selectbox("Timestamp column", cols, index=0)
            target_col = st.selectbox("Target column", cols, index=min(1, len(cols) - 1))
        except Exception:
            st.error("Could not parse CSV. Please check the file format.")
            uploaded_file = None

    st.markdown("---")
    horizon = st.number_input(
        "Forecast horizon (periods)",
        min_value=1,
        max_value=1024,
        value=13,
        step=1,
    )
    quantiles_str = st.text_input(
        "Quantile levels (comma-separated)",
        value="0.1, 0.5, 0.9",
    )
    st.markdown("---")
    run_button = st.button("🚀 Run Forecast", type="primary", use_container_width=True)


# --- Main panel -----------------------------------------------------------

# Load pipeline in background (cached)
try:
    pipeline = _cached_load_pipeline()
    st.session_state.pipeline_loaded = True
    info = get_pipeline_info()
except ModelLoadError as e:
    st.error(f"Model loading failed: {e}")
    st.session_state.pipeline_loaded = False
    pipeline = None
    info = {}

# Show model info
if info:
    col1, col2, col3 = st.columns(3)
    col1.metric("Model", info.get("model_id", MODEL_ID))
    col2.metric("Pipeline", "Cached" if st.session_state.pipeline_loaded else "Not loaded")
    col3.metric("Revision", info.get("model_revision", "N/A") or "N/A")

# --- Data preview ---------------------------------------------------------
st.subheader("📊 Data")

if data_option == "Use demo data":
    df = build_demo_data()
    st.info("Using built-in synthetic weekly data (104 periods).")
    st.dataframe(df.head(10), use_container_width=True)
elif uploaded_file is not None:
    df = pd.read_csv(uploaded_file)
    st.success(f"Loaded {len(df)} rows, {len(df.columns)} columns.")
    st.dataframe(df.head(10), use_container_width=True)
else:
    df = None
    st.info("Upload a CSV or use demo data to continue.")

# --- Run forecast ---------------------------------------------------------
if run_button and df is not None and st.session_state.pipeline_loaded:
    st.session_state.error_message = ""
    st.session_state.forecast_result = None

    # Parse quantiles
    try:
        q_levels = [float(q.strip()) for q in quantiles_str.split(",") if q.strip()]
    except ValueError:
        st.error("Invalid quantile levels. Use comma-separated numbers (e.g. 0.1, 0.5, 0.9).")
        st.stop()

    # Build task
    task = ForecastTask(
        mode=ForecastMode.STANDARD_UNIVARIATE,
        historical_data=tuple(df.to_dict("records")),
        timestamp_column=ts_col,
        target_columns=(target_col,),
        prediction_length=int(horizon),
        quantile_levels=tuple(q_levels),
    )

    with st.spinner("Running Chronos-2 forecast..."):
        try:
            result = create_forecast(task)
            st.session_state.forecast_result = result
            st.session_state.run_id = result.run_id
        except ForecastError as e:
            st.session_state.error_message = str(e)
        except Exception as e:
            st.session_state.error_message = f"Unexpected error: {e}"

# --- Show results ---------------------------------------------------------
if st.session_state.forecast_result:
    result = st.session_state.forecast_result

    st.subheader("✅ Forecast Complete")
    col1, col2, col3, col4 = st.columns(4)
    col1.metric("Run ID", result.run_id)
    col2.metric("Horizon", result.runtime_metadata.prediction_length)
    col3.metric("Backend", result.backend_name)
    col4.metric("Inference", f"{result.runtime_metadata.runtime_seconds:.2f}s")

    # Table
    st.subheader("📋 Forecast Table")
    rows_df = pd.DataFrame(result.forecast_rows)
    display_cols = [c for c in rows_df.columns if c not in ("run_id", "target_name")]
    st.dataframe(rows_df[display_cols], use_container_width=True)

    # Download
    csv_buffer = StringIO()
    rows_df.to_csv(csv_buffer, index=False)
    st.download_button(
        "Download forecast CSV",
        data=csv_buffer.getvalue(),
        file_name=f"forecast_{result.run_id}.csv",
        mime="text/csv",
    )

elif st.session_state.error_message:
    st.error(f"Forecast failed: {st.session_state.error_message}")
    st.info("Please adjust your configuration and try again. Your settings have been preserved.")
