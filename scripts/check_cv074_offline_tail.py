#!/usr/bin/env python3
"""CV-074: each product's declared offline-render tail covers its worst case.

An offline host asks the processor how long its tail runs
(`getTailLengthSeconds`) and keeps rendering that long after the input stops,
so the number has to cover the longest decay the *configured* settings can
produce. Everything below is evaluated from the sources, not remembered:

  FX (source/DrippyFX/PluginProcessor.cpp + dsp/CorvusEffects.h)
    delay_time     msParam(..., 0, 2000, ...)              -> 2.000 s
    delay_feedback pctParam 0..100% -> feedbackTarget(1.0)
                   = 0.65 + 0.27 = 0.92, and EnhancedDelay hard-clamps the
                   loop gain at 0.92 as well
                   RT60 = 2.000 s * ln(1e-3) / ln(0.92)     = 165.69 s
    reverb_size    pctParam 0..100% -> blockCoeffs.fb
                   = 0.70 + 0.27 * 1.0 = 0.97; longest comb 1617 samples at
                   the 44100 reference rate the comb sizes are scaled from
                   RT60 = (1617/44100) s * ln(1e-3) / ln(0.97)
                                                             =   8.32 s
    pre-delay      5 + 40 ms at size 100%                  =   0.05 s
    processBlock chains Delay -> Reverb, so the two decays add:
                   required >= 174.05 s  ->  declared 180.0 s

  Instrument (instrument/CorvusInstrumentProcessor.{h,cpp} + dsp/CorvusEffects.h)
    release        0.01..10.0 s envelope after the last note-off = 10.00 s
    Flight = 1 ->  delayTimeMs    = min(900, 90 + 410)      = 500 ms
                   delayFeedback  = min(0.75, 0.12 + 0.36)  = 0.48
                   RT60 = 0.500 s * ln(1e-3) / ln(0.48)     =   4.71 s
    Flight = 1 ->  reverbSize     = min(1, 0.30 + 0.62)     = 0.92
                   comb feedback  = 0.70 + 0.27 * 0.92      = 0.9484
                   RT60 = (1617/44100) s * ln(1e-3) / ln(0.9484)
                                                             =   4.78 s
    pre-delay      5 + 40 * 0.92 ms                         =   0.04 s
                   chain is Delay -> Reverb after the envelope:
                   required >= 19.53 s  ->  declared 20.0 s

Both declarations must stay a bare `return <seconds>;` constant: the override
may not read a parameter or touch state, so realtime processing is untouched.
Nothing here edits DSP, parameter ranges or presets - the gate only reports.

Negative probes (in-memory mutated copies; the real tree is never mutated):
  - FX declaration dropped to 0.5 s                -> rejected
  - FX delay_time max widened 2000 -> 8000 ms      -> rejected
  - Instrument declaration dropped to 0.5 s        -> rejected
  - Instrument release max widened 10 -> 30 s      -> rejected
  - benign comment edit next to the FX override    -> accepted
Exit 0 = ok, 1 = violation, 2 = setup/read failure.
"""
import math
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
FX_CPP = ROOT / "source" / "DrippyFX" / "PluginProcessor.cpp"
INST_CPP = ROOT / "source" / "DrippyFX" / "instrument" / "CorvusInstrumentProcessor.cpp"
INST_HDR = ROOT / "source" / "DrippyFX" / "instrument" / "CorvusInstrumentProcessor.h"
EFFECTS_H = ROOT / "source" / "DrippyFX" / "dsp" / "CorvusEffects.h"

FX_TAIL_RE = (r"double\s+CorvusFXAudioProcessor::getTailLengthSeconds\s*\(\s*\)"
              r"\s*const\s*\{([^}]*)\}")
INST_TAIL_RE = (r"double\s+getTailLengthSeconds\s*\(\s*\)\s*const\s*override"
                r"\s*\{([^}]*)\}")
# Group 1 is the upper bound of each range the tail is derived from.
FX_DELAY_RE = (r'msParam\(\s*"delay_time"\s*,\s*"[^"]*"\s*,\s*-?[\d.]+\s*,'
               r'\s*(-?[\d.]+)\s*,')
INST_RELEASE_RE = (r'"release"\s*,\s*"Release"\s*,\s*'
                   r'juce::NormalisableRange<float>\(\s*[\d.]+f\s*,'
                   r'\s*([\d.]+)f')
# ln of the -60 dB amplitude ratio: RT60 = seconds * ln(1e-3) / ln(loop gain).
RT60_LN = math.log(1.0e-3)


class Reject(Exception):
    pass


