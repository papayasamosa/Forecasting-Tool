#! /usr/bin/env python3
"""Verify the local D: drive environment is correctly set up.

Exit code 0 means all checks pass.
"""
from __future__ import annotations

import os
import sys
import platform


REQUIRED_DIRS = [
    r"D:\Forecasting-Tool-Local\venv",
    r"D:\Forecasting-Tool-Local\cache\pip",
    r"D:\Forecasting-Tool-Local\cache\huggingface",
    r"D:\Forecasting-Tool-Local\cache\transformers",
    r"D:\Forecasting-Tool-Local\cache\torch",
    r"D:\Forecasting-Tool-Local\temp",
    r"D:\Forecasting-Tool-Local\test-output",
    r"D:\Forecasting-Tool-Local\benchmarks",
]

REQUIRED_ENV_VARS = {
    "PIP_CACHE_DIR": r"D:\Forecasting-Tool-Local\cache\pip",
    "HF_HOME": r"D:\Forecasting-Tool-Local\cache\huggingface",
    "HUGGINGFACE_HUB_CACHE": r"D:\Forecasting-Tool-Local\cache\huggingface",
    "TRANSFORMERS_CACHE": r"D:\Forecasting-Tool-Local\cache\transformers",
    "TORCH_HOME": r"D:\Forecasting-Tool-Local\cache\torch",
    "TMP": r"D:\Forecasting-Tool-Local\temp",
    "TEMP": r"D:\Forecasting-Tool-Local\temp",
}

REQUIRED_PACKAGES = [
    "torch",
    "chronos",
    "pandas",
    "numpy",
    "streamlit",
    "pyarrow",
]


def main() -> int:
    errors = []

    # --- Python version ---
    py_ver = sys.version_info
    print(f"Python: {sys.version.split()[0]} on {sys.platform}")
    if py_ver.major != 3 or py_ver.minor != 12:
        errors.append(f"Expected Python 3.12, got {py_ver.major}.{py_ver.minor}")

    # --- Platform ---
    if sys.platform != "win32":
        errors.append(f"Expected Windows, got {sys.platform}")

    # --- D: drive ---
    if not os.path.exists("D:"):
        errors.append("D: drive not found")
    else:
        print("D: drive: OK")

    # --- Required directories ---
    for d in REQUIRED_DIRS:
        if os.path.exists(d):
            print(f"  {d}: OK")
        else:
            errors.append(f"Directory missing: {d}")

    # --- Environment variables ---
    for var, expected in REQUIRED_ENV_VARS.items():
        actual = os.environ.get(var, "")
        if actual == expected:
            print(f"  {var}: OK")
        else:
            errors.append(
                f"{var} is '{actual}', expected '{expected}'"
            )

    # --- Packages ---
    for pkg in REQUIRED_PACKAGES:
        try:
            mod = __import__(pkg)
            ver = getattr(mod, "__version__", "unknown")
            print(f"  {pkg}: {ver}")
        except ImportError:
            errors.append(f"Package not installed: {pkg}")

    if errors:
        print(f"\n❌ {len(errors)} error(s):")
        for e in errors:
            print(f"  - {e}")
        return 1
    else:
        print("\n✅ All checks passed")
        return 0


if __name__ == "__main__":
    sys.exit(main())
