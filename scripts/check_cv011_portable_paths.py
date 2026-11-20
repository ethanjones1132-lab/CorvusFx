#!/usr/bin/env python3
"""CV-011 (CV-T3): the scripts under scripts/ run on a machine that is not this one.

Every checker and one-shot in scripts/ must resolve the checkout from its own
location (`Path(__file__).resolve().parent.parent`) or from JUCE_PATH, never
from a hard-coded development-machine path. A literal `C:/Users/ethan` or
`C:/Projects/Corvus` in scripts/ means the harness only works in one checkout.

Allowed exceptions:
- this file, because it names the forbidden patterns;
- check_source_tracking_doc.py, whose regex exists precisely to flag docs that
  quote a machine-specific path.

Revert probe: re-hardcode `SRC = "C:/Projects/Corvus VST/source/DrippyFX/PluginProcessor.h"`
in scripts/fix_chorus_rate_cache.py (or any scripts/*.py) and this checker exits 1.

Keep in sync with the glob-driven gate: verify_corvus_source.sh runs every
scripts/check_*.py, so this file is registered automatically.
"""
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SCRIPTS = ROOT / "scripts"

SELF = Path(__file__).resolve().name
ALLOWED = {
    SELF,
    # Its job is to detect a machine-specific path quoted in a doc.
    "check_source_tracking_doc.py",
}

# A drive-letter absolute path to a developer checkout, in either slash style.
FORBIDDEN = re.compile(r"C:[\\/](?:Users[\\/]|Projects[\\/]Corvus)", re.IGNORECASE)


def offenders() -> list[str]:
    found: list[str] = []
    for path in sorted(SCRIPTS.glob("*")):
        if not path.is_file() or path.suffix.lower() not in {".py", ".sh", ".ps1"}:
            continue
        if path.name in ALLOWED:
            continue
        try:
            text = path.read_text(encoding="utf-8", errors="replace")
        except OSError as error:  # unreadable file: report, do not guess
            found.append(f"{path.relative_to(ROOT)}: unreadable ({error})")
            continue
        for number, line in enumerate(text.splitlines(), start=1):
            match = FORBIDDEN.search(line)
            if match:
                found.append(f"{path.relative_to(ROOT)}:{number}: hard-coded path {match.group(0)!r}")
    return found


def main() -> int:
    if not SCRIPTS.is_dir():
        print(f"FAIL: {SCRIPTS} is not a directory", file=sys.stderr)
        return 1
    found = offenders()
    if found:
        print("FAIL: these scripts only work in one checkout (CV-011):", file=sys.stderr)
        for line in found:
            print(f"  {line}", file=sys.stderr)
        print(
            "Resolve the repo root from this file "
            "(`ROOT = Path(__file__).resolve().parent.parent`) instead.",
            file=sys.stderr,
        )
        return 1
    print("check_cv011_portable_paths: OK - no hard-coded checkout paths under scripts/")
    return 0


if __name__ == "__main__":
    sys.exit(main())
