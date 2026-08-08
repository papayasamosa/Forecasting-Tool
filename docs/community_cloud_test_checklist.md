# Community Cloud Deployment Test Checklist

Use this checklist when deploying to Streamlit Community Cloud.

## Pre-deployment

- [ ] Branch: `main`
- [ ] Entrypoint: `app.py`
- [ ] Python version: 3.12 (select in Cloud advanced settings)
- [ ] `requirements.txt` pinned exactly
- [ ] `requirements-dev.txt` NOT included (dev deps excluded from production)
- [ ] CPU-only Torch via `--extra-index-url` in `requirements.txt` (no Streamlit secrets needed)
- [ ] Verify `torch.version.cuda is None` after build
- [ ] Branch protection requires green CI and resolved review threads

## Dependency-install parity check

- [ ] Cloud `pip install -r requirements.txt` must match CI install path
- [ ] Both use `--extra-index-url` directive from `requirements.txt` for CPU Torch
- [ ] No CUDA packages installed
- [ ] `pip check` passes

## Secrets

- [ ] Optional: Add `HF_TOKEN` in Streamlit secrets if downloading gated models
- [ ] Without token: test that `amazon/chronos-2` (open model) downloads correctly
- [ ] Token never printed or persisted

## Test scenarios

> **Status key:** ✅ passed (genuine, verified in the typed collection bundles under
> `docs/evidence/cloud_gate_c/`, commit `c46e586d`, 2026-08-07) · ⚠️ platform-enforced
> (rejection before parsing genuinely occurred via the Streamlit uploader, but the
> typed app event is not emitted) · ❌ not run (requires tooling/actions the agent does
> not have; never fabricated).

| # | Canonical Test Name | Expected | Actual |
|---|---------------------|----------|--------|
| 1 | `dependency_install` | `pip install -r requirements.txt` succeeds | ✅ both lifecycles |
| 2 | `pip_check` | `pip check` passes | ✅ both lifecycles |
| 3 | `cpu_only_torch` | `torch.version.cuda is None` | ✅ both (torch 2.13.0+cpu) |
| 4 | `no_nvidia_packages` | No NVIDIA/CUDA packages installed | ✅ both |
| 5 | `token_absent_load` | Model loads without HF_TOKEN (public model) | ✅ A lifecycle (req `3867b1f0-…`, 8.178 s) |
| 6 | `token_present_load` | Model loads with HF_TOKEN | ✅ B lifecycle (req `c183d6b4-…`, 8.745 s) |
| 7 | `cold_forecast` | First forecast completes, model loads within 5 min | ✅ both (RSS ~330→~970 MB) |
| 8 | `warm_forecast` | Inference faster than cold, pipeline reused | ✅ both (0.06–0.09 s, `pipeline_reused`) |
| 9 | `repeated_forecasts` | 3+ repeated forecasts with stable timing | ✅ both (≥3 warm runs each) |
| 10 | `valid_csv_forecast` | Upload valid CSV, preview + forecast works | ✅ both |
| 11 | `oversized_csv_rejected` | Upload file > 50 MB rejected before parsing | ⚠️ platform-enforced (51 MB rejected client-side by uploader; app event not emitted) |
| 12 | `blank_timestamp_rejected` | CSV with blank timestamps produces user-friendly error | ✅ both |
| 13 | `invalid_timestamp_rejected` | CSV with invalid timestamps produces user-friendly error | ✅ both |
| 14 | `same_column_rejected` | Same timestamp/target column selected is blocked | ✅ both |
| 15 | `context_truncation_visible` | Truncation notice displayed for long context | ✅ both (9000→8192 rows) |
| 16 | `recoverable_failure` | Expected failure + same-adapter retry succeeds | ✅ both lifecycles (genuine `InferenceError` from a non-numeric-target CSV + successful recovery run in the same session) |
| 17 | `configuration_preserved` | App config stays intact after recoverable error | ✅ recorded on genuine error paths that ran (rejections + recoverable failure) |
| 18 | `two_session_concurrency` | Two simultaneous sessions, queue behaviour recorded | ✅ **captured at `dc3046fa`** (Stage A fix re-measured) and **re-captured at `aa290c6f`** (final: sessions `1b0f2b151a87`/`c47deb17f47c`, 336 ms overlap, capacity-1 serialised, 6.434 s queue at dc3046fa, one pipeline, both success) — see `cloud_gate_c/README.md` |
| 19 | `coordinator_timeout_recovery` | Coordinator timeout surfaces as recoverable error | ✅ **re-measured at `aa290c6f`** (queue timeout corrected to a measured-justified 5 s; cold holder held capacity → queued session genuinely reached 5 s timeout → recovered on retry; typed IDs `317f3d11-…` / `3b952e38-…` bound) |

> **Note:** Duplicate-timestamp remediation is Phase 1 work. In Stage 0, malformed
> input produces a user-friendly error without detailed duplicate guidance.
> 
> **Canonical registry:** These 19 test names are defined in `CANONICAL_CLOUD_TESTS` in
> `src/evidence_schemas.py` and shared by schema validation, tests, and the Cloud
> evidence builder.

