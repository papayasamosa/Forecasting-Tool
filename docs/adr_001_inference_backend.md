# ADR-001: Inference Backend Architecture

**Status:** ⏳ Provisionally accepted, pending Cloud Gate C  
**Date:** 2026-08-06 (updated)  
**Note:** A genuine current-head local evidence bundle (Gate B3) is now
published on commit `7831cb4`:
`docs/evidence/stage0/evidence_local_stage0_bundle_20260805_171733_555681_2ce6345f.json`
— it includes an independently executed token-present run (unique run ID and
timestamps) and passes the hardened bundle checks. The invalidated PR #18
bundle remains in place for audit only. Cloud Gate C evidence is still
required for final ADR acceptance.

**Note (Stage 1 instrumentation closure):** the Cloud evidence
instrumentation (exact deployed-commit resolution, typed runtime
diagnostics, request-scoped memory sampling, dependency diagnostics,
bounded request telemetry, token-state boolean, and collection-session
digest binding) is being merged so that genuine Cloud Gate C evidence can
be collected from the deployed app. **Gate C is not complete** in that
instrumentation pull request — this ADR remains provisional until genuine
Cloud collection, evidence publication, and review complete.

## Context

Chronos-2 is a 120M-parameter foundation model. This ADR decides whether to
run inference via:
- **A)** Cached local CPU inference on Streamlit Community Cloud
- **B)** A remote Chronos-2 endpoint (e.g., SageMaker, AutoGluon-Cloud)

## Decision

**Provisionally: Choice A — Cached local CPU inference on Streamlit Community Cloud, pending Cloud evidence.**

> Local evidence (Gate B2) supports feasibility and justifies a Cloud trial,
> but the PRD's Stage 0 release gate requires measured Community Cloud
> evidence. This ADR will be finally accepted or rejected only after the
> Cloud Gate C evidence is collected and evaluated.
>
> **Note:** The PR #18 evidence bundle has been explicitly invalidated and
> preserved for audit. Do not cite invalidated evidence as proof. A valid
> genuine local bundle is now published (see Linked evidence below) and
> supersedes it.

### Local evidence (not Cloud proof)

| Measurement | Local result (Gate B2) | Cloud requirement | Feasible? |
|---|---|---|---|
| Cold-start total | 78.6 s (download-cold) / 37.7 s (process-cold) | < 5 min | Likely |
| Warm inference | 0.2–1.7 s | < 30 s | Likely |
| Peak process RSS | 825 MB (token-present) | Community Cloud ~1 GB typical | Uncertain |
| Pipeline reuse | Verified (0.0 s model load on warm) | Required | Likely |
| Repeated forecasts | 10/10 rolling folds stable | No degradation | Likely |
| CPU-only Torch | Confirmed (2.13.0+cpu, CUDA: None) | Required | ✅ |
| Token-absent resolution | Works (public model) | Required | ✅ |
| Token-present resolution | Works (exact revision match) | Required | ✅ |
| Failure recovery | Expected failure + same-adapter retry verified | Required | Likely |
| Concurrency | Not measured on Cloud | Required before public sharing | ⏳ TBD |

### Platform considerations

Official Streamlit Community Cloud resources are dynamic — CPU ranges from
approximately 0.078 to 2 cores, and memory from approximately 690 MB to
2.7 GB, subject to change without notice.

Local Windows RSS (825 MB peak) is **not** a guaranteed Cloud memory
calculation. It does not include Streamlit process overhead, Python
interpreter differences, Cloud model-cache behaviour, dataframe memory,
multiple sessions, allocator differences, or container overhead. Do not
subtract local RSS from an assumed Cloud allowance to claim headroom.

The `--extra-index-url` directive in `requirements.txt` was deployed to
Community Cloud at URL:
`https://forecasting-tool-bjhchtg9t6xhyxshidineu.streamlit.app/`

### Risk: concurrency

`st.cache_resource` shares one adapter across sessions. A process-wide
`InferenceCoordinator` with a bounded semaphore serialises inference access.
Concurrent-user behaviour remains a blocking measurement for final ADR
acceptance and must be completed before public sharing.

## Consequences (provisional)

- If Cloud evidence confirms Choice A after Gate C, the `Chronos2Adapter`
  with its `st.cache_resource`-cached pipeline is sufficient. No API gateway
  or GPU endpoint is needed.
- If Cloud evidence requires Choice B, a `RemoteChronos2Adapter` implementing
  the same `ForecastBackend` protocol will be added. Streamlit pages will not
  require changes.
- The inference coordinator with bounded semaphore is in place regardless of
  which choice is confirmed.

## Required Cloud evidence (Gate C)

1. Clean dependency build
2. CPU-only Torch confirmed
3. No NVIDIA/CUDA packages
4. Model load without HF_TOKEN
5. Model load with HF_TOKEN
6. Download-cold app start
7. First forecast
8. Same-process warm forecast
9. Three repeated forecasts (stable timing, pipeline reuse)
10. Pipeline construction count (= 1)
11. Peak memory recorded
12. Valid CSV upload and forecast
13. Oversized CSV rejection
14. Blank timestamp rejection
15. Invalid timestamp rejection
16. Same column mapping rejection
17. Context truncation notice
18. Recoverable inference failure
19. Configuration preservation after error
20. Two simultaneous sessions (concurrency with overlapping windows)
21. Queue or lock behaviour (if applicable)
22. Coordinator timeout recovery

## Linked evidence

- ~~[Local Stage 0 evidence bundle](../docs/evidence/stage0/evidence_local_stage0_bundle_20260729_130534_342298_71036f6f.json)~~ (invalidated — PR #18)
- ✅ [Genuine local Stage 0 evidence bundle (Gate B3)](../docs/evidence/stage0/evidence_local_stage0_bundle_20260805_171733_555681_2ce6345f.json) — published 2026-08-05, commit `7831cb4`, independently executed token-present run
- [Stage 0 benchmark report](stage_0_benchmark_report.md)
- Community Cloud deployment URL: `https://forecasting-tool-bjhchtg9t6xhyxshidineu.streamlit.app/`
- Community Cloud test checklist: [community_cloud_test_checklist.md](community_cloud_test_checklist.md)
