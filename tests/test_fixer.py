"""Unit tests for the fixer module."""

from unittest.mock import patch

from autopsy.db import get_cached_ai_fix, open_db, save_ai_fix
from autopsy.fixer import get_fix_suggestion, get_template_fix, strip_ansi
from autopsy.models import FlakinessReport, RootCause

# ── helpers ────────────────────────────────────────────────────────────────────

def _make_report(test_id: str, root_cause: RootCause | None = None) -> FlakinessReport:
    return FlakinessReport(
        test_id=test_id,
        total_runs=10,
        pass_count=5,
        fail_count=5,
        pass_rate=0.5,
        flakiness_score=0.25,
        confidence_interval=(0.25, 0.45),
        is_flaky=True,
        severity="medium",
        root_cause=root_cause,
    )


# ── strip_ansi ─────────────────────────────────────────────────────────────────

def test_strip_ansi_removes_color_codes():
    assert strip_ansi("\x1b[31mred text\x1b[0m") == "red text"


def test_strip_ansi_preserves_plain_text():
    text = "no escape codes here"
    assert strip_ansi(text) == text


# ── template fixes ─────────────────────────────────────────────────────────────

def test_template_ordering_mentions_fixture():
    fix, snippet = get_template_fix(RootCause("ordering", "high", []))
    assert "fixture" in fix.lower() or "isolation" in fix.lower() or "state" in fix.lower()
    assert snippet is not None


def test_template_timing_mentions_sleep_or_mock():
    fix, snippet = get_template_fix(RootCause("timing", "medium", []))
    assert any(kw in fix.lower() for kw in ("sleep", "mock", "timing", "wait"))
    assert snippet is not None


def test_template_randomness_mentions_seed():
    fix, snippet = get_template_fix(RootCause("randomness", "high", []))
    assert "seed" in fix.lower() or "random" in fix.lower()
    assert snippet is not None


def test_template_network_mentions_mock():
    fix, snippet = get_template_fix(RootCause("network", "high", []))
    assert "mock" in fix.lower()
    assert snippet is not None


def test_template_unknown_has_no_snippet():
    fix, snippet = get_template_fix(RootCause("unknown", "low", []))
    assert len(fix) > 10
    assert snippet is None


def test_template_all_known_categories_have_snippets():
    for cat in ("ordering", "timing", "randomness", "network"):
        _, snippet = get_template_fix(RootCause(cat, "high", []))
        assert snippet is not None, f"{cat} should have a code snippet"


# ── get_fix_suggestion: template only ─────────────────────────────────────────

def test_get_fix_suggestion_template_only(tmp_path):
    """use_ai=False always returns source='template' with no ai_fix."""
    cause = RootCause("ordering", "high", ["pass rate gap > 30%"])
    report = _make_report("tests/test_foo.py::test_ordering", cause)
    conn = open_db(tmp_path / "test.db")

    s = get_fix_suggestion(report, [], conn=conn, use_ai=False)

    assert s.source == "template"
    assert s.ai_fix is None
    assert s.from_cache is False
    assert len(s.template_fix) > 0
    assert s.root_cause_category == "ordering"
    conn.close()


def test_get_fix_suggestion_no_root_cause_defaults_to_unknown(tmp_path):
    """A report with root_cause=None uses the 'unknown' template fix."""
    report = _make_report("tests/test_bar.py::test_mystery", root_cause=None)
    conn = open_db(tmp_path / "test.db")

    s = get_fix_suggestion(report, [], conn=conn, use_ai=False)

    assert s.root_cause_category == "unknown"
    assert s.code_snippet is None
    conn.close()


# ── get_fix_suggestion: AI + cache ────────────────────────────────────────────

def test_get_fix_suggestion_cache_hit(tmp_path):
    """When the cache already has a hit, from_cache=True and no API call is made."""
    cause = RootCause("network", "high", ["connection refused"])
    report = _make_report("tests/test_net.py::test_call", cause)
    conn = open_db(tmp_path / "test.db")
    save_ai_fix(conn, report.test_id, "network", "Mock the HTTP client.", "claude-opus-4-7")

    with patch("autopsy.fixer.get_ai_fix") as mock_api:
        s = get_fix_suggestion(report, [], conn=conn, use_ai=True, use_cache=True)

    mock_api.assert_not_called()
    assert s.from_cache is True
    assert s.ai_fix == "Mock the HTTP client."
    assert s.source == "template+ai"
    conn.close()


def test_get_fix_suggestion_saves_to_cache(tmp_path):
    """A fresh AI response is stored in the cache for future calls."""
    cause = RootCause("timing", "medium", ["failures 3× slower"])
    report = _make_report("tests/test_slow.py::test_timer", cause)
    conn = open_db(tmp_path / "test.db")

    with patch("autopsy.fixer.get_ai_fix", return_value="Use monkeypatch.setattr."):
        s = get_fix_suggestion(report, [], conn=conn, use_ai=True, use_cache=True)

    assert s.ai_fix == "Use monkeypatch.setattr."
    assert s.from_cache is False
    assert s.source == "template+ai"
    cached = get_cached_ai_fix(conn, report.test_id, "timing")
    assert cached == "Use monkeypatch.setattr."
    conn.close()


def test_get_fix_suggestion_ai_error_falls_back_to_template(tmp_path):
    """When the AI call raises, ai_fix=None and source stays 'template'."""
    cause = RootCause("randomness", "high", ["uniform failure distribution"])
    report = _make_report("tests/test_rand.py::test_random", cause)
    conn = open_db(tmp_path / "test.db")

    with patch("autopsy.fixer.get_ai_fix", side_effect=Exception("API error")):
        s = get_fix_suggestion(report, [], conn=conn, use_ai=True, use_cache=False)

    assert s.ai_fix is None
    assert s.source == "template"
    conn.close()
