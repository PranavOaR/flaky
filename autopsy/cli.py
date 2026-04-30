"""Click CLI entry points for flaky-test-autopsy."""

import os
import sys
import uuid
from datetime import datetime, timezone
from pathlib import Path

import click
from rich.console import Console
from rich.rule import Rule
from rich.syntax import Syntax
from rich.table import Table

from autopsy.banner import print_banner
from autopsy.db import (
    clear_results,
    create_session,
    get_all_sessions,
    get_db_info,
    get_results_for_test,
    get_run_detail,
    get_run_summary,
    open_db,
)
from autopsy.models import FlakinessReport, FixSuggestion
from autopsy.runner import run_suite
from autopsy.scorer import filter_flaky, score_from_conn

_DB_FILENAME = "autopsy_results.db"

_SEVERITY_STYLES = {
    "critical": "bold red",
    "high": "red",
    "medium": "yellow",
    "low": "cyan",
    "none": "dim",
}

_CAUSE_STYLES = {
    "ordering": "magenta",
    "timing": "yellow",
    "randomness": "blue",
    "network": "red",
    "unknown": "dim",
}


@click.group()
def main() -> None:
    """flaky-test-autopsy: detect and diagnose flaky tests."""
    print_banner()


# ── autopsy run ────────────────────────────────────────────────────────────────

@main.command("run")
@click.argument("path", type=click.Path(exists=False))
@click.option("--runs", default=10, show_default=True, help="Number of full suite reruns.")
@click.option("--workers", default=1, show_default=True, help="Parallel workers (sequential if 1).")
@click.option("--verbose", is_flag=True, default=False, help="Stream pytest output live.")
@click.option("--fresh", is_flag=True, default=False, help="Clear existing DB data before running.")
@click.option("--label", default=None, help="Human-readable label for this session.")
def run_cmd(path: str, runs: int, workers: int, verbose: bool, fresh: bool, label: "str | None") -> None:
    """Run a pytest suite repeatedly, then score and classify flaky tests."""
    console = Console()
    suite_path = Path(path)

    if not suite_path.exists():
        console.print(f"[bold red]Error:[/] path does not exist: {suite_path}")
        raise SystemExit(1)

    db_path = Path.cwd() / _DB_FILENAME
    conn = open_db(db_path)

    if fresh:
        clear_results(conn)
        console.print("[dim]Cleared existing results (--fresh).[/]")

    session_id = str(uuid.uuid4())
    started_at = datetime.now(timezone.utc).isoformat()

    try:
        run_suite(
            suite_path=suite_path,
            num_runs=runs,
            workers=workers,
            verbose=verbose,
            conn=conn,
            console=console,
            session_id=session_id,
        )
        create_session(
            conn,
            session_id=session_id,
            started_at=started_at,
            label=label,
            run_count=runs,
            repo_path=str(suite_path.resolve()),
        )
        reports = score_from_conn(conn, min_runs=1, flaky_threshold=0.05)
        _print_scored_table(reports, db_path, console, only_flaky=False, explain=False)
    finally:
        conn.close()


# ── autopsy score ──────────────────────────────────────────────────────────────

@main.command("score")
@click.argument("db_path", type=click.Path(exists=False), default=_DB_FILENAME)
@click.option("--min-runs", default=5, show_default=True, help="Skip tests with fewer than N runs.")
@click.option("--threshold", default=0.05, show_default=True, type=float, help="Flakiness threshold.")
@click.option("--all", "show_all", is_flag=True, default=False, help="Show non-flaky tests too.")
@click.option("--explain", is_flag=True, default=False, help="Print evidence per flaky test.")
def score_cmd(db_path: str, min_runs: int, threshold: float, show_all: bool, explain: bool) -> None:
    """Score and classify flaky tests in an existing results DB."""
    console = Console()
    path = Path(db_path)

    if not path.exists():
        console.print(f"[bold red]Error:[/] database not found: {path}")
        raise SystemExit(1)

    conn = open_db(path)
    try:
        reports = score_from_conn(conn, min_runs=min_runs, flaky_threshold=threshold)
        _print_scored_table(reports, path, console, only_flaky=not show_all, explain=explain)
    finally:
        conn.close()


# ── autopsy info ───────────────────────────────────────────────────────────────

@main.command("info")
@click.argument("db_path", type=click.Path(exists=False), default=_DB_FILENAME)
def info_cmd(db_path: str) -> None:
    """Show a summary of recorded runs in a DB file."""
    console = Console()
    path = Path(db_path)

    if not path.exists():
        console.print(f"[bold red]Error:[/] database not found: {path}")
        raise SystemExit(1)

    conn = open_db(path)
    try:
        _print_info(conn, path, console)
    finally:
        conn.close()


