#!/usr/bin/env python3
"""Headless checker: the delay ring follows prepare()'s sample rate (CV-037).

`EnhancedDelay` shipped a fixed `float buffer[2][192000]` ring with the read
clamp pinned to `MAX_DELAY - 4` (191996 samples). 192000 samples only hold
2000 ms up to 96 kHz, so at 192 kHz `delayTimeMs * msToSamples` clamped to
~1000 ms and the top half of the 0..2000 ms delay-time knob was dead.

The ring must be allocated from the rate handed to prepare(): 2000 ms plus the
right channel's deliberate 2.7% stereo stretch, the modulation depth and the
existing 4-sample guard (about 2.06 s here, "2000 ms plus a small headroom"),
allocated off the audio thread, with the write heads restarted at 0 so a
re-prepare at a new rate cannot leave a write index past the new end.

Asserts on the real tree (comment-stripped, brace-matched EnhancedDelay):
  (a) the ring is dynamic (`std::vector<float> buffer[2]` / HeapBlock), not a
      fixed `float buffer[2][N]`, and 192000 does not appear in the struct;
  (b) a run-time `int ringLength` member exists;
  (c) prepare() samples its `sr` argument FIRST and then calls
      `resizeRing(ringLengthFor(sampleRate))` - the ring follows the new rate;
  (d) `ringLengthFor()` derives the length from rate * MAX_DELAY_SECONDS;
  (e) `resizeRing()` sizes both channels to ringLength and restarts
      writePos[0]/writePos[1] at 0;
  (f) the numeric clamp in prepare() (`maxDelayF`) still admits 2000 ms, and
      the right channel's 2.7% stretch plus modulation on top of it, at 44.1,
      48, 96 and 192 kHz (evaluated from the source clamp expression and the
      ring model) - the 192 kHz case is the reported defect (~1000 ms);
  (g) processSample()/beginBlock() never assign/resize/clear the ring; the
      reads still go through hermiteInterp over ringLength and the write
      heads still wrap at ringLength;
  (h) the 44.1/48 kHz delay math is untouched: msToSamples =
      sampleRate * 0.001f, the 0.9997 smoothing coefficient, and
      `jlimit(1.0f, maxDelayF, delayTimeMs * msToSamples)`.

Negative probes (in-memory mutated copies; a stale mutation aborts, the real
tree is never mutated):
  - restore the fixed 192000-sample ring -> rejected;
  - hard-code a 191996-sample clamp ceiling -> rejected (already short at
    96 kHz, ~1000 ms at 192 kHz);
  - shrink MAX_DELAY_SECONDS to 1.0 -> rejected (same 192 kHz shortfall);
  - shrink it to a bare 2.05 s -> rejected (the 2.7% stereo stretch at the
    top of the knob no longer fits, changing the 44.1/48 kHz sound);
  - stop restarting writePos in resizeRing() -> rejected;
  - allocate the ring inside processSample() -> rejected;
  - benign comment edits inside EnhancedDelay -> accepted.

Exit 0 = ok, 1 = violation with a cited diagnostic, 2 = setup/read failure.
"""
import math
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SRC = ROOT / "source" / "DrippyFX" / "dsp" / "CorvusEffects.h"

KNOB_MS = 2000.0
# processSample() reads channel 1 at targetSmp * 1.027 and adds up to
# 0.65 * (1.25 * modAmount * sampleRateK) samples of modulation, so the ring
# must still hold this beyond the knob value (the fixed ring always did at
# 44.1/48 kHz).
STEREO_STRETCH = 0.027
MOD_DEPTH_SR = 0.00075
RATES = (44100.0, 48000.0, 96000.0, 192000.0)
RATE_LABELS = {44100.0: "44.1 kHz", 48000.0: "48 kHz",
               96000.0: "96 kHz", 192000.0: "192 kHz"}


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


def constant(code, name):
    match = re.search(r"\b%s\s*=\s*([0-9]+(?:\.[0-9]+)?)\s*;" % name, code)
    if match is None:
        raise Reject("EnhancedDelay no longer declares a literal %s constant"
                     % name)
    return float(match.group(1))


