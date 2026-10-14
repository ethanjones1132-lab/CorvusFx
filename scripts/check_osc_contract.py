#!/usr/bin/env python3
"""check_osc_contract.py — pin the Corvus Instrument vertical slice Plan's
Task-3 WavetableOscillator doc contract BEFORE the oscillator header exists.

SoT: docs/superpowers/plans/2026-08-08-corvus-instrument-vertical-slice.md
Task 3 ("Implement a band-limited factory wavetable oscillator"), Interfaces
block:
  - Produces: enum class FactoryWave { Sine, Triangle, Saw, Square }
  - Produces: WavetableOscillator::prepare(double sampleRate)
  - Produces: WavetableOscillator::setFrequency(float hz)
  - Produces: WavetableOscillator::setWave(FactoryWave wave)
  - Produces: WavetableOscillator::reset(float phase = 0.0f)
  - Produces: WavetableOscillator::process() -> float
Step 3: power-of-two 2048-sample tables, progressively band-limited by
capping harmonics per octave, table selected from the fundamental frequency,
linear interpolation, clamp invalid frequency to zero output, reject
non-positive sample rates in prepare with jassertfalse plus safe silence.

Nothing until now pins the Plan text itself, so the contract could be
silently rewritten before implementation and every later Task-3 test would
inherit a drifted spec.

Checks:
  A. The Task 3 block still declares the documented contract (read-only,
     backtick-stripped): file name, the FactoryWave enum line, all five
     method signatures, the 2048 mipmapped-table constraint, the harmonic
     cap, linear interpolation, the invalid-frequency clamp, and the
     jassertfalse/safe-silence rejection.
  B. Once source/DrippyFX/instrument/WavetableOscillator.h exists, the
     interface names named in the Plan appear in the header (FactoryWave,
     prepare/setFrequency/setWave/reset/process). SKIPPED while the file is
     absent — not a pass-fake: a printed SKIP line cites the rule.
Negative probes (never on the real tree):
  N1. rewrite the Task-3 block dropping the FactoryWave line -> FAIL
  N2. rewrite it dropping the jassertfalse constraint sentence -> FAIL
  N3. temp-create a stub WavetableOscillator.h missing setWave -> FAIL
      (part B, exercised against a temp file, not the real header path)
  N4. drift the reset signature (phase default removed) -> FAIL
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
OSC_HDR = os.path.join(ROOT, "source", "DrippyFX", "instrument",
                       "WavetableOscillator.h")


def strip_markers(text: str) -> str:
    """Neutralize markdown emphasis/backticks so regexes match plain words."""
    return re.sub(r"`+", "", text)


def task3_block(plan_text: str) -> str:
    """Source region of the Task 3 section (heading to the next task)."""
    m = re.search(r"^#{2,4}\s*Task 3:.*$", plan_text, re.M)
    if not m:
        return ""
    nxt = re.search(r"^#{2,4}\s*Task \d+:.*$", plan_text[m.end():], re.M)
    end = m.end() + (nxt.start() if nxt else len(plan_text) - m.end())
    return plan_text[m.start():end]


def plan_checks(code: str):
    """Backtick-stripped Task-3 block checks. Return list of (label, ok, detail)."""
    res = []
    res.append(("block is non-empty", bool(code.strip()),
                "Task 3 heading found"))
    res.append(("oscillator file WavetableOscillator.h declared",
                "WavetableOscillator.h" in code, "Files"))
    res.append(("FactoryWave enum with the four factory voices declared",
                re.search(r"enum\s+class\s+FactoryWave\s*\{[^}]*Sine[^}]*"
                          r"Triangle[^}]*Saw[^}]*Square", code, re.S)
                is not None, "enum shape"))
    res.append(("WavetableOscillator::prepare(double sampleRate) declared",
                re.search(r"WavetableOscillator::prepare\s*\(\s*double\s+"
                          r"sampleRate\s*\)", code) is not None,
                "prepare shape"))
    res.append(("WavetableOscillator::setFrequency(float hz) declared",
                re.search(r"WavetableOscillator::setFrequency\s*\(\s*float\s+"
                          r"hz\s*\)", code) is not None, "setFrequency shape"))
    res.append(("WavetableOscillator::setWave(FactoryWave wave) declared",
                re.search(r"WavetableOscillator::setWave\s*\(\s*FactoryWave\s+"
                          r"wave\s*\)", code) is not None, "setWave shape"))
    res.append(("WavetableOscillator::reset(float phase = 0.0f) declared",
                re.search(r"WavetableOscillator::reset\s*\(\s*float\s+phase\s*"
                          r"=\s*0\.0f\s*\)", code) is not None, "reset shape"))
    res.append(("WavetableOscillator::process() -> float declared",
                re.search(r"WavetableOscillator::process\s*\(\s*\)\s*->\s*float",
                          code) is not None, "process shape"))
    res.append(("power-of-two 2048-sample tables declared",
                re.search(r"power-of-two\s+2048-sample\s+tables", code)
                is not None, "mipmap size"))
    res.append(("harmonic caps per octave (progressively band-limited)",
                re.search(r"capping\s+harmonics\s+per\s+octave", code)
                is not None, "band-limiting"))
    res.append(("table selected from fundamental frequency",
                re.search(r"select\s+the\s+table\s+from\s+fundamental\s+"
                          r"frequency", code) is not None, "table select"))
    res.append(("linear interpolation between adjacent samples",
                re.search(r"linear\s+interpolation\s+between\s+adjacent\s+"
                          r"samples", code) is not None, "interpolation"))
    res.append(("invalid frequency clamped to zero output",
                re.search(r"Clamp\s+invalid\s+frequency\s+to\s+zero\s+output",
                          code) is not None, "freq clamp"))
    res.append(("non-positive sample rate rejected in prepare with "
                "jassertfalse plus safe silence",
                re.search(r"reject\s+non-positive\s+sample\s+rates\s+in\s+"
                          r"prepare\s+with\s+jassertfalse\s+plus\s+safe\s+"
                          r"silence", code) is not None, "prepare reject"))
    return res


def header_checks(code: str):
    """Once the oscillator header exists, its interface must match the Plan."""
    res = []
    res.append(("header declares enum class FactoryWave with the four voices",
                re.search(r"enum\s+class\s+FactoryWave", code) is not None,
                "enum"))
    res.append(("header defines struct/class WavetableOscillator",
                re.search(r"(struct|class)\s+WavetableOscillator", code)
                is not None, "oscillator type"))
    res.append(("prepare member exists", re.search(r"\bprepare\s*\(", code)
                is not None, "prepare"))
    res.append(("setFrequency member exists",
                re.search(r"\bsetFrequency\s*\(", code) is not None,
                "setFrequency"))
    res.append(("setWave member exists", re.search(r"\bsetWave\s*\(", code)
                is not None, "setWave"))
    res.append(("reset member exists", re.search(r"\breset\s*\(", code)
                is not None, "reset"))
    res.append(("process member exists", re.search(r"\bprocess\s*\(\s*\)",
                code) is not None, "process"))
    return res


def run_plan(text: str, verbose=True):
    code = strip_markers(text)
    block = task3_block(code)
    ok = True
    for label, good, detail in plan_checks(block):
        if verbose:
            print(("PASS " if good else "FAIL ") + "osc-contract(plan): "
                  + label + " (%s)" % detail)
        ok = ok and good
    return 0 if ok else 1


def run_header(path: str, verbose=True):
    with open(path, "r", encoding="utf-8") as f:
        code = strip_markers(f.read())
    ok = True
    for label, good, detail in header_checks(code):
        if verbose:
            print(("PASS " if good else "FAIL ") + "osc-contract(hdr): "
                  + label + " (%s)" % detail)
        ok = ok and good
    return 0 if ok else 1


def main():
    if not os.path.isfile(PLAN):
        print("GATE_FAIL: %s missing" % PLAN)
        return 1
    with open(PLAN, "r", encoding="utf-8") as f:
        plan_text = f.read()
    rc = run_plan(plan_text)
    if rc != 0:
        return 1

    # Part B: only while the header exists
    if os.path.isfile(OSC_HDR):
        if run_header(OSC_HDR) != 0:
            return 1
    else:
        print("SKIP osc-contract(hdr): no %s yet — header checks not "
              "engaged (will auto-activate when Task 3 is implemented)"
              % os.path.relpath(OSC_HDR, ROOT))

    # Negative probes on temp copies of the PLAN (never the real tree)
    negs = [
        ("drop the FactoryWave enum line from Task 3",
         lambda s: s.replace("`enum class FactoryWave { Sine, Triangle, "
                             "Saw, Square }`", "")),
        ("drop the jassertfalse constraint sentence from Task 3",
         lambda s: s.replace("reject non-positive sample rates in "
                             "`prepare` with `jassertfalse` plus safe "
                             "silence.", "")),
        ("drift the reset signature (phase default removed)",
         lambda s: s.replace("`WavetableOscillator::reset(float phase "
                             "= 0.0f)`",
                             "`WavetableOscillator::reset(float phase)`")),
    ]
    tmpdir = tempfile.mkdtemp(prefix="check_osc_contract_")
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
            print("PASS osc-contract(plan): negative rejected -> " + label)

        # Part-B negative: stub oscillator header missing setWave (temp dir)
        stub = os.path.join(tmpdir, "WavetableOscillator.h")
        with open(stub, "w", encoding="utf-8") as f:
            f.write("enum class FactoryWave { Sine, Triangle, Saw, Square };\n"
                    "struct WavetableOscillator\n"
                    "{\n"
                    "    void prepare (double sampleRate);\n"
                    "    void setFrequency (float hz);\n"
                    "    void reset (float phase = 0.0f);\n"
                    "    float process();\n"
                    "};\n")
        if run_header(stub, verbose=False) == 0:
            print("GATE_FAIL: stub oscillator header missing setWave was "
                  "NOT rejected — checker too weak")
            return 1
        print("PASS osc-contract(hdr): negative rejected -> stub header "
              "missing setWave() fails")
    finally:
        shutil.rmtree(tmpdir, ignore_errors=True)

    print("OK oscillator contract pinned (Plan Task-3 WavetableOscillator "
          "doc contract guarded before the oscillator header exists)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
