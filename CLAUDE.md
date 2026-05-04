# flaky-test-autopsy — CLAUDE.md

## Project overview
Open-source Python CLI to detect and diagnose flaky tests in pytest repositories.
Currently at **v0.4.0**. Think pytest-rerunfailures but smarter — it diagnoses.

## What's built (v0.4.0)

### Core modules
- `autopsy/cli.py` — 14 Click subcommands: `run`, `score`, `info`, `fix`, `export`, `clean`, `ignore`, `history`, `watch`, `report`, `ci`, `trend`, `dashboard`, `init-ci`
- `autopsy/runner.py` — subprocess pytest runner, JSON report parser, parallel workers via `ThreadPoolExecutor`
- `autopsy/db.py` — SQLite schema, session tracking, pruning, AI fix cache, ignore list
- `autopsy/scorer.py` — Wilson lower-bound flakiness scorer + root cause classifier (network, fixture, timing, resource, ordering, randomness)
- `autopsy/fixer.py` — template + streaming AI fix suggestions (Anthropic SDK); templates for all 7 root cause categories
- `autopsy/trends.py` — session-based trend tracking, sparklines, regression detection
- `autopsy/dashboard.py` — self-contained local web dashboard with drill-down panel, ignore button, static report builder
- `autopsy/banner.py` — ASCII art banner
- `autopsy/models.py` — `TestResult`, `RunRecord`, `FlakinessReport`, `FixSuggestion`, `RootCause` dataclasses

### Tests
`tests/` has 13 test files covering scorer, fixer, trends, CLI, CI, DB, runner, ignore, history, watch. 118 tests, all passing.
`tests/fixtures/sample_suite/` contains intentionally flaky fixtures used by autopsy itself.

## Running locally
```bash
pip install -e ".[dev]"
autopsy run ./tests/fixtures/sample_suite --runs 10
```

## Linting & type-checking
```bash
uv run --with ruff ruff check autopsy/ tests/
mypy autopsy/ --ignore-missing-imports
```
Both must pass clean before committing.

## Running tests
```bash
uv run python -m pytest tests/ --cov=autopsy -q
```
`tests/fixtures/` is excluded automatically via `[tool.pytest.ini_options]`.

## Releasing
Tag `vX.Y.Z` and push — `.github/workflows/release.yml` builds and publishes to PyPI via Trusted Publishing.
```bash
git tag v0.4.0 && git push --tags
```

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
- `build_static_report()` injects `window.__STATIC_DATA__` and `window.__STATIC_TESTS__` into the HTML; JS checks these first before fetching from the server, enabling fully offline reports.
- Root cause priority: network > fixture > timing > resource > ordering > randomness > unknown. Fixture and resource are placed high because their keyword matches are unambiguous error class names.
- `dashboard.py`: `do_POST()` handles `/api/ignore` to add tests to the ignore list from the drill-down panel. Static report mode disables the ignore button and auto-refresh.
