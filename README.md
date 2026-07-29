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
| Pull-request CI | ✅ Green (120 tests, 90.19% coverage as of PR #10) |
| `main` branch CI (post-merge) | ⏳ Verified for PR-head only; push-to-main run pending confirmation |
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
| Model file checksum scope recorded | ✅ SHA-256 recorded (must verify file name, size, shard count on current head) |
| Community Cloud deployment | ⏳ Pending (not yet Cloud-proven) |
| ADR-001 inference backend | ⏳ Pending (requires Cloud deployment first, then evidence, then decision) |
| Current-head local evidence rerun | ⏳ Pending (Gate B2 — requires clean current-head commit first) |
| Phase 1 features | 🔜 Planned (after all Stage 0 gates pass) |
| MCP developer tooling scaffold | ✅ Optional, documentation-only, not functionally verified |
| Evidence and MCP-security review closure | ✅ Merged (PR #10) |
| Cache state labelling (smoke + benchmark) | ✅ Implemented |
| Git traceability (trustworthy repo-root detection) | ✅ Implemented |
| Blank/missing timestamp rejection | ✅ Implemented |
| MCP fine-grained PAT detection | ✅ Implemented |
| MCP static CI verification | ✅ Implemented |
| Self-contained CPU Torch dependency declaration | ✅ Implemented (repository-contained) |
| Windows machine CPU model detection | ✅ Implemented (platform-aware) |

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

# Install dependencies (requirements.txt includes --extra-index-url for CPU-only PyTorch)
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
# Use --initial-cache-state download_cold for first-ever run on a machine
# Use --initial-cache-state process_cold_cached_weights when weights are cached
python scripts/chronos2_smoke_test.py --initial-cache-state process_cold_cached_weights

# Run benchmarks
python scripts/run_stage0_benchmark.py --initial-cache-state process_cold_cached_weights

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

The intended `main` branch protection policy requires:

- Pull request reviews before merging
- CI status checks to pass
- Resolved review threads
- Up-to-date branch

PR CI must be green before merging. Note that PR #8 and PR #9 were merged
while review threads remained unresolved — either the repository settings
do not enforce the documented policy or the threads were created after
merge. The documentation here describes the required policy, which should
be independently verified against the GitHub repository settings.

Push-to-main CI is configured but no post-merge commit has yet been
verified on `main` — this will be confirmed after the next merge.

Real-model evidence (Gates B2–D) has not yet been collected on the current head.

## Remaining Stage 0 gates

| Gate | Requirement | Status | Sequence |
|------|-------------|--------|----------|
| A8 | Evidence and MCP-security closure | ✅ Merged (PR #10) | 1 |
| A9 | Evidence publication hardening | ✅ Merged (this PR) | 2 |
| B2 | Current-head local evidence rerun | ⏳ Pending | 3 — after A9 merges |
| C | Community Cloud technical spike | ⏳ Pending | 4 — collect evidence on Cloud |
| D | ADR-001 decision | ⏳ Pending | 5 — after Cloud evidence collected |
| E | Phase 1 start | 🔜 After all gates pass | 6 |

> **Sequence:** deploy technical spike → collect evidence → decide ADR.
> The benchmark report and checklist previously suggested Cloud deployment is pending
> ADR, which is circular. Correct order: 1) deploy technical spike, 2) collect evidence,
> 3) decide ADR.

## Current status after PR #11 (Evidence publication hardening)

This PR hardens evidence publication before the real-model rerun:

- **Evidence schema v2** — typed dataclasses for smoke, benchmark suite, model artifact,
  local bundle, and Cloud evidence with per-type validation methods
- **Benchmark suite envelope** — benchmark JSON is now a validated object with
  `suite_passed`, `code_commit`, `initial_cache_state`, and `scenarios` list
- **Strict publication validation** — publisher rejects failed evidence, wrong token
  state, revision mismatches, missing scenarios, missing cache states, unclean
  worktree, and bare lists (old format)
- **Local bundle builder** — `scripts/build_local_stage0_bundle.py` validates and
  combines all component evidence into a single bundle
- **Cache-state verification** — `inspect_hf_cache()` checks Hugging Face cache
  before runs (snapshot present/absent, file count, bytes)
- **Smoke failure traceability** — warm failures record `cache_state=same_process_warm`;
  top-level failures preserve parsed `initial_cache_state`
- **Recursive sanitisation** — all string values in lists, nested lists, and tuples
  are sanitised for personal paths
- **Model-artifact schema** — records snapshot commit, shard count, per-file SHA-256,
  and manifest hash
- **CI dependency assertions** — verifies no NVIDIA/CUDA packages installed
- **28 evidence tests** — validate schemas, publisher rules, sanitisation, bundles

> **Evidence manifest is empty** until the current-head local evidence rerun (Gate B2).
> Direct dependency pins are not a complete lock — capture a lock file after
> Cloud success. Direct pins plus the extra-index directive do not by themselves
> guarantee transitive reproducibility.
> Community Cloud may process `requirements.txt` with `uv` before falling back to
> `pip`. The `--extra-index-url` directive in `requirements.txt` has been verified
> with pip on CI but still needs an actual Cloud build to confirm the platform's
> resolver selects the CPU wheel.

## Developer MCP integrations (optional)

This repository includes optional configuration for **Model Context
Protocol (MCP)** servers — developer tooling that gives a coding assistant
(e.g. Claude Code) read access to repository/CI state, current library
documentation, a disposable browser for inspecting the running Streamlit
app, and Hugging Face Hub metadata while you work.

MCP is **not required to run the forecasting application** and is not a
Python or Streamlit dependency. See
[`docs/development/mcp_setup.md`](docs/development/mcp_setup.md) for setup
and [`docs/development/mcp_usage_policy.md`](docs/development/mcp_usage_policy.md)
for the read-only-by-default usage policy. Unauthenticated templates live
in [`tools/mcp/`](tools/mcp/).

## License

Apache-2.0 — see [LICENSE](LICENSE) and [NOTICE](NOTICE).