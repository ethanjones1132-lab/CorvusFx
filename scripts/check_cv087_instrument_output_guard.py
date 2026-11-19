#!/usr/bin/env python3
"""Headless invariant check: CV-087 instrument output finiteness guard.

The instrument ships with the same MSVC /fp:fast policy as the FX. Under those
flags the compiler may assume every float is finite, so a guard written as
`std::isfinite(value)` on a value that came out of arithmetic can be folded to
`true` and the containment becomes unreachable in the shipped binary - the
source text looks safe while nothing stops a NaN or an infinity reaching the
host. CV-082 fixed the FX processor this way; the instrument output loop kept
the foldable test at:

    auto value = buffer.getSample(channel, sample) * gain;
    if (!std::isfinite(value))
        value = 0.0f;

The fix is the same file-local IEEE-754 bit test CV-082 introduced, defined
once in instrument/CorvusInstrumentProcessor.cpp:

    inline bool isFiniteFloat(float value) noexcept
    {
        std::uint32_t bits = 0;
        std::memcpy(&bits, &value, sizeof(bits));
        return (bits & 0x7f800000u) != 0x7f800000u;
    }

It answers exactly what std::isfinite answers (NaN and both infinities false,
everything else true), but the answer is computed from the bits, so /fp:fast
cannot fold it away.

Asserts (comments stripped; guard sites whitespace-collapsed):
  (a) processBlock calls no compiler finiteness builtin any more;
  (b) the helper is defined exactly once in the instrument processor, copies
      the float through memcpy/bit_cast, and returns exactly
      `(bits & 0x7f800000u) != 0x7f800000u`;
  (c) the output loop still contains exactly one containment guard, written
      through the helper, and the existing accounting is unchanged and in
      order: guard -> lastPreClampPeak update -> jlimit(-1, 1) write.

Negative self-probes on mutated in-memory texts (the real tree is never
mutated), each asserting the mutation APPLIED before asserting rejection and
that the rejection carries the intended diagnostic:
  - the guard reverted to std::isfinite(value) -> rejected;
  - the guard statement deleted (nothing contains a non-finite sample)
    -> rejected;
  - the guard moved after the output clamp and peak accounting -> rejected;
  - the helper stops using the bit test (`return true;`) -> rejected;
  - the exponent mask flipped to a comparison that is not the exponent test
    -> rejected;
  - the helper stops copying through memcpy/bit_cast -> rejected;
  - the helper definition deleted -> rejected;
  - the pre-clamp peak accounting deleted -> rejected;
  - the output clamp deleted or widened away -> rejected;
  - benign probes ACCEPTED: a comment added in the output loop and the guard
    reflowed onto one line - the pin is content, not formatting.

Exit 0 = ok, 1 = violation, 2 = setup/read failure.
"""
import re
import sys
from pathlib import Path

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

ROOT = Path(__file__).resolve().parent.parent
SOURCE = (ROOT / "source" / "DrippyFX" / "instrument"
          / "CorvusInstrumentProcessor.cpp")

HELPER = "isFiniteFloat"
HELPER_DEF_RE = re.compile(
    r"\binline\s+bool\s+" + HELPER + r"\s*\(\s*float\s+[A-Za-z_]\w*\s*\)\s*noexcept")
MASK_RE = re.compile(r"\(\s*bits\s*&\s*0x7f800000u\s*\)\s*!=\s*0x7f800000u")
ISFINITE_CALL_RE = re.compile(r"\bisfinite\s*\(")
PROCESS_BLOCK_RE = re.compile(
    r"\bvoid\s+CorvusInstrumentProcessor::processBlock\s*\([^)]*\)\s*\{",
    flags=re.S)

# The CV-082 vehicle, pinned verbatim up to whitespace.
HELPER_COPY_LINE = "std::memcpy(&bits, &value, sizeof(bits));"
HELPER_RETURN_LINE = "return (bits & 0x7f800000u) != 0x7f800000u;"
HELPER_TEXT = (
    "inline bool isFiniteFloat(float value) noexcept\n"
    "{\n"
    '    static_assert(sizeof(float) == sizeof(std::uint32_t), "IEEE-754 float expected");\n'
    "\n"
    "    std::uint32_t bits = 0;\n"
    "    std::memcpy(&bits, &value, sizeof(bits));\n"
    "    return (bits & 0x7f800000u) != 0x7f800000u;\n"
    "}\n"
)

