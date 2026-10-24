#!/usr/bin/env python3
"""Headless invariant check: CV-023 effects-chain INPUT finiteness guard.

Pins the front of the DrippyFX/Corvus processBlock per-sample body
(source/DrippyFX/PluginProcessor.cpp). Before CV-023 the only finiteness
sanitiser ran at the very END of the per-sample chain
(`chData[...] = std::isfinite(...) ? ... : 0.0f`), so a NaN or infinity
entering the chain was stored inside delay.processSample()/reverb feedback
state and kept repeating for the rest of the session: the output guard
replaced the emitted sample but the poisoned buffer state stayed.
`juce::jlimit` is comparison-based and maps neither NaN nor infinity to a
bound, so the input clamp alone cannot stop it.

The fix folds the chain INPUT back to 0 immediately after the +/-2.0f headroom
clamp, before ANY DSP (distortion/chorus/delay/reverb/master) reads smpL/smpR.

Asserts (comment-stripped, per-sample loop body):
  (a) the input read/seed pair and the +/-2.0f jlimit clamp survive unchanged.
  (b) an input finiteness guard exists for BOTH channels:
        smpL = std::isfinite(smpL) ? smpL : 0.0f;
        smpR = std::isfinite(smpR) ? smpR : 0.0f;
      (the R guard keeps the mono duplicate consistent: for a mono bus smpR
      mirrors smpL, so both fold together; no extra branch is allowed).
  (c) the guards sit BETWEEN the input read (seed lines) and the first
      processSample/reverb call in the chain
      (seedL < seedR < guardL < guardR < distortion < delay < reverb).
  (d) the POST-chain output guard still exists exactly once per channel
      (`chData[0][s] = std::isfinite(smpL) ? ...` and the `if (!isMono)` R
      line) and still sits AFTER the reverb call — the last line of defence
      must not be dropped or moved in favour of the input guard.

Negative self-probes on mutated in-memory texts (real tree is never mutated):
  - input guard pair removed -> rejected (this is exactly the pre-CV-023
    shape, so the checker also proves it FAILS on the unfixed file)
  - input guard moved after delay.processSample -> rejected
  - post-chain output guard removed -> rejected
  - post-chain output guard moved before the reverb call -> rejected
  - benign no-op edit outside the pinned shape -> accepted (probe specificity)

Exit 0 = ok, 1 = violation.
"""
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SRC = ROOT / "source" / "DrippyFX" / "PluginProcessor.cpp"

SEED_L = "float smpL = juce::jlimit(-2.0f, 2.0f, chData[0][s]);"
SEED_R = "float smpR = juce::jlimit(-2.0f, 2.0f, isMono ? smpL : chData[1][s]);"
GUARD_L = "smpL = std::isfinite(smpL) ? smpL : 0.0f;"
GUARD_R = "smpR = std::isfinite(smpR) ? smpR : 0.0f;"
POST_L = "chData[0][s] = std::isfinite(smpL) ? smpL : 0.0f;"
POST_R = "if (!isMono) chData[1][s] = std::isfinite(smpR) ? smpR : 0.0f;"
DSP_DIST = "distortion.process("
DSP_DELAY = "delay.processSample("
DSP_REVERB = "upgradedReverb.processSample("


def fail(msg):
    print(f"CV023-INPUT-FINITE FAIL: {msg}")
    sys.exit(1)


def strip_comments(src):
    src = re.sub(r"//[^\n]*", "", src)
    src = re.sub(r"/\*.*?\*/", "", src, flags=re.S)
    return src


def brace_span(s, open_idx):
    depth = 0
    for j in range(open_idx, len(s)):
        if s[j] == "{":
            depth += 1
        elif s[j] == "}":
            depth -= 1
            if depth == 0:
                return j
    return -1


class _Rejected(Exception):
    pass


