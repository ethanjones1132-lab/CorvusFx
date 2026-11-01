#!/usr/bin/env python3
"""Headless invariant check: CV-023 smoothing-target finiteness guard (FX).

Every numeric knob is mapped on the AUDIO thread straight into a
juce::LinearSmoothedValue target:

    smooth<X>.setTargetValue(apvts.getRawParameterValue("<id>")->load() ...);

Both sites (prepareToPlay seeds, processBlock refreshes) used to hand the raw
APVTS read to the smoother with no finiteness test. A NaN, an infinity, or an
overflowed mapping (a finite raw percent whose SQUARE overflows float32, e.g.
delay_feedback's `fbRaw * fbRaw * 0.65f`) then became the smoothing target:
LinearSmoothedValue interpolates it into the audio path, and delay_feedback
carries it into the delay line's feedback state where it repeats for the rest
of the session. juce::jlimit is comparison-based and maps neither NaN nor
infinity, so no downstream clamp recovers.

The fix routes all 19 numeric targets through the file-local
`finiteSmoothingTarget(mapped, fallback)`:
  - prepareToPlay fallback: the parameter's DECLARED default carried through
    the same units/mapping (`getDefaultValue` -> `convertFrom0to1`, then
    / 100 or the delay curve) - never the previous target, never a blanket 0;
  - processBlock fallback: the smoother's CURRENT target when that is finite,
    otherwise the same declared default (lazy ternary, so the parameter
    lookup only runs on a bad read and a finite mapping is untouched).

Asserts (comment-stripped, whitespace-collapsed, brace-matched):
  (a) `finiteSmoothingTarget` is defined once, tests `mapped` first, then
      `fallback`, then returns 0 - the finite test strictly precedes use;
  (b) both real call sites route ALL 19 targets through it, in the pinned
      order, each paired with the correct fallback local computed BEFORE the
      call; the unguarded `setTargetValue(<mapped>)` form is absent;
  (c) the preparation fallback chain comes from the declared default
      (`declaredPercentTarget` / `declaredTarget` / `feedbackTarget`), and the
      prepare body never reads the previous target;
  (d) `declaredTarget` maps `getDefaultValue()` through `convertFrom0to1`;
  (e) the delay-feedback fallback curve coefficients EQUAL the real inline
      curve coefficients, and the fbRaw seed precedes the curve in both bodies;
  (f) the processBlock `master_side_drive` / `output_trim` /
      `const bool distortionBypass` trio stays consecutive (the anchor the
      raw-param drop probe relies on);
  (g) a numeric model of the helper plus the real inline curve: NaN, +Inf and
      -Inf map to the fallback, ordinary in-range values pass through
      unchanged, a finite raw percent whose square overflows float32 cannot
      reach the smoother, and a doubly-invalid pair lands on 0.

Negative self-probes on mutated in-memory texts (real tree never mutated):
  - bypass one actual target guard -> rejected;
  - remove one preparation fallback -> rejected;
  - let an invalid mapped feedback value through -> rejected;
  - retain a non-finite old target as the render fallback -> rejected;
  - benign comment edit inside prepareToPlay -> accepted (specificity).
Each probe asserts the mutation actually changed the source and that the
rejection carries the intended diagnostic.

Exit 0 = ok, 1 = violation.
"""
import math
import re
import struct
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SRC = ROOT / "source" / "DrippyFX" / "PluginProcessor.cpp"

FB_EXPR = "fbRaw * fbRaw * 0.65f + fbRaw * 0.27f"
FB_SEED = 'float fbRaw = apvts.getRawParameterValue("delay_feedback")->load() / 100.0f;'

# (smoother pascal name, param id, mapping family) in the pinned order.
# family: "pct" -> raw / 100, "native" -> raw Hz/ms, "feedback" -> delay curve.
TARGETS = [
    ("Overall", "overall", "pct"),
    ("Fatness", "fatness", "pct"),
    ("ChorusDepth", "chorus_depth", "pct"),
    ("ChorusRate", "chorus_rate", "native"),
    ("ChorusMix", "chorus_mix", "pct"),
    ("DelayTime", "delay_time", "native"),
    ("DelayFeedback", "delay_feedback", "feedback"),
    ("DelayMix", "delay_mix", "pct"),
    ("DelayDamping", "delay_damping", "pct"),
    ("DelayMod", "delay_mod", "pct"),
    ("ReverbSize", "reverb_size", "pct"),
    ("ReverbDamping", "reverb_damping", "pct"),
    ("ReverbMix", "reverb_mix", "pct"),
    ("ReverbMod", "reverb_mod", "pct"),
    ("MasterDrive", "master_drive", "pct"),
    ("MasterWidth", "master_width", "pct"),
    ("MasterMidDrive", "master_mid_drive", "pct"),
    ("MasterSideDrive", "master_side_drive", "pct"),
    ("OutputTrim", "output_trim", "pct"),
]

