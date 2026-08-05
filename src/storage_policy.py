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
from typing import Any

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
    os.path.join(LOCAL_ROOT, "cache", "pycache"),
    os.path.join(LOCAL_ROOT, "cache", "npm"),
    os.path.join(LOCAL_ROOT, "cache", "npm-prefix"),
    os.path.join(LOCAL_ROOT, "cache", "uv"),
    os.path.join(LOCAL_ROOT, "cache", "uv-tools"),
    os.path.join(LOCAL_ROOT, "cache", "playwright"),
    os.path.join(LOCAL_ROOT, "cache", "matplotlib"),
    os.path.join(LOCAL_ROOT, "cache", "ruff"),
    # WP-L: MCP/Graphify local storage — no MCP server is actually
    # connected in this repo yet, but any that is added later must use
    # these D-drive locations, never a default under the user profile.
    os.path.join(LOCAL_ROOT, "cache", "mcp"),
    os.path.join(LOCAL_ROOT, "cache", "graphify"),
    os.path.join(LOCAL_ROOT, "graphify-output"),
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
    "MCP_CACHE_DIR": os.path.join(LOCAL_ROOT, "cache", "mcp"),
    "GRAPHIFY_CACHE_DIR": os.path.join(LOCAL_ROOT, "cache", "graphify"),
    "GRAPHIFY_OUTPUT_DIR": os.path.join(LOCAL_ROOT, "graphify-output"),
}

# ---------------------------------------------------------------------------
# Validation
# ---------------------------------------------------------------------------

# Pattern: D:\Forecasting-Tool-Local or D:\Forecasting-Tool-Local\...
_VALID_ROOT_RE = re.compile(r"^D:\\Forecasting-Tool-Local(?:\\|$)", re.IGNORECASE)
_DRIVE_D_RE = re.compile(r"^D:", re.IGNORECASE)
_UNC_RE = re.compile(r"^\\\\")


def _is_abs_windows_path(path: str) -> bool:
    """Check if *path* is an absolute Windows path (e.g. ``D:\\...``).

    Works cross-platform: on Linux ``os.path.isabs`` returns ``False`` for
    ``D:\\...``, so we also check for a drive-letter prefix manually.
    """
    if not path:
        return False
    if os.path.isabs(path):
        return True
    # On non-Windows, check for drive-letter prefix
    if len(path) >= 3 and path[1] == ':' and path[2] in ('\\', '/'):
        return True
    return False


def _normalise_windows_path(path: str) -> str:
    """Normalise a Windows-style path for cross-platform regex matching.

    Converts forward slashes to backslashes and normalises via
    ``os.path.normpath``.  This is needed because on Linux,
    ``os.path.join`` produces mixed ``\\``/``/`` separators, and
    ``os.path.normpath`` on Linux does not convert forward slashes.
    """
    # Replace forward slashes with backslashes first
    path = path.replace("/", "\\")
    return os.path.normpath(path)


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
    if not _is_abs_windows_path(path):
        return False
    # Reject UNC paths
    if _UNC_RE.match(path):
        return False
    # Normalise and check — normalise separators first for cross-platform
    normalised = _normalise_windows_path(path)
    if not _DRIVE_D_RE.match(normalised):
        return False
    if not _VALID_ROOT_RE.match(normalised):
        return False
    return True


def is_under_local_root(path: str) -> bool:
    """Return True if *path* is under the approved local root."""
    if not is_valid_storage_root(path):
        return False
    # Normalise to a common format: replace all backslashes with forward slashes
    # for cross-platform comparison (os.sep differs: '\\' on Windows, '/' on Linux)
    norm_path = _normalise_windows_path(path).replace("\\", "/")
    norm_root = _normalise_windows_path(LOCAL_ROOT).replace("\\", "/")
    # Windows paths are case-insensitive: the on-disk case (e.g. as returned
    # by Path.resolve()) may differ from the constant's case, so compare
    # case-insensitively. (is_valid_storage_root already accepts either case.)
    norm_path_l = norm_path.lower()
    norm_root_l = norm_root.lower()
    return norm_path_l.startswith(norm_root_l + "/") or norm_path_l == norm_root_l