# ── autopsy fix ───────────────────────────────────────────────────────────────

@main.command("fix")
@click.argument("db_path", type=click.Path(exists=False), default=_DB_FILENAME)
@click.option("--ai", "use_ai", is_flag=True, default=False,
              help="Generate AI-powered fix suggestions (requires ANTHROPIC_API_KEY).")
@click.option("--no-cache", "no_cache", is_flag=True, default=False,
              help="Bypass the AI response cache.")
@click.option("--min-runs", default=5, show_default=True, help="Skip tests with fewer than N runs.")
@click.option("--threshold", default=0.05, show_default=True, type=float,
              help="Flakiness threshold.")
@click.option("--output", type=click.Path(), default=None,
              help="Write Markdown report to FILE instead of printing.")
def fix_cmd(
    db_path: str,
    use_ai: bool,
    no_cache: bool,
    min_runs: int,
    threshold: float,
    output: "str | None",
) -> None:
    """Generate fix suggestions for flaky tests in a results DB."""
    from autopsy.fixer import get_fix_suggestion

    console = Console()
    path = Path(db_path)

    if not path.exists():
        console.print(f"[bold red]Error:[/] database not found: {path}")
        raise SystemExit(1)

    conn = open_db(path)
    try:
        reports = score_from_conn(conn, min_runs=min_runs, flaky_threshold=threshold)
        flaky = filter_flaky(reports)

        if not flaky:
            console.print("\n[green]No flaky tests detected.[/]")
            console.print(f"[bold]Database:[/] {path}\n")
            return

        if use_ai:
            console.print(
                f"\n[dim]Generating AI fix suggestions for {len(flaky)} flaky test(s)…[/]"
            )

        pairs: list[tuple[FlakinessReport, FixSuggestion]] = []
        for r in flaky:
            results = get_results_for_test(conn, r.test_id)
            failure_outputs = [
                row["stdout"] or ""
                for row in results
                if row["status"] in ("failed", "error")
            ]
            suggestion = get_fix_suggestion(
                r,
                failure_outputs,
                conn=conn,
                use_ai=use_ai,
                use_cache=not no_cache,
            )
            pairs.append((r, suggestion))

        if output:
            _write_fix_report(pairs, path, output, console)
        else:
            _print_fix_report(pairs, console, use_ai)
    finally:
        conn.close()


# ── autopsy ci ────────────────────────────────────────────────────────────────

def _detect_ci_env() -> dict:
    """Return CI environment metadata dict."""
    is_ci = (
        os.environ.get("CI") == "true"
        or os.environ.get("GITHUB_ACTIONS") == "true"
        or os.environ.get("GITLAB_CI") == "true"
    )
    label = (
        os.environ.get("GITHUB_SHA")
        or os.environ.get("CI_COMMIT_SHA")
        or ("ci-run" if is_ci else None)
    )
    ci_platform = None
    if os.environ.get("GITHUB_ACTIONS") == "true":
        ci_platform = "GitHub Actions"
    elif os.environ.get("GITLAB_CI") == "true":
        ci_platform = "GitLab CI"
    elif is_ci:
        ci_platform = "CI"
    return {"is_ci": is_ci, "label": label, "platform": ci_platform}


def _is_plain_output() -> bool:
    """Return True when output should be plain text (no Rich markup)."""
    return (
        os.environ.get("NO_COLOR") is not None
        or not sys.stdout.isatty()
    )


@main.command("ci")
@click.argument("path", type=click.Path(exists=False))
@click.option("--runs", default=None, type=int,
              help="Number of full suite reruns (default: 5 in CI, 10 locally).")
@click.option("--label", default=None, help="Human-readable label for this session.")
@click.option("--baseline", "baseline_db", default=None, type=click.Path(),
              help="Path to baseline DB to compare against.")
@click.option("--regression-threshold", default=0.10, show_default=True, type=float,
              help="Flakiness delta above which a test is flagged as regression.")
@click.option("--min-runs", "min_runs", default=3, show_default=True, type=int,
              help="Minimum runs before flagging a test.")
@click.option("--output", type=click.Path(), default=None,
              help="Write markdown CI report to FILE.")
@click.option("--no-ai", "no_ai", is_flag=True, default=False,
              help="Skip AI fix suggestions.")
