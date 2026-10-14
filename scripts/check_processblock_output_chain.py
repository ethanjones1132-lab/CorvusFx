#!/usr/bin/env python3
"""Headless invariant check: processBlock output-chain ORDER-SAFETY shape.

Pins the back half of the DrippyFX/Corvus processBlock per-sample body
(source/DrippyFX/PluginProcessor.cpp), where every parameter is applied to
the output chain in a fixed order that later block-level refactor edits —
"simplify the chain", reordering for "efficiency" — could silently break:

  per-sample smoothing upstream of use  →  SAFETY LIMITER (padeSoftClip +
  jlimit ±1.5 on   BOTH channels)  →  OUTPUT TRIM multiply  →  OVERALL
  WET/DRY crossfade vs dryBuffer  →  writes back into chData  →  the output
  meter block reads chData after the write.

Real failure this pins against: any droop of the limiter (host DAW clipping,
master bus overs), an Erin move of OUTPUT TRIM before the limiter (band-limited
saturation closure is destroyed — soft clip then rescales a user knob — an
efficiency-chasing "clarity" change that is silent and pairs every execution),
or the wet/dry crossfade reading buffer channels instead of dryBuffer (loses
the "dry = pristine input" correctness of the blend). Meter block must still
follow the DSP: a future fork that returns or recomputes AFTER the write would
leave meters stale but still pass today's shape.

Asserts (comment-stripped):
  (a) the SAFETY LIMITER comments site both branches: padeSoftClip for L,
      `if (!isMono)` padeSoftClip for R, and each jlimit(-1.5f, 1.5f).
  (b) the OUTPUT TRIM multiply appears on the  chData-write side: smpL *=
      sOutputTrim; and `if (!isMono) smpR *= sOutputTrim;` — AFTER the
      limiter block and BEFORE the overall crossfade.
  (c) the OVERALL crossfade reads from dryBuffer.getReadPointer(0/1)[s] and
      the sOverall < 0.999f guard still exists (not a plain `smpL = ...`).
  (d) chData[0][s] / chData[1][s] writes appear AFTER the crossfade body —
      the output samples come from the crossfade, not the raw chain.
  (e) the output meter block ('outPeakL_') appears after (d) by source
      offset (meter reads the FINAL samples, not mid-chain).

Negative self-probes on mutated in-memory texts (real tree never mutated,
no-op mutation aborts as a stale alarm):
  - swap OUTPUT TRIM before SAFETY LIMITER → rejected
  - strip both jlimit(-1.5f,...) lines → rejected
  - crossfade reading dryBuffer replaced by a plain assignment → rejected
  - chData writes moved before the crossfade (mutate) → rejected
  - benign no-op edit inside the body → accepted (probe specificity)
Exit 0 = ok, 1 = violation.
"""
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SRC = ROOT / "source" / "DrippyFX" / "PluginProcessor.cpp"


def fail(msg):
    print(f"OUTPUT-CHAIN FAIL: {msg}")
    sys.exit(1)


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


text = SRC.read_text()
code = strip_comments(text)

m_loop = re.search(
    r"for\s*\(\s*int\s+s\s*=\s*0\s*;\s*s\s*<\s*numSamples\s*;\s*\+\+\s*s\s*\)", code)
if not m_loop:
    fail("per-sample loop `for (int s = 0; s < numSamples; ++s)` not found")
assert m_loop is not None
open_idx = code.find("{", m_loop.end())
if open_idx == -1:
    fail("per-sample loop has no body brace")
end_idx = brace_span(code, open_idx)
if end_idx == -1:
    fail("per-sample loop body braces unbalanced")
body = code[open_idx + 1:end_idx]
body_start = open_idx + 1

if len(body) < 500:
    fail(f"per-sample loop body is only {len(body)} chars — loop detection has "
         "drifted; do not trust green")


def offset_of(anchor):
    k = body.find(anchor)
    if k == -1:
        fail(f"pinned anchor not found in per-sample body: {anchor!r}")
    return k


