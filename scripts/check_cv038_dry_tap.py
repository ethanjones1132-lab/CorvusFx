#!/usr/bin/env python3
"""Headless checker: CV-038 folds non-finite input before the dry tap.

The input meter and the overall dry/wet blend read the per-sample dry capture.
Non-finite samples must be folded to zero before that capture, so a NaN or an
infinity cannot latch the meter or survive in the dry path. Finite samples pass
through unchanged, and CV-023's separate DSP-chain sanitiser stays in place.

The negative probe removes the fold from an in-memory source copy. The real
source file is read-only to this checker.
"""
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SRC = ROOT / "source" / "DrippyFX" / "PluginProcessor.cpp"

FOLD_L = "foldNonFiniteSamples(chData[0], numSamples);"
FOLD_R = "foldNonFiniteSamples(chData[1], numSamples);"
CAPTURE_L = "const float dryL = chData[0][s];"
METER_L = "float inV_ = std::abs(dryL);"
METER_R = "float inVR_ = std::abs(dryR);"
LOOP = re.compile(r"for\s*\(\s*int\s+s\s*=\s*0\s*;\s*s\s*<\s*numSamples\s*;\s*\+\+\s*s\s*\)")
HELPER = re.compile(
    r"inline\s+void\s+foldNonFiniteSamples\s*\([^)]*\)\s*noexcept\s*\{"
    r"[^{}]*!\s*std::isfinite\s*\(\s*samples\s*\[\s*i\s*\]\s*\)"
    r"[^{}]*samples\s*\[\s*i\s*\]\s*=\s*0\.0f\s*;[^{}]*\}")


class Rejected(Exception):
    pass


def strip_comments(src):
    src = re.sub(r"/\*.*?\*/", "", src, flags=re.S)
    return re.sub(r"//[^\n]*", "", src)


def verify(cpp_text):
    code = strip_comments(cpp_text)
    if HELPER.search(code) is None:
        raise Rejected("foldNonFiniteSamples no longer zeroes non-finite samples")
    loop = LOOP.search(code)
    if loop is None:
        raise Rejected("per-sample processBlock loop not found")
    for anchor in (FOLD_L, FOLD_R, CAPTURE_L, METER_L, METER_R):
        if code.count(anchor) != 1:
            raise Rejected("anchor must occur exactly once: %r" % anchor)
    fold_l, fold_r = code.index(FOLD_L), code.index(FOLD_R)
    capture, meter = code.index(CAPTURE_L), code.index(METER_L)
    if not (fold_l < fold_r < loop.start() < capture < meter):
        raise Rejected("input must be folded before the loop captures the dry tap the meter reads")
    between = code[fold_r + len(FOLD_R):loop.start()]
    if "chData" in between:
        raise Rejected("nothing may touch chData between the fold and the dry capture")


def run_text(text):
    try:
        verify(text)
    except Rejected as exc:
        return str(exc)
    return None


def main():
    if not SRC.exists():
        print("CV038 SETUP FAIL: missing %s" % SRC)
        return 2
    try:
        text = SRC.read_text(encoding="utf-8")
    except OSError as exc:
        print("CV038 SETUP FAIL: %s" % exc)
        return 2

    verdict = run_text(text)
    if verdict is not None:
        print("CV038 FAIL: %s" % verdict)
        return 1

    for label, removed in (
            ("left channel", text.replace(FOLD_L, "", 1)),
            ("right channel", text.replace(FOLD_R, "", 1)),
            ("helper body", text.replace("samples[i] = 0.0f;", "(void) samples[i];", 1))):
        if removed == text:
            print("CV038 FAIL: negative probe is stale: %s mutation did not apply" % label)
            return 1
        verdict = run_text(removed)
        if verdict is None:
            print("CV038 FAIL: dropping the %s fold was not rejected" % label)
            return 1
        print("cv038: %s probe rejected (%s)" % (label, verdict))

    print("cv038: input is folded before the dry tap the meter and blend read")
    return 0


if __name__ == "__main__":
    sys.exit(main())
