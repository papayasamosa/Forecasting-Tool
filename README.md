# Chronos-2 Forecasting Tool

A Streamlit application for time-series forecasting using **Amazon Chronos-2**, a 120M-parameter foundation model for zero-shot forecasting.

## Status

| Component | Status |
|-----------|--------|
| Schemas and configuration | ✅ Implemented, tested |
| `ForecastBackend` protocol | ✅ Implemented |
| `Chronos2Adapter` class | ✅ Implemented, tested with fake pipeline |
| Schema invariant validation | ✅ Implemented, tested |
| Unit tests (no model download) | ✅ Passing |
| Local setup (D: drive) | ✅ Documented |
| Smoke test | ⏳ Requires model download |
| Benchmark harness | ⏳ Requires model download |
| Community Cloud deployment | ⏳ Pending |
| ADR-001 inference backend | ⏳ Pending (awaiting Cloud evidence) |
| Phase 1 features | 🔜 Planned (see below) |

## Repository Structure

```
app.py                  # Streamlit entry point
pages/
    1_Forecast.py       # Stage 0 forecast page (lazy-loaded model)
    2_Methodology.py    # Documentation and methodology
src/
    config.py           # Centralised configuration
    schemas.py          # Canonical typed schemas with invariant validation
    benchmarking.py     # Stage 0 benchmark harness
    forecasting/
        base.py         # ForecastBackend protocol
        chronos2_adapter.py  # Chronos2Adapter class
scripts/
    chronos2_smoke_test.py   # Standalone smoke test
    run_stage0_benchmark.py  # Benchmark runner
    setup_local_windows.ps1 # Windows D: drive setup
    verify_environment.py   # Environment verification
tests/
    test_schemas.py          # Schema + validation tests
    test_adapter_contract.py # Adapter tests with fake pipeline
    test_benchmarking.py     # Benchmark harness tests
    fixtures/                # Synthetic data fixtures
docs/
    stage_0_benchmark_report.md        # ⏳ Pending
    adr_001_inference_backend.md       # ⏳ Pending
    community_cloud_test_checklist.md  # Checklist for Cloud testing
.github/workflows/
    ci.yml                 # CI (unit tests, lint, coverage)
```

## Local Setup (Windows, D: drive)

### Prerequisites

- **Python 3.12** — [Download from python.org](https://www.python.org/downloads/)
- **D: drive** with sufficient free space

### Installation (automated)

```powershell
# Run the setup script (creates everything on D: drive)
.\scripts\setup_local_windows.ps1
```

This script will:
1. Verify Python 3.12 is available
2. Create `D:\Forecasting-Tool-Local\` with venv, caches, temp, and benchmarks
3. Set all cache environment variables to D: drive
4. Install PyTorch (CPU), runtime deps, and dev deps
5. Run `scripts/verify_environment.py`

### Manual installation

```powershell
# Set environment variables
$env:PIP_CACHE_DIR = "D:\Forecasting-Tool-Local\cache\pip"
$env:HF_HOME = "D:\Forecasting-Tool-Local\cache\huggingface"
$env:HUGGINGFACE_HUB_CACHE = "D:\Forecasting-Tool-Local\cache\huggingface"
$env:TRANSFORMERS_CACHE = "D:\Forecasting-Tool-Local\cache\transformers"
$env:TORCH_HOME = "D:\Forecasting-Tool-Local\cache\torch"
$env:TMP = "D:\Forecasting-Tool-Local\temp"
$env:TEMP = "D:\Forecasting-Tool-Local\temp"

# Create directories
New-Item -ItemType Directory -Force -Path D:\Forecasting-Tool-Local\venv, D:\Forecasting-Tool-Local\cache\pip, D:\Forecasting-Tool-Local\temp | Out-Null

# Create virtual environment
& "C:\Users\moham\AppData\Local\Programs\Python\Python312\python.exe" -m venv D:\Forecasting-Tool-Local\venv

# Install PyTorch (CPU-only)
D:\Forecasting-Tool-Local\venv\Scripts\python.exe -m pip install torch --index-url https://download.pytorch.org/whl/cpu

# Install dependencies
D:\Forecasting-Tool-Local\venv\Scripts\python.exe -m pip install -r requirements.txt
D:\Forecasting-Tool-Local\venv\Scripts\python.exe -m pip install -r requirements-dev.txt
```

### Commands

```powershell
# Run unit tests (no model download)
D:\Forecasting-Tool-Local\venv\Scripts\python.exe -m pytest tests -v

# Run smoke test (first run downloads Chronos-2 ~500MB)
D:\Forecasting-Tool-Local\venv\Scripts\python.exe scripts/chronos2_smoke_test.py

# Run benchmarks
D:\Forecasting-Tool-Local\venv\Scripts\python.exe scripts/run_stage0_benchmark.py

# Launch Streamlit
D:\Forecasting-Tool-Local\venv\Scripts\python.exe -m streamlit run app.py
```

## Chronos-2 Adapter

The `Chronos2Adapter` class in `src/forecasting/chronos2_adapter.py` implements the
`ForecastBackend` protocol and wraps `Chronos2Pipeline` from `chronos-forecasting`.

Key features:
- Dependency injection (accepts pre-built pipeline or callable provider)
- Lazy model loading (pipeline created on first `forecast()` call)
- Streaming forecast output conversion to canonical `ForecastResult`
- Runtime metadata capture (model ID, revision, package versions, timings)
- Safe error types (`ConfigurationError`, `ModelLoadError`, `InferenceError`, `ResultSchemaError`)

## License

Apache-2.0 — see [LICENSE](LICENSE) and [NOTICE](NOTICE).