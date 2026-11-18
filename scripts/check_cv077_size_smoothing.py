#!/usr/bin/env python3
"""Headless source checker for smooth early-reflection Size changes (CV-077).

EarlyReflections::setRoomSize() may run at every block boundary, including
while the reverb is silent. It must retarget the tap parameters without
immediately replacing the parameters used by process(), and process() must
move the active taps toward those targets over a bounded transition. The first
setRoomSize() after prepare() instead seeds active and target values together:
there is no prior rendered field to transition from.

Negative probes mutate in-memory source copies and first prove each mutation
applied. The live source is never modified.
"""
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SRC = ROOT / "source" / "DrippyFX" / "dsp" / "CorvusEffects.h"
PROC = ROOT / "source" / "DrippyFX" / "PluginProcessor.cpp"


class Reject(Exception):
    pass


def strip_comments(src):
    src = re.sub(r"/\*.*?\*/", "", src, flags=re.S)
    return re.sub(r"//[^\n]*", "", src)


def brace_body(code, open_idx):
    depth = 0
    for i in range(open_idx, len(code)):
        if code[i] == "{":
            depth += 1
        elif code[i] == "}":
            depth -= 1
            if depth == 0:
                return code[open_idx + 1:i]
    return None


def named_body(code, kind, name):
    match = re.search(r"\b" + kind + r"\s+" + re.escape(name) +
                      r"\b[^;{]*\{", code)
    return brace_body(code, match.end() - 1) if match else None


def function_body(code, signature):
    match = re.search(signature, code)
    if not match:
        return None
    opening = code.find("{", match.end() - 1)
    return brace_body(code, opening) if opening >= 0 else None


def require(text, pattern, message):
    if re.search(pattern, text, flags=re.S) is None:
        raise Reject(message)


def verify(header, processor):
    code = strip_comments(header)
    early = named_body(code, "struct", "EarlyReflections")
    reverb = named_body(code, "struct", "UpgradedReverb")
    if early is None or reverb is None:
        raise Reject("EarlyReflections or UpgradedReverb not found")

    setter = function_body(early, r"\bvoid\s+setRoomSize\s*\(\s*float\s+roomSize\s*\)")
    process = function_body(early, r"\bfloat\s+process\s*\(\s*float\s+input\s*\)")
    prepare = function_body(early, r"\bvoid\s+prepare\s*\(\s*double\s+sr\s*\)")
    begin = function_body(reverb, r"\bvoid\s+beginBlock\s*\(\s*float\s+roomSize\s*,")
    if any(body is None for body in (setter, process, prepare, begin)):
        raise Reject("required EarlyReflections/UpgradedReverb method missing")

    for member in (
            r"\bfloat\s+tapDelay\s*\[\s*8\s*\]",
            r"\bfloat\s+targetTapDelay\s*\[\s*8\s*\]",
            r"\bfloat\s+tapGain\s*\[\s*8\s*\]",
            r"\bfloat\s+targetTapGain\s*\[\s*8\s*\]",
            r"\bint\s+transitionSamplesRemaining\s*=\s*0\s*;",
            r"\bbool\s+roomSizeInitialized\s*=\s*false\s*;"):
        require(early, member, "early-reflection transition state missing: " + member)

    # setRoomSize only changes targets after initialization, and seeds both
    # sides on first use so a fresh prepare cannot ramp from stale/zero taps.
    require(setter, r"if\s*\(\s*!roomSizeInitialized\s*\)",
            "setRoomSize no longer distinguishes first-use transition seeding")
    require(setter,
            r"tapDelay\s*\[\s*i\s*\]\s*=\s*targetTapDelay\s*\[\s*i\s*\]\s*=\s*delaySamps\s*;",
            "first-use seed must initialize active and target tap delays together")
    require(setter,
            r"tapGain\s*\[\s*i\s*\]\s*=\s*targetTapGain\s*\[\s*i\s*\]\s*=\s*gain\s*;",
            "first-use seed must initialize active and target tap gains together")
    require(setter, r"targetTapDelay\s*\[\s*i\s*\]\s*=\s*delaySamps\s*;",
            "setRoomSize no longer retargets delays")
    require(setter, r"targetTapGain\s*\[\s*i\s*\]\s*=\s*gain\s*;",
            "setRoomSize no longer retargets gains")
    if re.search(r"(?<!target)\btapDelay\s*\[\s*i\s*\]\s*=\s*delaySamps\s*;", setter):
        raise Reject("setRoomSize immediately retargets the active tap delay")
    if re.search(r"(?<!target)\btapGain\s*\[\s*i\s*\]\s*=\s*gain\s*;", setter):
        raise Reject("setRoomSize immediately retargets the active tap gain")
    require(setter,
            r"transitionSamplesRemaining\s*=\s*juce::jmax\s*\(\s*1\s*,\s*"
            r"\(int\)\s*\(\s*0\.020f\s*\*\s*sampleRate\s*\)\s*\)",
            "changed targets must arm a nonzero 20 ms transition")

    # A silent block still calls setRoomSize and arms the targets; rendering
    # advances the active fractional delay and gain without allocation.
    require(begin, r"earlyL\.setRoomSize\s*\(\s*roomSize\s*\)\s*;",
            "left early taps are not retargeted at every block")
    require(begin, r"earlyR\.setRoomSize\s*\(\s*roomSize\s*\)\s*;",
            "right early taps are not retargeted at every block")
    require(process,
            r"tapDelay\s*\[\s*i\s*\]\s*\+=\s*\(\s*targetTapDelay\s*\[\s*i\s*\]"
            r"\s*-\s*tapDelay\s*\[\s*i\s*\]\s*\)\s*/\s*divisor\s*;",
            "process() no longer slews active delays toward their targets")
    require(process,
            r"tapGain\s*\[\s*i\s*\]\s*\+=\s*\(\s*targetTapGain\s*\[\s*i\s*\]"
            r"\s*-\s*tapGain\s*\[\s*i\s*\]\s*\)\s*/\s*divisor\s*;",
            "process() no longer slews active gains toward their targets")
    require(process, r"hermiteInterp\s*\(\s*buf\s*,\s*MAX_SIZE\s*,\s*readPos\s*\)",
            "fractional tap reads no longer smooth changing delay positions")
    require(process, r"--transitionSamplesRemaining\s*==\s*0",
            "transition progress is not counted down per rendered sample")

    require(prepare, r"roomSizeInitialized\s*=\s*false\s*;",
            "prepare() must invalidate the transition seed for a fresh instance")
    require(prepare, r"setRoomSize\s*\(\s*0\.5f\s*\)",
            "prepare() must initialize the early field's default Size")

    proc = strip_comments(processor)
    require(proc, r"upgradedReverb\.beginBlock\s*\(\s*reverbSize\s*,",
            "PluginProcessor no longer supplies its smoothed Size to beginBlock")
    return None


