# flaky-test-autopsy

> Detect, track, and diagnose flaky tests in any pytest-based repository.

Most flakiness tools just retry. **flaky-test-autopsy** runs your full suite repeatedly with randomised execution order, captures structured per-test results, and tells you exactly which tests are flaky and how often — stored in SQLite so you can query and track it over time.

---

## What problem does this solve?

Flaky tests are tests that pass sometimes and fail other times without any code change. They're caused by:

- **Ordering dependencies** — test A secretly mutates shared state that test B depends on
- **Timing issues** — sleeps, timeouts, or race conditions
- **Randomness** — unseeded `random` calls, shuffled data
- **Network** — tests that hit real endpoints or DNS

Standard pytest just shows you a failure. `pytest-rerunfailures` retries silently. Neither tells you *why* or *how often* — which is what you need to fix the root cause.

---

## Features (Day 2)

- Runs your suite N times with a different random seed each time (via `pytest-randomly`)
- Parses structured per-test results using `pytest-json-report` — handles parametrized tests, xfail/xpass, unicode, setup/teardown errors
- Stores every result in SQLite after each run (incremental, never lost on crash)
- Live Rich progress bar during runs
- Flakiness summary table on completion
- `autopsy info` subcommand to inspect any results DB
- `--fresh` flag to wipe old data before a new run

---

## Installation

**Requires Python 3.10+**

From PyPI (coming soon):
```bash
pip install flaky-test-autopsy
```

From source (development):
```bash
git clone https://github.com/PranavOaR/flaky.git
cd flaky
uv venv .venv && uv pip install -e .
# or: pip install -e .
```

---

## Usage

### `autopsy run`

```bash
autopsy run <path> [--runs N] [--workers W] [--verbose] [--fresh]
```

| Argument / Flag | Default | Description |
|---|---|---|
| `path` | required | Path to a pytest-based project or test directory |
| `--runs N` | `10` | How many times to run the full suite |
| `--workers W` | `1` | Parallel workers (sequential if 1) |
| `--verbose` | off | Stream live pytest output instead of suppressing it |
| `--fresh` | off | Clear any existing DB data before running |

**Examples:**

```bash
# Quick check — 10 runs against a local project
autopsy run ./my-project

# Higher confidence — 30 runs
autopsy run ./my-project --runs 30

# Fresh run, streaming pytest output
autopsy run ./my-project --runs 20 --fresh --verbose

# Against a subdirectory of tests
autopsy run ./my-project/tests/integration --runs 15
```

### `autopsy info`

```bash
autopsy info [db_path]
```

Inspect a saved results database. Defaults to `./autopsy_results.db`.

```bash
autopsy info
autopsy info ./autopsy_results.db
```

---

## Sample output

### During run

```
autopsy running tests/fixtures/sample_suite × 10 runs

  Run 10/10 complete ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━ 10/10  9 failure(s) so far
```

### Summary table

```
┏━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━┳━━━━━━┳━━━━━━━━┳━━━━━━━━━━━┓
┃ Test                                                     ┃ Runs ┃ Passed ┃ Flakiness ┃
┡━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━╇━━━━━━╇━━━━━━━━╇━━━━━━━━━━━┩
│ tests/test_ordering.py::test_depends_on_state            │   10 │      5 │     50.0% │  ← ordering-sensitive
│ tests/test_flaky.py::test_sometimes_fails                │   10 │      6 │     40.0% │  ← randomly fails
│ tests/test_stable.py::test_addition                      │   10 │     10 │      0.0% │
│ tests/test_stable.py::test_string_upper                  │   10 │     10 │      0.0% │
└──────────────────────────────────────────────────────────┴──────┴────────┴───────────┘

Suspected flaky tests (flakiness > 0%): 2
Database saved to: ./autopsy_results.db
```

### `autopsy info` output

