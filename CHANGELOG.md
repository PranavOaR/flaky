# Changelog

## [0.4.0] — 2026-05-04

### Added

- `autopsy report` — generate a fully self-contained single-file HTML report (no server, works offline); embeds all test data and detail panels via `window.__STATIC_DATA__` / `window.__STATIC_TESTS__`; supports `--output FILE` and `--open`
- `autopsy watch <test_id> <path>` — re-run a single test up to `--max-runs` times (default 50) until it fails; prints a per-run status line, captures the failure output, and exits 1 with a ready-to-paste repro command including the exact random seed
- `autopsy ignore <test_id>` — add a test to the ignore list; suppresses it from CI exit codes, fix suggestions, and scored tables. Supports `--reason TEXT`, `--remove`, `--list`, and `--db PATH`
- `autopsy history <test_id>` — show the full per-run outcome table for a single test, with session labels, duration, and failure snippets. Supports `--last N` and `--failures-only`
- Dashboard drill-down panel — clicking any test row opens a 500px slide-in panel with severity pill, flakiness stats, run timeline (coloured dots), latest failure output, and a template fix suggestion; ESC or overlay click closes it
- Dashboard: "Ignore this test" button in drill-down panel — POSTs to `/api/ignore` endpoint, persists to the ignore list without a page reload
- Root cause classifiers: **fixture** (detects setup/teardown errors) and **resource** (detects memory, disk, and file-handle exhaustion); both have fix templates in the fixer
- PyPI publish workflow (`.github/workflows/release.yml`) — triggers on `v*` tags; builds sdist + wheel, publishes via Trusted Publishing (no API token needed), creates a GitHub Release with artifacts
- `[tool.autopsy]` config section in `pyproject.toml` — set `runs`, `workers`, `threshold`, `min_runs`, and `model` once per repo; all subcommands pick them up as defaults via Click's `default_map`
- GitHub Actions CI workflow (`.github/workflows/ci.yml`): lint + type-check job and test matrix (3.10, 3.11, 3.12) with coverage report upload
- `is_ignored` field on `FlakinessReport`; `_apply_ignore_list()` helper in `cli.py` propagates the ignore state through `score`, `fix`, and `ci` commands
- `get_history_for_test` DB query — joins sessions for per-run session labels
- 32 new tests across `test_ignore.py`, `test_history.py`, and `test_watch.py`

### Changed

- `_PRIORITY` updated: network > fixture > timing > resource > ordering > randomness > unknown
- Dashboard cause chart now colours fixture (purple) and resource (orange) slices
- Dashboard auto-refresh disabled in static report mode; ignore button hidden in static mode
- Modernised type annotations across `autopsy/` from `Optional[X]` to `X | None` (Python 3.10+ syntax)
- `ruff` and `mypy` added to `[dev]` extras; codebase is now fully lint-clean

## [0.3.0] — 2026-05-02

### Added

- `autopsy export` — export scored results to CSV or JSON for external dashboards and pipelines
- `autopsy clean` — prune old sessions by count (`--keep N`) or age (`--older-than N`), with `--dry-run` support
- `--workers N` flag on `autopsy run` for parallel pytest execution; reduces wall-clock time proportionally
- `--filter EXPR` flag on `autopsy run` passes a `-k` expression to pytest, targeting a subset of tests
- Streaming AI output in `autopsy fix --ai`: tokens appear live in the terminal instead of blocking until completion
- Tests for `db.py` (pruning, cascade deletes, `clear_results` sessions fix), `trends.py`, and `runner.py` JSON report parsing

### Fixed

- `--fresh` now also clears the sessions table — previously orphaned session rows remained after clearing runs/results, corrupting `autopsy info` and trend comparisons
- Runs with zero collected test results (import errors, plugin conflicts) are no longer inserted into the DB, preventing inflated run counts and diluted flakiness scores
- Pytest exit codes 4 ("no tests collected") and 2 ("interrupted") are now detected and logged, rather than silently treated as valid empty runs
- `_write_fix_report` now appends a trailing newline, matching the other report writers

### Changed

- `run_suite` and `_execute_run` accept `workers` and `filter_expr` parameters; console chatter is suppressed in parallel mode to avoid interleaved output
- AI fix generation uses the streaming API; the `on_text` callback enables live terminal output

### Security

- Dashboard: HTML-escape all test IDs and user-derived data before injecting into `innerHTML` (XSS fix)
- Dashboard: removed `Access-Control-Allow-Origin: *` header from local API endpoint
- AI prompt: failure output is now wrapped in `<failure_output>` tags and flagged as untrusted in the system prompt (prompt injection hardening)
- `autopsy init-ci`: `--schedule` value is validated against a cron character allowlist before YAML interpolation
- Markdown reports: test IDs are escaped before embedding in table cells and `<summary>` tags

## [0.2.0] — 2026-05-01

### Added

- `autopsy --version` / `-V` to print the installed version
- `--json` flag on `autopsy score` for machine-readable output
- `--json-output FILE` flag on `autopsy ci` for CI tooling integration
- `--model` flag on `autopsy fix` and `AUTOPSY_AI_MODEL` env var to override the default Claude model
- DB indexes on `results.run_id`, `results.test_id`, `runs.session_id`, `runs.run_index` for faster queries on large suites
- `Documentation` and `Changelog` URLs in `pyproject.toml`
- `pytest-mock` added to dev extras

### Fixed

- `autopsy ci` no longer mis-renders a 0.0% delta as `—` (operator-precedence bug in the WARN row)
- Banner is suppressed when invoking `autopsy` with no subcommand or `--version` (previously printed before the help text)

### Changed

- Removed the `--workers` flag from `autopsy run` (it was accepted but never honored)

## [0.1.0] — 2026-04-30

### Added

- `autopsy run` — parallel pytest reruns with random seeds
- `autopsy score` — Wilson score flakiness scoring with severity bands
- `autopsy fix` — template + AI-powered fix suggestions
- `autopsy trend` — session-based trend tracking and regression detection
- `autopsy ci` — CI-native composite command with exit codes
- `autopsy dashboard` — local web dashboard
- `autopsy init-ci` — GitHub Actions workflow generator
- Root cause classification: ordering, timing, randomness, network
- SQLite persistence with session tracking
- ASCII art banner
