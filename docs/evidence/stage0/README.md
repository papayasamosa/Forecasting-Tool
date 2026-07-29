# Stage 0 Evidence Artefacts

This directory stores sanitised evidence records from local and Cloud
Stage 0 runs.  No model weights, caches, venv, tokens, credentials,
personal paths or unsanitised logs are committed here.

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
