#!/usr/bin/env python3
"""Headless checker: reverb room-size guard + per-sample mix ramp (CV-023).

Two floor-review defects in `source/DrippyFX/dsp/CorvusEffects.h` are pinned
here because they meet in `UpgradedReverb::beginBlock()`:

  1. every block used to clear the early-reflection tap buffers (mute() ->
     memset), so the early field was silenced 60-100 times a second. The fix
     retargets the taps every block but only mutes them on a genuinely
     discontinuous room-size jump (CV-063 turns the old "did it move at all"
     test into a rate test, so smoothed knob travel never mutes):

         if (lastBlockSamples > 0)
         {
             const float blockSeconds = ... lastBlockSamples ... sampleRate;
             const float roomSizeRate = roomSizeValid
                 ? std::fabs(roomSize - lastRoomSize)
                       / juce::jmax(blockSeconds, 1.0e-6f)
                 : 0.0f;
             if (roomSizeRate > ROOM_SIZE_RATE_LIMIT)
             {
                 earlyL.mute();
                 earlyR.mute();
             }
             lastRoomSize = roomSize;  // CV-071: rendered blocks only
         }
         lastBlockSamples = 0;
         earlyL.setRoomSize(roomSize);
         earlyR.setRoomSize(roomSize);

  2. multiplying block-constant equal-power gains into the output made
     the wet/dry balance step once per block. The DSP now owns the Mix ramp:
     the applied gains move per sample and land exactly on the target.
     CV-073 keeps that ramp running when the next callback repeats the target.

Asserts on the real tree (comment-stripped, brace-matched UpgradedReverb):
  (a) beginBlock contains no memset and exactly two mute() calls (earlyL and
      earlyR), both inside the room-size rate guard; the applied size is
      tracked (`lastRoomSize = roomSize;`) outside that rate guard - CV-071
      keeps it inside the `lastBlockSamples > 0` gate, pinned by
      check_cv071_silent_size_jump.py;
  (b) earlyL/earlyR are still retargeted every block (setRoomSize outside the
      guard) and `float lastRoomSize = 0.0f;` is declared on the struct;
  (c) beginBlock keeps the equal-power dry/wet targets from wetMix, arms a
      per-sample ramp only on a mix change, snaps only on the first block,
      and leaves an in-flight ramp alone when the target is repeated;
  (d) processSample advances the applied gains before the output multiply and
      uses appliedDryGain/appliedWetGain, never the block constants;
  (e) prepare() resets the ramp state so a fresh instance snaps to its first
      mix instead of ramping from stale gains;
  (f) per-sample processing contains no mute()/memset.

Negative probes (in-memory mutated copies; a no-op mutation aborts as a stale
alarm, the real tree is never mutated):
  - make the early-buffer mute unconditional -> rejected;
  - add a memset of the early tap buffer to beginBlock -> rejected;
  - restore the block-constant wet/dry multiply -> rejected;
  - drop the per-sample ramp advance -> rejected;
  - snap or re-arm the ramp when the next block repeats the target -> rejected;
  - benign comment edit naming the pinned members -> accepted.

Exit 0 = ok, 1 = violation with a cited diagnostic, 2 = setup/read failure.
"""
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SRC = ROOT / "source" / "DrippyFX" / "dsp" / "CorvusEffects.h"


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
    match = re.search(r"\bstruct\s+" + re.escape(name) + r"\b[^;{]*\{",
                      code)
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


class Reject(Exception):
    pass


def require(body, pattern, why):
    if re.search(pattern, body, flags=re.S) is None:
        raise Reject(why)


