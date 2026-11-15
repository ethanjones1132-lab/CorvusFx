#!/usr/bin/env python3
"""Headless invariant check: every smoother reset in prepareToPlay is seeded.

`juce::LinearSmoothedValue::reset(sampleRate, time)` zeroes the CURRENT value
and only sets the ramp length; the target is whatever the last
setTargetValue() left behind. So a prepareToPlay that does:

    smoothX.reset(sampleRate, smoothTime);
    smoothX.setTargetValue(<current parameter value>);

starts the smoother at 0 and ramps to the real setting over the whole
smoothing time. The first `getNextValue()` after prepare therefore sweeps
output gain, delay time and every other knob from zero - audible on every
host block-size change and at the start of an offline render, and it makes
the CV-030 block-scope `getCurrentValue()` snapshot report 0 for the first
blocks after a re-prepare.

The fix seeds BOTH ends of the ramp with the value it is about to ramp toward:

    smoothX.setCurrentAndTargetValue(<current parameter value>);

Asserts (comment-stripped, brace-matched bodies):
  (a) the smoother roster declared in the header is exactly the pinned one
      (19 parameter smoothers + 5 bypass crossfade gains for the FX plugin;
      fx amount / flight / output gain for the instrument) - adding a member
      without extending this pin is a failure, not a silent pass;
  (b) every declared smoother is reset exactly once in prepareToPlay;
  (c) every one of them is seeded exactly once with
      `setCurrentAndTargetValue(` AFTER its reset() (a seed before the reset
      is discarded by the reset);
  (d) no plain `setTargetValue(` survives on any of them inside
      prepareToPlay (that is the ramp-from-zero bug this checker exists for);
  (e) prepareToPlay never advances a ramp (`getNextValue()`) or jumps one
      (`skip(`), so the seed is the value the first block really starts at;
  (f) FX parameter smoothers seed through `finiteSmoothingTarget(`, and the
      bypass crossfade gains seed from the inverted boolean literals bDist /
      bChor / bDel / bRev / bMast (the CV-023 guard and the bypass glue are
      not bypassed on the way in);
  (g) processBlock still RAMP (plain `setTargetValue(`) and never snaps
      (`setCurrentAndTargetValue(`) these smoothers on the audio thread;
  (h) the instrument's seeds read the live parameter state
      (`fx_amount` / `flight` raw loads, output through Decibels::decibelsToGain).

Negative self-probes on mutated in-memory texts (the real tree is never
mutated); each must be rejected with the intended diagnostic:
  - revert the FX overall seed to plain setTargetValue -> rejected;
  - delete the FX delay_mix seed -> rejected;
  - move the FX reverb_mix seed before its reset -> rejected;
  - revert the instrument outputGain seed to plain setTargetValue -> rejected;
  - delete the instrument flightAmount seed -> rejected;
  - benign comment addition inside prepareToPlay -> accepted (specificity).

Exit 0 = ok, 1 = violation.
"""
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SRC = ROOT / "source" / "DrippyFX"
FX_CPP = SRC / "PluginProcessor.cpp"
FX_HDR = SRC / "PluginProcessor.h"
INST_CPP = SRC / "instrument" / "CorvusInstrumentProcessor.cpp"
INST_HDR = SRC / "instrument" / "CorvusInstrumentProcessor.h"

# Pinned smoother rosters, in header declaration order.
FX_PARAM_SMOOTHERS = [
    "smoothOverall",
    "smoothFatness",
    "smoothChorusDepth",
    "smoothChorusRate",
    "smoothChorusMix",
    "smoothDelayTime",
    "smoothDelayFeedback",
    "smoothDelayMix",
    "smoothDelayDamping",
    "smoothDelayMod",
    "smoothReverbSize",
    "smoothReverbDamping",
    "smoothReverbMix",
    "smoothReverbMod",
    "smoothMasterDrive",
    "smoothMasterWidth",
    "smoothMasterMidDrive",
    "smoothMasterSideDrive",
    "smoothOutputTrim",
]

# (member, inverted-literal local) for the 5 bypass crossfade gains.
FX_BYPASS_SMOOTHERS = [
    ("bypassGainDist", "bDist"),
    ("bypassGainChorus", "bChor"),
    ("bypassGainDelay", "bDel"),
    ("bypassGainReverb", "bRev"),
    ("bypassGainMaster", "bMast"),
]

FX_ROSTER = FX_PARAM_SMOOTHERS + [m for m, _ in FX_BYPASS_SMOOTHERS]

# (member, substrings the seed expression must contain), instrument.
INST_SMOOTHERS = [
    ("fxAmount", ['getRawParameterValue("fx_amount")->load()']),
    ("flightAmount", ['getRawParameterValue("flight")->load()']),
    ("outputGain", ['getRawParameterValue("output")->load()',
                    "Decibels::decibelsToGain("]),
]

