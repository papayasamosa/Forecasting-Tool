# Stage 0 Evidence Artefacts

This directory stores sanitised evidence records from local and Cloud
Stage 0 runs.  No model weights, caches, venv, tokens, credentials,
personal paths or unsanitised logs are committed here.

## Invalidated evidence

`evidence_local_stage0_bundle_20260729_162933_791384_10def382.json` (Gate B3,
PR #18) is marked `"status": "invalidated"` in `evidence_manifest.json` and
must **not** be treated as passing Stage 0 release evidence. Its
`runs.token_present_smoke` record is an exact duplicate of
`runs.process_cold_smoke` (identical `started_at_utc`/`completed_at_utc`,
cold/warm timings, and RSS) with only `hf_token_present` and the token-result
objects changed — it is not an independently executed token-present run. The
file is retained unmodified for audit.

## Superseding genuine evidence (Gate B3, 2026-08-05)

`evidence_local_stage0_bundle_20260805_171733_555681_2ce6345f.json` is the
genuine current-head local Stage 0 evidence bundle (commit `7831cb4`), which
supersedes the invalidated PR #18 bundle. It was produced with the hardened
`scripts/chronos2_smoke_test.py` and validated by
`scripts/build_local_stage0_bundle.py`'s duplicate-evidence checks:

- `download_cold_smoke` — genuine first-download run (fresh cache,
  `hf_token_present: false`), distinct run ID
- `process_cold_smoke` — genuine cached-weights run (`hf_token_present:
  false`), distinct run ID
- `token_present_smoke` — genuine independently executed run
  (`hf_token_present: true`, unique `started_at_utc`/`completed_at_utc`,
  unique `run_id`, exact pinned revision) — NOT a duplicate of
  `process_cold_smoke`
- `benchmark` — suite passed (4/4 scenarios, 10/10 rolling folds), strict
  release validation OK
- `model_artifact` — real snapshot inventory (config.json + model.safetensors,
  SHA-256 hashes)
- All five components are bound to typed execution receipts with canonical
  content digests, and the bundle passed `build_local_stage0_bundle.py`
  validation with 0 errors.

The evidence manifest records this bundle and its receipts as the valid
Gate B3 entry.

## Cloud Gate C (collected draft — still pending, do not mark complete)

Cloud Gate C is the sole remaining Stage 0 evidence gate. Genuine Community
Cloud collection has been performed on the deployed app (commits
`c46e586d19c33e3dd4118ca99bbab1f0bc0743d4` / `c7856f06a188a470bea6eee87808d533b34ed394`
and, after the Stage A robustness fix, `dc3046fa2e8c32e3e379000ac68d1f43872a1270`)
and the raw typed bundles/diagnostics are committed under
`docs/evidence/cloud_gate_c/` (see its `README.md` for the full measured-results
matrix and honest status). **Gate C is NOT complete**: the manifest
`cloud_summary` entry stays `null` and no `cloud_stage0` release evidence is
published. Status:

- **16/19** measurements genuinely verified at `c46e586d` / `c7856f06` (both
  token lifecycles on functionally identical code, recoverable failure,
  configuration preservation, all input validations, context truncation).
- **two-session concurrency — re-measured and PROVEN at `dc3046fa`** (Stage A
  fix, PR #37): two isolated browser sessions, overlapping full request
  windows, serialised inference, 6.434 s measured queue time, one pipeline,
  coordinator healthy (typed records retained in
  `docs/evidence/cloud_gate_c/cloud_diagnostics_concurrency_*_dc3046fa.json`).
- **coordinator_timeout_recovery** — not safely inducible under the old
  300 s / 120 s timeouts (max legitimate request measured ~8-9 s cold); queue
  timeout adjusted to a measured-justified 5 s (`src/config.py`); final
  re-measurement scheduled after redeploy.
- **oversized_csv_rejected** — platform-enforced (rejection-before-parse
  verified; typed in-app event not emittable); represented in the canonical
  contract via `platform_enforced` (`PLATFORM_ENFORCED_CLOUD_TESTS`).

The Stage 1 corrective instrumentation added the producer for
genuine Cloud evidence:

- `src/cloud_diagnostics.py` — typed, allowlisted runtime diagnostics;
  exact deployed-commit resolution (40 lowercase hex, fail closed);
  request-scoped memory sampling (never reuses the process-lifetime peak
  as the request peak); bounded per-request telemetry; measured dependency
  diagnostics; token state exposed only as a boolean; typed collection
  session + canonical-digest receipt binding.
- `pages/3_Cloud_Diagnostics.py` — public, read-only diagnostics surface
  with deterministic JSON download, canonical digest, and deliberate
  collection-session begin/finalise controls (no secret input).

Diagnostics are **safe operational metadata**: they never contain the
`HF_TOKEN`, environment-variable values, Streamlit secrets, usernames,
hostnames, home directories, repository paths, uploaded CSV data, target
or forecast values, cookies, or request headers.

Gate C evidence will be built from the downloaded typed JSON only —
screenshots or manually transcribed UI values are not release evidence —
and must prove both token-absent and token-present process lifecycles on
the exact same deployed commit.

## Layout

```
docs/evidence/stage0/
  README.md                          ← this file
  evidence_manifest.json             ← SHA-256 hashes of all sanitised files
  local_no_token_summary.json        ← download-cold / process-cold / warm results (no token)
  local_token_present_summary.json   ← token-present resolution and timings
  cloud_summary.json                 ← Community Cloud results (pending)
```

## File naming convention

- `local_no_token_summary_<date>.json`
- `local_token_present_summary_<date>.json`
- `cloud_summary_<date>.json`

## Evidence schema version

Current version: `1`

Every evidence file includes:

| Field | Description |
|-------|-------------|
| `evidence_schema_version` | Schema version string |
| `code_commit` | Git commit SHA |
| `git_worktree_clean` | Whether the worktree was clean |
| `git_traceability_error` | Sanitised error string if traceability failed |
| `timestamp` | UTC ISO-8601 timestamp |
| `initial_cache_state` | Run-level cache state: `download_cold` or `process_cold_cached_weights` |
| `cold.cache_state` | Per-phase cache state (matches `initial_cache_state` for cold) |
| `warm.cache_state` | Per-phase cache state: `same_process_warm` |
| `configured_revision` | MODEL_REVISION from config |
| `model_revision` | Actual revision loaded |
| `python_version` | Python version |
| `package_versions` | Dict of key package versions |
| `cpu_model` | CPU model string |
| `cpu_logical_cores` | Logical core count |
| `ram_total_gb` | Total system RAM (GB) |

## Do not commit

- Model weights or snapshots
- Pip / conda package caches
- Hugging Face hub caches
- Virtual environments
- HF_TOKEN or any secrets
- Usernames or personal file paths
- Raw psutil or OS logs
- Unsanitised debug dumps
