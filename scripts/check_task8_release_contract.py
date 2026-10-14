#!/usr/bin/env python3
"""check_task8_release_contract.py — pin the vertical-slice Plan's Task-8
release-verification contract (the final task block that decides whether
the slice ships).

SoT: docs/superpowers/plans/2026-08-08-corvus-instrument-vertical-slice.md
Task 8 (:353-398). Sentence set NO checker currently pins:

  Step 1 (:370)  four-target build invocation
                 --target CorvusDSPTests DrippyFX_VST3 CorvusInstrument_VST3
                 CorvusInstrument_Standalone
  Step 2 (:379)  "Confirm the deployed instrument hash equals the build
                 output hash."
  Step 3 (:383)  Standalone smoke: "load all five patches, play MIDI ...,
                 exercise Flight, press panic, and exit cleanly"
  Step 4 (:387)  real DAW: "save the project, reopen it, and verify
                 patch/state recall" + FX identity still resolves separately
  Step 5 (:391)  "Do not claim commercial release readiness."

check_console_target_contract.py pins the CorvusDSPTests target DECLARATION
(Plan Task-1 Step-2); nothing pins the Task-8 BUILD INVOCATION, and grep
across scripts/check_*.py shows zero checkers name CorvusDSPTests together
with CorvusInstrument_VST3, zero mention "commercial". A later edit that
silently drops the four-target build, the hash-equality confirmation, the
five-patch smoke sweep, or the no-commercial-claim rule would let Task 8
ship without proving deploy/recall.

Checks:
  A. The `### Task 8:` block (heading to the next `### `/`## ` heading or
     EOF) still carries the pinned sentence set (marker/backtick-stripped).
Negative probes (never on the real tree, temp copies only):
  N1. drop `CorvusInstrument_Standalone` from the Step-1 target list -> FAIL
  N2. drop the hash-equality sentence from Step 2 -> FAIL
  N3. drop "Do not claim commercial release readiness" -> FAIL
  N4. drop the Step-4 save/reopen/recall sentence -> FAIL
  N5. drop the five-patch smoke sentence from Step 3 -> FAIL
  N6. no-op edit outside the Task-8 block must still pass (probes detect
      real exile, not any edit)
Exit 0 only when the real Plan passes and every negative fires.
"""

import os
import re
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
PLAN = os.path.join(ROOT, "docs", "superpowers", "plans",
                    "2026-08-08-corvus-instrument-vertical-slice.md")


def strip_markers(text: str) -> str:
    """Neutralize markdown emphasis/backticks so regexes match plain words."""
    return re.sub(r"`+", "", text)


def task8_block(plan_text: str) -> str:
    """Region between the `### Task 8:` heading and the next heading/EOF."""
    strip = strip_markers(plan_text)
    m = re.search(r"^### Task 8:.*$", strip, re.M)
    if not m:
        return ""
    after = strip[m.end():]
    nxt = re.search(r"^### |^## ", after, re.M)
    end = m.end() + (nxt.start() if nxt else len(after))
    return strip[m.start():end]


def task8_checks(block: str):
    res = []
    res.append(("block is non-empty", bool(block.strip()),
                "### Task 8: heading found"))

    def has(pattern, label, detail):
        res.append((label, re.search(pattern, block) is not None, detail))

    # Step 1: four-target build invocation (:370)
    has(r"--target\s+CorvusDSPTests\s+DrippyFX_VST3\s+"
        r"CorvusInstrument_VST3\s+CorvusInstrument_Standalone",
        "Step-1 four-target build list declared", "build invocation")
    # Step 2: hash equality (:379)
    has(r"Confirm the deployed instrument hash equals the build output hash",
        "Step-2 hash-equality confirmation declared", "deploy/recall")
    # Step 3: Standalone smoke sweep (:383)
    has(r"load all five patches[^.]*exercise Flight[^.]*press panic[^.]*"
        r"exit cleanly",
        "Step-3 five-patch Standalone smoke sweep declared", "smoke")
    # Step 4: real-DAW save/reopen/recall + FX identity (:387)
    has(r"save the project, reopen it, and verify patch/state recall",
        "Step-4 save/reopen/recall sentence declared", "daw recall")
    has(r"identity still resolves separately",
        "Step-4 FX-identity-separate sentence declared", "daw recall")
    # Step 5: anti-overclaim (:391)
    has(r"Do not claim commercial release readiness",
        "Step-5 no-commercial-claim sentence declared", "honesty")
    return res


def run_plan(text: str, verbose=True):
    block = task8_block(text)
    ok = True
    for label, good, detail in task8_checks(block):
        if verbose:
            print(("PASS " if good else "FAIL ") +
                  "task8(plan): " + label + " (%s)" % detail)
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
        ("drop CorvusInstrument_Standalone from the Step-1 target list",
         lambda s: s.replace(" CorvusInstrument_Standalone\n", "\n")),
        ("drop the Step-2 hash-equality sentence",
         lambda s: s.replace(
             "Confirm the deployed instrument hash equals the build "
             "output hash.", "")),
        ("drop the Step-5 no-commercial-claim sentence",
         lambda s: s.replace(
             "Do not claim commercial release readiness.", "")),
        ("drop the Step-4 save/reopen/recall sentence",
         lambda s: s.replace(
             "save the project, reopen it, and verify patch/state recall. ",
             "")),
        ("drop the Step-3 five-patch smoke sentence",
         lambda s: s.replace(
             "load all five patches", "")),
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
        print("PASS task8(plan): negative rejected -> " + label)

    # no-op guard: edit outside the Task-8 block must still pass
    noop = plan_text.replace(
        "**Goal:** Preserve Corvus FX behavior",
        "**Goal:** Retain Corvus FX behavior")
    if noop == plan_text:
        print("GATE_FAIL: no-op guard mutation is a no-op — "
              "checker stale vs plan")
        return 1
    if run_plan(noop, verbose=False) != 0:
        print("GATE_FAIL: no-op edit outside the Task-8 block wrongly "
              "rejected — checker over-tight")
        return 1
    print("PASS task8(plan): no-op outside block accepted")

    print("OK Task-8 release-verification contract pinned (four-target "
          "build, hash equality, five-patch smoke, DAW recall, "
          "no-commercial-claim; block read-only)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
