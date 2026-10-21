#!/usr/bin/env bash
# Portable source checks; does not require the old local sprint driver.
set -euo pipefail
# Force UTF-8 mode for every checker process. Without this a stock Windows
# console (cp1252 stdout, e.g. when output is redirected to a pipe or file)
# makes checkers that print non-ASCII diagnostics — such as the
# "distortion→chorus→delay→reverb→master" label in
# check_baseline_fixture_test.py — die with UnicodeEncodeError. The variable is
# exported so nested python interpreters the checkers spawn inherit it too.
export PYTHONUTF8=1
CORVUS_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
CORVUS_CHECK_COUNT=0
for check in "$CORVUS_ROOT"/scripts/check_*.py; do
    test -f "$check"
    python3 -X utf8 "$check"
    CORVUS_CHECK_COUNT=$((CORVUS_CHECK_COUNT + 1))
done
printf 'GATE_OK: %s source checkers\n' "$CORVUS_CHECK_COUNT"