def verify(header_text):
    code = strip_comments(header_text)
    reverb = struct_body(code, "UpgradedReverb")
    if reverb is None:
        raise Reject("struct UpgradedReverb not found / brace-matched")

    begins = function_bodies(
        reverb, r"void\s+beginBlock\s*\(\s*float\s+roomSize\s*,")
    if not begins:
        raise Reject("UpgradedReverb::beginBlock body not found")
    begin = begins[0]

    samples = function_bodies(
        reverb,
        r"void\s+processSample\s*\(\s*float\s+inL\s*,\s*float\s*inR\s*,"
        r"\s*float\s*&\s*outL")
    if not samples:
        raise Reject("UpgradedReverb::processSample body not found")
    sample = samples[0]

    prepares = function_bodies(reverb, r"void\s+prepare\s*\(\s*double\s+sr\s*\)")
    if not prepares:
        raise Reject("UpgradedReverb::prepare body not found")
    prepare = prepares[-1]

    coeffs = struct_body(reverb, "BlockCoeffs")
    if coeffs is None:
        raise Reject("UpgradedReverb::BlockCoeffs struct not found")

    if len(begin) < 400 or len(sample) < 400:
        raise Reject("brace matching drifted (beginBlock %d chars, "
                     "processSample %d chars) - do not trust green"
                     % (len(begin), len(sample)))

    # --- (a) early-buffer clearing is guarded, not per block ---------------
    if re.search(r"\bmemset\b", begin):
        raise Reject("beginBlock calls memset - the early-reflection/tap "
                     "buffers must only be cleared on an actual room-size "
                     "change, never every block")
    mutes = re.findall(r"\bearly[LR]\s*\.\s*mute\s*\(\s*\)", begin)
    if len(mutes) != 2:
        raise Reject("beginBlock must mute earlyL and earlyR exactly once "
                     "(found %d mute() calls) - unconditional or missing "
                     "clears both lose the early field" % len(mutes))
    guard_match = re.search(
        r"if\s*\(\s*roomSizeRate\s*>\s*ROOM_SIZE_RATE_LIMIT\s*\)\s*\{",
        begin)
    if guard_match is None:
        raise Reject("beginBlock no longer guards the early-buffer mute "
                     "behind the `roomSizeRate > ROOM_SIZE_RATE_LIMIT` rate "
                     "test - every block would clear the early taps again")
    guard = brace_body(begin, guard_match.end() - 1)
    if guard is None:
        raise Reject("room-size guard body not brace-matched")
    for needle, label in (("earlyL.mute();", "earlyL.mute()"),
                          ("earlyR.mute();", "earlyR.mute()")):
        if needle not in guard:
            raise Reject("%s must sit inside the room-size rate guard"
                         % label)
    require(begin, r"lastRoomSize\s*=\s*roomSize\s*;",
            "beginBlock never updates lastRoomSize - the guard would mute on "
            "every block")
    if begin.count("lastRoomSize = roomSize;") != 1:
        raise Reject("lastRoomSize = roomSize occurs %d times in beginBlock; "
                     "it must be tracked exactly once per block"
                     % begin.count("lastRoomSize = roomSize;"))
    if "lastRoomSize = roomSize;" in guard:
        raise Reject("lastRoomSize = roomSize sits inside the rate guard - a "
                     "smoothed move would never update the reference and could "
                     "accumulate into a late mute")

    # --- (b) the size mapping itself stays live ----------------------------
    for name in ("earlyL", "earlyR"):
        require(begin,
                r"\b%s\s*\.\s*setRoomSize\s*\(\s*roomSize\s*\)" % name,
                "%s.setRoomSize(roomSize) must still run every block - the "
                "size knob has to stay live" % name)
    require(reverb, r"\bfloat\s+lastRoomSize\s*=\s*0\.0f\s*;",
            "`float lastRoomSize = 0.0f;` declaration missing - the "
            "mute-on-change guard has nothing to compare against")

    # --- (c) equal-power targets + change-triggered ramp -------------------
    require(begin,
            r"blockCoeffs\.dryGain\s*=\s*std::cos\s*\(\s*wetMix\s*\*",
            "beginBlock no longer derives the equal-power dry target from "
            "wetMix")
    require(begin,
            r"blockCoeffs\.wetGain\s*=\s*std::sin\s*\(\s*wetMix\s*\*",
            "beginBlock no longer derives the equal-power wet target from "
            "wetMix")
    mix_update = re.search(
        r"\bif\s*\(\s*!wetMixValid\s*\)\s*\{(?P<first>[^{}]*)\}\s*"
        r"else\s+if\s*\(\s*wetMix\s*!=\s*lastWetMix\s*\)\s*"
        r"\{(?P<changed>[^{}]*)\}\s*"
        r"lastWetMix\s*=\s*wetMix\s*;\s*wetMixValid\s*=\s*true\s*;", begin)
    if mix_update is None:
        raise Reject("beginBlock must snap only on the first mix and arm only "
                     "on a changed target; a repeated target must leave the "
                     "in-flight ramp alone")
    first, changed = mix_update.group("first", "changed")
    require(changed, r"rampSamples\s*=\s*juce::jmax\s*\(\s*1\s*,",
            "beginBlock no longer derives a non-zero ramp length")
    require(changed, r"mixRampSamplesLeft\s*=\s*rampSamples\s*;",
            "beginBlock no longer arms the per-sample ramp")
    require(changed,
            r"dryGainStep\s*=\s*\(\s*blockCoeffs\.dryGain\s*-\s*"
            r"blockCoeffs\.appliedDryGain\s*\)",
            "beginBlock no longer computes the dry ramp slope")
    require(changed,
            r"wetGainStep\s*=\s*\(\s*blockCoeffs\.wetGain\s*-\s*"
            r"blockCoeffs\.appliedWetGain\s*\)",
            "beginBlock no longer computes the wet ramp slope")
    require(first, r"blockCoeffs\.appliedDryGain\s*=\s*blockCoeffs\.dryGain\s*;",
            "beginBlock no longer snaps appliedDryGain on the first mix")
    require(first, r"blockCoeffs\.appliedWetGain\s*=\s*blockCoeffs\.wetGain\s*;",
            "beginBlock no longer snaps appliedWetGain on the first mix")
    require(first, r"blockCoeffs\.mixRampSamplesLeft\s*=\s*0\s*;",
            "beginBlock must leave no ramp after snapping to the first mix")

    # --- (d) per-sample state declared + advanced before the multiply ------
    for pattern, why in (
            (r"float\s+lastWetMix\s*=\s*0\.0f\s*;",
             "`float lastWetMix = 0.0f;` member missing"),
            (r"bool\s+wetMixValid\s*=\s*false\s*;",
             "`bool wetMixValid = false;` member missing"),
            (r"static\s+constexpr\s+float\s+MIX_RAMP_SECONDS\s*="
             r"\s*0\.0[0-9]+f\s*;",
             "MIX_RAMP_SECONDS constant missing - the applied wet/dry has no "
             "defined ramp length")):
        require(reverb, pattern, why)
    for pattern, why in (
            (r"float\s+appliedDryGain\s*=\s*1\.0f\s*;",
             "BlockCoeffs::appliedDryGain missing"),
            (r"float\s+appliedWetGain\s*=\s*0\.0f\s*;",
             "BlockCoeffs::appliedWetGain missing"),
            (r"float\s+dryGainStep\s*=", "BlockCoeffs::dryGainStep missing"),
            (r"float\s+wetGainStep\s*=", "BlockCoeffs::wetGainStep missing"),
            (r"int\s+mixRampSamplesLeft\s*=\s*0\s*;",
             "BlockCoeffs::mixRampSamplesLeft missing")):
        require(coeffs, pattern, why)

    if re.search(r"in[LR]\s*\*\s*blockCoeffs\.dryGain\b", sample):
        raise Reject("processSample still multiplies the block-constant "
                     "dryGain into the output - the wet/dry steps per block "
                     "instead of following the mix ramp")
    if re.search(r"rev[LR]\s*\*\s*blockCoeffs\.wetGain\b", sample):
        raise Reject("processSample still multiplies the block-constant "
                     "wetGain into the output - the wet/dry steps per block")
    require(sample,
            r"if\s*\(\s*blockCoeffs\.mixRampSamplesLeft\s*>\s*0\s*\)",
            "processSample no longer runs the armed ramp")
    require(sample,
            r"blockCoeffs\.appliedDryGain\s*\+=\s*blockCoeffs\.dryGainStep\s*;",
            "processSample no longer advances appliedDryGain per sample")
    require(sample,
            r"blockCoeffs\.appliedWetGain\s*\+=\s*blockCoeffs\.wetGainStep\s*;",
            "processSample no longer advances appliedWetGain per sample")
    require(sample,
            r"blockCoeffs\.appliedDryGain\s*=\s*blockCoeffs\.dryGain\s*;",
            "processSample no longer lands appliedDryGain exactly")
    require(sample,
            r"blockCoeffs\.appliedWetGain\s*=\s*blockCoeffs\.wetGain\s*;",
            "processSample no longer lands appliedWetGain exactly")
    out_l = re.search(
        r"outL\s*=\s*inL\s*\*\s*blockCoeffs\.appliedDryGain\s*\+\s*"
        r"revL\s*\*\s*blockCoeffs\.appliedWetGain\s*;", sample)
    out_r = re.search(
        r"outR\s*=\s*inR\s*\*\s*blockCoeffs\.appliedDryGain\s*\+\s*"
        r"revR\s*\*\s*blockCoeffs\.appliedWetGain\s*;", sample)
    if out_l is None or out_r is None:
        raise Reject("processSample no longer applies the ramped gains "
                     "(out = in * appliedDryGain + rev * appliedWetGain)")
    advance = sample.find("blockCoeffs.appliedDryGain +=")
    if advance == -1 or advance > out_l.start():
        raise Reject("processSample applies the output before advancing the "
                     "ramp - the first sample of every block would use the "
                     "previous block's balance")

    # --- (e) prepare resets the ramp --------------------------------------
    for pattern, why in (
            (r"wetMixValid\s*=\s*false\s*;",
             "prepare() no longer invalidates the mix state"),
            (r"mixRampSamplesLeft\s*=\s*0\s*;",
             "prepare() no longer clears the armed ramp"),
            (r"appliedDryGain\s*=\s*1\.0f\s*;",
             "prepare() no longer resets appliedDryGain to dry-only"),
            (r"appliedWetGain\s*=\s*0\.0f\s*;",
             "prepare() no longer resets appliedWetGain to dry-only"),
            (r"lastWetMix\s*=\s*0\.0f\s*;",
             "prepare() no longer resets lastWetMix")):
        require(prepare, pattern, why)

    # --- (f) no buffer clearing on the per-sample path --------------------
    if "mute" in sample or "memset" in sample:
        raise Reject("processSample must not mute/memset any buffer")


