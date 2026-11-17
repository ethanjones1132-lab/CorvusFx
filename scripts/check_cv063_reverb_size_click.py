#!/usr/bin/env python3
"""Headless checker: reverb Size travel must not restart the early field (CV-063).

Defect: `UpgradedReverb::beginBlock()` re-seeded the early-reflection tap
buffers whenever the block's room size differed from the previous block's by
more than 1e-4. The size knob is smoothed over 20 ms upstream, but beginBlock()
only samples that ramp once per block, so any knob travel or automation ramp
moves the block value by far more than 1e-4 every block. The early field was
therefore memset + restarted at block rate (60-100 times a second) for as long
as the knob kept moving: audible as silence/gating while travelling.

Fix: the re-seed is now a RATE test over the previous block's rendered time.
The size knob reaches beginBlock() through a 20 ms LinearSmoothedValue in
PluginProcessor, so even an instant preset load or automation step cannot move
roomSize faster than 1.0 / 0.020 s = 50 range-units per second.
ROOM_SIZE_RATE_LIMIT (60/s, 20% headroom) cannot fire while the parameter is
travelling: the taps are re-derived in place every block and the early field
keeps running. Only a raw (un-smoothed) jump faster than any smoother can
produce still clears the tap buffers.

Asserts on the real tree (comment-stripped, brace-matched UpgradedReverb):
  (a) beginBlock() contains no memset and exactly two early mute() calls, both
      inside the `roomSizeRate > ROOM_SIZE_RATE_LIMIT` branch;
  (b) the guard really is a per-second rate: gated on lastBlockSamples > 0,
      blockSeconds = lastBlockSamples / sampleRate, roomSizeRate =
      fabs(roomSize - lastRoomSize) / max(blockSeconds, ...), compared with >;
  (c) lastRoomSize and lastBlockSamples are advanced/reset every block OUTSIDE
      the guard (a slow move must never accumulate into a late mute);
  (d) ROOM_SIZE_RATE_LIMIT is declared and sits above the 50/s ceiling of the
      20 ms smoother (so travel can never trip it) but stays a real limit, and
      PluginProcessor still feeds reverb_size through that 20 ms smoother;
  (e) processSample() counts the rendered samples, once per sample, and still
      contains no mute()/memset;
  (f) both early tap sets are re-derived every block (setRoomSize outside the
      guard), and prepare() still clears the taps for a fresh instance.

Negative probes (in-memory mutated copies; a no-op mutation aborts as a stale
alarm, the real tree is never mutated):
  - make the early-buffer mute unconditional -> rejected;
  - restore the raw per-block `> 1e-4f` change test -> rejected;
  - remove the jump re-seed entirely (never clear after a real jump) ->
    rejected;
  - delete the tap clear from the jump branch (never clear after a real jump)
    -> rejected;
  - lower ROOM_SIZE_RATE_LIMIT into ordinary travel -> rejected;
  - stop counting the rendered samples -> rejected;
  - benign comment edit naming the pinned members -> accepted.

Exit 0 = ok, 1 = violation with a cited diagnostic, 2 = setup/read failure.
"""
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SRC = ROOT / "source" / "DrippyFX" / "dsp" / "CorvusEffects.h"

# A 20 ms LinearSmoothedValue can move a 0..1 parameter no faster than
# 1.0 / 0.020 s = 50 range-units per second. The guard's limit must sit above
# that ceiling (travel can never trip it) but must stay a meaningful jump
# bound instead of a value that disables the re-seed path entirely.
SMOOTHER_CEILING = 50.0
RATE_LIMIT_MAX = 200.0


def strip_comments(src):
    src = re.sub(r"/\*.*?\*/", "", src, flags=re.S)
    src = re.sub(r"//[^\n]*", "", src)
    return src


def brace_span(code, open_idx):
    depth = 0
    for i in range(open_idx, len(code)):
        if code[i] == "{":
            depth += 1
        elif code[i] == "}":
            depth -= 1
            if depth == 0:
                return open_idx + 1, i
    return None, None


