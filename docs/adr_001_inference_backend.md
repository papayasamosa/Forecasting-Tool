# ADR-001: Inference Backend Architecture

**Status:** ✅ Accepted (Choice A) with documented limitations  
**Date:** 2026-08-07 (finalised after Cloud Gate C evidence collection)  
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
digest binding) was merged so that genuine Cloud Gate C evidence could be
collected from the deployed app.

**Note (Stage 4 final decision — accepted with documented limitations):**
Genuine Cloud Gate C evidence was collected on the deployed Community Cloud
app at commits `c46e586d` and `c7856f06` (functionally identical code) and
published under `docs/evidence/cloud_gate_c/` (PRs #34 and #35). **16 of 19
required measurements are genuinely captured and verified**, including both
token lifecycles on the exact same deployed code, recoverable inference
failure + configuration preservation, all input validations, and context
truncation. The following limitations are documented and accepted for this
Stage 0 decision:

1. **`two_session_concurrency` was NOT captured at the earlier commits.** Root
   cause was a genuine production robustness finding: the app reproducibly
   **wedged a Streamlit session under forecast triggering** (`is_running`
   became stuck, the Run button stayed disabled, and the request never
   completed until a page refresh). The process-wide `InferenceCoordinator`
   (capacity 1, bounded semaphore) appeared to retain a stuck hold that its
   300 s timeout did not release within the observation window.
   **Resolution:** the defect was fixed in Stage A (PR #37, commit `dc3046fa`;
   fail-closed execution-liveness watchdog + explicit UI run lifecycle) and
   **genuinely re-measured at `dc3046fa`**: two isolated browser sessions
   produced a capacity-1 queued pair (cold 6.44 s window overlapping a queued
   6.43 s request, one pipeline, coordinator healthy). The concurrency
   limitation is **re-measured and resolved**.
2. **`coordinator_timeout_recovery` was NOT run under the 300 s / 120 s
   timeouts** — no legitimate request can hold the permit that long (max
   measured ~8-9 s cold). The queue timeout is now a **measured-justified
   5 s** (`src/config.py`), making a genuine timeout inducible with a
   legitimate cold/max request; final re-measurement is scheduled after the
   redeploy carrying that change. Documented, not fabricated.
3. **`oversized_csv_rejected` is platform-enforced** — the Streamlit uploader
   (`maxUploadSize = 50`, matching the app limit) rejects files > 50 MB
   client-side before the app branch runs. Rejection before parsing was
   verified; the typed acceptance event is not emitted. Represented in the
   canonical contract via `platform_enforced=True`
   (`PLATFORM_ENFORCED_CLOUD_TESTS` in `src/evidence_schemas.py`).

Decision: **Choice A** (cached local CPU inference on Streamlit Community
Cloud) is accepted for Stage 0, with the concurrency robustness defect fixed
and re-measured and the remaining Gate C closure (timeout-recovery
re-measurement at the adjusted 5 s queue timeout) tracked as scheduled work
before public sharing.

## Context

Chronos-2 is a 120M-parameter foundation model. This ADR decides whether to
run inference via:
- **A)** Cached local CPU inference on Streamlit Community Cloud
- **B)** A remote Chronos-2 endpoint (e.g., SageMaker, AutoGluon-Cloud)

## Decision

**Accepted: Choice A — Cached local CPU inference on Streamlit Community Cloud (with documented limitations).**

> Genuine Cloud Gate C evidence (16/19 measurements verified, both token
> lifecycles on the exact same deployed code) supports Choice A. The three
> remaining items are accepted as documented limitations (see the Stage 4
> note above): concurrency blocked by a real session-wedging robustness bug
> (fix + re-measure required before public sharing), timeout recovery not
> safely inducible, and oversized rejection enforced by the platform.
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
Concurrent-user behaviour was NOT successfully measured (see the Stage 4
note): the deployed app reproducibly wedges a Streamlit session under
forecast triggering, and the coordinator's bounded semaphore appeared to
retain a stuck hold. **This is a confirmed production robustness issue that
must be fixed and re-measured before public sharing**; it is tracked as a
required follow-up rather than a blocker for this Stage 0 ADR acceptance.