F32_MAX = 3.4028234663852886e38


def fail(msg):
    print("CV023-PARAM-TARGETS FAIL: %s" % msg)
    sys.exit(1)


class _Rejected(Exception):
    pass


def strip_comments(src):
    src = re.sub(r"//[^\n]*", "", src)
    src = re.sub(r"/\*.*?\*/", "", src, flags=re.S)
    return src


def collapse_ws(s):
    return re.sub(r"\s+", " ", s).strip()


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


def fn_body(flat, marker):
    k = flat.find(marker)
    if k == -1:
        raise _Rejected("could not find `%s`" % marker)
    o = flat.find("{", k)
    if o == -1:
        raise _Rejected("could not find the opening brace of `%s`" % marker)
    e = brace_span(flat, o)
    if e == -1:
        raise _Rejected("unbalanced braces extracting `%s`" % marker)
    return flat[o + 1:e]


def helper_body(flat, name):
    m = re.search(r"float\s+" + re.escape(name) + r"\s*\(", flat)
    if not m:
        raise _Rejected("helper `%s` is not defined at file scope" % name)
    o = flat.find("{", m.end())
    if o == -1:
        raise _Rejected("helper `%s` has no body brace" % name)
    e = brace_span(flat, o)
    if e == -1:
        raise _Rejected("helper `%s` body braces are unbalanced" % name)
    return flat[o + 1:e]


# ---------------------------------------------------------------------------
# Expected text (single-space form, matching collapse_ws output)
# ---------------------------------------------------------------------------

def mapped_expr(pid, family):
    if family == "pct":
        return 'apvts.getRawParameterValue("%s")->load() / 100.0f' % pid
    if family == "native":
        return 'apvts.getRawParameterValue("%s")->load()' % pid
    return FB_EXPR


def expected_call(camel, pid, family):
    return "smooth%s.setTargetValue(finiteSmoothingTarget(%s, fallback%s));" % (
        camel, mapped_expr(pid, family), camel)


def declared_expr(pid, family):
    if family == "pct":
        return 'declaredPercentTarget(apvts, "%s")' % pid
    if family == "native":
        return 'declaredTarget(apvts, "%s")' % pid
    return 'feedbackTarget(declaredPercentTarget(apvts, "delay_feedback"))'


def prep_fallback_local(camel, pid, family):
    return "const float fallback%s = %s;" % (camel, declared_expr(pid, family))


def proc_fallback_local(camel, pid, family):
    return ("const float fallback%s = std::isfinite(smooth%s.getTargetValue())"
            " ? smooth%s.getTargetValue() : %s;"
            % (camel, camel, camel, declared_expr(pid, family)))


# ---------------------------------------------------------------------------
# Numeric model (mirrors the real helper + the real inline delay curve)
# ---------------------------------------------------------------------------

def to_f32(x):
    if math.isnan(x) or math.isinf(x):
        return x
    if abs(x) > F32_MAX:
        return math.copysign(math.inf, x)
    try:
        return struct.unpack("f", struct.pack("f", x))[0]
    except OverflowError:  # pragma: no cover - rounding past float32 max
        return math.copysign(math.inf, x)


def model_finite_smoothing_target(mapped, fallback):
    """Mirror of finiteSmoothingTarget: mapped -> fallback -> 0."""
    if math.isfinite(mapped):
        return mapped
    if math.isfinite(fallback):
        return fallback
    return 0.0


def model_feedback_curve(linear_amount, quad, lin):
    """Mirror of `fbRaw * fbRaw * quad + fbRaw * lin` in float32."""
    x = to_f32(linear_amount)
    squared = to_f32(to_f32(x * x) * quad)
    linear = to_f32(x * lin)
    return to_f32(squared + linear)


