#!/usr/bin/env python3
"""Headless checker: CV-061 — an effect engaged from zero must never produce
NaN/Inf (and the session-long silence that follows).

Failure mode this pins. `CorvusFXAudioProcessor::processBlock` seeded its
chorus and reverb block-coefficient caches only when the BLOCK-START smoothed
value was already above 0.001:

    if (reverbMix > 0.001f)   upgradedReverb.beginBlock(...);
    if (chorusDepth > 0.001f) chorus.beginBlock(...);

The per-sample smoothed value can cross those thresholds INSIDE the block
(raising Depth/Mix from 0, or loading a preset whose target is non-zero while
the smoother still reads 0), so `chorus.process()` / `processSample()` ran
with `voiceCosDelta`/`voiceSinDelta` (CorvusEffects.h EnhancedChorus) or
`modLfoCosDelta`/`modLfoSinDelta` (UpgradedReverb) still at their zero
initialisers. A zero rotation maps the unit phasor (sin, cos) to (0, 0); the
next renorm tick then divides by a zero magnitude and stores Inf/NaN into the
oscillator state, which the feedback path repeats for the rest of the session.

The fix has two halves, both pinned here:
  (a) both beginBlock() calls run EVERY block, before the per-sample loop,
      never behind a guard on the block-start smoothed value — the shared
      instrument path (CorvusInstrumentProcessor::processBlock, fixed
      sub-chunk heads) must stay unconditional the same way;
  (b) the renormalizers are total: near-zero magnitude resets the phasor to
      the canonical zero phase (sin 0, cos 1) instead of dividing, for the
      chorus LFO phasor, BOTH chorus drift phasors, and the reverb master
      modulation LFO phasor. No allocation, no new state.

Asserts (comment-stripped, brace-matched bodies):
  1. PluginProcessor::processBlock contains `upgradedReverb.beginBlock(` and
     `chorus.beginBlock(`, each unconditional (no if/else/? between the
     previous statement boundary and the call), each before the per-sample
     `for (int s = 0; s < numSamples` loop.
  2. CorvusInstrumentProcessor::processBlock contains `effects->chorus.beginBlock(`
     and `effects->reverb.beginBlock(`, each unconditional, and the old
     0.001 gates are not present around them.
  3. CorvusEffects.h defines the guarded `renormPhasor(float&, float&)` helper
     with an epsilon test (`magnitude < 1.0e-6f`) that resets sin to 0.0f and
     cos to 1.0f and returns before the division.
  4. `renormLFO()` routes the LFO phasor and both drift phasors through
     `renormPhasor` and performs no bare `1.0f / ...` division (nor its own
     std::sqrt) — a collapsed phasor cannot reach an unguarded divide.
  5. `renormModLFO()` routes modSin/modCos through `renormPhasor` and performs
     no bare division / std::sqrt.

Self-probes (negative checks, sibling checker style) run on mutated in-memory
TEMP texts — the real tree is never mutated. A mutation that does not apply is
a hard failure (stale alarm), never a silent skip.

Exit 0 = ok, 1 = violation with line-cited diagnostics.
"""
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SRC = ROOT / "source" / "DrippyFX"
FX_PROC = SRC / "PluginProcessor.cpp"
INST_PROC = SRC / "instrument" / "CorvusInstrumentProcessor.cpp"
HEADER = SRC / "dsp" / "CorvusEffects.h"

EPSILON = "1.0e-6f"


def fail(msg):
    print(f"CV061-ENGAGE-FROM-ZERO FAIL: {msg}")
    sys.exit(1)


def strip_comments(txt):
    out, i, n = [], 0, len(txt)
    while i < n:
        if txt.startswith("//", i):
            j = txt.find("\n", i)
            i = n if j == -1 else j
        elif txt.startswith("/*", i):
            j = txt.find("*/", i + 2)
            i = n if j == -1 else j + 2
        else:
            out.append(txt[i]); i += 1
    return "".join(out)


