#!/usr/bin/env python3
"""Portable CV-086 regression for continuous, block-safe reverb pre-delay reads.

The checker pins the production read-head/slew code and runs its equivalent
against a deterministic signal. It covers block-boundary retargets and ring
wrap, demonstrates that the former integer-offset splice jumps, and accepts a
comment-only edit as a benign probe.
"""
import math
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SRC = ROOT / "source" / "DrippyFX" / "dsp" / "CorvusEffects.h"
RING = 9600


class Reject(Exception):
    pass


def strip_comments(src):
    src = re.sub(r"/\*.*?\*/", "", src, flags=re.S)
    return re.sub(r"//[^\n]*", "", src)


def body_for(code, signature):
    match = re.search(signature, code)
    if not match:
        raise Reject("production function not found: " + signature)
    opening = code.find("{", match.end() - 1)
    depth = 0
    for index in range(opening, len(code)):
        if code[index] == "{":
            depth += 1
        elif code[index] == "}":
            depth -= 1
            if depth == 0:
                return code[opening + 1:index]
    raise Reject("unbalanced production function")


def verify(source):
    code = strip_comments(source)
    start = re.search(r"\bstruct\s+UpgradedReverb\b[^;{]*\{", code)
    if not start:
        raise Reject("UpgradedReverb not found")
    depth = 0
    end = None
    for index in range(code.find("{", start.start()), len(code)):
        if code[index] == "{":
            depth += 1
        elif code[index] == "}":
            depth -= 1
            if depth == 0:
                end = index
                break
    if end is None:
        raise Reject("UpgradedReverb brace matching failed")
    reverb = code[start.start():end + 1]
    sample = body_for(
        reverb,
        r"void\s+processSample\s*\(\s*float\s+inL\s*,\s*float\s*inR\s*,")
    begin = body_for(
        reverb,
        r"void\s+beginBlock\s*\(\s*float\s+roomSize\s*,")
    if not re.search(r"static\s+constexpr\s+int\s+PREDELAY_MAX\s*=\s*9600\s*;",
                     reverb):
        raise Reject("pre-delay ring maximum changed")
    if not re.search(
            r"blockCoeffs\.preDelaySmp\s*=\s*juce::jlimit\s*\(\s*0\s*,\s*"
            r"PREDELAY_MAX\s*-\s*1\s*,\s*\(int\)\s*\(\s*preDelayMs\s*"
            r"\*\s*0\.001f\s*\*\s*sampleRate\s*\)\s*\)",
            begin):
        raise Reject("pre-delay target range or millisecond-to-sample mapping changed")
    if not re.search(r"float\s+currentPreDelaySmp", reverb):
        raise Reject("pre-delay read-head state is missing")
    required_sample = (
        r"currentPreDelaySmp\s*\+=",
        r"juce::jlimit\s*\(\s*-2\.0f\s*,\s*2\.0f\s*,\s*delayDelta\s*\)",
        r"float\s+pdRead\s*=\s*static_cast<float>\s*\(\s*preDelayPos\s*\)\s*-\s*currentPreDelaySmp",
        r"pdRead\s*<\s*0\.0f[\s\S]*?pdRead\s*\+=\s*static_cast<float>\s*\(\s*PREDELAY_MAX\s*\)",
        r"hermiteInterp\s*\(\s*preDelayBuf\[0\]\s*,\s*PREDELAY_MAX\s*,\s*pdRead\s*\)",
        r"hermiteInterp\s*\(\s*preDelayBuf\[1\]\s*,\s*PREDELAY_MAX\s*,\s*pdRead\s*\)",
    )
    for pattern in required_sample:
        if not re.search(pattern, sample):
            raise Reject("processSample missing continuous/wrapped read invariant: " + pattern)
    if re.search(r"\bint\s+pdRead\s*=\s*preDelayPos\s*-\s*pdSmp", sample):
        raise Reject("legacy integer-offset splice remains")
    if not re.search(r"currentPreDelaySmp\s*=\s*static_cast<float>\s*\(\s*blockCoeffs\.preDelaySmp\s*\)", begin):
        raise Reject("first pre-delay target is not initialized before rendering")
    if not re.search(r"preDelayInitialized", begin) or not re.search(
            r"preDelayInitialized\s*=\s*false", reverb):
        raise Reject("pre-delay read head initialization state is missing")


def hermite(buf, pos):
    index = math.floor(pos)
    frac = pos - index
    x_m1, x0, x1, x2 = (buf[(index + offset) % RING]
                        for offset in (-1, 0, 1, 2))
    c1 = 0.5 * (x1 - x_m1)
    c2 = x_m1 - 2.5 * x0 + 2.0 * x1 - 0.5 * x2
    c3 = 0.5 * (x2 - x_m1) + 1.5 * (x0 - x1)
    return ((c3 * frac + c2) * frac + c1) * frac + x0


def render(moving, start_pos):
    history = [0.0] * RING
    targets = (80, 176, 224, 112, 64)
    delay = float(targets[0])
    pos = start_pos
    output = []
    boundary_pairs = []
    for block_index, target in enumerate(targets):
        block_start = len(output)
        for _ in range(64):
            sample = math.sin((len(output) + 1) * 0.025) + 0.2 * math.sin(
                (len(output) + 1) * 0.071)
            history[pos] = sample
            if moving:
                delay += max(-2.0, min(2.0, target - delay))
            else:
                delay = float(target)
            read = (pos - delay) % RING
            output.append(hermite(history, read))
            pos = (pos + 1) % RING
        if block_index:
            boundary_pairs.append((block_start - 1, block_start))
    return output, boundary_pairs


def check_behavior():
    # Starting near the end forces wrapped reads throughout the retarget sweep.
    moved, boundaries = render(True, RING - 100)
    old, _ = render(False, RING - 100)
    for before, after in boundaries:
        assert abs(moved[after] - moved[before]) < 0.16, (
            "moving pre-delay jumped at block boundary (including ring wrap)")
    old_jump = max(abs(old[after] - old[before]) for before, after in boundaries)
    assert old_jump > 0.16, "negative probe did not expose old integer splice"

    # Also exercise an ordinary non-wrapping transition.
    ordinary, ordinary_boundaries = render(True, 200)
    for before, after in ordinary_boundaries:
        assert abs(ordinary[after] - ordinary[before]) < 0.16, (
            "ordinary moving pre-delay jumped at block boundary")


def main():
    source = SRC.read_text(encoding="utf-8")
    verify(source)
    check_behavior()
    # A comment-only change must not trip the source invariants.
    verify(source + "\n// benign CV-086 checker probe\n")
    print("cv086-reverb-predelay: continuous block retargets and ring wrap pass; "
          "old integer splice rejected; benign comment accepted")


if __name__ == "__main__":
    try:
        main()
    except (AssertionError, Reject, OSError) as error:
        print("cv086-reverb-predelay: FAIL: %s" % error)
        raise SystemExit(1)
