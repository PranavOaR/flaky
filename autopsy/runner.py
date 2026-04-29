"""Core test runner: executes pytest subprocesses and parses results."""

import json
import random
import sqlite3
import subprocess
import sys
import tempfile
from datetime import datetime, timezone
from pathlib import Path

from rich.console import Console
from rich.progress import BarColumn, MofNCompleteColumn, Progress, SpinnerColumn, TextColumn

from autopsy.db import insert_run
from autopsy.models import RunRecord, TestResult

# xfailed = expected failure → treat as skipped (not a real failure)
# xpassed = unexpectedly passed → flag as failed (something changed)
_OUTCOME_MAP: dict[str, str] = {
    "passed": "passed",
    "failed": "failed",
    "error": "error",
    "skipped": "skipped",
    "xfailed": "skipped",
    "xpassed": "failed",
}


def run_suite(
    suite_path: Path,
    num_runs: int,
    workers: int,
    verbose: bool,
    conn: sqlite3.Connection,
    console: Console,
) -> None:
    """Execute the pytest suite `num_runs` times and store results in `conn`."""
    console.print(f"\n[bold cyan]autopsy[/] running [bold]{suite_path}[/] × {num_runs} runs\n")

    total_failures = 0

    with Progress(
        SpinnerColumn(),
        TextColumn("[progress.description]{task.description}"),
        BarColumn(),
        MofNCompleteColumn(),
        TextColumn("[dim]{task.fields[status]}"),
        console=console,
        transient=False,
    ) as progress:
        task = progress.add_task("Runs", total=num_runs, status="")

        for i in range(1, num_runs + 1):
            seed = random.randint(0, 2**31 - 1)
            record = _execute_run(suite_path, run_index=i, seed=seed, verbose=verbose, console=console)
            run_failures = sum(1 for r in record.results if r.status in ("failed", "error"))
            total_failures += run_failures
            insert_run(conn, record)
            progress.update(
                task,
                advance=1,
                status=f"{total_failures} failure(s) so far",
                description=f"Run {i}/{num_runs} complete",
            )


def _execute_run(
    suite_path: Path,
    run_index: int,
    seed: int,
    verbose: bool,
    console: Console,
) -> RunRecord:
    """Run pytest once with a JSON report and return a populated RunRecord."""
    started_at = datetime.now(timezone.utc).isoformat()
    t_start = datetime.now(timezone.utc)

    with tempfile.NamedTemporaryFile(suffix=".json", delete=False) as tf:
        report_path = Path(tf.name)

    try:
        cmd = [
            sys.executable, "-m", "pytest",
            str(suite_path),
            "--tb=short",
            "--no-header",
            "-p", "no:cacheprovider",
            f"--randomly-seed={seed}",
            "--json-report",
            f"--json-report-file={report_path}",
        ]

        try:
            subprocess.run(
                cmd,
                capture_output=not verbose,
                text=True,
                timeout=300,
            )
        except subprocess.TimeoutExpired:
            console.print(f"[yellow]Run {run_index}: pytest timed out — skipping[/]")
        except Exception as exc:  # noqa: BLE001
            console.print(f"[yellow]Run {run_index}: pytest crashed ({exc}) — skipping[/]")

        duration_s = (datetime.now(timezone.utc) - t_start).total_seconds()
        results = _parse_json_report(report_path, run_index, console)

    finally:
        report_path.unlink(missing_ok=True)

    return RunRecord(
        run_index=run_index,
        seed=seed,
        started_at=started_at,
        duration_s=duration_s,
        results=results,
    )


def _parse_json_report(report_path: Path, run_index: int, console: Console) -> list[TestResult]:
    """Parse a pytest-json-report file into TestResult objects."""
    if not report_path.exists():
        console.print(f"[yellow]Run {run_index}: JSON report not written (pytest may have crashed)[/]")
        return []

    try:
        data = json.loads(report_path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError) as exc:
        console.print(f"[yellow]Run {run_index}: JSON report malformed ({exc}) — skipping[/]")
        return []

    results: list[TestResult] = []
    for test in data.get("tests", []):
        raw_outcome = test.get("outcome", "error")
        status = _OUTCOME_MAP.get(raw_outcome, "error")

        duration_s: float = test.get("duration", 0.0)

        # Collect failure/error text from call phase; fall back to setup if no call
        stdout = ""
        for phase in ("call", "setup", "teardown"):
            phase_data = test.get(phase)
            if phase_data:
                parts = []
                if phase_data.get("stdout"):
                    parts.append(phase_data["stdout"])
                if phase_data.get("longrepr"):
                    parts.append(str(phase_data["longrepr"]))
                if parts:
                    stdout = "\n".join(parts)
                    break

        results.append(TestResult(
            test_id=test["nodeid"],
            status=status,
            duration_s=duration_s,
            stdout=stdout,
        ))

    return results