def _verify(cpp_text):
    """Raise _Rejected on any pinned-shape violation. None = pass."""
    c = strip_comments(cpp_text)
    mm = re.search(
        r"for\s*\(\s*int\s+s\s*=\s*0\s*;\s*s\s*<\s*numSamples\s*;\s*\+\+\s*s\s*\)",
        c)
    if not mm:
        raise _Rejected("per-sample loop `for (int s = 0; s < numSamples; ++s)` not found")
    o = c.find("{", mm.end())
    e = brace_span(c, o)
    if e == -1:
        raise _Rejected("per-sample loop body braces unbalanced")
    b = c[o + 1:e]
    if len(b) < 500:
        raise _Rejected("per-sample loop body is only %d chars - loop detection "
                        "has drifted; do not trust green" % len(b))

    def need(anchor):
        if anchor not in b:
            raise _Rejected("missing anchor: %r" % anchor)

    # (a) input read/seed pair unchanged
    seedL = b.find(SEED_L)
    seedR = b.find(SEED_R)
    if seedL == -1 or seedR == -1:
        raise _Rejected("input seed pair missing (read of chData +/-2.0f clamp)")
    if b.count("jlimit(-2.0f, 2.0f") != 2:
        raise _Rejected("input headroom jlimit(-2.0f, 2.0f) count changed - seed "
                        "lines drifted")

    # (b) input finiteness guard, BOTH channels, exactly once each
    gL = b.find(GUARD_L)
    gR = b.find(GUARD_R)
    if gL == -1 or gR == -1:
        raise _Rejected("input finiteness guard missing - a non-finite sample "
                        "reaches delay.processSample()/reverb and poisons "
                        "feedback state (the pre-CV-023 shape)")
    for anchor in (GUARD_L, GUARD_R):
        if b.count(anchor) != 1:
            raise _Rejected("input finiteness guard for smpL/smpR must appear "
                            "exactly once each (found %d of %r)" % (
                                b.count(anchor), anchor))

    # (c) order: after BOTH seeds, before the FIRST DSP call in the chain
    off_dist = b.find(DSP_DIST)
    off_delay = b.find(DSP_DELAY)
    off_reverb = b.find(DSP_REVERB)
    if min(off_dist, off_delay, off_reverb) == -1:
        raise _Rejected("DSP call anchors missing (distortion/delay/reverb) - "
                        "processing chain drifted")
    if seedR < seedL:
        raise _Rejected("mono-mirror R seed precedes the L seed - seed lines drifted")
    if gL <= seedL or gR <= seedR:
        raise _Rejected("input finiteness guard sits BEFORE the input read - "
                        "it would pass the pre-clamp value through")
    first_dsp = min(off_dist, off_delay, off_reverb)
    if gL >= first_dsp or gR >= first_dsp:
        raise _Rejected("input finiteness guard does NOT sit between the input "
                        "read and the first processSample/reverb call - a "
                        "poisoned sample still reaches the DSP state")

    # (d) post-chain output guard: still present, exactly once per channel,
    # still AFTER the reverb call (last line of defence untouched)
    pL = b.find(POST_L)
    pR = b.find(POST_R)
    if pL == -1 or pR == -1:
        raise _Rejected("post-chain output guard missing - the last line of "
                        "defence must stay even with the input guard in place")
    if b.count(POST_L) != 1 or b.count(POST_R) != 1:
        raise _Rejected("post-chain output guard duplicated or reshaped - each "
                        "channel must be written exactly once")
    if pL <= off_reverb or pR <= off_reverb:
        raise _Rejected("post-chain output guard moved before the reverb call - "
                        "output sanitisation order drifted")
    if pL < off_dist:
        raise _Rejected("post-chain output guard moved before the first DSP call")


def run_text(cpp_text):
    try:
        _verify(cpp_text)
    except _Rejected as r:
        return str(r)
    return None


text = SRC.read_text(encoding="utf-8")

# ---- positive: the live source must satisfy every pinned property ----
verdict = run_text(text)
if verdict is not None:
    fail(verdict)

# ---- negative probes (in-memory mutations; each must be REJECTED) ----
GUARD_BLOCK = (
    "        smpL = std::isfinite(smpL) ? smpL : 0.0f;\n"
    "        smpR = std::isfinite(smpR) ? smpR : 0.0f;\n")

probes = [
    ("input finiteness guard removed (pre-CV-023 shape)",
     lambda s: s.replace(GUARD_BLOCK, "")),
    ("input finiteness guard moved after delay.processSample",
     lambda s: s.replace(GUARD_BLOCK, "").replace(
         "            delay.processSample(smpL, smpR, dL, dR,\n"
         "                sDelayTime, sDelayFb, sDelayMix,\n"
         "                pingPong, sDelayMod);\n",
         "            delay.processSample(smpL, smpR, dL, dR,\n"
         "                sDelayTime, sDelayFb, sDelayMix,\n"
         "                pingPong, sDelayMod);\n" + GUARD_BLOCK)),
    ("post-chain output guard removed",
     lambda s: s.replace(
         "        chData[0][s] = std::isfinite(smpL) ? smpL : 0.0f;\n"
         "        if (!isMono) chData[1][s] = std::isfinite(smpR) ? smpR : 0.0f;\n",
         "")),
    ("post-chain output guard moved before the reverb call",
     lambda s: s.replace(
         "        chData[0][s] = std::isfinite(smpL) ? smpL : 0.0f;\n"
         "        if (!isMono) chData[1][s] = std::isfinite(smpR) ? smpR : 0.0f;\n",
         "").replace(
         "        // 1. DISTORTION (click-free bypass crossfade)\n",
         "        chData[0][s] = std::isfinite(smpL) ? smpL : 0.0f;\n"
         "        if (!isMono) chData[1][s] = std::isfinite(smpR) ? smpR : 0.0f;\n"
         "        // 1. DISTORTION (click-free bypass crossfade)\n")),
]

for label, mutate in probes:
    mutated = mutate(text)
    if mutated == text:
        fail("no-op probe (%s): mutation did not change the source - the "
             "negative check is vacuous" % label)
    verdict = run_text(mutated)
    if verdict is None:
        fail("negative probe '%s' was NOT rejected - checker is vacuous" % label)
    print("cv023-input-finite: negative probe '%s' rejected" % label)

# ---- no-op guard: benign edit outside the pinned shape must still pass ----
neutral = text.replace(
    "// CV-023 input sanitiser: jlimit is comparison-based and maps neither",
    "// CV-023 input sanitiser: jlimit is comparison-based and maps no")
if neutral == text:
    fail("no-op guard: unanchored neutral edit did not change the source")
if run_text(neutral) is not None:
    fail("neutral edit outside the pinned shape was REJECTED - checker over-fires")
print("cv023-input-finite: benign non-guard edit passes (probe specificity proven)")

# ---- final re-verification of the real source ----
final = run_text(SRC.read_text(encoding="utf-8"))
if final is not None:
    fail("final source re-verification failed: %s" % final)
print("cv023-input-finite: OK")
sys.exit(0)
