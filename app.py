"""Chronos-2 Forecasting Tool — Streamlit entry point.

Stage 0: Technical feasibility spike.
"""
from __future__ import annotations

import streamlit as st

st.set_page_config(
    page_title="Chronos-2 Forecasting Tool",
    page_icon="📈",
    layout="wide",
    initial_sidebar_state="expanded",
)

st.title("🚀 Chronos-2 Forecasting Tool")
st.markdown(
    "_Zero-shot time-series forecasting with Amazon Chronos-2_"
)

st.markdown("""
## Welcome

This application demonstrates **zero-shot forecasting** using Amazon's Chronos-2
foundation model.  Upload a time-series CSV or use the built-in demo data to
generate probabilistic forecasts with quantile predictions.

### Quick Start

1. Navigate to the **Forecast** page using the sidebar.
2. Choose **"Use demo data"** or upload your own CSV.
3. Configure the forecast horizon and quantile levels.
4. Click **"Run Forecast"**.
5. View and download the results.

### Status

| Component | Status |
|-----------|--------|
| `Chronos2Adapter` class | ✅ Implemented, tested with fake pipeline |
| Adapter unit tests | ✅ Implemented (no model download) |
| Schema invariant validation | ✅ Implemented, tested |
| Real Chronos-2 model smoke test | ⏳ Requires model download |
| Local benchmark suite | ⏳ Requires model download |
| Community Cloud deployment | ⏳ Pending |
| Inference backend decision (ADR-001) | ⏳ Pending (awaiting Cloud evidence) |
| Rolling Backtest | 🔜 Phase 1 |
| Naive Baselines | 🔜 Phase 1 |

### Important Notices

- This tool uses **zero-shot forecasting** — the model has not been fine-tuned
  on your specific data.
- Forecast intervals reflect model uncertainty, not guarantees.
- Uploaded data is session-only and not persisted.
- Do not upload confidential business data to this prototype.
""")

# Sidebar extras
with st.sidebar:
    st.markdown("### About")
    st.markdown(
        "**Chronos-2** is a 120M-parameter encoder-only time series foundation "
        "model for zero-shot forecasting. "
        "[Learn more](https://huggingface.co/amazon/chronos-2)"
    )
    st.markdown("---")
    st.caption("v0.1.0 — Stage 0 Feasibility Spike")