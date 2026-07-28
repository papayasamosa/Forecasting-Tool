"""Install dev dependencies and verify all packages in D: venv."""
import subprocess, os, sys

os.environ["TMP"] = r"D:\temp"
os.environ["TEMP"] = r"D:\temp"
os.environ["PIP_CACHE_DIR"] = r"D:\pip-cache"
venv = r"D:\forecasting-venv\Scripts\python.exe"

pkgs = ["psutil>=5.9", "matplotlib>=3.7", "pytest>=8.0", "pytest-cov>=5.0"]
for pkg in pkgs:
    print(f"Installing {pkg}...", flush=True)
    r = subprocess.run(
        [venv, "-m", "pip", "install", pkg],
        capture_output=True, text=True, timeout=120,
    )
    if r.returncode != 0:
        print(f"  FAILED: {r.stderr[:300]}")
    else:
        print("  OK", flush=True)

print("\nVerifying all packages:")
for mod in ["torch", "chronos", "pandas", "numpy", "streamlit", "matplotlib", "pytest", "psutil"]:
    r = subprocess.run(
        [venv, "-c", f"import {mod}; print({mod}.__version__)"],
        capture_output=True, text=True, timeout=15,
    )
    ver = r.stdout.strip() or r.stderr.strip()[:60]
    print(f"  {mod}: {ver}")

print("\n✅ All done!")
