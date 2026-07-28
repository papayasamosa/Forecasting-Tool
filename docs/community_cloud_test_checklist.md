# Community Cloud Deployment Test Checklist

Use this checklist when deploying to Streamlit Community Cloud.

## Pre-deployment

- [ ] Branch: `main` or `stage0-completion`
- [ ] Entrypoint: `app.py`
- [ ] Python version: 3.12 (select in Cloud advanced settings)
- [ ] `requirements.txt` pinned exactly
- [ ] `requirements-dev.txt` NOT included (dev deps excluded from production)

## Secrets

- [ ] Optional: Add `HF_TOKEN` in Streamlit secrets if downloading gated models
- [ ] Without token: test that `amazon/chronos-2` (open model) downloads correctly

## Test scenarios

| # | Test | Expected | Actual |
|---|------|----------|--------|
| 1 | Cold application start | Model loads within 5 min | |
| 2 | First forecast (demo data) | Forecast table visible | |
| 3 | Second forecast (warm) | Inference faster than cold | |
| 4 | Repeated forecast (3x) | Stable timing, no crash | |
| 5 | Upload valid CSV | Preview + forecast works | |
| 6 | Upload file > 50 MB | Rejected before parsing | |
| 7 | Upload CSV with bad data | User-friendly error | |
| 8 | Upload CSV with duplicates | Error with guidance | |
| 9 | Refresh page, forecast again | Model cached, warm reuse | |
| 10 | Without HF_TOKEN | Model loads (public model) | |
| 11 | With HF_TOKEN | Model loads | |

## Memory observations

Record approximate RSS from Cloud logs or monitoring:

| Condition | RSS (MB) |
|-----------|---------|
| Idle (no model loaded) | |
| After cold model load | |
| After warm forecast | |
| Peak during session | |

## Acceptance / rejection

- [ ] Cold start completes within 5 minutes
- [ ] Warm forecast completes within 30 seconds
- [ ] Peak memory stays below 900 MB
- [ ] File upload size limit enforced before parse
- [ ] Errors show user-friendly messages (no stack traces)
- [ ] Configuration preserved after recoverable error

**Decision:** ⏳ Pending
