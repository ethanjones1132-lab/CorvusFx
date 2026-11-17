#!/usr/bin/env python3
"""Headless checker: CV-062 — first sample after reset (or prepare) snaps delay to clamped target.

after a prepare/reset the delay line starts at its clamped target time instead of
gliding up from 0 ms. On the first sample after a reset (or prepare), snap the
smoothed delay to the clamped delay target rather than leaving it at 0 and letting
the one-pole climb. Do not change parameter ids, ranges, defaults, the preset
table, or the smoothing coefficient during normal operation: only the first
sample after reset snaps.
"""
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SRC = ROOT / "source" / "DrippyFX" / "dsp" / "CorvusEffects.h"

class Reject(Exception):
    pass
def strip_comments(src):
    src = re.sub(r"/\*.*?\*/", "", src, flags=re.S)
    src = re.sub(r"//[^\n]*", "", src)
    return src
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
def struct_body(code, name):
    match = re.search(r"\bstruct\s+" + re.escape(name) + r"\b[^;{]*\{", code)
    if not match:
        return None
    return brace_body(code, match.end() - 1)
def function_bodies(text, pattern):
    bodies = []
    for match in re.finditer(pattern, text):
        opening = text.find("{", match.end() - 1)
        if opening == -1:
            continue
        body = brace_body(text, opening)
        if body is not None:
            bodies.append(body)
    return bodies
def verify(header_text):
    code = strip_comments(header_text)
    delay = struct_body(code, "EnhancedDelay")
    if delay is None:
        raise Reject("struct EnhancedDelay not found / brace-matched")
    if len(delay) < 1200:
        raise Reject("brace matching drifted (EnhancedDelay body is only %d "
                     "chars) - do not trust green" % len(delay))

    # Check that EnhancedDelay::reset() sets smoothedDelay to clamped target, not 0
    resets = function_bodies(delay, r"void\s+reset\s*\(\s*\)")
    if not resets:
        raise Reject("EnhancedDelay::reset() body not found")
    reset = resets[0]
    
    # Look for smoothedDelay[0] = smoothedDelay[1] = 0.0f pattern
    if re.search(r"smoothedDelay\s*\[\s*0\s*\]\s*=\s*smoothedDelay\s*\[\s*1\s*\]\s*=\s*0\.0f", reset) is None:
        raise Reject("EnhancedDelay::reset() no longer sets smoothedDelay[0] and "
                     "smoothedDelay[1] to 0.0f - the first sample after reset "
                     "would not start at 0")
    
    # Check that EnhancedDelay::prepare() calls reset() after resizing the ring
    prepares = function_bodies(delay, r"void\s+prepare\s*\(\s*double\s+sr\s*\)")
    if not prepares:
        raise Reject("EnhancedDelay::prepare() body not found")
    prepare = prepares[0]
    
    # prepare() should resize ring first, then call reset()
    resize_calls = list(re.finditer(
        r"resizeRing\s*\(\s*ringLengthFor\s*\(\s*sampleRate\s*\)\s*\)", prepare))
    reset_calls = list(re.finditer(
        r"reset\s*\(\s*\)", prepare))
    
    if not resize_calls:
        raise Reject("prepare() no longer sizes the ring before reset()")
    if not reset_calls:
        raise Reject("prepare() no longer calls reset() after sizing the ring")
    
    # reset() should be called after resizeRing() in prepare()
    resize_match = resize_calls[0]
    reset_match = reset_calls[0]
    if reset_match.start() < resize_match.start():
        raise Reject("prepare() calls reset() before resizeRing() - the ring would "
                     "not be resized on reset")
    
    # Check that processSample() performs the delay snapping on first sample after reset
    procs = function_bodies(delay, r"void\s+processSample\s*\(")
    if not procs:
        raise Reject("EnhancedDelay::processSample body not found")
    proc = procs[0]
    
    # Check for the delay smoothing calculation (the one-pole smoothing)
    # We need to ensure that on the first sample after reset, the smoothed delay
    # snaps to the clamped target instead of starting from 0
    smoothing_pattern = r"smoothedDelay\s*\[\s*0\s*\]\s*=\s*smoothedDelay\s*\[\s*0\s*\]\s*\*\s*blockCoeffs\.smooth\s*\s*\+\s*\(\s*targetSmp\s*\s*\+\s*modSamples\s*\)\s*\*\s*\(\s*1\.0f\s*\s*-\s*blockCoeffs\.smooth\s*\)"
    if re.search(smoothing_pattern, proc) is None:
        raise Reject("processSample() no longer contains the one-pole smoothing "
                     "calculation - the delay would not ramp up from 0")
    
    # Check for the clamp after smoothing
    clamp_pattern = (r"for\s*\(\s*int\s+ch\s*=\s*0\s*;\s*ch\s*<\s*2\s*;\s*\+\+ch\s*\)\s*"
                     r"\{?\s*smoothedDelay\s*\[\s*ch\s*\]\s*=\s*juce::jlimit\s*\(\s*"
                     r"1\.0f\s*,\s*blockCoeffs\.maxDelayF\s*,\s*"
                     r"smoothedDelay\s*\[\s*ch\s*\]\s*\)\s*;?\s*\}?")
    if re.search(clamp_pattern, proc) is None:
        raise Reject("processSample() no longer clamps smoothedDelay after smoothing "
                     "- the delay value could exceed maxDelayF")
    
    # The actual CV-062 fix: the first sample after a reset/prepare snaps the
    # smoothed delay to the clamped target instead of gliding up from 0 ms.
    snap = re.search(
        r"if\s*\(\s*firstSampleAfterReset\s*\)\s*\{\s*"
        r"smoothedDelay\s*\[\s*0\s*\]\s*=\s*smoothedDelay\s*\[\s*1\s*\]\s*=\s*targetSmp\s*;\s*"
        r"firstSampleAfterReset\s*=\s*false\s*;\s*\}",
        proc)
    if snap is None:
        raise Reject("processSample() lost the first-sample snap - the first "
                     "sample after reset/prepare would glide up from 0 ms "
                     "again (pitch drag after every prepare)")
    if snap.end() > re.search(r"for\s*\(\s*int\s+ch", proc).start():
        raise Reject("the first-sample snap must run before the smoothing and "
                     "clamp, not after them")
    if re.search(r"firstSampleAfterReset\s*=\s*true\s*;", reset) is None:
        raise Reject("EnhancedDelay::reset() no longer arms firstSampleAfterReset "
                     "- a prepare/reset would not snap the delay to its target")

    # Check that the 0.9997 smoothing coefficient is preserved in prepare()
    if re.search(r"smooth\s*=\s*0\.9997f", prepare) is None:
        raise Reject("prepare() lost the 0.9997 delay-time smoothing coefficient - "
                     "the one-pole smoothing is essential for normal operation")
    
    # The key check: ensure that reset() sets smoothedDelay to 0.0f
    # and that processSample() will snap to clamped target on first sample
    # This is implicitly checked by the reset pattern above
    
    print("cv062: EnhancedDelay resets smoothedDelay to 0.0f in reset(), "
          "prepare() calls reset() after sizing the ring, and processSample() "
          "performs the one-pole smoothing with a subsequent clamp - the first "
          "sample after reset will snap to the clamped target value")
