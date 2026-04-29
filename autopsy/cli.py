"""Click CLI entry points for flaky-test-autopsy."""

from pathlib import Path

import click
from rich.console import Console
from rich.table import Table

from autopsy.db import fetch_flakiness_summary, open_db
from autopsy.runner import run_suite

_DB_FILENAME = "autopsy_results.db"


@click.group()
def main() -> None:
    """flaky-test-autopsy: detect and diagnose flaky tests."""


@main.command("run")
@click.argument("path", type=click.Path(exists=False))
@click.option("--runs", default=10, show_default=True, help="Number of full suite reruns.")
@click.option("--workers", default=1, show_default=True, help="Parallel workers (sequential if 1).")
@click.option("--verbose", is_flag=True, default=False, help="Stream pytest output live.")
def run_cmd(path: str, runs: int, workers: int, verbose: bool) -> None:
    """Run a pytest suite repeatedly and report flakiness."""
    console = Console()
    suite_path = Path(path)

    if not suite_path.exists():
        console.print(f"[bold red]Error:[/] path does not exist: {suite_path}")
        raise SystemExit(1)

    db_path = Path.cwd() / _DB_FILENAME
    conn = open_db(db_path)

    try:
        run_suite(
            suite_path=suite_path,
            num_runs=runs,
            workers=workers,
            verbose=verbose,
            conn=conn,
            console=console,
        )
    finally:
        _print_summary(conn, db_path, console)
        conn.close()


def _print_summary(conn, db_path: Path, console: Console) -> None:
    """Print the flakiness summary table and final stats."""
    rows = fetch_flakiness_summary(conn)

    if not rows:
        console.print("\n[yellow]No test results found.[/]")
        return

    table = Table(show_header=True, header_style="bold magenta")
    table.add_column("Test", style="cyan", no_wrap=False)
    table.add_column("Runs", justify="right")
    table.add_column("Passed", justify="right")
    table.add_column("Flakiness", justify="right")

    flaky_count = 0
    for row in rows:
        flakiness = row["flakiness_pct"] or 0.0
        style = "red" if flakiness > 0 else ""
        table.add_row(
            row["test_id"],
            str(row["total_runs"]),
            str(row["passed"]),
            f"{flakiness}%",
            style=style,
        )
        if flakiness > 0:
            flaky_count += 1

    console.print()
    console.print(table)
    console.print(f"\n[bold]Suspected flaky tests (flakiness > 0%):[/] {flaky_count}")
    console.print(f"[bold]Database saved to:[/] {db_path}\n")