def check_numeric_model(quad, lin):
    """Raise _Rejected unless the helper model behaves on the hostile cases."""
    nan = float("nan")
    inf = float("inf")

    # ordinary in-range percentage mappings pass through untouched
    for raw in (0.0, 0.1, 30.0, 37.5, 100.0):
        mapped = to_f32(raw / 100.0)
        if model_finite_smoothing_target(mapped, 0.0) != mapped:
            raise _Rejected("numeric model: in-range raw percent %r was not "
                            "passed through unchanged - a valid finite mapping "
                            "must never be replaced" % raw)

    # ordinary in-range delay curve, tied to the coefficients read from the
    # REAL inline curve at the delay-feedback call site
    curve = model_feedback_curve(0.3, quad, lin)
    expected = 0.3 * 0.3 * quad + 0.3 * lin
    if abs(curve - expected) > 1e-6:
        raise _Rejected("numeric model diverges from the pinned inline curve "
                        "(0.3 -> %r, expected %r)" % (curve, expected))
    if model_finite_smoothing_target(curve, 0.0) != curve:
        raise _Rejected("numeric model: a finite in-range delay curve value "
                        "was replaced instead of passed through")

    # NaN and both infinities must fold to a finite fallback
    for bad, name in ((nan, "NaN"), (inf, "+Infinity"), (-inf, "-Infinity")):
        got = model_finite_smoothing_target(bad, 0.25)
        if got != 0.25:
            raise _Rejected("numeric model: %s mapping did not fall back to "
                            "the supplied finite fallback (got %r)" % (name, got))

    # mapping overflow: a FINITE raw percent whose square overflows float32
    x = to_f32(1e23 / 100.0)  # 1e21: finite in float32
    if not math.isfinite(x):
        raise _Rejected("numeric model fixture drifted: 1e23/100 is no longer "
                        "a finite float32 raw percent")
    overflowed = model_feedback_curve(x, quad, lin)
    if math.isfinite(overflowed):
        raise _Rejected("numeric model fixture drifted: a finite raw percent "
                        "no longer overflows the feedback square (got %r)"
                        % overflowed)
    fallback = to_f32(0.1395)
    if model_finite_smoothing_target(overflowed, fallback) != fallback:
        raise _Rejected("numeric model: an overflowed feedback mapping reached "
                        "the smoother instead of the declared default")

    # doubly invalid: non-finite mapping AND non-finite fallback -> 0
    if model_finite_smoothing_target(nan, inf) != 0.0:
        raise _Rejected("numeric model: a doubly invalid pair did not land on 0")

    # hostile cross-product always ends finite
    for m in (nan, inf, -inf, 1e21, 0.3, -0.5):
        for f in (nan, inf, -inf, 0.0, 0.3):
            got = model_finite_smoothing_target(m, f)
            if not math.isfinite(got):
                raise _Rejected("numeric model: mapped=%r fallback=%r still "
                                "produced a non-finite target %r" % (m, f, got))


# ---------------------------------------------------------------------------
# Core assertions
# ---------------------------------------------------------------------------

def check_body(label, region, is_prepare):
    count = len(re.findall(r"smooth[A-Za-z0-9]+\.setTargetValue\(", region))
    if count != len(TARGETS):
        raise _Rejected("%s routes %d smoothing target(s) through "
                        "setTargetValue, expected %d - a dropped or duplicated "
                        "target line changes the smoothing roster"
                        % (label, count, len(TARGETS)))

    pos = -1
    for camel, pid, family in TARGETS:
        call = expected_call(camel, pid, family)
        if region.count(call) != 1:
            raise _Rejected(
                "%s target '%s' is not routed through finiteSmoothingTarget - "
                "expected `%s`; a NaN/inf/overflowed mapping would reach the "
                "smoother" % (label, pid, call))
        k = region.find(call)
        if k < pos:
            raise _Rejected("%s target '%s' arrived out of the pinned "
                            "smoothing order" % (label, pid))
        pos = k

        unguarded = "smooth%s.setTargetValue(%s);" % (camel, mapped_expr(pid, family))
        if unguarded in region:
            raise _Rejected("%s keeps an unguarded `%s` call - that mapped "
                            "value bypasses finiteSmoothingTarget"
                            % (label, unguarded))

        local = (prep_fallback_local(camel, pid, family) if is_prepare
                 else proc_fallback_local(camel, pid, family))
        if region.count(local) != 1:
            raise _Rejected(
                "%s fallback for '%s' missing or reshaped - expected `%s` "
                "(prepare fallback must be the DECLARED DEFAULT; render "
                "fallback the current finite target else the declared default)"
                % (label, pid, local))
        lk = region.find(local)
        if lk > k:
            raise _Rejected("%s fallback for '%s' is computed AFTER the "
                            "setTargetValue call - the guard would use an "
                            "unset fallback" % (label, pid))

        if is_prepare and ("smooth%s.getTargetValue()" % camel) in region:
            raise _Rejected("prepareToPlay reuses smooth%s current target as "
                            "the fallback - a repeated prepare with an invalid "
                            "value must seed from the DECLARED DEFAULT"
                            % camel)

    # delay-feedback seed must feed the curve, in both bodies
    if FB_SEED not in region:
        raise _Rejected("%s lost the fbRaw seed `%s` feeding the delay curve"
                        % (label, FB_SEED))
    if region.find(FB_SEED) > region.find(FB_EXPR):
        raise _Rejected("%s computes the delay curve before the fbRaw seed - "
                        "the mapped feedback value is not the raw read" % label)


