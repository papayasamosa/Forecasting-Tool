# Cloud Gate C — Genuine Collection Report (final status: Gate C NOT complete)

**Date:** 2026-08-07 (UTC times from artifacts)
**Deployment:** https://forecasting-tool-bjhchtg9t6xhyxshidineu.streamlit.app/
**Deployed commits (verified, git_head):** `c46e586d19c33e3dd4118ca99bbab1f0bc0743d4` (initial
lifecycles) and `c7856f06a188a470bea6eee87808d533b34ed394` (current, after the docs-only
evidence PR #34 auto-deployed; **functionally identical code** — PR #34 changed only
documentation and evidence JSON).
**Model:** `amazon/chronos-2`, pinned revision `29ec3766d36d6f73f0696f85560a422f50e8498c` (unchanged in all lifecycles)

This report is built **only** from typed JSON downloaded from the deployed app and
validated with the repository's own schema/validation code
(`import_prior_collection_bundle` in `src/cloud_diagnostics.py`). No measurement is
invented; screenshots and manually transcribed UI values are not used.

## Verified artifacts

| Artifact | Session / commit | Verified |
|---|---|---|
| `cloud_gate_c_collection_bundle_token_absent_20260807_053233_session411bd35493fe.json` | `session_411bd35493fe` (token absent), `c46e586d` | ✅ canonical digest `7ed0796e…` OK; 7 records; 13 tests; receipt `ab7b1e9d…` |
| `cloud_gate_c_collection_bundle_combined_20260807_081416_session044a0ffd048f.json` | `session_044a0ffd048f` (token present, A imported), `c46e586d` | ✅ canonical digest `eba43555…` OK; 14 records; 14 tests; receipt `c4e6684a…` |
| `cloud_gate_c_collection_bundle_token_absent_20260807_053233_commit_c7856f06_session31a05d6c2881.json` | `session_31a05d6c2881` (token absent), `c7856f06` | ✅ canonical digest `bde26e5c…` OK; 9 records; **15 tests incl. `recoverable_failure` + `configuration_preserved`**; receipt `a4d3634b…` |

## Lifecycle A — token ABSENT (Deployment A)

- At `c46e586d` (`session_411bd35493fe`): cold load WITHOUT token, request
  `3867b1f0-c6c2-4b9b-aaac-a08854b04251`, `model_load_s = 8.178`, `pipeline_constructed = True`
  → `cold_forecast` + `token_absent_load`; 7 records; 13 tests.
- Re-verified at `c7856f06` (`session_31a05d6c2881`): cold load WITHOUT token, request
  `593ca7f7-efaa-4bca-a3c8-cda46b856b09` → `cold_forecast` + `token_absent_load`; warm ×3;
  repeated; valid CSV; same-column/blank/invalid-timestamp rejections; context truncation;
  **`recoverable_failure` + `configuration_preserved`** (genuine `InferenceError` from a CSV
  with non-numeric target values, followed by a successful recovery run); 9 records; 15 tests;
  diagnostics `hf_token_present: false`.

## Lifecycle B — token PRESENT (Deployment B)

- At `c46e586d` (`session_044a0ffd048f`, A imported): cold load WITH token, request
  `c183d6b4-cc49-4951-bb16-aba31271e5ab`, `model_load_s = 8.745`,
  `pipeline_constructed = True` → `cold_forecast` + `token_present_load`; 14 records (7 B + 7 A);
  14 tests; both token paths bound (`token_absent_execution_ids` + `token_present_execution_ids`).
- At `c7856f06` (`session_0b868694bb46`, A2 imported): cold load WITH token, request
  `a7363da9-e8c9-49e8-8460-ad5d37827100` → `cold_forecast` + `token_present_load`; warm ×3;
  repeated; valid CSV; rejections; truncation; `recoverable_failure` + `configuration_preserved`;
  37 records (18 B + 9 A2 + peer), 16 tests, both token paths bound. **Note:** this bundle's
  downloaded file was overwritten during the concurrency attempts and is not retained on disk;
  its session record digests and test names were verified before the file was lost (canonical
  digest `94fe873c…`, receipt `08a425ae…`). The `c46e586d` combined bundle above remains the
  retained two-lifecycle record and is functionally identical (docs-only diff).

## two_session_concurrency — NOT captured (documented)

Despite many coordinated attempts (busy loops, a second browser session, cold-load window
coordination, multiple peer sessions `fe69173a1264` / `db43bf01bce0` / `22a0a47b3463`), no
genuine overlapping request-window pair was recorded. Root causes:
1. Async human-in-the-loop coordination latency is far larger than warm run duration
   (0.1–0.9 s), so simultaneous clicks did not overlap.
2. **Production robustness finding:** the app reproducibly **wedges a Streamlit session under
   forecast triggering** — `is_running` becomes stuck `True`, the Run button stays disabled and
   the request never completes, until the page is refreshed. This happened to automation
   sessions and to the operator's browser (the operator had to refresh mid-test; a rapid-click
   stream produced only one recorded request). The coordinator (`capacity=1`, `sync_mode=semaphore`)
   appears to have a stuck hold that its 300 s timeout did not release within the observation
   window. This must be fixed before the concurrency measurement can be taken reliably.
