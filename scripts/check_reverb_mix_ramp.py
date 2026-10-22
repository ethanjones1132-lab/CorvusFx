#!/usr/bin/env python3
"""Headless checker: the reverb wet/dry follows the mix ramp, per sample.

CV-023 (effects slice) reports two floor-review defects in
`source/DrippyFX/dsp/CorvusEffects.h`:

  1. room-size change memset the early-reflection buffer every block
     (fixed in f87e5e8, guarded by `lastRoomSize` in beginBlock; that half is
     enforced by `check_early_reflections_resize.py`, whose negative probe
     removes the guard and must be rejected -- untouched here);
  2. reverb dry/wet stayed stale for the length of the ramp: the host's 20 ms
     LinearSmoothedValue moved `smoothReverbMix`, but `UpgradedReverb` only
     receives the block-level mix, so beginBlock() baked cos/sin gains once per
     block and processSample() multiplied those constants into the output. The
     ramp never reached the applied balance: the wet/dry stepped at the block
     boundary.

The live shape this checker enforces for (2):

    blockCoeffs.dryGain = std::cos(wetMix * halfPi);
    blockCoeffs.wetGain = std::sin(wetMix * halfPi) * 1.5f;
    if (!wetMixValid || std::fabs(wetMix - lastWetMix) <= 1e-6f) {
        appliedDryGain = dryGain;  appliedWetGain = wetGain;  // settled/exact
        mixRampSamplesLeft = 0;
    } else {
        const int rampSamples = jmax(1, (int)(MIX_RAMP_SECONDS * sampleRate));
        mixRampSamplesLeft = rampSamples;
        dryGainStep = (dryGain - appliedDryGain) / rampSamples; ...
    }
    ...
    // in processSample()
    if (blockCoeffs.mixRampSamplesLeft > 0) {
        appliedDryGain += dryGainStep;  appliedWetGain += wetGainStep;
        if (--mixRampSamplesLeft == 0) { applied* = *Gain; }   // land exactly
    }
    outL = inL * appliedDryGain + revL * appliedWetGain;
    outR = inR * appliedDryGain + revR * appliedWetGain;

Asserts on the real tree (comment-stripped, brace-matched UpgradedReverb):
  (a) the equal-power target gains are still computed from wetMix (no gain
      staging trade for the ramp);
  (b) beginBlock() arms the ramp only on a mix change: it tests `lastWetMix`,
      computes a per-sample step from the distance to the target over a
      MIX_RAMP_SECONDS-long ramp, and snaps applied* to the targets when the
      mix has not moved (a settled mix stays bit-exact);
  (c) the ramp state is declared at class scope with a defined start, and
      prepare() resets it so the first block snaps instead of ramping from
      stale gain state;
  (d) processSample() advances appliedDry/WetGain once per sample while a ramp
      is armed, lands exactly on the target, and the output multiply uses the
      applied gains -- never the block-constant dryGain/wetGain.

Negative self-probes on in-memory mutated copies (the real tree is never
mutated; a mutation that changes nothing aborts as a stale alarm):
  - restore the defect: multiply the block constants dryGain/wetGain into the
    output -> rejected
  - make beginBlock() snap instead of arming a ramp (mix still jumps) ->
    rejected
  - drop the per-sample ramp advance in processSample() -> rejected
  - drop the prepare()-time ramp reset -> rejected
  - benign comment edit that names dryGain/wetGain -> accepted (comment
    stripping proves probe specificity)

Exit 0 = ok, 1 = violation with a cited diagnostic, 2 = setup/read failure.
"""
import re
from sys import exit as _quit
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SRC = ROOT / "source" / "DrippyFX" / "dsp" / "CorvusEffects.h"


class _Rejected(Exception):
    pass


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


def struct_body(code, name):
    m = re.search(r"\bstruct\s+" + re.escape(name) + r"\b[^;{]*\{", code)
    if not m:
        return None
    open_idx = m.end() - 1
    end_idx = brace_span(code, open_idx)
    if end_idx == -1:
        return None
    return code[open_idx + 1:end_idx]