def _verify(cpp_text):
    flat = collapse_ws(strip_comments(cpp_text))

    if flat.count("float finiteSmoothingTarget(") != 1:
        raise _Rejected("finiteSmoothingTarget must be defined exactly once at "
                        "file scope")
    if flat.find("float finiteSmoothingTarget(") > flat.find(".setTargetValue("):
        raise _Rejected("finiteSmoothingTarget is defined after its first call "
                        "site")

    hb = helper_body(flat, "finiteSmoothingTarget")
    order = ["std::isfinite(mapped)", "return mapped;",
             "std::isfinite(fallback)", "return fallback;", "return 0.0f;"]
    last = -1
    for anchor in order:
        if hb.count(anchor) != 1:
            raise _Rejected("finiteSmoothingTarget must test/return `%s` "
                            "exactly once - the mapped->fallback->0 order is "
                            "the whole guard" % anchor)
        p = hb.find(anchor)
        if p < last:
            raise _Rejected("finiteSmoothingTarget tests `%s` out of order - "
                            "the finite test must run BEFORE the value can be "
                            "returned" % anchor)
        last = p

    dt = helper_body(flat, "declaredTarget")
    if "getParameter(paramId)" not in dt:
        raise _Rejected("declaredTarget must read the declared default through "
                        "apvts.getParameter(paramId)")
    if not re.search(r"convertFrom0to1\(param->getDefaultValue\(\)\)", dt):
        raise _Rejected("declaredTarget must map getDefaultValue() through "
                        "convertFrom0to1() - the declared default has to come "
                        "through the parameter's own units")
    if "getTargetValue" in dt:
        raise _Rejected("declaredTarget reads the current target - the "
                        "preparation fallback must not reuse the previous "
                        "value")

    dpt = helper_body(flat, "declaredPercentTarget")
    if "declaredTarget(state, paramId)" not in dpt or "/ 100.0f" not in dpt:
        raise _Rejected("declaredPercentTarget must be declaredTarget / 100.0f "
                        "- a percentage fallback in the wrong units seeds the "
                        "smoother 100x high")

    ft = helper_body(flat, "feedbackTarget")
    m = re.search(r"linearAmount \* linearAmount \* ([\d.]+)f \+ "
                  r"linearAmount \* ([\d.]+)f", ft)
    if not m:
        raise _Rejected("feedbackTarget lost the quadratic feedback curve - "
                        "the preparation fallback would not land on the same "
                        "curve as a live read")
    helper_quad, helper_lin = float(m.group(1)), float(m.group(2))

    prep = fn_body(flat, "CorvusFXAudioProcessor::prepareToPlay(")
    proc = fn_body(flat, "CorvusFXAudioProcessor::processBlock(")

    m_loop = proc.find("for (int s = 0; s < numSamples")
    if m_loop == -1:
        raise _Rejected("processBlock per-sample loop not found - the update "
                        "region cannot be delimited")
    proc_region = proc[:m_loop]
    if len(proc_region) < 500:
        raise _Rejected("processBlock parameter-update region is only %d "
                        "chars - extraction drifted; do not trust green"
                        % len(proc_region))

    check_body("prepareToPlay", prep, True)
    check_body("processBlock", proc_region, False)

    # (e) the fallback curve must carry the REAL inline curve coefficients
    inline = re.search(r"fbRaw \* fbRaw \* ([\d.]+)f \+ fbRaw \* ([\d.]+)f",
                       proc_region)
    if not inline:
        raise _Rejected("processBlock lost the inline delay-feedback curve")
    quad, lin = float(inline.group(1)), float(inline.group(2))
    if (quad, lin) != (helper_quad, helper_lin):
        raise _Rejected("feedbackTarget coefficients (%r, %r) do not match the "
                        "real inline curve (%r, %r) - the prepare fallback and "
                        "the live mapping would disagree"
                        % (helper_quad, helper_lin, quad, lin))
    if FB_EXPR not in prep or FB_EXPR not in proc_region:
        raise _Rejected("the inline delay-feedback curve must stay in BOTH "
                        "bodies (prepare seed + render refresh)")

    # (f) the trio the raw-param drop probe anchors on stays consecutive
    trio = (expected_call("MasterSideDrive", "master_side_drive", "pct") + " "
            + expected_call("OutputTrim", "output_trim", "pct") + " "
            + 'const bool distortionBypass = apvts.getRawParameterValue('
              '"distortion_bypass")->load() > 0.5f;')
    if trio not in proc_region:
        raise _Rejected("processBlock master_side_drive / output_trim / "
                        "`const bool distortionBypass` must stay consecutive "
                        "(check_raw_param_ids.py drop-probe anchor)")

    # (g) numeric model tied to the real inline curve
    check_numeric_model(quad, lin)