A concurrency-supplement bundle (`session_a643d633407e`, 3 records, no overlap, receipt
`b6d3530a…`) was downloaded as honest negative evidence but is not treated as passing the test.

## coordinator_timeout_recovery — NOT captured

The coordinator timeout is 300 s; inducing a genuine timeout requires a >300 s semaphore hold,
which is not safely inducible in production. Documented as not run (not fabricated).

## oversized_csv_rejected — platform-enforced

The Streamlit uploader (`maxUploadSize = 50` in `.streamlit/config.toml`, matching
`MAX_UPLOAD_SIZE_BYTES`) rejects files > 50 MB client-side before the app branch runs
("Error: File must be 50.0MB or smaller."). Rejection before parsing DOES occur and was
observed, but the typed acceptance event is not emitted because the file never reaches the app.

## Honest final status

- **16 of 19 required measurements are genuinely captured and verified** (both token paths on
  the exact same deployed code, recoverable failure, configuration preservation, all input
  validations, context truncation, dependency/pip/CPU-only checks).
- The remaining three are: `two_session_concurrency` (blocked by the session-wedging production
  bug + coordination latency; needs a fix then re-measurement), `coordinator_timeout_recovery`
  (300 s timeout, not safely inducible), and `oversized_csv_rejected` (platform-enforced;
  rejection-before-parse verified, typed event not emitted).
- **Gate C is NOT complete.** The manifest `cloud_summary` entry stays `null`; no `cloud_stage0`
  release evidence is published. The session-wedging robustness finding should be tracked as a
  fix before public sharing.

## Lifecycle B — token PRESENT (Deployment B) — combined record

- Cold load WITH token: request `c183d6b4-cc49-4951-bb16-aba31271e5ab`,
  `model_load_s = 8.745`, `pipeline_constructed = True` → `cold_forecast` + `token_present_load`
- Prior token-absent bundle imported at finalise (codex P1-23): 14 request records
  (7 B + 7 A), 14 acceptance tests, `token_absent_execution_ids = [3867b1f0-…]`,
  `token_present_execution_ids = [c183d6b4-…]`, diagnostics `hf_token_present: true`

## Measured results matrix

| Requirement (ADR / checklist) | Result | Evidence |
|---|---|---|
| Clean dependency build | ✅ | `dependency_install`, `pip_check` |
| CPU-only Torch | ✅ | `cpu_only_torch` (torch 2.13.0+cpu, torch.version.cuda None) |
| No NVIDIA/CUDA packages | ✅ | `no_nvidia_packages` |
| Model load without HF_TOKEN | ✅ | `token_absent_load` (3867b1f0-…, 8.178 s) |
| Model load with HF_TOKEN | ✅ | `token_present_load` (c183d6b4-…, 8.745 s) |
| Download-cold app start | ✅ | `cold_forecast` both lifecycles; cold RSS ~330 MB → ~970 MB |
| First forecast | ✅ | `cold_forecast` |
| Same-process warm forecast | ✅ | `warm_forecast` (0.06–0.09 s, `pipeline_reused=True`, `model_load_s=0.0`) |
| Three repeated forecasts | ✅ | `repeated_forecasts` (≥3 warm runs each lifecycle) |
| Pipeline construction count (=1) | ✅ | one `pipeline_constructed=True` record per lifecycle |
| Peak memory recorded | ✅ | `process_peak_rss_mb` in diagnostics (976 MB token-present) |
| Valid CSV upload + forecast | ✅ | `valid_csv_forecast` |
| Oversized CSV rejection | ⚠️ platform-enforced | Streamlit uploader rejected 51 MB client-side ("File must be 50.0MB or smaller.") BEFORE parsing; the app-level `oversized_csv_rejected` event cannot be recorded because `.streamlit/config.toml` `maxUploadSize=50` blocks the file before the app branch runs |
| Blank timestamp rejection | ✅ | `blank_timestamp_rejected` |
| Invalid timestamp rejection | ✅ | `invalid_timestamp_rejected` |
| Same column mapping rejection | ✅ | `same_column_rejected` |
| Context truncation notice | ✅ | `context_truncation_visible` (9000→8192 rows, notice rendered in success path) |
| Recoverable inference failure | ✅ | `recoverable_failure` (genuine `InferenceError` from a non-numeric-target CSV, then successful recovery run in the same session) |
| Configuration preservation after error | ✅ | `configuration_preserved` on genuine error paths (rejections and the recoverable failure) |
| Two simultaneous sessions | ❌ not captured | see `two_session_concurrency` section: blocked by the session-wedging production bug + coordination latency; NOT fabricated |
| Queue/lock behaviour | ⏳ partial | coordinator `sync_mode=semaphore`, `capacity=1` reported in diagnostics; the wedging finding indicates a real queue/semaphore robustness issue that must be fixed before public sharing |
| Coordinator timeout recovery | ❌ not run | coordinator timeout is 300 s — not safely inducible; documented, not fabricated |