# The output loop, pinned up to whitespace. The order of these three
# statements is the containment contract: a non-finite sample is zeroed before
# it is metered and before it is written back clamped.
OUTPUT_GUARD = "if (!isFiniteFloat(value)) value = 0.0f;"
PEAK_ACCOUNTING = ("lastPreClampPeak = juce::jmax(lastPreClampPeak, "
                   "std::abs(value));")
OUTPUT_CLAMP = ("buffer.setSample(channel, sample, "
                "juce::jlimit(-1.0f, 1.0f, value));")

GUARD_LITERAL = "if (!isFiniteFloat(value))\n                value = 0.0f;"
PEAK_LITERAL = ("            lastPreClampPeak = juce::jmax(lastPreClampPeak, "
                "std::abs(value));")
CLAMP_LITERAL = ("            buffer.setSample(channel, sample, "
                 "juce::jlimit(-1.0f, 1.0f, value));")


def fail(msg):
    print("CV087-INSTRUMENT-OUTPUT-GUARD FAIL: %s" % msg)
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


def process_block_body(code):
    match = PROCESS_BLOCK_RE.search(code)
    if match is None:
        return None
    opening = match.end() - 1
    closing = brace_span(code, opening)
    if closing == -1:
        return None
    return code[opening + 1:closing]


def _verify(text):
    """Raise _Rejected on any violation. None returned on success."""
    code = strip_comments(text)

    # (a) no compiler finiteness builtin may remain in the audio output path
    body = process_block_body(code)
    if body is None:
        raise _Rejected(
            "processBlock could not be located in the instrument processor - "
            "the output containment guard cannot be verified")
    m = ISFINITE_CALL_RE.search(body)
    if m is not None:
        line = code[:code.find(body) + m.start()].count("\n") + 1
        raise _Rejected(
            "processBlock line ~%d still calls isfinite() - /fp:fast may fold "
            "that test on an arithmetic value to true, leaving the guard "
            "unreachable in the shipped binary; route it through %s() instead"
            % (line, HELPER))

    # (b) one file-local helper, copying bits, returning the exponent test
    defs = list(HELPER_DEF_RE.finditer(code))
    if len(defs) != 1:
        raise _Rejected(
            "the %s helper must be defined exactly once in "
            "CorvusInstrumentProcessor.cpp (found %d definitions) - the "
            "instrument output guard is only fold-proof while it calls this "
            "bit test" % (HELPER, len(defs)))
    opening = code.find("{", defs[0].end())
    closing = brace_span(code, opening) if opening != -1 else -1
    if closing == -1:
        raise _Rejected("the %s helper body braces are unbalanced" % HELPER)
    helper_body = code[opening + 1:closing]
    if not re.search(r"\bmemcpy\s*\(", helper_body) \
            and "bit_cast" not in helper_body:
        raise _Rejected(
            "the %s helper no longer copies the float through memcpy/bit_cast "
            "- reading the value as arithmetic is exactly what /fp:fast folds"
            % HELPER)
    if MASK_RE.search(collapse_ws(helper_body)) is None:
        raise _Rejected(
            "the %s helper lost the IEEE-754 bit test; it must return "
            "`(bits & 0x7f800000u) != 0x7f800000u` (NaN and both infinities "
            "false, everything else true) or the guard is not value-dependent"
            % HELPER)

    # (c) the output guard, the peak accounting and the clamp, in that order
    flat = collapse_ws(body)
    found = flat.count(OUTPUT_GUARD)
    if found != 1:
        raise _Rejected(
            "instrument output guard missing or reshaped (expected exactly 1, "
            "found %d) - expected `%s`; deleting the guard or reverting it to "
            "std::isfinite leaves a non-finite sample free to reach the host"
            % (found, OUTPUT_GUARD))
    for label, snippet in (("pre-clamp peak accounting", PEAK_ACCOUNTING),
                           ("output clamp", OUTPUT_CLAMP)):
        count = flat.count(snippet)
        if count != 1:
            raise _Rejected(
                "%s missing or reshaped (expected exactly 1, found %d) - "
                "expected `%s`" % (label, count, snippet))
    guard_at = flat.find(OUTPUT_GUARD)
    peak_at = flat.find(PEAK_ACCOUNTING)
    clamp_at = flat.find(OUTPUT_CLAMP)
    if not guard_at < peak_at:
        raise _Rejected(
            "the containment guard no longer runs before the peak accounting "
            "- a non-finite sample must be zeroed before it is metered")
    if not peak_at < clamp_at:
        raise _Rejected(
            "the peak accounting no longer runs before the output clamp - the "
            "metered peak must stay the pre-clamp value")


