# Chronos-2 Forecasting Tool

A Streamlit application for time-series forecasting using **Amazon Chronos-2**, a 120M-parameter foundation model for zero-shot forecasting.

## Status

| Component | Status |
|-----------|--------|
| Schemas and configuration | ✅ Implemented, tested |
| `ForecastBackend` protocol | ✅ Implemented |
| `Chronos2Adapter` class | ✅ Implemented, tested with fake pipeline |
| Schema invariant validation | ✅ Implemented, tested |
| Unit tests (no model download) | ✅ Implemented |
| Local setup (D: drive) | ✅ Documented |
| CI (GitHub Actions) | ✅ Implemented |
| `st.cache_resource` process-level caching | ✅ Implemented |
| Pipeline reuse (unit-tested with fake pipeline) | ✅ Implemented |
| Pipeline reuse (real Chronos-2 model) | ✅ Verified (prior code — must rerun on current head) |
| Pull-request CI | ✅ Green (102 tests, 90.54% coverage as of PR #7) |
| `main` branch CI (post-merge) | ⏳ Verified only for PR-head; push-to-main run pending confirmation |
| Context capping before record materialisation | ✅ Implemented |
| Truncation warnings displayed in UI | ✅ Implemented |
| Warm reuse enforced in benchmark gate | ✅ Implemented |
| Explicit `cross_learning=False` in standard calls | ✅ Implemented |
| Failure telemetry recorded | ✅ Implemented |
| Summary calculations exclude aggregate | ✅ Implemented |
| Smoke evidence written on all failure paths | ✅ Implemented |
| Reusable telemetry module (`src/telemetry.py`) | ✅ Implemented |
| Real Chronos-2 model smoke test | ⏳ Prior evidence exists (cold ~23.5s, warm ~0.27s); must rerun on current head |
| Local benchmark suite | ⏳ Prior evidence exists (4/4 scenarios pass); must rerun on current head |
| Immutable model revision pinned | ✅ `29ec3766d36d6f73f0696f85560a422f50e8498c` |
| Model file checksum | ✅ `ddcda3c7508bf2528087723e98a20707cc04b7f370ae275a9fd88078ddba4f42` |
| Community Cloud deployment | ⏳ Pending (not yet Cloud-proven) |
| ADR-001 inference backend | ⏳ Pending (requires Cloud deployment first, then evidence, then decision) |
| Current-head local evidence rerun | ⏳ Pending (Gate B2) |
| Phase 1 features | 🔜 Planned (after all Stage 0 gates pass) |

## Repository Structure

```
app.py                  # Streamlit entry point
pages/
    1_Forecast.py       # Stage 0 forecast page (lazy-loaded model)
    2_Methodology.py    # Documentation and methodology
src/
    config.py           # Centralised configuration
    schemas.py          # Canonical typed schemas with invariant validation
    telemetry.py        # Reusable telemetry helpers (memory, package versions, evidence)
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
    evidence/stage0/                   # Sanitised evidence artefacts (WP9)
    stage_0_benchmark_report.md        # Report (prior evidence — needs current-head rerun)
    adr_001_inference_backend.md       # Pending — requires Cloud evidence first
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
# Set environment variables (all D: drive, including Hub and Xet caches)
$env:PIP_CACHE_DIR = "D:\Forecasting-Tool-Local\cache\pip"
$env:HF_HOME = "D:\Forecasting-Tool-Local\cache\huggingface"
$env:HUGGINGFACE_HUB_CACHE = "D:\Forecasting-Tool-Local\cache\huggingface"
$env:HF_HUB_CACHE = "D:\Forecasting-Tool-Local\cache\huggingface\hub"
$env:HF_XET_CACHE = "D:\Forecasting-Tool-Local\cache\huggingface\xet"
$env:TRANSFORMERS_CACHE = "D:\Forecasting-Tool-Local\cache\transformers"
$env:TORCH_HOME = "D:\Forecasting-Tool-Local\cache\torch"
$env:TMP = "D:\Forecasting-Tool-Local\temp"
$env:TEMP = "D:\Forecasting-Tool-Local\temp"

# Create directories
New-Item -ItemType Directory -Force -Path D:\Forecasting-Tool-Local\venv, D:\Forecasting-Tool-Local\cache\pip, D:\Forecasting-Tool-Local\temp | Out-Null

# Create virtual environment (adjust Python path if needed)
py -3.12 -m venv D:\Forecasting-Tool-Local\venv

# Install PyTorch (CPU-only, exact pin)
D:\Forecasting-Tool-Local\venv\Scripts\python.exe -m pip install torch==2.13.0 --index-url https://download.pytorch.org/whl/cpu

# Install dependencies
D:\Forecasting-Tool-Local\venv\Scripts\python.exe -m pip install -r requirements.txt
D:\Forecasting-Tool-Local\venv\Scripts\python.exe -m pip install -r requirements-dev.txt
```

### Commands

```powershell
# Activate the D: drive environment (sets caches + activates venv)
.\scripts\activate_local_windows.ps1

# Run unit tests (no model download)
python -m pytest tests -v

# Run smoke test (first run downloads Chronos-2 ~500MB)
python scripts/chronos2_smoke_test.py

# Run benchmarks
python scripts/run_stage0_benchmark.py

# Launch Streamlit
python -m streamlit run app.py
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

## Branch protection

The `main` branch is protected in the GitHub repository settings:

- Requires pull request reviews before merging
- Requires CI status checks to pass
- Requires resolved review threads
- Requires up-to-date branch

PR CI must be green before merging. Push-to-main CI should confirm the merge is
clean, but as of this PR the first post-merge commit has not yet been verified on
main — this will be confirmed after merge.

Real-model evidence (Gates B2–D) has not yet been collected on the current head.

## Remaining Stage 0 gates

| Gate | Requirement | Status | Sequence |
|------|-------------|--------|----------|
| A7 | Post-evidence repair (this PR) | 🔜 In progress | 1 |
| B2 | Current-head local evidence rerun | ⏳ Pending | 2 — after A7 merges |
| C | Community Cloud technical spike | ⏳ Pending | 3 — collect evidence on Cloud |
| D | ADR-001 decision | ⏳ Pending | 4 — after Cloud evidence collected |
| E | Phase 1 start | 🔜 After all gates pass | 5 |

> **Sequence:** Community Cloud deployment first → evidence collection → ADR decision.
> The benchmark report and checklist previously suggested Cloud deployment is pending
> ADR, which is circular. Correct order: 1) deploy technical spike, 2) collect evidence,
> 3) decide ADR.

## License

Apache-2.0 — see [LICENSE](LICENSE) and [NOTICE](NOTICE).