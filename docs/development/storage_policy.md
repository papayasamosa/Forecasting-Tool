# D-Drive Storage Policy

## Purpose

All project-related local installations, repositories, virtual environments,
package caches, model files, installers, downloads, temporary files, browser
binaries, test output, benchmark output, logs and evidence-working files
must be on the **D: drive** under `D:\Forecasting-Tool-Local`.

This applies to **local Windows work only**. GitHub-hosted Linux runners and
Streamlit Community Cloud containers are exempt.

## Policy

### Required root

```
D:\Forecasting-Tool-Local
```

### Required locations

```
D:\Forecasting-Tool-Local\repo
D:\Forecasting-Tool-Local\python312
D:\Forecasting-Tool-Local\installers
D:\Forecasting-Tool-Local\downloads
D:\Forecasting-Tool-Local\venv
D:\Forecasting-Tool-Local\cache
D:\Forecasting-Tool-Local\temp
D:\Forecasting-Tool-Local\temp\pytest
D:\Forecasting-Tool-Local\test-output
D:\Forecasting-Tool-Local\benchmarks
D:\Forecasting-Tool-Local\evidence-work
D:\Forecasting-Tool-Local\logs
```

### Required environment variables

| Variable | Value |
|---|---|
| `FORECASTING_LOCAL_ROOT` | `D:\Forecasting-Tool-Local` |
| `PIP_CACHE_DIR` | `D:\Forecasting-Tool-Local\cache\pip` |
| `HF_HOME` | `D:\Forecasting-Tool-Local\cache\huggingface` |
| `HUGGINGFACE_HUB_CACHE` | `D:\Forecasting-Tool-Local\cache\huggingface` |
| `HF_HUB_CACHE` | `D:\Forecasting-Tool-Local\cache\huggingface\hub` |
| `HF_XET_CACHE` | `D:\Forecasting-Tool-Local\cache\huggingface\xet` |
| `TRANSFORMERS_CACHE` | `D:\Forecasting-Tool-Local\cache\transformers` |
| `TORCH_HOME` | `D:\Forecasting-Tool-Local\cache\torch` |
| `TMP` | `D:\Forecasting-Tool-Local\temp` |
| `TEMP` | `D:\Forecasting-Tool-Local\temp` |
| `PYTHONPYCACHEPREFIX` | `D:\Forecasting-Tool-Local\cache\pycache` |
| `XDG_CACHE_HOME` | `D:\Forecasting-Tool-Local\cache` |
| `NPM_CONFIG_CACHE` | `D:\Forecasting-Tool-Local\cache\npm` |
| `NPM_CONFIG_PREFIX` | `D:\Forecasting-Tool-Local\cache\npm-prefix` |
| `UV_CACHE_DIR` | `D:\Forecasting-Tool-Local\cache\uv` |
| `UV_TOOL_DIR` | `D:\Forecasting-Tool-Local\cache\uv-tools` |
| `UV_PYTHON_INSTALL_DIR` | `D:\Forecasting-Tool-Local\python312` |
| `PLAYWRIGHT_BROWSERS_PATH` | `D:\Forecasting-Tool-Local\cache\playwright` |
| `MPLCONFIGDIR` | `D:\Forecasting-Tool-Local\cache\matplotlib` |
| `RUFF_CACHE_DIR` | `D:\Forecasting-Tool-Local\cache\ruff` |

### Validation rules

- Accept only `D:\Forecasting-Tool-Local` or descendants.
- Reject C:, other drives, UNC paths and relative paths.
- Activation validates before changing environment variables.
- Verification explicitly requires D:.
- Active interpreter is the D-drive venv.
- Repository is under `D:\Forecasting-Tool-Local\repo`.
- Every required local cache variable points to D:.
- Pytest base temp points to D:.
- Python installer and runtime instructions use D:.
- No silent fallback to system Python.
- No model download before preflight passes.

### Enforcement

The policy is enforced by:

- `src/storage_policy.py` — Python module with validation functions.
- `scripts/setup_local_windows.ps1` — Setup script (checks drive).
- `scripts/activate_local_windows.ps1` — Activation script (validates before change).
- `scripts/verify_environment.py` — Verification script (calls shared module).

### Exceptions

A Windows component may remain on C: only when:
1. The operating system or installer strictly requires it, AND
2. No supported redirect exists.

Each exception must be documented before proceeding.