def ring_model(delay_code):
    """Ring length model taken from the declared constants."""
    seconds = constant(delay_code, "MAX_DELAY_SECONDS")
    guard = int(constant(delay_code, "RING_GUARD_SAMPLES"))
    floor = int(constant(delay_code, "MIN_RING_SAMPLES"))

    def ring(sr):
        return max(floor, int(math.ceil(sr * seconds)))

    return {"seconds": seconds, "guard": guard, "floor": floor, "ring": ring}


SAFE_EXPR = re.compile(r"[0-9eE+\-*/(). \t]+")


def eval_clamp(expr, sr, model):
    """Evaluate the maxDelayF clamp expression for one sample rate."""
    text = re.sub(r"static_cast\s*<\s*(?:float|double|int)\s*>", "", expr)
    text = re.sub(r"\(\s*(?:float|double|int)\s*\)", "", text)
    symbols = {
        "ringLength": model["ring"](sr),
        "MAX_DELAY_SECONDS": model["seconds"],
        "RING_GUARD_SAMPLES": model["guard"],
        "MIN_RING_SAMPLES": model["floor"],
        "MAX_DELAY": 192000.0,
    }
    for name in sorted(symbols, key=len, reverse=True):
        text = re.sub(r"\b%s\b" % name, repr(float(symbols[name])), text)
    text = re.sub(r"(?<=[0-9.])f\b", "", text)
    if SAFE_EXPR.fullmatch(text) is None:
        raise Reject("cannot evaluate the prepare() maxDelayF clamp "
                     "expression %r" % expr.strip())
    try:
        return float(eval(text, {"__builtins__": {}}, {}))
    except Exception:
        raise Reject("the prepare() maxDelayF clamp expression %r does not "
                     "evaluate" % expr.strip())


ALLOC_ON_AUDIO_THREAD = (
    r"\b(?:assign|resize|reserve|push_back|emplace_back)\s*\("
    r"|\bnew\s*\[|\bmemset\s*\("
)