def run(header_text):
    try:
        verify(header_text)
    except Reject as exc:
        return str(exc)
    return None


def main():
    if not SRC.exists():
        print("REVERB-ROOM-RAMP SETUP FAIL: missing %s" % SRC)
        return 2
    try:
        text = SRC.read_text(encoding="utf-8", errors="replace")
    except OSError as exc:
        print("REVERB-ROOM-RAMP SETUP FAIL: %s" % exc)
        return 2

    verdict = run(text)
    if verdict is not None:
        print("REVERB-ROOM-RAMP FAIL: %s" % verdict)
        return 1
    print("reverb-room-ramp: early taps are muted only on a room-size change, "
          "and the applied wet/dry ramps per sample toward its mix target")

    # Negative probes: every mutation reintroduces a reported defect shape.
    probes = [
        ("make the early-buffer mute unconditional",
         lambda s: s.replace(
             "if (roomSizeRate > ROOM_SIZE_RATE_LIMIT)",
             "if (true)", 1)),
        ("add a memset of the early tap buffer to beginBlock",
         lambda s: s.replace(
             "earlyL.setRoomSize(roomSize);",
             "std::memset(earlyL.buf, 0, sizeof(earlyL.buf));\n"
             "                earlyL.setRoomSize(roomSize);", 1)),
        ("restore the block-constant wet/dry multiply",
         lambda s: s.replace(
             "outL = inL * blockCoeffs.appliedDryGain + revL * "
             "blockCoeffs.appliedWetGain;",
             "outL = inL * blockCoeffs.dryGain + revL * "
             "blockCoeffs.wetGain;", 1).replace(
             "outR = inR * blockCoeffs.appliedDryGain + revR * "
             "blockCoeffs.appliedWetGain;",
             "outR = inR * blockCoeffs.dryGain + revR * "
             "blockCoeffs.wetGain;", 1)),
        ("drop the per-sample ramp advance",
         lambda s: s.replace(
             "if (blockCoeffs.mixRampSamplesLeft > 0)",
             "if (false)", 1)),
        ("snap on a repeated mix target",
         lambda s: s.replace(
             "if (!wetMixValid)", "if (!wetMixValid || wetMix == lastWetMix)", 1)),
        ("restart the ramp on a repeated mix target",
         lambda s: s.replace("else if (wetMix != lastWetMix)", "else", 1)),
    ]
    for label, mutate in probes:
        mutated = mutate(text)
        if mutated == text:
            print("REVERB-ROOM-RAMP FAIL: probe '%s' is stale: mutation did "
                  "not apply - cannot trust the negative check" % label)
            return 1
        verdict = run(mutated)
        if verdict is None:
            print("REVERB-ROOM-RAMP FAIL: probe '%s' was NOT rejected - "
                  "checker is vacuous" % label)
            return 1
        print("reverb-room-ramp: probe '%s' rejected (%s)"
              % (label, verdict[:88]))

    # Specificity: a comment that names the pinned members must not trip it.
    neutral = text.replace(
        "    float lastRoomSize = 0.0f;",
        "    // A comment naming earlyL.mute(), lastRoomSize, appliedDryGain,\n"
        "    // dryGain/wetGain and mixRampSamplesLeft is not code.\n"
        "    float lastRoomSize = 0.0f;", 1)
    if neutral == text:
        print("REVERB-ROOM-RAMP FAIL: benign comment probe is stale: the "
              "edit did not apply")
        return 1
    verdict = run(neutral)
    if verdict is not None:
        print("REVERB-ROOM-RAMP FAIL: benign comment edit was rejected - "
              "checker over-fires: %s" % verdict)
        return 1
    print("reverb-room-ramp: benign comment edit accepted (probe specificity "
          "proven)")

    if run(SRC.read_text(encoding="utf-8", errors="replace")) is not None:
        print("REVERB-ROOM-RAMP FAIL: final live-source re-verification failed")
        return 1
    print(f"REVERB-ROOM-RAMP OK ({len(probes)} negatives, comment edit accepted)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
