"""Flakiness scoring (Wilson lower bound) and root cause classification."""

import math
import sqlite3
from pathlib import Path
from statistics import mean

from autopsy.db import get_results_for_test, get_results_matrix, open_db
from autopsy.models import FlakinessReport, RootCause

_Z_95 = 1.96  # 95% confidence z-score

# ── keyword sets per cause ─────────────────────────────────────────────────────
# (substring matching, case-insensitive)
_NETWORK_KEYWORDS = (
    "connection", "refused", "timeout", "socket", "http", "request",
    "dns", "unreachable", "network", "api", "endpoint",
    "urllib", "requests", "aiohttp", "httpx",
    "404", "500", "503", "ssl", "certificate",
)
_TIMING_KEYWORDS = (
    "timeout", "timed out", "deadline", "sleep",
    "race", "concurrent", "thread", "async",
)
_RANDOMNESS_KEYWORDS = (
    "random", "uuid", "seed", "shuffle", "sample",
    "randint", "choice", "hash", "pythonhashseed",
)

# Priority order — lower number = higher priority (more actionable)
_PRIORITY = {"network": 1, "timing": 2, "ordering": 3, "randomness": 4, "unknown": 5}

# Outcomes considered "real" data (skipped/missing/xfail are excluded)
_REAL_OUTCOMES = ("passed", "failed", "error")


# ── Wilson score interval ──────────────────────────────────────────────────────

def wilson_lower_bound(successes: int, total: int, z: float = _Z_95) -> float:
    """Wilson score lower bound for the binomial success rate."""
    if total <= 0:
        return 0.0
    p = successes / total
    n = total
    denom = 1 + (z ** 2) / n
    center = p + (z ** 2) / (2 * n)
    margin = z * math.sqrt(p * (1 - p) / n + (z ** 2) / (4 * n ** 2))
    return max(0.0, (center - margin) / denom)


def wilson_upper_bound(successes: int, total: int, z: float = _Z_95) -> float:
    """Wilson score upper bound for the binomial success rate."""
    if total <= 0:
        return 0.0
    p = successes / total
    n = total
    denom = 1 + (z ** 2) / n
    center = p + (z ** 2) / (2 * n)
    margin = z * math.sqrt(p * (1 - p) / n + (z ** 2) / (4 * n ** 2))
    return min(1.0, (center + margin) / denom)


def compute_severity(score: float) -> str:
    """Map a flakiness score to a severity band."""
    if score == 0.0:
        return "none"
    if score <= 0.10:
        return "low"
    if score <= 0.30:
        return "medium"
    if score <= 0.60:
        return "high"
    return "critical"


# ── classifiers ────────────────────────────────────────────────────────────────

def _find_keywords(text: str, keywords: tuple[str, ...]) -> list[str]:
    """Return the keywords that appear in `text`, case-insensitive."""
    if not text:
        return []
    lower = text.lower()
    return sorted({kw for kw in keywords if kw in lower})


def _classify_network(failures: list[dict]) -> RootCause | None:
    """Detect network-related failures via keyword scan of failure output."""
    text = "\n".join((f.get("stdout") or "") for f in failures)
    found = _find_keywords(text, _NETWORK_KEYWORDS)
    if not found:
        return None
    confidence = "high" if len(found) >= 2 else "medium"
    evidence = [f"failure output contains network keyword '{kw}'" for kw in found[:5]]
    return RootCause(category="network", confidence=confidence, evidence=evidence)


def _classify_timing(passes: list[dict], failures: list[dict]) -> RootCause | None:
    """Detect timing/race issues via duration delta and keyword scan."""
    if not failures:
        return None

    fail_text = "\n".join((f.get("stdout") or "") for f in failures)
    keywords = _find_keywords(fail_text, _TIMING_KEYWORDS)

    duration_signal = False
    duration_ratio = 0.0
    pass_durations = [(p.get("duration_s") or 0.0) for p in passes]
    fail_durations = [(f.get("duration_s") or 0.0) for f in failures]
    if pass_durations and fail_durations and mean(pass_durations) > 0:
        duration_ratio = mean(fail_durations) / mean(pass_durations)
        if duration_ratio > 1.5:
            duration_signal = True

    if not duration_signal and not keywords:
        return None

    if duration_ratio > 2.0 and keywords:
        confidence = "high"
    else:
        confidence = "medium"

    evidence: list[str] = []
    if duration_signal:
        evidence.append(
            f"failures take {duration_ratio:.1f}× longer than passes "
            f"({mean(fail_durations):.2f}s vs {mean(pass_durations):.2f}s)"
        )
    for kw in keywords[:3]:
        evidence.append(f"failure output contains timing keyword '{kw}'")

    return RootCause(category="timing", confidence=confidence, evidence=evidence)


