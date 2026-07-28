"""Install chronos-forecasting into D: venv."""
import subprocess, sys, os

venv_python = r"D:\forecasting-venv\Scripts\python.exe"
os.environ["TMP"] = r"D:\temp"
os.environ["TEMP"] = r"D:\temp"
os.environ["PIP_CACHE_DIR"] = r"D:\pip-cache"
os.makedirs(r"D:\temp", exist_ok=True)
os.makedirs(r"D:\pip-cache", exist_ok=True)

cmds = [
    [venv_python, "-m", "pip", "install", "chronos-forecasting>=2.2.0"],
    [venv_python, "-m", "pip", "install", "-r",
     os.path.join(os.path.dirname(os.path.dirname(__file__)), "requirements.txt")],
]

for cmd in cmds:
    print(f"\n{'='*60}")
    print(f"Running: {' '.join(cmd)}")
    print(f"{'='*60}")
    sys.stdout.flush()
    result = subprocess.run(cmd, capture_output=True, text=True, timeout=900)
    print(result.stdout[-3000:] if len(result.stdout) > 3000 else result.stdout)
    if result.stderr:
        print(result.stderr[-2000:] if len(result.stderr) > 2000 else result.stderr)
    if result.returncode != 0:
        print(f"FAILED with rc={result.returncode}")
        sys.exit(result.returncode)
    print("OK")

# Verify
print("\n" + "=" * 60)
print("Verification:")
sys.stdout.flush()
for mod_name in ["torch", "chronos", "pandas", "numpy", "streamlit"]:
    r = subprocess.run(
        [venv_python, "-c", f"import {mod_name}; print({mod_name}.__version__)"],
        capture_output=True, text=True, timeout=30
    )
    print(f"  {mod_name}: {r.stdout.strip() or 'FAILED'}")
print("\n✅ All done!")