def run(header_text):
    try:
        verify(header_text)
    except Reject as exc:
        return str(exc)
    return None
def main():
    if not SRC.exists():
        print("CV062 SETUP FAIL: missing %s" % SRC)
        return 2
    try:
        text = SRC.read_text(encoding="utf-8", errors="replace")
    except OSError as exc:
        print("CV062 SETUP FAIL: %s" % exc)
        return 2

    verdict = run(text)
    if verdict is not None:
        print("CV062 FAIL: %s" % verdict)
        return 1
    print("cv062: EnhancedDelay::reset() sets smoothedDelay to 0.0f, "
          "prepare() calls reset() after resizing, and processSample() "
          "performs one-pole smoothing with clamp - first sample after reset "
          "snaps to clamped target")

    # Negative probes - these should all be rejected
    probes = [
        ("make reset() set smoothedDelay to clamped target instead of 0.0f",
         lambda s: s.replace(
             "        smoothedDelay[0] = smoothedDelay[1] = 0.0f;",
             "        smoothedDelay[0] = smoothedDelay[1] = juce::jlimit(1.0f, blockCoeffs.maxDelayF, targetSmp);", 1)),
        
        ("make prepare() NOT call reset() after sizing the ring",
         lambda s: s.replace(
             "        oversample[1].prepare(sampleRate);\n        reset();",
             "        oversample[1].prepare(sampleRate);", 1)),
        
        ("make processSample() NOT perform one-pole smoothing",
         lambda s: s.replace(
             "        smoothedDelay[0] = smoothedDelay[0] * blockCoeffs.smooth + (targetSmp + modSamples) * (1.0f - blockCoeffs.smooth);",
             "        smoothedDelay[0] = targetSmp + modSamples;", 1)),

        ("remove the first-sample snap (delay glides up from 0 ms again)",
         lambda s: s.replace(
             "        if (firstSampleAfterReset)\n        {\n            smoothedDelay[0] = smoothedDelay[1] = targetSmp;\n            firstSampleAfterReset = false;\n        }\n        else\n        {\n",
             "        if (false)\n        {\n            smoothedDelay[0] = smoothedDelay[1] = targetSmp;\n            firstSampleAfterReset = false;\n        }\n        else\n        {\n", 1)),
    ]
    
    for label, mutate in probes:
        mutated = mutate(text)
        if mutated == text:
            print("CV062 FAIL: probe '%s' is stale: mutation did not apply - "
                  "cannot trust the negative check" % label)
            return 1
        verdict = run(mutated)
        if verdict is None:
            print("CV062 FAIL: probe '%s' was NOT rejected - checker is "
                  "vacuous" % label)
            return 1
        print("cv062: probe '%s' rejected (%s)" % (label, verdict[:96]))

    print("cv062: OK (3 negatives rejected)")
    return 0
if __name__ == "__main__":
    sys.exit(main())