```
Database: ./autopsy_results.db
Total runs recorded: 10
Unique tests seen:   12
First run: 2024-01-15T10:23:01+00:00
Last run:  2024-01-15T10:23:45+00:00

Run breakdown:
┏━━━━━┳━━━━━━━━━━━━┳━━━━━━━┳━━━━━━━━━━┓
┃ Run ┃       Seed ┃ Tests ┃ Duration ┃
┡━━━━━╇━━━━━━━━━━━━╇━━━━━━━╇━━━━━━━━━━┩
│   1 │  400436084 │    12 │    0.21s │
│   2 │ 1004408758 │    12 │    0.22s │
   ...
```

---

## How it works

1. **Randomised runs** — each run passes a unique `--randomly-seed` to `pytest-randomly`, shuffling test execution order to surface ordering dependencies
2. **Structured parsing** — uses `pytest-json-report` to capture per-test outcome, duration, and failure tracebacks as structured JSON (not fragile stdout scraping)
3. **Incremental persistence** — results are written to SQLite after *every* run, so a crash midway loses nothing
4. **Outcome mapping** — `xfailed` → skipped (expected failure, not a real flake), `xpassed` → failed (unexpectedly passed, worth flagging)
5. **Flakiness formula** — `(failed + error) / total_runs × 100%` per test, across all recorded runs

---

## Database schema

Results are stored in `autopsy_results.db` (SQLite, current working directory).

```sql
-- One row per pytest run
CREATE TABLE runs (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    run_index   INTEGER,   -- 1-based run number
    seed        INTEGER,   -- random seed used for test ordering
    started_at  TEXT,      -- ISO 8601 UTC timestamp
    duration_s  REAL       -- total run wall-clock time
);

-- One row per test per run
CREATE TABLE results (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    run_id      INTEGER REFERENCES runs(id),
    test_id     TEXT,      -- full pytest node id, e.g. tests/test_foo.py::test_bar
    status      TEXT,      -- 'passed' | 'failed' | 'error' | 'skipped'
    duration_s  REAL,      -- individual test duration
    stdout      TEXT       -- captured output + failure traceback
);
```

You can query it directly:

```bash
sqlite3 autopsy_results.db \
  "SELECT test_id, COUNT(*) runs, SUM(status='failed') fails FROM results GROUP BY test_id"
```

---

## Project structure

```
flaky-test-autopsy/
├── autopsy/
│   ├── cli.py          # Click entry points (autopsy run, autopsy info)
│   ├── runner.py       # Subprocess pytest runner + JSON report parser
│   ├── db.py           # SQLite schema, inserts, and query layer
│   └── models.py       # TestResult and RunRecord dataclasses
├── tests/
│   ├── test_db.py      # Unit tests for db.py query layer
│   └── fixtures/
│       └── sample_suite/
│           ├── test_stable.py      # Always passes
│           ├── test_flaky.py       # Fails ~40% of the time
│           ├── test_ordering.py    # Fails when run out of order
│           └── test_edge_cases.py  # Parametrized, xfail, unicode, slow
├── pyproject.toml
└── CLAUDE.md
```

---

## Development

```bash
# Clone and set up
git clone https://github.com/PranavOaR/flaky.git
cd flaky
uv venv .venv && uv pip install -e .

# Run the sample suite (end-to-end test of the tool itself)
.venv/bin/autopsy run ./tests/fixtures/sample_suite --runs 10 --fresh

# Run unit tests
.venv/bin/python -m pytest tests/test_db.py -v
```

---

## Roadmap

| Day | Scope | Status |
|-----|-------|--------|
| 1 | Runner harness — subprocess pytest, SQLite, progress bar, summary table | Done |
| 2 | JSON report parser, full DB query layer, `autopsy info`, `--fresh` | Done |
| 3–4 | Flakiness scorer + classification (timing / ordering / randomness / network) | Planned |
| 5–7 | Root cause analysis per flakiness class | Planned |
| 8–11 | Targeted fix suggestions | Planned |
| 12–13 | React dashboard + GitHub Action | Planned |

---

## License

MIT
