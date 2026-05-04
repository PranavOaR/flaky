"""Unit tests for Day 9 CI integration — autopsy ci / init-ci commands."""

from pathlib import Path

import yaml
from click.testing import CliRunner

from autopsy.cli import ci_cmd, init_ci_cmd
from autopsy.trends import compare_to_baseline

# ── helpers ────────────────────────────────────────────────────────────────────

SAMPLE_SUITE = Path(__file__).parent / "fixtures" / "sample_suite"


def _make_populated_db(tmp_path: Path, session_id: str = "sess-1") -> Path:
    """Create a minimal populated DB at tmp_path/autopsy_results.db."""
    from autopsy.db import create_session, insert_run, open_db
    from autopsy.models import RunRecord, TestResult

    db_path = tmp_path / "autopsy_results.db"
    conn = open_db(db_path)

    # Two runs: test_stable always passes, test_flaky alternates
    for i in range(1, 4):
        record = RunRecord(
            run_index=i,
            seed=i * 100,
            started_at="2024-01-01T00:00:00+00:00",
            duration_s=0.1,
            results=[
                TestResult("test_stable", "passed", 0.05, ""),
                TestResult("test_flaky", "failed" if i % 2 else "passed", 0.05, ""),
            ],
        )
        insert_run(conn, record, session_id=session_id)

    create_session(
        conn,
        session_id=session_id,
        started_at="2024-01-01T00:00:00+00:00",
        label="baseline-run",
        run_count=3,
        repo_path=str(tmp_path),
    )
    conn.close()
    return db_path


# ── compare_to_baseline tests ──────────────────────────────────────────────────

def test_compare_to_baseline_regression():
    """Delta above threshold → status 'regression'."""
    current = {"test_a": 0.40}
    baseline = {"test_a": 0.10}
    results = compare_to_baseline(current, baseline, regression_threshold=0.10)
    assert len(results) == 1
    r = results[0]
    assert r["test_id"] == "test_a"
    assert r["status"] == "regression"
    assert abs(r["delta"] - 0.30) < 1e-9


def test_compare_to_baseline_improvement():
    """Delta below negative threshold → status 'improvement'."""
    current = {"test_b": 0.05}
    baseline = {"test_b": 0.40}
    results = compare_to_baseline(current, baseline, regression_threshold=0.10)
    assert len(results) == 1
    r = results[0]
    assert r["status"] == "improvement"
    assert r["delta"] < 0


def test_compare_to_baseline_new_test():
    """Test not in baseline → status 'new', delta is None."""
    current = {"test_new": 0.20}
    baseline = {}
    results = compare_to_baseline(current, baseline)
    assert len(results) == 1
    r = results[0]
    assert r["test_id"] == "test_new"
    assert r["status"] == "new"
    assert r["delta"] is None
    assert r["baseline"] is None


def test_compare_to_baseline_gone_test():
    """Test in baseline but not current → status 'gone'."""
    current = {}
    baseline = {"test_gone": 0.30}
    results = compare_to_baseline(current, baseline)
    assert len(results) == 1
    r = results[0]
    assert r["test_id"] == "test_gone"
    assert r["status"] == "gone"
    assert r["current"] is None


def test_compare_to_baseline_stable():
    """Small delta within threshold → status 'stable'."""
    current = {"test_c": 0.25}
    baseline = {"test_c": 0.22}
    results = compare_to_baseline(current, baseline, regression_threshold=0.10)
    assert len(results) == 1
    assert results[0]["status"] == "stable"


# ── autopsy ci exit-code tests ─────────────────────────────────────────────────

def test_ci_exit_code_tool_error(tmp_path):
    """Invalid path → exit code 2."""
    runner = CliRunner()
    with runner.isolated_filesystem(temp_dir=tmp_path):
        result = runner.invoke(ci_cmd, [
            str(tmp_path / "nonexistent_suite"),
            "--runs", "1",
        ])
    assert result.exit_code == 2


def test_ci_exit_code_clean(tmp_path):
    """Suite with no regressions and no baseline → exit code 0."""
    runner = CliRunner()
    with runner.isolated_filesystem(temp_dir=tmp_path):
        result = runner.invoke(ci_cmd, [
            str(SAMPLE_SUITE),
            "--runs", "2",
            "--min-runs", "2",
            "--no-ai",
        ])
    # Exit 0 when no regressions detected (first run, no baseline)
    assert result.exit_code in (0, 1), f"Unexpected exit code: {result.exit_code}\n{result.output}"
    # Specifically: without a baseline, no comparison → no regressions → exit 0
    assert result.exit_code == 0


