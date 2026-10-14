#!/usr/bin/env python3
"""check_global_constraints.py — pin the vertical-slice Plan's Global
Constraints block verbatim, BEFORE and AFTER any task lands.

SoT: docs/superpowers/plans/2026-08-08-corvus-instrument-vertical-slice.md
Global Constraints (:11-22). Four sentences NO checker currently pins:

  :19 "Do not add wavetable import/editing, granular playback, sampling,
       a sequencer, arpeggiator, custom UI, or unlimited modulation in
       this vertical slice."
  :20 "Keep effects global after the stereo voice mix; do not allocate
       delay or reverb instances per voice."
  :21 "Verify each changed binary against its build output and prior
       committed artifact before claiming delivery."
  :22 "Do not modify or delete existing tracked Visual Studio build
       artifacts outside the task's explicit files."

scripts/check_flight_contract.py covers only Task-6's per-voice subset;
none of the seven tasks' checkers guard this block verbatim, so any
later edit that silently rewrites the block — deleting the arpeggiator /
custom-UI / per-voice-allocator / binary-verification guard rails —
ships with no headless rejection.

Checks:
  A. The Global Constraints block (between the `## Global Constraints`
     heading and the first following `---` / `## ` heading) still
     carries all four sentences (marker-stripped, backtick-robust).
Negative probes (never on the real tree, temp copies only):
  N1. drop "arpeggiator" from the :19 sentence -> FAIL
  N2. rewrite :20 to permit per-voice allocation -> FAIL
  N3. drop the :21 binary-verification sentence -> FAIL
  N4. drop the :22 VS-artifacts sentence -> FAIL
  N5. drop the :13 git-SoT sentence -> FAIL
  N6. drop the :17 1.0e-6f tolerance sentence -> FAIL
  N7. no-op style mutation guarded (a mutation that does not change
      the block must still pass, proving probes detect real exile)
Exit 0 only when the real Plan passes and every negative fires.
"""

import os
import re
import sys
import tempfile
import shutil

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
PLAN = os.path.join(ROOT, "docs", "superpowers", "plans",
                    "2026-08-08-corvus-instrument-vertical-slice.md")


def strip_markers(text: str) -> str:
    """Neutralize markdown emphasis/backticks so regexes match plain words."""
    return re.sub(r"`+", "", text)


def global_constraints_block(plan_text: str) -> str:
    """Region between the '## Global Constraints' heading and the next
    top-level divider (`---` line or `## ` heading)."""
    strip = strip_markers(plan_text)
    m = re.search(r"^## Global Constraints\s*$", strip, re.M)
    if not m:
        return ""
    after = strip[m.end():]
    # next fenced line break pattern: a standalone rule line or a heading
    nxt = re.search(r"^(?:-{3,}\s*$|## )", after, re.M)
    end = m.end() + (nxt.start() if nxt else len(after))
    return strip[m.start():end]


