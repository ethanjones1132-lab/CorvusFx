#!/usr/bin/env python3
"""Headless checker: CV-064 — chorus Depth must not hard-switch the effect.

Defect. `CorvusFXAudioProcessor::processBlock` ran the chorus process/advance
pair behind

    if (gChorus > 0.001f && sChorusDepth > 0.001f)

so when the smoothed Depth crossed 0.001 the chorus output switched from the
full Mix blend to untouched dry in a single sample (a click at the boundary),
and while Depth sat below the threshold `chorus.process()` and
`chorus.advanceWritePos()` never ran: the delay line, feedback state, allpass
states and every LFO froze. When Depth came back the first wet samples read
delay history from arbitrarily long ago — stale audio faded in over the bypass
ramp instead of the current signal.

Fix, pinned here:

  * PluginProcessor's per-sample gate is the bypass crossfade contract only,
    `if (gChorus > 0.001f)`. The chorus process pair and advanceWritePos() run
    every sample while the module sits in the chain, so delay history never
    freezes on a Depth move.
  * EnhancedChorus owns a depth-engage crossfade: DEPTH_ENGAGE_EPSILON (the
    old 0.001 boundary) plus a DEPTH_ENGAGE_SECONDS (20 ms) linear ramp in
    `engageGain` drive
        input * (1 - engageGain) + mixed * engageGain
    so Depth at/below the threshold fades the chorus contribution out and back
    in instead of stepping it. The gain is seeded exactly on the first rendered
    sample (nothing has been heard yet) and only ramps afterwards.
  * Depth stays modulation depth: the delay-modulation argument and the 0.25
    feedback scale, never a wet/dry coefficient. Dry/Wet stays the independent
    Mix path (dryGain/wetGain -> `mixed`), so Depth and Mix remain orthogonal:
    the engage ramp is not a second mix control and `engageGain`/`engageTarget`
    are never derived from `mix`.

Asserts (comment-stripped, brace-matched bodies):
  FX processBlock
    (a) the chorus gate is exactly `if (gChorus > 0.001f)` — no Depth conjunct;
    (b) no `if (...)` condition in the per-sample body tests `sChorusDepth`;
    (c) the gate body calls chorus.process(smpL, 0, ...) then
        chorus.process(smpR, 1, ...) and chorus.advanceWritePos() after both,
        with no depth branch around them;
  EnhancedChorus (dsp/CorvusEffects.h)
    (d) DEPTH_ENGAGE_EPSILON sits at the old 0.001 boundary and
        DEPTH_ENGAGE_SECONDS is a real fade (5-100 ms), not a switch;
    (e) beginBlock derives engageStep from DEPTH_ENGAGE_SECONDS and sample
        rate; prepare resets engageGain and clears engageSeeded;
    (f) process() writes delayBuffer[channel][writePos] with no early return
        before it and no branch on `depth`, so history advances while the
        chorus contribution is faded out;
    (g) channel 0 owns `engageTarget = (depth > DEPTH_ENGAGE_EPSILON) ? 1 : 0`
        and the min()/max() ramp by engageStep; the target is seeded exactly
        once through `if (! engageSeeded)` and never assigned per sample;
    (h) the return crossfades `mixed` against the dry input with engageGain,
        `mixed` is still `input * dryGain + wetOut * wetGain`, and Depth never
        appears as a `1.0f - depth` blend coefficient.

Exit 0 = ok, 1 = violation with a cited diagnostic, 2 = setup/read failure.
"""
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SRC = ROOT / "source" / "DrippyFX"
FX_PROC = SRC / "PluginProcessor.cpp"
HEADER = SRC / "dsp" / "CorvusEffects.h"

EPSILON_MIN = 0.0
EPSILON_MAX = 0.002
FADE_SECONDS_MIN = 0.005
FADE_SECONDS_MAX = 0.100

CHORUS_CALL_RE = re.compile(
    r"chorus\s*\.\s*process\s*\(\s*(smp[LR])\s*,\s*(\d)\s*,\s*"
    r"sChorusRate\s*,\s*sChorusDepth\s*,\s*sChorusFb\s*\)")
