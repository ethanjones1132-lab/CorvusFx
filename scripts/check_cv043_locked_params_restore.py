#!/usr/bin/env python3
"""Check that a restore leaves exactly the parameter locks the state carries.

Pins `CorvusFXAudioProcessor::setStateInformation` in
source/DrippyFX/PluginProcessor.cpp:

  (a) `lockedParams.clear()` runs UNCONDITIONALLY, before the
      `if (... getChildByName("paramLocks"))` branch and under
      `lockedParamsLock` — exactly the way the MIDI map is cleared above it,
      so a state with no "paramLocks" child means "no locks" instead of
      keeping the previous session's locks armed;
  (b) the clear is not conditional (not inside an `if`/`else` block) and is
      the only clear in the restore, so the branch can only add locks;
  (c) the restore loop and its id handling are unchanged: it iterates the
      "lock" children, reads the `id` attribute, skips empty ids and inserts
      the rest into `lockedParams`.

Self-probes: a comment-only edit is accepted; moving the clear back inside
the branch (the pre-CV-043 shape) is rejected; dropping the lock guard,
dropping the clear altogether, dropping the empty-id guard and dropping the
insert are each rejected. A probe whose pattern is absent fails the run, so
the probes cannot silently go stale.
"""
import re
import sys
from pathlib import Path

# Diagnostics quote source text with non-ASCII arrows; a cp1252 console must
# not turn a verdict into a crash.
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

ROOT = Path(__file__).resolve().parent.parent
SOURCE = ROOT / "source" / "DrippyFX" / "PluginProcessor.cpp"

PROCESSOR = "CorvusFXAudioProcessor"

BRANCH = re.compile(
    r'if\s*\(\s*auto\s*\*\s*\w+\s*=\s*xml\s*->\s*getChildByName\s*'
    r'\(\s*"paramLocks"\s*\)\s*\)\s*')
CLEAR = re.compile(r"\blockedParams\s*\.\s*clear\s*\(\s*\)\s*;")
LOCK_GUARD = re.compile(
    r"const\s+juce::ScopedLock\s+\w+\s*\(\s*lockedParamsLock\s*\)\s*;")
ITERATOR = re.compile(r'getChildWithTagNameIterator\s*\(\s*"lock"\s*\)')
ID_ATTRIBUTE = re.compile(r'getStringAttribute\s*\(\s*"id"\s*\)')
ID_GUARD = re.compile(r"\bid\s*\.\s*isNotEmpty\s*\(\s*\)")
INSERT = re.compile(r"\blockedParams\s*\.\s*insert\s*\(\s*id\s*\)\s*;")


def strip_comments(text: str) -> str:
    text = re.sub(r"/\*.*?\*/",
                  lambda match: "\n" * match.group(0).count("\n"),
                  text, flags=re.S)
    return re.sub(r"//[^\n]*", "", text)


def braced_span(text: str, opening: int):
    """(open, close_exclusive, inner) of the brace block at `opening`."""
    depth = 0
    for i in range(opening, len(text)):
        char = text[i]
        if char == "{":
            depth += 1
        elif char == "}":
            depth -= 1
            if depth == 0:
                return opening, i + 1, text[opening + 1:i]
    return None


def brace_body(text: str, pos: int):
    """(open, close_exclusive, inner) of the first '{' at/after `pos`."""
    opening = text.find("{", pos)
    if opening == -1:
        return None
    return braced_span(text, opening)


def function_body(code: str, name: str):
    """(open, close_exclusive, inner) of CorvusFXAudioProcessor::<name>."""
    match = re.search(rf"\bvoid\s+{PROCESSOR}::{name}\s*\([^)]*\)\s*\{{",
                      code, flags=re.S)
    if not match:
        return None
    return braced_span(code, match.end() - 1)


def enclosing_block(text: str, pos: int):
    """(open, close_exclusive) of the innermost brace block containing pos."""
    opening = None
    depth = 0
    for i in range(pos - 1, -1, -1):
        if text[i] == "}":
            depth += 1
        elif text[i] == "{":
            if depth == 0:
                opening = i
                break
            depth -= 1
    if opening is None:
        return None
    found = braced_span(text, opening)
    return (found[0], found[1]) if found else None