> **Measurement source (Cloud Diagnostics page):** The deployed app exposes
> a dedicated **Cloud Diagnostics** page (`pages/3_Cloud_Diagnostics.py`)
> that produces a typed, allowlisted runtime-diagnostics snapshot with:
> exact deployed commit + resolution source, package/Python versions, OS,
> CPU model/cores, RAM, `pip check`, CPU-only Torch, NVIDIA-package
> absence, `hf_token_present` boolean, current/process-peak RSS, pipeline
> state, coordinator state, bounded per-request telemetry (with scoped
> per-request memory samples), a deterministic JSON download, and a
> canonical JSON digest.  This is the **only** release-evidence source —
> human-readable UI values and screenshots are **not** sufficient
> evidence (P0: no manual transcription).
>
> **Exact deployed commit:** release collection requires the exact 40-char
> deployed commit (from `?expected_commit=<sha>` on the Cloud Diagnostics
> page).  The page fails closed when the deployed commit cannot be proven
> or does not match the expected collection commit.
>
> **Token sequence:** collect the token-absent lifecycle first (no
> `HF_TOKEN` in Streamlit Secrets, app rebooted), then the token-present
> lifecycle (token added, app rebooted).  Each lifecycle has its own run
> IDs, timestamps, model-load result, and execution receipt; the two paths
> are never simulated from one another.
>
> **No screenshot-only evidence:** screenshots and manually transcribed
> values are treated as insufficient.  Cloud Gate C evidence is built from
> the downloaded typed diagnostics/request/session JSON only.

## Recorded measurements

| Field | Value |
|-------|-------|
| Build result | |
| Package versions | |
| Model ID | `amazon/chronos-2` |
| Configured revision | `29ec3766d36d6f73f0696f85560a422f50e8498c` |
| Resolved revision | |
| Cold load time (s) | |
| Cold peak RSS (MB) | |
| Warm inference time (s) | |
| Warm RSS (MB) | |
| Process peak RSS (MB) | |
| Pipeline construction count | |
| HF_TOKEN present | yes / no |
| Dependency resolver | pip / uv |
| Resource limit exceeded | yes / no |
| App restart occurred | yes / no |
| Sync mode | semaphore / lock / none |
| Timeout result | no_timeout / timeout_occurred / timeout_recovered |
| Concurrency result | |
| Failure recovery result | |
| Configuration preserved after error | yes / no |
| Receipt attestation type | operator_attested |

## Acceptance / rejection

- [x] Dependency install matches CI
- [x] CPU-only Torch confirmed
- [x] Cold start completes within 5 minutes (model load 8.2–8.7 s on this deployment)
- [x] Warm forecast completes within 30 seconds (0.06–0.09 s)
- [x] Peak memory within Community Cloud platform limits (peak RSS 976 MB recorded)
- [x] File upload size limit enforced before parse (platform uploader rejects > 50 MB)
- [x] Same-column mapping blocked
- [x] Errors show user-friendly messages (no stack traces)
- [x] Configuration preserved after recoverable error
- [x] Recoverable failure + retry measured (genuine non-numeric-target `InferenceError` + recovery)
- [x] Two-session concurrency measured at `dc3046fa` and re-captured at `aa290c6f` (isolated sessions, overlapping windows, serialised, one pipeline)
- [x] Coordinator timeout recovery measured at `aa290c6f` (5 s queue timeout, genuine timeout + recovery on retry)

**Decision:** ✅ **PASS — Gate C COMPLETE, Stage 0 complete.** Final collection at
**`aa290c6f`** (measured-justified 5 s queue timeout + `platform_enforced` contract):
**18 of 19 measurements genuinely verified, both token lifecycles on the exact same
deployed commit** (token-absent `5144b8f7-…` 6.31 s model load / token-present
`d18952f4-…` 6.96 s), genuine **two-session concurrency**, genuine **coordinator
timeout recovery (5 s)**, recoverable failure + configuration preservation, all input
validations, context truncation, dependency/pip/CPU-only checks; `oversized_csv_rejected`
**platform-enforced** (rejection-before-parse verified, typed event not emittable —
represented in the contract via `platform_enforced`). Manifest `cloud_summary` populated
with `evidence_cloud_stage0_20260808_130858_484438_4ca8249f.json` (`success=True`,
`evidence_origin=real_measurement`); `verify_evidence_manifest.py` and
`verify_stage0_evidence_readiness.py` pass (exit 0). See
`docs/evidence/cloud_gate_c/README.md` for the full measured-results matrix.

## Administration checkpoints (user-authenticated, exact)

The coding agent cannot authenticate to Streamlit Community Cloud. The
user performs these actions and confirms only non-secret results:

1. **Deployment A (token absent):** sign in → select the app connected to
   `papayasamosa/Forecasting-Tool` → deploy the exact Stage 1 merge commit
   from `main` → ensure `HF_TOKEN` is **absent** from Streamlit Secrets →
   reboot the app → confirm `deployment A restarted` and `HF_TOKEN absent`
   plus the public app URL.
2. **Deployment B (token present):** open app settings → add the read-only
   token as `HF_TOKEN = "..."` → save Secrets → reboot the app → confirm
   `deployment B restarted` and `HF_TOKEN present`.

Never send the token, passwords, email/MFA codes, cookies, or session
tokens through the coding agent.

## PR / merge / post-merge requirements

- Corrective instrumentation, evidence, and ADR PRs are opened and merged
  automatically only after: latest-head CI green, coverage + readiness
  gates passed, review completed on the latest SHA, zero unresolved
  discussions, zero unremediated P0/P1 findings, branch current with
  `main`, no secrets detected, and documentation consistent with the code.
- PR prose is **not** authoritative test evidence — only GitHub workflow
  results and logs are.
- The exact push-to-main workflow run on the merge commit is verified
  separately from the PR's own run before the next stage commences.
