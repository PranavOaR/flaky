"""Unit tests for CLI behavior added in 0.2.0."""

import json
from pathlib import Path

from click.testing import CliRunner

from autopsy import __version__
from autopsy.cli import _load_config, main, score_cmd
from autopsy.db import insert_run, open_db
from autopsy.models import RunRecord, TestResult

# ── helpers ────────────────────────────────────────────────────────────────────

def _populate_db(db_path: Path) -> None:
    """Create a small DB with one stable and one alternating-flaky test."""
    conn = open_db(db_path)
    for i in range(1, 11):
        record = RunRecord(
            run_index=i,
            seed=i * 100,
            started_at="2024-01-01T00:00:00+00:00",
            duration_s=0.1,
            results=[
                TestResult("pkg::test_stable", "passed", 0.05, ""),
                TestResult(
                    "pkg::test_flaky",
                    "failed" if i % 2 else "passed",
                    0.05,
                    "",
                ),
            ],
        )
        insert_run(conn, record, session_id="s1")
    conn.close()


# ── --version flag ─────────────────────────────────────────────────────────────

def test_version_flag_prints_version():
    """`autopsy --version` prints the package version and exits 0."""
    runner = CliRunner()
    result = runner.invoke(main, ["--version"])
    assert result.exit_code == 0
    assert __version__ in result.output


def test_short_version_flag():
    """`autopsy -V` is the short form of --version."""
    runner = CliRunner()
    result = runner.invoke(main, ["-V"])
    assert result.exit_code == 0
    assert __version__ in result.output


def test_no_subcommand_prints_help():
    """Bare `autopsy` shows help, not the banner-only output."""
    runner = CliRunner()
    result = runner.invoke(main, [])
    assert result.exit_code == 0
    assert "Usage:" in result.output


# ── `autopsy score --json` ─────────────────────────────────────────────────────

def test_score_json_output(tmp_path):
    """`autopsy score --json` emits a parseable JSON payload."""
    db = tmp_path / "autopsy_results.db"
    _populate_db(db)

    runner = CliRunner()
    result = runner.invoke(score_cmd, [str(db), "--min-runs", "5", "--json"])

    assert result.exit_code == 0
    payload = json.loads(result.output)

    assert payload["schema_version"] == 1
    assert "tests" in payload
    assert payload["summary"]["total_tests"] == 2
    assert payload["summary"]["flaky_tests"] >= 1

    test_ids = {t["test_id"] for t in payload["tests"]}
    assert "pkg::test_stable" in test_ids
    assert "pkg::test_flaky" in test_ids

    flaky = next(t for t in payload["tests"] if t["test_id"] == "pkg::test_flaky")
    assert flaky["is_flaky"] is True
    assert flaky["root_cause"] is not None
    assert "category" in flaky["root_cause"]


def test_score_json_missing_db(tmp_path):
    """`autopsy score --json` on a missing DB emits an error JSON and exits 1."""
    runner = CliRunner()
    result = runner.invoke(score_cmd, [str(tmp_path / "nope.db"), "--json"])
    assert result.exit_code == 1
    payload = json.loads(result.output)
    assert "error" in payload


# ── _load_config ───────────────────────────────────────────────────────────────

def test_load_config_empty_when_no_pyproject(tmp_path, monkeypatch):
    """Returns empty dict when no pyproject.toml is found."""
    monkeypatch.chdir(tmp_path)
    assert _load_config() == {}


def test_load_config_empty_when_no_tool_autopsy(tmp_path, monkeypatch):
    """Returns empty dict when pyproject.toml has no [tool.autopsy] section."""
    monkeypatch.chdir(tmp_path)
    (tmp_path / "pyproject.toml").write_text("[project]\nname = 'dummy'\n", encoding="utf-8")
    assert _load_config() == {}


def test_load_config_maps_runs(tmp_path, monkeypatch):
    """runs key maps to the 'run' and 'ci' subcommands."""
    monkeypatch.chdir(tmp_path)
    (tmp_path / "pyproject.toml").write_text(
        "[tool.autopsy]\nruns = 25\n", encoding="utf-8"
    )
    cfg = _load_config()
    assert cfg.get("run", {}).get("runs") == 25
    assert cfg.get("ci", {}).get("runs") == 25


def test_load_config_maps_all_keys(tmp_path, monkeypatch):
    """All supported config keys produce the correct default_map entries."""
    monkeypatch.chdir(tmp_path)
    (tmp_path / "pyproject.toml").write_text(
        "[tool.autopsy]\n"
        "runs = 20\n"
        "workers = 4\n"
        "threshold = 0.08\n"
        "min_runs = 3\n"
        'model = "claude-sonnet-4-6"\n',
        encoding="utf-8",
    )
    cfg = _load_config()

    assert cfg["run"]["runs"] == 20
    assert cfg["run"]["workers"] == 4
    assert cfg["ci"]["runs"] == 20

    assert cfg["score"]["threshold"] == 0.08
    assert cfg["ci"]["regression_threshold"] == 0.08

    assert cfg["score"]["min_runs"] == 3
    assert cfg["fix"]["min_runs"] == 3

    assert cfg["fix"]["model"] == "claude-sonnet-4-6"


def test_load_config_stops_at_git_boundary(tmp_path, monkeypatch):
    """Config search does not walk above a .git directory."""
    # pyproject.toml above .git — should not be found
    (tmp_path / "pyproject.toml").write_text(
        "[tool.autopsy]\nruns = 99\n", encoding="utf-8"
    )
    repo = tmp_path / "repo"
    repo.mkdir()
    (repo / ".git").mkdir()
    sub = repo / "sub"
    sub.mkdir()
    monkeypatch.chdir(sub)

    assert _load_config() == {}