def brace_body(code, open_idx):
    start, end = brace_span(code, open_idx)
    if start is None:
        return None
    return code[start:end]


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

    if len(begin) < 400 or len(sample) < 400:
        raise Reject("brace matching drifted (beginBlock %d chars, "
                     "processSample %d chars) - do not trust green"
                     % (len(begin), len(sample)))

    # --- (a) the per-block path must not clear the early buffers -----------
    if re.search(r"\bmemset\b", begin):
        raise Reject("beginBlock calls memset - the early-reflection buffers "
                     "must only be cleared on a genuinely discontinuous size "
                     "jump, never every block")
    mutes = re.findall(r"\bearly[LR]\s*\.\s*mute\s*\(\s*\)", begin)
    if len(mutes) != 2:
        raise Reject("beginBlock must mute earlyL and earlyR exactly once "
                     "(found %d mute() calls) - an unguarded or missing clear "
                     "either silences the travelling field or keeps stale taps"
                     % len(mutes))

    guard_match = re.search(
        r"if\s*\(\s*roomSizeRate\s*>\s*ROOM_SIZE_RATE_LIMIT\s*\)\s*\{", begin)
    if guard_match is None:
        raise Reject("beginBlock no longer gates the early-tap re-seed on "
                     "`roomSizeRate > ROOM_SIZE_RATE_LIMIT` - a plain delta "
                     "test mutes on every smoothed knob step")
    gstart, gend = brace_span(begin, guard_match.end() - 1)
    if gstart is None:
        raise Reject("room-size rate guard body not brace-matched")
    guard = begin[gstart:gend]
    for needle, label in (("earlyL.mute();", "earlyL.mute()"),
                          ("earlyR.mute();", "earlyR.mute()")):
        if needle not in guard:
            raise Reject("%s must sit inside the room-size rate guard"
                         % label)
    if "setRoomSize" in guard:
        raise Reject("setRoomSize() sits inside the jump guard - the tap "
                     "delays must be re-derived every block while travelling")
    if re.search(r"lastRoomSize\s*=", guard):
        raise Reject("lastRoomSize is only updated inside the guard - a "
                     "smoothed move would never advance the reference")

    # --- (b) the guard is a per-second rate over the rendered block time ---
    require(begin, r"if\s*\(\s*lastBlockSamples\s*>\s*0\s*\)",
            "beginBlock no longer gates the rate test on lastBlockSamples > 0 "
            "- the block duration is unknown and the rate is meaningless")
    require(begin,
            r"const\s+float\s+blockSeconds\s*=\s*static_cast<float>\s*\(\s*"
            r"lastBlockSamples\s*\)\s*/\s*static_cast<float>\s*\(\s*"
            r"sampleRate\s*\)\s*;",
            "beginBlock no longer derives blockSeconds from lastBlockSamples "
            "and sampleRate - a raw per-block delta is block-size dependent")
    require(begin,
            r"const\s+float\s+roomSizeRate\s*=\s*std::fabs\s*\(\s*roomSize"
            r"\s*-\s*lastRoomSize\s*\)\s*/\s*juce::jmax\s*\(\s*blockSeconds"
            r"\s*,",
            "beginBlock no longer divides the room-size delta by blockSeconds "
            "- the guard must test a rate, not a block-sized delta")
    rate_at = begin.find("roomSizeRate =")
    if rate_at == -1 or rate_at > guard_match.start():
        raise Reject("the room-size rate is computed after the guard that "
                     "uses it - the comparison would read stale/zero state")

    # --- (c) reference + counter advance every block, outside the guard ----
    require(begin, r"lastRoomSize\s*=\s*roomSize\s*;",
            "beginBlock never updates lastRoomSize - the guard would compare "
            "against a stale reference for the whole block")
    if begin.count("lastRoomSize = roomSize;") != 1:
        raise Reject("lastRoomSize = roomSize occurs %d times in beginBlock; "
                     "it must be tracked exactly once per block"
                     % begin.count("lastRoomSize = roomSize;"))
    assign_at = begin.find("lastRoomSize = roomSize;")
    if assign_at < gend:
        raise Reject("lastRoomSize = roomSize runs inside the rate guard - "
                     "smoothed travel would accumulate into a late mute")
    require(begin, r"lastBlockSamples\s*=\s*0\s*;",
            "beginBlock never resets lastBlockSamples - the next block would "
            "measure a longer, slower interval and could miss a real jump")
    if begin.count("lastBlockSamples = 0;") != 1:
        raise Reject("lastBlockSamples = 0 occurs %d times in beginBlock; it "
                     "must be reset exactly once per block"
                     % begin.count("lastBlockSamples = 0;"))
    reset_at = begin.find("lastBlockSamples = 0;")
    if reset_at < gend:
        raise Reject("lastBlockSamples = 0 runs inside the rate guard - only "
                     "the jump branch would reset it")

    # --- (d) the threshold clears the smoother's travel ceiling ------------
    limit_match = re.search(
        r"static\s+constexpr\s+float\s+ROOM_SIZE_RATE_LIMIT\s*=\s*"
        r"([0-9]+(?:\.[0-9]*)?)f\s*;", reverb)
    if limit_match is None:
        raise Reject("ROOM_SIZE_RATE_LIMIT constant missing - the guard has no "
                     "defined jump threshold")
    limit = float(limit_match.group(1))
    if not (SMOOTHER_CEILING < limit <= RATE_LIMIT_MAX):
        raise Reject("ROOM_SIZE_RATE_LIMIT is %gf; it must stay above the "
                     "%.0f/s ceiling of the 20 ms size smoother (or a travelling "
                     "knob mutes) and at most %.0f/s (or a real jump never "
                     "re-seeds)" % (limit, SMOOTHER_CEILING, RATE_LIMIT_MAX))
    for pattern, why in (
            (r"\bfloat\s+lastRoomSize\s*=\s*0\.0f\s*;",
             "`float lastRoomSize = 0.0f;` member missing"),
            (r"\bint\s+lastBlockSamples\s*=\s*0\s*;",
             "`int lastBlockSamples = 0;` member missing")):
        require(reverb, pattern, why)

    # --- (d2) the upstream 20 ms smoother keeps the travel ceiling at 50/s --
    proc_path = ROOT / "source" / "DrippyFX" / "PluginProcessor.cpp"
    try:
        proc_text = strip_comments(
            proc_path.read_text(encoding="utf-8", errors="replace"))
    except OSError as exc:
        raise Reject("cannot read %s for the smoother anchor: %s"
                     % (proc_path, exc))
    require(proc_text, r"const\s+double\s+smoothTime\s*=\s*0\.02\s*;",
            "PluginProcessor's `const double smoothTime = 0.02;` is gone - the "
            "ROOM_SIZE_RATE_LIMIT headroom above the 50/s travel ceiling was "
            "derived from that 20 ms ramp")
    require(proc_text,
            r"smoothReverbSize\.reset\s*\(\s*sampleRate\s*,\s*smoothTime\s*\)",
            "smoothReverbSize no longer uses the shared 20 ms smoother - a "
            "faster ramp could exceed ROOM_SIZE_RATE_LIMIT and mute mid-travel")

    # --- (e) the counter advances per rendered sample, no clears there -----
    if re.search(r"\bearly[LR]\s*\.\s*mute\s*\(", sample):
        raise Reject("processSample mutes the early taps - the re-seed belongs "
                     "to the block-rate jump guard only")
    if re.search(r"\bmemset\b", sample):
        raise Reject("processSample memsets a buffer - the early field would "
                     "be cleared inside the audio block")
    if (re.search(r"\+\+\s*lastBlockSamples\b", sample) is None
            and re.search(r"\blastBlockSamples\s*\+\+", sample) is None):
        raise Reject("processSample no longer counts the rendered samples - "
                     "beginBlock cannot turn the size delta into a rate")

    # --- (f) the size mapping stays live and prepare still clears ----------
    for name in ("earlyL", "earlyR"):
        require(begin,
                r"\b%s\s*\.\s*setRoomSize\s*\(\s*roomSize\s*\)" % name,
                "%s.setRoomSize(roomSize) must still run every block - the "
                "taps have to be re-derived while the knob travels" % name)
        require(prepare, r"\b%s\s*\.\s*mute\s*\(\s*\)" % name,
                "%s is no longer cleared in prepare() - a fresh instance could "
                "start on stale tap history" % name)