def is_conditional_block(text: str, opening: int) -> bool:
    """True when the block at `opening` is the body of an if/else."""
    return text[:opening].rstrip().endswith(")")


def verify(source_text=None):
    """Return the list of CV-043 violations (empty when the source is ok)."""
    if source_text is None:
        source_text = SOURCE.read_text(encoding="utf-8", errors="replace")
    errors = []

    code = strip_comments(source_text)
    found = function_body(code, "setStateInformation")
    if found is None:
        return ["could not find CorvusFXAudioProcessor::setStateInformation "
                "body"]
    body = found[2]

    branch = BRANCH.search(body)
    if not branch:
        errors.append('setStateInformation lost its "paramLocks" restore '
                      'branch')
        return errors
    branch_span = brace_body(body, branch.end())
    if branch_span is None:
        errors.append('the "paramLocks" branch has no body')
        return errors
    branch_open, branch_close, branch_body = branch_span

    clears = list(CLEAR.finditer(body))
    if not clears:
        errors.append("setStateInformation never clears lockedParams — a "
                      "state without a \"paramLocks\" child would keep the "
                      "previous session's locks (CV-043)")
        return errors
    if len(clears) > 1:
        errors.append("setStateInformation clears lockedParams more than "
                      "once; one unconditional clear before the \"paramLocks\" "
                      "branch is the contract (CV-043)")

    clear = clears[0]
    if clear.start() > branch_open:
        errors.append("lockedParams.clear() must run BEFORE the "
                      "\"paramLocks\" branch (clearing only inside the branch "
                      "means an absent child keeps the old locks — CV-043)")

    block = enclosing_block(body, clear.start())
    if block is None:
        errors.append("lockedParams.clear() is not inside a guarded block")
    else:
        guarded = body[block[0]:block[1]]
        if not LOCK_GUARD.search(guarded):
            errors.append("lockedParams.clear() must be taken under "
                          "lockedParamsLock (CV-043)")
        if is_conditional_block(body, block[0]):
            errors.append("lockedParams.clear() must be unconditional — a "
                          "conditional clear keeps stale locks whenever the "
                          "condition is false (CV-043)")

    # (c) the restore loop and its id handling are unchanged.
    if not ITERATOR.search(branch_body):
        errors.append('the "paramLocks" branch no longer iterates the "lock" '
                      "children")
    if not ID_ATTRIBUTE.search(branch_body):
        errors.append('the "paramLocks" restore no longer reads the "id" '
                      "attribute")
    if not ID_GUARD.search(branch_body):
        errors.append("the \"paramLocks\" restore no longer skips empty ids")
    if not INSERT.search(branch_body):
        errors.append("the \"paramLocks\" restore no longer inserts the "
                      "restored id into lockedParams")

    return errors


# ---------------------------------------------------------------------------
# Real tree
# ---------------------------------------------------------------------------
if not SOURCE.exists():
    print(f"FAIL: missing source file {SOURCE}")
    sys.exit(1)

source_text = SOURCE.read_text(encoding="utf-8", errors="replace")
errors = verify(source_text)
if errors:
    print("FAIL: CV-043 locked-parameter restore invariants violated:")
    for error in errors:
        print(f"  - {error}")
    sys.exit(1)

print("OK: lockedParams is cleared unconditionally under lockedParamsLock "
      "before the paramLocks branch")
print("OK: the paramLocks restore loop still reads the lock ids and skips "
      "empty ones")

# ---------------------------------------------------------------------------
# Self-probes (in memory only — the real tree is never written)
# ---------------------------------------------------------------------------
code = strip_comments(source_text)


def fail_probe(label, why):
    print(f"FAIL: probe '{label}' was NOT rejected — {why}")
    sys.exit(1)