INST_ROSTER = [m for m, _ in INST_SMOOTHERS]

SEED = ".setCurrentAndTargetValue("
RAMP = ".setTargetValue("
DECL_RE = re.compile(
    r"juce::LinearSmoothedValue<float>\s+([A-Za-z_][A-Za-z0-9_]*)\s*;")


class Violation(Exception):
    pass


def fail(msg):
    print("SMOOTHER-SEED FAIL: %s" % msg)
    sys.exit(1)


def strip_comments(src):
    src = re.sub(r"/\*.*?\*/", "", src, flags=re.S)
    src = re.sub(r"//[^\n]*", "", src)
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


def fn_body(flat, marker):
    k = flat.find(marker)
    if k == -1:
        raise Violation("could not find `%s` - the function this checker pins "
                        "is gone (do not trust a green gate without it)" % marker)
    o = flat.find("{", k)
    if o == -1:
        raise Violation("could not find the opening brace of `%s`" % marker)
    e = brace_span(flat, o)
    if e == -1:
        raise Violation("unbalanced braces extracting `%s`" % marker)
    return flat[o + 1:e]


def declared_members(hdr_raw, label):
    members = DECL_RE.findall(strip_comments(hdr_raw))
    if len(members) != len(set(members)):
        dupes = sorted({m for m in members if members.count(m) > 1})
        raise Violation("%s declares duplicate smoother member(s) %s"
                        % (label, dupes))
    return members


def seed_window(body, member):
    """Text from `member.reset(` through the `;` that closes its seed."""
    start = body.find(member + ".reset(")
    seed_at = body.find(member + SEED)
    if start == -1 or seed_at == -1:
        return None
    end = body.find(";", seed_at)
    if end == -1:
        return None
    return body[start:end + 1]


def check_seeds(body, roster, where, reset_needle=".reset("):
    """Shared per-member rules: reset once, seeded once, seed after reset."""
    for member in roster:
        resets = body.count(member + reset_needle)
        if resets != 1:
            raise Violation(
                "%s must call `%s.reset(...)` exactly once, found %d - the "
                "ramp length or the whole seam changed"
                % (where, member, resets))

        seeds = body.count(member + SEED)
        if seeds == 0:
            raise Violation(
                "%s resets %s but never seeds it with "
                "`%s.setCurrentAndTargetValue(` -- after "
                "reset(sampleRate, smoothTime) the current value is 0, so the "
                "first getNextValue() ramps from 0 for the smoothing time "
                "(audible sweep on output gain and delay time at every prepare / "
                "block-size change)" % (where, member, member))
        if seeds != 1:
            raise Violation("%s seeds %s %d times, expected exactly 1 seed"
                            % (where, member, seeds))

        if (member + RAMP) in body:
            raise Violation(
                "%s still uses plain `%s.setTargetValue(` -- reset() zeroed the "
                "current value, so the smoother starts at 0 and ramps up to the "
                "setting it should already be at (the CV-023 remainder bug)"
                % (where, member))

        reset_at = body.find(member + reset_needle)
        seed_at = body.find(member + SEED)
        if seed_at < reset_at:
            raise Violation(
                "%s seeds %s BEFORE its reset(...) -- the reset zeroes the "
                "current value again, so the seed is discarded and the first "
                "block ramps from 0" % (where, member))

        if (member + ".getNextValue(") in body:
            raise Violation(
                "%s advances the %s ramp with getNextValue() -- prepare must "
                "only seed it; the first consumer block would start one step "
                "along the ramp" % (where, member))

        if (member + ".skip(") in body:
            raise Violation(
                "%s jumps the %s ramp with skip() -- the seeded value would not "
                "be the value the first block starts at" % (where, member))