def function_bodies(text, pattern):
    """Every brace-matched body whose signature matches `pattern`."""
    out = []
    for m in re.finditer(pattern, text):
        open_idx = text.find("{", m.end() - 1)
        if open_idx == -1:
            continue
        end_idx = brace_span(text, open_idx)
        if end_idx == -1:
            continue
        out.append(text[open_idx + 1:end_idx])
    return out


def _require(body, pattern, what):
    if not re.search(pattern, body, re.S):
        raise _Rejected(what)


def _verify(header_text):
    """Raise _Rejected on a violation; return None when the shape is intact."""
    code = strip_comments(header_text)
    reverb = struct_body(code, "UpgradedReverb")
    if reverb is None:
        raise _Rejected("struct UpgradedReverb not found/brace-matched")

    begins = function_bodies(
        reverb, r"void\s+beginBlock\s*\(\s*float\s+roomSize\s*,")
    if not begins:
        raise _Rejected("UpgradedReverb::beginBlock body not found")
    begin = begins[0]

    samples = function_bodies(
        reverb,
        r"void\s+processSample\s*\(\s*float\s+inL\s*,\s*float\s+inR\s*,"
        r"\s*float\s*&\s*outL")
    if not samples:
        raise _Rejected("UpgradedReverb::processSample body not found")
    sample = samples[0]

    prepares = function_bodies(reverb, r"void\s+prepare\s*\(\s*double\s+sr\s*\)")
    if not prepares:
        raise _Rejected("UpgradedReverb::prepare body not found")
    prepare = prepares[-1]

    if len(begin) < 400 or len(sample) < 400:
        raise _Rejected(
            "brace matching drifted (beginBlock %d chars, processSample %d "
            "chars) - do not trust green" % (len(begin), len(sample)))

    # (a) Gain staging must survive the change: equal-power targets from wetMix.
    _require(begin,
             r"blockCoeffs\.dryGain\s*=\s*std::cos\s*\(\s*wetMix\s*\*",
             "beginBlock no longer computes the equal-power dry target from "
             "wetMix (blockCoeffs.dryGain = std::cos(wetMix * ...)) - the "
             "reverb gain staging must not be traded for the ramp")
    _require(begin,
             r"blockCoeffs\.wetGain\s*=\s*std::sin\s*\(\s*wetMix\s*\*",
             "beginBlock no longer computes the equal-power wet target from "
             "wetMix (blockCoeffs.wetGain = std::sin(wetMix * ...) * 1.5f) - "
             "the reverb gain staging must not be traded for the ramp")

    # (b) A mix change arms a per-sample ramp; an unchanged mix snaps.
    _require(begin,
             r"std::fabs\s*\(\s*wetMix\s*-\s*lastWetMix\s*\)",
             "beginBlock no longer compares the requested mix against "
             "lastWetMix - without a change test the applied gains either jump "
             "every block or ramp forever")
    _require(begin,
             r"appliedDryGain\s*=\s*blockCoeffs\.dryGain\s*;",
             "beginBlock no longer snaps appliedDryGain to the target when the "
             "mix is unchanged - a settled mix must stay bit-exact")
    _require(begin,
             r"appliedWetGain\s*=\s*blockCoeffs\.wetGain\s*;",
             "beginBlock no longer snaps appliedWetGain to the target when the "
             "mix is unchanged - a settled mix must stay bit-exact")
    _require(begin,
             r"rampSamples\s*=\s*juce::jmax\s*\(\s*1\s*,",
             "beginBlock no longer derives a non-zero ramp length in samples")
    _require(begin,
             r"mixRampSamplesLeft\s*=\s*rampSamples\s*;",
             "beginBlock no longer arms the per-sample ramp "
             "(mixRampSamplesLeft = rampSamples) - the mix change would still "
             "step at the block boundary")
    _require(begin,
             r"dryGainStep\s*=\s*\(\s*blockCoeffs\.dryGain\s*-\s*"
             r"blockCoeffs\.appliedDryGain\s*\)[^;]*;",
             "beginBlock no longer computes dryGainStep from the distance to "
             "the dry target - the ramp has no per-sample slope")
    _require(begin,
             r"wetGainStep\s*=\s*\(\s*blockCoeffs\.wetGain\s*-\s*"
             r"blockCoeffs\.appliedWetGain\s*\)[^;]*;",
             "beginBlock no longer computes wetGainStep from the distance to "
             "the wet target - the ramp has no per-sample slope")
    _require(begin,
             r"lastWetMix\s*=\s*wetMix\s*;",
             "beginBlock no longer stores lastWetMix - every block would look "
             "like a change and re-arm the ramp")

    # (c) Ramp state declared with a defined start and reset by prepare().
    _require(reverb,
             r"float\s+lastWetMix\s*=\s*0\.0f\s*;",
             "`float lastWetMix = 0.0f;` member missing - the change test has "
             "nothing to compare against")
    _require(reverb,
             r"bool\s+wetMixValid\s*=\s*false\s*;",
             "`bool wetMixValid = false;` member missing - the first block "
             "cannot be distinguished from a mix change")
    _require(reverb,
             r"static\s+constexpr\s+float\s+MIX_RAMP_SECONDS\s*=\s*0\.0[0-9]+f\s*;",
             "MIX_RAMP_SECONDS constant missing - the applied wet/dry has no "
             "defined ramp length and steps instead of following the knob ramp")
    _require(prepare,
             r"wetMixValid\s*=\s*false\s*;",
             "prepare() no longer marks the mix state invalid - a re-prepared "
             "reverb would ramp from the previous instance's gain state")
    _require(prepare,
             r"mixRampSamplesLeft\s*=\s*0\s*;",
             "prepare() no longer clears the armed ramp (mixRampSamplesLeft) - "
             "a re-prepared reverb could resume a stale ramp")

    # (d) processSample advances the applied gains and multiplies with them.
    if re.search(r"inL\s*\*\s*blockCoeffs\.dryGain\b", sample) or \
       re.search(r"inR\s*\*\s*blockCoeffs\.dryGain\b", sample):
        line = code[:code.find(sample)].count("\n") + 1
        raise _Rejected(
            "processSample (near line %d) multiplies the block-constant "
            "dryGain into the output - that is the reported defect: the "
            "wet/dry balance ignores the mix ramp and steps per block" % line)
    _require(sample,
             r"if\s*\(\s*blockCoeffs\.mixRampSamplesLeft\s*>\s*0\s*\)",
             "processSample no longer runs the armed ramp "
             "(if (mixRampSamplesLeft > 0)) - the per-sample balance never "
             "moves toward the new mix")
    _require(sample,
             r"blockCoeffs\.appliedDryGain\s*\+=\s*blockCoeffs\.dryGainStep\s*;",
             "processSample no longer advances appliedDryGain by dryGainStep - "
             "the applied dry gain cannot follow the ramp")
    _require(sample,
             r"blockCoeffs\.appliedWetGain\s*\+=\s*blockCoeffs\.wetGainStep\s*;",
             "processSample no longer advances appliedWetGain by wetGainStep - "
             "the applied wet gain cannot follow the ramp")
    _require(sample,
             r"blockCoeffs\.appliedDryGain\s*=\s*blockCoeffs\.dryGain\s*;",
             "processSample no longer lands appliedDryGain exactly on the "
             "target when the ramp completes - a settled mix would keep "
             "interpolation residue")
    _require(sample,
             r"blockCoeffs\.appliedWetGain\s*=\s*blockCoeffs\.wetGain\s*;",
             "processSample no longer lands appliedWetGain exactly on the "
             "target when the ramp completes - a settled mix would keep "
             "interpolation residue")
    out_l = re.search(
        r"outL\s*=\s*inL\s*\*\s*blockCoeffs\.appliedDryGain\s*\+\s*"
        r"revL\s*\*\s*blockCoeffs\.appliedWetGain\s*;", sample)
    if not out_l:
        raise _Rejected(
            "processSample no longer applies the ramped gains "
            "(outL = inL * appliedDryGain + revL * appliedWetGain) - the "
            "wet/dry balance is not driven by the applied gains")
    out_r = re.search(
        r"outR\s*=\s*inR\s*\*\s*blockCoeffs\.appliedDryGain\s*\+\s*"
        r"revR\s*\*\s*blockCoeffs\.appliedWetGain\s*;", sample)
    if not out_r:
        raise _Rejected(
            "processSample no longer applies the ramped gains "
            "(outR = inR * appliedDryGain + revR * appliedWetGain) - the "
            "wet/dry balance is not driven by the applied gains")
    advance = sample.find("blockCoeffs.appliedDryGain +=")
    if advance == -1 or advance > out_l.start():
        raise _Rejected(
            "processSample applies the output gains BEFORE advancing the ramp "
            "- the first sample of every block would use the previous block's "
            "applied balance")
    return None