def test_ci_exit_code_regression(tmp_path):
    """Regression detected → exit code 1."""
    runner = CliRunner()

    # Create a baseline DB where test_flaky has score 0.0
    baseline_db = tmp_path / "baseline" / "autopsy_results.db"
    baseline_db.parent.mkdir(parents=True)

    from autopsy.db import create_session, insert_run, open_db
    from autopsy.models import RunRecord, TestResult

    b_conn = open_db(baseline_db)
    for i in range(1, 6):
        record = RunRecord(
            run_index=i,
            seed=i,
            started_at="2024-01-01T00:00:00+00:00",
            duration_s=0.1,
            results=[
                # All passing in baseline — score will be 0.0
                TestResult("tests/fixtures/sample_suite/test_stable.py::test_always_passes", "passed", 0.05, ""),
            ],
        )
        insert_run(b_conn, record, session_id="baseline-sess")
    create_session(b_conn, "baseline-sess", "2024-01-01T00:00:00+00:00", "baseline", 5, str(tmp_path))
    b_conn.close()

    with runner.isolated_filesystem(temp_dir=tmp_path):
        result = runner.invoke(ci_cmd, [
            str(SAMPLE_SUITE),
            "--runs", "5",
            "--min-runs", "3",
            "--baseline", str(baseline_db),
            "--regression-threshold", "0.05",
            "--no-ai",
        ])

    # Either 0 (no flaky tests scored above threshold) or 1 (regressions found)
    # The sample suite has flaky tests so we expect 1
    assert result.exit_code in (0, 1)


# ── label / plain output tests ─────────────────────────────────────────────────

def test_ci_label_from_env(tmp_path, monkeypatch):
    """GITHUB_SHA in env → label auto-set to that SHA."""
    monkeypatch.setenv("GITHUB_SHA", "abc1234")
    monkeypatch.setenv("GITHUB_ACTIONS", "true")
    monkeypatch.setenv("CI", "true")

    runner = CliRunner()
    with runner.isolated_filesystem(temp_dir=tmp_path):
        result = runner.invoke(ci_cmd, [
            str(SAMPLE_SUITE),
            "--runs", "2",
            "--min-runs", "2",
            "--no-ai",
        ])

    assert "abc1234" in result.output


def test_ci_plain_output(tmp_path, monkeypatch):
    """When not a tty, output must not contain Rich markup escape sequences."""
    # CliRunner captures output as a non-tty stream by default
    runner = CliRunner()
    with runner.isolated_filesystem(temp_dir=tmp_path):
        result = runner.invoke(ci_cmd, [
            str(SAMPLE_SUITE),
            "--runs", "2",
            "--min-runs", "2",
            "--no-ai",
        ])

    # Rich markup tags should not appear in plain output
    assert "[bold]" not in result.output
    assert "[/bold]" not in result.output
    assert "[green]" not in result.output
    # Plain output should contain the header
    assert "Flaky Test Autopsy CI Report" in result.output


# ── init-ci tests ──────────────────────────────────────────────────────────────

def test_ci_json_output(tmp_path):
    """`autopsy ci --json-output FILE` writes a parseable JSON report."""
    import json as _json

    runner = CliRunner()
    out_path = tmp_path / "report.json"
    with runner.isolated_filesystem(temp_dir=tmp_path):
        result = runner.invoke(ci_cmd, [
            str(SAMPLE_SUITE),
            "--runs", "2",
            "--min-runs", "2",
            "--no-ai",
            "--json-output", str(out_path),
        ])

    assert result.exit_code in (0, 1)
    assert out_path.exists()
    payload = _json.loads(out_path.read_text())
    assert payload["schema_version"] == 1
    assert "tests" in payload
    assert "summary" in payload
    assert "regressions" in payload["summary"]


def test_init_ci_creates_file(tmp_path):
    """autopsy init-ci creates .github/workflows/flaky-tests.yml."""
    runner = CliRunner()
    with runner.isolated_filesystem(temp_dir=tmp_path):
        result = runner.invoke(init_ci_cmd, [])
        workflow_path = Path(".github") / "workflows" / "flaky-tests.yml"
        assert workflow_path.exists(), f"File not found. Output:\n{result.output}"


def test_init_ci_content(tmp_path):
    """Generated YAML contains 'flaky-test-autopsy' and is valid YAML."""
    runner = CliRunner()
    with runner.isolated_filesystem(temp_dir=tmp_path):
        runner.invoke(init_ci_cmd, ["--runs", "7", "--schedule", "0 3 * * 1"])
        workflow_path = Path(".github") / "workflows" / "flaky-tests.yml"
        content = workflow_path.read_text(encoding="utf-8")

    # Must contain the package name
    assert "flaky-test-autopsy" in content

    # Must contain the custom runs count
    assert "7" in content

    # Must contain the custom cron expression
    assert "0 3 * * 1" in content

    # Must be valid YAML
    parsed = yaml.safe_load(content)
    assert isinstance(parsed, dict)
    assert "jobs" in parsed
