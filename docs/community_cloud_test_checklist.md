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

| # | Canonical Test Name | Expected | Actual |
|---|---------------------|----------|--------|
| 1 | `dependency_install` | `pip install -r requirements.txt` succeeds | |
| 2 | `pip_check` | `pip check` passes | |
| 3 | `cpu_only_torch` | `torch.version.cuda is None` | |
| 4 | `no_nvidia_packages` | No NVIDIA/CUDA packages installed | |
| 5 | `token_absent_load` | Model loads without HF_TOKEN (public model) | |
| 6 | `token_present_load` | Model loads with HF_TOKEN | |
| 7 | `cold_forecast` | First forecast completes, model loads within 5 min | |
| 8 | `warm_forecast` | Inference faster than cold, pipeline reused | |
| 9 | `repeated_forecasts` | 3+ repeated forecasts with stable timing | |
| 10 | `valid_csv_forecast` | Upload valid CSV, preview + forecast works | |
| 11 | `oversized_csv_rejected` | Upload file > 50 MB rejected before parsing | |
| 12 | `blank_timestamp_rejected` | CSV with blank timestamps produces user-friendly error | |
| 13 | `invalid_timestamp_rejected` | CSV with invalid timestamps produces user-friendly error | |
| 14 | `same_column_rejected` | Same timestamp/target column selected is blocked | |
| 15 | `context_truncation_visible` | Truncation notice displayed for long context | |
| 16 | `recoverable_failure` | Expected failure + same-adapter retry succeeds | |
| 17 | `configuration_preserved` | App config stays intact after recoverable error | |
| 18 | `two_session_concurrency` | Two simultaneous sessions, queue behaviour recorded | |
| 19 | `coordinator_timeout_recovery` | Coordinator timeout surfaces as recoverable error | |

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
