"""List installed packages in D: venv."""
import subprocess, os

os.environ["TMP"] = r"D:\temp"
os.environ["TEMP"] = r"D:\temp"
venv = r"D:\forecasting-venv\Scripts\python.exe"

r = subprocess.run([venv, "-m", "pip", "list", "--format=columns"], capture_output=True, text=True, timeout=60)
print(r.stdout)

# Also test each import
print("\n--- Import tests ---")
for mod in ["torch", "chronos", "pandas", "numpy", "streamlit", "psutil"]:
    r2 = subprocess.run([venv, "-c", f"import {mod}; print({mod}.__version__)"], capture_output=True, text=True, timeout=15)
    print(f"  {mod}: {r2.stdout.strip() or 'FAILED: ' + r2.stderr.strip()[:60]}")
