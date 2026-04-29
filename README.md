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

## Features (Day 4)

- Runs your suite N times with a different random seed each time (via `pytest-randomly`)
- Parses structured per-test results using `pytest-json-report` — handles parametrized tests, xfail/xpass, unicode, setup/teardown errors
- Stores every result in SQLite after each run (incremental, never lost on crash)
- **Wilson score lower bound** for statistically rigorous flakiness measurement (95% confidence)
- **Root cause classifier** — labels each flaky test as `ordering`, `timing`, `randomness`, `network`, or `unknown`
- Severity bands: `none` / `low` / `medium` / `high` / `critical`
- `--explain` flag prints evidence bullets per flaky test
- `autopsy info` and `autopsy score` subcommands for inspecting saved DBs
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

### `autopsy score`

```bash
autopsy score [db_path] [--min-runs N] [--threshold F] [--all] [--explain]
```

Score and classify flaky tests in an existing results DB. Defaults to `./autopsy_results.db`.

| Flag | Default | Description |
|---|---|---|
| `--min-runs N` | `5` | Skip tests with fewer than N real outcomes |
| `--threshold F` | `0.05` | Wilson lower-bound flakiness threshold for the "is_flaky" cutoff |
| `--all` | off | Show non-flaky tests too (default: only flaky) |
| `--explain` | off | Print evidence bullets per flaky test |

```bash
# Show only flaky tests with their root cause
autopsy score

# Show evidence for each flaky test
autopsy score --explain

# Show all tests, with a stricter threshold and 10-run minimum
autopsy score --all --threshold 0.10 --min-runs 10
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

### Scored summary table

```
┏━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━┳══════┳═══════════┳═══════════┳══════════┳═════════════┓
┃ Test                                                ┃ Runs ┃ Pass rate ┃ Flakiness ┃ Severity ┃ Root cause  ┃
┡━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━╇══════╇═══════════╇═══════════╇══════════╇═════════════┩
│ tests/test_network.py::test_fake_network_call       │   10 │      0.0% │     72.2% │ CRITICAL │ network     │
│ tests/test_ordering.py::test_depends_on_state       │   10 │     20.0% │     49.0% │   HIGH   │ ordering    │
│ tests/test_flaky.py::test_sometimes_fails           │   10 │     70.0% │     10.8% │  MEDIUM  │ randomness  │
└─────────────────────────────────────────────────────┴──────┴───────────┴───────────┴──────────┴─────────────┘

3 flaky test(s) detected out of 12 total (95% confidence)
```

### `autopsy score --explain` evidence

```
tests/test_network.py::test_fake_network_call
  network  (high confidence)
    • failure output contains network keyword 'connection'
    • failure output contains network keyword 'refused'
    • failure output contains network keyword '503'

tests/test_ordering.py::test_depends_on_state
  ordering  (medium confidence)
    • pass rate in runs 1-5: 0%, runs 6-10: 40%
    • correlation between run position and failure: 0.40

tests/test_flaky.py::test_sometimes_fails
  randomness  (high confidence)
    • failure output contains keyword 'random'
    • failures uniformly distributed across 10 runs (no clustering)
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
5. **Wilson score lower bound** — flakiness is the conservative 95% lower bound on the failure rate, so a test with 1/2 failures isn't ranked the same as 50/100. With 5/10 failures, score ≈ 24%; with 50/100 failures, score ≈ 41%
6. **Severity bands** — `0` = none · `≤0.10` = low · `≤0.30` = medium · `≤0.60` = high · `>0.60` = critical

### Root cause classification

For each flaky test, the classifier runs four heuristics and returns the highest-priority match (network → timing → ordering → randomness → unknown):

| Cause | Signal |
|---|---|
| **network** | Failure traceback contains keywords like `connection`, `refused`, `socket`, `dns`, `404`, `503`, `ssl`, `urllib`, `requests`, … |
| **timing** | Failures take noticeably longer than passes (≥1.5×), or contain `timeout`, `sleep`, `race`, `async`, … |
| **ordering** | Pass rate in first half of runs differs from second half by >30% (suggests test order matters) |
| **randomness** | Failures are uniformly distributed (no clustering), or contain `random`, `uuid`, `shuffle`, `hash`, … |
| **unknown** | None of the above fired |

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
│   ├── cli.py          # Click entry points (autopsy run, score, info)
│   ├── runner.py       # Subprocess pytest runner + JSON report parser
│   ├── scorer.py       # Wilson score + root cause classifier
│   ├── db.py           # SQLite schema, inserts, and query layer
│   └── models.py       # TestResult, RunRecord, FlakinessReport, RootCause
├── tests/
│   ├── test_db.py      # Unit tests for db.py query layer
│   ├── test_scorer.py  # Unit tests for Wilson math + classifiers
│   └── fixtures/
│       └── sample_suite/
│           ├── test_stable.py      # Always passes
│           ├── test_flaky.py       # Fails ~40% of the time (randomness)
│           ├── test_ordering.py    # Fails when run out of order
│           ├── test_network.py     # Always fails with a network-style traceback
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

# Run unit tests (db + scorer)
.venv/bin/python -m pytest tests/test_db.py tests/test_scorer.py -v
```

---

## Roadmap

| Day | Scope | Status |
|-----|-------|--------|
| 1 | Runner harness — subprocess pytest, SQLite, progress bar, summary table | Done |
| 2 | JSON report parser, full DB query layer, `autopsy info`, `--fresh` | Done |
| 3–4 | Wilson flakiness scorer + classifier (network / timing / ordering / randomness), `autopsy score`, `--explain` | Done |
| 5–7 | Root cause analysis per flakiness class | Planned |
| 8–11 | Targeted fix suggestions | Planned |
| 12–13 | React dashboard + GitHub Action | Planned |

---

## License

MIT
