#!/usr/bin/env python3
"""check_console_target_contract.py — pin the vertical-slice Plan's
Task-1 Step-2 CorvusDSPTests console-target CMake contract BEFORE the
target exists in source/DrippyFX/CMakeLists.txt.

SoT: docs/superpowers/plans/2026-08-08-corvus-instrument-vertical-slice.md
Task 1, Step 2 ("Add the console test target"):
  Add juce_add_console_app(CorvusDSPTests PRODUCT_NAME "Corvus DSP
  Tests"), juce_generate_juce_header(CorvusDSPTests), the test source,
  include directories, and links to juce::juce_audio_utils,
  juce::juce_dsp, and recommended config flags. The test main() runs
  all registered tests and returns nonzero when any result fails.

Checks:
  A. The Task-1 Step-2 block still declares the documented contract
     (read-only): the juce_add_console_app target line, the
     juce_generate_juce_header call, the test source + include
     directories, both links (juce_audio_utils AND juce_dsp), and the
     main() runs-all-registered-tests / nonzero-on-failure rule.
  B. Once source/DrippyFX/CMakeLists.txt contains
     `juce_add_console_app(CorvusDSPTests`, it must also contain the
     juce_generate_juce_header(CorvusDSPTests) call, links to
     juce::juce_audio_utils and juce::juce_dsp, and include
     directories on that target. SKIPPED while the target is absent —
     a printed SKIP line cites the rule (auto-activates when Task 1
     Step 2 lands on Windows).
Negative probes (never on the real tree):
  N1. drop the juce_generate_juce_header sentence from Step 2 -> FAIL
  N2. drop the juce_dsp link sentence from Step 2 -> FAIL
  N3. stub CMakeLists with the console app but no juce_dsp link -> FAIL
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
CMAKELISTS = os.path.join(ROOT, "source", "DrippyFX", "CMakeLists.txt")

CONSOLE_APP = "juce_add_console_app(CorvusDSPTests"
GENERATE_HDR = "juce_generate_juce_header(CorvusDSPTests)"
LINK_UTILS = "juce::juce_audio_utils"
LINK_DSP = "juce::juce_dsp"


def strip_markers(text: str) -> str:
    """Neutralize markdown backticks so regexes match plain words."""
    return re.sub(r"`+", "", text)


def step2_block(plan_text: str) -> str:
    """Source region of Task 1 Step 2 (its heading to the next Step)."""
    strip = strip_markers(plan_text)
    m = re.search(r"^\s*[-\*\s\[\]x]*\*\*Step 2: Add the console test"
                  r" target\*\*\s*$", strip, re.M)
    if not m:
        return ""
    nxt = re.search(r"^\s*[-\*\s\[\]x]*\*\*Step \d+:.*\*\*\s*$",
                    strip[m.end():], re.M)
    end = m.end() + (nxt.start() if nxt else len(strip) - m.end())
    return strip[m.start():end]


def plan_checks(block: str):
    """Comment-stripped Step-2 block checks. (label, ok, detail) tuples."""
    res = []
    res.append(("block is non-empty", bool(block.strip()),
                "Step 2 heading found"))
    res.append(("console target name declared",
                re.search(r"juce_add_console_app\(CorvusDSPTests\s*"
                          r"PRODUCT_NAME\s*\"Corvus DSP Tests\"\)",
                          block) is not None,
                "target line"))
    res.append(("juce header generation declared",
                re.search(r"juce_generate_juce_header\(CorvusDSPTests\)",
                          block) is not None,
                "generate header"))
    res.append(("test source declared",
                re.search(r"\bthe\s+test\s+source\b", block) is not None,
                "test source"))
    res.append(("include directories declared",
                re.search(r"\binclude\s+directories\b", block) is not None,
                "include directories"))
    res.append(("link to juce_audio_utils declared",
                re.search(r"juce_audio_utils", block) is not None,
                LINK_UTILS))
    res.append(("link to juce_dsp declared",
                re.search(r"juce_dsp\b(?!_)", block) is not None,
                LINK_DSP))
    res.append(("main() runs all registered tests",
                re.search(r"main\(\)\s+runs\s+all\s+registered\s+tests",
                          block) is not None,
                "run all tests"))
    res.append(("main() returns nonzero on failure",
                re.search(r"returns\s+nonzero\s+when\s+any\s+result\s+fails",
                          block) is not None,
                "nonzero semantics"))
    return res


def cmake_checks(code: str):
    """Once the console target exists in CMakeLists, it must match."""
    res = []
    res.append(("console target present in CMakeLists",
                re.search(r"juce_add_console_app\(CorvusDSPTests",
                          code) is not None,
                "target line"))
    res.append(("juce_generate_juce_header(CorvusDSPTests) present",
                re.search(re.escape(GENERATE_HDR), code) is not None,
                "generate header"))
    res.append(("links juce::juce_audio_utils",
                re.search(re.escape(LINK_UTILS), code) is not None,
                "audio utils link"))
    res.append(("links juce::juce_dsp",
                re.search(re.escape(LINK_DSP), code) is not None,
                "dsp link"))
    res.append(("declares include directories",
                re.search(r"target_include_directories", code) is not None,
                "include directories"))
    res.append(("references the test source",
                re.search(r"CorvusDspTests\.cpp|tests/CorvusDspTests\.cpp",
                          code) is not None,
                "test source"))
    return res


def run_plan(text: str, verbose=True):
    block = step2_block(text)
    ok = True
    for label, good, detail in plan_checks(block):
        if verbose:
            print(("PASS " if good else "FAIL ") +
                  "console-target(plan): " + label + " (%s)" % detail)
        ok = ok and good
    return 0 if ok else 1


def run_cmake(path: str, verbose=True):
    with open(path, "r", encoding="utf-8", errors="replace") as f:
        code = f.read()
    ok = True
    for label, good, detail in cmake_checks(code):
        if verbose:
            print(("PASS " if good else "FAIL ") +
                  "console-target(cmake): " + label + " (%s)" % detail)
        ok = ok and good
    if verbose and ok:
        print("PASS console-target(hdr): console app present in "
              "CMakeLists.txt (%s)" % CONSOLE_APP)
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

    # Part B: only while the CMakeLists declares the console target
    cmake_text = ""
    if os.path.isfile(CMAKELISTS):
        with open(CMAKELISTS, "r", encoding="utf-8", errors="replace") as f:
            cmake_text = f.read()
    if CONSOLE_APP in cmake_text:
        if run_cmake(CMAKELISTS) != 0:
            return 1
    else:
        print("SKIP console-target(cmake): no %s in CMakeLists.txt yet —"
              " CMake checks not engaged (will auto-activate when Plan"
              " Task 1 Step 2 is implemented on Windows)" % CONSOLE_APP)

    # Negative probes on temp copies (never the real tree)
    negs = [
        ("drop the juce_generate_juce_header sentence",
         lambda s: strip_markers(s).replace(
             "juce_generate_juce_header(CorvusDSPTests),", "")),
        ("drop the juce_dsp link sentence",
         lambda s: strip_markers(s).replace(
             "juce::juce_dsp", "juce::juce_dsp_removed")),
        ("drop the nonzero-on-failure semantics",
         lambda s: strip_markers(s).replace(
             "returns nonzero when any result fails",
             "returns whatever the mood says")),
    ]
    tmpdir = tempfile.mkdtemp(prefix="check_console_target_contract_")
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
            print("PASS console-target(plan): negative rejected -> "
                  + label)

        # Part-B negative: stub CMakeLists with the console app but
        # no juce_dsp link
        stub = os.path.join(tmpdir, "CMakeLists.txt")
        stubdecl = (
            "cmake_minimum_required(VERSION 3.22)\n"
            "juce_add_console_app(CorvusDSPTests PRODUCT_NAME"
            " \"Corvus DSP Tests\")\n"
            "juce_generate_juce_header(CorvusDSPTests)\n"
            "target_sources(CorvusDSPTests PRIVATE"
            " tests/CorvusDspTests.cpp)\n"
            "target_include_directories(CorvusDSPTests PRIVATE .)\n"
            "target_link_libraries(CorvusDSPTests PRIVATE"
            " juce::juce_audio_utils)\n"
        )
        with open(stub, "w", encoding="utf-8") as f:
            f.write(stubdecl)
        if run_cmake(stub, verbose=False) == 0:
            print("GATE_FAIL: stub CMakeLists (console app but no "
                  "juce_dsp link) was NOT rejected — checker too weak")
            return 1
        print("PASS console-target(cmake): negative rejected -> stub "
              "CMakeLists missing the juce_dsp link fails")
    finally:
        shutil.rmtree(tmpdir, ignore_errors=True)

    print("OK console-target contract pinned (Plan Task-1 Step-2 "
          "CorvusDSPTests CMake contract guarded before the target "
          "exists)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
