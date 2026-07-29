# ADR-001: Inference Backend Architecture

**Status:** ✅ Accepted — Choice A  
**Date:** 2026-07-29 (updated)

## Context

Chronos-2 is a 120M-parameter foundation model. This ADR decides whether to
run inference via:
- **A)** Cached local CPU inference on Streamlit Community Cloud
- **B)** A remote Chronos-2 endpoint (e.g., SageMaker, AutoGluon-Cloud)

## Decision

**Choice A — Cached local CPU inference on Streamlit Community Cloud.**

### Evidence base

| Measurement | Local result (Gate B2) | Cloud requirement | Feasible? |
|---|---|---|---|
| Cold-start total | 78.6 s (download-cold) / 37.7 s (process-cold) | < 5 min | ✅ Yes |
| Warm inference | 0.2–1.7 s | < 30 s | ✅ Yes |
| Peak process RSS | 825 MB (token-present) | Community Cloud ~1 GB limit | ✅ Yes |
| Pipeline reuse | Verified (0.0 s model load on warm) | Required | ✅ Yes |
| Repeated forecasts | 10/10 rolling folds stable | No degradation | ✅ Yes |
| CPU-only Torch | Confirmed (2.13.0+cpu, CUDA: None) | Required | ✅ Yes |
| Token-absent resolution | Works (public model) | Required | ✅ Yes |
| Token-present resolution | Works (exact revision match) | Optional | ✅ Yes |
| Failure recovery | Expected failure + same-adapter retry verified | Required | ✅ Yes |
| Concurrency | Not measured on Cloud | To be verified | ⏳ TBD |

### Platform considerations

Streamlit Community Cloud free tier provides approximately 1 GB RAM. The local
peak RSS of 825 MB leaves ~175 MB headroom. A cold start may take up to 90
seconds (model download + pipeline construction), which is within the 5-minute
Cloud request timeout.

The `--extra-index-url` directive in `requirements.txt` was deployed to
Community Cloud at URL:
`https://forecasting-tool-bjhchtg9t6xhyxshidineu.streamlit.app/`

### Risk: concurrency

`st.cache_resource` shares one adapter across sessions. No process-wide lock
was tested. If concurrent sessions cause pipeline contention, a bounded queue
or per-session adapter may be needed. This should be verified before public
sharing but does not block the ADR decision.

## Consequences

- The `Chronos2Adapter` with its `st.cache_resource`-cached pipeline is
  sufficient for Stage 0 and Phase 1. No API gateway or GPU endpoint is needed.
- No `RemoteChronos2Adapter` is required unless Cloud evidence later shows
  concurrency issues or the platform memory limit is insufficient (the local
  825 MB peak is close to the 1 GB boundary).
- The Streamlit app requires no architectural changes.

## Linked evidence

- [Local Stage 0 evidence bundle](../docs/evidence/stage0/evidence_local_stage0_bundle_20260729_130534_342298_71036f6f.json)
- [Stage 0 benchmark report](stage_0_benchmark_report.md)
- Community Cloud deployment URL: `https://forecasting-tool-bjhchtg9t6xhyxshidineu.streamlit.app/`
- Community Cloud test checklist: [community_cloud_test_checklist.md](community_cloud_test_checklist.md)
