# flaky-test-autopsy — CLAUDE.md

## Project overview
Open-source Python CLI to detect and diagnose flaky tests in pytest repositories.
Published to PyPI eventually. Think pytest-rerunfailures but smarter — it diagnoses.

## Current day: Day 1 — Runner harness only

### What's built
- `autopsy/cli.py` — Click CLI (`autopsy run <path> --runs N`)
- `autopsy/runner.py` — subprocess pytest runner, output parser, progress bar
- `autopsy/db.py` — SQLite schema and queries
- `autopsy/models.py` — `TestResult` and `RunRecord` dataclasses
- `tests/fixtures/sample_suite/` — stable, flaky (~40%), and ordering-dependent fixtures

### What's NOT built yet
- Flakiness classification (Day 3–4)
- Fix suggestions (Day 5+)
- React dashboard (Day 12–13)
- GitHub Action (Day 13)

## Running locally
```bash
pip install -e .
autopsy run ./tests/fixtures/sample_suite --runs 10
```

## Code conventions
- Type hints on every function signature
- One-liner docstrings on every public function
- No global state — pass db connection / config explicitly
- `cli.py` stays thin; logic lives in `runner.py` and `db.py`
- `subprocess.run()` for pytest (never pytest's Python API — need process isolation)
