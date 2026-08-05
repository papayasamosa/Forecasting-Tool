#! /usr/bin/env python3
r"""Verify the local D: drive environment is correctly set up.

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

# Use the canonical storage_policy module as single source of truth
sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))
from src.storage_policy import REQUIRED_DIRS, REQUIRED_ENV_VARS

REQUIRED_PACKAGES = [
    ("torch", "torch"),
    ("chronos", "chronos-forecasting"),
    ("pandas", "pandas"),
    ("numpy", "numpy"),
    ("streamlit", "streamlit"),
    ("pyarrow", "pyarrow"),
]

def _load_pinned_versions() -> dict[str, str]:
    """Parse direct pins from requirements.txt (single source of truth)."""
    repo_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    req_path = os.path.join(repo_root, "requirements.txt")
    pins: dict[str, str] = {}
    try:
        with open(req_path, encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line or line.startswith("#") or "==" not in line:
                    continue
                name, _, version = line.partition("==")
                pins[name.strip()] = version.strip()
    except OSError:
        pass
    return pins


# Expected pinned versions, read directly from requirements.txt
PINNED_VERSIONS = _load_pinned_versions()


def main() -> int:
    # Make the emoji status output safe on consoles whose codepage cannot
    # encode them (e.g. cp1252): reconfigure stdout so a failure report can
    # never crash with UnicodeEncodeError and mask the real error list.
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")

    errors = []

    # --- WP12: D-drive storage policy enforcement ---
    sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))
    try:
        from src.storage_policy import assert_d_drive_preflight, verify_ddrive_runtime
        d_errors = assert_d_drive_preflight()
        errors.extend(d_errors)
        if not d_errors:
            print("✅ D-drive storage policy: OK")
        # WP3: verify the venv base interpreter is the D-drive project Python
        runtime_errors = verify_ddrive_runtime()
        errors.extend(runtime_errors)
        if runtime_errors:
            for re_ in runtime_errors:
                print(f"  ❌ D-drive runtime: {re_}")
        else:
            print("✅ D-drive runtime base interpreter: OK (based on D-drive project Python)")
    except ImportError as exc:
        errors.append(f"Could not import storage_policy module: {exc}")
    except Exception as exc:
        errors.append(f"D-drive preflight error: {exc}")

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

    # --- Interpreter location ---
    if sys.platform == "win32":
        expected_python = os.path.join(LOCAL_ROOT, "venv", "Scripts", "python.exe")
        actual = os.path.normcase(os.path.abspath(sys.executable))
        expected = os.path.normcase(os.path.abspath(expected_python))
        if actual != expected:
            errors.append(
                f"Running under {sys.executable}, expected the local-root venv "
                f"interpreter at {expected_python}"
            )
        else:
            print(f"Interpreter: {sys.executable} OK (local-root venv)")

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
            # Compare only the PEP 440 release portion -- local version
            # labels like "+cpu" (added by the CPU wheel index) legitimately
            # vary by install source and don't indicate a wrong pin.
            if alias in PINNED_VERSIONS and ver.split("+")[0] != PINNED_VERSIONS[alias]:
                errors.append(
                    f"{alias} version mismatch: got {ver}, expected {PINNED_VERSIONS[alias]}"
                )
            # Check torch is CPU build
            if pkg_name == "torch":
                try:
                    import torch
                    has_cuda_build = torch.version.cuda is not None
                    gpu_available = torch.cuda.is_available()
                    if has_cuda_build or gpu_available:
                        errors.append(
                            f"Non-CPU-only torch detected (cuda build={torch.version.cuda}, "
                            f"cuda.is_available()={gpu_available}); expected the CPU-only wheel"
                        )
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