def brace_body(code, start):
    """Return the brace-matched region beginning at the first '{' at/after start."""
    o = code.find("{", start)
    if o == -1:
        return None
    depth, j = 0, o
    while j < len(code):
        if code[j] == "{": depth += 1
        elif code[j] == "}":
            depth -= 1
            if depth == 0:
                return code[o:j + 1]
        j += 1
    return None


def extract_method(txt, cls_marker, fn_name):
    """Comment-stripped body of `<cls_marker>::<fn_name>(...)`, or None."""
    marker = f"{cls_marker}::{fn_name}("
    k = txt.find(marker)
    if k == -1:
        return None
    body = brace_body(txt, k)
    if body is None:
        return None
    return strip_comments(body)


def statement_prefix(body, call):
    """Text between the previous statement boundary and `call`, or None."""
    p = body.find(call)
    if p == -1:
        return None
    stmt_start = max(body.rfind(";", 0, p),
                     body.rfind("{", 0, p),
                     body.rfind("}", 0, p))
    return body[stmt_start + 1:p]


def unconditional_reason(body, call, loop_marker=None):
    """None when `call` is a plain unconditional statement, else a diagnostic."""
    prefix = statement_prefix(body, call)
    if prefix is None:
        return f"`{call}` call missing"
    if re.search(r"\bif\s*\(|\belse\b|\?", prefix):
        return (f"`{call}` is still conditional (`{prefix.strip()}`): it must run "
                "every block/chunk, never gate on the block-start smoothed value")
    if loop_marker is not None:
        loop_at = body.find(loop_marker)
        if loop_at == -1:
            return f"per-sample loop marker `{loop_marker}` not found"
        if body.find(call) > loop_at:
            return f"`{call}` appears AFTER the per-sample loop"
    return None


def check_fx(full_text):
    body = extract_method(full_text, "CorvusFXAudioProcessor", "processBlock")
    if body is None:
        return ("could not extract the brace-matched "
                "CorvusFXAudioProcessor::processBlock body")
    loop = "for (int s = 0; s < numSamples"
    for call in ("upgradedReverb.beginBlock(", "chorus.beginBlock("):
        reason = unconditional_reason(body, call, loop)
        if reason:
            return reason
    for gate in ("reverbMix > 0.001f", "chorusDepth > 0.001f"):
        if gate in body:
            return (f"old block-start gate `{gate}` is back at block scope: the "
                    "beginBlock fan must not depend on the smoothed value")
    return None


def check_instrument(full_text):
    body = extract_method(full_text, "CorvusInstrumentProcessor", "processBlock")
    if body is None:
        return ("could not extract the brace-matched "
                "CorvusInstrumentProcessor::processBlock body")
    for call in ("effects->chorus.beginBlock(", "effects->reverb.beginBlock("):
        prefix = statement_prefix(body, call)
        if prefix is None:
            return f"`{call}` call missing from the instrument chunk head"
        if re.search(r"\bif\s*\(|\belse\b|\?", prefix):
            return (f"`{call}` is conditional (`{prefix.strip()}`): the "
                    "instrument chunk head must fan out every beginBlock the "
                    "same way as the FX processBlock")
    for gate in ("chorusDepth > 0.001f", "reverbMix > 0.001f"):
        if gate in body:
            return (f"instrument chunk head gated on `{gate}`: a preset load "
                    "while the smoother still reads 0 would leave the "
                    "coefficients at their zero initialisers")
    return None


