#!/usr/bin/env python3
"""check_shared_dsp_utils.py — pin the three shared-utility DSP functions that
the Corvus Instrument vertical slice Plan's Task 2 extraction must preserve
byte-stable (docs/superpowers/plans/2026-08-08-corvus-instrument-vertical-slice.md:
Task 2 "Preserves: hermiteInterp, padeTanh, padeSoftClip").

SoT: source/DrippyFX/PluginProcessor.h
  - hermiteInterp  (~line 14): Hermite cubic, c1/c2/c3 coefficient set with the
    0.5f tangents, 2.0f/2.5f/0.5f quadratic terms, and Horner return order.
  - padeTanh       (~line 37): Padé [3/2] rational approximant
    z*(15+z²)/(15+6z²) with the ±2.5 saturation clamp.
  - padeSoftClip   (~line 51): same Padé core around a threshold with
    (|x|-threshold)*0.5 z shaping and a scale factor.

A mechanical-move edit into dsp/CorvusEffects.h must keep these bodies intact:
this checker pins the key constants and algebraic shape of each function so a
silently reordered c2/c3 coefficient or swapped Padé numerator term fails the
gate headless.

Checks (on comment-stripped, real source):
  1. hermiteInterp: inline float signature at PluginProcessor.h; wrap lambda;
     c0..c3 locals; 0.5f * (x1 - xm1); 2.5f/2.0f/0.5f quadratic coefficients;
     Horner form ((c3 * frac + c2) * frac + c1) * frac + c0.
  2. padeTanh: inline float signature; 2.5f saturation test; z2 = z*z;
     z * (15 + z2) / (15 + 6 * z2) rational shape with the exact literals.
  3. padeSoftClip: inline float with threshold/scale defaults 1.0f/0.2f;
     both sign branches present; z = (x ∓ threshold) * 0.5f in each;
     Padé rational with * scale in both branches; pass-through return x.
Negative probes (mutated copies, never the real tree — each must be REJECTED):
  N1. swap the Padé numerator constants (z2 -> 18) in padeTanh -> FAIL
  N2. drop one hermite mask/quadratic term -> FAIL
  N3. swap hermite c2/c3 coefficient literals -> FAIL
  N4. drop the padeSoftClip negative branch -> FAIL
Exit 0 only when the real source passes and every negative fires.
"""

import os
import re
import sys
import tempfile
import shutil

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
HDR = os.path.join(ROOT, "source", "DrippyFX", "PluginProcessor.h")


def strip_comments(src: str) -> str:
    out = []
    i, n = 0, len(src)
    while i < n:
        if src.startswith("//", i):
            j = src.find("\n", i)
            i = n if j < 0 else j
        elif src.startswith("/*", i):
            j = src.find("*/", i + 2)
            i = n if j < 0 else j + 2
        else:
            out.append(src[i])
            i += 1
    return "".join(out)


def _body(func: str, code: str) -> str:
    """Source region from the function's signature to the next top-level
    'inline' or 'struct' marker (slashes normalized so the regexes don't need
    /-lookalikes)."""
    m = re.search(r"\binline\s+float\s+" + func + r"\s*\(", code)
    if not m:
        return ""
    start = m.start()
    nxt = re.search(r"\n\s*inline\s+|\n\s*struct\s+", code[m.end():])
    end = m.end() + (nxt.start() if nxt else len(code) - m.end())
    return code[start:end].replace("/", "÷")