def strip_comments(src):
    # One pass: a `//` line comment may itself contain `/*`, which would
    # otherwise pair with a later `*/` and swallow real code.
    return re.sub(r"/\*.*?\*/|//[^\n]*", "", src, flags=re.S)


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
    if match is None:
        return None
    return brace_body(code, match.end() - 1)


def need(pattern, text, label):
    match = re.search(pattern, text)
    if match is None:
        raise Reject("could not find %s - the tail derivation is stale, "
                     "re-derive it before trusting green" % label)
    return match


def rt60(seconds, loop_gain, label):
    """Seconds for `loop_gain` per echo to fall 60 dB (never guessed)."""
    if not 0.0 < loop_gain < 1.0:
        raise Reject("%s loop gain %s is outside (0, 1): the tail would never "
                     "decay and no finite declaration covers it"
                     % (label, loop_gain))
    return seconds * RT60_LN / math.log(loop_gain)


def declared_tail(code, pattern, label):
    """The declared seconds, as a bare constant (no state, no parameter read)."""
    match = need(pattern, code, label)
    body = match.group(1)
    if re.fullmatch(r"\s*return\s+[\d.]+\s*;\s*", body) is None:
        raise Reject("%s must stay a bare `return <seconds>;` constant - an "
                     "override that reads parameters or state would put host "
                     "queries on the realtime path" % label)
    return float(re.search(r"return\s+([\d.]+)\s*;", body).group(1))


def effects_sections(effects):
    delay = struct_body(effects, "EnhancedDelay")
    if delay is None:
        raise Reject("struct EnhancedDelay not found / brace-matched in "
                     "dsp/CorvusEffects.h")
    reverb = struct_body(effects, "UpgradedReverb")
    if reverb is None:
        raise Reject("struct UpgradedReverb not found / brace-matched in "
                     "dsp/CorvusEffects.h")
    return delay, reverb


def delay_feedback_ceiling(fx, delay_code, amount):
    """Loop gain the delay can reach: the smoother's curve, DSP-clamped."""
    match = need(r"inline\s+float\s+feedbackTarget\s*\(\s*float\s+linearAmount"
                 r"\s*\)\s*\{\s*return\s+linearAmount\s*\*\s*linearAmount"
                 r"\s*\*\s*([\d.]+)f\s*\+\s*linearAmount\s*\*\s*([\d.]+)f",
                 fx, "feedbackTarget() curve")
    quadratic, linear = float(match.group(1)), float(match.group(2))
    curve = quadratic * amount * amount + linear * amount
    match = need(r"feedback\s*=\s*std::min\(\s*feedback\s*,\s*([\d.]+)f\s*\)",
                 delay_code, "EnhancedDelay feedback clamp")
    return min(curve, float(match.group(1)))


def reverb_decay(reverb_code, room_size):
    """Reverb RT60 plus its pre-delay at one room size (0..1)."""
    match = need(r"blockCoeffs\.fb\s*=\s*([\d.]+)f\s*\+\s*roomSize"
                 r"\s*\*\s*([\d.]+)f", reverb_code,
                 "room size -> comb feedback mapping")
    loop_gain = float(match.group(1)) + float(match.group(2)) * room_size

    bases = []
    for name in ("baseCombL", "baseCombR"):
        found = need(r"%s\[NUM_COMBS\]\s*=\s*\{([^}]*)\}" % name,
                     reverb_code, "%s base comb lengths" % name)
        bases.extend(int(token) for token in re.findall(r"\d+", found.group(1)))
    if not bases:
        raise Reject("no comb lengths found in UpgradedReverb")
    # prepare() sizes every comb as base * (sr / 44100), so the longest comb's
    # duration in seconds is base / 44100 at any sample rate.
    match = need(r"double\s+ratio\s*=\s*sr\s*/\s*([\d.]+)", reverb_code,
                 "comb sample-rate reference")
    comb_seconds = max(bases) / float(match.group(1))
    return rt60(comb_seconds, loop_gain, "reverb")


