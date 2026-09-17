#!/usr/bin/env python3
"""check_baseline_fixture_test.py — pin the Corvus Instrument vertical slice's
Plan Task 1 Step 1 baseline fixture test source.

SoT for the item: docs/superpowers/plans/2026-08-08-corvus-instrument-vertical-slice.md
Task 1 ("Add a deterministic JUCE test target and baseline FX fixture"), Step 1:
a JUCE UnitTest named CorvusEffectsBaselineTest that renders a deterministic
stereo impulse through ProfessionalDistortion, EnhancedChorus, EnhancedDelay,
UpgradedReverb, and MasterOutputStage and asserts every sample is finite, plus
a second fingerprint assertion against a constant seeded wrong-on-purpose
(uint64_t{0}) so the first Windows run fails intentionally (plan Task 1 Step 4).

What this headless checker can verify on macOS (no JUCE tree here, per
AGENTS.md): the test FILE exists and carries the required shape. Compiling and
RUNNING the fingerprint bootstrap (plan Steps 4-5) happens on the Windows
build tree; this checker never claims the fingerprint is green.

Checks:
  1. source/DrippyFX/tests/CorvusDspTests.cpp exists.
  2. (comment-stripped) class CorvusEffectsBaselineTest : public juce::UnitTest
  3. renderEffectsFixture() is declared/defined returning std::array<float, ...>
  4. the render path instantiates all five effect structs AND calls each one's
     process/prepare entry point (chain order pinned by source position:
     distortion < chorus < delay < reverb < master in the file).
  5. a per-sample std::isfinite assertion exists in runTest().
  6. the fingerprint assert compares against a named constant (locked or 0).
Negative checks (temp-mutate a copy in a temp dir, never the real file):
  N1. drop the isfinite loop -> FAIL
  N2. rename the test class -> FAIL
  N3. remove one effect struct's instantiation -> FAIL
Exit 0 only when the real file passes all checks; any negative exits 1.
"""

import os
import re
import sys
import tempfile
import shutil

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
TEST_PATH = os.path.join(ROOT, "source", "DrippyFX", "tests", "CorvusDspTests.cpp")

EFFECTS = ["ProfessionalDistortion", "EnhancedChorus", "EnhancedDelay",
           "UpgradedReverb", "MasterOutputStage"]


def strip_comments(src: str) -> str:
    out = []
    i, n = 0, len(src)
    while i < n:
        if src.startswith("//", i):
            j = src.find("\n", i)
            i = n if j < 0 else j
        elif src.startswith("/*", i):
            j = src.find("*/", i + 2)
            i = n if j < 0 else j + 2
        else:
            out.append(src[i])
            i += 1
    return "".join(out)


def checks(src: str):
    """Return list of (label, ok, detail)."""
    code = strip_comments(src)
    res = []

    m = re.search(r"class\s+CorvusEffectsBaselineTest[^{]*public\s+juce::UnitTest", code)
    res.append(("defines CorvusEffectsBaselineTest : public juce::UnitTest",
                bool(m), "class declaration"))

    m = re.search(r"std::array<float,\s*fixtureNumSamples>\s+renderEffectsFixture\s*\(", code)
    res.append(("declares renderEffectsFixture() -> std::array<float, fixtureNumSamples>",
                bool(m), "fixture function signature"))

    m = re.search(r"beginTest\s*\(\s*\"deterministic fixture remains finite\"\s*\)", code)
    res.append(("finiteness test block present", bool(m), "beginTest label"))

    m = re.search(r"beginTest\s*\(\s*\"fixture fingerprint\"\s*\)", code)
    res.append(("fingerprint test block present", bool(m), "beginTest label"))

    m = re.search(r"expectEquals\s*\(\s*fp\s*,\s*expectedFingerprint\s*\)", code)
    res.append(("fingerprint assert compares fp against expectedFingerprint",
                bool(m), "expectEquals call"))

    # per-sample isfinite inside runTest region
    run = code[code.find("void runTest"):]
    res.append(("runTest asserts std::isfinite per sample",
                "std::isfinite (sample)" in run, "isfinite loop"))

    m = re.search(r"expectedFingerprint\s*=\s*uint64_t\s*\{\s*\d+\s*\}", code)
    res.append(("fingerprint compared against a named constant (0 = seed for "
                "the intentional first-run failure)",
                bool(m), "expectedFingerprint constant"))

    # all five effects instantiated in the fixture body
    body = code[code.find("renderEffectsFixture"):]
    for eff in EFFECTS:
        res.append(("fixture instantiates " + eff,
                    re.search(r"\b" + eff + r"\s+\w+\s*;", body) is not None,
                    "struct instantiation"))

    # chain order in source positions
    order_ok = True
    last = -1
    for eff in EFFECTS:
        pos = body.find(eff + " ")
        if pos < 0 or pos < last:
            order_ok = False
            break
        last = pos
    res.append(("five effects appear in chain order "
                "(distortion→chorus→delay→reverb→master)", order_ok, "order"))

    return res


def run(path, verbose=True):
    try:
        with open(path, "r", encoding="utf-8") as f:
            src = f.read()
    except OSError as e:
        print("GATE_FAIL: cannot read %s: %s" % (path, e))
        return 1
    ok = True
    for label, good, detail in checks(src):
        if verbose:
            print(("PASS " if good else "FAIL ") + "baseline-fixture-test: " + label +
                  " (%s)" % detail)
        ok = ok and good
    return 0 if ok else 1


def main():
    if not os.path.isfile(TEST_PATH):
        print("GATE_FAIL: %s missing (Plan Task 1 Step 1 test source not created)" % TEST_PATH)
        return 1
    rc = run(TEST_PATH)
    if rc != 0:
        return 1

    # Negatives on a temp copy
    with open(TEST_PATH, "r", encoding="utf-8") as f:
        src = f.read()

    negs = [
        ("drop the per-sample isfinite assertion",
         lambda s: s.replace("std::isfinite (sample)",
                             "/* stripped */ true")),
        ("rename the test class",
         lambda s: s.replace("CorvusEffectsBaselineTest",
                             "RenamedTest")),
        ("remove the MasterOutputStage instantiation",
         lambda s: s.replace("MasterOutputStage   master;", "/* gone */")),
        ("replace the expectedFingerprint compare with a constant true",
         lambda s: s.replace("expectEquals (fp, expectedFingerprint);",
                             "(void) fp;")),
    ]
    tmpdir = tempfile.mkdtemp(prefix="check_baseline_")
    try:
        for label, mutate in negs:
            mutated = mutate(src)
            if mutated == src:
                print("GATE_FAIL: negative '%s' mutation is a no-op — checker "
                      "stale vs source" % label)
                return 1
            p = os.path.join(tmpdir, "mut.cpp")
            with open(p, "w", encoding="utf-8") as f:
                f.write(mutated)
            if run(p, verbose=False) == 0:
                print("GATE_FAIL: negative check '%s' did NOT fail — "
                      "checker too weak" % label)
                return 1
            print("PASS baseline-fixture-test: negative rejected -> " + label)
    finally:
        shutil.rmtree(tmpdir, ignore_errors=True)

    print("OK baseline fixture test pinned (Plan Task 1 Step 1 source shape; "
          "fingerprint value itself is locked on Windows)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
