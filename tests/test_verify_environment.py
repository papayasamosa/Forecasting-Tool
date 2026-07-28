"""Tests for scripts/verify_environment.py's requirements-parsing logic.

These run on any platform/CI (no D: drive, no Windows, no venv required) —
they only exercise the pure parsing function, not the Windows-specific
environment checks in main().
"""
from __future__ import annotations

import importlib.util
import os

import pytest

_SCRIPT_PATH = os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
    "scripts",
    "verify_environment.py",
)


def _load_module():
    spec = importlib.util.spec_from_file_location("verify_environment", _SCRIPT_PATH)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


@pytest.fixture(scope="module")
def verify_environment_module():
    return _load_module()


class TestLoadPinnedVersions:
    def test_returns_non_empty_dict(self, verify_environment_module):
        pins = verify_environment_module._load_pinned_versions()
        assert isinstance(pins, dict)
        assert pins

    def test_known_packages_present(self, verify_environment_module):
        pins = verify_environment_module._load_pinned_versions()
        for pkg in ("streamlit", "pandas", "numpy", "pyarrow", "chronos-forecasting", "torch"):
            assert pkg in pins
            assert pins[pkg]

    def test_pinned_versions_matches_loaded_dict(self, verify_environment_module):
        assert verify_environment_module.PINNED_VERSIONS == (
            verify_environment_module._load_pinned_versions()
        )

    def test_matches_actual_requirements_txt(self, verify_environment_module):
        repo_root = os.path.dirname(os.path.dirname(_SCRIPT_PATH))
        req_path = os.path.join(repo_root, "requirements.txt")
        expected = {}
        with open(req_path, encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line or line.startswith("#") or "==" not in line:
                    continue
                name, _, version = line.partition("==")
                expected[name.strip()] = version.strip()
        assert verify_environment_module._load_pinned_versions() == expected
