#!/usr/bin/env python3
"""check_sync_map_growth.py — pin the vertical-slice Plan's Task-2 Step-3
sync-map append contract BEFORE dsp/CorvusEffects.h exists.

SoT: docs/superpowers/plans/2026-08-08-corvus-instrument-vertical-slice.md
Task 2 Step 3 ("Update the explicit sync map"), :136-138:
  Add `dsp/CorvusEffects.h` to the sync script and run both copy and
  `-VerifyOnly` modes.

Task 1 Step 3 (already pinned by check_sync_script_contract.py) forbids
directory mirroring, so the only correct way to add the new header is an
explicit array append. This checker pins the Step-3 sentence itself, and
once BOTH scripts/sync_corvus_source.ps1 AND source/DrippyFX/dsp/
CorvusEffects.h exist, verifies the sync script's explicit path array
actually mentions dsp/CorvusEffects.h — a missed append makes every
Windows sync silently omit the new shared-DSP header.

Checks:
  A. The Task-2 Step-3 block still declares the documented contract
     (read-only, marker-stripped): the "Add dsp/CorvusEffects.h to the
     sync script" sentence plus the both-modes (copy + -VerifyOnly) run.
  B. Once BOTH files exist, the sync script must mention
     dsp/CorvusEffects.h in its explicit path array.
     SKIPPED while either file is absent — not a pass-fake: a printed
     SKIP line cites the rule.
Negative probes (never on the real tree):
  N1. drop the Step-3 sentence from the Plan block -> FAIL
  N2. drift the -VerifyOnly mode out of the Step-3 sentence -> FAIL
  N3. stub sync script with an explicit array lacking the header while
      a stub header exists -> FAIL (temp dir, not the real tree)
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
SYNC = os.path.join(ROOT, "scripts", "sync_corvus_source.ps1")
EFFECTS = os.path.join(ROOT, "source", "DrippyFX", "dsp",
                       "CorvusEffects.h")


def strip_markers(text: str) -> str:
    """Neutralize markdown emphasis/backticks so regexes match plain words."""
    return re.sub(r"`+", "", text)


def task2_step3_block(plan_text: str) -> str:
    """Task-2 Step-3 region: 'Step 3:' checkbox to the next step checkbox."""
    strip = strip_markers(plan_text)
    m = re.search(r"^- \[ \] \*\*Step 3: Update the explicit sync map\*\*",
                  strip, re.M)
    if not m:
        return ""
    nxt = re.search(r"^- \[ \] \*\*Step", strip[m.end():], re.M)
    end = m.end() + (nxt.start() if nxt else len(strip) - m.end())
    return strip[m.start():end]


def plan_checks(block: str):
    res = []
    res.append(("block is non-empty", bool(block.strip()),
                "Task-2 Step-3 checkbox found"))
    res.append(("'Add dsp/CorvusEffects.h to the sync script' declared",
                re.search(r"Add {0,2}dsp/CorvusEffects\.h {0,2}to the "
                          r"sync script", block) is not None,
                "explicit append sentence"))
    res.append(("'run both copy and -VerifyOnly modes' declared",
                re.search(r"run\s+both\s+copy\s+and\s+-VerifyOnly\s+modes",
                          block) is not None,
                "both-modes run"))
    return res


def sync_checks(code: str):
    """Part B: once the sync script and header both exist."""
    res = []
    res.append(("sync script mentions dsp/CorvusEffects.h",
                "dsp/CorvusEffects.h" in code.replace("\\", "/"), "map growth"))
    return res


def run_plan(text: str, verbose=True):
    block = task2_step3_block(text)
    ok = True
    for label, good, detail in plan_checks(block):
        if verbose:
            print(("PASS " if good else "FAIL ") +
                  "sync-map(plan): " + label + " (%s)" % detail)
        ok = ok and good
    return 0 if ok else 1


def run_sync(path: str, verbose=True):
    with open(path, "r", encoding="utf-8", errors="replace") as f:
        code = f.read()
    ok = True
    for label, good, detail in sync_checks(code):
        if verbose:
            print(("PASS " if good else "FAIL ") +
                  "sync-map(psl): " + label + " (%s)" % detail)
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

    # Part B: only when BOTH the sync script and the extracted header exist
    sync_exists = os.path.isfile(SYNC)
    effects_exists = os.path.isfile(EFFECTS)
    if sync_exists and effects_exists:
        if run_sync(SYNC) != 0:
            return 1
    else:
        print("SKIP sync-map(psl): dsp/CorvusEffects.h "
              + ("ABSENT" if not effects_exists else "present")
              + " and scripts/sync_corvus_source.ps1 "
              + ("ABSENT" if not sync_exists else "present")
              + " — Part B not engaged (auto-activates when Plan Task 2 "
              "lands: explicit-array append of the shared-DSP header)")

    # Negative probes on temp copies (never the real tree)
    negs = [
        ("drop the Step-3 'Add dsp/CorvusEffects.h to the sync script' "
         "sentence",
         lambda s: s.replace("Add `dsp/CorvusEffects.h` to the sync "
                             "script and run both copy and `-VerifyOnly` "
                             "modes.", "")),
        ("drift -VerifyOnly out of the Step-3 both-modes run",
         lambda s: s.replace("run both copy and `-VerifyOnly` modes.",
                             "run the copy mode.")),
    ]
    ok_all = True
    tmpdir = tempfile.mkdtemp(prefix="check_sync_map_growth_")
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
            print("PASS sync-map(plan): negative rejected -> " + label)

        # Part-B negative: stub sync script whose explicit array omits
        # the header, evaluated with a stub header present (temp dir).
        stub_sync = os.path.join(tmpdir, "sync_corvus_source.ps1")
        with open(stub_sync, "w", encoding="utf-8") as f:
            f.write("$paths = @('PluginProcessor.h','tests/"
                    "CorvusDspTests.cpp')\n")
        if run_sync(stub_sync, verbose=False) == 0:
            print("GATE_FAIL: stub sync script (explicit array without "
                  "dsp/CorvusEffects.h) was NOT rejected — checker too weak")
            return 1
        print("PASS sync-map(psl): negative rejected -> explicit array "
              "missing dsp/CorvusEffects.h fails")
    finally:
        shutil.rmtree(tmpdir, ignore_errors=True)

    print("OK sync-map growth contract pinned (Plan Task-2 Step-3 "
          "guarded; Part B auto-activates when both files exist)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