def fx_requirements(fx, effects):
    delay_code, reverb_code = effects_sections(effects)

    match = need(FX_DELAY_RE, fx, "delay_time msParam range")
    delay_seconds = float(match.group(1)) / 1000.0

    for param_id in ("delay_feedback", "reverb_size"):
        need(r'pctParam\(\s*"%s"' % param_id, fx,
             "%s pctParam registration" % param_id)
    anchor = fx.find("auto pctParam")
    if anchor < 0:
        raise Reject("pctParam helper not found in createParameterLayout")
    match = need(r"NormalisableRange<float>\(\s*-?[\d.]+\s*,\s*(-?[\d.]+)\s*,",
                 fx[anchor:], "pctParam range")
    amount = float(match.group(1)) / 100.0   # percentage knobs are 0..100%

    feedback = delay_feedback_ceiling(fx, delay_code, amount)
    delay_rt60 = rt60(delay_seconds, feedback, "delay")

    reverb_rt60 = reverb_decay(reverb_code, amount)
    match = need(r"reverbPreDelay\s*=\s*([\d.]+)f\s*\+\s*reverbSize"
                 r"\s*\*\s*([\d.]+)f", fx, "reverb pre-delay")
    pre_delay = (float(match.group(1)) + float(match.group(2)) * amount) / 1000.0

    return {"delay": delay_rt60, "reverb": reverb_rt60, "pre_delay": pre_delay,
            "release": 0.0,
            "total": delay_rt60 + reverb_rt60 + pre_delay}


def inst_requirements(inst_cpp, effects):
    delay_code, reverb_code = effects_sections(effects)

    match = need(r"amount\s*=\s*juce::jlimit\(\s*[\d.]+f\s*,\s*([\d.]+)f\s*,"
                 r"\s*flight\s*\)", inst_cpp, "Flight -> amount clamp")
    amount = float(match.group(1))

    def flight_ceiling(field):
        found = need(r"settings\.%s\s*=\s*juce::jlimit\(\s*[\d.]+f\s*,"
                     r"\s*([\d.]+)f\s*,\s*([\d.]+)f\s*\+\s*amount\s*\*\s*"
                     r"([\d.]+)f\s*\)" % field, inst_cpp,
                     "settingsForFlight() %s" % field)
        ceiling, base, slope = (float(g) for g in found.groups())
        return min(ceiling, base + slope * amount)

    delay_seconds = flight_ceiling("delayTimeMs") / 1000.0
    feedback = min(flight_ceiling("delayFeedback"),
                   float(need(r"feedback\s*=\s*std::min\(\s*feedback\s*,"
                              r"\s*([\d.]+)f\s*\)", delay_code,
                              "EnhancedDelay feedback clamp").group(1)))
    delay_rt60 = rt60(delay_seconds, feedback, "instrument delay")

    room_size = flight_ceiling("reverbSize")
    reverb_rt60 = reverb_decay(reverb_code, room_size)
    match = need(r"([\d.]+)f\s*\+\s*settings\.reverbSize\s*\*\s*([\d.]+)f",
                 inst_cpp, "reverb pre-delay")
    pre_delay = (float(match.group(1)) + float(match.group(2)) * room_size) / 1000.0

    match = need(INST_RELEASE_RE, inst_cpp, "release parameter range")
    release = float(match.group(1))

    return {"delay": delay_rt60, "reverb": reverb_rt60, "pre_delay": pre_delay,
            "release": release,
            "total": release + delay_rt60 + reverb_rt60 + pre_delay}


def evaluate(fx_text, inst_cpp, inst_hdr, effects):
    """Return ([diagnostic, ...], {product: (declared, required)} or None)."""
    fx = strip_comments(fx_text)
    inst = strip_comments(inst_cpp)
    hdr = strip_comments(inst_hdr)
    code = strip_comments(effects)

    errors = []
    details = {}
    for product, source, pattern, requirement in (
            ("FX", fx, FX_TAIL_RE,
             lambda: fx_requirements(fx, code)),
            ("Instrument", hdr, INST_TAIL_RE,
             lambda: inst_requirements(inst, code))):
        try:
            required = requirement()
            declared = declared_tail(source, pattern,
                                     "%s getTailLengthSeconds()" % product)
        except (Reject, ValueError) as exc:
            errors.append("[%s] %s" % (product, exc))
            continue
        if declared < required["total"]:
            errors.append(
                "[%s] getTailLengthSeconds() = %s s < %0.2f s required by the "
                "configured maximums (release %0.2f s + delay RT60 %0.2f s + "
                "reverb RT60 %0.2f s + pre-delay %0.2f s)"
                % (product, declared, required["total"], required["release"],
                   required["delay"], required["reverb"],
                   required["pre_delay"]))
            continue
        details[product] = (declared, required)
    return errors, (details if not errors else None)


def set_tail(text, pattern, seconds):
    """Rewrite the declared literal in a copy of the raw text."""
    match = re.search(pattern, text)
    if match is None:
        return text
    body = match.group(1)
    literal = re.search(r"return\s+[\d.]+\s*;", body)
    if literal is None:
        return text
    new_body = (body[:literal.start()] + "return %s;" % seconds
                + body[literal.end():])
    return text[:match.start(1)] + new_body + text[match.end(1):]


