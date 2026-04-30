# Contributing to Flaky Test Autopsy

## Setup

```bash
git clone https://github.com/PranavOaR/flaky
cd flaky
pip install -e ".[dev]"
```

## Running tests

```bash
pytest                       # all tests
pytest tests/test_scorer.py  # single module
pytest --cov=autopsy         # with coverage
```

## Adding a new root cause classifier

1. Add detection logic in `autopsy/scorer.py` as `_classify_<name>()`
2. Add it to the priority chain in `classify_root_cause()`
3. Add a template fix in `autopsy/fixer.py` `get_template_fix()`
4. Add unit tests in `tests/test_scorer.py` and `tests/test_fixer.py`

## Submitting a PR

- All 57+ tests must pass
- New features need tests
- Run `twine check dist/*` before submitting