def ci_cmd(
    path: str,
    runs: "int | None",
    label: "str | None",
    baseline_db: "str | None",
    regression_threshold: float,
    min_runs: int,
    output: "str | None",
    no_ai: bool,
) -> None:
    """Run suite, score, compare baseline, exit 0/1/2 for CI."""
    ci_env = _detect_ci_env()
    plain = _is_plain_output()

    # Resolve defaults dependent on CI context
    if runs is None:
        runs = 5 if ci_env["is_ci"] else 10
    if label is None:
        label = ci_env["label"]

    console = Console(highlight=False)

    suite_path = Path(path)
    if not suite_path.exists():
        _ci_print(plain, f"Error: path does not exist: {suite_path}")
        raise SystemExit(2)

    db_path = Path.cwd() / _DB_FILENAME
    try:
        conn = open_db(db_path)
    except Exception as exc:
        _ci_print(plain, f"Error: cannot open database: {exc}")
        raise SystemExit(2)

    session_id = str(uuid.uuid4())
    started_at = datetime.now(timezone.utc).isoformat()
    t_start = datetime.now(timezone.utc)

    try:
        run_suite(
            suite_path=suite_path,
            num_runs=runs,
            workers=1,
            verbose=False,
            conn=conn,
            console=console,
            session_id=session_id,
        )
    except Exception as exc:
        _ci_print(plain, f"Error: test run failed: {exc}")
        conn.close()
        raise SystemExit(2)

    duration_s = (datetime.now(timezone.utc) - t_start).total_seconds()

    create_session(
        conn,
        session_id=session_id,
        started_at=started_at,
        label=label,
        run_count=runs,
        repo_path=str(suite_path.resolve()),
    )

    reports = score_from_conn(conn, min_runs=min_runs, flaky_threshold=0.05)

    # Build current flakiness score map
    current_scores: dict[str, float] = {r.test_id: r.flakiness_score for r in reports}

    # Load baseline scores if requested
    baseline_scores: "dict[str, float] | None" = None
    baseline_label: "str | None" = None
    if baseline_db:
        baseline_path = Path(baseline_db)
        if baseline_path.exists():
            try:
                from autopsy.scorer import score_from_conn as _score
                b_conn = open_db(baseline_path)
                try:
                    b_reports = _score(b_conn, min_runs=1, flaky_threshold=0.0)
                    baseline_scores = {r.test_id: r.flakiness_score for r in b_reports}
                    # Best-effort label from latest session
                    b_sessions = get_all_sessions(b_conn)
                    if b_sessions:
                        last = b_sessions[-1]
                        baseline_label = last.get("label") or last["id"][:8]
                finally:
                    b_conn.close()
            except Exception:
                baseline_scores = None
        # If file doesn't exist yet (first run), silently proceed with no baseline

    # Compare against previous session in same DB if no explicit baseline provided
    if baseline_scores is None and not baseline_db:
        sessions = get_all_sessions(conn)
        # Only compare if there's a previous session besides the one we just created
        prev_sessions = [s for s in sessions if s["id"] != session_id]
        if prev_sessions:
            from autopsy.db import get_results_by_session
            from autopsy.scorer import wilson_lower_bound as _wlb
            prev_sid = prev_sessions[-1]["id"]
            results_by_session = get_results_by_session(conn)
            if prev_sid in results_by_session:
                baseline_scores = {}
                _REAL = ("passed", "failed", "error")
                for tid, statuses in results_by_session[prev_sid].items():
                    relevant = [s for s in statuses if s in _REAL]
                    total = len(relevant)
                    fails = sum(1 for s in relevant if s in ("failed", "error"))
                    baseline_scores[tid] = _wlb(fails, total)
                baseline_label = prev_sessions[-1].get("label") or prev_sessions[-1]["id"][:8]

    # Run comparison
    comparisons: list[dict] = []
    regressions: list[dict] = []
    if baseline_scores is not None:
        from autopsy.trends import compare_to_baseline
        comparisons = compare_to_baseline(current_scores, baseline_scores, regression_threshold)
        regressions = [c for c in comparisons if c["status"] == "regression"]

    conn.close()

    # Build fix suggestions for regressions if --output is set and not --no-ai
    fix_pairs: "list[tuple[FlakinessReport, FixSuggestion]] | None" = None
    if output and not no_ai:
        from autopsy.fixer import get_fix_suggestion
        from autopsy.db import get_results_for_test as _get_results
        try:
            conn2 = open_db(db_path)
            flaky = filter_flaky(reports)
            fix_pairs = []
            for r in flaky:
                results = _get_results(conn2, r.test_id)
                failure_outputs = [
                    row["stdout"] or ""
                    for row in results
                    if row["status"] in ("failed", "error")
                ]
                suggestion = get_fix_suggestion(
                    r,
                    failure_outputs,
                    conn=conn2,
                    use_ai=False,
                    use_cache=True,
                )
                fix_pairs.append((r, suggestion))
            conn2.close()
        except Exception:
            fix_pairs = None

    # Print summary
    _print_ci_summary(
        plain=plain,
        path=path,
        runs=runs,
        label=label,
        ci_platform=ci_env["platform"],
        duration_s=duration_s,
        reports=reports,
        comparisons=comparisons,
        regressions=regressions,
        db_path=db_path,
        output=output,
    )

    # Write markdown report if requested
    if output:
        _write_ci_report(
            output_path=output,
            path=path,
            runs=runs,
            label=label,
            baseline_label=baseline_label,
            duration_s=duration_s,
            reports=reports,
            comparisons=comparisons,
            fix_pairs=fix_pairs,
        )
        if plain:
            print(f"Details: {output}")
        else:
            console.print(f"[green]CI report written to:[/] {output}\n")

    raise SystemExit(1 if regressions else 0)


