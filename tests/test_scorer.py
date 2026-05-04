"""Unit tests for the scorer + classifier."""

import sqlite3

from autopsy.db import _create_schema, insert_run
from autopsy.models import RootCause, RunRecord, TestResult
from autopsy.scorer import (
    _classify_network,
    _classify_ordering,
    _classify_randomness,
    _classify_timing,
    classify_root_cause,
    compute_severity,
    score_from_conn,
    wilson_lower_bound,
)

# ── Wilson math ────────────────────────────────────────────────────────────────

def test_wilson_perfect():
    """10/10 passes (0 failures) → flakiness < 0.05."""
    score = wilson_lower_bound(0, 10)
    assert score < 0.05


def test_wilson_always_failing():
    """0/10 passes (10 failures) → flakiness > 0.60."""
    score = wilson_lower_bound(10, 10)
    assert score > 0.60


def test_wilson_half():
    """5/10 passes (5 failures) → flakiness in [0.20, 0.35]."""
    score = wilson_lower_bound(5, 10)
    assert 0.20 <= score <= 0.35


def test_wilson_low_n():
    """min_runs=5 must exclude tests with fewer real outcomes."""
    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row
    _create_schema(conn)
    for i in range(1, 4):  # only 3 runs
        insert_run(conn, RunRecord(
            run_index=i,
            seed=i * 1000,
            started_at=f"2024-01-0{i}T00:00:00+00:00",
            duration_s=0.5,
            results=[TestResult("t::a", "passed" if i < 3 else "failed", 0.1, "")],
        ))

    reports = score_from_conn(conn, min_runs=5)
    assert reports == []


def test_severity_bands():
    """One assertion per band boundary."""
    assert compute_severity(0.0) == "none"
    assert compute_severity(0.05) == "low"
    assert compute_severity(0.10) == "low"
    assert compute_severity(0.11) == "medium"
    assert compute_severity(0.30) == "medium"
    assert compute_severity(0.31) == "high"
    assert compute_severity(0.60) == "high"
    assert compute_severity(0.61) == "critical"


# ── classifier tests ───────────────────────────────────────────────────────────

def test_classify_ordering():
    """First half all-fail, second half all-pass → ordering, high confidence."""
    statuses = ["failed"] * 5 + ["passed"] * 5
    cause = _classify_ordering(statuses)
    assert cause is not None
    assert cause.category == "ordering"
    assert cause.confidence == "high"


def test_classify_network():
    """Failure output containing 'connection refused' triggers network."""
    failures = [{"stdout": "ConnectionError: connection refused to api.example.com"}]
    cause = _classify_network(failures)
    assert cause is not None
    assert cause.category == "network"
    assert cause.confidence == "high"  # 'connection', 'refused', 'api' → ≥2 keywords


def test_classify_randomness():
    """Uniform pass/fail alternation with no keywords → randomness."""
    statuses = ["passed", "failed"] * 5  # alternating
    failures = [{"stdout": "AssertionError: 0.123 >= 0.4"} for _ in range(5)]
    cause = _classify_randomness(statuses, failures)
    assert cause is not None
    assert cause.category == "randomness"


def test_classify_timing():
    """Failing runs averaging 3× longer than passes → timing."""
    passes = [{"duration_s": 0.1, "stdout": ""} for _ in range(5)]
    failures = [{"duration_s": 0.5, "stdout": "AssertionError"} for _ in range(3)]
    cause = _classify_timing(passes, failures)
    assert cause is not None
    assert cause.category == "timing"


def test_classify_priority():
    """When network keywords + ordering signal both fire, network wins."""
    statuses = ["failed"] * 5 + ["passed"] * 5  # ordering signal
    failure_text = "ConnectionError: connection refused to api.example.com"
    results = (
        [{"status": "failed", "duration_s": 0.1, "stdout": failure_text}] * 5
        + [{"status": "passed", "duration_s": 0.1, "stdout": ""}] * 5
    )
    cause = classify_root_cause(statuses, results)
    assert isinstance(cause, RootCause)
    assert cause.category == "network"
