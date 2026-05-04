"""Tests for autopsy/runner.py — JSON report parsing and run logic."""

import json
from pathlib import Path

import pytest
from rich.console import Console

from autopsy.runner import _OUTCOME_MAP, _parse_json_report

# ── fixtures ───────────────────────────────────────────────────────────────────

@pytest.fixture
def console():
    return Console(quiet=True)


def _write_report(path: Path, tests: list[dict]) -> None:
    """Write a minimal pytest-json-report file."""
    path.write_text(json.dumps({"tests": tests}), encoding="utf-8")


# ── outcome map ────────────────────────────────────────────────────────────────

def test_outcome_map_covers_all_pytest_outcomes():
    """Every outcome pytest-json-report can produce has a mapping."""
    expected = {"passed", "failed", "error", "skipped", "xfailed", "xpassed"}
    assert expected == set(_OUTCOME_MAP.keys())


def test_xfailed_maps_to_skipped():
    assert _OUTCOME_MAP["xfailed"] == "skipped"


def test_xpassed_maps_to_failed():
    assert _OUTCOME_MAP["xpassed"] == "failed"


# ── _parse_json_report ────────────────────────────────────────────────────────

def test_parse_missing_file(tmp_path, console):
    """Missing report file returns empty list without raising."""
    results = _parse_json_report(tmp_path / "nope.json", run_index=1, console=console)
    assert results == []


def test_parse_malformed_json(tmp_path, console):
    """Malformed JSON returns empty list without raising."""
    bad = tmp_path / "bad.json"
    bad.write_text("not json!", encoding="utf-8")
    results = _parse_json_report(bad, run_index=1, console=console)
    assert results == []


def test_parse_basic_results(tmp_path, console):
    """Parses nodeid, outcome, and duration correctly."""
    report = tmp_path / "report.json"
    _write_report(report, [
        {"nodeid": "t::test_a", "outcome": "passed", "duration": 0.12},
        {"nodeid": "t::test_b", "outcome": "failed", "duration": 0.30,
         "call": {"stdout": "AssertionError: 1 != 2", "longrepr": "short traceback"}},
    ])

    results = _parse_json_report(report, run_index=1, console=console)

    assert len(results) == 2
    assert results[0].test_id == "t::test_a"
    assert results[0].status == "passed"
    assert abs(results[0].duration_s - 0.12) < 1e-9

    assert results[1].test_id == "t::test_b"
    assert results[1].status == "failed"
    assert "AssertionError" in results[1].stdout


def test_parse_unknown_outcome_becomes_error(tmp_path, console):
    """Unrecognised outcome string maps to 'error'."""
    report = tmp_path / "report.json"
    _write_report(report, [
        {"nodeid": "t::test_x", "outcome": "weird_future_outcome", "duration": 0.0},
    ])
    results = _parse_json_report(report, run_index=1, console=console)
    assert results[0].status == "error"


def test_parse_stdout_prefers_call_phase(tmp_path, console):
    """stdout is taken from the 'call' phase if present."""
    report = tmp_path / "report.json"
    _write_report(report, [{
        "nodeid": "t::test_phases",
        "outcome": "failed",
        "duration": 0.1,
        "setup": {"stdout": "setup output", "longrepr": None},
        "call":  {"stdout": "call output",  "longrepr": "the traceback"},
    }])
    results = _parse_json_report(report, run_index=1, console=console)
    assert "call output" in results[0].stdout
    assert "setup output" not in results[0].stdout


def test_parse_empty_tests_list(tmp_path, console):
    """A report with an empty tests array returns an empty list."""
    report = tmp_path / "report.json"
    report.write_text(json.dumps({"tests": []}), encoding="utf-8")
    results = _parse_json_report(report, run_index=1, console=console)
    assert results == []


def test_parse_quiet_suppresses_output(tmp_path, capsys):
    """quiet=True suppresses console messages for missing reports."""
    console = Console()
    _parse_json_report(tmp_path / "missing.json", run_index=1, console=console, quiet=True)
    captured = capsys.readouterr()
    assert captured.out == ""
    assert captured.err == ""