def verify(header_text):
    code = strip_comments(header_text)
    delay = struct_body(code, "EnhancedDelay")
    if delay is None:
        raise Reject("struct EnhancedDelay not found / brace-matched")
    if len(delay) < 1200:
        raise Reject("brace matching drifted (EnhancedDelay body is only %d "
                     "chars) - do not trust green" % len(delay))

    # --- (a) the ring is dynamic, not the fixed 192000-sample array ---------
    fixed = re.search(r"\bfloat\s+buffer\s*\[\s*2\s*\]\s*\[\s*[^\]]*\]", delay)
    if fixed is not None:
        raise Reject("EnhancedDelay still declares a fixed-size ring (%r) - "
                     "its length cannot follow prepare()'s sample rate"
                     % fixed.group(0).strip())
    if re.search(r"\b192000\b", delay) is not None:
        raise Reject("EnhancedDelay still hard-codes 192000 samples - the ring "
                     "must be sized from the rate prepare() is handed (192000 "
                     "samples are only 1000 ms at 192 kHz)")
    dynamic = (re.search(r"\bstd::vector\s*<\s*float\s*>\s+buffer\s*\[\s*2\s*\]",
                         delay)
               or re.search(r"\bjuce::HeapBlock\s*<\s*float\s*>\s+buffer\s*"
                            r"\[\s*2\s*\]", delay))
    if dynamic is None:
        raise Reject("EnhancedDelay::buffer is not a dynamic 2-channel ring "
                     "(std::vector<float> buffer[2] expected)")

    # --- (b) run-time ring length state ------------------------------------
    if re.search(r"\bint\s+ringLength\s*=", delay) is None:
        raise Reject("EnhancedDelay lost the run-time `int ringLength` member "
                     "- nothing to size the ring or clamp the read against")

    # --- (c) prepare() sizes the ring from the rate it was handed ----------
    prepares = function_bodies(delay, r"void\s+prepare\s*\(\s*double\s+sr\s*\)")
    if not prepares:
        raise Reject("EnhancedDelay::prepare(double sr) body not found")
    prepare = prepares[0]

    sized = list(re.finditer(
        r"resizeRing\s*\(\s*ringLengthFor\s*\(\s*sampleRate\s*\)\s*\)", prepare))
    if not sized:
        raise Reject("prepare() no longer sizes the ring from its own rate "
                     "(no `resizeRing(ringLengthFor(sampleRate))`) - a re-prepare "
                     "at a new rate would keep the old ring")
    sampled = re.search(r"sampleRate\s*=\s*[^;]*\bsr\b", prepare)
    if sampled is None or sampled.start() > sized[0].start():
        raise Reject("prepare() sizes the ring before it samples the rate it "
                     "was handed - the ring would follow the previous rate")

    # --- (d) ringLengthFor() derives the length from the rate --------------
    sizers = function_bodies(delay, r"static\s+int\s+ringLengthFor\s*\(")
    if not sizers:
        raise Reject("ringLengthFor() helper not found - the ring length no "
                     "longer has a single rate-driven definition")
    sizer = sizers[0]
    if re.search(r"ceil\s*\([^;]*rate\s*\*\s*MAX_DELAY_SECONDS", sizer) is None:
        raise Reject("ringLengthFor() no longer derives the length from "
                     "`ceil(rate * MAX_DELAY_SECONDS)` - the ring is not sized "
                     "from the sample rate")
    if re.search(r"jmax\s*\(\s*MIN_RING_SAMPLES", sizer) is None:
        raise Reject("ringLengthFor() lost the MIN_RING_SAMPLES floor")

    # --- (e) resizeRing() sizes both channels and restarts the write heads -
    resizers = function_bodies(delay, r"void\s+resizeRing\s*\(")
    if not resizers:
        raise Reject("resizeRing() helper not found - prepare() has nothing "
                     "that re-sizes the ring")
    resize = resizers[0]
    if re.search(r"ringLength\s*=", resize) is None:
        raise Reject("resizeRing() no longer records the new ringLength")
    if re.search(r"assign\s*\([^;]*ringLength", resize) is None:
        raise Reject("resizeRing() no longer sizes both channel rings to "
                     "ringLength")
    if re.search(r"writePos\s*\[\s*0\s*\]\s*=\s*writePos\s*\[\s*1\s*\]\s*=\s*0",
                 resize) is None:
        raise Reject("resizeRing() no longer restarts writePos[0]/writePos[1] "
                     "at 0 - a re-prepare could leave a write index past the "
                     "new end")

    # --- (f) the clamp still admits the whole 0..2000 ms knob range --------
    clamp_m = re.search(r"maxDelayF\s*=\s*([^;]+);", prepare)
    if clamp_m is None:
        raise Reject("prepare() no longer seeds blockCoeffs.maxDelayF - the "
                     "delay-time read clamp lost its source")
    clamp_expr = clamp_m.group(1)
    model = ring_model(delay)
    for sr in RATES:
        max_samples = eval_clamp(clamp_expr, sr, model)
        needed = sr * KNOB_MS / 1000.0
        if max_samples < needed:
            reached_ms = max_samples / sr * 1000.0
            raise Reject("after prepare(%d) [%s] the delay clamp is %.0f "
                         "samples = %.1f ms - a 2000 ms request would collapse "
                         "below the knob's top"
                         % (int(sr), RATE_LABELS[sr], max_samples, reached_ms))
    ring_192k = model["ring"](192000.0)
    if ring_192k < 192000.0 * KNOB_MS / 1000.0 + model["guard"]:
        raise Reject("the 192 kHz ring (%d samples, %.0f ms) does not hold "
                     "2000 ms plus the %d-sample guard"
                     % (ring_192k, ring_192k / 192.0,
                        model["guard"]))

    # The old fixed ring left room for the right channel's 2.7% stretch and the
    # modulation on top of the knob value at 44.1/48 kHz (and every higher rate
    # once the ring follows the rate). A ring that only reaches 2000 ms would
    # clamp the stretched channel at the top of the knob and change the sound
    # of a 48 kHz session.
    needed_s = KNOB_MS / 1000.0 * (1.0 + STEREO_STRETCH) + MOD_DEPTH_SR
    for sr in RATES:
        max_samples = eval_clamp(clamp_expr, sr, model)
        if max_samples < sr * needed_s:
            raise Reject("after prepare(%d) [%s] the delay clamp is %.0f "
                         "samples = %.1f ms - the right channel's 2.7%% stretch "
                         "plus modulation no longer reach the top of the knob "
                         "(%.1f ms needed)"
                         % (int(sr), RATE_LABELS[sr], max_samples,
                            max_samples / sr * 1000.0, needed_s * 1000.0))

    # --- (g) the audio thread never touches the ring's size ---------------
    procs = function_bodies(delay, r"void\s+processSample\s*\(")
    if not procs:
        raise Reject("EnhancedDelay::processSample body not found")
    proc = procs[0]

    blocks = function_bodies(delay, r"void\s+beginBlock\s*\([^)]*\)")
    hot = [(proc, "processSample()")] + [(b, "beginBlock()") for b in blocks]
    for body, label in hot:
        alloc = re.search(ALLOC_ON_AUDIO_THREAD, body)
        if alloc is not None:
            raise Reject("%s allocates or clears ring memory (%r) - that is "
                         "audio-thread work" % (label, alloc.group(0)))

    for ch in (0, 1):
        if re.search(r"hermiteInterp\s*\(\s*buffer\s*\[\s*%d\s*\]\s*\.\s*data"
                     r"\s*\(\s*\)\s*,\s*ringLength\s*," % ch, proc) is None:
            raise Reject("processSample() no longer reads channel %d with "
                         "hermiteInterp over ringLength" % ch)
    wraps = re.findall(r"\+\+writePos\s*\[\s*\d\s*\]\s*>=\s*ringLength", proc)
    if len(wraps) < 2:
        raise Reject("processSample() no longer wraps both write heads at "
                     "ringLength - the ring end must follow the allocation")

    # --- (h) the 44.1/48 kHz delay math is unchanged -----------------------
    if re.search(r"msToSamples\s*=\s*static_cast<float>\s*\(\s*sampleRate\s*\)"
                 r"\s*\*\s*0\.001f", prepare) is None:
        raise Reject("prepare() no longer derives "
                     "`msToSamples = sampleRate * 0.001f` - the knob's "
                     "ms-to-samples math changed")
    if re.search(r"smooth\s*=\s*0\.9997f", prepare) is None:
        raise Reject("prepare() lost the 0.9997 delay-time smoothing "
                     "coefficient - the delay-time ramp changed")
    if re.search(r"jlimit\s*\(\s*1\.0f\s*,\s*blockCoeffs\.maxDelayF\s*,\s*"
                 r"delayTimeMs\s*\*\s*blockCoeffs\.msToSamples\s*\)",
                 proc) is None:
        raise Reject("processSample() no longer clamps "
                     "`delayTimeMs * blockCoeffs.msToSamples` to "
                     "`blockCoeffs.maxDelayF` - the delay-time mapping changed")


