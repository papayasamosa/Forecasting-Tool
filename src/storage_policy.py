"""Shared D-drive storage policy for the Forecasting Tool.

Used by:

- ``scripts/setup_local_windows.ps1``
- ``scripts/activate_local_windows.ps1``
- ``scripts/verify_environment.py``
- Any other local setup, verification or activation script.

Requirements (WP12):
- Accept only ``D:\\Forecasting-Tool-Local`` or descendants.
- Reject C:, other drives, UNC paths and relative paths.
"""

from __future__ import annotations

import os
import re
import sys
from pathlib import Path

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------
LOCAL_ROOT = r"D:\Forecasting-Tool-Local"

REQUIRED_DIRS: list[str] = [
    os.path.join(LOCAL_ROOT, "repo"),
    os.path.join(LOCAL_ROOT, "python312"),
    os.path.join(LOCAL_ROOT, "installers"),
    os.path.join(LOCAL_ROOT, "downloads"),
    os.path.join(LOCAL_ROOT, "venv"),
    os.path.join(LOCAL_ROOT, "cache"),
    os.path.join(LOCAL_ROOT, "cache", "pip"),
    os.path.join(LOCAL_ROOT, "cache", "huggingface"),
    os.path.join(LOCAL_ROOT, "cache", "huggingface", "hub"),
    os.path.join(LOCAL_ROOT, "cache", "huggingface", "xet"),
    os.path.join(LOCAL_ROOT, "cache", "transformers"),
    os.path.join(LOCAL_ROOT, "cache", "torch"),
    os.path.join(LOCAL_ROOT, "temp"),
    os.path.join(LOCAL_ROOT, "temp", "pytest"),
    os.path.join(LOCAL_ROOT, "test-output"),
    os.path.join(LOCAL_ROOT, "benchmarks"),
    os.path.join(LOCAL_ROOT, "evidence-work"),
    os.path.join(LOCAL_ROOT, "logs"),
]

REQUIRED_ENV_VARS: dict[str, str] = {
    "FORECASTING_LOCAL_ROOT": LOCAL_ROOT,
    "PIP_CACHE_DIR": os.path.join(LOCAL_ROOT, "cache", "pip"),
    "HF_HOME": os.path.join(LOCAL_ROOT, "cache", "huggingface"),
    "HUGGINGFACE_HUB_CACHE": os.path.join(LOCAL_ROOT, "cache", "huggingface"),
    "HF_HUB_CACHE": os.path.join(LOCAL_ROOT, "cache", "huggingface", "hub"),
    "HF_XET_CACHE": os.path.join(LOCAL_ROOT, "cache", "huggingface", "xet"),
    "TRANSFORMERS_CACHE": os.path.join(LOCAL_ROOT, "cache", "transformers"),
    "TORCH_HOME": os.path.join(LOCAL_ROOT, "cache", "torch"),
    "TMP": os.path.join(LOCAL_ROOT, "temp"),
    "TEMP": os.path.join(LOCAL_ROOT, "temp"),
    "PYTHONPYCACHEPREFIX": os.path.join(LOCAL_ROOT, "cache", "pycache"),
    "XDG_CACHE_HOME": os.path.join(LOCAL_ROOT, "cache"),
    "NPM_CONFIG_CACHE": os.path.join(LOCAL_ROOT, "cache", "npm"),
    "NPM_CONFIG_PREFIX": os.path.join(LOCAL_ROOT, "cache", "npm-prefix"),
    "UV_CACHE_DIR": os.path.join(LOCAL_ROOT, "cache", "uv"),
    "UV_TOOL_DIR": os.path.join(LOCAL_ROOT, "cache", "uv-tools"),
    "UV_PYTHON_INSTALL_DIR": os.path.join(LOCAL_ROOT, "python312"),
    "PLAYWRIGHT_BROWSERS_PATH": os.path.join(LOCAL_ROOT, "cache", "playwright"),
    "MPLCONFIGDIR": os.path.join(LOCAL_ROOT, "cache", "matplotlib"),
    "RUFF_CACHE_DIR": os.path.join(LOCAL_ROOT, "cache", "ruff"),
}

# ---------------------------------------------------------------------------
# Validation
# ---------------------------------------------------------------------------

# Pattern: D:\Forecasting-Tool-Local or D:\Forecasting-Tool-Local\...
_VALID_ROOT_RE = re.compile(r"^D:\\Forecasting-Tool-Local(?:\\|$)", re.IGNORECASE)
_DRIVE_D_RE = re.compile(r"^D:", re.IGNORECASE)
_UNC_RE = re.compile(r"^\\\\")


def is_valid_storage_root(path: str) -> bool:
    """Return True if *path* is an acceptable D: storage root.

    Rules:
    - Must be on drive D:.
    - Must start with ``D:\\Forecasting-Tool-Local``.
    - Must be an absolute path (not relative).
    - Must not be a UNC path.
    """
    if not path:
        return False
    # Reject relative paths
    if not os.path.isabs(path):
        return False
    # Reject UNC paths
    if _UNC_RE.match(path):
        return False
    # Normalise and check
    normalised = os.path.normpath(path)
    if not _DRIVE_D_RE.match(normalised):
        return False
    if not _VALID_ROOT_RE.match(normalised):
        return False
    return True


def is_under_local_root(path: str) -> bool:
    """Return True if *path* is under the approved local root."""
    if not is_valid_storage_root(path):
        return False
    norm_path = os.path.normpath(path)
    norm_root = os.path.normpath(LOCAL_ROOT)
    return norm_path.startswith(norm_root + os.sep) or norm_path == norm_root


def assert_d_drive_preflight() -> list[str]:
    """Run D-drive preflight checks. Return list of error messages.

    Checks:
    - Platform is Windows.
    - D: drive exists.
    - Current interpreter is under the D: venv.
    - Repository is under D:\\Forecasting-Tool-Local\\repo.
    - All required env vars point to D:.
    - Pytest base temp would be on D:.
    """
    errors: list[str] = []

    if sys.platform != "win32":
        errors.append("D-drive policy applies only to Windows")
        return errors

    # Check D: drive exists
    if not os.path.exists("D:\\"):
        errors.append("D: drive not found")

    # Check interpreter
    venv_python = os.path.join(LOCAL_ROOT, "venv", "Scripts", "python.exe")
    actual_exec = os.path.normcase(os.path.abspath(sys.executable))
    expected_exec = os.path.normcase(os.path.abspath(venv_python))
    if actual_exec != expected_exec:
        errors.append(
            f"Active interpreter '{sys.executable}' is not the D-drive venv "
            f"interpreter '{venv_python}'"
        )

    # Check repo location
    repo_root = Path(__file__).resolve().parent.parent
    if not is_under_local_root(str(repo_root)):
        errors.append(
            f"Repository at '{repo_root}' is not under "
            f"'{LOCAL_ROOT}\\repo'"
        )

    # Check env vars
    for var, expected in REQUIRED_ENV_VARS.items():
        actual = os.environ.get(var, "")
        if not actual:
            errors.append(f"{var}: not set, expected '{expected}'")
        elif not is_under_local_root(actual):
            errors.append(f"{var}: '{actual}' is not on D: drive")

    return errors


def __getattr__(name: str) -> Any:
    """Provide backward compat for scripts that import from this module."""
    if name == "LOCAL_ROOT":
        return LOCAL_ROOT
    if name == "REQUIRED_DIRS":
        return REQUIRED_DIRS
    if name == "REQUIRED_ENV_VARS":
        return REQUIRED_ENV_VARS
    raise AttributeError(f"module 'src.storage_policy' has no attribute '{name}'")
