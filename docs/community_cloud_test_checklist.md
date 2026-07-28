# Community Cloud Deployment Test Checklist

Use this checklist when deploying to Streamlit Community Cloud.

## Pre-deployment

- [ ] Branch: `main`
- [ ] Entrypoint: `app.py`
- [ ] Python version: 3.12 (select in Cloud advanced settings)
- [ ] `requirements.txt` pinned exactly
- [ ] `requirements-dev.txt` NOT included (dev deps excluded from production)
- [ ] CPU-only Torch: set `PIP_EXTRA_INDEX_URL=https://download.pytorch.org/whl/cpu` in Streamlit secrets
- [ ] Verify `torch.version.cuda is None` after build
- [ ] Branch protection requires green CI and resolved review threads

## Dependency-install parity check

- [ ] Cloud `pip install -r requirements.txt` must match CI install path
- [ ] Both use `PIP_EXTRA_INDEX_URL` for CPU Torch (not a manual pre-install step)
- [ ] No CUDA packages installed
- [ ] `pip check` passes

## Secrets

- [ ] Optional: Add `HF_TOKEN` in Streamlit secrets if downloading gated models
- [ ] Without token: test that `amazon/chronos-2` (open model) downloads correctly
- [ ] Token never printed or persisted

## Test scenarios

| # | Test | Expected | Actual |
|---|------|----------|--------|
| 1 | Clean dependency installation | `pip check` passes | |
| 2 | CPU-only Torch verification | `torch.version.cuda is None` | |
| 3 | Cold application start | Model loads within 5 min | |
| 4 | First forecast (demo data) | Forecast table visible | |
| 5 | Second forecast (warm) | Inference faster than cold | |
| 6 | Repeated forecast (3x) | Stable timing, no crash | |
| 7 | Upload valid CSV | Preview + forecast works | |
| 8 | Upload file > 50 MB | Rejected before parsing | |
| 9 | Upload CSV with bad timestamps | User-friendly error | |
| 10 | Same timestamp/target column selected | Blocked before forecast | |
| 11 | Refresh page, forecast again | Model cached, warm reuse | |
| 12 | Without HF_TOKEN | Model loads (public model) | |
| 13 | With HF_TOKEN | Model loads | |
| 14 | Two-session concurrency | No crash, queue behaviour recorded | |

> **Note:** Duplicate-timestamp remediation is Phase 1 work. In Stage 0, malformed
> input produces a user-friendly error without detailed duplicate guidance.

## Recorded measurements

| Field | Value |
|-------|-------|
| Build result | |
| Package versions | |
| Model ID | `amazon/chronos-2` |
| Configured revision | |
| Resolved revision | |
| Cold load time (s) | |
| Warm inference time (s) | |
| Peak RSS (MB) | |
| Pipeline construction count | |
| HF_TOKEN present | yes / no |
| Concurrency result | |
| Failure recovery result | |

## Acceptance / rejection

- [ ] Dependency install matches CI
- [ ] CPU-only Torch confirmed
- [ ] Cold start completes within 5 minutes
- [ ] Warm forecast completes within 30 seconds
- [ ] Peak memory within Community Cloud platform limits (to be measured)
- [ ] File upload size limit enforced before parse
- [ ] Same-column mapping blocked
- [ ] Errors show user-friendly messages (no stack traces)
- [ ] Configuration preserved after recoverable error

**Decision:** ⏳ Pending
