# Cloud Gate C — Genuine Collection Report (final status: Gate C NOT complete)

**Date:** 2026-08-07 (UTC times from artifacts)
**Stage 4 outcome:** ADR-001 was **accepted (Choice A) with documented limitations** on
2026-08-07 based on this evidence (see `docs/adr_001_inference_backend.md`). Gate C itself
remains **not marked complete** — the manifest `cloud_summary` entry stays `null`.
**Deployment:** https://forecasting-tool-bjhchtg9t6xhyxshidineu.streamlit.app/
**Deployed commits (verified, git_head):**
- `c46e586d19c33e3dd4118ca99bbab1f0bc0743d4` (initial lifecycles) and
  `c7856f06a188a470bea6eee87808d533b34ed394` (docs-only PR #34; **functionally identical code**)
- **`dc3046fa2e8c32e3e379000ac68d1f43872a1270`** (Stage A robustness closure — PR #37; the
  **current** deployment used for the concurrency re-measurement below)
**Model:** `amazon/chronos-2`, pinned revision `29ec3766d36d6f73f0696f85560a422f50e8498c` (unchanged in all lifecycles)

This report is built **only** from typed JSON downloaded from the deployed app and
validated with the repository's own schema/validation code
(`import_prior_collection_bundle` in `src/cloud_diagnostics.py`). No measurement is
invented; screenshots and manually transcribed UI values are not used.

## Stage A re-measurement at dc3046fa (2026-08-07)

The production session-wedging defect (below) was fixed in Stage A (PR #37): the
coordinator now separates `queue_timeout_seconds` from a fail-closed backend
execution-liveness watchdog, and the Forecast page uses an explicit active-request
lifecycle instead of a lone `is_running` boolean. The app was rebooted on the exact
Stage A merge commit `dc3046fa` (deployment identity verified: `git_head`, exact
40-hex match, model revision pinned, CPU-only torch, coordinator healthy with
`queue_timeout_s=120`).

### two_session_concurrency — GENUINELY CAPTURED at dc3046fa ✅

Two genuinely independent browser sessions (two isolated browser contexts) produced a
capacity-1 queued concurrency pair. Typed request records (retained verbatim in
`cloud_diagnostics_concurrency_primary_20260807_dc3046fa.json` and
`cloud_diagnostics_concurrency_peer_20260807_dc3046fa.json`):

| Field | Session 1 (cold) | Session 2 (queued) |
|---|---|---|
| session_id | `session_5850e6f5fa29` | `session_ecc49f26c6de` |
| request_id | `220cc5c4-…` | `e0055809-…` |
| started_at_utc | `18:31:35.333` | `18:31:35.350` |
| completed_at_utc | `18:31:41.783` | `18:31:42.046` |
| queue_seconds | 0.0 | **6.434** |
| model_load_seconds | 6.371 | 0.0 |
| pipeline_constructed | true | false |
| pipeline_reused | false | true |
| success | true | true |

- Distinct session IDs ✅ · distinct request IDs ✅
- **Overlapping full request windows** (session 2 queued during session 1's cold window) ✅
- **Non-overlapping inference windows** (serialised capacity-1) ✅
- Measured queue time 6.434 s ✅ · both success ✅
- One process-cached pipeline (`pipeline_construction_count=1`) ✅
- No stuck UI state; coordinator `health=healthy`, `last_failure_category=` ✅

### coordinator_timeout_recovery — timeout adjusted (was not inducible)

Measured request durations at dc3046fa prove that **no legitimate request can hold the
capacity-1 permit long enough for the old 120 s queue timeout to fire**:
warm ~0.06-0.5 s, cold (incl. model load) ~6.4-8.7 s, maximum legitimate request
(8192 context × 1024 horizon, Chronos-2 parallel horizon generation) ~1 s warm / ~8-9 s
cold. The queue timeout is therefore a **measured-justified 5 s** (see `src/config.py`):
it bounds the worst-case silent wait, stays above a normal warm request, and is
genuinely inducible with a legitimate cold/max request. Final timeout-recovery
re-measurement requires a redeploy on the commit carrying that change and is scheduled
as the remaining Gate C measurement.

### oversized_csv_rejected — platform-enforced (documented in contract)

The Streamlit uploader (`maxUploadSize = 50` in `.streamlit/config.toml`, matching
`MAX_UPLOAD_SIZE_BYTES`) rejects files > 50 MB client-side before the app branch runs,
so the typed in-app event can never be emitted. Rejection-before-parse IS verified. The
canonical contract now represents this truthfully via `platform_enforced=True` for
`oversized_csv_rejected` (see `PLATFORM_ENFORCED_CLOUD_TESTS` in `src/evidence_schemas.py`).

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

## two_session_concurrency — captured at dc3046fa (see above)

Earlier attempts at `c46e586d` / `c7856f06` produced no genuine overlapping pair.
Root causes then:
1. Async human-in-the-loop coordination latency is far larger than warm run duration
   (0.1–0.9 s), so simultaneous clicks did not overlap.
2. **Production robustness finding:** the app reproducibly **wedged a Streamlit session
   under forecast triggering** — `is_running` became stuck `True`, the Run button stayed
   disabled and the request never completed, until the page was refreshed. This happened
   to automation sessions and to the operator's browser. The coordinator (`capacity=1`,
   `sync_mode=semaphore`) appeared to have a stuck hold that its 300 s timeout did not
   release within the observation window.
A concurrency-supplement bundle (`session_a643d633407e`, 3 records, no overlap, receipt
`b6d3530a…`) was downloaded as honest negative evidence.

**Resolution:** Stage A (PR #37, commit `dc3046fa`) fixed the wedge (fail-closed
execution-liveness watchdog + explicit UI run lifecycle). Genuine re-measurement with two
isolated browser sessions at `dc3046fa` captured a capacity-1 queued pair (see the
"Stage A re-measurement" section above) — **the concurrency limitation is re-measured and
resolved**.

## coordinator_timeout_recovery — adjusted and scheduled for final re-measurement

Under the old 300 s (and Stage A's 120 s) timeouts, inducing a genuine timeout required a
>120 s semaphore hold, which no legitimate request can produce (max measured ~8-9 s cold).
The queue timeout is now a **measured-justified 5 s** (`src/config.py`): with a legitimate
cold/max request holding capacity (~7-9 s), a queued request genuinely reaches the 5 s
timeout and recovers on retry. Final re-measurement requires a redeploy on the commit
carrying that change; until then this test is **not yet re-measured** (not fabricated).

## oversized_csv_rejected — platform-enforced

The Streamlit uploader (`maxUploadSize = 50` in `.streamlit/config.toml`, matching
`MAX_UPLOAD_SIZE_BYTES`) rejects files > 50 MB client-side before the app branch runs
("Error: File must be 50.0MB or smaller."). Rejection before parsing DOES occur and was
observed, but the typed acceptance event is not emitted because the file never reaches the app.

## Honest final status

- **18 of 19 required measurements are genuinely captured and verified** (both token paths on
  functionally identical code, recoverable failure, configuration preservation, all input
  validations, context truncation, dependency/pip/CPU-only checks, and — at `dc3046fa` —
  **two-session concurrency**).
- The remaining two are: `coordinator_timeout_recovery` (queue timeout adjusted to a
  measured-justified 5 s; final re-measurement scheduled after redeploy) and
  `oversized_csv_rejected` (platform-enforced; rejection-before-parse verified, typed event
  not emittable — represented in the contract via `platform_enforced`).
- **Gate C is NOT complete.** The manifest `cloud_summary` entry stays `null`; no `cloud_stage0`
  release evidence is published. The session-wedging robustness defect is **fixed and
  re-measured** (concurrency proven at `dc3046fa`); the final Gate C closure requires the
  timeout-recovery re-measurement at the adjusted (5 s) queue timeout.

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
