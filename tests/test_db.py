"""Unit tests for the db.py query layer."""

import sqlite3

import pytest

from autopsy.db import (
    clear_results,
    get_all_test_ids,
    get_results_for_test,
    get_results_matrix,
    get_run_summary,
    insert_run,
    open_db,
)
from autopsy.models import RunRecord, TestResult


# ── helpers ────────────────────────────────────────────────────────────────────

def _make_db() -> sqlite3.Connection:
    """Return an in-memory DB with schema applied."""
    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row
    from autopsy.db import _create_schema
    _create_schema(conn)
    return conn


def _make_run(run_index: int, test_ids: list[str], statuses: list[str]) -> RunRecord:
    return RunRecord(
        run_index=run_index,
        seed=run_index * 1000,
        started_at=f"2024-01-0{run_index}T00:00:00+00:00",
        duration_s=0.5,
        results=[
            TestResult(test_id=tid, status=st, duration_s=0.1, stdout="")
            for tid, st in zip(test_ids, statuses)
        ],
    )


# ── tests ──────────────────────────────────────────────────────────────────────

def test_get_results_matrix_shape():
    """Matrix dimensions must match (runs × tests)."""
    conn = _make_db()
    tests = ["a::t1", "a::t2", "a::t3"]

    insert_run(conn, _make_run(1, tests, ["passed", "passed", "failed"]))
    insert_run(conn, _make_run(2, tests, ["passed", "failed", "passed"]))
    insert_run(conn, _make_run(3, tests, ["failed", "passed", "passed"]))

    matrix = get_results_matrix(conn)

    assert set(matrix.keys()) == set(tests)
    for test_id, statuses in matrix.items():
        assert len(statuses) == 3, f"{test_id} should have 3 entries"


def test_get_results_matrix_missing():
    """Runs where a test is absent must appear as 'missing'."""
    conn = _make_db()
    all_tests = ["a::t1", "a::t2"]

    # Run 1: both tests
    insert_run(conn, _make_run(1, all_tests, ["passed", "passed"]))
    # Run 2: only t1 (t2 not collected)
    insert_run(conn, _make_run(2, ["a::t1"], ["failed"]))
    # Run 3: both tests again
    insert_run(conn, _make_run(3, all_tests, ["passed", "passed"]))

    matrix = get_results_matrix(conn)

    assert matrix["a::t2"] == ["passed", "missing", "passed"]
    assert matrix["a::t1"] == ["passed", "failed", "passed"]


def test_get_all_test_ids():
    """get_all_test_ids returns exactly the distinct ids inserted."""
    conn = _make_db()
    tests = ["suite::alpha", "suite::beta", "suite::gamma"]
    insert_run(conn, _make_run(1, tests, ["passed"] * 3))
    insert_run(conn, _make_run(2, tests[:2], ["failed", "passed"]))

    ids = get_all_test_ids(conn)

    assert sorted(ids) == sorted(tests)


def test_clear_results():
    """After clear_results both tables must be empty."""
    conn = _make_db()
    insert_run(conn, _make_run(1, ["x::a", "x::b"], ["passed", "failed"]))
    insert_run(conn, _make_run(2, ["x::a", "x::b"], ["passed", "passed"]))

    clear_results(conn)

    assert conn.execute("SELECT COUNT(*) FROM runs").fetchone()[0] == 0
    assert conn.execute("SELECT COUNT(*) FROM results").fetchone()[0] == 0


def test_get_run_summary():
    """get_run_summary counts must reflect exactly what was inserted."""
    conn = _make_db()
    tests = ["m::t1", "m::t2"]
    insert_run(conn, _make_run(1, tests, ["passed", "failed"]))
    insert_run(conn, _make_run(2, tests, ["passed", "passed"]))

    s = get_run_summary(conn)

    assert s["total_runs"] == 2
    assert s["unique_test_ids"] == 2
    assert s["total_tests_seen"] == 4  # 2 tests × 2 runs
    assert s["first_run_at"] != ""
    assert s["last_run_at"] != ""
