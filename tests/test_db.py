"""Unit tests for the db.py query layer."""

import sqlite3
from datetime import datetime, timedelta, timezone

import pytest

from autopsy.db import (
    clear_results,
    create_session,
    get_all_sessions,
    get_all_test_ids,
    get_cached_ai_fix,
    get_results_by_session,
    get_results_for_test,
    get_results_matrix,
    get_run_summary,
    get_session_for_run,
    get_sessions_to_prune,
    insert_run,
    open_db,
    prune_sessions,
    save_ai_fix,
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
    """After clear_results runs, results, and sessions tables must be empty."""
    conn = _make_db()
    create_session(conn, "s1", "2024-01-01T00:00:00+00:00", "label", 2, "/repo")
    insert_run(conn, _make_run(1, ["x::a", "x::b"], ["passed", "failed"]), session_id="s1")
    insert_run(conn, _make_run(2, ["x::a", "x::b"], ["passed", "passed"]), session_id="s1")

    clear_results(conn)

    assert conn.execute("SELECT COUNT(*) FROM runs").fetchone()[0] == 0
    assert conn.execute("SELECT COUNT(*) FROM results").fetchone()[0] == 0
    assert conn.execute("SELECT COUNT(*) FROM sessions").fetchone()[0] == 0


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


def test_ai_fixes_table_created(tmp_path):
    """open_db should create the ai_fixes table automatically."""
    conn = open_db(tmp_path / "test.db")
    tables = {
        row[0]
        for row in conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table'"
        ).fetchall()
    }
    assert "ai_fixes" in tables
    conn.close()


def test_cache_roundtrip(tmp_path):
    """save_ai_fix stores and get_cached_ai_fix retrieves correctly; upserts update."""
    conn = open_db(tmp_path / "test.db")

    assert get_cached_ai_fix(conn, "t::foo", "network") is None

    save_ai_fix(conn, "t::foo", "network", "Fix: use requests_mock.", "claude-opus-4-7")
    assert get_cached_ai_fix(conn, "t::foo", "network") == "Fix: use requests_mock."

    # Different cause — should be independent
    assert get_cached_ai_fix(conn, "t::foo", "timing") is None

    # Upsert same key — should overwrite
    save_ai_fix(conn, "t::foo", "network", "Updated fix.", "claude-opus-4-7")
    assert get_cached_ai_fix(conn, "t::foo", "network") == "Updated fix."

    conn.close()


# ── session tests ──────────────────────────────────────────────────────────────

def test_create_session(tmp_path):
    """create_session persists a row that get_all_sessions returns."""
    conn = open_db(tmp_path / "test.db")

    create_session(
        conn,
        session_id="sess-abc",
        started_at="2024-06-01T10:00:00+00:00",
        label="baseline",
        run_count=5,
        repo_path="/some/path",
    )

    sessions = get_all_sessions(conn)
    ids = [s["id"] for s in sessions]
    assert "sess-abc" in ids

    sess = next(s for s in sessions if s["id"] == "sess-abc")
    assert sess["label"] == "baseline"
    assert sess["run_count"] == 5
    assert sess["repo_path"] == "/some/path"

    conn.close()


def test_get_results_by_session(tmp_path):
    """get_results_by_session returns correct nested structure."""
    conn = open_db(tmp_path / "test.db")

    create_session(conn, "s1", "2024-01-01T00:00:00+00:00", "first", 2, "/p")
    create_session(conn, "s2", "2024-01-02T00:00:00+00:00", "second", 2, "/p")

    tests = ["suite::test_a", "suite::test_b"]

    insert_run(conn, _make_run(1, tests, ["passed", "failed"]), session_id="s1")
    insert_run(conn, _make_run(2, tests, ["passed", "passed"]), session_id="s1")
    insert_run(conn, _make_run(3, tests, ["failed", "passed"]), session_id="s2")

    by_session = get_results_by_session(conn)

    assert "s1" in by_session
    assert "s2" in by_session

    s1_test_a = by_session["s1"]["suite::test_a"]
    assert "passed" in s1_test_a
    assert len(s1_test_a) == 2

    s2_test_a = by_session["s2"]["suite::test_a"]
    assert s2_test_a == ["failed"]

    conn.close()