def run(header_text):
    try:
        verify(header_text)
    except Reject as exc:
        return str(exc)
    return None


def body_span(text, pattern):
    match = re.search(pattern, text)
    if match is None:
        return None
    opening = text.find("{", match.end() - 1)
    if opening == -1:
        return None
    body = brace_body(text, opening)
    if body is None:
        return None
    return opening + 1, opening + 1 + len(body)


def mutate_body(text, pattern, transform):
    span = body_span(text, pattern)
    if span is None:
        return text
    start, end = span
    return text[:start] + transform(text[start:end]) + text[end:]


def struct_span(text, name):
    match = re.search(r"\bstruct\s+" + re.escape(name) + r"\b[^;{]*\{", text)
    if match is None:
        return None
    opening = match.end() - 1
    body = brace_body(text, opening)
    if body is None:
        return None
    return opening + 1, opening + 1 + len(body)


def mutate_struct(text, name, pattern, transform):
    """Mutate one function body inside one struct of the raw text."""
    span = struct_span(text, name)
    if span is None:
        return text
    start, end = span
    body = mutate_body(text[start:end], pattern, transform)
    return text[:start] + body + text[end:]


def drop_write_reset(body):
    return re.sub(r"[ \t]*writePos\s*\[\s*0\s*\][^\n]*\n", "", body, count=1)