def _ci_print(plain: bool, message: str) -> None:
    """Print a message respecting plain vs Rich mode."""
    print(message)


def _print_ci_summary(
    plain: bool,
    path: str,
    runs: int,
    label: "str | None",
    ci_platform: "str | None",
    duration_s: float,
    reports: list[FlakinessReport],
    comparisons: list[dict],
    regressions: list[dict],
    db_path: Path,
    output: "str | None",
) -> None:
    """Print the CI summary in plain or Rich format."""
    # Build a lookup for comparison status by test_id
    comp_by_id: dict[str, dict] = {c["test_id"]: c for c in comparisons}

    label_str = label or "—"
    platform_str = f" ({ci_platform})" if ci_platform else ""
    session_str = f"{label_str}{platform_str}"

    if plain:
        print("=== Flaky Test Autopsy CI Report ===")
        print(f"Repo:    {path}")
        print(f"Runs:    {runs}")
        print(f"Session: {session_str}")
        print(f"Time:    {duration_s:.1f}s")
        print()
        print("Results:")
        for r in reports:
            comp = comp_by_id.get(r.test_id)
            cause_str = ""
            if r.root_cause and r.is_flaky:
                cause_str = f" [{r.root_cause.category}]"
            if comp and comp["status"] == "regression" and comp["delta"] is not None:
                delta_pct = comp["delta"] * 100
                sign = "+" if delta_pct >= 0 else ""
                tag = f"FAIL  {r.test_id:<60} ({r.flakiness_score*100:.0f}% flaky) (REGRESSION {sign}{delta_pct:.0f}%){cause_str}"
            elif r.is_flaky:
                tag = f"WARN  {r.test_id:<60} ({r.flakiness_score*100:.0f}% flaky){cause_str}"
            else:
                tag = f"PASS  {r.test_id:<60} ({r.flakiness_score*100:.0f}% flaky)"
            print(f"  {tag}")

        print()
        n_reg = len(regressions)
        if n_reg == 0:
            print("Summary: No regressions detected.")
        else:
            print(f"Summary: {n_reg} regression(s) detected.")
            print(f"Fix:     autopsy fix {db_path}")

        if output:
            print(f"Details: {output}")

        n_reg = len(regressions)
        print(f"\nExit code: {1 if n_reg else 0}")
    else:
        from rich.console import Console as _Console
        console = _Console(highlight=False)
        console.print("\n[bold]=== Flaky Test Autopsy CI Report ===[/]")
        console.print(f"[bold]Repo:[/]    {path}")
        console.print(f"[bold]Runs:[/]    {runs}")
        console.print(f"[bold]Session:[/] {session_str}")
        console.print(f"[bold]Time:[/]    {duration_s:.1f}s\n")

        table = Table(show_header=True, header_style="bold magenta")
        table.add_column("Status", justify="center")
        table.add_column("Test", style="cyan", no_wrap=False, min_width=30)
        table.add_column("Flakiness", justify="right")
        table.add_column("Root Cause", justify="left")
        table.add_column("Delta", justify="right")

        for r in reports:
            comp = comp_by_id.get(r.test_id)
            cause_str = r.root_cause.category if (r.root_cause and r.is_flaky) else "—"

            if comp and comp["status"] == "regression" and comp["delta"] is not None:
                delta_pct = comp["delta"] * 100
                sign = "+" if delta_pct >= 0 else ""
                status_cell = "[bold red]FAIL[/]"
                delta_cell = f"[bold red]{sign}{delta_pct:.0f}%[/]"
            elif r.is_flaky:
                status_cell = "[yellow]WARN[/]"
                delta_cell = comp["delta"] and f"{comp['delta']*100:+.0f}%" or "—" if comp else "—"
            else:
                status_cell = "[green]PASS[/]"
                delta_cell = "—"

            table.add_row(
                status_cell,
                r.test_id,
                f"{r.flakiness_score*100:.0f}%",
                cause_str,
                delta_cell,
            )

        console.print(table)
        n_reg = len(regressions)
        if n_reg == 0:
            console.print("\n[green]Summary: No regressions detected.[/]")
        else:
            console.print(f"\n[bold red]Summary: {n_reg} regression(s) detected.[/]")
            console.print(f"[bold]Fix:[/] autopsy fix {db_path}")
        console.print()


