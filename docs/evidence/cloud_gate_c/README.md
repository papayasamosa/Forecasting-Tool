# Cloud Gate C — Genuine Collection Report (draft, Gate C NOT yet complete)

**Date:** 2026-08-07 (UTC times from artifacts)
**Deployment:** https://forecasting-tool-bjhchtg9t6xhyxshidineu.streamlit.app/
**Deployed commit (verified, both lifecycles):** `c46e586d19c33e3dd4118ca99bbab1f0bc0743d4` (resolution source `git_head`)
**Model:** `amazon/chronos-2`, pinned revision `29ec3766d36d6f73f0696f85560a422f50e8498c` (unchanged in both lifecycles)

This report is built **only** from typed JSON downloaded from the deployed app and
validated with the repository's own schema/validation code
(`import_prior_collection_bundle` in `src/cloud_diagnostics.py`). No measurement is
invented; screenshots and manually transcribed UI values are not used.

## Verified artifacts

| Artifact | Session | Verified |
|---|---|---|
| `cloud_gate_c_collection_bundle_token_absent_20260807_053233_session411bd35493fe.json` | `session_411bd35493fe` (token absent) | ✅ canonical digest `7ed0796e…` OK; 7 records; 13 tests; receipt `ab7b1e9d…` |
| `cloud_gate_c_collection_bundle_combined_20260807_081416_session044a0ffd048f.json` | `session_044a0ffd048f` (token present, A imported) | ✅ canonical digest `eba43555…` OK; 14 records; 14 tests; receipt `c4e6684a…` |

## Lifecycle A — token ABSENT (Deployment A)

- Cold load WITHOUT token: request `3867b1f0-c6c2-4b9b-aaac-a08854b04251`,
  `model_load_s = 8.178`, `pipeline_constructed = True` → `cold_forecast` + `token_absent_load`
- 7 request records, 13 acceptance tests, diagnostics `hf_token_present: false`

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
| Recoverable inference failure | ❌ not run | requires inducing a genuine adapter failure (not fabricated) |
| Configuration preservation after error | ✅ | `configuration_preserved` events recorded on the error paths that genuinely ran (rejections) |
| Two simultaneous sessions | ❌ not run | requires a second browser session; not achievable with the available automation tooling |
| Queue/lock behaviour | ⏳ partial | coordinator `sync_mode=semaphore`, `capacity=1` reported in diagnostics; no overlapping-session measurement |
| Coordinator timeout recovery | ❌ not run | coordinator timeout is 300 s — not safely inducible; requires induced genuine timeout + retry |

## Honest status

- **14 of the required measurements are genuinely captured and verified**, including
  both token paths on the exact same deployed commit — the core Gate C proof.
- The remaining items require capabilities the agent does not have:
  - a **second browser session** (concurrency) — needs either the user's own second
    browser, or different automation tooling;
  - an **induced genuine failure / 300 s timeout** (recoverable failure, timeout
    recovery) — would require deliberate production interference;
  - the **oversized-rejection acceptance event** — genuinely blocked by the platform
    upload limit (rejection-before-parse is enforced and observed, but the typed event
    is not emitted).
- **Gate C is therefore NOT complete.** This directory is a draft evidence collection,
  not release evidence. The manifest `cloud_summary` entry stays `null`.