def fail_stale(label):
    print(f"FAIL: probe '{label}': NO-OP MUTATION (pattern absent from the "
          f"live source) — the probe is stale")
    sys.exit(1)


# A comment-only change must not affect the source contract.
if verify(source_text + "\n// harmless checker probe\n"):
    print("FAIL: harmless comment edit was rejected")
    sys.exit(1)
print("probe ok: harmless comment edit -> accepted")


def move_clear_into_branch(text):
    """Rebuild the pre-CV-043 shape: clear only inside the paramLocks branch."""
    branch = BRANCH.search(text)
    if not branch:
        return None
    branch_span = brace_body(text, branch.end())
    if branch_span is None:
        return None
    branch_open, branch_close = branch_span[0], branch_span[1]
    outside = [match for match in CLEAR.finditer(text)
               if not (branch_open <= match.start() < branch_close)]
    if len(outside) != 1:
        return None
    block = enclosing_block(text, outside[0].start())
    if block is None:
        return None
    removed = text[:block[0]] + text[block[1]:]

    branch = BRANCH.search(removed)
    if not branch:
        return None
    branch_span = brace_body(removed, branch.end())
    if branch_span is None:
        return None
    open_at, inner = branch_span[0], branch_span[2]
    guard = LOCK_GUARD.search(inner)
    insert_at = open_at + 1 + guard.end() if guard else open_at + 1
    return removed[:insert_at] + "\n    lockedParams.clear();" + removed[insert_at:]


legacy_text = move_clear_into_branch(code)
if legacy_text is None:
    fail_stale("clear moved back inside the branch")
if not verify(legacy_text):
    fail_probe("clear moved back inside the branch",
               "the pre-CV-043 shape (clear only inside the branch) passed")
print("probe ok: clear only inside the paramLocks branch -> rejected")

# A clear without the lock is a data race with the audio/editor readers.
without_lock = None
clear = CLEAR.search(code)
if clear:
    block = enclosing_block(code, clear.start())
    if block:
        inner, count = LOCK_GUARD.subn("(void) 0;", code[block[0]:block[1]],
                                      count=1)
        if count:
            without_lock = code[:block[0]] + inner + code[block[1]:]
if without_lock is None:
    fail_stale("lock guard dropped from the clear")
if not verify(without_lock):
    fail_probe("lock guard dropped from the clear",
               "an unguarded lockedParams.clear() passed")
print("probe ok: unguarded lockedParams.clear() -> rejected")

# Dropping the clear entirely brings the inherited-lock bug straight back.
no_clear, count = CLEAR.subn("(void) 0;", code, count=1)
if count == 0:
    fail_stale("clear removed")
if not verify(no_clear):
    fail_probe("clear removed", "a restore with no clear passed")
print("probe ok: no clear at all -> rejected")

# The restore must keep skipping empty ids.
loose_ids, count = re.subn(
    r"if\s*\(\s*id\s*\.\s*isNotEmpty\s*\(\s*\)\s*\)\s*\n\s*"
    r"lockedParams\s*\.\s*insert\s*\(\s*id\s*\)\s*;",
    "lockedParams.insert(id);", code, count=1)
if count == 0:
    fail_stale("empty-id guard dropped")
if not verify(loose_ids):
    fail_probe("empty-id guard dropped",
               "an empty id was accepted into lockedParams")
print("probe ok: empty-id guard dropped -> rejected")

# The restore must still insert the restored ids.
no_insert, count = INSERT.subn("(void) id;", code, count=1)
if count == 0:
    fail_stale("restore insert dropped")
if not verify(no_insert):
    fail_probe("restore insert dropped",
               "a paramLocks branch that inserts nothing passed")
print("probe ok: restore insert dropped -> rejected")

# Final live re-verification (nothing was written to the real tree).
try:
    final_errors = verify()
except OSError as exc:
    print(f"FAIL: final source re-verification failed: {exc}")
    sys.exit(1)
if final_errors:
    print("FAIL: final source re-verification failed:")
    for error in final_errors:
        print(f"  - {error}")
    sys.exit(1)
print("CV-043 OK")
