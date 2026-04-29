"""Click CLI entry points for flaky-test-autopsy."""

from pathlib import Path

import click
from rich.console import Console
from rich.rule import Rule
from rich.syntax import Syntax
from rich.table import Table

from autopsy.db import (
    clear_results,
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


# ── autopsy run ────────────────────────────────────────────────────────────────

@main.command("run")
@click.argument("path", type=click.Path(exists=False))
@click.option("--runs", default=10, show_default=True, help="Number of full suite reruns.")
@click.option("--workers", default=1, show_default=True, help="Parallel workers (sequential if 1).")
@click.option("--verbose", is_flag=True, default=False, help="Stream pytest output live.")
@click.option("--fresh", is_flag=True, default=False, help="Clear existing DB data before running.")
def run_cmd(path: str, runs: int, workers: int, verbose: bool, fresh: bool) -> None:
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

    try:
        run_suite(
            suite_path=suite_path,
            num_runs=runs,
            workers=workers,
            verbose=verbose,
            conn=conn,
            console=console,
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
    summary = get_run_summary(conn)

    console.print(f"\n[bold]Database:[/] {db_path}")
    console.print(f"[bold]Total runs recorded:[/] {summary['total_runs']}")
    console.print(f"[bold]Unique tests seen:[/]   {summary['unique_test_ids']}")
    console.print(f"[bold]First run:[/] {summary['first_run_at'] or 'n/a'}")
    console.print(f"[bold]Last run:[/]  {summary['last_run_at'] or 'n/a'}")

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