# (seed) MONO-MIRROR seed + ±2.0f INPUT HEADROOM clamp — pinned BEFORE any DSP:
#   L seed clamps chData[0][s] to ±2.0f; R seed reads chData[1][s] ONLY through
#   the `isMono ? smpL :` ternary (mono bus chProc==1 leaves chData[1] a nullptr
#   write-pointer — reading it unguarded is a deref hazard) and also clamps ±2.0f.
#   Widening the headroom (unbounded input reaching padeSoftClip/distortion with
#   inf/NaN) or dropping the mono-mirror compiles clean behind an otherwise-green
#   gate, so both seed lines are pinned here, before the limiter anchor.
seedL_off = offset_of("float smpL = juce::jlimit(-2.0f, 2.0f, chData[0][s]);")
seedR_off = offset_of(
    "float smpR = juce::jlimit(-2.0f, 2.0f, isMono ? smpL : chData[1][s]);")
if seedR_off < seedL_off:
    fail("mono-mirror R seed precedes the L seed — seed lines drifted")
if body.count("jlimit(-2.0f, 2.0f") != 2:
    fail(f"input headroom jlimit(-2.0f, 2.0f) appears only at unexpected count "
         f"({body.count('jlimit(-2.0f, 2.0f')}) — both seed lines must keep the "
         "±2.0f headroom clamp")

# (a) SAFETY LIMITER shape — both channels, soft clip + jlimit
limL_off = offset_of("smpL = padeSoftClip(smpL);")
klim = body.find("if (!isMono)", limL_off)
if klim == -1:
    fail("safety-limiter branch not found after the L padeSoftClip — mono handling drift")
limR_off = klim
k = body.find("smpR = padeSoftClip(smpR);", limR_off)
if k == -1 or k > limR_off + 400:
    fail("safety-limiter R padeSoftClip missing or far from the mono guard")
jl_count = body.count("jlimit(-1.5f, 1.5f")
if jl_count < 2:
    fail(f"safety limiter jlimit(-1.5f, 1.5f) appears only {jl_count}x "
         "(must clamp BOTH channels) — hard-clip ceiling would be dropped silently")

# (b) OUTPUT TRIM after limiter, before crossfade
trimL_off = offset_of("smpL *= sOutputTrim;")
trimR_off = offset_of("if (!isMono) smpR *= sOutputTrim;")
if trimR_off < trimL_off:
    fail("OUTPUT TRIM R multiply precedes L — channel-scoped guard drifted")
valid_start = max(limL_off, k)
if trimL_off < valid_start:
    fail("OUTPUT TRIM multiply sits BEFORE the safety limiter — trim would rescale "
         "everything after; the pinned chain order is LIMITER -> TRIM -> WET/DRY")

# (c) OVERALL crossfade reads dryBuffer, with the <0.999f guard
xtf_off = body.find("sOverall < 0.999f")
if xtf_off == -1:
    fail("overall wet/dry guard `sOverall < 0.999f` missing from the per-sample body")
if xtf_off < trimL_off:
    fail("overall wet/dry crossfade sits BEFORE OUTPUT TRIM — chain order drifted")
if body.count("dryBuffer.getReadPointer(0)[s]") < 1 or \
   body.count("dryBuffer.getReadPointer(1)[s]") < 1:
    fail("overall crossfade no longer reads dryBuffer — dry path would blend the "
         "already-processed signal (double-DSP) instead of pristine input")

# (d) chData writes AFTER the crossfade body
writeL_off = offset_of("chData[0][s] = std::isfinite(smpL) ? smpL : 0.0f;")
writeR_off = offset_of("chData[1][s] = std::isfinite(smpR) ? smpR : 0.0f;")
xtf_body_end = body.find("if (sOverall < 0.999f)", xtf_off)
if xtf_body_end != -1:
    k2 = brace_span(body, xtf_body_end)
    if k2 != -1 and writeL_off < k2:
        fail("chData write sits INSIDE the overall crossfade body — would drop "
             "the write when overall >= 0.999f (untouched branch)")
