#!/usr/bin/env python3
"""Headless invariant check: CV-082 finiteness guards must survive /fp:fast.

The product targets compile with MSVC /fp:fast. Under those flags the compiler
may assume every float is finite, so a guard written as `std::isfinite(x)` on a
value that came out of arithmetic can be folded to `true` and the guard becomes
unreachable in the shipped binary - the source text looks safe while the binary
has no containment at all.

The fix is one file-local helper that classifies the IEEE-754 exponent bits:

    inline bool isFiniteFloat (float value) noexcept
    {
        static_assert (sizeof (float) == sizeof (std::uint32_t), "IEEE-754 float expected");
        std::uint32_t bits = 0;
        std::memcpy (&bits, &value, sizeof (bits));
        return (bits & 0x7f800000u) != 0x7f800000u;
    }

It answers exactly what std::isfinite answers (NaN and both infinities false,
everything else true) but the answer is computed from the bits, so /fp:fast
cannot fold it away. The same bit test already backs the render harness
(tests/CorvusRenderHarness.h: isNormalOrZero) and the offline render tool
(tools/CorvusOfflineRender.cpp: isFiniteFloat).

Asserts (comment-stripped; guard sites whitespace-collapsed):
  (a) neither PluginProcessor.cpp nor PluginProcessor.h calls isfinite() any
      more - every guard went through the bit-test helper, so no compiler
      builtin finiteness test can be folded to true;
  (b) the helper is defined exactly once (header or .cpp), copies the float
      through memcpy/bit_cast, and its returned predicate is exactly
      `(bits & 0x7f800000u) != 0x7f800000u`;
  (c) every guard that contained std::isfinite still exists exactly once and
      now calls the helper:
        - finiteSmoothingTarget's mapped / fallback branches,
        - foldNonFiniteSamples' per-sample fold,
        - the 19 processBlock smoothing fallbacks (one per numeric knob),
        - the two CV-023 input sanitiser lines,
        - the two post-chain chData output writes.
      Behaviour is otherwise unchanged: same conditions, same fallbacks.

Negative self-probes on mutated in-memory texts (the real tree is never
mutated), each asserting the mutation APPLIED before asserting rejection and
that the rejection carries the intended diagnostic:
  - pre-patch shape: every guard calls std::isfinite again -> rejected;
  - one fallback guard reverted to std::isfinite -> rejected;
  - an input sanitiser line deleted -> rejected;
  - a processBlock fallback declaration deleted -> rejected;
  - the helper stops using the bit test (`return true;`) -> rejected;
  - the bit-test mask flipped to a comparison that is not the exponent test
    -> rejected;
  - the helper stops copying through memcpy/bit_cast -> rejected;
  - benign probes ACCEPTED: a comment added next to the helper, and a guard
    reflowed across two lines - the pin is content, not formatting.

Exit 0 = ok, 1 = violation, 2 = setup/read failure.
"""
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
CPP_PATH = ROOT / "source" / "DrippyFX" / "PluginProcessor.cpp"
HDR_PATH = ROOT / "source" / "DrippyFX" / "PluginProcessor.h"

HELPER = "isFiniteFloat"
MASK_RE = re.compile(r"\(\s*bits\s*&\s*0x7f800000u\s*\)\s*!=\s*0x7f800000u")
HELPER_DEF_RE = re.compile(
    r"\binline\s+bool\s+" + HELPER + r"\s*\(\s*float\s+[A-Za-z_]\w*\s*\)\s*noexcept")
ISFINITE_CALL_RE = re.compile(r"\bisfinite\s*\(")

# (smoother pascal name, param id, mapping family) in the pinned order. A copy
# of the CV-023 roster: each knob's render fallback must stay guarded.
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

INPUT_GUARD_L = "smpL = isFiniteFloat(smpL) ? smpL : 0.0f;"
INPUT_GUARD_R = "smpR = isFiniteFloat(smpR) ? smpR : 0.0f;"
OUTPUT_GUARD_L = "chData[0][s] = isFiniteFloat(smpL) ? smpL : 0.0f;"
OUTPUT_GUARD_R = "if (!isMono) chData[1][s] = isFiniteFloat(smpR) ? smpR : 0.0f;"


def fail(msg):
    print("CV082-FINITE-GUARDS FAIL: %s" % msg)
    sys.exit(1)


class _Rejected(Exception):
    pass


def strip_comments(src):
    src = re.sub(r"/\*.*?\*/", "", src, flags=re.S)
    return re.sub(r"//[^\n]*", "", src)


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