IF_COND_RE = re.compile(r"if\s*\(([^)]*)\)")

GATE_RE = re.compile(r"if\s*\(\s*gChorus\s*>\s*0\.001f\s*\)\s*\{")


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


def method_body(code, marker):
    k = code.find(marker)
    if k == -1:
        return None
    opening = code.find("{", k)
    if opening == -1:
        return None
    return brace_body(code, opening)


def struct_body(code, name):
    match = re.search(r"\bstruct\s+" + re.escape(name) + r"\b[^;{]*\{", code)
    if not match:
        return None
    return brace_body(code, match.end() - 1)


def function_body(code, pattern):
    match = re.search(pattern, code)
    if not match:
        return None
    return brace_body(code, match.end() - 1)


def require(body, pattern, why, flags=re.S):
    if re.search(pattern, body, flags=flags) is None:
        return why
    return None


def first_error(checks):
    for err in checks:
        if err:
            return err
    return None


def check_fx(text):
    code = strip_comments(text)
    body = method_body(code, "CorvusFXAudioProcessor::processBlock(")
    if body is None:
        return ("could not extract the brace-matched "
                "CorvusFXAudioProcessor::processBlock body")

    gate_match = GATE_RE.search(body)
    if gate_match is None:
        return ("the chorus gate is not `if (gChorus > 0.001f)`: CV-064 removed "
                "the `sChorusDepth > 0.001f` conjunct so the bypass crossfade "
                "alone decides whether the process/advance pair runs")
    gate = brace_body(body, gate_match.end() - 1)
    if gate is None:
        return "could not brace-match the chorus gate body"

    calls = list(CHORUS_CALL_RE.finditer(gate))
    if len(calls) != 2:
        return ("expected exactly 2 chorus.process calls inside the bypass "
                f"gate, found {len(calls)}")
    if (calls[0].group(1), calls[0].group(2)) != ("smpL", "0"):
        return ("first chorus.process must be the L voice with channel index "
                f"0, got ({calls[0].group(1)}, {calls[0].group(2)})")
    if (calls[1].group(1), calls[1].group(2)) != ("smpR", "1"):
        return ("second chorus.process must be the R voice with channel index "
                f"1, got ({calls[1].group(1)}, {calls[1].group(2)})")

    advance_at = gate.find("chorus.advanceWritePos();")
    if advance_at == -1:
        return ("chorus.advanceWritePos() is missing from the bypass gate - "
                "the delay line would stop advancing on every rendered sample")
    if advance_at < calls[1].end():
        return ("chorus.advanceWritePos() must follow both chorus.process "
                "calls (hoisting it shifts the read/write slot every sample)")

    for cond in IF_COND_RE.findall(gate):
        if re.search(r"depth", cond, flags=re.I):
            return ("the chorus gate body branches on depth "
                    f"(`if ({cond.strip()})`) - the process/advance pair must "
                    "run unconditionally so silent engagement keeps the delay "
                    "history moving")

    if re.search(r"sChorusDepth\s*>\s*0\.001f", body):
        return ("the old `sChorusDepth > 0.001f` process-and-advance gate is "
                "back in processBlock: crossing that boundary hard-switches the "
                "chorus and freezes the delay history (CV-064)")
    for cond in IF_COND_RE.findall(body):
        if "sChorusDepth" in cond:
            return ("an `if (...)` condition in the per-sample body tests "
                    f"sChorusDepth (`if ({cond.strip()})`) - Depth is "
                    "modulation depth, not an on/off gate (CV-064)")
    return None


