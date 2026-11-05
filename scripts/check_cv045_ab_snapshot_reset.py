#!/usr/bin/env python3
"""Check A/B snapshot restore clears stale state before reading abSlots.

Pins the reset to setStateInformation, before the optional abSlots branch,
while retaining the complete-pair and byte-length checks for a saved pair.
In-memory probes exercise the old conditional-clear shape, a missing reset,
and removed pair validation; no source file is modified by the probes.
"""
import re
import sys
from pathlib import Path

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

ROOT = Path(__file__).resolve().parent.parent
SOURCE = ROOT / "source" / "DrippyFX" / "PluginProcessor.cpp"
PROCESSOR = "CorvusFXAudioProcessor"

BRANCH = re.compile(
    r'if\s*\(\s*auto\s*\*\s*\w+\s*=\s*xml\s*->\s*getChildByName\s*'
    r'\(\s*"abSlots"\s*\)\s*\)\s*')
RESET = re.compile(
    r'\bsnapshotA\s*\.\s*fill\s*\(\s*0(?:\.0)?f?\s*\)\s*;'
    r'\s*\bsnapshotB\s*\.\s*fill\s*\(\s*0(?:\.0)?f?\s*\)\s*;'
    r'\s*\babSlotIsA\s*=\s*true\s*;'
    r'\s*\babSnapshotsPersisted\s*=\s*false\s*;')
BYTE_LENGTH = re.compile(
    r'getDataSize\s*\(\s*\)\s*==\s*static_cast\s*<\s*size_t\s*>\s*'
    r'\(\s*NUM_AB_PARAMS\s*\)\s*\*\s*sizeof\s*\(\s*float\s*\)')
COMPLETE_PAIR = re.compile(r'if\s*\(\s*restoredA\s*&&\s*restoredB\s*\)')


def strip_comments(text):
    text = re.sub(r"/\*.*?\*/", lambda m: "\n" * m.group(0).count("\n"),
                  text, flags=re.S)
    return re.sub(r"//[^\n]*", "", text)


def braced_span(text, opening):
    depth = 0
    for i in range(opening, len(text)):
        if text[i] == "{":
            depth += 1
        elif text[i] == "}":
            depth -= 1
            if depth == 0:
                return opening, i + 1, text[opening + 1:i]
    return None


def enclosing_block(text, pos):
    depth = 0
    for i in range(pos - 1, -1, -1):
        if text[i] == "}":
            depth += 1
        elif text[i] == "{":
            if depth == 0:
                span = braced_span(text, i)
                return (span[0], span[1]) if span else None
            depth -= 1
    return None


def function_body(code):
    match = re.search(
        rf'\bvoid\s+{PROCESSOR}::setStateInformation\s*\([^)]*\)\s*\{{',
        code, flags=re.S)
    return braced_span(code, match.end() - 1) if match else None


def verify(source_text=None):
    if source_text is None:
        source_text = SOURCE.read_text(encoding="utf-8", errors="replace")
    body_span = function_body(strip_comments(source_text))
    if body_span is None:
        return ["could not find CorvusFXAudioProcessor::setStateInformation body"]
    body = body_span[2]
    branch = BRANCH.search(body)
    if not branch:
        return ['setStateInformation lost its "abSlots" restore branch']
    branch_open = body.find("{", branch.end())
    branch_span = braced_span(body, branch_open)
    if branch_span is None:
        return ['the "abSlots" branch has no body']

    resets = list(RESET.finditer(body))
    errors = []
    if len(resets) != 1:
        errors.append("A/B arrays, active slot, and persisted flag must each be "
                      "reset exactly once before abSlots")
    else:
        if resets[0].start() > branch_open:
            errors.append("the complete A/B reset must precede the optional abSlots branch")
        block = enclosing_block(body, resets[0].start())
        if block is None or body[:block[0]].rstrip().endswith(")"):
            errors.append("the complete A/B reset must be unconditional")
    if not BYTE_LENGTH.search(body):
        errors.append("A/B restore lost its same-type/expected-byte-length validation")
    if len(BYTE_LENGTH.findall(body)) < 2:
        errors.append("both snapshotA and snapshotB must retain expected-byte-length validation")
    if not COMPLETE_PAIR.search(branch_span[2]):
        errors.append("A/B restore must apply only a complete snapshot pair")
    return errors


def fail_probe(label, detail):
    print(f"FAIL: probe '{label}' was not rejected — {detail}")
    sys.exit(1)


if not SOURCE.exists():
    print(f"FAIL: missing source file {SOURCE}")
    sys.exit(1)
source_text = SOURCE.read_text(encoding="utf-8", errors="replace")
errors = verify(source_text)
if errors:
    print("FAIL: CV-045 A/B snapshot restore invariants violated:")
    for error in errors:
        print(f"  - {error}")
    sys.exit(1)
print("OK: A/B snapshot state resets unconditionally before the abSlots branch")
print("OK: both snapshots retain byte-length validation and only complete pairs apply")

code = strip_comments(source_text)
reset = RESET.search(code)
if not reset:
    print("FAIL: stale self-probe: reset pattern absent")
    sys.exit(1)
branch = BRANCH.search(code)
branch_open = code.find("{", branch.end())
if reset.start() >= branch_open:
    print("FAIL: stale self-probe: reset is not before branch")
    sys.exit(1)
legacy = code[:reset.start()] + code[reset.end():]
branch = BRANCH.search(legacy)
branch_open = legacy.find("{", branch.end())
insert_at = branch_open + 1
legacy = legacy[:insert_at] + "\n" + reset.group(0) + legacy[insert_at:]
if not verify(legacy):
    fail_probe("clear moved back inside branch", "conditional reset shape passed")
print("probe ok: reset moved inside abSlots branch -> rejected")

no_reset, count = RESET.subn("", code, count=1)
if count != 1:
    print("FAIL: stale self-probe: reset removal pattern absent")
    sys.exit(1)
if not verify(no_reset):
    fail_probe("clear removed", "source with no A/B reset passed")
print("probe ok: reset removed -> rejected")

without_validation, count = BYTE_LENGTH.subn("true", code)
if count != 2:
    print("FAIL: stale self-probe: expected two byte-length checks, found "
          f"{count}")
    sys.exit(1)
if not verify(without_validation):
    fail_probe("pair validation removed", "source without byte-length checks passed")
print("probe ok: pair byte-length validation removed -> rejected")
