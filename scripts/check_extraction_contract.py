#!/usr/bin/env python3
"""check_extraction_contract.py — pin the Corvus Instrument vertical slice
Plan's Task-2 mechanical-move extraction contract BEFORE
source/DrippyFX/dsp/CorvusEffects.h exists.

SoT: docs/superpowers/plans/2026-08-08-corvus-instrument-vertical-slice.md
Task 2 ("Extract the shared Corvus effects header without behavior changes"):
  - Produces unchanged global types: DCBlocker, OnePole, Oversampling2x,
    ProfessionalDistortion, EnhancedChorus, EnhancedDelay, UpgradedReverb,
    MasterOutputStage
  - Preserves: hermiteInterp, padeTanh, and padeSoftClip
  - Step 2: mechanically move the utility functions and structs currently
    occupying PluginProcessor.h lines 11-1522 into dsp/CorvusEffects.h;
    leave only processor-specific includes and CorvusFXAudioProcessor in
    PluginProcessor.h
  - Step 4 required results: baseline fingerprint unchanged, all samples
    finite.

Nothing until now pins the Task-2 doc text itself and nothing verifies after
the move that all eight type names live in dsp/CorvusEffects.h and that
PluginProcessor.h includes it — a duplicated-include drift compiles on
Windows but violates the "unchanged global types" contract.

Checks:
  A. The Task 2 block still declares the documented contract (read-only,
     backtick-stripped): the unchanged-global-types list, the utils-preserve
     line, the lines-11-1522 + leave-only-processor sentences, and the
     Step-4 fingerprint-unchanged/finite required results.
  B. Once source/DrippyFX/dsp/CorvusEffects.h exists, all eight type names
     and the three utility names appear in it AND PluginProcessor.h includes
     dsp/CorvusEffects.h. SKIPPED while the file is absent — a printed SKIP
     line cites the rule (no silent no-op pass).
Negative probes (never on the real tree):
  N1. drop the unchanged-global-types list from Task 2 -> FAIL
  N2. drop the leave-only-processor sentence from Step 2 -> FAIL
  N3. stub dsp/CorvusEffects.h missing EnhancedChorus -> FAIL
      (exercised on a temp copy, not the real header path)
  N4. drift the lines-11-1522 range in Step 2 -> FAIL
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
DSP_HDR = os.path.join(ROOT, "source", "DrippyFX", "dsp", "CorvusEffects.h")
PP_HDR = os.path.join(ROOT, "source", "DrippyFX", "PluginProcessor.h")

EIGHT_TYPES = ["DCBlocker", "OnePole", "Oversampling2x",
               "ProfessionalDistortion", "EnhancedChorus", "EnhancedDelay",
               "UpgradedReverb", "MasterOutputStage"]
THREE_UTILS = ["hermiteInterp", "padeTanh", "padeSoftClip"]
STUB_HDR_NAME = "CorvusEffects.h"


def strip_markers(text: str) -> str:
    """Neutralize markdown emphasis/backticks so regexes match plain words."""
    return re.sub(r"`+", "", text)


def task2_block(plan_text: str) -> str:
    """Source region of the Task 2 section (heading to the next task)."""
    m = re.search(r"^#{2,4}\s*Task 2:.*$", plan_text, re.M)
    if not m:
        return ""
    nxt = re.search(r"^#{2,4}\s*Task \d+:.*$", plan_text[m.end():], re.M)
    end = m.end() + (nxt.start() if nxt else len(plan_text) - m.end())
    return plan_text[m.start():end]


def plan_checks(code: str):
    """Backtick-stripped Task-2 block checks. Return list of (label, ok, detail)."""
    res = []
    res.append(("block is non-empty", bool(code.strip()),
                "Task 2 heading found"))
    res.append(("shared header dsp/CorvusEffects.h declared (Create line)",
                "dsp/CorvusEffects.h" in code, "source/DrippyFX/dsp/CorvusEffects.h"))
    res.append(("all eight unchanged-global-type names declared together",
                all(t in code for t in EIGHT_TYPES),
                "DCBlocker OnePole Oversampling2x ProfessionalDistortion "
                "EnhancedChorus EnhancedDelay UpgradedReverb MasterOutputStage"))
    res.append(("unchanged-global-types Produces line text intact",
                re.search(r"Produces\s+unchanged\s+global\s+types", code)
                is not None, ":123"))
    res.append(("utils-preserve line (hermiteInterp/padeTanh/padeSoftClip)",
                re.search(r"Preserves\s*:\s*hermiteInterp\s*,\s*padeTanh\s*,\s*"
                          r"and\s+padeSoftClip", code) is not None, ":124"))
    res.append(("Step 2 declares the lines-11-1522 mechanical move",
                re.search(r"Move the utility functions and structs currently\s*"
                          r"occupying Plugins?Processor\.h lines 11-1522 into\s*"
                          r"dsp/CorvusEffects\.h", code) is not None, ":134"))
    res.append(("Step 2 leave-only-processor sentence intact",
                re.search(r"leave only processor-specific includes and\s*"
                          r"CorvusFXAudioProcessor in that file", code)
                is not None, ":134"))
    res.append(("PluginProcessor.h include-shape sentence intact",
                re.search(r"Add\s+#include\s+\"dsp/CorvusEffects\.h\"\s+to\s+"
                          r"PluginProcessor\.h", code) is not None, ":134"))
    res.append(("Step 4 required result: baseline fingerprint unchanged",
                re.search(r"Required results:\s*baseline fingerprint unchanged",
                          code) is not None, ":142"))
    res.append(("Step 4 required result: all samples finite",
                re.search(r"all samples finite", code) is not None, ":142"))
    return res


def header_checks(hdr_code: str, pp_code: str):
    """Once dsp/CorvusEffects.h exists, the moved names must live there and
    PluginProcessor.h must include it."""
    res = []
    for t in EIGHT_TYPES:
        res.append(("CorvusEffects.h declares/preserves " + t,
                    re.search(r"\b%s\b" % re.escape(t), hdr_code) is not None,
                    "type name"))
    for u in THREE_UTILS:
        res.append(("CorvusEffects.h preserves " + u,
                    re.search(r"\b%s\b" % re.escape(u), hdr_code) is not None,
                    "utility name"))
    res.append(("PluginProcessor.h includes dsp/CorvusEffects.h",
                re.search(r"#\s*include\s+\"dsp/CorvusEffects\.h\"", pp_code)
                is not None, "include line"))
    return res


def run_plan(text: str, verbose=True):
    code = strip_markers(text)
    block = task2_block(code)
    ok = True
    for label, good, detail in plan_checks(block):
        if verbose:
            print(("PASS " if good else "FAIL ") + "extraction-contract(plan): "
                  + label + " (%s)" % detail)
        ok = ok and good
    return 0 if ok else 1


def run_header_pair(hdr_path: str, verbose=True):
    with open(hdr_path, "r", encoding="utf-8") as f:
        hdr_code = strip_markers(f.read())
    with open(PP_HDR, "r", encoding="utf-8") as f:
        pp_code = strip_markers(f.read())
    ok = True
    for label, good, detail in header_checks(hdr_code, pp_code):
        if verbose:
            print(("PASS " if good else "FAIL ") + "extraction-contract(hdr): "
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

    # Part B: only while the extracted header exists
    if os.path.isfile(DSP_HDR) and os.path.isfile(PP_HDR):
        if run_header_pair(DSP_HDR) != 0:
            return 1
    else:
        print("SKIP extraction-contract(hdr): no %s yet — header checks not "
              "engaged (will auto-activate when Task 2 is implemented)"
              % os.path.relpath(DSP_HDR, ROOT))

    # Negative probes on temp copies of the PLAN (never the real tree)
    negs = [
        ("drop the unchanged-global-types list from Task 2",
         lambda s: s.replace("Produces unchanged global types: "
                             "`DCBlocker`, `OnePole`, `Oversampling2x`, "
                             "`ProfessionalDistortion`, `EnhancedChorus`, "
                             "`EnhancedDelay`, `UpgradedReverb`, "
                             "`MasterOutputStage`", "")),
        ("drop the leave-only-processor sentence from Step 2",
         lambda s: s.replace("leave only processor-specific includes and "
                             "`CorvusFXAudioProcessor` in that file.", "")),
        ("drift the lines-11-1522 mechanical-move range in Step 2",
         lambda s: s.replace("occupying `PluginProcessor.h` lines 11-1522",
                             "occupying `PluginProcessor.h` lines 11-999")),
    ]
    tmpdir = tempfile.mkdtemp(prefix="check_extraction_contract_")
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
            print("PASS extraction-contract(plan): negative rejected -> "
                  + label)

        # Part-B negative: stub extraction header missing EnhancedChorus
        # (temp file, run against the real PluginProcessor.h text so the
        # include-line check still has real input)
        stub = os.path.join(tmpdir, STUB_HDR_NAME)
        with open(stub, "w", encoding="utf-8") as f:
            f.write("struct DCBlocker;\n"
                    "struct OnePole;\n"
                    "struct Oversampling2x;\n"
                    "struct ProfessionalDistortion;\n"
                    "struct EnhancedDelay;\n"
                    "struct UpgradedReverb;\n"
                    "struct MasterOutputStage;\n"
                    "inline float hermiteInterp(float frac, float x0, "
                    "float x1, float x2, float x3);\n"
                    "inline float padeTanh(float z);\n"
                    "inline float padeSoftClip(float x, float threshold "
                    "= 1.0f, float scale = 0.2f);\n")
        with open(PP_HDR, "r", encoding="utf-8") as f:
            pp_txt = strip_markers(f.read())
        with open(stub, "r", encoding="utf-8") as f:
            stub_txt = strip_markers(f.read())
        # The include line CAN'T pass for a temp stub (real PP_HDR doesn't
        # include the header yet), so for the negative probe evaluate only
        # the stub-side checks (types + utils), holding the pp text fixed.
        ok = True
        for label, good, _detail in header_checks(stub_txt, pp_txt):
            if label.startswith("PluginProcessor.h includes"):
                continue  # real PP_HDR has no include yet by design
            ok = ok and good
        if ok:
            print("GATE_FAIL: stub CorvusEffects.h missing EnhancedChorus "
                  "was NOT rejected — checker too weak")
            return 1
        print("PASS extraction-contract(hdr): negative rejected -> stub "
              "header missing EnhancedChorus fails")
    finally:
        shutil.rmtree(tmpdir, ignore_errors=True)

    print("OK extraction contract pinned (Plan Task-2 mechanical-move "
          "doc contract guarded before dsp/CorvusEffects.h exists)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
