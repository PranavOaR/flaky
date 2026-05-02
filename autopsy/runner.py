"""Core test runner: executes pytest subprocesses and parses results."""

import json
import random
import sqlite3
import subprocess
import sys
import tempfile
import threading
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

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

# Pytest exit codes that mean "no usable results"
_SKIP_EXIT_CODES = {
    2: "interrupted",
    4: "no tests collected",
}


def run_suite(
    suite_path: Path,
    num_runs: int,
    verbose: bool,
    conn: sqlite3.Connection,
    console: Console,
    session_id: "str | None" = None,
    workers: int = 1,
    filter_expr: "str | None" = None,
) -> None:
    """Execute the pytest suite `num_runs` times and store results in `conn`."""
    workers = max(1, workers)
    worker_str = f" ({workers} workers)" if workers > 1 else ""
    filter_str = f" [dim]-k {filter_expr}[/]" if filter_expr else ""
    console.print(
        f"\n[bold cyan]autopsy[/] running [bold]{suite_path}[/]"
        f" × {num_runs} runs{worker_str}{filter_str}\n"
    )

    total_failures = 0
    db_lock = threading.Lock()

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

        if workers == 1:
            for i in range(1, num_runs + 1):
                seed = random.randint(0, 2**31 - 1)
                record = _execute_run(
                    suite_path, run_index=i, seed=seed,
                    verbose=verbose, console=console, filter_expr=filter_expr,
                )
                if record.results:
                    run_failures = sum(1 for r in record.results if r.status in ("failed", "error"))
                    total_failures += run_failures
                    insert_run(conn, record, session_id=session_id)
                progress.update(
                    task,
                    advance=1,
                    status=f"{total_failures} failure(s) so far",
                    description=f"Run {i}/{num_runs} complete",
                )
        else:
            # Parallel: suppress per-run console chatter, serialise DB writes
            seeds = [random.randint(0, 2**31 - 1) for _ in range(num_runs)]
            future_to_index = {}
            with ThreadPoolExecutor(max_workers=workers) as executor:
                for i, seed in enumerate(seeds, 1):
                    future = executor.submit(
                        _execute_run,
                        suite_path, i, seed, False, console, filter_expr, True,
                    )
                    future_to_index[future] = i

                completed = 0
                for future in as_completed(future_to_index):
                    completed += 1
                    record = future.result()
                    if record.results:
                        run_failures = sum(1 for r in record.results if r.status in ("failed", "error"))
                        total_failures += run_failures
                        with db_lock:
                            insert_run(conn, record, session_id=session_id)
                    progress.update(
                        task,
                        advance=1,
                        status=f"{total_failures} failure(s) so far",
                        description=f"{completed}/{num_runs} complete",
                    )


def _execute_run(
    suite_path: Path,
    run_index: int,
    seed: int,
    verbose: bool,
    console: Console,
    filter_expr: "str | None" = None,
    quiet: bool = False,
) -> RunRecord:
    """Run pytest once with a JSON report and return a populated RunRecord."""
    started_at = datetime.now(timezone.utc).isoformat()
    t_start = datetime.now(timezone.utc)

    with tempfile.NamedTemporaryFile(suffix=".json", delete=False) as tf:
        report_path = Path(tf.name)

    results: list[TestResult] = []
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
        if filter_expr:
            cmd += ["-k", filter_expr]

        try:
            proc = subprocess.run(
                cmd,
                capture_output=not verbose,
                text=True,
                timeout=300,
            )
            if proc.returncode in _SKIP_EXIT_CODES and not quiet:
                reason = _SKIP_EXIT_CODES[proc.returncode]
                console.print(f"[yellow]Run {run_index}: {reason} (exit {proc.returncode}) — skipping[/]")
        except subprocess.TimeoutExpired:
            if not quiet:
                console.print(f"[yellow]Run {run_index}: pytest timed out — skipping[/]")
        except Exception as exc:  # noqa: BLE001
            if not quiet:
                console.print(f"[yellow]Run {run_index}: pytest crashed ({exc}) — skipping[/]")

        duration_s = (datetime.now(timezone.utc) - t_start).total_seconds()
        results = _parse_json_report(report_path, run_index, console, quiet=quiet)

    finally:
        report_path.unlink(missing_ok=True)

    return RunRecord(
        run_index=run_index,
        seed=seed,
        started_at=started_at,
        duration_s=duration_s,
        results=results,
    )


def _parse_json_report(
    report_path: Path,
    run_index: int,
    console: Console,
    quiet: bool = False,
) -> list[TestResult]:
    """Parse a pytest-json-report file into TestResult objects."""
    if not report_path.exists():
        if not quiet:
            console.print(f"[yellow]Run {run_index}: JSON report not written (pytest may have crashed)[/]")
        return []

    try:
        data = json.loads(report_path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError) as exc:
        if not quiet:
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
