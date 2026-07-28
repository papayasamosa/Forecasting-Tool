#! /usr/bin/env python3
"""Install all dependencies into the D: drive virtual environment."""
from __future__ import annotations

import os
import subprocess
import sys

VENV_PYTHON = r"D:\forecasting-venv\Scripts\python.exe"
PROJECT_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
REQUIREMENTS = os.path.join(PROJECT_DIR, "requirements.txt")
TEMP_DIR = r"D:\temp"
PIP_CACHE_DIR = r"D:\pip-cache"

os.makedirs(TEMP_DIR, exist_ok=True)
os.makedirs(PIP_CACHE_DIR, exist_ok=True)

env = os.environ.copy()
env["TMP"] = TEMP_DIR
env["TEMP"] = TEMP_DIR
env["PIP_CACHE_DIR"] = PIP_CACHE_DIR


def run(cmd: list[str], timeout: int | None = None) -> None:
    print(f"\n--- Running: {' '.join(cmd)} ---")
    sys.stdout.flush()
    result = subprocess.run(
        cmd, capture_output=True, text=True, env=env, timeout=timeout
    )
    # Print last 1000 chars of stdout
    if result.stdout:
        out = result.stdout.strip()
        if len(out) > 1000:
            out = out[-1000:]
        print(out)
    if result.stderr:
        err = result.stderr.strip()
        if len(err) > 1000:
            err = err[-1000:]
        print(err)
    if result.returncode != 0:
        print(f"ERROR (rc={result.returncode})")
        sys.exit(result.returncode)


def main():
    # Verify venv
    if not os.path.exists(VENV_PYTHON):
        print(f"ERROR: {VENV_PYTHON} not found. Run setup_drive.py first.")
        sys.exit(1)

    print(f"Using venv: {VENV_PYTHON}")

    # Step 1: Upgrade pip
    run([VENV_PYTHON, "-m", "pip", "install", "--upgrade", "pip", "-q"], timeout=60)

    # Step 2: Install torch (CPU) - big download
    print("\n=== Installing torch (CPU) ===")
    run([
        VENV_PYTHON, "-m", "pip", "install", "--no-cache-dir",
        "torch",
        "--index-url", "https://download.pytorch.org/whl/cpu",
    ], timeout=600)

    # Verify torch
    result = subprocess.run(
        [VENV_PYTHON, "-c", "import torch; print(torch.__version__)"],
        capture_output=True, text=True, timeout=30
    )
    print(f"  torch version: {result.stdout.strip()}")

    # Step 3: Install chronos-forecasting and other deps
    print("\n=== Installing chronos-forecasting and other dependencies ===")
    run([
        VENV_PYTHON, "-m", "pip", "install", "--no-cache-dir",
        "chronos-forecasting>=2.2.0",
    ], timeout=600)

    # Step 4: Install remaining requirements
    print(f"\n=== Installing from {REQUIREMENTS} ===")
    run([
        VENV_PYTHON, "-m", "pip", "install", "--no-cache-dir",
        "-r", REQUIREMENTS,
    ], timeout=300)

    # Verify
    for mod_name in ["torch", "chronos", "pandas", "numpy", "streamlit"]:
        result = subprocess.run(
            [VENV_PYTHON, "-c", f"import {mod_name}; print({mod_name}.__version__)"],
            capture_output=True, text=True, timeout=15
        )
        ver = result.stdout.strip() or "FAILED"
        print(f"  {mod_name}: {ver}")

    print(f"\n✅ All packages installed in {VENV_PYTHON}")
    print(f"   To run tests: {VENV_PYTHON} -m pytest tests/ -v")
    print(f"   To run smoke test: {VENV_PYTHON} scripts/chronos2_smoke_test.py")
    print(f"   To run Streamlit: {VENV_PYTHON} -m streamlit run app.py")


if __name__ == "__main__":
    main()
