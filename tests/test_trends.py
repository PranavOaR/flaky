"""Unit tests for autopsy/trends.py — sparklines and trend classification."""

import sqlite3

from autopsy.trends import (
    SessionScore,
    TrendReport,
    _classify_trend,
    get_regressions,
    make_sparkline,
)

# ── helpers ────────────────────────────────────────────────────────────────────

def _session(session_id: str, score: float) -> SessionScore:
    return SessionScore(
        session_id=session_id,
        started_at="2024-01-01T00:00:00+00:00",
        label=None,
        flakiness_score=score,
        pass_rate=1.0 - score,
        total_runs=10,
    )


# ── sparkline tests ────────────────────────────────────────────────────────────

def test_sparkline_all_zeros():
    """All-zero scores map to lowest block character (space or ▁)."""
    result = make_sparkline([0.0, 0.0, 0.0])
    # Index 0 → space ' '
    assert result == "   "


def test_sparkline_all_ones():
    """All-one scores map to full block character '█'."""
    result = make_sparkline([1.0, 1.0, 1.0])
    assert result == "███"


def test_sparkline_mixed():
    """Mixed scores produce expected character sequence."""
    # 0.0 → idx 0 → ' '
    # 0.5 → idx 4 → '▄'
    # 1.0 → idx 8 → '█'
    result = make_sparkline([0.0, 0.5, 1.0])
    assert len(result) == 3
    assert result[0] == " "
    assert result[1] == "▄"
    assert result[2] == "█"


# ── trend classification tests ─────────────────────────────────────────────────

def test_trend_regression():
    """Clean → flaky transition is classified as 'regression'."""
    sessions = [_session("s1", 0.0), _session("s2", 0.20)]
    trend, delta = _classify_trend(sessions)
    assert trend == "regression"
    assert abs(delta - 0.20) < 1e-9


def test_trend_improvement():
    """Flaky → clean transition is classified as 'improvement'."""
    sessions = [_session("s1", 0.40), _session("s2", 0.02)]
    trend, delta = _classify_trend(sessions)
    assert trend == "improvement"
    assert delta < 0


def test_trend_worsening():
    """Flaky → worse flaky (delta > threshold) is classified as 'worsening'."""
    sessions = [_session("s1", 0.20), _session("s2", 0.45)]
    trend, delta = _classify_trend(sessions, regression_threshold=0.10)
    assert trend == "worsening"
    assert abs(delta - 0.25) < 1e-9


def test_trend_stable_flaky():
    """Flaky score with small delta stays 'stable_flaky'."""
    sessions = [_session("s1", 0.30), _session("s2", 0.32)]
    trend, delta = _classify_trend(sessions, regression_threshold=0.10)
    assert trend == "stable_flaky"


def test_trend_stable_clean():
    """Two sessions both below threshold → 'stable_clean'."""
    sessions = [_session("s1", 0.02), _session("s2", 0.01)]
    trend, delta = _classify_trend(sessions)
    assert trend == "stable_clean"


def test_trend_new():
    """Single session returns 'new' with delta 0.0."""
    sessions = [_session("s1", 0.35)]
    trend, delta = _classify_trend(sessions)
    assert trend == "new"
    assert delta == 0.0


def test_trend_delta():
    """trend_delta equals latest.flakiness_score - previous.flakiness_score."""
    sessions = [_session("s1", 0.10), _session("s2", 0.35)]
    _, delta = _classify_trend(sessions)
    assert abs(delta - (0.35 - 0.10)) < 1e-9


# ── get_regressions tests ──────────────────────────────────────────────────────

def test_get_regressions_filter():
    """get_regressions returns only regression and worsening, sorted by delta desc."""
    reports = [
        TrendReport(test_id="a", trend="regression", trend_delta=0.20, sparkline=""),
        TrendReport(test_id="b", trend="worsening", trend_delta=0.15, sparkline=""),
        TrendReport(test_id="c", trend="stable_flaky", trend_delta=0.02, sparkline=""),
        TrendReport(test_id="d", trend="improvement", trend_delta=-0.10, sparkline=""),
        TrendReport(test_id="e", trend="stable_clean", trend_delta=0.0, sparkline=""),
    ]
    regressions = get_regressions(reports)
    ids = [r.test_id for r in regressions]
    assert set(ids) == {"a", "b"}
    # sorted by delta descending
    assert ids[0] == "a"


# ── session migration test ─────────────────────────────────────────────────────

def test_session_migration(tmp_path):
    """Opening a DB without session_id column triggers migration without error."""
    db_path = tmp_path / "old.db"

    # Build an "old-style" DB without session_id or sessions table
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
        VALUES (1, 42, '2024-01-01T00:00:00+00:00', 0.5);
        INSERT INTO results (run_id, test_id, status, duration_s, stdout)
        VALUES (1, 'test_a::test_one', 'passed', 0.1, '');
    """)
    conn_old.commit()
    conn_old.close()

    # Now open via open_db — migration should run silently
    from autopsy.db import open_db
    conn = open_db(db_path)

    # session_id column should exist
    cols = {row[1] for row in conn.execute("PRAGMA table_info(runs)").fetchall()}
    assert "session_id" in cols

    # The legacy run should have been assigned the legacy session id
    row = conn.execute("SELECT session_id FROM runs WHERE id = 1").fetchone()
    assert row["session_id"] == "legacy-session-001"

    # sessions table should have an entry for the legacy session
    sess = conn.execute(
        "SELECT * FROM sessions WHERE id = 'legacy-session-001'"
    ).fetchone()
    assert sess is not None

    conn.close()