def widen_bound(text, pattern, value):
    """Rewrite the upper bound a tail is derived from, in a copy."""
    match = re.search(pattern, text)
    if match is None:
        return text
    return text[:match.start(1)] + value + text[match.end(1):]


def main():
    for path in (FX_CPP, INST_CPP, INST_HDR, EFFECTS_H):
        if not path.exists():
            print("CV074 SETUP FAIL: missing %s" % path)
            return 2
    try:
        fx_text = FX_CPP.read_text(encoding="utf-8", errors="replace")
        inst_cpp = INST_CPP.read_text(encoding="utf-8", errors="replace")
        inst_hdr = INST_HDR.read_text(encoding="utf-8", errors="replace")
        effects = EFFECTS_H.read_text(encoding="utf-8", errors="replace")
    except OSError as exc:
        print("CV074 SETUP FAIL: %s" % exc)
        return 2

    original = (fx_text, inst_cpp, inst_hdr, effects)
    errors, details = evaluate(*original)
    if errors:
        print("CV074 FAIL:")
        for error in errors:
            print("  - %s" % error)
        return 1

    fx_declared, fx_req = details["FX"]
    inst_declared, inst_req = details["Instrument"]
    print("cv074: FX tail %.1f s covers %.2f s (delay RT60 %.2f + reverb RT60 "
          "%.2f + pre-delay %.2f); Instrument tail %.1f s covers %.2f s "
          "(release %.2f + delay RT60 %.2f + reverb RT60 %.2f + pre-delay "
          "%.2f)"
          % (fx_declared, fx_req["total"], fx_req["delay"], fx_req["reverb"],
             fx_req["pre_delay"], inst_declared, inst_req["total"],
             inst_req["release"], inst_req["delay"], inst_req["reverb"],
             inst_req["pre_delay"]))

    def mutated_fx_tail(seconds):
        return (set_tail(fx_text, FX_TAIL_RE, seconds), inst_cpp, inst_hdr,
                effects)

    def mutated_fx_delay_bound():
        return (widen_bound(fx_text, FX_DELAY_RE, "8000"), inst_cpp, inst_hdr,
                effects)

    def mutated_inst_tail(seconds):
        return (fx_text, inst_cpp, set_tail(inst_hdr, INST_TAIL_RE, seconds),
                effects)

    def mutated_inst_release_bound():
        return (fx_text, widen_bound(inst_cpp, INST_RELEASE_RE, "30.0"),
                inst_hdr, effects)

    def comment_only_edit():
        marker = "double CorvusFXAudioProcessor::getTailLengthSeconds"
        edited = fx_text.replace(
            marker, "// CV-074: host tail declaration (comment edit only)\n"
            + marker, 1)
        return edited, (edited, inst_cpp, inst_hdr, effects)

    probes = [
        ("FX declaration dropped to 0.5 s", "[FX]", mutated_fx_tail(0.5)),
        ("FX delay_time max widened to 8000 ms", "[FX]",
         mutated_fx_delay_bound()),
        ("Instrument declaration dropped to 0.5 s", "[Instrument]",
         mutated_inst_tail(0.5)),
        ("Instrument release max widened to 30 s", "[Instrument]",
         mutated_inst_release_bound()),
    ]
    for label, prefix, mutated in probes:
        if mutated == original:
            print("CV074 FAIL: probe '%s' is stale: mutation did not apply - "
                  "cannot trust the negative check" % label)
            return 1
        probe_errors, _ = evaluate(*mutated)
        if not any(error.startswith(prefix) for error in probe_errors):
            print("CV074 FAIL: probe '%s' was NOT rejected (%s) - checker is "
                  "vacuous" % (label, "; ".join(probe_errors) or "no errors"))
            return 1
        print("cv074: probe '%s' rejected (%s)"
              % (label, next(e for e in probe_errors
                             if e.startswith(prefix))[:96]))

    neutral_text, neutral_tuple = comment_only_edit()
    if neutral_text == fx_text:
        print("CV074 FAIL: benign comment probe is stale: the edit did not "
              "apply - cannot trust the specificity check")
        return 1
    neutral, _ = evaluate(*neutral_tuple)
    if neutral:
        print("CV074 FAIL: benign comment edit next to the FX override was "
              "rejected - checker over-fires: %s" % "; ".join(neutral))
        return 1
    print("cv074: benign comment edit next to the FX override accepted")
    return 0


if __name__ == "__main__":
    sys.exit(main())