def run_text(header_text):
    try:
        _verify(header_text)
    except _Rejected as r:
        return str(r)
    return None


def main():
    if not SRC.exists():
        print("REVERB-MIX-RAMP SETUP FAIL: missing source file %s" % SRC)
        return 2
    try:
        text = SRC.read_text(encoding="utf-8")
    except OSError as e:
        print("REVERB-MIX-RAMP SETUP FAIL: cannot read %s (%s)" % (SRC, e))
        return 2

    verdict = run_text(text)
    if verdict is not None:
        print("REVERB-MIX-RAMP FAIL: %s" % verdict)
        return 1
    print("reverb-mix-ramp: applied wet/dry ramps per sample toward the "
          "block's mix target and snaps bit-exactly when settled")

    # Negative self-probes: each mutation reintroduces the reported defect in a
    # different shape. The real tree is never mutated.
    probes = [
        ("restore the block-constant wet/dry (the reported defect)",
         lambda s: s.replace(
             "outL = inL * blockCoeffs.appliedDryGain + revL * "
             "blockCoeffs.appliedWetGain;",
             "outL = inL * blockCoeffs.dryGain + revL * blockCoeffs.wetGain;",
             1).replace(
             "outR = inR * blockCoeffs.appliedDryGain + revR * "
             "blockCoeffs.appliedWetGain;",
             "outR = inR * blockCoeffs.dryGain + revR * blockCoeffs.wetGain;",
             1)),
        ("make beginBlock snap instead of arming the ramp",
         lambda s: s.replace(
             "blockCoeffs.mixRampSamplesLeft = rampSamples;",
             "blockCoeffs.mixRampSamplesLeft = 0;", 1)),
        ("drop the per-sample ramp advance in processSample",
         lambda s: s.replace(
             "if (blockCoeffs.mixRampSamplesLeft > 0)",
             "if (false)", 1)),
        ("drop the prepare()-time ramp reset",
         lambda s: s.replace(
             "        lastWetMix = 0.0f;\n        wetMixValid = false;\n",
             "", 1)),
    ]
    for label, mutate in probes:
        mutated = mutate(text)
        if mutated == text:
            print("REVERB-MIX-RAMP FAIL: no-op probe (%s): mutation did not "
                  "change the source - the negative check is vacuous" % label)
            return 1
        verdict = run_text(mutated)
        if verdict is None:
            print("REVERB-MIX-RAMP FAIL: negative probe '%s' was NOT rejected "
                  "- checker is vacuous" % label)
            return 1
        print("reverb-mix-ramp: negative probe '%s' rejected (%s...)"
              % (label, verdict[:72]))

    # Specificity: a comment naming the gains must not trip the checker.
    neutral = text.replace(
        "// Equal-power wet/dry crossfade -- constant perceived level across mix range.",
        "// The block-constant dryGain/wetGain must NOT reach the output; only\n"
        "        // the applied gains may (this comment is not code).\n"
        "        // Equal-power wet/dry crossfade -- constant perceived level "
        "across mix range.",
        1)
    if neutral == text:
        print("REVERB-MIX-RAMP FAIL: no-op guard: neutral comment edit did not "
              "change the source - probe is stale")
        return 1
    verdict = run_text(neutral)
    if verdict is not None:
        print("REVERB-MIX-RAMP FAIL: benign comment edit was REJECTED - "
              "checker over-fires: %s" % verdict)
        return 1
    print("reverb-mix-ramp: harmless comment edit passes (probe specificity "
          "proven)")

    if run_text(SRC.read_text(encoding="utf-8")) is not None:
        print("REVERB-MIX-RAMP FAIL: final live-source re-verification failed")
        return 1
    print("REVERB-MIX-RAMP OK")
    return 0


if __name__ == "__main__":
    _quit(main())