## Consequences (accepted)

- Cloud evidence confirms Choice A: the `Chronos2Adapter` with its
  `st.cache_resource`-cached pipeline is sufficient for Stage 0. No API
  gateway or GPU endpoint is needed.
- A `RemoteChronos2Adapter` is NOT required now; it would only be added if a
  future decision revisits Choice B. Streamlit pages would not require
  changes.
- The inference coordinator with bounded semaphore remains in place, but its
  session-wedging robustness issue (stuck `is_running` / stuck semaphore hold
  under triggering) must be fixed and the concurrency measurement re-taken
  before public sharing.

## Required Cloud evidence (Gate C) — status

1. ✅ Clean dependency build (`dependency_install`, `pip_check`)
2. ✅ CPU-only Torch confirmed (`cpu_only_torch`, torch 2.13.0+cpu, CUDA None)
3. ✅ No NVIDIA/CUDA packages (`no_nvidia_packages`)
4. ✅ Model load without HF_TOKEN (`token_absent_load`, 8.178 s cold)
5. ✅ Model load with HF_TOKEN (`token_present_load`, 8.745 s cold)
6. ✅ Download-cold app start (`cold_forecast`, RSS ~330 → ~970 MB)
7. ✅ First forecast (`cold_forecast`)
8. ✅ Same-process warm forecast (`warm_forecast`, 0.06–0.09 s, pipeline reused)
9. ✅ Three repeated forecasts (`repeated_forecasts`, ≥3 warm runs per lifecycle)
10. ✅ Pipeline construction count (= 1 per lifecycle)
11. ✅ Peak memory recorded (`process_peak_rss_mb` 976 MB token-present)
12. ✅ Valid CSV upload and forecast (`valid_csv_forecast`)
13. ⚠️ Oversized CSV rejection — platform-enforced (uploader rejects > 50 MB
    client-side before the app branch; rejection-before-parse verified, typed
    event not emitted)
14. ✅ Blank timestamp rejection (`blank_timestamp_rejected`)
15. ✅ Invalid timestamp rejection (`invalid_timestamp_rejected`)
16. ✅ Same column mapping rejection (`same_column_rejected`)
17. ✅ Context truncation notice (`context_truncation_visible`, 9000→8192 rows)
18. ✅ Recoverable inference failure (`recoverable_failure`, genuine
    `InferenceError` from a non-numeric-target CSV + successful recovery)
19. ✅ Configuration preservation after error (`configuration_preserved`)
20. ❌ Two simultaneous sessions (concurrency) — NOT captured; blocked by the
    session-wedging production bug (see Stage 4 note). Fix + re-measure
    required before public sharing.
21. ⏳ Queue/lock behaviour — coordinator `sync_mode=semaphore`, `capacity=1`
    reported; the wedging finding indicates a real queue robustness issue
    requiring the fix in (20).
22. ❌ Coordinator timeout recovery — 300 s timeout, not safely inducible;
    documented, not fabricated.

## Linked evidence

- ~~[Local Stage 0 evidence bundle](../docs/evidence/stage0/evidence_local_stage0_bundle_20260729_130534_342298_71036f6f.json)~~ (invalidated — PR #18)
- ✅ [Genuine local Stage 0 evidence bundle (Gate B3)](../docs/evidence/stage0/evidence_local_stage0_bundle_20260805_171733_555681_2ce6345f.json) — published 2026-08-05, commit `7831cb4`, independently executed token-present run
- ✅ [Cloud Gate C genuine collection report](evidence/cloud_gate_c/README.md) — PRs #34/#35, commits `c46e586d` / `c7856f06`, 16/19 verified with three documented limitations
- ✅ [Community Cloud test checklist](community_cloud_test_checklist.md) — filled with genuine results, Gate C not marked complete
- [Stage 0 benchmark report](stage_0_benchmark_report.md)
- Community Cloud deployment URL: `https://forecasting-tool-bjhchtg9t6xhyxshidineu.streamlit.app/`