def run_text(cpp_text):
    try:
        _verify(cpp_text)
    except _Rejected as r:
        return str(r)
    return None


# ---------------------------------------------------------------------------
# Raw (un-stripped) anchors used by the self-probes
# ---------------------------------------------------------------------------

def raw_call(camel, pid, family):
    return "    " + expected_call(camel, pid, family) + "\n"


def raw_prep_local(camel, pid, family):
    return "    " + prep_fallback_local(camel, pid, family) + "\n"


def raw_proc_local(camel, pid, family):
    return ("    const float fallback%s = std::isfinite(smooth%s.getTargetValue())\n"
            "        ? smooth%s.getTargetValue() : %s;\n"
            % (camel, camel, camel, declared_expr(pid, family)))


def main():
    if not SRC.exists():
        fail("missing source file %s" % SRC)
    text = SRC.read_text(encoding="utf-8")

    # ---- positive control: the live source must satisfy every property ----
    verdict = run_text(text)
    if verdict is not None:
        fail(verdict)
    print("cv023-parameter-targets: 19 targets guarded in prepareToPlay + "
          "processBlock, declared-default fallbacks pinned")

    # ---- negative probes (in-memory mutations; each must be REJECTED) ----
    probes = [
        ("bypass one actual target guard (prepareToPlay output_trim)",
         lambda s: s.replace(
             raw_call("OutputTrim", "output_trim", "pct"),
             '    smoothOutputTrim.setTargetValue(apvts.getRawParameterValue('
             '"output_trim")->load() / 100.0f);\n', 1),
         "finiteSmoothingTarget"),
        ("remove the preparation fallback (overall)",
         lambda s: s.replace(raw_prep_local("Overall", "overall", "pct"), "", 1),
         "prepareToPlay fallback"),
        ("let an invalid mapped feedback value through (prepareToPlay)",
         lambda s: s.replace(
             raw_call("DelayFeedback", "delay_feedback", "feedback"),
             "    smoothDelayFeedback.setTargetValue(%s);\n" % FB_EXPR, 1),
         "finiteSmoothingTarget"),
        ("retain a non-finite old target as the render fallback (overall)",
         lambda s: s.replace(
             raw_proc_local("Overall", "overall", "pct"),
             "    const float fallbackOverall = smoothOverall.getTargetValue();\n",
             1),
         "processBlock fallback"),
    ]

    for label, mutate, expect in probes:
        mutated = mutate(text)
        if mutated == text:
            fail("no-op probe (%s): mutation did not change the source - the "
                 "negative check is vacuous" % label)
        verdict = run_text(mutated)
        if verdict is None:
            fail("negative probe '%s' was NOT rejected - checker is vacuous"
                 % label)
        if expect not in verdict:
            fail("negative probe '%s' rejected for the wrong reason (expected "
                 "%r in the diagnostic, got %r)" % (label, expect, verdict))
        print("cv023-parameter-targets: negative probe '%s' rejected (%s)"
              % (label, verdict[:90]))

    # ---- benign no-op edit must still pass (probe specificity) ----
    neutral = text.replace(
        "    const double smoothTime = 0.02; // 20ms",
        "    // benign probe edit\n"
        "    const double smoothTime = 0.02; // 20ms", 1)
    if neutral == text:
        fail("no-op guard: the benign comment edit did not change the source")
    if run_text(neutral) is not None:
        fail("benign comment edit inside prepareToPlay was REJECTED - checker "
             "over-fires: %s" % run_text(neutral))
    print("cv023-parameter-targets: benign comment edit passes (specificity "
          "proven)")

    # ---- final re-verification of the real source ----
    final = run_text(SRC.read_text(encoding="utf-8"))
    if final is not None:
        fail("final source re-verification failed: %s" % final)
    print("cv023-parameter-targets: OK")
    sys.exit(0)


if __name__ == "__main__":
    main()
