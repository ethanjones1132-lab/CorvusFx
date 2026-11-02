#!/usr/bin/env python3
"""Headless checker: Master Drive is a saturation amount, unity at 0 (CV-035).

The shipped master stage fed `drive` straight into the push-pull shaper, so
drive 0 computed `d = x * 0 = 0` and returned 0 for every sample. With the
defaults (master_drive/master_mid_drive/master_side_drive all 0, master bypass
off) the stage ran and muted the signal; any combined drive below 1 was a
plain gain cut rather than less saturation.

`MasterOutputStage::pushPullSaturate` now keeps the existing asymmetric shape
and internal gain (k = drive) but blends it against the dry signal:

    amount = min(drive, 1)
    shaped = push-pull shaper with k = drive
    out    = x + amount * (shaped - x)

so drive 0 is an exact passthrough, 0 < drive < 1 adds saturation without a
level cut, and drive >= 1 stays fully wet (today's output).

Asserts on the real tree (comment-stripped, brace-matched MasterOutputStage):
  (a) the amount is `min(drive, 1)` (jmin/std::min), never the raw drive;
  (b) the unity blend `x + amount * (shaped - x)` is present and the fully-wet
      short-circuit returns the unblended shaper output;
  (c) the asymmetric shaper (0.15 positive knee, 0.25 negative knee, padeTanh)
      is still there and both branches assign `shaped`;
  (d) the mid and side saturation lambdas both call pushPullSaturate with their
      own drive (midDrive / sideDrive) and the right oversampler;
  (e) no code path multiplies the shaper output by drive alone (the old
      `shaped * drive` / `padeTanh(z) * drive` gain-cut shape).

Negative probes (in-memory mutated copies; a stale mutation aborts, the real
tree is never mutated):
  - return only the shaper at drive 0 -> rejected;
  - drop the min(drive,1) clamp -> rejected;
  - route the mid path through sideDrive -> rejected;
  - multiply the shaper output by drive alone -> rejected;
  - benign code edit (`x * drive` -> `drive * x`) -> accepted.

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


# The shaper output must never be turned straight into a gain. `d = x * drive`
# (input times drive) is the intentional internal gain and is not matched.
SHAPER_TIMES_DRIVE = (
    r"(?:\bshaped\b|\bpadeTanh\s*\([^()]*\))\s*\*\s*[^;{}]*\bdrive\b",
    r"\bdrive\s*\*\s*(?:\bshaped\b|\bpadeTanh\s*\([^()]*\))",
)


def shaper_times_drive(code):
    for pattern in SHAPER_TIMES_DRIVE:
        match = re.search(pattern, code, flags=re.S)
        if match is not None:
            return match.group(0)
    return None


def verify(header_text):
    code = strip_comments(header_text)
    master = struct_body(code, "MasterOutputStage")
    if master is None:
        raise Reject("struct MasterOutputStage not found / brace-matched")

    sats = function_bodies(
        master,
        r"float\s+pushPullSaturate\s*\(\s*float\s+x\s*,\s*float\s+drive\s*\)")
    if not sats:
        raise Reject("MasterOutputStage::pushPullSaturate body not found")
    sat = sats[0]

    processes = function_bodies(
        master,
        r"void\s+process\s*\(\s*float\s*&\s*L\s*,\s*float\s*&\s*R\s*,"
        r"\s*float\s+midDrive\s*,\s*float\s+sideDrive\s*,\s*float\s+width\s*,"
        r"\s*bool\s+applySaturator\s*=\s*true\s*\)")
    if not processes:
        raise Reject("MasterOutputStage::process body not found")
    process = processes[0]

    if len(sat) < 200 or len(process) < 700:
        raise Reject("brace matching drifted (saturator %d chars, process %d "
                     "chars) - do not trust green" % (len(sat), len(process)))

    # --- (a) drive is an amount, clamped to 1 ------------------------------
    require(sat,
            r"amount\s*=\s*(?:juce::jmin|std::min|jmin)\s*\(\s*drive\s*,"
            r"\s*1\.0f\s*\)",
            "pushPullSaturate no longer clamps the saturation amount with "
            "min(drive, 1) - the blend stops being an amount")

    # --- (b) unity blend + fully-wet short-circuit -------------------------
    require(sat,
            r"return\s+x\s*\+\s*amount\s*\*\s*\(\s*shaped\s*-\s*x\s*\)\s*;",
            "pushPullSaturate no longer returns the unity blend "
            "`x + amount * (shaped - x)` - drive 0 must pass the input through, "
            "not silence it")
    require(sat,
            r"if\s*\(\s*amount\s*>=\s*1\.0f\s*\)\s*"
            r"(?:\{\s*return\s+shaped\s*;\s*\}|return\s+shaped\s*;)",
            "pushPullSaturate no longer returns the unblended shaper when "
            "amount >= 1 - drive >= 1 must stay fully wet (today's output)")

    # --- (c) the shipped asymmetric shape stays intact ---------------------
    require(sat, r"\bfloat\s+shaped\s*;",
            "pushPullSaturate no longer names the shaped sample")
    require(sat, r"shaped\s*=\s*padeTanh\s*\(\s*z\s*\)\s*;",
            "pushPullSaturate lost the positive-half padeTanh shaper")
    require(sat, r"shaped\s*=\s*-\s*padeTanh\s*\(\s*z\s*\)\s*;",
            "pushPullSaturate lost the negative-half padeTanh shaper")
    for knee, label in (("0.15f", "positive (0.15)"),
                        ("0.25f", "negative (0.25)")):
        if knee not in sat:
            raise Reject("pushPullSaturate lost the %s asymmetric knee (%s) - "
                         "the even-harmonic shape changed" % (label, knee))

    # --- (d) mid and side both use the amount shaper ----------------------
    require(process,
            r"oversampleMid\s*\.\s*processSampleMono\s*\(\s*mid\b",
            "process no longer saturates the mid signal through oversampleMid")
    require(process,
            r"oversampleSide\s*\.\s*processSampleMono\s*\(\s*side\b",
            "process no longer saturates the side signal through oversampleSide")
    require(process,
            r"if\s*\(\s*!\s*applySaturator\s*\)\s*"
            r"(?:\{\s*out\s*=\s*in\s*;\s*\}|out\s*=\s*in\s*;)",
            "process no longer has a linear reference branch (out = in when "
            "applySaturator is false) on both mid and side")
    if len(re.findall(r"if\s*\(\s*!\s*applySaturator\s*\)", process)) < 2:
        raise Reject("process must bypass the saturator on both mid and side "
                     "when applySaturator is false; a one-sided bypass is not "
                     "the linear reference")
    require(process,
            r"out\s*=\s*pushPullSaturate\s*\(\s*in\s*,\s*midDrive\s*\)\s*;",
            "the mid saturation path no longer calls "
            "pushPullSaturate(in, midDrive)")
    require(process,
            r"out\s*=\s*pushPullSaturate\s*\(\s*in\s*,\s*sideDrive\s*\)\s*;",
            "the side saturation path no longer calls "
            "pushPullSaturate(in, sideDrive)")

    # --- (e) no shaper-output * drive gain path ---------------------------
    gain_cut = shaper_times_drive(master)
    if gain_cut is not None:
        raise Reject("MasterOutputStage multiplies the shaper output by drive "
                     "alone (%r) - that is the old level/mute behaviour, not a "
                     "saturation amount" % gain_cut.strip())


def run(header_text):
    try:
        verify(header_text)
    except Reject as exc:
        return str(exc)
    return None


def main():
    if not SRC.exists():
        print("MASTER-UNITY SETUP FAIL: missing %s" % SRC)
        return 2
    try:
        text = SRC.read_text(encoding="utf-8", errors="replace")
    except OSError as exc:
        print("MASTER-UNITY SETUP FAIL: %s" % exc)
        return 2

    verdict = run(text)
    if verdict is not None:
        print("MASTER-UNITY FAIL: %s" % verdict)
        return 1
    print("master-unity: Master Drive is a min(drive,1) saturation amount, "
          "unity at 0, fully wet at >= 1, on both mid and side")

    # Negative probes: every mutation reintroduces a reported defect shape.
    probes = [
        ("return only the shaper at drive 0",
         lambda s: s.replace(
             "return x + amount * (shaped - x);",
             "return shaped;", 1)),
        ("drop the min(drive,1) clamp",
         lambda s: s.replace(
             "const float amount = juce::jmin(drive, 1.0f);",
             "const float amount = drive;", 1)),
        ("route the mid path through sideDrive",
         lambda s: s.replace(
             "out = pushPullSaturate(in, midDrive);",
             "out = pushPullSaturate(in, sideDrive);", 1)),
        ("multiply the shaper output by drive alone",
         lambda s: s.replace(
             "return x + amount * (shaped - x);",
             "return shaped * drive;", 1)),
    ]
    for label, mutate in probes:
        mutated = mutate(text)
        if mutated == text:
            print("MASTER-UNITY FAIL: probe '%s' is stale: mutation did not "
                  "apply - cannot trust the negative check" % label)
            return 1
        verdict = run(mutated)
        if verdict is None:
            print("MASTER-UNITY FAIL: probe '%s' was NOT rejected - checker is "
                  "vacuous" % label)
            return 1
        print("master-unity: probe '%s' rejected (%s)"
              % (label, verdict[:88]))

    # Specificity: a benign commutative rewrite must not trip the checker.
    neutral = text.replace(
        "float d = x * drive;",
        "float d = drive * x;", 1)
    if neutral == text:
        print("MASTER-UNITY FAIL: benign edit probe is stale: the edit did not "
              "apply")
        return 1
    verdict = run(neutral)
    if verdict is not None:
        print("MASTER-UNITY FAIL: benign code edit was rejected - checker "
              "over-fires: %s" % verdict)
        return 1
    print("master-unity: benign code edit accepted (probe specificity proven)")

    if run(SRC.read_text(encoding="utf-8", errors="replace")) is not None:
        print("MASTER-UNITY FAIL: final live-source re-verification failed")
        return 1
    print("MASTER-UNITY OK (4 negatives, benign edit accepted)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