def check_header(text):
    code = strip_comments(text)
    chorus = struct_body(code, "EnhancedChorus")
    if chorus is None:
        return "struct EnhancedChorus not found / brace-matched in CorvusEffects.h"

    eps_match = re.search(
        r"static\s+constexpr\s+float\s+DEPTH_ENGAGE_EPSILON\s*=\s*"
        r"([0-9]*\.?[0-9]+)f\s*;", chorus)
    if eps_match is None:
        return ("`static constexpr float DEPTH_ENGAGE_EPSILON` is missing - the "
                "depth-engage crossfade has no threshold")
    epsilon = float(eps_match.group(1))
    if not (EPSILON_MIN < epsilon <= EPSILON_MAX):
        return (f"DEPTH_ENGAGE_EPSILON is {epsilon:g}; it must stay at the old "
                f"0.001 boundary and at most {EPSILON_MAX:g}, or ordinary "
                "Depth travel starts fading the chorus out")

    sec_match = re.search(
        r"static\s+constexpr\s+float\s+DEPTH_ENGAGE_SECONDS\s*=\s*"
        r"([0-9]*\.?[0-9]+)f\s*;", chorus)
    if sec_match is None:
        return ("`static constexpr float DEPTH_ENGAGE_SECONDS` is missing - the "
                "depth-engage crossfade has no ramp time")
    seconds = float(sec_match.group(1))
    if not (FADE_SECONDS_MIN <= seconds <= FADE_SECONDS_MAX):
        return (f"DEPTH_ENGAGE_SECONDS is {seconds:g}s; it must be a real fade "
                f"({FADE_SECONDS_MIN:g}-{FADE_SECONDS_MAX:g}s), not a switch "
                "that steps the output at the depth boundary")

    for pattern, why in (
            (r"float\s+engageGain\s*=\s*1\.0f\s*;",
             "the `float engageGain = 1.0f;` member is missing"),
            (r"bool\s+engageSeeded\s*=\s*false\s*;",
             "the `bool engageSeeded = false;` member is missing")):
        err = require(chorus, pattern, why, flags=0)
        if err:
            return err

    begin = function_body(
        chorus,
        r"void\s+beginBlock\s*\(\s*float\s+depth\s*,\s*float\s+mix\s*,"
        r"\s*float\s+rate\s*\)\s*\{")
    if begin is None:
        return "EnhancedChorus::beginBlock body not found"
    err = first_error([
        require(begin,
                r"chorusBlockCoeffs\s*\.\s*engageStep\s*=\s*1\.0f\s*/\s*"
                r"\(\s*DEPTH_ENGAGE_SECONDS\s*\*\s*sr\s*\)\s*;",
                "beginBlock no longer derives engageStep from "
                "DEPTH_ENGAGE_SECONDS and the sample rate - the engage ramp "
                "must be time-based, not per-sample-per-block luck"),
        require(begin, r"float\s+effectiveMix\s*=\s*mix\s*\*\s*0\.90f\s*;",
                "beginBlock no longer derives effectiveMix from the Mix "
                "control - the independent Dry/Wet blend must survive CV-064"),
        require(begin, r"chorusBlockCoeffs\s*\.\s*dryGain\s*=\s*std::cos\(",
                "beginBlock no longer computes the Mix dry gain"),
        require(begin, r"chorusBlockCoeffs\s*\.\s*wetGain\s*=\s*std::sin\(",
                "beginBlock no longer computes the Mix wet gain"),
    ])
    if err:
        return err

    prepare = function_body(chorus, r"void\s+prepare\s*\(\s*double\s+sr\s*\)\s*\{")
    if prepare is None:
        return "EnhancedChorus::prepare body not found"
    err = first_error([
        require(prepare, r"engageGain\s*=\s*1\.0f\s*;",
                "prepare() no longer resets engageGain - a fresh instance "
                "would ramp from stale state"),
        require(prepare, r"engageSeeded\s*=\s*false\s*;",
                "prepare() no longer clears engageSeeded - the first rendered "
                "sample must seed the engage gain exactly"),
    ])
    if err:
        return err

    process = function_body(
        chorus,
        r"float\s+process\s*\(\s*float\s+input\s*,\s*int\s+channel\s*,"
        r"\s*float\s+rate\s*,\s*float\s+depth\s*,\s*float\s+feedback\s*\)\s*\{")
    if process is None:
        return "EnhancedChorus::process body not found"
    if len(process) < 800:
        return ("brace matching drifted (process() body is only %d chars) - do "
                "not trust green" % len(process))

    # --- (f) the delay line advances unconditionally, every sample ----------
    write_match = re.search(
        r"delayBuffer\s*\[\s*channel\s*\]\s*\[\s*writePos\s*\]\s*=", process)
    if write_match is None:
        return ("process() no longer writes delayBuffer[channel][writePos] - the "
                "chorus has no delay history to advance")
    if "return" in process[:write_match.start()]:
        return ("process() returns before the delay-line write - while the "
                "chorus contribution is faded out the history would freeze and "
                "re-engagement would read stale audio")
    for cond in IF_COND_RE.findall(process):
        if re.search(r"\bdepth\b", cond):
            return ("process() branches on depth "
                    f"(`if ({cond.strip()})`) - any depth branch can skip the "
                    "delay-line write/advance and freeze the history while the "
                    "output is inaudible")

    # --- (g) the engage ramp is channel-0 owned, target-exact seeded --------
    channel_match = re.search(r"if\s*\(\s*channel\s*==\s*0\s*\)\s*\{", process)
    if channel_match is None:
        return ("process() has no `if (channel == 0)` block for the engage "
                "ramp - the shared gain must advance once per sample")
    channel_block = brace_body(process, channel_match.end() - 1)
    if channel_block is None:
        return "could not brace-match the engage-ramp channel block"
    err = first_error([
        require(channel_block,
                r"const\s+float\s+engageTarget\s*=\s*\(\s*depth\s*>\s*"
                r"DEPTH_ENGAGE_EPSILON\s*\)\s*\?\s*1\.0f\s*:\s*0\.0f\s*;",
                "the engage target is no longer "
                "`(depth > DEPTH_ENGAGE_EPSILON) ? 1.0f : 0.0f` - Depth must "
                "drive the engage transition"),
        require(channel_block,
                r"engageGain\s*=\s*std::min\s*\(\s*engageTarget\s*,\s*"
                r"engageGain\s*\+\s*chorusBlockCoeffs\s*\.\s*engageStep\s*\)\s*;",
                "the engage gain has no upward ramp "
                "(`std::min(engageTarget, engageGain + engageStep)`) - a direct "
                "assignment is the CV-064 hard switch"),
        require(channel_block,
                r"engageGain\s*=\s*std::max\s*\(\s*engageTarget\s*,\s*"
                r"engageGain\s*-\s*chorusBlockCoeffs\s*\.\s*engageStep\s*\)\s*;",
                "the engage gain has no downward ramp "
                "(`std::max(engageTarget, engageGain - engageStep)`) - the "
                "fade-out would step at the depth boundary"),
    ])
    if err:
        return err

    seed_match = re.search(r"if\s*\(\s*!\s*engageSeeded\s*\)\s*\{", channel_block)
    if seed_match is None:
        return ("the engage gain no longer seeds through `if (! engageSeeded)` - "
                "either it reseeds every sample (the hard switch) or the first "
                "rendered sample steps from stale state")
    seed_block = brace_body(channel_block, seed_match.end() - 1)
    if seed_block is None:
        return "could not brace-match the engage seeding block"
    err = first_error([
        require(seed_block, r"engageGain\s*=\s*engageTarget\s*;",
                "the seeding branch no longer assigns engageGain = engageTarget"),
        require(seed_block, r"engageSeeded\s*=\s*true\s*;",
                "the seeding branch no longer sets engageSeeded = true - the "
                "gain would be reseeded (hard-switched) on every sample"),
    ])
    if err:
        return err
    direct = re.findall(r"engageGain\s*=\s*engageTarget\s*;", process)
    if len(direct) != 1:
        return ("engageGain is assigned the target directly %d times in "
                "process(); it must be seeded exactly once and ramped "
                "otherwise (CV-064)" % len(direct))
    if re.search(r"engageTarget\s*=[^;]*\bmix\b", process) or \
            re.search(r"engageGain\s*=[^;]*\bmix\b", process):
        return ("the engage gain is derived from mix - the transition belongs "
                "to Depth and the Dry/Wet blend to the independent Mix control")

    # --- (h) Depth is not a wet/dry coefficient ----------------------------
    if re.search(r"1\.0f\s*-\s*depth", process):
        return ("process() blends with `1.0f - depth` - Depth is being used as "
                "a wet/dry coefficient; the engage crossfade must be the only "
                "blend of its kind and Mix the only Dry/Wet control")
    mixed_match = re.search(
        r"const\s+float\s+mixed\s*=\s*input\s*\*\s*dryGain\s*\+\s*"
        r"wetOut\s*\*\s*wetGain\s*;", process)
    if mixed_match is None:
        return ("the Mix blend (`const float mixed = input * dryGain + wetOut * "
                "wetGain;`) is gone - Dry/Wet must stay independent of Depth")
    if "engageGain" in mixed_match.group(0):
        return ("engageGain is folded into the Mix blend - the engage ramp must "
                "crossfade the finished blend, not replace the Mix control")
    if not re.search(
            r"if\s*\(\s*engageGain\s*>=\s*1\.0f\s*\)\s*return\s+juce::jlimit"
            r"\s*\(\s*-4\.0f\s*,\s*4\.0f\s*,\s*mixed\s*\)\s*;", process):
        return ("process() no longer returns the untouched Mix blend when "
                "engageGain is fully engaged - a settled render must not be "
                "perturbed by the engage crossfade")
    if not re.search(r"float\s+dryGain\s*=\s*chorusBlockCoeffs\s*\.\s*dryGain\s*;",
                     process):
        return "process() no longer reads the Mix dry gain from the block cache"
    if not re.search(r"float\s+wetGain\s*=\s*chorusBlockCoeffs\s*\.\s*wetGain\s*;",
                     process):
        return "process() no longer reads the Mix wet gain from the block cache"
    if not re.search(
            r"return\s+juce::jlimit\s*\(\s*-4\.0f\s*,\s*4\.0f\s*,\s*"
            r"input\s*\*\s*\(\s*1\.0f\s*-\s*engageGain\s*\)\s*\+\s*"
            r"mixed\s*\*\s*engageGain\s*\)\s*;", process):
        return ("process() no longer returns "
                "`input * (1.0f - engageGain) + mixed * engageGain` - without "
                "the engage crossfade the depth boundary hard-switches again")
    return None


