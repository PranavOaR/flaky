"""Unit tests for AI model resolution (0.2.0)."""

from unittest.mock import patch

from autopsy.fixer import (
    DEFAULT_AI_MODEL,
    get_fix_suggestion,
    resolve_ai_model,
)
from autopsy.db import open_db
from autopsy.models import FlakinessReport, RootCause


def _report() -> FlakinessReport:
    return FlakinessReport(
        test_id="t::a",
        total_runs=10,
        pass_count=5,
        fail_count=5,
        pass_rate=0.5,
        flakiness_score=0.25,
        confidence_interval=(0.25, 0.45),
        is_flaky=True,
        severity="medium",
        root_cause=RootCause("network", "high", []),
    )


def test_resolve_default(monkeypatch):
    """No env, no explicit → default model."""
    monkeypatch.delenv("AUTOPSY_AI_MODEL", raising=False)
    assert resolve_ai_model() == DEFAULT_AI_MODEL


def test_resolve_env_override(monkeypatch):
    """AUTOPSY_AI_MODEL env var wins over default."""
    monkeypatch.setenv("AUTOPSY_AI_MODEL", "claude-haiku-4-5-20251001")
    assert resolve_ai_model() == "claude-haiku-4-5-20251001"


def test_resolve_explicit_overrides_env(monkeypatch):
    """Explicit arg beats env var."""
    monkeypatch.setenv("AUTOPSY_AI_MODEL", "claude-haiku-4-5-20251001")
    assert resolve_ai_model("claude-sonnet-4-6") == "claude-sonnet-4-6"


def test_get_fix_suggestion_passes_model(tmp_path, monkeypatch):
    """When --model is supplied, get_ai_fix is called with that model id."""
    monkeypatch.delenv("AUTOPSY_AI_MODEL", raising=False)
    conn = open_db(tmp_path / "test.db")

    with patch("autopsy.fixer.get_ai_fix", return_value="ok") as mock_api:
        get_fix_suggestion(
            _report(),
            ["connection refused"],
            conn=conn,
            use_ai=True,
            use_cache=False,
            model="claude-sonnet-4-6",
        )

    mock_api.assert_called_once()
    # `model` is the 4th positional arg in get_ai_fix
    assert mock_api.call_args.args[3] == "claude-sonnet-4-6"
    conn.close()