def checks(code: str):
    """Return list of (label, ok, detail)."""
    res = []

    # ---- hermiteInterp ----
    hb = _body("hermiteInterp", code)
    res.append(("hermiteInterp exists as inline float",
                "hermiteInterp" in hb and "int idx" in hb, "signature + body found"))
    res.append(("hermiteInterp: wrap lambda with modulo wrap",
                re.search(r"wrap\s*=\s*\[bufSize\]\s*\(int\s*p\)\s*->\s*int\s*\{", hb) is not None,
                "wrap lambda"))
    for v in ("xm1", "x0", "x1", "x2", "c0", "c1", "c2", "c3", "frac"):
        res.append(("hermiteInterp: declares %s" % v,
                    re.search(r"float\s+" + v + r"\b", hb) is not None, v))
    res.append(("hermiteInterp: tangent-term literal 0.5f * (x1 - xm1)",
                re.search(r"0\.5f\s*\*\s*\(\s*x1\s*-\s*xm1\s*\)", hb) is not None,
                "c1 shape"))
    # c2:  xm1 - 2.5f*x0 + 2.0f*x1 - 0.5f*x2 — all four terms, any spacing
    c2 = re.search(r"c2\s*=\s*xm1\s*-\s*2\.5f\s*\*\s*x0\s*\+\s*2\.0f\s*\*\s*x1\s*-\s*0\.5f\s*\*\s*x2\s*;", hb)
    res.append(("hermiteInterp: c2 quadratic retains 2.5f·x0 + 2.0f·x1 − 0.5f·x2",
                c2 is not None, "c2 terms present and ordered"))
    c3 = re.search(r"c3\s*=\s*0\.5f\s*\*\s*\(\s*x2\s*-\s*xm1\s*\)\s*\+\s*1\.5f\s*\*\s*\(\s*x0\s*-\s*x1\s*\)\s*;", hb)
    res.append(("hermiteInterp: c3 cubic term retains 0.5f·(x2−xm1) + 1.5f·(x0−x1)",
                c3 is not None, "c3 shape"))
    ret = re.search(r"return\s+\(\(c3\s*\*\s*frac\s*\+\s*c2\)\s*\*\s*frac\s*\+\s*c1\)\s*\*\s*frac\s*\+\s*c0\s*;", hb)
    res.append(("hermiteInterp: Horner return order ((c3·f+c2)·f+c1)·f+c0",
                ret is not None, "Horner form"))

    # ---- padeTanh ----
    tb = _body("padeTanh", code)
    res.append(("padeTanh exists as inline float",
                "padeTanh" in tb and "fabsf" in tb, "signature found"))
    res.append(("padeTanh: |z| > 2.5f saturation clamp to ±1",
                re.search(r"if\s*\(\s*a\s*>\s*2\.5f\s*\)\s*return\s+z\s*>\s*0\s*\?\s*1\.0f\s*:\s*-1\.0f\s*;", tb) is not None,
                "saturation branch"))
    res.append(("padeTanh: z2 = z * z precompute",
                re.search(r"z2\s*=\s*z\s*\*\s*z\s*;", tb) is not None, "z2"))
    rat = re.search(r"return\s+z\s*\*\s*\(\s*15\.0f\s*\+\s*z2\s*\)\s*÷\s*\(\s*15\.0f\s*\+\s*6\.0f\s*\*\s*z2\s*\)\s*;", tb)
    res.append(("padeTanh: Padé [3/2] rational z·(15+z²)÷(15+6z²) exact literals",
                rat is not None, "numerator 15.0f+z2, denominator 15.0f+6.0f*z2"))

    # ---- padeSoftClip ----
    sb = _body("padeSoftClip", code)
    res.append(("padeSoftClip exists as inline float with defaults 1.0f/0.2f",
                re.search(r"padeSoftClip\s*\(\s*float\s+x\s*,\s*float\s+threshold\s*=\s*1\.0f\s*,\s*float\s+scale\s*=\s*0\.2f\s*\)", sb) is not None,
                "signature"))
    pos = re.search(r"if\s*\(\s*x\s*>\s*threshold\s*\)", sb)
    neg = re.search(r"else\s+if\s*\(\s*x\s*<\s*-threshold\s*\)", sb)
    res.append(("padeSoftClip: positive overload branch x > threshold", pos is not None, "pos branch"))
    res.append(("padeSoftClip: negative overload branch x < -threshold", neg is not None, "neg branch"))
    pos_z = re.search(r"z\s*=\s*\(\s*x\s*-\s*threshold\s*\)\s*\*\s*0\.5f\s*;", sb)
    neg_z = re.search(r"z\s*=\s*\(\s*x\s*\+\s*threshold\s*\)\s*\*\s*0\.5f\s*;", sb)
    res.append(("padeSoftClip: z = (x − threshold)·0.5f shaping in + branch",
                pos_z is not None, "+branch z"))
    res.append(("padeSoftClip: z = (x + threshold)·0.5f shaping in − branch",
                neg_z is not None, "−branch z"))
    pos_rat = re.search(r"threshold\s*\+\s*z\s*\*\s*\(\s*15\.0f\s*\+\s*z2\s*\)\s*÷\s*\(\s*15\.0f\s*\+\s*6\.0f\s*\*\s*z2\s*\)\s*\*\s*scale\s*;", sb)
    neg_rat = re.search(r"-threshold\s*\+\s*z\s*\*\s*\(\s*15\.0f\s*\+\s*z2\s*\)\s*÷\s*\(\s*15\.0f\s*\+\s*6\.0f\s*\*\s*z2\s*\)\s*\*\s*scale\s*;", sb)
    res.append(("padeSoftClip: + branch Padé rational · scale (exact literals)",
                pos_rat is not None, "+branch rational"))
    res.append(("padeSoftClip: − branch Padé rational · scale (exact literals)",
                neg_rat is not None, "−branch rational"))
    res.append(("padeSoftClip: in-band pass-through return x",
                re.search(r"return\s+x\s*;", sb) is not None, "pass-through"))
    return res


