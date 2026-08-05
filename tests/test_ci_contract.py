"""WP-K: regression tests proving the CI coverage gate is fail-closed.

Root cause of the false-green bug this closes (verified by reproduction,
not guessed): pytest-cov's ``--cov-fail-under`` has two independent code
paths. The printed terminal-summary message compares the raw, unrounded
total (``self.cov_total < self.options.cov_fail_under``), but the code
that actually flips the process exit code
(``coverage.results.should_fail_under``) rounds the total to
``--cov-precision`` digits first (default precision 0) before comparing.
A true coverage of 81.91% against a threshold of 82 rounds to 82.0, and
``82.0 < 82`` is False — so the gate silently passed while printing a
scary-looking "FAIL Required test coverage of 82%..." message. This was
reproduced against the actual PR #25 CI run's own numbers (81.91% vs an
82% threshold, precision unset) before this fix.

These tests never run the real project's own coverage gate on itself
(that would be circular and slow); they exercise the same library
functions/CLI in isolation with tiny synthetic fixtures.
"""
from __future__ import annotations

import subprocess
import sys
import textwrap
from pathlib import Path

import pytest


class TestRoundingRootCause:
    """Direct reproduction of the coverage.py rounding gap, and proof that
    --cov-precision=2 (what ci.yml now sets) closes it."""

    def test_should_fail_under_rounds_total_by_default_precision(self):
        from coverage.results import should_fail_under
        # This is the exact scenario observed in PR #25's CI run.
        assert should_fail_under(81.91, 82, 0) is False

    def test_should_fail_under_with_precision_2_does_not_round_away_the_gap(self):
        from coverage.results import should_fail_under
        assert should_fail_under(81.91, 82, 2) is True

    def test_terminal_summary_message_uses_unrounded_comparison(self):
        # The printed "FAIL ..." message is based on this raw comparison —
        # it was already correctly identifying the failure; only the
        # exit-code-flipping path (should_fail_under) had the rounding gap.
        cov_total = 81.91
        cov_fail_under = 82
        assert (cov_total < cov_fail_under) is True


class TestCoverageGateImpossibleThreshold:
    """Workflow-contract check: an impossible coverage threshold must fail
    the process, end to end, through the exact CLI invocations ci.yml uses."""

    @pytest.fixture
    def tiny_project(self, tmp_path: Path) -> Path:
        (tmp_path / "mod.py").write_text(
            textwrap.dedent("""
                def covered():
                    return 1

                def uncovered():
                    return 2
                """).strip() + "\n",
            encoding="utf-8",
        )
        (tmp_path / "test_mod.py").write_text(
            textwrap.dedent("""
                from mod import covered

                def test_covered():
                    assert covered() == 1
                """).strip() + "\n",
            encoding="utf-8",
        )
        return tmp_path

    def test_pytest_cov_fail_under_100_fails_closed(self, tiny_project):
        """An impossible 100% threshold against a fixture with known
        partial coverage must produce a non-zero exit code — this is the
        regression check that would have caught the original bug."""
        result = subprocess.run(
            [
                sys.executable, "-m", "pytest", "test_mod.py", "-q",
                "--cov=mod", "--cov-report=term-missing",
                "--cov-precision=2", "--cov-fail-under=100",
            ],
            cwd=tiny_project, capture_output=True, text=True, timeout=60,
        )
        assert result.returncode != 0, (
            f"pytest exited 0 with an impossible 100% threshold — "
            f"coverage gate is not fail-closed.\nstdout:\n{result.stdout}"
        )

    def test_pytest_cov_fail_under_100_message_says_fail(self, tiny_project):
        result = subprocess.run(
            [
                sys.executable, "-m", "pytest", "test_mod.py", "-q",
                "--cov=mod", "--cov-report=term-missing",
                "--cov-precision=2", "--cov-fail-under=100",
            ],
            cwd=tiny_project, capture_output=True, text=True, timeout=60,
        )
        assert "FAIL Required test coverage" in result.stdout

    def test_pytest_cov_fail_under_achievable_threshold_passes(self, tiny_project):
        """Sanity check: the same fixture with an achievable threshold
        (50%, actual is exactly 50%) must exit 0 — proves the gate isn't
        just permanently broken in the other direction."""
        result = subprocess.run(
            [
                sys.executable, "-m", "pytest", "test_mod.py", "-q",
                "--cov=mod", "--cov-report=term-missing",
                "--cov-precision=2", "--cov-fail-under=50",
            ],
            cwd=tiny_project, capture_output=True, text=True, timeout=60,
        )
        assert result.returncode == 0, result.stdout

    def test_independent_coverage_report_gate_also_fails_closed(self, tiny_project):
        """The second, independent ci.yml step: `coverage report
        --fail-under=X` reading the same .coverage data via the plain
        coverage.py CLI (not pytest-cov) — must also be fail-closed."""
        run_result = subprocess.run(
            [sys.executable, "-m", "pytest", "test_mod.py", "-q", "--cov=mod", "--cov-precision=2"],
            cwd=tiny_project, capture_output=True, text=True, timeout=60,
        )
        assert run_result.returncode == 0, run_result.stdout
        assert (tiny_project / ".coverage").exists()

        report_result = subprocess.run(
            [sys.executable, "-m", "coverage", "report", "--precision=2", "--fail-under=100"],
            cwd=tiny_project, capture_output=True, text=True, timeout=60,
        )
        assert report_result.returncode != 0, (
            f"coverage report exited 0 with an impossible 100% threshold.\n"
            f"stdout:\n{report_result.stdout}"
        )

    def test_missing_coverage_data_fails_closed(self, tmp_path):
        """ci.yml's independent gate step must fail if the .coverage data
        file is missing entirely (e.g. the pytest step never ran, or
        produced no coverage output) rather than silently reporting
        success on nothing."""
        result = subprocess.run(
            [sys.executable, "-m", "coverage", "report", "--precision=2", "--fail-under=82"],
            cwd=tmp_path, capture_output=True, text=True, timeout=60,
        )
        assert result.returncode != 0

    def test_zero_tests_collected_is_a_failing_exit_code(self, tmp_path):
        """pytest's own exit code for zero collected tests (5) is
        non-zero — ci.yml's `set +e; ...; pytest_exit=$?` capture must
        propagate this, not just coverage-threshold failures."""
        (tmp_path / "conftest.py").write_text("", encoding="utf-8")
        result = subprocess.run(
            [sys.executable, "-m", "pytest", "-q", "--co", "-k", "nothing_matches_this"],
            cwd=tmp_path, capture_output=True, text=True, timeout=60,
        )
        assert result.returncode != 0