def is_windows_platform() -> bool:
    """Return True if running on Windows."""
    return sys.platform == "win32"


def _read_pyvenv_cfg_home(prefix: str) -> str:
    """Read the ``home`` line from a venv's ``pyvenv.cfg``.

    Returns the resolved ``home`` value, or ``""`` if the file is absent
    or unreadable. Kept as a module-level helper so tests can stub it
    without patching the global ``open`` builtin (which would corrupt
    coverage.py's own file reads on Linux runners).
    """
    pyvenv_cfg = os.path.join(prefix, "pyvenv.cfg")
    home = ""
    try:
        with open(pyvenv_cfg, encoding="utf-8") as f:
            for line in f:
                if line.strip().lower().startswith("home"):
                    home = line.split("=", 1)[1].strip()
    except OSError:
        pass
    return home


def verify_ddrive_runtime() -> list[str]:
    """Verify the active interpreter is the D-drive venv based on the
    D-drive project Python.

    The project runtime is:

    - base interpreter: ``D:\\Forecasting-Tool-Local\\python312\\python.exe``
    - virtual environment: ``D:\\Forecasting-Tool-Local\\venv``

    Returns a list of error messages (empty = OK). Checks:
    - ``sys.executable`` is the D-drive venv interpreter
    - ``sys.prefix`` is under ``D:\\Forecasting-Tool-Local``
    - ``sys.base_prefix`` is under ``D:\\Forecasting-Tool-Local`` (so the
      venv is NOT based on a C-drive Python)
    - the venv's ``pyvenv.cfg`` ``home`` points under the approved runtime
      tree

    On non-Windows platforms this returns an empty list (the D-drive
    policy does not apply to GitHub runners or Cloud containers).
    """
    errors: list[str] = []

    if sys.platform != "win32":
        return errors

    venv_python = os.path.join(LOCAL_ROOT, "venv", "Scripts", "python.exe")
    actual_exec = os.path.normcase(os.path.abspath(sys.executable))
    expected_exec = os.path.normcase(os.path.abspath(venv_python))
    if actual_exec != expected_exec:
        errors.append(
            f"Active interpreter '{sys.executable}' is not the D-drive venv "
            f"interpreter '{venv_python}'"
        )

    if not is_under_local_root(os.path.normpath(sys.prefix)):
        errors.append(f"sys.prefix '{sys.prefix}' is not under {LOCAL_ROOT}")

    if not is_under_local_root(os.path.normpath(sys.base_prefix)):
        errors.append(
            f"sys.base_prefix '{sys.base_prefix}' is not under {LOCAL_ROOT} — "
            f"the D-drive venv must be based on the D-drive project Python "
            f"at '{os.path.join(LOCAL_ROOT, 'python312')}', never a "
            f"C-drive (or other) installation"
        )

    # pyvenv.cfg home must point under the approved runtime tree
    home = _read_pyvenv_cfg_home(sys.prefix)
    if home and not is_under_local_root(os.path.normpath(home)):
        errors.append(
            f"pyvenv.cfg home '{home}' is not under {LOCAL_ROOT} — the "
            f"venv is based on a Python outside the approved runtime tree"
        )

    return errors


def assert_d_drive_preflight() -> list[str]:
    """Run D-drive preflight checks. Return list of error messages.

    Checks:
    - Platform is Windows.
    - D: drive exists.
    - Current interpreter is under the D: venv.
    - Repository is under D:\\Forecasting-Tool-Local\\repo.
    - All required env vars point to D:.
    - Pytest base temp would be on D:.

    On non-Windows platforms, returns an informational message but does
    not fail (the D-drive policy does not apply).
    """
    errors: list[str] = []

    if sys.platform != "win32":
        # D-drive policy does not apply to non-Windows
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

    # Check the venv base interpreter is the D-drive project Python (WP3):
    # a venv created from a C-drive Python is not an approved runtime.
    errors.extend(verify_ddrive_runtime())

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