def check_header(full_text):
    code = strip_comments(full_text)

    k = code.find("renormPhasor(float& sinPhase, float& cosPhase)")
    if k == -1:
        return ("guarded `renormPhasor(float& sinPhase, float& cosPhase)` helper "
                "not found in dsp/CorvusEffects.h")
    helper = brace_body(code, k)
    if helper is None:
        return "could not brace-match the renormPhasor() body"
    if not re.search(r"if\s*\(\s*magnitude\s*<\s*" + re.escape(EPSILON) + r"\s*\)",
                     helper):
        return ("renormPhasor() lost its near-zero guard "
                f"`if (magnitude < {EPSILON})` - a collapsed (0, 0) phasor would "
                "divide by zero and poison the effect with NaN")
    if not re.search(r"sinPhase\s*=\s*0\.0f\s*;", helper):
        return "renormPhasor() no longer resets the sine to 0.0f on a collapsed phasor"
    if not re.search(r"cosPhase\s*=\s*1\.0f\s*;", helper):
        return "renormPhasor() no longer resets the cosine to 1.0f on a collapsed phasor"
    if "return;" not in helper:
        return "renormPhasor() reset branch no longer returns before the division"
    if not re.search(r"1\.0f\s*/\s*magnitude", helper):
        return "renormPhasor() no longer divides by the measured magnitude"

    def method_body(name):
        m = re.search(r"void\s+" + name + r"\s*\(\s*\)", code)
        if not m:
            return None
        return brace_body(code, m.end() - 1)

    lfo = method_body("renormLFO")
    if lfo is None:
        return "could not brace-match EnhancedChorus::renormLFO()"
    for pair in ("lfoSin[i], lfoCos[i]",
                 "driftSin1[i], driftCos1[i]",
                 "driftSin2[i], driftCos2[i]"):
        if f"renormPhasor({pair});" not in lfo:
            return (f"renormLFO() no longer routes `{pair}` through the guarded "
                    "renormPhasor()")
    if re.search(r"1\.0f\s*/", lfo) or "std::sqrt" in lfo:
        return ("renormLFO() divides/sqrts a phasor itself again: every phasor "
                "must go through the guarded renormPhasor()")

    mod = method_body("renormModLFO")
    if mod is None:
        return "could not brace-match UpgradedReverb::renormModLFO()"
    if "renormPhasor(modSin, modCos);" not in mod:
        return ("renormModLFO() no longer routes modSin/modCos through the "
                "guarded renormPhasor()")
    if re.search(r"1\.0f\s*/", mod) or "std::sqrt" in mod:
        return ("renormModLFO() divides/sqrts the master LFO phasor itself "
                "again: it must go through the guarded renormPhasor()")
    return None


for path in (FX_PROC, INST_PROC, HEADER):
    if not path.exists():
        fail(f"missing source file {path}")

fx_c = FX_PROC.read_text(encoding="utf-8")
inst_c = INST_PROC.read_text(encoding="utf-8")
hdr_c = HEADER.read_text(encoding="utf-8")

for label, err in (("PluginProcessor.cpp processBlock", check_fx(fx_c)),
                   ("CorvusInstrumentProcessor.cpp processBlock",
                    check_instrument(inst_c)),
                   ("dsp/CorvusEffects.h", check_header(hdr_c))):
    if err:
        fail(f"{label}: {err}")

print("cv061-engage-from-zero: chorus/reverb beginBlock fan honest every block "
      "(FX + instrument) and all LFO phasor renormalizers reset a collapsed "
      "sin/cos pair instead of dividing by zero")


# ---------------------------------------------------------------------------
# Self-probes on mutated in-memory texts (real tree never mutated)
# ---------------------------------------------------------------------------

def probe(description, src, mutate, check):
    mutated = mutate(src)
    if mutated == src:
        fail(f"probe '{description}' mutation did not apply (stale alarm)")
    if check(mutated) is None:
        fail(f"probe '{description}' should be rejected but passed")
    print(f"cv061-engage-from-zero: self-probe fired: {description} -> rejected")


def _replace_once(txt, old, new):
    if old not in txt:
        return txt
    return txt.replace(old, new, 1)


# (a) FX processBlock: re-gate each call, delete one, and hoist one past the loop.
probe("reverb beginBlock re-gated on reverbMix > 0.001f", fx_c,
      lambda t: _replace_once(
          t, "    upgradedReverb.beginBlock(reverbSize,",
          "    if (reverbMix > 0.001f)\n        upgradedReverb.beginBlock(reverbSize,"),
      check_fx)
probe("chorus beginBlock re-gated on chorusDepth > 0.001f", fx_c,
      lambda t: _replace_once(
          t, "    chorus.beginBlock(chorusDepth",
          "    if (chorusDepth > 0.001f)\n        chorus.beginBlock(chorusDepth"),
      check_fx)
