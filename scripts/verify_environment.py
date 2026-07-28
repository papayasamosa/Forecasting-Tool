#! /usr/bin/env python3
"""Verify the local D: drive environment is correctly set up.

Checks can be customised via environment variables:
  FORECASTING_LOCAL_ROOT — root directory (default: D:\Forecasting-Tool-Local)

Exit code 0 means all checks pass.
"""
from __future__ import annotations

import os
import sys
import subprocess


LOCAL_ROOT = os.environ.get(
    "FORECASTING_LOCAL_ROOT",
    r"D:\Forecasting-Tool-Local",
)

REQUIRED_DIRS = [
    os.path.join(LOCAL_ROOT, "venv"),
    os.path.join(LOCAL_ROOT, "cache", "pip"),
    os.path.join(LOCAL_ROOT, "cache", "huggingface"),
    os.path.join(LOCAL_ROOT, "cache", "transformers"),
    os.path.join(LOCAL_ROOT, "cache", "torch"),
    os.path.join(LOCAL_ROOT, "temp"),
    os.path.join(LOCAL_ROOT, "test-output"),
    os.path.join(LOCAL_ROOT, "benchmarks"),
]

REQUIRED_ENV_VARS = {
    "PIP_CACHE_DIR": os.path.join(LOCAL_ROOT, "cache", "pip"),
    "HF_HOME": os.path.join(LOCAL_ROOT, "cache", "huggingface"),
    "HUGGINGFACE_HUB_CACHE": os.path.join(LOCAL_ROOT, "cache", "huggingface"),
    "TRANSFORMERS_CACHE": os.path.join(LOCAL_ROOT, "cache", "transformers"),
    "TORCH_HOME": os.path.join(LOCAL_ROOT, "cache", "torch"),
    "TMP": os.path.join(LOCAL_ROOT, "temp"),
    "TEMP": os.path.join(LOCAL_ROOT, "temp"),
}

REQUIRED_PACKAGES = [
    ("torch", "torch"),
    ("chronos", "chronos-forecasting"),
    ("pandas", "pandas"),
    ("numpy", "numpy"),
    ("streamlit", "streamlit"),
    ("pyarrow", "pyarrow"),
]

# Expected pinned versions (from requirements.txt)
PINNED_VERSIONS = {
    "streamlit": "1.60.0",
    "pandas": "3.0.5",
    "numpy": "2.4.6",
    "pyarrow": "24.0.0",
    "chronos-forecasting": "2.3.1",
    "torch": "2.13.0",
}


def main() -> int:
    errors = []

    # --- Python version ---
    py_ver = sys.version_info
    print(f"Python: {sys.version.split()[0]} on {sys.platform}")
    if py_ver.major != 3 or py_ver.minor != 12:
        errors.append(f"Expected Python 3.12, got {py_ver.major}.{py_ver.minor}")

    # --- Platform ---
    if sys.platform != "win32":
        print("  (not Windows — some Windows-specific checks skipped)")

    # --- Local root ---
    if sys.platform == "win32":
        root_drive = os.path.splitdrive(LOCAL_ROOT)[0] + os.sep
        if not os.path.exists(root_drive):
            errors.append(f"Drive not found: {root_drive}")
        else:
            print(f"Root drive: {root_drive} OK")
    else:
        print(f"Local root: {LOCAL_ROOT}")

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
            if sys.platform == "win32":
                errors.append(
                    f"{var} is '{actual}', expected '{expected}'"
                )
            else:
                print(f"  {var}: '{actual}' (not Windows — expected '{expected}' but may differ)")

    # --- Packages ---
    for pkg_name, alias in REQUIRED_PACKAGES:
        try:
            mod = __import__(pkg_name)
            ver = getattr(mod, "__version__", "unknown")
            print(f"  {alias}: {ver}")
            if alias in PINNED_VERSIONS and ver != PINNED_VERSIONS[alias]:
                errors.append(
                    f"{alias} version mismatch: got {ver}, expected {PINNED_VERSIONS[alias]}"
                )
            # Check torch is CPU build
            if pkg_name == "torch":
                try:
                    if hasattr(mod, "_C") and hasattr(mod._C, "_get_cpu_capability"):
                        pass  # PyTorch C extension available
                    import torch
                    if torch.cuda.is_available():
                        print("    (CUDA available — expected CPU-only)")
                    else:
                        print("    (CPU-only build)")
                except Exception:
                    print("    (CPU — CUDA check unavailable)")
        except ImportError:
            errors.append(f"Package not installed: {alias}")

    # --- pip check ---
    try:
        result = subprocess.run(
            [sys.executable, "-m", "pip", "check"],
            capture_output=True, text=True, timeout=30,
        )
        if result.returncode == 0:
            print("  pip check: OK")
        else:
            errors.append(f"pip check failed:\n{result.stdout[:500]}{result.stderr[:500]}")
    except Exception as e:
        errors.append(f"pip check error: {e}")

    # --- Torch CPU check ---
    try:
        import torch
        t = torch.tensor([1.0, 2.0, 3.0])
        r = t + t
        assert r.sum().item() == 12.0, "Torch basic operation failed"
        print("  Torch CPU: OK (basic tensor ops work)")
    except Exception as e:
        errors.append(f"Torch CPU check failed: {e}")

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