def _write_ci_report(
    output_path: str,
    path: str,
    runs: int,
    label: "str | None",
    baseline_label: "str | None",
    duration_s: float,
    reports: list[FlakinessReport],
    comparisons: list[dict],
    fix_pairs: "list[tuple[FlakinessReport, FixSuggestion]] | None",
) -> None:
    """Write the markdown CI report to disk."""
    comp_by_id: dict[str, dict] = {c["test_id"]: c for c in comparisons}
    label_str = label or "—"
    baseline_str = baseline_label or "—"

    lines: list[str] = [
        "## Flaky Test Autopsy Report\n",
        "| | |",
        "|---|---|",
        f"| **Repo** | `{path}` |",
        f"| **Runs** | {runs} |",
        f"| **Session** | `{label_str}` |",
        f"| **Baseline** | `{baseline_str}` |",
        f"| **Duration** | {duration_s:.1f}s |",
        "",
        "### Results\n",
        "| Status | Test | Flakiness | Root Cause | Delta |",
        "|--------|------|-----------|------------|-------|",
    ]

    for r in reports:
        comp = comp_by_id.get(r.test_id)
        cause_str = r.root_cause.category if (r.root_cause and r.is_flaky) else "—"

        if comp and comp["status"] == "regression" and comp["delta"] is not None:
            delta_pct = comp["delta"] * 100
            sign = "+" if delta_pct >= 0 else ""
            status_icon = "🔴"
            delta_cell = f"**{sign}{delta_pct:.0f}%**"
        elif r.is_flaky:
            status_icon = "⚠️"
            if comp and comp["delta"] is not None:
                delta_pct = comp["delta"] * 100
                sign = "+" if delta_pct >= 0 else ""
                delta_cell = f"{sign}{delta_pct:.0f}%"
            else:
                delta_cell = "—"
        else:
            status_icon = "✅"
            delta_cell = "—"

        lines.append(
            f"| {status_icon} | `{r.test_id}` | {r.flakiness_score*100:.0f}% | {cause_str} | {delta_cell} |"
        )

    # Fix suggestions section
    if fix_pairs:
        lines += ["", "### Fix Suggestions\n"]
        for r, s in fix_pairs:
            conf = r.root_cause.confidence if r.root_cause else "low"
            lines += [
                f"<details>",
                f"<summary>🔴 {s.test_id} — {s.root_cause_category} ({conf} confidence)</summary>",
                "",
                f"**Fix:** {s.template_fix}",
            ]
            if s.code_snippet:
                lines += ["", "```python", s.code_snippet.strip(), "```"]
            if s.ai_fix:
                lines += ["", "**AI-powered fix:**", "", s.ai_fix]
            lines += ["", "</details>", ""]

    lines += [
        "",
        "---",
        "*Generated by [flaky-test-autopsy](https://github.com/PranavOaR/flaky)*",
    ]

    Path(output_path).write_text("\n".join(lines) + "\n", encoding="utf-8")


# ── autopsy init-ci ────────────────────────────────────────────────────────────

_WORKFLOW_TEMPLATE = """\
name: Flaky Test Detection

on:
  push:
    branches: [main]
  pull_request:
  schedule:
    - cron: '{cron}'

jobs:
  flaky-tests:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4

      - name: Set up Python
        uses: actions/setup-python@v5
        with:
          python-version: '3.11'

      - name: Install dependencies
        run: |
          pip install flaky-test-autopsy
          pip install -r requirements.txt

      - name: Download baseline DB (if exists)
        uses: actions/download-artifact@v4
        with:
          name: autopsy-baseline
          path: ./baseline
        continue-on-error: true

      - name: Run flaky test detection
        run: |
          autopsy ci . --runs {runs} \\
            --baseline ./baseline/autopsy_results.db \\
            --output autopsy_ci_report.md

      - name: Upload results as artifact
        if: always()
        uses: actions/upload-artifact@v4
        with:
          name: autopsy-baseline
          path: autopsy_results.db

      - name: Upload CI report
        if: always()
        uses: actions/upload-artifact@v4
        with:
          name: autopsy-report
          path: autopsy_ci_report.md
"""


@main.command("init-ci")
@click.option("--runs", default=5, show_default=True, type=int,
              help="Number of runs to pass to autopsy ci.")
@click.option("--schedule", default="0 2 * * *", show_default=True,
              help="Cron expression for scheduled runs.")
