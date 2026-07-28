#! /usr/bin/env python3
"""Minimal installer that runs pip in the D: venv without streaming issues."""
from __future__ import annotations

import os
import subprocess
import sys
import time

VENV_PYTHON = r"D:\forecasting-venv\Scripts\python.exe"
TEMP_DIR = r"D:\temp"
PIP_CACHE_DIR = r"D:\pip-cache"
TORCH_INDEX = "https://download.pytorch.org/whl/cpu"

os.makedirs(TEMP_DIR, exist_ok=True)
os.makedirs(PIP_CACHE_DIR, exist_ok=True)

env = os.environ.copy()
env["TMP"] = TEMP_DIR
env["TEMP"] = TEMP_DIR
env["PIP_CACHE_DIR"] = PIP_CACHE_DIR


def run(cmd: list[str], timeout: int = 600) -> None:
    print(f"\n{'='*60}")
    print(f"Running: {' '.join(cmd)}")
    print(f"{'='*60}")
    sys.stdout.flush()
    t0 = time.time()
    result = subprocess.run(
        cmd, capture_output=True, text=True, env=env, timeout=timeout
    )
    elapsed = time.time() - t0
    # Print full output (both stdout and stderr)
    if result.stdout:
        print(result.stdout)
    if result.stderr:
        print(result.stderr)
    print(f"Return code: {result.returncode}  (took {elapsed:.0f}s)")
    if result.returncode != 0:
        sys.exit(result.returncode)


def main():
    if not os.path.exists(VENV_PYTHON):
        # Create venv first
        python = sys.executable
        run([python, "-m", "venv", r"D:\forecasting-venv"], timeout=60)
        print("Virtual environment created.")

    # 1. Upgrade pip
    run([VENV_PYTHON, "-m", "pip", "install", "--upgrade", "pip", "-q"], timeout=60)

    # 2. Install torch CPU
    run([
        VENV_PYTHON, "-m", "pip", "install",
        "torch", "--index-url", TORCH_INDEX,
    ], timeout=900)

    # 3. Install chronos-forecasting
    run([
        VENV_PYTHON, "-m", "pip", "install",
        "chronos-forecasting>=2.2.0",
    ], timeout=600)

    # 4. Install other deps
    req = os.path.join(os.path.dirname(os.path.dirname(__file__)), "requirements.txt")
    run([
        VENV_PYTHON, "-m", "pip", "install",
        "-r", req,
    ], timeout=300)

    # Verify
    print("\n" + "=" * 60)
    print("Verification:")
    for mod in ["torch", "chronos", "pandas", "numpy", "streamlit"]:
        r = subprocess.run(
            [VENV_PYTHON, "-c", f"import {mod}; print({mod}.__version__)"],
            capture_output=True, text=True, timeout=30
        )
        print(f"  {mod}: {r.stdout.strip() or 'FAILED'}")

    print(f"\n✅ Done!")
    print(f"   Venv: {VENV_PYTHON}")


if __name__ == "__main__":
    main()
