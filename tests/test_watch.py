"""Tests for autopsy watch command."""

import subprocess as _subprocess
from unittest.mock import MagicMock, patch

from click.testing import CliRunner

from autopsy.cli import watch_cmd
from autopsy.models import TestResult


def _make_results(status: str) -> list[TestResult]:
    return [TestResult(
        test_id="pkg::test_target",
        status=status,
        duration_s=0.1,
        stdout="AssertionError: boom" if status == "failed" else "",
    )]


def test_watch_reproduces_failure(tmp_path):
    """`autopsy watch` exits 1 and prints repro info when the test fails."""
    runner = CliRunner()
    suite = tmp_path / "suite"
    suite.mkdir()

    with patch("autopsy.cli.subprocess.run"), \
         patch("autopsy.runner._parse_json_report", return_value=_make_results("failed")):
        result = runner.invoke(watch_cmd, ["pkg::test_target", str(suite), "--max-runs", "5"])

    assert result.exit_code == 1
    assert "Reproduced" in result.output
    assert "Seed" in result.output


def test_watch_no_reproduction(tmp_path):
    """`autopsy watch` exits 0 when max-runs exhausted without failure."""
    runner = CliRunner()
    suite = tmp_path / "suite"
    suite.mkdir()

    with patch("autopsy.cli.subprocess.run"), \
         patch("autopsy.runner._parse_json_report", return_value=_make_results("passed")):
        result = runner.invoke(watch_cmd, ["pkg::test_target", str(suite), "--max-runs", "3"])

    assert result.exit_code == 0
    assert "Not reproduced" in result.output


def test_watch_prints_per_run_status(tmp_path):
    """`autopsy watch` prints a status line per run."""
    runner = CliRunner()
    suite = tmp_path / "suite"
    suite.mkdir()

    with patch("autopsy.cli.subprocess.run"), \
         patch("autopsy.runner._parse_json_report", return_value=_make_results("passed")):
        result = runner.invoke(watch_cmd, ["pkg::test_target", str(suite), "--max-runs", "2"])

    assert "Run 1/2" in result.output
    assert "Run 2/2" in result.output


def test_watch_skips_uncollected_test(tmp_path):
    """`autopsy watch` skips runs where the target test isn't in results."""
    runner = CliRunner()
    suite = tmp_path / "suite"
    suite.mkdir()

    with patch("autopsy.cli.subprocess.run"), \
         patch("autopsy.runner._parse_json_report", return_value=[]):
        result = runner.invoke(watch_cmd, ["pkg::test_target", str(suite), "--max-runs", "2"])

    assert result.exit_code == 0
    assert "not collected" in result.output


def test_watch_handles_timeout(tmp_path):
    """`autopsy watch` prints a timeout warning and continues."""
    runner = CliRunner()
    suite = tmp_path / "suite"
    suite.mkdir()

    call_count = 0

    def fake_run(*args, **kwargs):
        nonlocal call_count
        call_count += 1
        if call_count == 1:
            raise _subprocess.TimeoutExpired(cmd=args[0], timeout=1)
        return MagicMock()

    with patch("autopsy.cli.subprocess.run", side_effect=fake_run), \
         patch("autopsy.runner._parse_json_report", return_value=_make_results("passed")):
        result = runner.invoke(watch_cmd, ["pkg::test_target", str(suite), "--max-runs", "2"])

    assert "timed out" in result.output
    assert result.exit_code == 0


def test_watch_shows_failure_snippet(tmp_path):
    """`autopsy watch` prints the failure output when a failure is found."""
    runner = CliRunner()
    suite = tmp_path / "suite"
    suite.mkdir()

    with patch("autopsy.cli.subprocess.run"), \
         patch("autopsy.runner._parse_json_report", return_value=_make_results("failed")):
        result = runner.invoke(watch_cmd, ["pkg::test_target", str(suite), "--max-runs", "5"])

    assert "AssertionError" in result.output
