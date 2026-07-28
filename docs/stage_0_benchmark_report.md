# Stage 0 Benchmark Report

**Generated:** Pending — run `scripts/run_stage0_benchmark.py` to produce results.  
**Status:** ⏳ Pending (local environment requires Chronos-2 model download)

## Environment

- Python: 3.12.x
- OS: Windows (local) / Linux (Community Cloud — pending)
- Model: `amazon/chronos-2`

## Scenarios

| # | Scenario | Status |
|---|----------|--------|
| 1 | Weekly series (260 obs, horizon 13) | ⏳ Pending |
| 2 | Small panel (5 series, benchmark-only direct API) | ⏳ Pending |
| 3 | 10 rolling forecast calls | ⏳ Pending |
| 4 | Failure + successful retry (injected failure) | ⏳ Pending |

## Local Results

*To be filled after running `scripts/run_stage0_benchmark.py` on the D: drive environment.*
*Use `.\scripts\activate_local_windows.ps1` first to set D: drive caches.*

## Community Cloud Results

*To be filled after deploying to Streamlit Community Cloud.*

## Key Measurements

| Metric | Cold | Warm |
|--------|------|------|
| Model load time | TBD | N/A |
| Inference time (13-step) | TBD | TBD |
| Result conversion time | TBD | TBD |
| Baseline RSS | TBD | TBD |
| Peak RSS (approximate) | TBD | TBD |
| Pipeline reuse | TBD | Unit-tested (real rerun pending) |
