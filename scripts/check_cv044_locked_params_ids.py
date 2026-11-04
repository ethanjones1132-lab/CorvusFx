#!/usr/bin/env python3
"""Check that restored parameter locks name parameters in this build.

Pins the paramLocks restore loop in
source/DrippyFX/PluginProcessor.cpp: lock children are iterated, their id
attribute is read, empty ids are skipped, and only ids accepted by
apvts.getParameter(id) are inserted into lockedParams.

Self-probes ensure the check rejects a missing parameter lookup, a lookup
moved after the insert, and a removed empty-id guard. A probe that no longer
matches the live source fails loudly rather than silently going stale.
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
    r'\(\s*"paramLocks"\s*\)\s*\)\s*')
ITERATOR = re.compile(r'getChildWithTagNameIterator\s*\(\s*"lock"\s*\)')
ID_ATTRIBUTE = re.compile(r'getStringAttribute\s*\(\s*"id"\s*\)')
ID_GUARD = re.compile(r'\bid\s*\.\s*isNotEmpty\s*\(\s*\)')
PARAMETER_LOOKUP = re.compile(
    r'\bapvts\s*\.\s*getParameter\s*\(\s*id\s*\)\s*==\s*nullptr')
INSERT = re.compile(r'\blockedParams\s*\.\s*insert\s*\(\s*id\s*\)\s*;')
EMPTY_GUARD_INSERT = re.compile(
    r'if\s*\(\s*id\s*\.\s*isNotEmpty\s*\(\s*\)\s*\)\s*'
    r'lockedParams\s*\.\s*insert\s*\(\s*id\s*\)\s*;')
REJECT_UNKNOWN = re.compile(
    r'if\s*\(\s*!\s*id\s*\.\s*isEmpty\s*\(\s*\)\s*&&\s*'
    r'apvts\s*\.\s*getParameter\s*\(\s*id\s*\)\s*==\s*nullptr\s*\)\s*'
    r'continue\s*;')


def strip_comments(text: str) -> str:
    text = re.sub(r"/\*.*?\*/", lambda match: "\n" * match.group(0).count("\n"),
                  text, flags=re.S)
    return re.sub(r"//[^\n]*", "", text)


def braced_span(text: str, opening: int):
    depth = 0
    for i in range(opening, len(text)):
        if text[i] == "{":
            depth += 1
        elif text[i] == "}":
            depth -= 1
            if depth == 0:
                return opening, i + 1, text[opening + 1:i]
    return None


def brace_body(text: str, pos: int):
    opening = text.find("{", pos)
    return braced_span(text, opening) if opening != -1 else None


def function_body(code: str, name: str):
    match = re.search(rf"\bvoid\s+{PROCESSOR}::{name}\s*\([^)]*\)\s*\{{",
                      code, flags=re.S)
    return braced_span(code, match.end() - 1) if match else None


def verify(source_text=None):
    """Return CV-044 violations (empty when the restore is safe)."""
    if source_text is None:
        source_text = SOURCE.read_text(encoding="utf-8", errors="replace")
    code = strip_comments(source_text)
    found = function_body(code, "setStateInformation")
    if found is None:
        return ["could not find CorvusFXAudioProcessor::setStateInformation body"]
    body = found[2]
    branch = BRANCH.search(body)
    if not branch:
        return ['setStateInformation lost its "paramLocks" restore branch']
    span = brace_body(body, branch.end())
    if span is None:
        return ['the "paramLocks" branch has no body']
    branch_body = span[2]

    errors = []
    if not ITERATOR.search(branch_body):
        errors.append('the "paramLocks" branch no longer iterates "lock" children')
    if not ID_ATTRIBUTE.search(branch_body):
        errors.append('the "paramLocks" restore no longer reads the "id" attribute')
    guard = ID_GUARD.search(branch_body)
    lookup = PARAMETER_LOOKUP.search(branch_body)
    insert = INSERT.search(branch_body)
    rejection = REJECT_UNKNOWN.search(branch_body)
    if not guard:
        errors.append("the \"paramLocks\" restore no longer skips empty ids")
    if not lookup:
        errors.append("the restore does not check that id names an existing APVTS parameter")
    if not rejection:
        errors.append("unknown parameter ids are not skipped before the lock insert")
    if not insert:
        errors.append("the \"paramLocks\" restore no longer inserts the restored id")
    if guard and insert and not EMPTY_GUARD_INSERT.search(branch_body):
        errors.append("the empty-id guard must remain directly on the lock insert")
    if lookup and insert and lookup.start() > insert.start():
        errors.append("the existing-parameter check must precede the lock insert")
    if rejection and insert and rejection.start() > insert.start():
        errors.append("unknown parameter ids must be skipped before the lock insert")
    return errors


if not SOURCE.exists():
    print(f"FAIL: missing source file {SOURCE}")
    sys.exit(1)

source_text = SOURCE.read_text(encoding="utf-8", errors="replace")
errors = verify(source_text)
if errors:
    print("FAIL: CV-044 restored locked-parameter id invariant violated:")
    for error in errors:
        print(f"  - {error}")
    sys.exit(1)

print("OK: restored locked parameter ids must name an existing APVTS parameter")


def fail_probe(label, why):
    print(f"FAIL: probe '{label}' was NOT rejected — {why}")
    sys.exit(1)


def fail_stale(label):
    print(f"FAIL: probe '{label}': NO-OP MUTATION (pattern absent from the live source) — probe is stale")
    sys.exit(1)


code = strip_comments(source_text)

# Removing the parameter lookup must make the source fail verification.
without_lookup, count = PARAMETER_LOOKUP.subn("true", code, count=1)
if count == 0:
    fail_stale("parameter lookup removed")
if not verify(without_lookup):
    fail_probe("parameter lookup removed", "an unchecked lock id passed")
print("probe ok: missing parameter lookup -> rejected")

# Moving the lookup after insertion must not protect the inserted id.
rejection = REJECT_UNKNOWN.search(code)
insert = INSERT.search(code)
if not rejection or not insert or rejection.start() > insert.start():
    fail_stale("parameter lookup moved after insert")
moved = (code[:rejection.start()] + "if (id.isNotEmpty()) continue;"
         + code[rejection.end():])
insert = INSERT.search(moved)
moved = moved[:insert.end()] + "\n                if (apvts.getParameter(id) == nullptr) continue;" + moved[insert.end():]
if not verify(moved):
    fail_probe("parameter lookup moved after insert", "a post-insert lookup passed")
print("probe ok: lookup moved after insert -> rejected")

# Removing the empty-id guard must also be rejected.
loose_ids, count = re.subn(
    r"if\s*\(\s*id\s*\.\s*isNotEmpty\s*\(\s*\)\s*\)\s*"
    r"lockedParams\s*\.\s*insert\s*\(\s*id\s*\)\s*;",
    "lockedParams.insert(id);",
    code, count=1)
if count == 0:
    fail_stale("empty-id guard removed")
if not verify(loose_ids):
    fail_probe("empty-id guard removed", "an empty id could reach lockedParams")
print("probe ok: removed empty-id guard -> rejected")

final_errors = verify()
if final_errors:
    print("FAIL: final source re-verification failed:")
    for error in final_errors:
        print(f"  - {error}")
    sys.exit(1)
print("CV-044 OK")