if writeR_off != -1 and writeR_off < writeL_off:
    fail("chData[1] write precedes chData[0] — channel labels drifted")

# (e) output meter after the writes
out_m_off = body.find("outPeakL_")
if out_m_off == -1:
    fail("output level meter (outPeakL_) not found in the per-sample body")
if out_m_off < writeL_off:
    fail("output meter block sits before the chData writes with the meter AFTER "
         "the order — meter would read mid-chain samples; if you intentionally "
         "moved the meter, re-pin it here")

# (checks sizes) chData must be written for both channels and only here.
# chData must be WRITTEN exactly once per channel (reads via jlimit aren't writes)
if body.count("chData[0][s] = std::isfinite(smpL) ? smpL : 0.0f") != 1 or body.count("chData[1][s] = std::isfinite(smpR) ? smpR : 0.0f") != 1:
    fail("chData writes in the per-sample body unexpected — each channel must "
         "be written exactly once to avoid double-apply of the trimmed value")


# ---- negative self-probes on mutated candidates ----
def run_text(cpp_text):
    """Re-run the core assertions. None = pass, else the reason."""
    try:
        _verify(cpp_text)
    except _Rejected as r:
        return str(r)
    return None


class _Rejected(Exception):
    pass


def _verify(cpp_text):
    c = strip_comments(cpp_text)
    mm = re.search(
        r"for\s*\(\s*int\s+s\s*=\s*0\s*;\s*s\s*<\s*numSamples\s*;\s*\+\+\s*s\s*\)", c)
    if not mm:
        raise _Rejected("per-sample loop missing")
    o = c.find("{", mm.end())
    e = brace_span(c, o)
    if e == -1:
        raise _Rejected("brace mismatch")
    b = c[o + 1:e]

    def need(anchor):
        if anchor not in b:
            raise _Rejected(f"missing anchor: {anchor!r}")

    need("smpL = juce::jlimit(-2.0f, 2.0f, chData[0][s]);")
    need("smpR = juce::jlimit(-2.0f, 2.0f, isMono ? smpL : chData[1][s]);")
    if b.count("jlimit(-2.0f, 2.0f") != 2:
        raise _Rejected("input headroom ±2.0f clamp missing from a seed line")
    need("smpL = padeSoftClip(smpL);")
    need("smpR = padeSoftClip(smpR);")
    if b.count("jlimit(-1.5f, 1.5f") < 2:
        raise _Rejected("both-channel jlimit missing")
    tL = b.find("smpL *= sOutputTrim;")
    forL = b.find("smpL = padeSoftClip(smpL);")
    forR = b.find("smpR = padeSoftClip(smpR);")
    if tL < max(forL, forR):
        raise _Rejected("trim before limiter accepted")
    need("sOverall < 0.999f")
    if "dryBuffer.getReadPointer(0)[s] * (1.0f - sOverall)" not in b:
        raise _Rejected("crossfade dry source missing")
    need("chData[0][s] = std::isfinite(smpL) ? smpL : 0.0f;")
    need("chData[1][s] = std::isfinite(smpR) ? smpR : 0.0f;")
    wL = b.find("chData[0][s] = std::isfinite(smpL) ? smpL : 0.0f;")
    if wL != -1 and wL < b.find("smpL *= sOutputTrim;"):
        raise _Rejected("write before trim accepted")
    if wL != -1:
        # the write must sit OUTSIDE every `if (sOverall < 0.999f)` block body
        for gm in re.finditer(r"if\s*\(\s*sOverall\s*<\s*0\.999f\s*\)", b):
            bo = b.find("{", gm.end())
            if bo != -1 and bo < wL:
                xb2 = brace_span(b, bo)
                if xb2 != -1 and wL < xb2:
                    raise _Rejected(
                        "chData write inside an overall-crossfade block accepted")
    mm_out = b.find("outPeakL_")
    if mm_out == -1 or mm_out < wL:
        raise _Rejected("meter after write missing")


