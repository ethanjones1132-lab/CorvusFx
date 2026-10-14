#!/usr/bin/env bash
# Portable source checks; does not require the old local sprint driver.
set -euo pipefail
CORVUS_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
CORVUS_CHECK_COUNT=0
for check in "$CORVUS_ROOT"/scripts/check_*.py; do
    test -f "$check"
    python3 "$check"
    CORVUS_CHECK_COUNT=$((CORVUS_CHECK_COUNT + 1))
done
printf 'GATE_OK: %s source checkers\n' "$CORVUS_CHECK_COUNT"
