#!/usr/bin/env python3
"""check_patch_bank_contract.py — pin the vertical-slice Plan's Task-7
signature-preset-bank contract BEFORE CorvusInstrumentPresets.h exists.

SoT: docs/superpowers/plans/2026-08-08-corvus-instrument-vertical-slice.md
Task 7 ("Add five signature patches and host program behavior"):
  Produces: InstrumentPreset { name, wave, attack, decay, sustain,
  release, fxAmount, flight, output }
  Produces programs: Dawn Choir, Raven Glass, Ashen Sky, Northern Signal,
  Cathedral Drift
  Steps require: exactly five programs, stable names and indices,
  deterministic recall, state round trip after recall, non-silent A3
  chord output, finite samples, peak output at or below the safety
  target, and "Normalize perceived level by measured peak and RMS
  rather than by arbitrary gain copying."

Checks:
  A. The Task 7 block still declares the documented contract
     (read-only): preset struct fields, the five program names
     verbatim, exact-five cardinality + recall/round-trip sentences,
     A3/finite/peak/at-safety-target lines, measured-peak/RMS rule.
  B. Once source/DrippyFX/instrument/CorvusInstrumentPresets.h exists,
     the header must declare InstrumentPreset and all five program
     names. SKIPPED while the file is absent — a printed SKIP line
     cites the rule (auto-activates when Task 7 lands on Windows).
Negative probes (never on the real tree):
  N1. rename one program name in the Task-7 block -> FAIL
  N2. drop the measured peak/RMS normalization sentence -> FAIL
  N3. drop the InstrumentPreset struct line -> FAIL
  N4. stub presets header missing a program name -> FAIL
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
                      "CorvusInstrumentPresets.h")

NAMES = ["Dawn Choir", "Raven Glass", "Ashen Sky", "Northern Signal",
         "Cathedral Drift"]


def strip_markers(text: str) -> str:
    """Neutralize markdown backticks so regexes match plain words."""
    return re.sub(r"`+", "", text)


def task7_block(plan_text: str) -> str:
    """Source region of Task 7 (its heading to the next ###/end)."""
    strip = strip_markers(plan_text)
    m = re.search(r"^###\s+Task 7:.*$", strip, re.M)
    if not m:
        return ""
    nxt = re.search(r"^###\s+Task \d+:.*$", strip[m.end():], re.M)
    end = m.end() + (nxt.start() if nxt else len(strip) - m.end())
    return strip[m.start():end]


def plan_checks(block: str):
    """Comment-stripped Task-7 block checks. (label, ok, detail) tuples."""
    res = []
    res.append(("block is non-empty", bool(block.strip()),
                "Task 7 heading found"))
    res.append(("InstrumentPreset struct declared with fields",
                re.search(r"InstrumentPreset\s*\{\s*name,\s*wave,\s*attack,"
                          r"\s*decay,\s*sustain,\s*release,\s*fxAmount,\s*"
                          r"flight,\s*output\s*\}", block) is not None,
                "preset struct"))
    for nm in NAMES:
        res.append(("program name declared: " + nm,
                    re.search(re.escape(nm), block) is not None,
                    "signature program"))
    res.append(("exactly five programs required",
                re.search(r"exactly\s+five\s+programs", block) is not None,
                "cardinality"))
    res.append(("deterministic recall required",
                re.search(r"deterministic\s+recall", block) is not None,
                "recall"))
    res.append(("state round trip after recall required",
                re.search(r"state\s+round\s+trip", block) is not None,
                "round trip"))
    res.append(("non-silent A3 chord output required",
                re.search(r"non-silent\s+A3\s+chord\s+output", block)
                is not None, "a3 chord"))
    res.append(("finite samples required",
                re.search(r"finite\s+samples", block) is not None,
                "finite"))
    res.append(("peak at or below the safety target required",
                re.search(r"peak\s+output\s+at\s+or\s+below\s+the\s+safety",
                          block) is not None, "safety target"))
    res.append(("normalize by measured peak and RMS (no gain copying)",
                re.search(r"Normalize\s+perceived\s+level\s+by\s+measured\s+"
                          r"peak\s+and\s+RMS\s+rather\s+than\s+by\s+arbitrary"
                          r"\s+gain\s+copying", block) is not None,
                "level normalization"))
    return res


def header_checks(code: str):
    """Once the presets header exists, it must match the contract."""
    res = []
    res.append(("InstrumentPreset present in header",
                re.search(r"InstrumentPreset", code) is not None,
                "preset struct"))
    for nm in NAMES:
        res.append(("program name present in header: " + nm,
                    re.search(re.escape(nm), code) is not None,
                    "signature program"))
    return res


def run_plan(text: str, verbose=True):
    block = task7_block(text)
    ok = True
    for label, good, detail in plan_checks(block):
        if verbose:
            print(("PASS " if good else "FAIL ") +
                  "patch-bank(plan): " + label + " (%s)" % detail)
        ok = ok and good
    return 0 if ok else 1


def run_header(path: str, verbose=True):
    with open(path, "r", encoding="utf-8", errors="replace") as f:
        code = f.read()
    ok = True
    for label, good, detail in header_checks(code):
        if verbose:
            print(("PASS " if good else "FAIL ") +
                  "patch-bank(hdr): " + label + " (%s)" % detail)
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

    # Part B: only while the presets header exists
    if os.path.isfile(HEADER):
        if run_header(HEADER) != 0:
            return 1
    else:
        print("SKIP patch-bank(hdr): no %s yet — header checks not "
              "engaged (will auto-activate when Plan Task 7 is "
              "implemented on Windows)" % os.path.relpath(HEADER, ROOT))

    # Negative probes on temp copies (never the real tree)
    negs = [
        ("rename a program name in Task 7",
         lambda s: strip_markers(s).replace("Northern Signal", "South Ink")),
        ("drop the measured peak/RMS normalization rule",
         lambda s: s.replace("Normalize perceived level by measured peak "
                             "and RMS rather than by arbitrary gain "
                             "copying.", "Level match by waiting.")),
        ("drop the InstrumentPreset struct declaration",
         lambda s: s.replace("InstrumentPreset { name, wave, attack, "
                             "decay, sustain, release, fxAmount, flight, "
                             "output }", "vector of anonymous dicts")),
    ]
    tmpdir = tempfile.mkdtemp(prefix="check_patch_bank_contract_")
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
            print("PASS patch-bank(plan): negative rejected -> " + label)

        # Part-B negative: stub presets header missing a program name
        stub = os.path.join(tmpdir, "CorvusInstrumentPresets.h")
        stubdecl = ("#pragma once\n"
                    "struct InstrumentPreset { const char* name; int wave;"
                    " float attack, decay, sustain, release, fxAmount,"
                    " flight, output; };\n"
                    "static const InstrumentPreset kPresets[] = {\n" +
                    "".join('  {"%s", 0, 1.f,1.f,1.f,1.f,1.f,1.f,1.f},\n'
                            % nm for nm in NAMES if nm != "Ashen Sky") +
                    "};\n")
        with open(stub, "w", encoding="utf-8") as f:
            f.write(stubdecl)
        if run_header(stub, verbose=False) == 0:
            print("GATE_FAIL: stub presets header (only four of five "
                  "program names) was NOT rejected — checker too weak")
            return 1
        print("PASS patch-bank(hdr): negative rejected -> stub header "
              "missing 'Ashen Sky' fails")
    finally:
        shutil.rmtree(tmpdir, ignore_errors=True)

    print("OK patch-bank contract pinned (Plan Task-7 signature-preset "
          "bank guarded before the presets header exists)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