def run_text(text):
    try:
        _verify(text)
    except _Rejected as r:
        return str(r)
    return None


def main():
    if not SOURCE.exists():
        print("CV087 SETUP FAIL: missing %s" % SOURCE)
        return 2
    try:
        source = SOURCE.read_text(encoding="utf-8")
    except OSError as exc:
        print("CV087 SETUP FAIL: %s" % exc)
        return 2

    # ---- positive control: the live source must satisfy every property ----
    verdict = run_text(source)
    if verdict is not None:
        fail(verdict)
    print("cv087-instrument-output-guard: the instrument output loop contains "
          "a non-finite sample through %s()'s IEEE-754 bit test before the "
          "pre-clamp peak accounting and the jlimit write" % HELPER)

    # ---- negative probes (in-memory mutations; each must be REJECTED) ----
    probes = [
        ("output guard reverted to std::isfinite",
         lambda t: t.replace("if (!isFiniteFloat(value))",
                             "if (!std::isfinite(value))", 1),
         "isfinite()"),
        ("output guard deleted (nothing contains a non-finite sample)",
         lambda t: t.replace(GUARD_LITERAL, "", 1),
         "output guard missing"),
        ("output guard moved after the clamp and peak accounting",
         lambda t: t.replace(
             GUARD_LITERAL, "", 1).replace(
             CLAMP_LITERAL,
             CLAMP_LITERAL + " " + OUTPUT_GUARD, 1),
         "before the peak accounting"),
        ("helper stops using the bit test (return true)",
         lambda t: t.replace("    " + HELPER_RETURN_LINE,
                             "    return true;", 1),
         "bit test"),
        ("helper mask flipped to a comparison that is not the exponent test",
         lambda t: t.replace(
             "    " + HELPER_RETURN_LINE,
             "    return (bits & 0x7f800000u) == 0x7f800000u;", 1),
         "bit test"),
        ("helper stops copying through memcpy/bit_cast",
         lambda t: t.replace(
             "    " + HELPER_COPY_LINE,
             "    bits = static_cast<std::uint32_t>(value);", 1),
         "memcpy/bit_cast"),
        ("helper definition deleted",
         lambda t: t.replace(HELPER_TEXT, "", 1),
         "exactly once"),
        ("pre-clamp peak accounting deleted",
         lambda t: t.replace(PEAK_LITERAL, "", 1),
         "peak accounting missing"),
        ("output clamp deleted",
         lambda t: t.replace(
             CLAMP_LITERAL,
             "            buffer.setSample(channel, sample, value);", 1),
         "output clamp missing"),
        ("output clamp widened away around the already-zeroed value",
         lambda t: t.replace(
             "juce::jlimit(-1.0f, 1.0f, value)", "value", 1),
         "output clamp missing"),
    ]

    for label, mutate, expect in probes:
        mutated = mutate(source)
        if mutated == source:
            fail("no-op probe (%s): mutation did not change the source - the "
                 "negative check is vacuous" % label)
        verdict = run_text(mutated)
        if verdict is None:
            fail("negative probe '%s' was NOT rejected - checker is vacuous"
                 % label)
        if expect not in verdict:
            fail("negative probe '%s' rejected for the wrong reason (expected "
                 "%r in the diagnostic, got %r)" % (label, expect, verdict))
        print("cv087-instrument-output-guard: negative probe '%s' rejected (%s)"
              % (label, verdict[:90]))

    # ---- benign probes: content edits outside the pin must still pass ----
    benign = source.replace(
        "            auto value = buffer.getSample(channel, sample) * gain;",
        "            // benign probe comment\n"
        "            auto value = buffer.getSample(channel, sample) * gain;", 1)
    benign = benign.replace(
        GUARD_LITERAL, "if (!isFiniteFloat(value)) value = 0.0f;", 1)
    if benign == source:
        fail("no-op guard: the benign edit did not change the source")
    verdict = run_text(benign)
    if verdict is not None:
        fail("benign comment/whitespace edit was REJECTED - checker over-fires: "
             "%s" % verdict)
    print("cv087-instrument-output-guard: benign comment + guard reflow pass "
          "(probe specificity proven)")

    # ---- final re-verification of the real source ----
    final = run_text(SOURCE.read_text(encoding="utf-8"))
    if final is not None:
        fail("final source re-verification failed: %s" % final)
    print("cv087-instrument-output-guard: OK")
    return 0


if __name__ == "__main__":
    sys.exit(main())