def gc_checks(block: str):
    res = []
    res.append(("block is non-empty", bool(block.strip()),
                "Global Constraints heading found"))
    def has(pattern, label, detail):
        res.append((label, re.search(pattern, block) is not None, detail))

    # :13 git source of truth
    has(r"Edit the git source of truth under {1,3}C:\\Projects\\Corvus VST",
        "'Edit the git source of truth' declared", "C:/Projects SoT rule")
    # :14 explicit sync
    has(r"Sync every changed source explicitly",
        "'Sync every changed source explicitly' declared", "sync rule")
    # :15 preserve identity
    has(r"Preserve the existing Corvus FX manufacturer code, plugin code, "
        r"host identity, presets, and state behavior",
        "'Preserve the existing Corvus FX' declared", "identity rule")
    # :16 never replaces the FX binary
    has(r"it never replaces the FX binary",
        "'it never replaces the FX binary' declared", "instrument rule")
    # :17 the absolute tolerance
    has(r"behavior-preserving within a documented absolute tolerance of "
        r"1\.0e-6f", "as the 1.0e-6f tolerance declared", "tolerance rule")
    # :18 test-first
    has(r"Use test-first changes and one coherent commit per task",
        "'Use test-first changes and one coherent commit per task' declared",
        "commit rule")
    # :19 no forbidden features
    has(r"Do not add wavetable import/editing, granular playback, sampling, "
        r"a sequencer, arpeggiator, custom UI, or unlimited modulation in "
        r"this vertical slice",
        ":19 forbidden-features sentence declared (arpeggiator/custom-UI/etc)",
        "forbidden features")
    # :20 effects global, not per voice
    has(r"Keep effects global after the stereo voice mix; do not allocate "
        r"delay or reverb instances per voice",
        ":20 per-voice-allocator exclusion declared", "global effects rule")
    # :21 binary verification
    has(r"Verify each changed binary against its build output and prior "
        r"committed artifact before claiming delivery",
        ":21 binary-verification sentence declared", "binary rule")
    # :22 no VS artifact deletion
    has(r"Do not modify or delete existing tracked Visual Studio build "
        r"artifacts outside the task's explicit files",
        ":22 do-not-touch-VS-artifacts sentence declared", "artifacts rule")
    return res


def run_plan(text: str, verbose=True):
    block = global_constraints_block(text)
    ok = True
    for label, good, detail in gc_checks(block):
        if verbose:
            print(("PASS " if good else "FAIL ") +
                  "gc(plan): " + label + " (%s)" % detail)
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

    # Negative probes on temp copies (never the real tree)
    negs = [
        ("strip 'arpeggiator' from the :19 forbidden-features sentence",
         lambda s: s.replace("arpeggiator, ", "")),
        ("rewrite :20 to allow per-voice allocation",
         lambda s: s.replace("do not allocate delay or reverb instances "
                             "per voice.",
                             "delay or reverb instances may allocate per "
                             "voice.")),
        ("drop the :21 binary-verification sentence",
         lambda s: s.replace(
             "Verify each changed binary against its build output and "
             "prior committed artifact before claiming delivery.\n", "")),
        ("drop the :22 VS-artifacts sentence",
         lambda s: s.replace(
             "Do not modify or delete existing tracked Visual Studio "
             "build artifacts outside the task's explicit files.\n", "")),
        ("drop the :13 git-SoT sentence",
         lambda s: s.replace(
             "Edit the git source of truth under "
             "`C:\\Projects\\Corvus VST\\source\\DrippyFX` first.\n", "")),
        ("drop the :17 1.0e-6f tolerance sentence",
         lambda s: s.replace(
             "behavior-preserving within a documented absolute tolerance "
             "of `1.0e-6f` on deterministic fixtures.\n", "")),
    ]
    ok_all = True
    tmpdir = tempfile.mkdtemp(prefix="check_global_constraints_")
    try:
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
            print("PASS gc(plan): negative rejected -> " + label)

        # no-op guard: a mutation that edits a DIFFERENT part of the plan
        # must still pass (proves probe fails are caused by real exile of
        # the pinned text, not by any edit at all)
        noop = plan_text.replace(
            "**Goal:** Preserve Corvus FX behavior",
            "**Goal:** Retain Corvus FX behavior")
        if noop == plan_text:
            print("GATE_FAIL: no-op guard mutation is a no-op — "
                  "checker stale vs plan")
            return 1
        if run_plan(noop, verbose=False) != 0:
            print("GATE_FAIL: no-op edit outside the Global Constraints "
                  "block wrongly rejected — checker over-tight")
            return 1
        print("PASS gc(plan): no-op outside block accepted")
    finally:
        shutil.rmtree(tmpdir, ignore_errors=True)

    print("OK Global-Constraints contract pinned (four sentences + "
          "identity/tolerance rules guarded verbatim; block read-only)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