def _move_chorus_into_loop(txt):
    marker = "    chorus.beginBlock(chorusDepth, chorusMix, chorusRate);\n"
    loop_line = "    for (int s = 0; s < numSamples; ++s)\n    {\n"
    if marker not in txt or loop_line not in txt:
        return txt
    return txt.replace(marker, "", 1).replace(
        loop_line, loop_line +
        "        chorus.beginBlock(chorusDepth, chorusMix, chorusRate);\n", 1)


probe("chorus beginBlock deleted from processBlock", fx_c,
      lambda t: _replace_once(t, "    chorus.beginBlock(chorusDepth", "    // gone"),
      check_fx)
probe("chorus beginBlock moved inside the per-sample loop", fx_c,
      _move_chorus_into_loop, check_fx)

# (b) instrument chunk head: gate the chorus fan.
probe("instrument chorus beginBlock gated on chorusDepth", inst_c,
      lambda t: _replace_once(
          t, "            effects->chorus.beginBlock(",
          "            if (settings.chorusDepth > 0.001f)\n"
          "                effects->chorus.beginBlock("),
      check_instrument)
probe("instrument reverb beginBlock gated on reverbMix", inst_c,
      lambda t: _replace_once(
          t, "            effects->reverb.beginBlock(",
          "            if (settings.reverbMix > 0.001f)\n"
          "                effects->reverb.beginBlock("),
      check_instrument)

# (c) header: the guard, its reset payload, and every phasor route.
probe("renormPhasor epsilon guard tightened to a dead `magnitude < 0.0f`", hdr_c,
      lambda t: _replace_once(t, f"magnitude < {EPSILON}", "magnitude < 0.0f"),
      check_header)
probe("renormPhasor reset collapses the cosine to 0.0f too", hdr_c,
      lambda t: _replace_once(t, "cosPhase = 1.0f;", "cosPhase = 0.0f;"),
      check_header)
probe("renormLFO stops renormalising the second drift phasor", hdr_c,
      lambda t: _replace_once(t, "            renormPhasor(driftSin2[i], driftCos2[i]);\n",
                              ""),
      check_header)
probe("renormLFO divides the LFO phasor itself again", hdr_c,
      lambda t: _replace_once(
          t, "            renormPhasor(lfoSin[i], lfoCos[i]);\n",
          "            float m = std::sqrt(lfoSin[i]*lfoSin[i] + lfoCos[i]*lfoCos[i]);\n"
          "            float inv = 1.0f / m;\n"
          "            lfoSin[i] *= inv; lfoCos[i] *= inv;\n"),
      check_header)
probe("renormModLFO divides the master phasor itself again", hdr_c,
      lambda t: _replace_once(
          t, "        renormPhasor(modSin, modCos);\n",
          "        float m = std::sqrt(modSin*modSin + modCos*modCos);\n"
          "        float inv = 1.0f / m;\n"
          "        modSin *= inv; modCos *= inv;\n"),
      check_header)

# benign no-op edits must stay accepted
benign_fx = fx_c.replace(
    "// Pre-compute chorus coefficients once per block",
    "// Pre-compute chorus coefficients once per block (CV-061 heard)", 1)
if benign_fx == fx_c:
    fail("benign no-op mutation did not apply (stale alarm)")
if check_fx(benign_fx) is not None:
    fail("benign no-op comment edit in processBlock should be accepted")

benign_hdr = hdr_c.replace(
    "inline void renormPhasor(float& sinPhase, float& cosPhase)",
    "// CV-061 benign probe edit\ninline void renormPhasor(float& sinPhase, float& cosPhase)",
    1)
if benign_hdr == hdr_c:
    fail("benign header no-op mutation did not apply (stale alarm)")
if check_header(benign_hdr) is not None:
    fail("benign no-op comment edit in dsp/CorvusEffects.h should be accepted")

print("CV061-ENGAGE-FROM-ZERO OK")
sys.exit(0)
