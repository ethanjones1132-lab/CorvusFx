#!/usr/bin/env python3
"""Pin the implemented deterministic shared-DSP fixture and its locked hash.

The instrument integration completed the original bootstrap plan. Follow its
heap-allocated effects and stereo EffectsFixture, preserving mutation probes
for finiteness, the five-effect roster, test identity, and fingerprint assertion.
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

    m = re.search(r"EffectsFixture\s+renderEffectsFixture\s*\(", code)
    res.append(("declares renderEffectsFixture() -> EffectsFixture",
                bool(m), "fixture function signature"))

    m = re.search(r"beginTest\s*\(\s*\"deterministic fixture remains finite\"\s*\)", code)
    res.append(("finiteness test block present", bool(m), "beginTest label"))

    m = re.search(r"beginTest\s*\(\s*\"fixture fingerprint\"\s*\)", code)
    res.append(("fingerprint test block present", bool(m), "beginTest label"))

    m = re.search(r"expect\s*\(\s*actual\s*==\s*expected\s*,", code)
    res.append(("fingerprint assert compares actual against expected",
                bool(m), "expectEquals call"))

    res.append(("fingerprint enforces exact repetition on every host",
                "actual == fingerprint(repeated)" in code, "deterministic repeat"))
    res.append(("locked raw hash is scoped to the measured toolchain",
                "#if JUCE_MAC && JUCE_ARM" in code and "__clang_major__ == 14" in code,
                "platform/compiler scope"))
    # per-sample isfinite inside runTest region
    run = code[code.find("void runTest"):]
    res.append(("runTest asserts std::isfinite per sample",
                "std::isfinite(sample)" in run, "isfinite loop"))

    m = re.search(r"expected\s*=\s*std::uint64_t\s*\{\s*0x[0-9a-fA-F]+ull\s*\}", code)
    res.append(("fingerprint compared against a locked constant (completed "
                "bootstrap)",
                bool(m), "expected constant"))

    # all five effects instantiated in the fixture body
    body = code[code.find("renderEffectsFixture"):]
    for eff in EFFECTS:
        res.append(("fixture instantiates " + eff,
                    re.search(r"std::make_unique<" + eff + r">\s*\(\s*\)", body) is not None,
                    "struct instantiation"))

    # chain order in source positions
    order_ok = True
    last = -1
    for eff in EFFECTS:
        pos = body.find("std::make_unique<" + eff + ">")
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
         lambda s: s.replace("std::isfinite(sample)",
                             "/* stripped */ true")),
        ("rename the test class",
         lambda s: s.replace("CorvusEffectsBaselineTest",
                             "RenamedTest")),
        ("remove the MasterOutputStage instantiation",
         lambda s: s.replace("std::make_unique<MasterOutputStage>()", "/* gone */ nullptr")),
        ("replace the expectedFingerprint compare with a constant true",
         lambda s: s.replace("expect(actual == expected,",
                             "expect(true,")),
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
          "fingerprint reference is scoped to the measured compiler/architecture)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