def test_session_migration(tmp_path):
    """Opening a DB missing session_id column triggers migration without error."""
    db_path = tmp_path / "legacy.db"

    # Create an old-style DB without session_id column or sessions table
    conn_old = sqlite3.connect(str(db_path))
    conn_old.executescript("""
        CREATE TABLE runs (
            id          INTEGER PRIMARY KEY AUTOINCREMENT,
            run_index   INTEGER,
            seed        INTEGER,
            started_at  TEXT,
            duration_s  REAL
        );
        CREATE TABLE results (
            id          INTEGER PRIMARY KEY AUTOINCREMENT,
            run_id      INTEGER,
            test_id     TEXT,
            status      TEXT,
            duration_s  REAL,
            stdout      TEXT
        );
        INSERT INTO runs (run_index, seed, started_at, duration_s)
        VALUES (1, 99, '2024-03-01T00:00:00+00:00', 1.0);
        INSERT INTO results (run_id, test_id, status, duration_s, stdout)
        VALUES (1, 'legacy::test_x', 'passed', 0.2, '');
    """)
    conn_old.commit()
    conn_old.close()

    # open_db must not raise
    conn = open_db(db_path)

    # session_id column must now exist
    cols = {row[1] for row in conn.execute("PRAGMA table_info(runs)").fetchall()}
    assert "session_id" in cols

    # Legacy run must be assigned to legacy session
    row = conn.execute("SELECT session_id FROM runs WHERE id = 1").fetchone()
    assert row["session_id"] == "legacy-session-001"

    # Legacy session row must exist in sessions table
    sess = conn.execute(
        "SELECT * FROM sessions WHERE id = 'legacy-session-001'"
    ).fetchone()
    assert sess is not None

    conn.close()


# ── pruning tests ──────────────────────────────────────────────────────────────

def _ts(days_ago: int) -> str:
    return (datetime.now(timezone.utc) - timedelta(days=days_ago)).isoformat()


def test_prune_by_keep(tmp_path):
    """get_sessions_to_prune keeps only the N most recent sessions."""
    conn = open_db(tmp_path / "prune.db")
    for i in range(5):
        create_session(conn, f"s{i}", _ts(10 - i), None, 1, "/r")

    to_remove = get_sessions_to_prune(conn, keep=3)
    assert len(to_remove) == 2
    assert "s0" in to_remove
    assert "s1" in to_remove
    conn.close()


def test_prune_by_age(tmp_path):
    """get_sessions_to_prune removes sessions older than N days."""
    conn = open_db(tmp_path / "prune_age.db")
    create_session(conn, "old", _ts(30), None, 1, "/r")
    create_session(conn, "new", _ts(1), None, 1, "/r")

    to_remove = get_sessions_to_prune(conn, keep=100, older_than_days=7)
    assert "old" in to_remove
    assert "new" not in to_remove
    conn.close()


def test_prune_sessions_cascades(tmp_path):
    """prune_sessions removes associated runs and results."""
    conn = open_db(tmp_path / "cascade.db")
    create_session(conn, "s1", _ts(20), None, 1, "/r")
    insert_run(conn, _make_run(1, ["t::a"], ["passed"]), session_id="s1")

    removed = prune_sessions(conn, ["s1"])

    assert removed == 1
    assert get_all_sessions(conn) == []
    assert get_run_summary(conn)["total_runs"] == 0
    assert get_run_summary(conn)["total_tests_seen"] == 0
    conn.close()


def test_prune_empty_list_is_noop(tmp_path):
    """Pruning an empty list returns 0 and leaves data intact."""
    conn = open_db(tmp_path / "noop.db")
    create_session(conn, "s1", _ts(1), None, 1, "/r")

    assert prune_sessions(conn, []) == 0
    assert len(get_all_sessions(conn)) == 1
    conn.close()
