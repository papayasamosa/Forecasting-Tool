# Chronos-2 Forecasting Tool

A Streamlit application for time-series forecasting using **Amazon Chronos-2**, a 120M-parameter foundation model for zero-shot forecasting.

## Current Status: Stage 0 — Technical Feasibility Spike

This project is in the early feasibility stage. The goal is to prove that Chronos-2 can run within hosting constraints before building the full application.

## Repository Structure

```
app.py                  # Streamlit entry point
pages/
    1_Forecast.py       # Minimal forecast page (Stage 0)
    2_Methodology.py    # Documentation and methodology
src/
    config.py           # Centralised configuration
    schemas.py          # Canonical typed schemas
    forecasting/
        base.py         # ForecastBackend protocol
        chronos2_adapter.py  # Chronos-2 adapter
scripts/
    chronos2_smoke_test.py   # Standalone smoke test
tests/
    test_schemas.py          # Schema tests (no model needed)
    test_adapter_contract.py # Adapter protocol tests
    fixtures/                # Synthetic data fixtures
```

## Local Setup

### Prerequisites

- Python 3.11+ (3.14 recommended)
- pip

### Installation

```bash
# 1. Clone or navigate to the project directory
cd Forecasting-Tool

# 2. (Recommended) Create a virtual environment
python -m venv .venv
.venv\Scripts\activate   # Windows
source .venv/bin/activate  # macOS/Linux

# 3. Install PyTorch (CPU-only)
pip install torch --index-url https://download.pytorch.org/whl/cpu

# 4. Install dependencies
pip install -r requirements.txt

# 5. Run the smoke test (loads Chronos-2, runs forecast)
python scripts/chronos2_smoke_test.py

# 6. Run unit tests (no model download needed)
pytest tests/ -v

# 7. Launch the Streamlit app
streamlit run app.py
```

### Important Notes

- **First run**: The smoke test will download the Chronos-2 model (~500 MB) from Hugging Face. This happens once; subsequent runs use cached weights.
- **CPU inference**: Chronos-2 runs on CPU. A GPU is not required but would significantly speed up inference.
- **Memory**: The 120M-parameter model requires approximately 1-2 GB RAM.
- **No data persistence**: Uploaded data exists only for the duration of your session.

## Chronos-2 API Reference

The adapter in `src/forecasting/chronos2_adapter.py` wraps the `Chronos2Pipeline` class from the `chronos-forecasting` package.

### Key methods used

| Method | Purpose |
|--------|---------|
| `Chronos2Pipeline.from_pretrained("amazon/chronos-2", device_map="cpu")` | Load the model |
| `pipeline.predict_df(df, prediction_length=N, quantile_levels=[...])` | Run inference via pandas API |

## Smoke Test

Run the standalone smoke test to verify the full inference pipeline:

```bash
python scripts/chronos2_smoke_test.py
```

Expected output:
- Python and package versions
- Model loading time
- Inference time
- Forecast output shape (13 rows)
- Quantile columns (0.1, 0.5, 0.9)
- Warm forecast timing (should be faster than cold)

## Deployment

### Streamlit Community Cloud

1. Push this repository to GitHub.
2. Connect your repository at [share.streamlit.io](https://share.streamlit.io).
3. Set the main file to `app.py`.
4. (Optional) Add a Hugging Face token in Streamlit secrets as `HF_TOKEN`.
5. Deploy.

The application is designed for CPU environments. Chronos-2 loading may take 1-2 minutes on cold start.

## License

Apache-2.0 — see [LICENSE](LICENSE) and [NOTICE](NOTICE).