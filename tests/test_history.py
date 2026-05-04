"""Tests for autopsy history command and get_history_for_test DB query."""

from pathlib import Path

from click.testing import CliRunner

from autopsy.cli import history_cmd
from autopsy.db import (
    create_session,
    get_history_for_test,
    insert_run,
    open_db,
)
from autopsy.models import RunRecord, TestResult

# ── helpers ────────────────────────────────────────────────────────────────────

def _make_db(tmp_path: Path) -> Path:
    """Create a DB with two sessions and a mix of pass/fail outcomes."""
    db_path = tmp_path / "autopsy_results.db"
    conn = open_db(db_path)

    create_session(conn, "s1", "2024-01-01T00:00:00+00:00", "baseline", 5, "/r")
    for i in range(1, 6):
        insert_run(conn, RunRecord(
            run_index=i, seed=i * 100,
            started_at="2024-01-01T00:00:00+00:00", duration_s=0.1,
            results=[
                TestResult("pkg::test_flaky", "failed" if i % 2 else "passed", 0.05,
                           f"AssertionError: run {i} failed" if i % 2 else ""),
                TestResult("pkg::test_stable", "passed", 0.03, ""),
            ],
        ), session_id="s1")

    create_session(conn, "s2", "2024-01-02T00:00:00+00:00", "v2", 5, "/r")
    for i in range(6, 11):
        insert_run(conn, RunRecord(
            run_index=i, seed=i * 100,
            started_at="2024-01-02T00:00:00+00:00", duration_s=0.1,
            results=[
                TestResult("pkg::test_flaky", "passed", 0.05, ""),
                TestResult("pkg::test_stable", "passed", 0.03, ""),
            ],
        ), session_id="s2")

    conn.close()
    return db_path


# ── DB-layer unit tests ────────────────────────────────────────────────────────

def test_get_history_for_test_returns_all_runs(tmp_path):
    """get_history_for_test returns one row per run the test appeared in."""
    db = _make_db(tmp_path)
    conn = open_db(db)
    rows = get_history_for_test(conn, "pkg::test_flaky")
    conn.close()
    assert len(rows) == 10


def test_get_history_for_test_includes_session_label(tmp_path):
    """Rows include the session label from the sessions table."""
    db = _make_db(tmp_path)
    conn = open_db(db)
    rows = get_history_for_test(conn, "pkg::test_flaky")
    conn.close()
    labels = {r["session_label"] for r in rows}
    assert "baseline" in labels
    assert "v2" in labels


def test_get_history_for_test_ordered_by_run_index(tmp_path):
    """Rows are sorted ascending by run_index."""
    db = _make_db(tmp_path)
    conn = open_db(db)
    rows = get_history_for_test(conn, "pkg::test_flaky")
    conn.close()
    indices = [r["run_index"] for r in rows]
    assert indices == sorted(indices)


def test_get_history_for_test_unknown_test(tmp_path):
    """Returns empty list for a test ID that doesn't exist in the DB."""
    db = _make_db(tmp_path)
    conn = open_db(db)
    rows = get_history_for_test(conn, "pkg::no_such_test")
    conn.close()
    assert rows == []


# ── CLI tests ──────────────────────────────────────────────────────────────────

def test_history_basic_output(tmp_path):
    """`autopsy history <test_id>` shows run count and status rows."""
    db = _make_db(tmp_path)
    runner = CliRunner()
    result = runner.invoke(history_cmd, ["pkg::test_flaky", str(db)])
    assert result.exit_code == 0
    # Summary line should mention 10 runs
    assert "10" in result.output
    # Both pass and fail should appear
    assert "passed" in result.output
    assert "failed" in result.output


def test_history_shows_failure_snippet(tmp_path):
    """`autopsy history` includes a truncated failure message in the output."""
    db = _make_db(tmp_path)
    runner = CliRunner()
    result = runner.invoke(history_cmd, ["pkg::test_flaky", str(db)])
    assert result.exit_code == 0
    assert "AssertionError" in result.output


def test_history_failures_only(tmp_path):
    """`--failures-only` suppresses passing rows."""
    db = _make_db(tmp_path)
    runner = CliRunner()
    result = runner.invoke(history_cmd, ["pkg::test_flaky", str(db), "--failures-only"])
    assert result.exit_code == 0
    # Only failure rows — no "✓ passed" cells
    assert "✓" not in result.output


def test_history_last_n(tmp_path):
    """`--last N` limits output to the N most recent runs and shows a note."""
    db = _make_db(tmp_path)
    runner = CliRunner()
    result = runner.invoke(history_cmd, ["pkg::test_flaky", str(db), "--last", "3"])
    assert result.exit_code == 0
    assert "3" in result.output


def test_history_unknown_test(tmp_path):
    """`autopsy history` on a test not in the DB exits 1."""
    db = _make_db(tmp_path)
    runner = CliRunner()
    result = runner.invoke(history_cmd, ["pkg::no_such_test", str(db)])
    assert result.exit_code == 1


def test_history_missing_db(tmp_path):
    """`autopsy history` on a missing DB exits 1."""
    runner = CliRunner()
    result = runner.invoke(history_cmd, ["pkg::any_test", str(tmp_path / "nope.db")])
    assert result.exit_code == 1


def test_history_shows_session_label(tmp_path):
    """Session labels from both sessions appear in the output."""
    db = _make_db(tmp_path)
    runner = CliRunner()
    result = runner.invoke(history_cmd, ["pkg::test_flaky", str(db)])
    assert result.exit_code == 0
    assert "baseline" in result.output
    assert "v2" in result.output