def run(header, processor):
    try:
        verify(header, processor)
    except Reject as exc:
        return str(exc)
    return None


def replace_once(text, old, new):
    return text.replace(old, new, 1) if old in text else text


def main():
    try:
        header = SRC.read_text(encoding="utf-8")
        processor = PROC.read_text(encoding="utf-8")
    except OSError as exc:
        print("CV-077 SIZE-SMOOTHING SETUP FAIL: %s" % exc)
        return 2

    verdict = run(header, processor)
    if verdict:
        print("CV-077 SIZE-SMOOTHING FAIL: %s" % verdict)
        return 1

    probes = [
        ("abrupt active-delay retarget",
         lambda s: replace_once(
             s,
             "tapDelay[i] += (targetTapDelay[i] - tapDelay[i]) / divisor;",
             "tapDelay[i] = targetTapDelay[i];")),
        ("missing silent-start seed",
         lambda s: replace_once(
             s,
             "tapDelay[i] = targetTapDelay[i] = delaySamps;",
             "targetTapDelay[i] = delaySamps;")),
    ]
    for label, mutate in probes:
        changed = mutate(header)
        if changed == header:
            print("CV-077 SIZE-SMOOTHING FAIL: probe '%s' mutation did not apply"
                  % label)
            return 1
        failure = run(changed, processor)
        if failure is None:
            print("CV-077 SIZE-SMOOTHING FAIL: probe '%s' was accepted" % label)
            return 1
        print("cv077-size-smoothing: probe '%s' rejected (%s)"
              % (label, failure[:100]))

    neutral = header.replace(
        "            bool roomSizeInitialized = false;",
        "            // Active and target values intentionally share this seed.\n"
        "            bool roomSizeInitialized = false;", 1)
    if neutral == header:
        print("CV-077 SIZE-SMOOTHING FAIL: benign edit mutation did not apply")
        return 1
    if run(neutral, processor) is not None:
        print("CV-077 SIZE-SMOOTHING FAIL: benign comment edit was rejected")
        return 1
    print("cv077-size-smoothing: benign comment edit accepted")

    if run(SRC.read_text(encoding="utf-8"), processor) is not None:
        print("CV-077 SIZE-SMOOTHING FAIL: live-source re-verification failed")
        return 1
    print("CV-077 SIZE-SMOOTHING OK (2 negatives, benign edit accepted)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
