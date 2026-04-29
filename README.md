# flaky-test-autopsy

Detect and diagnose flaky tests in any pytest-based repository.

Unlike simple retry tools, **flaky-test-autopsy** runs your suite multiple times with randomised ordering and tells you *which* tests are flaky and *how often* they fail.

## Installation

```bash
pip install flaky-test-autopsy
```

Or in development:

```bash
pip install -e .
```

## Usage

```bash
# Run suite 10 times (default)
autopsy run ./my-project

# Run 20 times with verbose pytest output
autopsy run ./my-project --runs 20 --verbose

# Run 10 times with 4 parallel workers
autopsy run ./my-project --runs 10 --workers 4
```

## Output

After all runs complete, autopsy prints a summary table:

```
┌─────────────────────────────────────────────────┬──────┬────────┬──────────┐
│ Test                                            │ Runs │ Passed │ Flakiness│
├─────────────────────────────────────────────────┼──────┼────────┼──────────┤
│ tests/test_flaky.py::test_sometimes_fails       │ 10   │ 6      │ 40.0%    │
│ tests/test_stable.py::test_addition             │ 10   │ 10     │ 0.0%     │
└─────────────────────────────────────────────────┴──────┴────────┴──────────┘

Suspected flaky tests (flakiness > 0%): 1
Database saved to: ./autopsy_results.db
```

Results are stored in `autopsy_results.db` (SQLite) for further analysis.

## How it works

1. Runs your pytest suite N times, each time with a unique random seed (`--randomly-seed`) to shuffle test order
2. Parses per-test pass/fail/error/skip status from each run
3. Stores results in SQLite after every run
4. Computes per-test flakiness as `(failed + error) / total_runs × 100%`

## Roadmap

- Day 3–4: Flakiness classification (timing, ordering, randomness, network)
- Day 5+: Targeted fix suggestions
- Day 12–13: React dashboard + GitHub Action
