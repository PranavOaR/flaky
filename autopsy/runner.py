"""Core test runner: executes pytest subprocesses and parses results."""

import random
import re
import sqlite3
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

from rich.console import Console
from rich.progress import Progress, SpinnerColumn, TextColumn, BarColumn, MofNCompleteColumn

from autopsy.db import insert_run
from autopsy.models import RunRecord, TestResult

_RESULT_LINE = re.compile(
    r"^(PASSED|FAILED|ERROR|SKIPPED)\s+(.+?)(?:\s+-\s+(.+))?$"
)
# pytest -v line: "tests/foo.py::test_bar PASSED [ 50%]"
_VERBOSE_LINE = re.compile(
    r"^(.+?::[\w\[\]\-]+)\s+(PASSED|FAILED|ERROR|SKIPPED)"
)
# duration from "1 passed in 0.12s" style summary
_DURATION_RE = re.compile(r"in\s+([\d.]+)s")
# short mode: ".F.s" character per test — not reliable for node ids, so we use -v
# We always pass -v internally so we get node ids


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
    """Run pytest once and return a populated RunRecord."""
    cmd = [
        sys.executable, "-m", "pytest",
        str(suite_path),
        "-v",                          # needed to get node ids per test
        "--tb=short",
        "--no-header",
        "-p", "no:cacheprovider",
        f"--randomly-seed={seed}",
    ]

    started_at = datetime.now(timezone.utc).isoformat()
    t_start = datetime.now(timezone.utc)

    try:
        proc = subprocess.run(
            cmd,
            capture_output=not verbose,
            text=True,
            timeout=300,
        )
        output = (proc.stdout or "") + (proc.stderr or "")
    except subprocess.TimeoutExpired:
        console.print(f"[yellow]Run {run_index}: pytest timed out — skipping[/]")
        output = ""
    except Exception as exc:  # noqa: BLE001
        console.print(f"[yellow]Run {run_index}: pytest crashed ({exc}) — skipping[/]")
        output = ""

    duration_s = (datetime.now(timezone.utc) - t_start).total_seconds()
    results = _parse_output(output)

    return RunRecord(
        run_index=run_index,
        seed=seed,
        started_at=started_at,
        duration_s=duration_s,
        results=results,
    )


def _parse_output(output: str) -> list[TestResult]:
    """Parse pytest -v output and return a TestResult list."""
    results: list[TestResult] = []
    seen: set[str] = set()

    for line in output.splitlines():
        line = line.strip()
        m = _VERBOSE_LINE.match(line)
        if m:
            node_id = m.group(1).strip()
            status_raw = m.group(2).strip().lower()
            if node_id not in seen:
                seen.add(node_id)
                results.append(TestResult(
                    test_id=node_id,
                    status=status_raw,
                    duration_s=0.0,
                    stdout="",
                ))

    return results