def run(header_text):
    try:
        verify(header_text)
    except Reject as exc:
        return str(exc)
    return None


def _replace_once(txt, old, new):
    if old not in txt:
        return txt
    return txt.replace(old, new, 1)


def main():
    if not SRC.exists():
        print("REVERB-SIZE-CLICK SETUP FAIL: missing %s" % SRC)
        return 2
    try:
        text = SRC.read_text(encoding="utf-8", errors="replace")
    except OSError as exc:
        print("REVERB-SIZE-CLICK SETUP FAIL: %s" % exc)
        return 2

    verdict = run(text)
    if verdict is not None:
        print("REVERB-SIZE-CLICK FAIL: %s" % verdict)
        return 1
    print("reverb-size-click: early taps are re-seeded only by the "
          "room-size rate guard; smoothed Size travel never mutes them")

    # Negative probes: every mutation reintroduces a reported defect shape.
    probes = [
        ("make the early-buffer mute unconditional",
         lambda s: _replace_once(
             s, "if (roomSizeRate > ROOM_SIZE_RATE_LIMIT)", "if (true)")),
        ("restore the raw per-block `> 1e-4f` change test",
         lambda s: _replace_once(
             s, "if (roomSizeRate > ROOM_SIZE_RATE_LIMIT)",
             "if (std::fabs(roomSize - lastRoomSize) > 1e-4f)")),
        ("remove the jump re-seed entirely (never clear after a real jump)",
         lambda s: _replace_once(
             s, "if (roomSizeRate > ROOM_SIZE_RATE_LIMIT)", "if (false)")),
        ("delete the tap clear from the jump branch (never clear after a jump)",
         lambda s: _replace_once(s, "earlyL.mute();", "").replace(
             "earlyR.mute();", "", 1)),
        ("lower ROOM_SIZE_RATE_LIMIT into ordinary knob travel",
         lambda s: _replace_once(
             s, "static constexpr float ROOM_SIZE_RATE_LIMIT = 60.0f;",
             "static constexpr float ROOM_SIZE_RATE_LIMIT = 10.0f;")),
        ("stop counting the rendered samples",
         lambda s: _replace_once(s, "        ++lastBlockSamples;\n", "")),
    ]
    for label, mutate in probes:
        mutated = mutate(text)
        if mutated == text:
            print("REVERB-SIZE-CLICK FAIL: probe '%s' is stale: mutation did "
                  "not apply - cannot trust the negative check" % label)
            return 1
        verdict = run(mutated)
        if verdict is None:
            print("REVERB-SIZE-CLICK FAIL: probe '%s' was NOT rejected - "
                  "checker is vacuous" % label)
            return 1
        print("reverb-size-click: probe '%s' rejected (%s)"
              % (label, verdict[:88]))

    # Specificity: a comment that names the pinned members must not trip it.
    neutral = text.replace(
        "    float lastRoomSize = 0.0f;",
        "    // A comment naming earlyL.mute(), earlyR.mute(), lastRoomSize,\n"
        "    // lastBlockSamples, ROOM_SIZE_RATE_LIMIT, roomSizeRate and\n"
        "    // setRoomSize(roomSize) is prose, not code.\n"
        "    float lastRoomSize = 0.0f;", 1)
    if neutral == text:
        print("REVERB-SIZE-CLICK FAIL: benign comment probe is stale: the "
              "edit did not apply")
        return 1
    verdict = run(neutral)
    if verdict is not None:
        print("REVERB-SIZE-CLICK FAIL: benign comment edit was rejected - "
              "checker over-fires: %s" % verdict)
        return 1
    print("reverb-size-click: benign comment edit accepted (probe specificity "
          "proven)")

    if run(SRC.read_text(encoding="utf-8", errors="replace")) is not None:
        print("REVERB-SIZE-CLICK FAIL: final live-source re-verification failed")
        return 1
    print("REVERB-SIZE-CLICK OK (6 negatives, comment edit accepted)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
