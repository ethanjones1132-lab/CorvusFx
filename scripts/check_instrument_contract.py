#!/usr/bin/env python3
"""check_instrument_contract.py — pin the vertical-slice Plan's Task-5
CorvusInstrument processor/state contract BEFORE
CorvusInstrumentProcessor.h exists.

SoT: docs/superpowers/plans/2026-08-08-corvus-instrument-vertical-slice.md
Task 5 ("Add the distinct Corvus Instrument processor and state"):
  Produces: CorvusInstrumentProcessor : juce::AudioProcessor (a plain
  class declaration, not a template)
  Produces parameter IDs: osc_wave, attack, decay, sustain, release,
  fx_amount, flight, output
  Produces state root: CorvusInstrumentState with integer schemaVersion=1
  Step 2 requires: manufacturer code Crvs, plugin code Cvi1, IS_SYNTH
  TRUE, "Leave the existing DrippyFX target fields unchanged"
  Step 3 requires: a stable wrapper around juce::GenericAudioProcessorEditor
  Step 4 requires: reject wrong-root or unsupported-version data, leave
  current state unchanged

Checks:
  A. The Task 5 block still declares the documented contract
     (read-only): the eight parameter IDs, the CorvusInstrumentState
     root with schemaVersion=1, the Crvs/Cvi1 codes, IS_SYNTH TRUE,
     the unchanged-DrippyFX-fields sentence, the generic editor
     wrapper, and the version-reject semantics.
  B. Once source/DrippyFX/instrument/CorvusInstrumentProcessor.h
     exists, the header must declare all eight parameter IDs.
     SKIPPED while the file is absent — a printed SKIP line cites the
     rule (auto-activates when Task 5 lands on Windows).
Negative probes (never on the real tree):
  N1. drop one of the eight parameter IDs from the Task-5 block -> FAIL
  N2. schemaVersion=1 -> 2 in the Task-5 block -> FAIL
  N3. drop the "Leave the existing DrippyFX target fields unchanged"
      sentence -> FAIL
  N4. stub processor header missing the `flight` ID -> FAIL
      (part B, exercised against a temp dir, not the real path)
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
HEADER = os.path.join(ROOT, "source", "DrippyFX", "instrument",
                      "CorvusInstrumentProcessor.h")

PARAM_IDS = ["osc_wave", "attack", "decay", "sustain", "release",
             "fx_amount", "flight", "output"]


def strip_markers(text: str) -> str:
    """Neutralize markdown backticks so regexes match plain words."""
    return re.sub(r"`+", "", text)


def task5_block(plan_text: str) -> str:
    """Source region of Task 5 (its heading to the next ###/end)."""
    strip = strip_markers(plan_text)
    m = re.search(r"^###\s+Task 5:.*$", strip, re.M)
    if not m:
        return ""
    nxt = re.search(r"^###\s+Task \d+:.*$", strip[m.end():], re.M)
    end = m.end() + (nxt.start() if nxt else len(strip) - m.end())
    return strip[m.start():end]


def plan_checks(block: str):
    """Task-5 block checks. (label, ok, detail) tuples."""
    res = []
    res.append(("block is non-empty", bool(block.strip()),
                "Task 5 heading found"))
    res.append(("CorvusInstrumentProcessor : juce::AudioProcessor declared",
                re.search(r"CorvusInstrumentProcessor\s*:\s*"
                          r"juce::AudioProcessor", block) is not None,
                "processor class"))
    for pid in PARAM_IDS:
        res.append(("parameter ID declared: " + pid,
                    re.search(r"(?<![A-Za-z0-9_])" + re.escape(pid) +
                              r"(?![A-Za-z0-9_])", block) is not None,
                    "parameter id"))
    res.append(("parameter-ID production line intact",
                re.search(r"Produces\s+parameter\s+IDs:\s*osc_wave,\s*"
                          r"attack,\s*decay,\s*sustain,\s*release,\s*"
                          r"fx_amount,\s*flight,\s*output", block)
                is not None, "id set line"))
    res.append(("CorvusInstrumentState root declared",
                re.search(r"CorvusInstrumentState", block) is not None,
                "state root"))
    res.append(("schemaVersion=1 declared",
                re.search(r"schemaVersion\s*=\s*1", block) is not None,
                "schema id"))
    res.append(("manufacturer code Crvs required",
                re.search(r"(?<![A-Za-z0-9_])Crvs(?![A-Za-z0-9_])", block)
                is not None, "manufacturer code"))
    res.append(("plugin code Cvi1 required",
                re.search(r"(?<![A-Za-z0-9_])Cvi1(?![A-Za-z0-9_])", block)
                is not None, "plugin code"))
    res.append(("IS_SYNTH TRUE required",
                re.search(r"IS_SYNTH\s+TRUE", block) is not None,
                "synth identity"))
    res.append(("DrippyFX target fields must stay unchanged",
                re.search(r"Leave\s+the\s+existing\s+DrippyFX\s+target\s+"
                          r"fields\s+unchanged", block) is not None,
                "fx identity retention"))
    res.append(("generic editor wrapper required",
                re.search(r"wrapper\s+around\s*juce::"
                          r"GenericAudioProcessorEditor", block)
                is not None, "editor wrapper"))
    res.append(("version/wrong-root reject semantics required",
                re.search(r"Reject\s+XML\s+or\s+binary\s+data\s+with\s+the\s+"
                          r"wrong\s+root\s+or\s+unsupported\s+version", block)
                is not None, "version reject"))
    return res


def header_checks(code: str):
    """Once the processor header exists, it must match the contract."""
    res = []
    res.append(("CorvusInstrumentProcessor present in header",
                re.search(r"CorvusInstrumentProcessor", code) is not None,
                "processor class"))
    for pid in PARAM_IDS:
        res.append(("parameter ID present in header: " + pid,
                    re.search(r"(?<![A-Za-z0-9_])" + re.escape(pid) +
                              r"(?![A-Za-z0-9_])", code) is not None,
                    "parameter id"))
    return res


def run_plan(text: str, verbose=True):
    block = task5_block(text)
    ok = True
    for label, good, detail in plan_checks(block):
        if verbose:
            print(("PASS " if good else "FAIL ") +
                  "instr(plan): " + label + " (%s)" % detail)
        ok = ok and good
    return 0 if ok else 1


def run_header(path: str, verbose=True, include_implementation=False):
    with open(path, "r", encoding="utf-8", errors="replace") as f:
        code = f.read()
    ok = True
    if include_implementation:
        with open(os.path.splitext(path)[0] + ".cpp", encoding="utf-8") as implementation:
            code += "\n" + implementation.read()
    for label, good, detail in header_checks(code):
        if verbose:
            print(("PASS " if good else "FAIL ") +
                  "instr(hdr): " + label + " (%s)" % detail)
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

    # Part B: only while the processor header exists
    if os.path.isfile(HEADER):
        if run_header(HEADER, include_implementation=True) != 0:
            return 1
    else:
        print("SKIP instr(hdr): no %s yet — header checks not "
              "engaged (will auto-activate when Plan Task 5 is "
              "implemented on Windows)" % os.path.relpath(HEADER, ROOT))

    # Negative probes on temp copies (never the real tree)
    negs = [
        ("drop the flight parameter ID from Task 5",
         lambda s: s.replace("fx_amount, `flight`, `output`",
                             "fx_amount, `output`")
                   .replace("`fx_amount`, `flight`, `output`",
                            "`fx_amount`, `output`")),
        ("drift schemaVersion 1 to 2 in Task 5",
         lambda s: s.replace("schemaVersion=1", "schemaVersion=2")),
        ("drop the unchanged-DrippyFX-fields sentence",
         lambda s: s.replace("Leave the existing `DrippyFX` target fields "
                             "unchanged.", "Free to rename the FX target.")
                   .replace("Leave the existing DrippyFX target fields "
                            "unchanged.", "Free to rename the FX target.")),
    ]
    tmpdir = tempfile.mkdtemp(prefix="check_instrument_contract_")
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
            print("PASS instr(plan): negative rejected -> " + label)

        # Part-B negative: stub processor header missing the `flight` ID
        stub = os.path.join(tmpdir, "CorvusInstrumentProcessor.h")
        stubdecl = ("#pragma once\n"
                    "class CorvusInstrumentProcessor : public juce::AudioProcessor"
                    " {\n"
                    "  static constexpr const char* kParamIds[] = {\n"
                    "    \"osc_wave\", \"attack\", \"decay\", \"sustain\",\n"
                    "    \"release\", \"fx_amount\", \"output\" };\n"
                    "};\n")
        with open(stub, "w", encoding="utf-8") as f:
            f.write(stubdecl)
        if run_header(stub, verbose=False) == 0:
            print("GATE_FAIL: stub processor header (missing the "
                  "'flight' param ID) was NOT rejected — checker too weak")
            return 1
        print("PASS instr(hdr): negative rejected -> stub header "
              "missing 'flight' fails")
    finally:
        shutil.rmtree(tmpdir, ignore_errors=True)

    print("OK instrument contract pinned (Plan Task-5 processor/state "
          "guarded before the processor header exists)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