def run(src: str, verbose=True):
    code = strip_comments(src)
    ok = True
    for label, good, detail in checks(code):
        if verbose:
            print(("PASS " if good else "FAIL ") + "shared-dsp-utils: " + label +
                  " (%s)" % detail)
        ok = ok and good
    return 0 if ok else 1


def main():
    if not os.path.isfile(HDR):
        print("GATE_FAIL: %s missing" % HDR)
        return 1
    with open(HDR, "r", encoding="utf-8") as f:
        src = f.read()
    if run(src) != 0:
        return 1

    negatives = [
        ("swap the padeTanh numerator constant 15.0f -> 18.0f",
         lambda s: _swap_first(s, "return z * (15.0f + z2) / (15.0f + 6.0f * z2);",
                               "return z * (18.0f + z2) / (15.0f + 6.0f * z2);")),
        ("drop hermiteInterp's 2.0f·x1 quadratic term",
         lambda s: _swap_first(s, "+ 2.0f * x1 - 0.5f * x2;",
                               "            - 0.5f * x2;")),
        ("swap hermiteInterp c2/c3 literal group (2.5f<->0.5f in c2)",
         lambda s: _swap_first(s, "c2 = xm1 - 2.5f * x0 + 2.0f * x1 - 0.5f * x2;",
                               "c2 = xm1 - 0.5f * x0 + 2.0f * x1 - 2.5f * x2;")),
        ("drop the padeSoftClip negative-overflow branch",
         lambda s: _swap_first(s, "else if (x < -threshold)\n    {", "{")),
    ]

    tmpdir = tempfile.mkdtemp(prefix="check_shared_dsp_")
    try:
        for label, mutate in negatives:
            mutated = mutate(src)
            if mutated == src:
                print("GATE_FAIL: negative '%s' mutation is a no-op — "
                      "checker stale vs source" % label)
                return 1
            p = os.path.join(tmpdir, "PluginProcessor.h")
            with open(p, "w", encoding="utf-8") as f:
                f.write(mutated)
            if run(mutated, verbose=False) == 0:
                print("GATE_FAIL: negative check '%s' did NOT fail — "
                      "checker too weak" % label)
                return 1
            print("PASS shared-dsp-utils: negative rejected -> " + label)
    finally:
        shutil.rmtree(tmpdir, ignore_errors=True)

    print("OK shared DSP utilities pinned (hermiteInterp / padeTanh / "
          "padeSoftClip bodies guarded for the Task-2 extraction)")
    return 0


def _swap_first(src, old, new):
    """Replace the FIRST occurrence of old with new (returns src unchanged if absent)."""
    i = src.find(old)
    if i < 0:
        return src
    return src[:i] + new + src[i + len(old):]


if __name__ == "__main__":
    sys.exit(main())
