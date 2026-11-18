#!/usr/bin/env python3
"""Headless checker: a reverb Size jump made while the module is silent still
re-seeds the early field on the first audible block (CV-071).

Defect: `UpgradedReverb::beginBlock()` advanced the "value just applied"
baseline (`lastRoomSize`) on every block, including blocks that rendered no
audio at all. The reverb is silent whenever its bypass crossfade or its mix
sits at zero, and then `processSample()` never runs, so `lastBlockSamples`
stays 0 and the tap history does not move. Advancing the baseline in that
window recorded a Size jump as "already applied": when the module re-engaged,
the first audible block compared roomSize against that same new value,
measured a zero rate, and the early taps kept reading history written for the
old room. The jump only re-seeded if the user happened to move Size again
after the audio came back.

Fix: the baseline now advances only inside the `lastBlockSamples > 0` gate,
so a silent block leaves it untouched and the next rendered block still sees
the jump and mutes. The rate test stays a one-block rate over rendered time -
never an accumulator - so a slow move keeps the baseline current every block
and cannot mute late. A new `roomSizeValid` flag keeps the first audible
block after `prepare()` from reading the initial `lastRoomSize` (0) as a
jump: `prepare()` clears it, only a rendered block sets it, and a block with
no measured baseline computes a zero rate.

Asserts on the real tree (comment-stripped, brace-matched UpgradedReverb):
  (a) beginBlock() gates the size handling on `lastBlockSamples > 0`, advances
      `lastRoomSize = roomSize;` exactly once and only INSIDE that gate, still
      resets `lastBlockSamples = 0;` every block outside it, and still
      re-derives both early tap sets every block (`setRoomSize` outside);
  (b) the room-size rate is computed before the `roomSizeRate >
      ROOM_SIZE_RATE_LIMIT` comparison and only against a baseline a rendered
      block established (`roomSizeValid`), so a size that never moved never
      mutes; the no-baseline branch measures a zero rate;
  (c) `roomSizeValid` is declared false on the struct, set true only inside
      the rendered-block gate, and cleared again by prepare();
  (d) the jump guard itself still mutes earlyL and earlyR only inside the
      rate branch - a jump made while silent still clears the taps.

Negative probes (in-memory mutated copies; a no-op mutation aborts as a stale
alarm, the real tree is never mutated):
  - advance the baseline on silent blocks too (the reported defect) -> rejected;
  - test the rate without an established baseline (mute the first audible
    block) -> rejected;
  - keep the baseline valid across prepare() -> rejected;
  - make the early-buffer mute unconditional -> rejected;
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


GATE = r"if\s*\(\s*lastBlockSamples\s*>\s*0\s*\)\s*\{"
GUARD = r"if\s*\(\s*roomSizeRate\s*>\s*ROOM_SIZE_RATE_LIMIT\s*\)\s*\{"
ASSIGN = "lastRoomSize = roomSize;"
RESET = "lastBlockSamples = 0;"


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

    prepares = function_bodies(
        reverb, r"void\s+prepare\s*\(\s*double\s+sr\s*\)")
    if not prepares:
        raise Reject("UpgradedReverb::prepare body not found")
    prepare = prepares[-1]

    if len(begin) < 400 or len(sample) < 400:
        raise Reject("brace matching drifted (beginBlock %d chars, "
                     "processSample %d chars) - do not trust green"
                     % (len(begin), len(sample)))

    # --- (a) only a block that rendered audio advances the baseline -------
    gate_match = re.search(GATE, begin)
    if gate_match is None:
        raise Reject("beginBlock no longer gates the size handling on "
                     "`lastBlockSamples > 0` - a block that rendered nothing "
                     "(reverb bypassed or mix at zero, so processSample() "
                     "never ran) would still swallow a size jump made while "
                     "silent")
    gate_start, gate_end = brace_span(begin, gate_match.end() - 1)
    if gate_start is None:
        raise Reject("rendered-block gate body not brace-matched")
    rendered = begin[gate_start:gate_end]

    if begin.count(ASSIGN) != 1:
        raise Reject("lastRoomSize = roomSize occurs %d times in beginBlock; "
                     "it must be advanced exactly once, by the block that "
                     "rendered audio" % begin.count(ASSIGN))
    assign_at = begin.find(ASSIGN)
    if not (gate_start <= assign_at < gate_end):
        raise Reject("lastRoomSize = roomSize runs outside the "
                     "`lastBlockSamples > 0` gate - a silent block would move "
                     "the baseline and the first audible block after the jump "
                     "would compare the new size against itself and never "
                     "re-seed the early taps")
    if begin.count(RESET) != 1:
        raise Reject("lastBlockSamples = 0 occurs %d times in beginBlock; it "
                     "must be reset exactly once, every block"
                     % begin.count(RESET))
    reset_at = begin.find(RESET)
    if reset_at < gate_end:
        raise Reject("lastBlockSamples = 0 runs inside the rendered-block gate "
                     "- only a block that rendered would reset the counter and "
                     "the next block would measure a longer, slower interval")

    # The tap delays must still follow the block's size even when silent.
    for name in ("earlyL", "earlyR"):
        at = begin.find("%s.setRoomSize(roomSize);" % name)
        if at == -1:
            raise Reject("%s.setRoomSize(roomSize) missing - the taps are no "
                         "longer re-derived for the block's room size" % name)
        if gate_start <= at < gate_end:
            raise Reject("%s.setRoomSize(roomSize) sits inside the "
                         "rendered-block gate - a silent block would leave the "
                         "tap delays on the old room" % name)

    # --- (b) the rate is only measured against an established baseline ----
    guard_match = re.search(GUARD, begin)
    if guard_match is None:
        raise Reject("beginBlock no longer gates the early-tap re-seed on "
                     "`roomSizeRate > ROOM_SIZE_RATE_LIMIT`")
    rate_at = begin.find("roomSizeRate =")
    if rate_at == -1 or rate_at > guard_match.start():
        raise Reject("the room-size rate is computed after the comparison "
                     "that uses it - the guard would read stale/zero state")
    if "roomSizeValid" not in begin[rate_at:guard_match.start()]:
        raise Reject("the room-size rate is not gated on roomSizeValid - the "
                     "first audible block after prepare() would read the "
                     "initial lastRoomSize (0) as a jump and mute a size that "
                     "never moved")
    if re.search(r":\s*0\.0f\s*;", rendered) is None:
        raise Reject("a block without an established baseline no longer "
                     "measures a zero rate - the first audible block after "
                     "prepare() would mute a size that never moved")

    # --- (c) the baseline validity flag lifecycle -------------------------
    for pattern, why in (
            (r"\bfloat\s+lastRoomSize\s*=\s*0\.0f\s*;",
             "`float lastRoomSize = 0.0f;` member missing"),
            (r"\bbool\s+roomSizeValid\s*=\s*false\s*;",
             "`bool roomSizeValid = false;` member missing - the rate test "
             "cannot tell a measured baseline from the initial 0")):
        require(reverb, pattern, why)
    require(rendered, r"roomSizeValid\s*=\s*true\s*;",
            "the rendered-block gate no longer marks roomSizeValid - every "
            "later block would be measured against an unmeasured baseline")
    require(prepare, r"roomSizeValid\s*=\s*false\s*;",
            "prepare() no longer clears roomSizeValid - a fresh session would "
            "compare a jump against the previous session's baseline")
    if re.search(r"roomSizeValid\s*=\s*true\s*;", begin[gate_end:]) is not None:
        raise Reject("roomSizeValid is set true outside the rendered-block "
                     "gate - a silent block would claim a baseline it never "
                     "measured")

    # --- (d) a silent jump still clears the early taps --------------------
    gstart, gend = brace_span(begin, guard_match.end() - 1)
    if gstart is None:
        raise Reject("room-size rate guard body not brace-matched")
    guard = begin[gstart:gend]
    for name in ("earlyL", "earlyR"):
        if "%s.mute();" % name not in guard:
            raise Reject("%s.mute() is not inside the room-size rate guard - "
                         "a jump made while the reverb was silent would never "
                         "clear the stale taps" % name)


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
        print("SILENT-SIZE-JUMP SETUP FAIL: missing %s" % SRC)
        return 2
    try:
        text = SRC.read_text(encoding="utf-8", errors="replace")
    except OSError as exc:
        print("SILENT-SIZE-JUMP SETUP FAIL: %s" % exc)
        return 2

    verdict = run(text)
    if verdict is not None:
        print("SILENT-SIZE-JUMP FAIL: %s" % verdict)
        return 1
    print("silent-size-jump: the room-size baseline advances only on a block "
          "that rendered audio, so a jump made while silent still re-seeds the "
          "early field on the first audible block")

    # Negative probes: every mutation reintroduces a reported defect shape.
    probes = [
        ("advance the baseline on silent blocks too",
         lambda s: _replace_once(
             s,
             "            lastRoomSize = roomSize;\n"
             "            roomSizeValid = true;\n"
             "        }",
             "        }\n"
             "        lastRoomSize = roomSize;\n"
             "        roomSizeValid = true;")),
        ("test the rate without an established baseline",
         lambda s: _replace_once(
             s,
             "const float roomSizeRate = roomSizeValid\n"
             "                ? std::fabs(roomSize - lastRoomSize)",
             "const float roomSizeRate = std::fabs(roomSize - lastRoomSize)")),
        ("keep the baseline valid across prepare()",
         lambda s: _replace_once(s, "        roomSizeValid = false;\n", "")),
        ("make the early-buffer mute unconditional",
         lambda s: _replace_once(
             s, "if (roomSizeRate > ROOM_SIZE_RATE_LIMIT)", "if (true)")),
    ]
    for label, mutate in probes:
        mutated = mutate(text)
        if mutated == text:
            print("SILENT-SIZE-JUMP FAIL: probe '%s' is stale: mutation did "
                  "not apply - cannot trust the negative check" % label)
            return 1
        verdict = run(mutated)
        if verdict is None:
            print("SILENT-SIZE-JUMP FAIL: probe '%s' was NOT rejected - "
                  "checker is vacuous" % label)
            return 1
        print("silent-size-jump: probe '%s' rejected (%s)"
              % (label, verdict[:88]))

    # Specificity: a comment that names the pinned members must not trip it.
    neutral = text.replace(
        "    float lastRoomSize = 0.0f;",
        "    // A comment naming lastRoomSize, lastBlockSamples, roomSizeValid,\n"
        "    // roomSizeRate, ROOM_SIZE_RATE_LIMIT, processSample() and\n"
        "    // earlyL.setRoomSize(roomSize) is prose, not code.\n"
        "    float lastRoomSize = 0.0f;", 1)
    if neutral == text:
        print("SILENT-SIZE-JUMP FAIL: benign comment probe is stale: the edit "
              "did not apply")
        return 1
    verdict = run(neutral)
    if verdict is not None:
        print("SILENT-SIZE-JUMP FAIL: benign comment edit was rejected - "
              "checker over-fires: %s" % verdict)
        return 1
    print("silent-size-jump: benign comment edit accepted (probe specificity "
          "proven)")

    if run(SRC.read_text(encoding="utf-8", errors="replace")) is not None:
        print("SILENT-SIZE-JUMP FAIL: final live-source re-verification failed")
        return 1
    print("SILENT-SIZE-JUMP OK (4 negatives, comment edit accepted)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
