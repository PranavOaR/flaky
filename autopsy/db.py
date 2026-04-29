"""SQLite interface for storing test run results."""

import sqlite3
from datetime import datetime, timezone
from pathlib import Path

from autopsy.models import RunRecord


def open_db(path: Path) -> sqlite3.Connection:
    """Open (or create) the SQLite database and ensure schema exists."""
    conn = sqlite3.connect(str(path))
    conn.row_factory = sqlite3.Row
    _create_schema(conn)
    create_ai_fixes_table(conn)
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


def create_ai_fixes_table(conn: sqlite3.Connection) -> None:
    """Create the AI fix response cache table if it doesn't exist."""
    conn.execute("""
        CREATE TABLE IF NOT EXISTS ai_fixes (
            id           INTEGER PRIMARY KEY AUTOINCREMENT,
            test_id      TEXT NOT NULL,
            root_cause   TEXT NOT NULL,
            ai_response  TEXT NOT NULL,
            model        TEXT NOT NULL,
            created_at   TEXT NOT NULL,
            UNIQUE(test_id, root_cause)
        )
    """)
    conn.commit()


def get_cached_ai_fix(conn: sqlite3.Connection, test_id: str, root_cause: str) -> "str | None":
    """Return cached AI response for this test+cause, or None if not cached."""
    row = conn.execute(
        "SELECT ai_response FROM ai_fixes WHERE test_id = ? AND root_cause = ?",
        (test_id, root_cause),
    ).fetchone()
    return row["ai_response"] if row else None


def save_ai_fix(
    conn: sqlite3.Connection,
    test_id: str,
    root_cause: str,
    ai_response: str,
    model: str,
) -> None:
    """Upsert AI fix response into cache."""
    conn.execute(
        """
        INSERT OR REPLACE INTO ai_fixes (test_id, root_cause, ai_response, model, created_at)
        VALUES (?, ?, ?, ?, ?)
        """,
        (test_id, root_cause, ai_response, model, datetime.now(timezone.utc).isoformat()),
    )
    conn.commit()


# ── write ─────────────────────────────────────────────────────────────────────

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


def clear_results(conn: sqlite3.Connection) -> None:
    """Delete all rows from runs and results tables."""
    conn.executescript("DELETE FROM results; DELETE FROM runs;")
    conn.commit()


# ── read: summary ──────────────────────────────────────────────────────────────

def fetch_flakiness_summary(conn: sqlite3.Connection) -> list[dict]:
    """Return per-test pass counts and flakiness percentage across all runs."""
    rows = conn.execute("""
        SELECT
            test_id,
            COUNT(*) AS total_runs,
            SUM(CASE WHEN status = 'passed' THEN 1 ELSE 0 END) AS passed,
            ROUND(
                100.0 * SUM(CASE WHEN status IN ('failed', 'error') THEN 1 ELSE 0 END)
                / NULLIF(COUNT(*), 0),
                1
            ) AS flakiness_pct
        FROM results
        GROUP BY test_id
        ORDER BY flakiness_pct DESC, test_id
    """).fetchall()
    return [dict(r) for r in rows]


def get_all_test_ids(conn: sqlite3.Connection) -> list[str]:
    """Return distinct test node ids seen across all runs."""
    rows = conn.execute("SELECT DISTINCT test_id FROM results ORDER BY test_id").fetchall()
    return [r["test_id"] for r in rows]


def get_results_for_test(conn: sqlite3.Connection, test_id: str) -> list[dict]:
    """Return all result rows for a given test_id ordered by run_index."""
    rows = conn.execute("""
        SELECT ru.run_index, ru.seed, re.status, re.duration_s, re.stdout
        FROM results re
        JOIN runs ru ON ru.id = re.run_id
        WHERE re.test_id = ?
        ORDER BY ru.run_index ASC
    """, (test_id,)).fetchall()
    return [dict(r) for r in rows]


def get_run_summary(conn: sqlite3.Connection) -> dict:
    """Return aggregate stats across all recorded runs."""
    runs_row = conn.execute("""
        SELECT
            COUNT(*)            AS total_runs,
            MIN(started_at)     AS first_run_at,
            MAX(started_at)     AS last_run_at
        FROM runs
    """).fetchone()

    results_row = conn.execute("""
        SELECT
            COUNT(*)                    AS total_tests_seen,
            COUNT(DISTINCT test_id)     AS unique_test_ids
        FROM results
    """).fetchone()

    return {
        "total_runs": runs_row["total_runs"] or 0,
        "total_tests_seen": results_row["total_tests_seen"] or 0,
        "unique_test_ids": results_row["unique_test_ids"] or 0,
        "first_run_at": runs_row["first_run_at"] or "",
        "last_run_at": runs_row["last_run_at"] or "",
    }


def get_results_matrix(conn: sqlite3.Connection) -> dict[str, list[str]]:
    """Return test_id → [status_per_run] with 'missing' for absent entries.

    Ordered by run_index ascending; gaps filled with 'missing'.
    """
    runs = conn.execute("SELECT id, run_index FROM runs ORDER BY run_index").fetchall()
    run_ids = [r["id"] for r in runs]

    if not run_ids:
        return {}

    all_results = conn.execute("SELECT run_id, test_id, status FROM results").fetchall()

    lookup: dict[tuple[int, str], str] = {}
    all_test_ids: set[str] = set()
    for row in all_results:
        lookup[(row["run_id"], row["test_id"])] = row["status"]
        all_test_ids.add(row["test_id"])

    return {
        test_id: [lookup.get((run_id, test_id), "missing") for run_id in run_ids]
        for test_id in sorted(all_test_ids)
    }


# ── read: per-run detail ───────────────────────────────────────────────────────

def get_run_detail(conn: sqlite3.Connection) -> list[dict]:
    """Return per-run rows with test count and duration for the info table."""
    rows = conn.execute("""
        SELECT
            ru.id,
            ru.run_index,
            ru.seed,
            ru.started_at,
            ru.duration_s,
            COUNT(re.id) AS test_count
        FROM runs ru
        LEFT JOIN results re ON re.run_id = ru.id
        GROUP BY ru.id
        ORDER BY ru.run_index
    """).fetchall()
    return [dict(r) for r in rows]


# ── debug ──────────────────────────────────────────────────────────────────────

def get_db_info(conn: sqlite3.Connection) -> str:
    """Return a human-readable summary string of DB contents."""
    s = get_run_summary(conn)
    return (
        f"Runs: {s['total_runs']} | "
        f"Unique tests: {s['unique_test_ids']} | "
        f"Total result rows: {s['total_tests_seen']} | "
        f"First: {s['first_run_at'] or 'n/a'} | "
        f"Last: {s['last_run_at'] or 'n/a'}"
    )
