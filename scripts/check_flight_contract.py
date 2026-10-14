#!/usr/bin/env python3
"""check_flight_contract.py — pin the vertical-slice Plan's Task-6
effects-chain / Flight doc contract BEFORE CorvusInstrumentProcessor.h
implements the FX routing.

SoT: docs/superpowers/plans/2026-08-08-corvus-instrument-vertical-slice.md
Task 6 ("Wire the full global Corvus effects chain and Flight control"):
  Consumes: shared ProfessionalDistortion, EnhancedChorus,
            EnhancedDelay, UpgradedReverb, MasterOutputStage
  Produces: InstrumentEffectsSettings
            CorvusInstrumentProcessor::settingsForFlight(float flight) const
  Produces: one global effects instance per module
  Step 3 requires: prepare one instance of every existing effect module,
            reuse the FX processor's safe parameter ranges and
            begin-block ordering, mix dry and processed output through a
            smoothed fx_amount control.
  Step 4 requires: map Flight monotonically across distortion amount,
            chorus depth/mix, delay mix/modulation, reverb
            size/mix/modulation, master width, and master drive; clamp
            every derived parameter before passing it to shared DSP;
            Flight does not alter oscillator pitch or amplitude in this
            slice.

Checks:
  A. The Task 6 block still declares the documented contract
     (read-only): the five consumed shared structs, the
     settingsForFlight signature, the one-global-instance rule, the
     smoothed fx_amount mix, the monotonic Flight mapping, the
     per-parameter clamp, and the pitch/amplitude exclusion sentence.
  B. Once source/DrippyFX/instrument/CorvusInstrumentProcessor.h
     exists, the header must declare settingsForFlight. SKIPPED while
     the file is absent — a printed SKIP line cites the rule
     (auto-activates when Task 5/6 land on Windows).
Negative probes (never on the real tree):
  N1. drop the clamp sentence from Task 6 Step 4 -> FAIL
  N2. drop the pitch/amplitude exclusion sentence -> FAIL
  N3. drop the five-struct Consumes line -> FAIL
  N4. stub processor header missing settingsForFlight -> FAIL
      (part B, exercised against a temp dir, not the real path)
Exit 0 only when the real Plan passes and every negative fires.
"""

import os
import re
import sys
import shutil
import tempfile

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
PLAN = os.path.join(ROOT, "docs", "superpowers", "plans",
                    "2026-08-08-corvus-instrument-vertical-slice.md")
HEADER = os.path.join(ROOT, "source", "DrippyFX", "instrument",
                      "CorvusInstrumentProcessor.h")

SHARED_STRUCTS = ["ProfessionalDistortion", "EnhancedChorus",
                  "EnhancedDelay", "UpgradedReverb", "MasterOutputStage"]


def strip_markers(text: str) -> str:
    """Neutralize markdown backticks so regexes match plain words."""
    return re.sub(r"`+", "", text)


def task6_block(plan_text: str) -> str:
    """Source region of Task 6 (its heading to the next ###/end)."""
    strip = strip_markers(plan_text)
    m = re.search(r"^###\s+Task 6:.*$", strip, re.M)
    if not m:
        return ""
    nxt = re.search(r"^###\s+Task \d+:.*$", strip[m.end():], re.M)
    end = m.end() + (nxt.start() if nxt else len(strip) - m.end())
    return strip[m.start():end]