def check_fx(cpp_raw, hdr_raw):
    members = declared_members(hdr_raw, "PluginProcessor.h")
    if members != FX_ROSTER:
        raise Violation(
            "PluginProcessor.h smoother roster drifted from the pinned 24 "
            "(19 parameter smoothers + 5 bypass crossfade gains): declared %s"
            % members)

    body = fn_body(strip_comments(cpp_raw),
                   "CorvusFXAudioProcessor::prepareToPlay(")
    where = "CorvusFXAudioProcessor::prepareToPlay (PluginProcessor.cpp)"

    check_seeds(body, FX_ROSTER, where, reset_needle=".reset(")

    # finiteSmoothingTarget keeps the CV-023 finiteness guard on the seed path.
    for member in FX_PARAM_SMOOTHERS:
        if (member + SEED + "finiteSmoothingTarget(") not in body:
            raise Violation(
                "%s seeds %s without finiteSmoothingTarget() -- an unguarded "
                "mapped value (NaN / inf / overflowed feedback curve) could "
                "become the seeded current value" % (where, member))

    # bypass crossfade gains seed from their inverted boolean literals.
    for member, local in FX_BYPASS_SMOOTHERS:
        if not re.search(r"%s\.setCurrentAndTargetValue\(\s*%s\s*\)\s*;"
                         % (re.escape(member), re.escape(local)), body):
            raise Violation(
                "%s seeds %s from something other than `%s` -- the crossfade "
                "gain must start at the stored bypass state (0.0 = dry)"
                % (where, member, local))

    resets = len(re.findall(r"\.reset\(sampleRate, ", body))
    seeds = len(re.findall(r"\.setCurrentAndTargetValue\(", body))
    if resets != len(FX_ROSTER) or seeds != len(FX_ROSTER):
        raise Violation(
            "%s resets %d smoother(s) and seeds %d, expected %d of each - a "
            "smoother was added or dropped without a matching seed"
            % (where, resets, seeds, len(FX_ROSTER)))

    # processBlock must keep RAMPING (it runs every block; snapping there would
    # click) - only prepareToPlay seeds current == target.
    proc = fn_body(strip_comments(cpp_raw),
                   "CorvusFXAudioProcessor::processBlock(")
    loop = proc.find("for (int s = 0; s < numSamples")
    if loop == -1:
        raise Violation("processBlock per-sample loop not found - cannot "
                        "delimit the parameter-update region")
    proc_region = proc[:loop]
    for member in FX_ROSTER:
        if (member + SEED) in proc_region:
            raise Violation(
                "processBlock snaps %s with setCurrentAndTargetValue() -- the "
                "per-block refresh must stay a ramp (setTargetValue); a snap on "
                "the audio thread is a zipper-free but audible step"
                % member)
    for member in FX_PARAM_SMOOTHERS:
        if (member + RAMP) not in proc_region:
            raise Violation(
                "processBlock no longer smooths %s with setTargetValue() - the "
                "knob would run on a stale smoother target" % member)

    return resets


def check_instrument(cpp_raw, hdr_raw):
    members = declared_members(hdr_raw, "CorvusInstrumentProcessor.h")
    if members != INST_ROSTER:
        raise Violation(
            "CorvusInstrumentProcessor.h smoother roster drifted from the "
            "pinned [fxAmount, flightAmount, outputGain]: declared %s"
            % members)

    body = fn_body(strip_comments(cpp_raw),
                   "CorvusInstrumentProcessor::prepareToPlay(")
    where = "CorvusInstrumentProcessor::prepareToPlay"

    check_seeds(body, INST_ROSTER, where, reset_needle=".reset(")

    for member, needed in INST_SMOOTHERS:
        window = seed_window(body, member)
        if window is None:  # pragma: no cover - check_seeds already fired
            raise Violation("%s lost the %s seed" % (where, member))
        flat = re.sub(r"\s+", " ", window)
        for needle in needed:
            if needle not in flat:
                raise Violation(
                    "%s seeds %s from something other than the live parameter "
                    "state - expected `%s` between the reset and the seed, got "
                    "`%s`" % (where, member, needle, flat.strip()))

    proc = fn_body(strip_comments(cpp_raw),
                   "CorvusInstrumentProcessor::processBlock(")
    for member in INST_ROSTER:
        if (member + SEED) in proc:
            raise Violation(
                "CorvusInstrumentProcessor::processBlock snaps %s with "
                "setCurrentAndTargetValue() - the render path must keep ramping "
                "with setTargetValue()" % member)

    return body.count(SEED)


def _verify(fx_cpp, fx_hdr, inst_cpp, inst_hdr):
    fx_seeds = check_fx(fx_cpp, fx_hdr)
    inst_seeds = check_instrument(inst_cpp, inst_hdr)
    return fx_seeds, inst_seeds


def run_text(fx_cpp, fx_hdr, inst_cpp, inst_hdr):
    try:
        return _verify(fx_cpp, fx_hdr, inst_cpp, inst_hdr), None
    except Violation as v:
        return None, str(v)


def line_containing(text, needle):
    for line in text.splitlines(keepends=True):
        if needle in line:
            return line
    return None


