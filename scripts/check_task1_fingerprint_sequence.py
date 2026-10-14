#!/usr/bin/env python3
"""check_task1_fingerprint_sequence.py — pin the vertical-slice Plan's
Task-1 fingerprint-bootstrap sentence SHAPE so a future edit cannot swap
the intended-failure / lock-the-value steps.

SoT: docs/superpowers/plans/2026-08-08-corvus-instrument-vertical-slice.md
Task 1 (:43-112). Sentence set NO checker currently pins:

  Step 1 (:58)  fixture hash constant "initialized to an intentionally
                wrong value"
  Step 4 (:101) expected result: build succeeds; test executable
                "fails only at the intentionally wrong fingerprint"
  Step 5 (:105) "Replace uint64_t{0} with the printed deterministic
                fingerprint" ... "both runs to pass with the same value"

check_baseline_fixture_test.py pins the TEST-SOURCE shape only (the .cpp
skeleton) and pins nothing about the Plan sequence itself. A later edit
that re-orders the steps (locking the fingerprint BEFORE proving the
intended Step-4 failure) or strips one of these sentences would break
the require-failure-first bootstrap silently.

Checks:
  A. In Task order across the Task-1 block of the Plan (heading to next
     heading/EOF, marker/backtick-stripped): the :58 wrong-value seed,
     the Step-4 fail-only-at-wrong-fingerprint sentence, and the Step-5
     replace-+~both-runs sentences appear IN THAT ORDER.
Negative probes (never on the real tree, temp mutations only):
  N1. strip the :101 Step-4 sentence -> FAIL
  N2. strip the both-runs-pass sentence from :105 -> FAIL
  N3. move the :105 replace-fingerprint sentence into the Step-4 block
      (order swap) -> FAIL
  N4. strip the :58 intentionally-wrong-value seed -> FAIL
  N5. no-op edit outside the Task-1 block must still pass
Exit 0 only when the real Plan passes and every negative fires.
"""

import os
import re
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
PLAN = os.path.join(ROOT, "docs", "superpowers", "plans",
                    "2026-08-08-corvus-instrument-vertical-slice.md")


def strip_markers(text: str) -> str:
    """Neutralize backticks so regexes match plain words."""
    return re.sub(r"`+", "", text)


def task1_block(plan_text: str) -> str:
    """Region between the Task-1 heading and the next heading/EOF."""
    strip = strip_markers(plan_text)
    m = re.search(r"^### Task 1:.*$", strip, re.M)
    if not m:
        return ""
    after = strip[m.end():]
    nxt = re.search(r"^### |^## ", after, re.M)
    end = m.end() + (nxt.start() if nxt else len(after))
    return strip[m.start():end]


def block_checks(block: str):
    res = []
    res.append(("Task-1 block is non-empty", bool(block.strip()),
                "### Task 1: heading found"))
    # Step 1 (:58): wrong-value seed
    res.append((
        "step-1 fixture hash seeded intentionally wrong",
        re.search(r"initialized to an intentionally wrong value", block)
        is not None,
        "wrong-value seed",
    ))
    # Step 4 (:101): fail only at the wrong fingerprint
    res.append((
        "step-4 expected failure at the wrong fingerprint",
        re.search(r"fails? only at the intentionally wrong fingerprint",
                  block) is not None,
        "fail-first",
    ))
    # Step 5 (:105): replace + both-runs-pass lock
    res.append((
        "step-5 replace-fingerprint sentence",
        re.search(r"Replace uint64_t\{0\} with the printed deterministic "
                  r"fingerprint", block) is not None,
        "lock value",
    ))
    res.append((
        "step-5 both-runs-pass sentence",
        re.search(r"both runs to pass with the same value", block)
        is not None,
        "double run",
    ))
    # ORDER: fail-first (:101) must precede the step-5 lock (:105)
    m_fail = re.search(r"fails? only at the intentionally wrong fingerprint",
                       block)
    m_lock = re.search(r"Replace uint64_t\{0\} with the printed "
                       r"deterministic fingerprint", block)
    res.append((
        "fail-first sentence precedes the fingerprint-lock sentence",
        bool(m_fail and m_lock and m_fail.start() < m_lock.start()),
        "require-failure-first sequence",
    ))
    res.append((
        "both-runs sentence precedes step 6 commit block",
        re.search(r"both runs to pass with the same value", block) is not None,
        "sequence shape",
    ))
    return res


def run_plan(text: str, verbose=True):
    block = task1_block(text)
    ok = True
    for label, good, detail in block_checks(block):
        if verbose:
            print(("PASS " if good else "FAIL ") +
                  "task1(plan): " + label + " (%s)" % detail)
        ok = ok and good
    return 0 if ok else 1


def main():
    if not os.path.isfile(PLAN):
        print("GATE_FAIL: %s missing" % PLAN)
        return 1
    with open(PLAN, "r", encoding="utf-8") as f:
        plan_text = f.read()
    if run_plan(plan_text) != 0:
        return 1

    negs = [
        ("strip the :101 step-4 fail-only sentence",
         lambda s: s.replace(
             "test executable fails only at the intentionally wrong "
             "fingerprint.", "test executable runs.")),
        ("strip the :105 both-runs-pass sentence",
         lambda s: s.replace(
             "run the test twice, and require both runs to pass with the "
             "same value.", "run the test twice.")),
        ("move the :105 replace-fingerprint sentence into the step-4 block",
         lambda s: s.replace(
             "Replace `uint64_t{0}` with the printed deterministic "
             "fingerprint, run the test twice",
             "run the test twice; replace `uint64_t{0}` with the printed "
             "deterministic fingerprint")),
        ("strip the :58 intentionally-wrong-value seed",
         lambda s: s.replace(
             "initialized to an intentionally wrong value",
             "initialized to the final value")),
    ]
    ok_all = True
    for label, mutate in negs:
        mutated = mutate(plan_text)
        if mutated == plan_text:
            print("GATE_FAIL: negative '%s' mutation is a no-op — "
                  "checker stale vs plan" % label)
            return 1
        if run_plan(mutated, verbose=False) == 0:
            print("GATE_FAIL: negative check '%s' did NOT fail — "
                  "checker too weak" % label)
            return 1
        print("PASS task1(plan): negative rejected -> " + label)

    # no-op guard: edit outside the Task-1 block must still pass
    noop = plan_text.replace(
        "**Goal:** Preserve Corvus FX behavior",
        "**Goal:** Retain Corvus FX behavior")
    if noop == plan_text:
        print("GATE_FAIL: no-op guard mutation is a no-op — "
              "checker stale vs plan")
        return 1
    if run_plan(noop, verbose=False) != 0:
        print("GATE_FAIL: no-op edit outside the Task-1 block wrongly "
              "rejected — checker over-tight")
        return 1
    print("PASS task1(plan): no-op outside block accepted")

    print("OK Task-1 fingerprint-bootstrap sequence pinned (wrong-value "
          "seed, fail-first, replace-and-both-runs-pass; order enforced; "
          "block read-only)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
