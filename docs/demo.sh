#!/bin/bash
set -e

echo "=== Flaky Test Autopsy — Demo ==="
echo ""

rm -f autopsy_results.db

echo "--- Session 1: baseline ---"
autopsy run ./tests/fixtures/sample_suite --runs 10 --label "baseline"

echo "--- Session 2: after-change ---"
autopsy run ./tests/fixtures/sample_suite --runs 10 --label "after-change"

echo "--- Scoring ---"
autopsy score ./autopsy_results.db --explain

echo "--- Fix suggestions ---"
autopsy fix ./autopsy_results.db

echo "--- Trend analysis ---"
autopsy trend ./autopsy_results.db

echo "--- CI simulation ---"
autopsy ci ./tests/fixtures/sample_suite --runs 5 || true

echo "--- Dashboard ---"
echo "Run: autopsy dashboard ./autopsy_results.db"
echo "     to open the web dashboard"

echo ""
echo "=== Demo complete ==="
