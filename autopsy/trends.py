"""Trend tracking and regression detection across test sessions."""

from dataclasses import dataclass, field

from autopsy.db import get_all_sessions, get_results_by_session, open_db
from autopsy.scorer import wilson_lower_bound

# Block characters for sparklines, index 0 (empty) to 8 (full)
_SPARK_CHARS = " ▁▂▃▄▅▆▇█"

_REAL_OUTCOMES = ("passed", "failed", "error")


@dataclass
class SessionScore:
    """Flakiness metrics for a single test within one session."""

    session_id: str
    started_at: str
    label: "str | None"
    flakiness_score: float
    pass_rate: float
    total_runs: int


@dataclass
class TrendReport:
    """Per-test trend summary across all sessions."""

    test_id: str
    sessions: list[SessionScore] = field(default_factory=list)
    trend: str = "new"          # regression|improvement|worsening|stable_flaky|stable_clean|new|gone
    trend_delta: float = 0.0    # flakiness_score[-1] - flakiness_score[-2]; 0.0 if one session
    sparkline: str = ""         # ASCII sparkline of flakiness over time


# ── sparkline ─────────────────────────────────────────────────────────────────

def make_sparkline(scores: list[float], width: int = 8) -> str:
    """Generate ASCII sparkline from list of flakiness scores (0.0–1.0)."""
    if not scores:
        return ""
    chars: list[str] = []
    for s in scores[:width]:
        # Clamp to [0, 1], map to index 0–8
        idx = min(8, int(max(0.0, min(1.0, s)) * 8.999))
        chars.append(_SPARK_CHARS[idx])
    return "".join(chars)


# ── trend classification ───────────────────────────────────────────────────────

def _classify_trend(
    sessions: list[SessionScore],
    regression_threshold: float = 0.10,
) -> tuple[str, float]:
    """Return (trend_label, delta) given ordered session scores."""
    if len(sessions) == 0:
        return "new", 0.0

    latest = sessions[-1].flakiness_score

    if len(sessions) == 1:
        return "new", 0.0

    previous = sessions[-2].flakiness_score
    delta = latest - previous

    was_clean = previous < 0.05
    is_clean = latest < 0.05
    was_flaky = previous >= 0.05
    is_flaky = latest >= 0.05

    if was_clean and is_flaky:
        trend = "regression"
    elif was_flaky and is_clean:
        trend = "improvement"
    elif was_flaky and is_flaky and delta > regression_threshold:
        trend = "worsening"
    elif was_flaky and is_flaky:
        trend = "stable_flaky"
    else:
        trend = "stable_clean"

    return trend, delta


# ── per-test session scoring ───────────────────────────────────────────────────

def _score_session(
    session_meta: dict,
    statuses: list[str],
) -> SessionScore:
    """Compute a SessionScore for one test in one session."""
    relevant = [s for s in statuses if s in _REAL_OUTCOMES]
    total = len(relevant)
    if total == 0:
        return SessionScore(
            session_id=session_meta["id"],
            started_at=session_meta["started_at"],
            label=session_meta.get("label"),
            flakiness_score=0.0,
            pass_rate=0.0,
            total_runs=0,
        )

    passes = sum(1 for s in relevant if s == "passed")
    fails = total - passes
    pass_rate = passes / total
    flakiness_score = wilson_lower_bound(fails, total)

    return SessionScore(
        session_id=session_meta["id"],
        started_at=session_meta["started_at"],
        label=session_meta.get("label"),
        flakiness_score=flakiness_score,
        pass_rate=pass_rate,
        total_runs=total,
    )


# ── public API ─────────────────────────────────────────────────────────────────

def compute_trends(
    db_path: str,
    min_sessions: int = 2,
    regression_threshold: float = 0.10,
) -> list[TrendReport]:
    """Compute per-test flakiness trend across all sessions."""
    from pathlib import Path

    conn = open_db(Path(db_path))
    try:
        session_rows = get_all_sessions(conn)                        # ordered ASC
        results_by_session = get_results_by_session(conn)           # {sid: {tid: [status...]}}
    finally:
        conn.close()

    session_meta: dict[str, dict] = {s["id"]: s for s in session_rows}

    # Collect all test ids that appear in at least one session
    all_test_ids: set[str] = set()
    for tid_map in results_by_session.values():
        all_test_ids.update(tid_map.keys())

    reports: list[TrendReport] = []

    for test_id in sorted(all_test_ids):
        session_scores: list[SessionScore] = []

        for sid in [s["id"] for s in session_rows]:  # maintain chronological order
            if sid not in results_by_session:
                continue
            tid_map = results_by_session[sid]
            if test_id not in tid_map:
                continue
            meta = session_meta.get(sid, {"id": sid, "started_at": "", "label": None})
            sc = _score_session(meta, tid_map[test_id])
            session_scores.append(sc)

        if len(session_scores) < min_sessions:
            continue

        trend, delta = _classify_trend(session_scores, regression_threshold)
        spark = make_sparkline([sc.flakiness_score for sc in session_scores])

        reports.append(TrendReport(
            test_id=test_id,
            sessions=session_scores,
            trend=trend,
            trend_delta=delta,
            sparkline=spark,
        ))

    return reports


def get_regressions(reports: list[TrendReport]) -> list[TrendReport]:
    """Return only tests with trend == 'regression' or 'worsening', sorted by delta desc."""
    filtered = [r for r in reports if r.trend in ("regression", "worsening")]
    filtered.sort(key=lambda r: r.trend_delta, reverse=True)
    return filtered


def compare_to_baseline(
    current_scores: dict[str, float],
    baseline_scores: dict[str, float],
    regression_threshold: float = 0.10,
) -> list[dict]:
    """Compare current scores against baseline; return per-test status dicts."""
    results: list[dict] = []

    all_ids = set(current_scores) | set(baseline_scores)

    for test_id in sorted(all_ids):
        in_current = test_id in current_scores
        in_baseline = test_id in baseline_scores

        if in_current and not in_baseline:
            results.append({
                "test_id": test_id,
                "current": current_scores[test_id],
                "baseline": None,
                "delta": None,
                "status": "new",
            })
        elif in_baseline and not in_current:
            results.append({
                "test_id": test_id,
                "current": None,
                "baseline": baseline_scores[test_id],
                "delta": None,
                "status": "gone",
            })
        else:
            current = current_scores[test_id]
            baseline = baseline_scores[test_id]
            delta = current - baseline

            if delta > regression_threshold:
                status = "regression"
            elif delta < -regression_threshold:
                status = "improvement"
            else:
                status = "stable"

            results.append({
                "test_id": test_id,
                "current": current,
                "baseline": baseline,
                "delta": delta,
                "status": status,
            })

    return results