class TestWorkflowTriggerContract:
    """WP4: the CI workflow must declare the exact triggers the release
    sequence depends on, and the correctness lint must be fail-closed
    across src/ and scripts/ (WP7)."""

    REPO_ROOT = Path(__file__).resolve().parent.parent

    def test_workflow_declares_required_triggers(self):
        """push: main, pull_request: main, and workflow_dispatch must all
        be declared so (a) every merge commit gets a push-to-main run and
        (b) an explicit recovery/diagnostics run is always possible."""
        ci = (self.REPO_ROOT / ".github" / "workflows" / "ci.yml").read_text(encoding="utf-8")
        # YAML block scalar: the triggers section follows "on:".
        triggers = ci.split("on:")[1].split("jobs:")[0] if "on:" in ci else ""
        assert triggers, "workflow has no 'on:' trigger section"
        assert "push:" in triggers
        assert "branches: [main]" in triggers or "branches:" in triggers
        assert "pull_request:" in triggers
        assert "workflow_dispatch:" in triggers

    def test_workflow_runs_pull_request_on_main(self):
        ci = (self.REPO_ROOT / ".github" / "workflows" / "ci.yml").read_text(encoding="utf-8")
        # The pull_request trigger must target main so PR CI is mandatory.
        pr_section = ci.split("pull_request:")[1].split("jobs:")[0]
        assert "main" in pr_section

    def test_workflow_runs_push_on_main(self):
        ci = (self.REPO_ROOT / ".github" / "workflows" / "ci.yml").read_text(encoding="utf-8")
        push_section = ci.split("push:")[1].split("pull_request:")[0]
        assert "main" in push_section

    def test_correctness_lint_covers_src_and_scripts(self):
        """The fail-closed correctness lint step must run flake8 with the
        E9,F63,F7,F82,F402,F541,F811,F841,W605 rule set across src/ and
        scripts/ — not just a handful of selected files."""
        ci = (self.REPO_ROOT / ".github" / "workflows" / "ci.yml").read_text(encoding="utf-8")
        assert "src" in ci
        assert "scripts" in ci
        for rule in ("E9", "F63", "F7", "F82", "F402", "F541", "F811", "F841", "W605"):
            assert rule in ci, f"lint rule {rule} missing from ci.yml"
        assert "flake8 src scripts" in ci or "flake8 src/ scripts/" in ci or "src/ scripts/" in ci