def declared_expr(pid, family):
    if family == "pct":
        return 'declaredPercentTarget(apvts, "%s")' % pid
    if family == "native":
        return 'declaredTarget(apvts, "%s")' % pid
    return 'feedbackTarget(declaredPercentTarget(apvts, "delay_feedback"))'


def fallback_line(camel, pid, family):
    return ("const float fallback%s = isFiniteFloat(smooth%s.getTargetValue())"
            " ? smooth%s.getTargetValue() : %s;"
            % (camel, camel, camel, declared_expr(pid, family)))


GUARD_SITES = [
    ("finiteSmoothingTarget mapped branch",
     "if (isFiniteFloat(mapped)) return mapped;"),
    ("finiteSmoothingTarget fallback branch",
     "if (isFiniteFloat(fallback)) return fallback;"),
    ("foldNonFiniteSamples per-sample fold",
     "if (!isFiniteFloat(samples[i])) samples[i] = 0.0f;"),
    ("CV-023 input sanitiser left", INPUT_GUARD_L),
    ("CV-023 input sanitiser right", INPUT_GUARD_R),
    ("post-chain output guard left", OUTPUT_GUARD_L),
    ("post-chain output guard right", OUTPUT_GUARD_R),
]
GUARD_SITES += [
    ("processBlock fallback for %s" % pid, fallback_line(camel, pid, family))
    for camel, pid, family in TARGETS
]

EXPECTED_GUARDS = 26  # 2 + 1 + 19 + 2 + 2


def _verify(cpp_text, hdr_text):
    """Raise _Rejected on any violation. None returned on success."""
    cpp = strip_comments(cpp_text)
    hdr = strip_comments(hdr_text)
    combined = cpp + "\n" + hdr

    # (a) no compiler finiteness builtin survives in the FX processor
    for label, code in (("PluginProcessor.cpp", cpp),
                        ("PluginProcessor.h", hdr)):
        m = ISFINITE_CALL_RE.search(code)
        if m is not None:
            line = code[:m.start()].count("\n") + 1
            raise _Rejected(
                "%s line ~%d still calls isfinite() - /fp:fast may fold that "
                "test to true, leaving the guard unreachable in the shipped "
                "binary; route it through %s() instead"
                % (label, line, HELPER))

    # (b) one helper, copying bits, returning the IEEE-754 exponent test
    defs = list(HELPER_DEF_RE.finditer(combined))
    if len(defs) != 1:
        raise _Rejected(
            "the %s helper must be defined exactly once in "
            "PluginProcessor.cpp/.h (found %d definitions)"
            % (HELPER, len(defs)))
    opening = combined.find("{", defs[0].end())
    closing = brace_span(combined, opening) if opening != -1 else -1
    if closing == -1:
        raise _Rejected("the %s helper body braces are unbalanced" % HELPER)
    body = combined[opening + 1:closing]
    if not re.search(r"\bmemcpy\s*\(", body) and "bit_cast" not in body:
        raise _Rejected(
            "the %s helper no longer copies the float through memcpy/bit_cast "
            "- reading the value as arithmetic is exactly what /fp:fast folds"
            % HELPER)
    if MASK_RE.search(collapse_ws(body)) is None:
        raise _Rejected(
            "the %s helper lost the IEEE-754 bit test; it must return "
            "`(bits & 0x7f800000u) != 0x7f800000u` (NaN and both infinities "
            "false, everything else true) or the guard is not value-dependent"
            % HELPER)

    # (c) every named guard still exists, exactly once, through the helper
    flat = collapse_ws(cpp)
    for label, snippet in GUARD_SITES:
        found = flat.count(snippet)
        if found != 1:
            raise _Rejected(
                "%s guard missing or reshaped (expected exactly 1, found %d) "
                "- expected `%s`; deleting the guard or reverting it to "
                "std::isfinite removes the containment this check exists for"
                % (label, found, snippet))
    if len(GUARD_SITES) != EXPECTED_GUARDS:
        raise _Rejected("guard roster drifted: %d pinned sites, expected %d"
                        % (len(GUARD_SITES), EXPECTED_GUARDS))


def run_text(cpp_text, hdr_text):
    try:
        _verify(cpp_text, hdr_text)
    except _Rejected as r:
        return str(r)
    return None


