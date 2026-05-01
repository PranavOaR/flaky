# Changelog

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
