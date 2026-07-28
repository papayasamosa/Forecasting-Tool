#! /usr/bin/env python3
"""Setup script: create venv on D: drive and install deps there.

Run:  python scripts/setup_drive.py
"""
from __future__ import annotations

import os
import subprocess
import sys
import shutil

D_DRIVE = "D:"
VENV_DIR = os.path.join(D_DRIVE, "forecasting-venv")
TEMP_DIR = os.path.join(D_DRIVE, "temp")
PIP_CACHE_DIR = os.path.join(D_DRIVE, "pip-cache")

os.makedirs(TEMP_DIR, exist_ok=True)
os.makedirs(PIP_CACHE_DIR, exist_ok=True)

env = os.environ.copy()
env["TMP"] = TEMP_DIR
env["TEMP"] = TEMP_DIR
env["PIP_CACHE_DIR"] = PIP_CACHE_DIR


def run(cmd: list[str], **kwargs) -> subprocess.CompletedProcedure:
    print(f"Running: {' '.join(cmd)}")
    result = subprocess.run(cmd, capture_output=True, text=True, env=env, **kwargs)
    if result.stdout:
        print(result.stdout[-2000:])
    if result.stderr:
        print(result.stderr[-2000:])
    if result.returncode != 0:
        print(f"ERROR (rc={result.returncode})")
        sys.exit(result.returncode)
    return result


def main():
    # Step 1: Create venv on D: if not exists
    python_exe = sys.executable
    if not os.path.exists(os.path.join(VENV_DIR, "Scripts", "python.exe")):
        print(f"Creating virtual environment at {VENV_DIR} ...")
        run([python_exe, "-m", "venv", VENV_DIR])
    else:
        print(f"Virtual environment already exists at {VENV_DIR}")

    venv_python = os.path.join(VENV_DIR, "Scripts", "python.exe")

    # Step 2: Upgrade pip
    run([venv_python, "-m", "pip", "install", "--upgrade", "pip", "-q"])

    # Step 3: Install torch (CPU)
    run([
        venv_python, "-m", "pip", "install",
        "--no-cache-dir",
        "torch",
        "--index-url", "https://download.pytorch.org/whl/cpu",
    ])

    # Step 4: Install requirements
    requirements = os.path.join(
        os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
        "requirements.txt",
    )
    run([venv_python, "-m", "pip", "install", "--no-cache-dir", "-r", requirements])

    # Verify
    result = run([venv_python, "-c", "import torch; print('torch', torch.__version__)"])
    print(f"\nTorch version: {result.stdout.strip()}")

    result = run([venv_python, "-c", "import chronos; print('chronos', chronos.__version__)"])
    print(f"Chronos version: {result.stdout.strip()}")

    print(f"\n✅ All packages installed in {VENV_DIR}")
    print(f"   Use: {venv_python} to run Python with all dependencies")


if __name__ == "__main__":
    main()