def main():
    for path in (CPP_PATH, HDR_PATH):
        if not path.exists():
            print("CV082 SETUP FAIL: missing %s" % path)
            return 2
    try:
        cpp = CPP_PATH.read_text(encoding="utf-8")
        hdr = HDR_PATH.read_text(encoding="utf-8")
    except OSError as exc:
        print("CV082 SETUP FAIL: %s" % exc)
        return 2

    # ---- positive control: the live source must satisfy every property ----
    verdict = run_text(cpp, hdr)
    if verdict is not None:
        fail(verdict)
    print("cv082-finite-guards: %d guards route through %s()'s IEEE-754 bit "
          "test (no std::isfinite left in the FX processor)"
          % (len(GUARD_SITES), HELPER))

    # ---- negative probes (in-memory mutations; each must be REJECTED) ----
    probes = [
        ("pre-patch shape: every guard back on std::isfinite",
         lambda c, h: (c.replace("isFiniteFloat(", "std::isfinite("), h),
         "isfinite()"),
        ("one processBlock fallback reverted to std::isfinite",
         lambda c, h: (c.replace(
             "isFiniteFloat(smoothOverall.getTargetValue())",
             "std::isfinite(smoothOverall.getTargetValue())"), h),
         "isfinite()"),
        ("CV-023 input sanitiser left guard deleted",
         lambda c, h: (c.replace("        " + INPUT_GUARD_L + "\n", ""), h),
         "input sanitiser left"),
        ("processBlock fallback declaration deleted (output_trim)",
         lambda c, h: (c.replace(
             "    const float fallbackOutputTrim = isFiniteFloat("
             "smoothOutputTrim.getTargetValue())\n"
             '        ? smoothOutputTrim.getTargetValue() : '
             'declaredPercentTarget(apvts, "output_trim");\n', ""), h),
         "processBlock fallback for output_trim"),
        ("helper stops using the bit test (return true)",
         lambda c, h: (c.replace(
             "    return (bits & 0x7f800000u) != 0x7f800000u;",
             "    return true;"), h),
         "bit test"),
        ("helper mask flipped to a comparison that is not the exponent test",
         lambda c, h: (c.replace(
             "    return (bits & 0x7f800000u) != 0x7f800000u;",
             "    return (bits & 0x7f800000u) == 0x7f800000u;"), h),
         "bit test"),
        ("helper stops copying through memcpy/bit_cast",
         lambda c, h: (c.replace(
             "    std::memcpy(&bits, &value, sizeof(bits));",
             "    bits = static_cast<std::uint32_t>(value);"), h),
         "memcpy/bit_cast"),
    ]

    for label, mutate, expect in probes:
        mutated_cpp, mutated_hdr = mutate(cpp, hdr)
        if (mutated_cpp, mutated_hdr) == (cpp, hdr):
            fail("no-op probe (%s): mutation did not change the source - the "
                 "negative check is vacuous" % label)
        verdict = run_text(mutated_cpp, mutated_hdr)
        if verdict is None:
            fail("negative probe '%s' was NOT rejected - checker is vacuous"
                 % label)
        if expect not in verdict:
            fail("negative probe '%s' rejected for the wrong reason (expected "
                 "%r in the diagnostic, got %r)" % (label, expect, verdict))
        print("cv082-finite-guards: negative probe '%s' rejected (%s)"
              % (label, verdict[:90]))

    # ---- benign probes: content edits outside the pin must still pass ----
    benign = (
        cpp.replace(
            "// CV-082: bit-level finiteness test.",
            "// CV-082: bit-level finiteness test (benign probe comment).", 1),
        hdr)
    benign = (
        benign[0].replace(
            "if (isFiniteFloat(mapped))   return mapped;",
            "if (isFiniteFloat(mapped))\n        return mapped;", 1),
        benign[1])
    if benign == (cpp, hdr):
        fail("no-op guard: the benign edit did not change the source")
    verdict = run_text(benign[0], benign[1])
    if verdict is not None:
        fail("benign comment/whitespace edit was REJECTED - checker over-fires: "
             "%s" % verdict)
    print("cv082-finite-guards: benign comment + guard whitespace reflow pass "
          "(probe specificity proven)")

    # ---- final re-verification of the real source ----
    final = run_text(CPP_PATH.read_text(encoding="utf-8"),
                     HDR_PATH.read_text(encoding="utf-8"))
    if final is not None:
        fail("final source re-verification failed: %s" % final)
    print("cv082-finite-guards: OK")
    return 0


if __name__ == "__main__":
    sys.exit(main())