def main():
    if not SRC.exists():
        print("CV037 SETUP FAIL: missing %s" % SRC)
        return 2
    try:
        text = SRC.read_text(encoding="utf-8", errors="replace")
    except OSError as exc:
        print("CV037 SETUP FAIL: %s" % exc)
        return 2

    verdict = run(text)
    if verdict is not None:
        print("CV037 FAIL: %s" % verdict)
        return 1
    print("cv037: delay ring is sized from prepare()'s sample rate (2.06 s: "
          "2000 ms + stereo stretch + mod + guard), "
          "both write heads restart on resize, the clamp admits the full "
          "0..2000 ms knob range at 44.1/48/96/192 kHz, and the delay math is "
          "unchanged")

    probes = [
        ("restore the fixed 192000-sample ring",
         lambda s: s.replace("std::vector<float> buffer[2];",
                             "float buffer[2][192000] = {};", 1)),
        ("hard-code the old 191996-sample clamp ceiling",
         lambda s: s.replace(
             "blockCoeffs.maxDelayF = static_cast<float>(ringLength - "
             "RING_GUARD_SAMPLES);",
             "blockCoeffs.maxDelayF = 191996.0f;", 1)),
        ("shrink MAX_DELAY_SECONDS to 1.0",
         lambda s: s.replace("MAX_DELAY_SECONDS = 2.06;",
                             "MAX_DELAY_SECONDS = 1.0;", 1)),
        ("shrink MAX_DELAY_SECONDS to a bare 2.05 s (loses the stereo stretch)",
         lambda s: s.replace("MAX_DELAY_SECONDS = 2.06;",
                             "MAX_DELAY_SECONDS = 2.05;", 1)),
        ("stop restarting the write heads in resizeRing()",
         lambda s: mutate_struct(s, "EnhancedDelay",
                                 r"void\s+resizeRing\s*\(", drop_write_reset)),
        ("allocate the ring inside EnhancedDelay::processSample()",
         lambda s: mutate_struct(
             s, "EnhancedDelay", r"void\s+processSample\s*\(",
             lambda b: "\n        buffer[0].assign(1, 0.0f);" + b)),
    ]
    for label, mutate in probes:
        mutated = mutate(text)
        if mutated == text:
            print("CV037 FAIL: probe '%s' is stale: mutation did not apply - "
                  "cannot trust the negative check" % label)
            return 1
        verdict = run(mutated)
        if verdict is None:
            print("CV037 FAIL: probe '%s' was NOT rejected - checker is "
                  "vacuous" % label)
            return 1
        print("cv037: probe '%s' rejected (%s)" % (label, verdict[:96]))

    # Specificity: comment-only edits must still pass.
    neutrals = [
        ("tick comment in reset()",
         "// The renormalization tick is part of the modulation state: a reset",
         "// The renormalization tick is part of the modulation state: a reset"
         " (comment edit only)"),
        ("ring comment in prepare()",
         "// Stage the SSE coefficient vectors and clear both channel histories.",
         "// Stage the SSE coefficient vectors and clear both channel "
         "histories. (comment edit only)"),
    ]
    for label, old, new in neutrals:
        neutral = text.replace(old, new, 1)
        if neutral == text:
            print("CV037 FAIL: benign comment probe '%s' is stale: the edit "
                  "did not apply" % label)
            return 1
        verdict = run(neutral)
        if verdict is not None:
            print("CV037 FAIL: benign comment edit '%s' was rejected - checker "
                  "over-fires: %s" % (label, verdict))
            return 1
        print("cv037: benign comment edit '%s' accepted" % label)

    if run(SRC.read_text(encoding="utf-8", errors="replace")) is not None:
        print("CV037 FAIL: final live-source re-verification failed")
        return 1
    print("cv037: OK (6 negatives rejected, comment edits accepted)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