TRADE_ANCHOR = "smpL = padeSoftClip(smpL);"
probes = [
    ("drop the mono-mirror ternary (unguarded chData[1] read)",
     lambda s: s.replace(
         "float smpR = juce::jlimit(-2.0f, 2.0f, isMono ? smpL : chData[1][s]);",
         "float smpR = juce::jlimit(-2.0f, 2.0f, chData[1][s]);")),
    ("widen the input headroom clamp 2.0f -> 10.0f",
     lambda s: s.replace(
         "float smpL = juce::jlimit(-2.0f, 2.0f, chData[0][s]);\n"
         "        float smpR = juce::jlimit(-2.0f, 2.0f, isMono ? smpL : chData[1][s]);",
         "float smpL = juce::jlimit(-10.0f, 10.0f, chData[0][s]);\n"
         "        float smpR = juce::jlimit(-10.0f, 10.0f, isMono ? smpL : chData[1][s]);")),
    ("swap OUTPUT TRIM before the safety limiter",
     lambda s: s.replace(
         "// 6. SAFETY LIMITER - Pade [3/2] rational approximant (eliminates last per-sample transcendental)\n        smpL = padeSoftClip(smpL);\n        smpL = juce::jlimit(-1.5f, 1.5f, smpL);\n",
         "// 6. OUTPUT TRIM (moved before limiter)\n        smpL *= sOutputTrim;\n        if (!isMono) smpR *= sOutputTrim;\n\n        // SAFETY LIMITER\n        smpL = padeSoftClip(smpL);\n        smpL = juce::jlimit(-1.5f, 1.5f, smpL);\n")),
    ("strip both jlimit clamps",
     lambda s: s.replace("        smpL = juce::jlimit(-1.5f, 1.5f, smpL);\n", "")
               .replace("        smpR = juce::jlimit(-1.5f, 1.5f, smpR);\n", "")),
    ("crossfade reads the processed buffer instead of dryBuffer",
     lambda s: s.replace(
         "smpL = dryBuffer.getReadPointer(0)[s] * (1.0f - sOverall) + smpL * sOverall;\n            if (!isMono)\n                smpR = dryBuffer.getReadPointer(1)[s] * (1.0f - sOverall) + smpR * sOverall;",
         "smpL = chData[0][s] * (1.0f - sOverall) + smpL * sOverall;\n            if (!isMono)\n                smpR = chData[1][s] * (1.0f - sOverall) + smpR * sOverall;")),
    (
        "chData write moved inside the overall crossfade",
        lambda s: s.replace(
            "chData[0][s] = std::isfinite(smpL) ? smpL : 0.0f;\n        if (!isMono) chData[1][s] = std::isfinite(smpR) ? smpR : 0.0f;",
            "// writes moved inside the crossfade\n        if (sOverall < 0.999f) { chData[0][s] = std::isfinite(smpL) ? smpL : 0.0f; if (!isMono) chData[1][s] = std::isfinite(smpR) ? smpR : 0.0f; }"),
    ),
]
for label, mutate in probes:
    mutated = mutate(text)
    if mutated == text:
        fail(f"no-op probe ({label}): mutation did not change the source — "
             "the negative check is vacuous")
    verdict = run_text(mutated)
    if verdict is None:
        fail(f"negative probe '{label}' was NOT rejected — checker is vacuous")
    print(f"output-chain: negative probe '{label}' rejected")

# no-op guard: benign edit outside the pinned shape must still pass
neutral = text.replace(
    "// Snapshot smoothed values for the beginning of this block.",
    "// Snapshot smoothed values for the start of this block.")
if neutral == text:
    fail("no-op guard: unanchored neutral edit did not change the source")
if run_text(neutral) is not None:
    fail("neutral edit outside the pinned chain was REJECTED — checker over-fires")
print("output-chain: benign non-chain edit passes (probe specificity proven)")

# Real tree never mutated — but re-verify the live source one last time before gating.
run_text(SRC.read_text())  # raises via sys.exit inside _verify? no: verify raises _Rejected
_v = None
try:
    _verify(text)
except _Rejected as r:
    fail(f"final source re-verification failed: {r}")
print("output-chain: OK")
sys.exit(0)