def plan_checks(block: str):
    """Task-6 block checks. (label, ok, detail) tuples."""
    res = []
    res.append(("block is non-empty", bool(block.strip()),
                "Task 6 heading found"))
    for name in SHARED_STRUCTS:
        res.append(("consumed shared struct declared: " + name,
                    re.search(r"(?<![A-Za-z0-9_])" + re.escape(name) +
                              r"(?![A-Za-z0-9_])", block) is not None,
                    "consumed struct"))
    res.append(("five-struct Consumes line intact",
                re.search(r"Consumes:\s*shared\s*ProfessionalDistortion,\s*"
                          r"EnhancedChorus,\s*EnhancedDelay,\s*"
                          r"UpgradedReverb,\s*MasterOutputStage", block)
                is not None, "consumes line"))
    res.append(("settingsForFlight signature declared",
                re.search(r"InstrumentEffectsSettings\s+"
                          r"CorvusInstrumentProcessor::settingsForFlight"
                          r"\(\s*float\s+flight\s*\)\s*const", block)
                is not None, "flight mapping signature"))
    res.append(("one global effects instance per module required",
                re.search(r"one\s+global\s+effects\s+instance\s+per\s+"
                          r"module", block) is not None,
                "global-not-per-voice rule"))
    res.append(("prepare one instance of every existing effect module",
                re.search(r"Prepare\s+one\s+instance\s+of\s+every\s+"
                          r"existing\s+effect\s+module", block)
                is not None, "global chain prepare"))
    res.append(("FX processor safe ranges + begin-block ordering reused",
                re.search(r"Reuse\s+the\s+FX\s+processor's\s+safe\s+"
                          r"parameter\s+ranges\s+and\s+begin-block\s+"
                          r"ordering", block) is not None,
                "fx range reuse"))
    res.append(("smoothed fx_amount dry/wet mix required",
                re.search(r"through\s+a\s+smoothed\s+fx_amount\s+control",
                          block) is not None, "smoothed mix"))
    res.append(("monotonic Flight mapping across derived parameters",
                re.search(r"Map\s+Flight\s+monotonically\s+across\s+"
                          r"distortion\s+amount,\s*chorus\s+depth/mix,\s*"
                          r"delay\s+mix/modulation,\s*reverb\s+"
                          r"size/mix/modulation,\s*master\s+width,\s*and\s*"
                          r"master\s+drive", block) is not None,
                "monotonic flight"))
    res.append(("per-parameter clamp before shared DSP required",
                re.search(r"Clamp\s+every\s+derived\s+parameter\s+before\s+"
                          r"passing\s+it\s+to\s+shared\s+DSP", block)
                is not None, "clamp rule"))
    res.append(("Flight does not alter oscillator pitch or amplitude",
                re.search(r"Flight\s+does\s+not\s+alter\s+oscillator\s+"
                          r"pitch\s+or\s+amplitude\s+in\s+this\s+slice",
                          block) is not None, "pitch/amplitude exclusion"))
    return res


def header_checks(code: str):
    """Once the processor header exists, it must match the contract."""
    res = []
    res.append(("CorvusInstrumentProcessor present in header",
                re.search(r"CorvusInstrumentProcessor", code) is not None,
                "processor class"))
    res.append(("settingsForFlight declared in header",
                re.search(r"settingsForFlight", code) is not None,
                "flight mapping entry point"))
    return res


def run_plan(text: str, verbose=True):
    block = task6_block(text)
    ok = True
    for label, good, detail in plan_checks(block):
        if verbose:
            print(("PASS " if good else "FAIL ") +
                  "flight(plan): " + label + " (%s)" % detail)
        ok = ok and good
    return 0 if ok else 1


def run_header(path: str, verbose=True):
    with open(path, "r", encoding="utf-8", errors="replace") as f:
        code = f.read()
    ok = True
    for label, good, detail in header_checks(code):
        if verbose:
            print(("PASS " if good else "FAIL ") +
                  "flight(hdr): " + label + " (%s)" % detail)
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
        if run_header(HEADER) != 0:
            return 1
    else:
        print("SKIP flight(hdr): no %s yet — header checks not "
              "engaged (will auto-activate when Plan Tasks 5-6 are "
              "implemented on Windows)" % os.path.relpath(HEADER, ROOT))

    # Negative probes on temp copies (never the real tree)
    negs = [
        ("drop the clamp sentence from Task 6 Step 4",
         lambda s: s.replace("Clamp every derived parameter before "
                             "passing it to shared DSP. ",
                             "")),
        ("drop the pitch/amplitude exclusion sentence",
         lambda s: s.replace("Flight does not alter oscillator pitch "
                             "or amplitude in this slice.", "")),
        ("drop the five-struct Consumes line",
         lambda s: s.replace("Consumes: shared `ProfessionalDistortion`, "
                             "`EnhancedChorus`, `EnhancedDelay`, "
                             "`UpgradedReverb`, `MasterOutputStage`",
                             "Consumes: the shared effects modules")),
    ]
    tmpdir = tempfile.mkdtemp(prefix="check_flight_contract_")
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
            print("PASS flight(plan): negative rejected -> " + label)

        # Part-B negative: stub processor header missing settingsForFlight
        stub = os.path.join(tmpdir, "CorvusInstrumentProcessor.h")
        stubdecl = ("#pragma once\n"
                    "class CorvusInstrumentProcessor : public "
                    "juce::AudioProcessor {\n"
                    "  // effects chain wired elsewhere\n"
                    "};\n")
        with open(stub, "w", encoding="utf-8") as f:
            f.write(stubdecl)
        if run_header(stub, verbose=False) == 0:
            print("GATE_FAIL: stub processor header (missing the "
                  "settingsForFlight entry point) was NOT rejected — "
                  "checker too weak")
            return 1
        print("PASS flight(hdr): negative rejected -> stub header "
              "missing settingsForFlight fails")
    finally:
        shutil.rmtree(tmpdir, ignore_errors=True)

    print("OK flight contract pinned (Plan Task-6 effects-chain/Flight "
          "guarded before the instrument processor implements routing)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
