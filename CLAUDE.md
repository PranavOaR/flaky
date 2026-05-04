# flaky-test-autopsy — CLAUDE.md

## Project overview
Open-source Python CLI to detect and diagnose flaky tests in pytest repositories.
Currently at v0.3.0 (unreleased v0.4.0 in progress). Think pytest-rerunfailures but smarter — it diagnoses.

## What's built (v0.3.0 + unreleased)

### Core modules
- `autopsy/cli.py` — 12 Click subcommands: `run`, `score`, `info`, `fix`, `export`, `clean`, `ignore`, `history`, `ci`, `trend`, `dashboard`, `init-ci`
- `autopsy/runner.py` — subprocess pytest runner, JSON report parser, parallel workers via `ThreadPoolExecutor`
- `autopsy/db.py` — SQLite schema, session tracking, pruning, AI fix cache
- `autopsy/scorer.py` — Wilson lower-bound flakiness scorer + root cause classifier (network, timing, ordering, randomness)
- `autopsy/fixer.py` — template + streaming AI fix suggestions (Anthropic SDK)
- `autopsy/trends.py` — session-based trend tracking, sparklines, regression detection
- `autopsy/dashboard.py` — self-contained local web dashboard (dark theme, Chart.js, XSS-hardened)
- `autopsy/banner.py` — ASCII art banner
- `autopsy/models.py` — `TestResult`, `RunRecord`, `FlakinessReport`, `FixSuggestion`, `RootCause` dataclasses

### Tests
`tests/` has 10 test files covering scorer, fixer, trends, CLI, CI, DB, runner, ignore, history. 112 tests, all passing.
`tests/fixtures/sample_suite/` contains intentionally flaky fixtures used by autopsy itself.

## Running locally
```bash
pip install -e ".[dev]"
autopsy run ./tests/fixtures/sample_suite --runs 10
```

## Linting & type-checking
```bash
ruff check autopsy/ tests/
mypy autopsy/ --ignore-missing-imports
```
Both must pass clean before committing.

## Running tests
```bash
pytest tests/ --cov=autopsy -q
```
`tests/fixtures/` is excluded automatically via `[tool.pytest.ini_options]`.

## Code conventions
- Type hints on every function signature; use `X | None` not `Optional[X]`
- One-liner docstrings on every public function
- No global state — pass db connection / config explicitly
- `cli.py` stays thin; logic lives in domain modules
- `subprocess.run()` for pytest (never pytest's Python API — need process isolation)
- `ruff` and `mypy` must pass clean; no `# noqa` without a comment explaining why

## Config file support
Users can set defaults in their `pyproject.toml`:
```toml
[tool.autopsy]
runs = 20
workers = 4
threshold = 0.05
min_runs = 3
model = "claude-opus-4-7"
```
`_load_config()` in `cli.py` reads this and passes it as Click's `default_map`.

## Key design notes
- `FlakinessReport.is_ignored` — set by `_apply_ignore_list()` in cli.py after scoring; suppresses CI exit, fix output, and filters the scored table. Never set by scorer.py itself.
- `autopsy ignore` uses `--db PATH` (named option) not a positional, because `test_id` is also optional and two optional positionals in Click are ambiguous.
- `get_history_for_test` LEFT JOINs sessions so runs without a session_id still appear.
- `ignored_tests` table is created by `create_ignored_tests_table()` called in `open_db()` — same pattern as `ai_fixes`.
