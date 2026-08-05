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
