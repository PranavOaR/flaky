"""Tests for autopsy ignore command and DB ignore-list functions."""

from pathlib import Path

from click.testing import CliRunner

from autopsy.cli import ignore_cmd
from autopsy.db import (
    add_ignored_test,
    create_session,
    get_ignored_tests,
    get_ignored_tests_detail,
    insert_run,
    open_db,
    remove_ignored_test,
)
from autopsy.models import RunRecord, TestResult

# ── helpers ────────────────────────────────────────────────────────────────────

def _make_db(tmp_path: Path) -> Path:
    """Create a populated DB with one stable and one flaky test."""
    db_path = tmp_path / "autopsy_results.db"
    conn = open_db(db_path)
    create_session(conn, "s1", "2024-01-01T00:00:00+00:00", "test", 10, "/r")
    for i in range(1, 11):
        conn_record = RunRecord(
            run_index=i,
            seed=i * 100,
            started_at="2024-01-01T00:00:00+00:00",
            duration_s=0.1,
            results=[
                TestResult("pkg::test_stable", "passed", 0.05, ""),
                TestResult("pkg::test_flaky", "failed" if i % 2 else "passed", 0.05, ""),
            ],
        )
        insert_run(conn, conn_record, session_id="s1")
    conn.close()
    return db_path


# ── DB-layer unit tests ────────────────────────────────────────────────────────

def test_ignored_tests_table_created(tmp_path):
    """open_db creates the ignored_tests table."""
    conn = open_db(tmp_path / "test.db")
    tables = {
        row[0]
        for row in conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table'"
        ).fetchall()
    }
    assert "ignored_tests" in tables
    conn.close()


def test_get_ignored_tests_empty(tmp_path):
    """Returns an empty set when no tests have been ignored."""
    conn = open_db(tmp_path / "test.db")
    assert get_ignored_tests(conn) == set()
    conn.close()


def test_add_and_get_ignored_test(tmp_path):
    """add_ignored_test persists and get_ignored_tests returns the test ID."""
    conn = open_db(tmp_path / "test.db")
    add_ignored_test(conn, "pkg::test_flaky", reason="known infrastructure issue")
    assert "pkg::test_flaky" in get_ignored_tests(conn)
    conn.close()


def test_add_ignored_test_upserts(tmp_path):
    """Adding the same test twice doesn't raise and the set stays size 1."""
    conn = open_db(tmp_path / "test.db")
    add_ignored_test(conn, "pkg::test_foo")
    add_ignored_test(conn, "pkg::test_foo", reason="updated reason")
    assert get_ignored_tests(conn) == {"pkg::test_foo"}
    conn.close()


def test_get_ignored_tests_detail_includes_reason(tmp_path):
    """get_ignored_tests_detail returns reason and timestamp."""
    conn = open_db(tmp_path / "test.db")
    add_ignored_test(conn, "pkg::test_x", reason="flaky in CI only")
    rows = get_ignored_tests_detail(conn)
    assert len(rows) == 1
    assert rows[0]["test_id"] == "pkg::test_x"
    assert rows[0]["reason"] == "flaky in CI only"
    assert rows[0]["ignored_at"]
    conn.close()


def test_remove_ignored_test_returns_true_when_present(tmp_path):
    """remove_ignored_test returns True when the test was on the list."""
    conn = open_db(tmp_path / "test.db")
    add_ignored_test(conn, "pkg::test_y")
    assert remove_ignored_test(conn, "pkg::test_y") is True
    assert "pkg::test_y" not in get_ignored_tests(conn)
    conn.close()


def test_remove_ignored_test_returns_false_when_absent(tmp_path):
    """remove_ignored_test returns False when the test was not on the list."""
    conn = open_db(tmp_path / "test.db")
    assert remove_ignored_test(conn, "pkg::test_z") is False
    conn.close()


# ── CLI tests ──────────────────────────────────────────────────────────────────

def test_ignore_add(tmp_path):
    """`autopsy ignore <test_id>` adds the test to the ignore list."""
    db = _make_db(tmp_path)
    runner = CliRunner()
    result = runner.invoke(ignore_cmd, ["pkg::test_flaky", "--db", str(db)])
    assert result.exit_code == 0
    assert "Ignoring" in result.output

    conn = open_db(db)
    assert "pkg::test_flaky" in get_ignored_tests(conn)
    conn.close()


def test_ignore_add_with_reason(tmp_path):
    """`autopsy ignore <test_id> --reason` stores the reason."""
    db = _make_db(tmp_path)
    runner = CliRunner()
    runner.invoke(ignore_cmd, ["pkg::test_flaky", "--db", str(db), "--reason", "known infra issue"])
    conn = open_db(db)
    rows = get_ignored_tests_detail(conn)
    row = next(r for r in rows if r["test_id"] == "pkg::test_flaky")
    assert row["reason"] == "known infra issue"
    conn.close()


def test_ignore_list(tmp_path):
    """`autopsy ignore --list` shows all ignored tests."""
    db = _make_db(tmp_path)
    conn = open_db(db)
    add_ignored_test(conn, "pkg::test_alpha", reason="slow")
    add_ignored_test(conn, "pkg::test_beta")
    conn.close()

    runner = CliRunner()
    result = runner.invoke(ignore_cmd, ["--list", "--db", str(db)])
    assert result.exit_code == 0
    assert "pkg::test_alpha" in result.output
    assert "pkg::test_beta" in result.output
    assert "slow" in result.output


def test_ignore_list_empty(tmp_path):
    """`autopsy ignore --list` on an empty list reports nothing to show."""
    db = _make_db(tmp_path)
    runner = CliRunner()
    result = runner.invoke(ignore_cmd, ["--list", "--db", str(db)])
    assert result.exit_code == 0
    assert "No tests" in result.output


def test_ignore_remove(tmp_path):
    """`autopsy ignore <test_id> --remove` removes the test."""
    db = _make_db(tmp_path)
    conn = open_db(db)
    add_ignored_test(conn, "pkg::test_flaky")
    conn.close()

    runner = CliRunner()
    result = runner.invoke(ignore_cmd, ["pkg::test_flaky", "--db", str(db), "--remove"])
    assert result.exit_code == 0
    assert "Removed" in result.output

    conn = open_db(db)
    assert "pkg::test_flaky" not in get_ignored_tests(conn)
    conn.close()


def test_ignore_remove_nonexistent(tmp_path):
    """`autopsy ignore --remove` on an absent test reports it wasn't there."""
    db = _make_db(tmp_path)
    runner = CliRunner()
    result = runner.invoke(ignore_cmd, ["pkg::no_such_test", "--db", str(db), "--remove"])
    assert result.exit_code == 0
    assert "not on the ignore list" in result.output


def test_ignore_requires_test_id_when_adding(tmp_path):
    """`autopsy ignore` with no test_id and no flag exits with an error."""
    db = _make_db(tmp_path)
    runner = CliRunner()
    result = runner.invoke(ignore_cmd, ["--db", str(db)])
    assert result.exit_code != 0
    assert "provide a test_id" in result.output


def test_ignore_missing_db(tmp_path):
    """`autopsy ignore` on a missing DB exits 1."""
    runner = CliRunner()
    result = runner.invoke(ignore_cmd, ["some::test", "--db", str(tmp_path / "nope.db")])
    assert result.exit_code == 1