def verify(fx_text, header_text):
    return check_fx(fx_text) or check_header(header_text)


def _replace_once(txt, old, new):
    if old not in txt:
        return txt
    return txt.replace(old, new, 1)


def main():
    for path in (FX_PROC, HEADER):
        if not path.exists():
            print("CV064-CHORUS-DEPTH SETUP FAIL: missing %s" % path)
            return 2
    try:
        fx_text = FX_PROC.read_text(encoding="utf-8", errors="replace")
        header_text = HEADER.read_text(encoding="utf-8", errors="replace")
    except OSError as exc:
        print("CV064-CHORUS-DEPTH SETUP FAIL: %s" % exc)
        return 2

    verdict = verify(fx_text, header_text)
    if verdict is not None:
        print("CV064-CHORUS-DEPTH FAIL: %s" % verdict)
        return 1
    print("cv064-chorus-depth: the bypass gate alone runs the chorus "
          "process/advance pair; the EnhancedChorus depth-engage crossfade "
          "fades the contribution in and out over 20 ms while the delay "
          "history keeps advancing, and Depth stays independent of Mix")

    # Negative probes: each mutation reintroduces the reported defect shape.
    probes = [
        ("FX: restore the old `gChorus && sChorusDepth > 0.001f` gate", "fx",
         lambda s: _replace_once(
             s, "if (gChorus > 0.001f)",
             "if (gChorus > 0.001f && sChorusDepth > 0.001f)")),
        ("FX: delete chorus.advanceWritePos() (history frozen)", "fx",
         lambda s: _replace_once(s, "chorus.advanceWritePos();", "")),
        ("FX: guard advanceWritePos() on the depth threshold", "fx",
         lambda s: _replace_once(
             s, "            chorus.advanceWritePos();",
             "            if (sChorusDepth > 0.001f) chorus.advanceWritePos();")),
        ("header: return before the delay write while Depth is silent", "header",
         lambda s: _replace_once(
             s, "        delayBuffer[channel][writePos] = filtered + fbOut * feedback;",
             "        if (depth <= DEPTH_ENGAGE_EPSILON) return input;\n"
             "        delayBuffer[channel][writePos] = filtered + fbOut * feedback;")),
        ("header: reseed the engage gain every sample (hard switch)", "header",
         lambda s: _replace_once(s, "if (! engageSeeded)", "if (true)")),
        ("header: replace the engage ramp with a direct assignment", "header",
         lambda s: _replace_once(
             s, "engageGain = std::min(engageTarget,",
             "engageGain = engageTarget; //")),
        ("header: drive the engage gain from Mix instead of Depth", "header",
         lambda s: _replace_once(
             s, "const float engageTarget = (depth > DEPTH_ENGAGE_EPSILON)",
             "const float engageTarget = (mix > DEPTH_ENGAGE_EPSILON)")),
        ("header: use Depth as the wet/dry coefficient", "header",
         lambda s: _replace_once(
             s, "input * (1.0f - engageGain) + mixed * engageGain)",
             "input * (1.0f - depth) + mixed * depth)")),
        ("header: drop the engage crossfade from the return", "header",
         lambda s: _replace_once(
             s, "input * (1.0f - engageGain) + mixed * engageGain);",
             "mixed);")),
        ("header: shorten DEPTH_ENGAGE_SECONDS to a switch", "header",
         lambda s: _replace_once(
             s, "static constexpr float DEPTH_ENGAGE_SECONDS = 0.020f;",
             "static constexpr float DEPTH_ENGAGE_SECONDS = 0.00002f;")),
    ]
    for label, kind, mutate in probes:
        original = fx_text if kind == "fx" else header_text
        mutated = mutate(original)
        if mutated == original:
            print("CV064-CHORUS-DEPTH FAIL: probe '%s' is stale: mutation did "
                  "not apply - cannot trust the negative check" % label)
            return 1
        fx_mut = mutated if kind == "fx" else fx_text
        header_mut = mutated if kind == "header" else header_text
        verdict = verify(fx_mut, header_mut)
        if verdict is None:
            print("CV064-CHORUS-DEPTH FAIL: probe '%s' was NOT rejected - "
                  "checker is vacuous" % label)
            return 1
        print("cv064-chorus-depth: probe '%s' rejected (%s)"
              % (label, verdict[:88]))

    # Specificity: edits that only add prose naming the pinned members must
    # stay accepted.
    fx_neutral = fx_text.replace(
        "        if (gChorus > 0.001f)",
        "        // A comment naming gChorus, sChorusDepth, advanceWritePos()\n"
        "        // and chorus.process() is prose, not a gate.\n"
        "        if (gChorus > 0.001f)", 1)
    if fx_neutral == fx_text:
        print("CV064-CHORUS-DEPTH FAIL: benign FX comment probe is stale: the "
              "edit did not apply")
        return 1
    if check_fx(fx_neutral) is not None:
        print("CV064-CHORUS-DEPTH FAIL: benign comment edit in processBlock was "
              "rejected - checker over-fires: %s" % check_fx(fx_neutral))
        return 1

    header_neutral = header_text.replace(
        "            const float engageTarget = (depth > DEPTH_ENGAGE_EPSILON)",
        "            // A comment naming engageGain, engageTarget,\n"
        "            // DEPTH_ENGAGE_EPSILON, mixed and depth is prose.\n"
        "            const float engageTarget = (depth > DEPTH_ENGAGE_EPSILON)", 1)
    if header_neutral == header_text:
        print("CV064-CHORUS-DEPTH FAIL: benign header comment probe is stale: "
              "the edit did not apply")
        return 1
    if check_header(header_neutral) is not None:
        print("CV064-CHORUS-DEPTH FAIL: benign comment edit in "
              "EnhancedChorus::process was rejected - checker over-fires: %s"
              % check_header(header_neutral))
        return 1
    print("cv064-chorus-depth: benign comment edits accepted (probe "
          "specificity proven)")

    if verify(FX_PROC.read_text(encoding="utf-8", errors="replace"),
              HEADER.read_text(encoding="utf-8", errors="replace")) is not None:
        print("CV064-CHORUS-DEPTH FAIL: final live-source re-verification failed")
        return 1
    print("CV064-CHORUS-DEPTH OK (10 negatives, 2 benign edits accepted)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