def _classify_ordering(matrix_row: list[str]) -> RootCause | None:
    """Detect ordering dependency via half-vs-half pass-rate gap."""
    relevant = [s for s in matrix_row if s in _REAL_OUTCOMES]
    n = len(relevant)
    if n < 4:
        return None

    half = n // 2
    first = relevant[:half]
    second = relevant[half:]

    pr_first = sum(1 for s in first if s == "passed") / len(first)
    pr_second = sum(1 for s in second if s == "passed") / len(second)
    diff = abs(pr_first - pr_second)

    if diff <= 0.3:
        return None

    confidence = "high" if diff > 0.6 else "medium"
    evidence = [
        f"pass rate in runs 1-{half}: {pr_first*100:.0f}%, "
        f"runs {half+1}-{n}: {pr_second*100:.0f}%",
        f"correlation between run position and failure: {diff:.2f}",
    ]
    return RootCause(category="ordering", confidence=confidence, evidence=evidence)


def _classify_randomness(
    matrix_row: list[str],
    failures: list[dict],
) -> RootCause | None:
    """Detect randomness via keyword scan + uniform failure distribution."""
    fail_text = "\n".join((f.get("stdout") or "") for f in failures)
    keywords = _find_keywords(fail_text, _RANDOMNESS_KEYWORDS)

    relevant = [s for s in matrix_row if s in _REAL_OUTCOMES]
    n = len(relevant)
    fail_count = sum(1 for s in relevant if s in ("failed", "error"))

    if fail_count == 0 or fail_count == n or n < 4:
        return None

    half = n // 2
    first = relevant[:half]
    second = relevant[half:]
    fr_first = sum(1 for s in first if s in ("failed", "error")) / len(first)
    fr_second = sum(1 for s in second if s in ("failed", "error")) / len(second)
    uniform = abs(fr_first - fr_second) <= 0.2 and fail_count >= 2

    if not keywords and not uniform:
        return None

    confidence = "high" if (keywords and uniform) else "medium"

    evidence: list[str] = []
    for kw in keywords[:3]:
        evidence.append(f"failure output contains keyword '{kw}'")
    if uniform:
        evidence.append(
            f"failures uniformly distributed across {n} runs (no clustering)"
        )

    return RootCause(category="randomness", confidence=confidence, evidence=evidence)


def classify_root_cause(
    matrix_row: list[str],
    results: list[dict],
) -> RootCause:
    """Run every classifier and return the highest-priority result."""
    passes = [r for r in results if r.get("status") == "passed"]
    failures = [r for r in results if r.get("status") in ("failed", "error")]

    candidates: list[RootCause] = []
    for cause in (
        _classify_network(failures),
        _classify_timing(passes, failures),
        _classify_ordering(matrix_row),
        _classify_randomness(matrix_row, failures),
    ):
        if cause is not None:
            candidates.append(cause)

    if not candidates:
        return RootCause(
            category="unknown",
            confidence="low",
            evidence=["no clear pattern detected in failure outputs or run order"],
        )

    candidates.sort(key=lambda c: _PRIORITY.get(c.category, 99))
    return candidates[0]


# ── per-test scoring ───────────────────────────────────────────────────────────

def _score_one(
    test_id: str,
    statuses: list[str],
    results: list[dict],
    flaky_threshold: float,
) -> FlakinessReport:
    relevant = [s for s in statuses if s in _REAL_OUTCOMES]
    total = len(relevant)
    passes = sum(1 for s in relevant if s == "passed")
    fails = total - passes

    pass_rate = passes / total if total else 0.0
    flakiness_score = wilson_lower_bound(fails, total)
    upper = wilson_upper_bound(fails, total)
    severity = compute_severity(flakiness_score)
    is_flaky = flakiness_score >= flaky_threshold

    root_cause: RootCause | None = None
    if is_flaky:
        root_cause = classify_root_cause(statuses, results)

    return FlakinessReport(
        test_id=test_id,
        total_runs=total,
        pass_count=passes,
        fail_count=fails,
        pass_rate=pass_rate,
        flakiness_score=flakiness_score,
        confidence_interval=(flakiness_score, upper),
        is_flaky=is_flaky,
        severity=severity,
        root_cause=root_cause,
    )


def score_from_conn(
    conn: sqlite3.Connection,
    min_runs: int = 5,
    flaky_threshold: float = 0.05,
) -> list[FlakinessReport]:
    """Score every test with at least `min_runs` real outcomes."""
    matrix = get_results_matrix(conn)
    reports: list[FlakinessReport] = []
    for test_id, statuses in matrix.items():
        relevant = [s for s in statuses if s in _REAL_OUTCOMES]
        if len(relevant) < min_runs:
            continue
        results = get_results_for_test(conn, test_id)
        reports.append(_score_one(test_id, statuses, results, flaky_threshold))
    return reports


def score_tests(
    db_path: str,
    min_runs: int = 5,
    flaky_threshold: float = 0.05,
) -> list[FlakinessReport]:
    """Open the DB at `db_path` and score every test."""
    conn = open_db(Path(db_path))
    try:
        return score_from_conn(conn, min_runs=min_runs, flaky_threshold=flaky_threshold)
    finally:
        conn.close()


def filter_flaky(reports: list[FlakinessReport]) -> list[FlakinessReport]:
    """Return only flaky tests, sorted by flakiness_score descending."""
    flaky = [r for r in reports if r.is_flaky]
    flaky.sort(key=lambda r: r.flakiness_score, reverse=True)
    return flaky
