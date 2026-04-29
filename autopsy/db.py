"""SQLite interface for storing test run results."""

import sqlite3
from pathlib import Path

from autopsy.models import RunRecord, TestResult


def open_db(path: Path) -> sqlite3.Connection:
    """Open (or create) the SQLite database and ensure schema exists."""
    conn = sqlite3.connect(str(path))
    conn.row_factory = sqlite3.Row
    _create_schema(conn)
    return conn


def _create_schema(conn: sqlite3.Connection) -> None:
    conn.executescript("""
        CREATE TABLE IF NOT EXISTS runs (
            id          INTEGER PRIMARY KEY AUTOINCREMENT,
            run_index   INTEGER,
            seed        INTEGER,
            started_at  TEXT,
            duration_s  REAL
        );

        CREATE TABLE IF NOT EXISTS results (
            id          INTEGER PRIMARY KEY AUTOINCREMENT,
            run_id      INTEGER REFERENCES runs(id),
            test_id     TEXT,
            status      TEXT,
            duration_s  REAL,
            stdout      TEXT
        );
    """)
    conn.commit()


def insert_run(conn: sqlite3.Connection, record: RunRecord) -> int:
    """Insert a completed run and all its test results; return the run's row id."""
    cur = conn.execute(
        "INSERT INTO runs (run_index, seed, started_at, duration_s) VALUES (?,?,?,?)",
        (record.run_index, record.seed, record.started_at, record.duration_s),
    )
    run_id = cur.lastrowid
    conn.executemany(
        "INSERT INTO results (run_id, test_id, status, duration_s, stdout) VALUES (?,?,?,?,?)",
        [
            (run_id, r.test_id, r.status, r.duration_s, r.stdout)
            for r in record.results
        ],
    )
    conn.commit()
    return run_id


def fetch_flakiness_summary(conn: sqlite3.Connection) -> list[dict]:
    """Return per-test pass counts and flakiness percentage across all runs."""
    rows = conn.execute("""
        SELECT
            test_id,
            COUNT(*) AS total_runs,
            SUM(CASE WHEN status = 'passed' THEN 1 ELSE 0 END) AS passed,
            ROUND(
                100.0 * SUM(CASE WHEN status != 'passed' AND status != 'skipped' THEN 1 ELSE 0 END)
                / NULLIF(COUNT(*), 0),
                1
            ) AS flakiness_pct
        FROM results
        GROUP BY test_id
        ORDER BY flakiness_pct DESC, test_id
    """).fetchall()
    return [dict(r) for r in rows]