def init_ci_cmd(runs: int, schedule: str) -> None:
    """Generate .github/workflows/flaky-tests.yml for CI integration."""
    workflow_dir = Path.cwd() / ".github" / "workflows"
    workflow_dir.mkdir(parents=True, exist_ok=True)
    workflow_path = workflow_dir / "flaky-tests.yml"

    content = _WORKFLOW_TEMPLATE.format(cron=schedule, runs=runs)
    workflow_path.write_text(content, encoding="utf-8")

    print(f"Created {workflow_path}")
    print()
    print("Next steps:")
    print("1. Commit and push this file")
    print("2. Set ANTHROPIC_API_KEY in your GitHub repo secrets (optional)")
    print("3. On first run, no baseline exists — autopsy ci will create one")
    print("4. From the second run onwards, regressions will be detected")


# ── autopsy dashboard ─────────────────────────────────────────────────────────

@main.command("dashboard")
@click.argument("db_path", type=click.Path(exists=False), default=_DB_FILENAME)
@click.option("--port", default=7878, show_default=True, type=int, help="Port to listen on.")
@click.option("--no-browser", "no_browser", is_flag=True, default=False,
              help="Do not open the browser automatically.")
def dashboard_cmd(db_path: str, port: int, no_browser: bool) -> None:
    """Serve a local web dashboard for the results DB."""
    from autopsy.dashboard import serve_dashboard

    path = Path(db_path)
    if not path.exists():
        Console().print(f"[bold red]Error:[/] database not found: {path}")
        raise SystemExit(1)

    serve_dashboard(str(path), port=port, open_browser=not no_browser)


# ── autopsy trend ─────────────────────────────────────────────────────────────

_TREND_ICON = {
    "regression":   "↘ REGRESS",
    "worsening":    "↗ WORSE",
    "improvement":  "↓ IMPROV",
    "stable_flaky": "~ FLAKY",
    "stable_clean": "✓ STABLE",
    "new":          "★ NEW",
    "gone":         "✗ GONE",
}

_TREND_STYLE = {
    "regression":   "bold red",
    "worsening":    "red",
    "improvement":  "green",
    "stable_flaky": "yellow",
    "stable_clean": "dim",
    "new":          "cyan",
    "gone":         "dim",
}


@main.command("trend")
@click.argument("db_path", type=click.Path(exists=False), default=_DB_FILENAME)
@click.option("--min-sessions", default=2, show_default=True,
              help="Minimum sessions a test must appear in.")
@click.option("--regressions-only", "regressions_only", is_flag=True, default=False,
              help="Show only regression and worsening tests.")
@click.option("--threshold", default=0.10, show_default=True, type=float,
              help="Delta above which stable_flaky becomes worsening.")
@click.option("--output", type=click.Path(), default=None,
              help="Write Markdown report to FILE.")
def trend_cmd(
    db_path: str,
    min_sessions: int,
    regressions_only: bool,
    threshold: float,
    output: "str | None",
) -> None:
    """Show per-test flakiness trends across recorded sessions."""
    from autopsy.trends import compute_trends, get_regressions

    console = Console()
    path = Path(db_path)

    if not path.exists():
        console.print(f"[bold red]Error:[/] database not found: {path}")
        raise SystemExit(1)

    reports = compute_trends(str(path), min_sessions=min_sessions, regression_threshold=threshold)

    if regressions_only:
        reports = get_regressions(reports)

    conn = open_db(path)
    try:
        sessions = get_all_sessions(conn)
    finally:
        conn.close()

    console.print(f"\n[bold]Sessions recorded:[/] {len(sessions)}")

    if not reports:
        console.print("[dim]No tests meet the min-sessions threshold.[/]\n")
        return

    table = Table(show_header=True, header_style="bold magenta")
    table.add_column("Test", style="cyan", no_wrap=False, min_width=30)
    table.add_column("Trend", justify="center")
    table.add_column("Latest", justify="right")
    table.add_column("Delta", justify="right")
    table.add_column("History", justify="left")

    for r in reports:
        latest_score = r.sessions[-1].flakiness_score * 100
        trend_style = _TREND_STYLE.get(r.trend, "")
        trend_label = _TREND_ICON.get(r.trend, r.trend)
        trend_cell = f"[{trend_style}]{trend_label}[/]" if trend_style else trend_label

        if len(r.sessions) < 2:
            delta_cell = "n/a"
        else:
            sign = "+" if r.trend_delta >= 0 else ""
            delta_cell = f"{sign}{r.trend_delta * 100:.1f}%"

        table.add_row(
            r.test_id,
            trend_cell,
            f"{latest_score:.1f}%",
            delta_cell,
            r.sparkline,
        )

    console.print(table)

    regressions = [r for r in reports if r.trend in ("regression", "worsening")]
    if regressions:
        console.print(
            f"\n[bold yellow]⚠ {len(regressions)} regression(s) detected.[/] "
            f"Run: [bold]autopsy fix {db_path}[/] for fix suggestions."
        )
    console.print()

    if output:
        _write_trend_report(reports, sessions, path, output)
        console.print(f"[green]Trend report written to:[/] {output}\n")


