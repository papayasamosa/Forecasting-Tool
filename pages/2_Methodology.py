# pragma: no cover
"""Streamlit page: Methodology — Documentation and references.
"""
import os
import sys

import streamlit as st

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from src.telemetry import (  # noqa: E402
    deployed_commit,
    machine_summary,
    package_versions_metadata,
)

st.set_page_config(
    page_title="Methodology — Chronos-2",
    page_icon="📘",
    layout="wide",
)

st.title("📘 Methodology")

st.markdown("""
## Overview

This tool uses **Amazon Chronos-2**, a 120M-parameter encoder-only time series
foundation model for zero-shot forecasting.

- **Paper**: [Chronos-2: From Univariate to Universal Forecasting](https://arxiv.org/abs/2510.15821)
- **Model**: [amazon/chronos-2](https://huggingface.co/amazon/chronos-2)
- **Repository**: [amazon-science/chronos-forecasting](https://github.com/amazon-science/chronos-forecasting)

## Important Disclaimers

| Notice | Description |
|--------|-------------|
| **Zero-shot forecasting** | Chronos-2 makes predictions without fine-tuning on your data. Accuracy depends on how similar your series are to the model's training data. |
| **Uncertainty** | Forecast intervals reflect model uncertainty, not confidence bounds. They are not guarantees of future outcomes. |
| **No causal interpretation** | Forecast outputs are statistical predictions only. Do not interpret them as causal, optimised, MMM, or scenario-planning results. |
| **Session-based data** | Uploaded data is kept only for the duration of your browser session. It is not stored or logged. |
| **Community Cloud** | Deployed on Streamlit Community Cloud with limited CPU resources. Large models may load slowly. |
| **Anonymous data** | For this public prototype, only anonymised or aggregated data should be used — do not upload confidential business data. |

## Current Phase: Univariate MVP

This application is in **Phase 1 (Univariate MVP)**. The following features
are available:

- ✅ CSV ingestion with column mapping
- ✅ Chronos-2 zero-shot forecasting
- ✅ Customisable horizon and quantiles
- ✅ Forecast download (CSV)
- ✅ Model pipeline caching (second forecast reuses loaded model)

Features planned for later phases:

- ⏳ Rolling-origin backtesting
- ⏳ Naive baselines (last-value, seasonal naive)
- ⏳ Forecast metrics (MAE, RMSE, WAPE, sMAPE, MASE, pinball loss)
- ⏳ Residual diagnostics (ACF, Ljung-Box, Durbin-Watson)
- ⏳ Combined history + forecast exports
- ⏳ Cross-learning and covariate-aware forecasting

## Architecture

```
User Upload / Demo Data
        │
        ▼
    Data Ingestion  ──►  Validation  ──►  Fingerprinting
        │
        ▼
    ForecastTask (canonical schema)
        │
        ▼
    ForecastBackend (Protocol)
        │
        ├── Chronos2Adapter (Phase 1)
        │
        └── Naive Baselines (Phase 2)
        │
        ▼
    ForecastResult (canonical schema)
        │
        ▼
    Visualisation / Export
```

## Package Versions

The following packages are used by this application:

| Package | Version (pinned) |
|---------|-----------------|
| `chronos-forecasting` | See `requirements.txt` |
| `torch` | See `requirements.txt` |
| `streamlit` | See `requirements.txt` |
| `pandas` | See `requirements.txt` |
| `numpy` | See `requirements.txt` |
""")

st.markdown("""## Deployment

Best-effort identity of the currently running deployment (resolved from the
app's git checkout at runtime, no admin access needed):
""")
st.markdown(f"- **Deployed commit:** `{deployed_commit() or 'not available'}`")

st.markdown("""## Runtime Environment

Versions and machine summary of the process serving this app (read at
runtime, no admin access needed):
""")
_env_versions = package_versions_metadata()
_env_machine = machine_summary()
st.markdown(
    "| Attribute | Value |\n"
    "|---|---|\n"
    f"| Python | `{_env_versions.get('python', 'unknown')}` |\n"
    f"| chronos-forecasting | `{_env_versions.get('chronos-forecasting', 'unknown')}` |\n"
    f"| torch | `{_env_versions.get('torch', 'unknown')}` |\n"
    f"| streamlit | `{_env_versions.get('streamlit', 'unknown')}` |\n"
    f"| pandas | `{_env_versions.get('pandas', 'unknown')}` |\n"
    f"| numpy | `{_env_versions.get('numpy', 'unknown')}` |\n"
    f"| OS | `{_env_machine.get('os_name', 'unknown')}` |\n"
    f"| CPU model | `{_env_machine.get('cpu_model', 'unknown') or 'unknown'}` |\n"
    f"| CPU logical cores | `{_env_machine.get('cpu_logical_cores', 0)}` |\n"
    f"| RAM total (GB) | `{_env_machine.get('ram_total_gb', 0.0)}` |\n"
)