def main():
    for path in (FX_CPP, FX_HDR, INST_CPP, INST_HDR):
        if not path.exists():
            fail("missing source file %s" % path)

    fx_cpp = FX_CPP.read_text(encoding="utf-8")
    fx_hdr = FX_HDR.read_text(encoding="utf-8")
    inst_cpp = INST_CPP.read_text(encoding="utf-8")
    inst_hdr = INST_HDR.read_text(encoding="utf-8")

    # ---- positive control ------------------------------------------------
    counts, verdict = run_text(fx_cpp, fx_hdr, inst_cpp, inst_hdr)
    if verdict is not None:
        fail(verdict)
    print("smoother-seed: %d FX smoothers (19 params + 5 bypass gains) and %d "
          "instrument smoothers reset in prepareToPlay and seeded with "
          "setCurrentAndTargetValue after the reset; processBlock keeps ramping"
          % (counts[0], counts[1]))

    # ---- negative probes (in-memory mutations) ---------------------------
    probes = []

    fx_overall_seed = line_containing(fx_cpp, "smoothOverall" + SEED)
    fx_delaymix_seed = line_containing(fx_cpp, "smoothDelayMix" + SEED)
    fx_reverbmix_seed = line_containing(fx_cpp, "smoothReverbMix" + SEED)
    fx_reverbmix_reset = line_containing(fx_cpp, "smoothReverbMix.reset(")
    inst_gain_seed = line_containing(inst_cpp, "outputGain" + SEED)
    inst_flight_seed = line_containing(inst_cpp, "flightAmount" + SEED)

    for label, line in (
            ("FX overall seed anchor", fx_overall_seed),
            ("FX delay_mix seed anchor", fx_delaymix_seed),
            ("FX reverb_mix seed anchor", fx_reverbmix_seed),
            ("FX reverb_mix reset anchor", fx_reverbmix_reset),
            ("instrument outputGain seed anchor", inst_gain_seed),
            ("instrument flightAmount seed anchor", inst_flight_seed)):
        if not line:
            fail("probe anchor missing (%s) - the negative checks cannot run; "
                 "the source shape changed" % label)

    def fx_mutate(old, new):
        return lambda t: t.replace(old, new, 1)

    def inst_mutate(old, new):
        return lambda t: t.replace(old, new, 1)

    probes.append((
        "FX seed reverted to plain setTargetValue (smoothOverall)",
        "fx", fx_mutate(fx_overall_seed,
                        fx_overall_seed.replace("setCurrentAndTargetValue",
                                                "setTargetValue", 1)),
        "setCurrentAndTargetValue"))
    probes.append((
        "FX seed deleted (smoothDelayMix)",
        "fx", fx_mutate(fx_delaymix_seed, ""),
        "smoothDelayMix"))
    probes.append((
        "FX seed moved before its reset (smoothReverbMix)",
        "fx", lambda t: t.replace(fx_reverbmix_seed, "", 1).replace(
            fx_reverbmix_reset, fx_reverbmix_seed + fx_reverbmix_reset, 1),
        "BEFORE its"))
    probes.append((
        "instrument seed reverted to plain setTargetValue (outputGain)",
        "inst", inst_mutate(inst_gain_seed,
                            inst_gain_seed.replace("setCurrentAndTargetValue",
                                                   "setTargetValue", 1)),
        "outputGain"))
    probes.append((
        "instrument seed deleted (flightAmount)",
        "inst", inst_mutate(inst_flight_seed, ""),
        "flightAmount"))

    for label, target, mutate, expect in probes:
        base = fx_cpp if target == "fx" else inst_cpp
        mutated = mutate(base)
        if mutated == base:
            fail("no-op probe (%s): mutation did not change the source - the "
                 "negative check is vacuous" % label)
        if target == "fx":
            _, verdict = run_text(mutated, fx_hdr, inst_cpp, inst_hdr)
        else:
            _, verdict = run_text(fx_cpp, fx_hdr, mutated, inst_hdr)
        if verdict is None:
            fail("negative probe '%s' was NOT rejected - checker is vacuous"
                 % label)
        if expect not in verdict:
            fail("negative probe '%s' rejected for the wrong reason (expected "
                 "%r in the diagnostic, got %r)" % (label, expect, verdict))
        print("smoother-seed: negative probe '%s' rejected (%s)"
              % (label, verdict[:96]))

    # ---- benign no-op edit must still pass (probe specificity) -----------
    anchor = line_containing(fx_cpp, "smoothOverall.reset(")
    if not anchor:
        fail("no-op guard: the smoothOverall reset anchor is missing")
    neutral = fx_cpp.replace(anchor, "    // benign probe edit\n" + anchor, 1)
    if neutral == fx_cpp:
        fail("no-op guard: the benign comment edit did not change the source")
    _, verdict = run_text(neutral, fx_hdr, inst_cpp, inst_hdr)
    if verdict is not None:
        fail("benign comment edit inside prepareToPlay was REJECTED - checker "
             "over-fires: %s" % verdict)
    print("smoother-seed: benign comment edit passes (specificity proven)")

    # ---- final re-verification of the real source ------------------------
    counts, verdict = run_text(
        FX_CPP.read_text(encoding="utf-8"), fx_hdr,
        INST_CPP.read_text(encoding="utf-8"), inst_hdr)
    if verdict is not None:
        fail("final source re-verification failed: %s" % verdict)
    print("smoother-seed: OK")
    sys.exit(0)


if __name__ == "__main__":
    main()