def _write_trend_report(
    reports: list,
    sessions: list[dict],
    db_path: Path,
    output_path: str,
) -> None:
    """Write a Markdown trend report to disk."""
    lines: list[str] = [
        "# Flaky Test Trend Report\n",
        f"Database: {db_path}",
        f"Sessions: {len(sessions)}\n",
        "---\n",
        "| Test | Trend | Latest | Delta | History |",
        "|------|-------|--------|-------|---------|",
    ]
    for r in reports:
        latest = f"{r.sessions[-1].flakiness_score * 100:.1f}%"
        if len(r.sessions) < 2:
            delta = "n/a"
        else:
            sign = "+" if r.trend_delta >= 0 else ""
            delta = f"{sign}{r.trend_delta * 100:.1f}%"
        lines.append(f"| `{r.test_id}` | {r.trend} | {latest} | {delta} | {r.sparkline} |")

    Path(output_path).write_text("\n".join(lines) + "\n", encoding="utf-8")


# ── helpers ────────────────────────────────────────────────────────────────────

def _print_scored_table(
    reports: list[FlakinessReport],
    db_path: Path,
    console: Console,
    only_flaky: bool,
    explain: bool,
) -> None:
    """Print the scored + classified summary table."""
    if not reports:
        console.print("\n[yellow]No test results to score.[/]")
        return

    flaky_reports = filter_flaky(reports)
    rows = flaky_reports if only_flaky else (
        flaky_reports + [r for r in reports if not r.is_flaky]
    )

    if not rows:
        console.print("\n[green]No flaky tests detected.[/]")
        console.print(f"[bold]Database:[/] {db_path}\n")
        return

    table = Table(show_header=True, header_style="bold magenta")
    table.add_column("Test", style="cyan", no_wrap=False, min_width=30)
    table.add_column("Runs", justify="right")
    table.add_column("Pass rate", justify="right")
    table.add_column("Flakiness", justify="right")
    table.add_column("Severity", justify="center")
    table.add_column("Root cause", justify="left")

    for r in rows:
        sev_style = _SEVERITY_STYLES.get(r.severity, "")
        cause_text = r.root_cause.category if r.root_cause else "—"
        cause_style = _CAUSE_STYLES.get(cause_text, "")
        table.add_row(
            r.test_id,
            str(r.total_runs),
            f"{r.pass_rate*100:.1f}%",
            f"{r.flakiness_score*100:.1f}%",
            f"[{sev_style}]{r.severity.upper()}[/]" if sev_style else r.severity.upper(),
            f"[{cause_style}]{cause_text}[/]" if cause_style else cause_text,
        )

    console.print()
    console.print(table)
    console.print(
        f"\n[bold]{len(flaky_reports)}[/] flaky test(s) detected out of "
        f"[bold]{len(reports)}[/] total (95% confidence)"
    )
    console.print(f"[bold]Database:[/] {db_path}\n")

    if explain and flaky_reports:
        _print_evidence(flaky_reports, console)


def _print_evidence(reports: list[FlakinessReport], console: Console) -> None:
    """Print per-test evidence bullets for --explain."""
    for r in reports:
        if not r.root_cause:
            continue
        cause = r.root_cause
        cause_style = _CAUSE_STYLES.get(cause.category, "")
        cause_label = (
            f"[{cause_style}]{cause.category}[/]" if cause_style else cause.category
        )
        console.print(f"\n[bold]{r.test_id}[/]")
        console.print(f"  {cause_label}  [dim]({cause.confidence} confidence)[/]")
        for bullet in cause.evidence:
            console.print(f"    • {bullet}")
    console.print()


def _print_fix_report(
    pairs: "list[tuple[FlakinessReport, FixSuggestion]]",
    console: Console,
    show_ai: bool,
) -> None:
    """Print fix suggestions to the terminal."""
    console.print()
    for r, s in pairs:
        sev_style = _SEVERITY_STYLES.get(r.severity, "")
        cause_style = _CAUSE_STYLES.get(s.root_cause_category, "")
        conf_note = (
            f"  [dim]({r.root_cause.confidence} confidence)[/dim]"
            if r.root_cause else ""
        )

        console.print(Rule(f"[bold cyan]{s.test_id}[/]", style="cyan"))
        console.print(
            f"  [{sev_style}]{r.severity.upper()}[/]  ·  "
            f"[{cause_style}]{s.root_cause_category}[/]{conf_note}"
        )
        console.print()
        console.print("  [bold]Template fix:[/bold]")
        console.print(f"  {s.template_fix}")

        if s.code_snippet:
            console.print()
            console.print(
                Syntax(s.code_snippet.strip(), "python", theme="monokai", padding=(0, 2))
            )

        if show_ai:
            console.print()
            if s.ai_fix:
                cache_note = " [dim](cached)[/dim]" if s.from_cache else ""
                console.print(f"  [bold]AI-powered fix:[/bold]{cache_note}")
                console.print()
                for line in s.ai_fix.splitlines():
                    console.print(f"  {line}")
            else:
                console.print(
                    "  [dim]AI fix unavailable — check ANTHROPIC_API_KEY.[/dim]"
                )

        console.print()

    console.print(
        f"[bold]{len(pairs)}[/] flaky test(s) analyzed  ·  [bold]Database:[/] ...\n"
    )


