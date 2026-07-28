"""Streamlit page: Forecast — Stage 0 (not yet Phase 1).

The Chronos-2 model is loaded only when the user clicks "Run Forecast".
"""
from __future__ import annotations

import logging
import os
import sys
from io import StringIO

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
# Session state
# ---------------------------------------------------------------------------
_DEFAULT_STATE = {
    "run_id": "",
    "forecast_result": None,
    "error_message": "",
    "is_running": False,
    "backend": None,
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

    if data_option == "Upload CSV":
        uploaded_file = st.file_uploader("Choose a CSV file", type=["csv"])
        if uploaded_file is not None:
            uploaded_file.seek(0, os.SEEK_END)
            size = uploaded_file.tell()
            uploaded_file.seek(0)
            if size > MAX_UPLOAD_BYTES:
                st.error(f"File exceeds the 50 MB limit ({size / 1024 / 1024:.1f} MB).")
                uploaded_file = None
            else:
                try:
                    raw_df = pd.read_csv(uploaded_file)
                    cols = raw_df.columns.tolist()
                    ts_col = st.selectbox("Timestamp column", cols, index=0)
                    target_col = st.selectbox("Target column", cols, index=min(1, len(cols) - 1))
                except Exception:
                    st.error("Could not parse CSV. Please check the file format.")
                    uploaded_file = None

    st.markdown("---")
    horizon = st.number_input("Forecast horizon (periods)", min_value=1, max_value=1024, value=13, step=1)
    quantiles_str = st.text_input("Quantile levels (comma-separated)", value="0.1, 0.5, 0.9")
    st.markdown("---")
    run_button = st.button("🚀 Run Forecast", type="primary", use_container_width=True,
                          disabled=st.session_state.is_running)

# ---------------------------------------------------------------------------
# Data preview
# ---------------------------------------------------------------------------
st.subheader("📊 Data")

if data_option == "Use demo data":
    df = _build_demo_data()
    st.info("Using built-in synthetic weekly data (104 periods).")
    st.dataframe(df.head(10), use_container_width=True)
elif uploaded_file is not None:
    try:
        df = pd.read_csv(uploaded_file)
        st.success(f"Loaded {len(df)} rows, {len(df.columns)} columns.")
        st.dataframe(df.head(10), use_container_width=True)
    except Exception:
        st.error("Could not read CSV.")
        df = None
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

    # Create or reuse cached backend
    if st.session_state.backend is None:
        with st.spinner("Loading Chronos-2 model (cold start)..."):
            try:
                st.session_state.backend = Chronos2Adapter()
            except AdapterError:
                st.error("Model loading failed. Please try again later.")
                logger.error("Model load failed", exc_info=True)
                st.session_state.is_running = False
                st.stop()
    else:
        st.info("Using previously loaded model (warm reuse).")

    # Run forecast
    with st.spinner("Running Chronos-2 forecast..."):
        try:
            result = st.session_state.backend.forecast(task)
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
    call_count = getattr(st.session_state.backend, "pipeline_call_count", 0)
    label = "cold" if call_count <= 1 else "warm"

    st.subheader("✅ Forecast Complete")
    c1, c2, c3, c4 = st.columns(4)
    c1.metric("Run ID", result.run_id)
    c2.metric("Horizon", result.runtime_metadata.prediction_length)
    c3.metric("Backend", f"{result.backend_name} ({label})")
    c4.metric("Inference", f"{result.runtime_metadata.runtime_seconds:.2f}s")

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


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------
def _build_demo_data() -> pd.DataFrame:
    import numpy as np
    rng = np.random.default_rng(seed=42)
    t = np.arange(104)
    values = 100 + 0.05 * t + 5 * np.sin(2 * np.pi * t / 52) + rng.normal(0, 2, size=104)
    dates = pd.date_range("2022-01-03", periods=104, freq="W")
    return pd.DataFrame({"timestamp": dates, "target": values})