def _write_fix_report(
    pairs: "list[tuple[FlakinessReport, FixSuggestion]]",
    db_path: Path,
    output_path: str,
    console: Console,
) -> None:
    """Write fix suggestions to a Markdown file."""
    from datetime import datetime, timezone

    lines: list[str] = [
        "# Flaky Test Fix Report\n",
        f"Generated: {datetime.now(timezone.utc).isoformat()}",
        f"Database: {db_path}",
        f"Flaky tests analyzed: {len(pairs)}\n",
        "---\n",
    ]

    for r, s in pairs:
        conf = f" ({r.root_cause.confidence} confidence)" if r.root_cause else ""
        lines += [
            f"## `{s.test_id}`\n",
            f"**Severity:** {r.severity.upper()} | "
            f"**Root cause:** {s.root_cause_category}{conf}\n",
        ]

        if r.root_cause and r.root_cause.evidence:
            lines.append("### Evidence\n")
            lines += [f"- {e}" for e in r.root_cause.evidence]
            lines.append("")

        lines += [
            "### Template Fix\n",
            s.template_fix,
            "",
        ]

        if s.code_snippet:
            lines += ["```python", s.code_snippet.strip(), "```", ""]

        if s.ai_fix:
            cache_note = " *(from cache)*" if s.from_cache else ""
            lines += [f"### AI-Powered Fix{cache_note}\n", s.ai_fix, ""]

        lines.append("---\n")

    Path(output_path).write_text("\n".join(lines), encoding="utf-8")
    console.print(f"\n[green]Report written to:[/] {output_path}\n")


def _print_info(conn, db_path: Path, console: Console) -> None:
    """Print the info summary for the `autopsy info` subcommand."""
    from autopsy.scorer import filter_flaky, score_from_conn
    from autopsy.db import get_results_by_session

    summary = get_run_summary(conn)

    console.print(f"\n[bold]Database:[/] {db_path}")
    console.print(f"[bold]Total runs recorded:[/] {summary['total_runs']}")
    console.print(f"[bold]Unique tests seen:[/]   {summary['unique_test_ids']}")
    console.print(f"[bold]First run:[/] {summary['first_run_at'] or 'n/a'}")
    console.print(f"[bold]Last run:[/]  {summary['last_run_at'] or 'n/a'}")

    # ── Sessions section ──────────────────────────────────────────────────────
    sessions = get_all_sessions(conn)
    if sessions:
        console.print("\n[bold]Sessions:[/]")
        results_by_session = get_results_by_session(conn)

        sess_table = Table(show_header=True, header_style="bold magenta")
        sess_table.add_column("Session ID", style="dim", no_wrap=True)
        sess_table.add_column("Label", style="cyan")
        sess_table.add_column("Date", justify="left")
        sess_table.add_column("Runs", justify="right")
        sess_table.add_column("Flaky tests", justify="right")

        for s in sessions:
            # Estimate flaky count: tests with at least one failure in this session
            tid_map = results_by_session.get(s["id"], {})
            flaky_count = sum(
                1 for statuses in tid_map.values()
                if any(st in ("failed", "error") for st in statuses)
                and any(st == "passed" for st in statuses)
            )
            date_str = (s["started_at"] or "")[:19].replace("T", " ")
            sess_table.add_row(
                s["id"][:16] + "…" if len(s["id"]) > 16 else s["id"],
                s["label"] or "—",
                date_str,
                str(s["run_count"]),
                str(flaky_count),
            )

        console.print(sess_table)

    detail = get_run_detail(conn)
    if not detail:
        console.print("\n[dim]No runs recorded.[/]")
        return

    console.print("\n[bold]Run breakdown:[/]")
    table = Table(show_header=True, header_style="bold magenta")
    table.add_column("Run", justify="right")
    table.add_column("Seed", justify="right")
    table.add_column("Tests", justify="right")
    table.add_column("Duration", justify="right")

    for row in detail:
        table.add_row(
            str(row["run_index"]),
            str(row["seed"]),
            str(row["test_count"]),
            f"{row['duration_s']:.2f}s",
        )

    console.print(table)
    console.print(f"\n[dim]{get_db_info(conn)}[/]\n")
