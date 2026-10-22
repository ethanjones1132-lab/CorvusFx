#!/usr/bin/env python3
"""Headless checker: the wavetable bank is built by prepare(), never by the audio path.

`source/DrippyFX/instrument/WavetableOscillator.h` used to own a lazy accessor:

    static const TableBank& tables()
    {
        static const auto bank = createTableBank();
        return bank;
    }

and `process()` called it on every sample. The function-local static therefore
first ran inside the audio callback: the first note of the first instance paid
the whole 4 x 11 x 2048 float table build (sine sums plus normalisation) on the
real-time thread. `prepare()` only stored the sample rate, so nothing on the
prepare side forced the build.

The live shape captures the bank in prepare() (prepareToPlay may allocate) and
keeps the audio path read-only:

    void prepare(double newSampleRate)
    {
        tableBankPtr = &buildTableBankOnce();
        ...
    }

    float process() noexcept
    {
        if (tableBankPtr == nullptr || ...)
            return 0.0f;
        const auto& table = (*tableBankPtr)[waveIndex][selectMipLevel()];
        ...
    }

Asserts on the real tree (comment-stripped, brace-matched function bodies):
  (a) `process()` holds no function-local `static` storage of its own and calls
      no `createTableBank(` itself;
  (b) no function that `process()` calls holds a plain `static` local or calls
      `createTableBank(` - restoring the lazy `tables()` accessor and calling it
      from the audio callback is rejected;
  (c) `process()` guards the prepared pointer with `tableBankPtr == nullptr`
      and `return 0.0f;` BEFORE the first `(*tableBankPtr)[` read, so an
      oscillator that was never prepared renders silence instead of building
      tables;
  (d) `prepare()` assigns `tableBankPtr` from a bank builder before its first
      `return`, and that builder body is the only place `createTableBank(` is
      called, so the build cannot be reached from process() or from any second
      lazy path;
  (e) the member defaults to `nullptr`, so no instance starts out pointing at a
      bank that prepare() did not build.

Negative self-probes on mutated in-memory texts (the real tree is never mutated;
a mutation that changes nothing aborts as a stale alarm):
  - restore the lazy `tables()` accessor holding the static and call it from
    process() -> rejected
  - call the bank builder directly from process() -> rejected
  - inline a function-local `static const auto bank = createTableBank();` into
    process() -> rejected
  - assign the bank lazily from process() -> rejected
  - drop the audio-thread null guard -> rejected
  - drop the prepare-time bank capture -> rejected
  - harmless comment edit that names `static`/`createTableBank` in a comment ->
    accepted (a comment cannot launder an audio-path build; probe specificity
    proven)

Exit 0 = ok, 1 = violation with a cited diagnostic.
"""
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SRC = ROOT / "source" / "DrippyFX" / "instrument" / "WavetableOscillator.h"

CONTROL_KEYWORDS = {"if", "for", "while", "switch", "catch", "return",
                    "sizeof", "static_assert"}


class _Rejected(Exception):
    pass


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


def function_bodies(code):
    """Map member-function name -> brace-matched body of the live header."""
    bodies = {}
    for m in re.finditer(
            r"\b(\w+)\s*\(([^;{}()]*)\)\s*(?:const\s*)?(?:noexcept\s*)?\{", code):
        name = m.group(1)
        if name in CONTROL_KEYWORDS:
            continue
        open_idx = m.end() - 1
        end_idx = brace_span(code, open_idx)
        if end_idx == -1:
            continue
        bodies.setdefault(name, code[open_idx + 1:end_idx])
    return bodies


def _verify(header_text):
    """Raise _Rejected on a violation; return None when the shape is intact."""
    code = strip_comments(header_text)
    if not re.search(r"\bclass\s+WavetableOscillator\b", code):
        raise _Rejected("class WavetableOscillator not found in the header")

    bodies = function_bodies(code)
    for required in ("prepare", "process"):
        if required not in bodies:
            raise _Rejected(
                "WavetableOscillator::%s body not found/brace-matched"
                % required)
    process = bodies["process"]
    prepare = bodies["prepare"]
    if len(process) < 200:
        raise _Rejected(
            "process() body is only %d chars - brace matching drifted; do not "
            "trust green" % len(process))
    if len(prepare) < 50:
        raise _Rejected(
            "prepare() body is only %d chars - brace matching drifted; do not "
            "trust green" % len(prepare))

    # (a) process() must not build or host the bank itself.
    if re.search(r"\bcreateTableBank\s*\(", process):
        raise _Rejected(
            "process() calls createTableBank() - the audio callback would "
            "build the wavetable bank on the real-time thread")
    if re.search(r"\bstatic\b", process):
        raise _Rejected(
            "process() declares function-local static storage - a lazy table "
            "bank initialiser on the audio path is exactly what this contract "
            "forbids")

    # (b) nor may anything process() reaches hold the lazy build.
    for call in re.finditer(r"\b(\w+)\s*\(", process):
        callee_name = call.group(1)
        callee = bodies.get(callee_name)
        if callee is None:
            continue
        builds = re.search(r"\bcreateTableBank\s*\(", callee)
        lazy_static = re.search(r"\bstatic\b", callee)
        if builds or lazy_static:
            raise _Rejected(
                "process() calls `%s()`, whose body builds the wavetable bank "
                "(function-local static or createTableBank) - the audio "
                "callback must only read a bank that prepare() already built"
                % callee_name)

    # (c) the prepared pointer is null-guarded before the first bank read.
    guard = re.search(
        r"if\s*\(\s*tableBankPtr\s*==\s*nullptr\b[^)]*\)\s*(?:\{\s*)?"
        r"return\s+0\.0f\s*;",
        process)
    if not guard:
        raise _Rejected(
            "process() no longer guards `tableBankPtr == nullptr` with "
            "`return 0.0f;` - an oscillator prepared nowhere would have to "
            "build the wavetable bank on the audio thread")
    read = re.search(r"\(\s*\*\s*tableBankPtr\s*\)\s*\[", process)
    if not read:
        raise _Rejected(
            "process() does not read the prepare-built bank through "
            "`(*tableBankPtr)[...]` - the audio path lost its prepared table "
            "source")
    if read.start() < guard.end():
        raise _Rejected(
            "process() reads the wavetable bank before the null guard - the "
            "guard must run first")

    # (d) prepare() captures the bank, and only that builder creates it.
    capture = re.search(r"tableBankPtr\s*=\s*&\s*(\w+)\s*\(\s*\)\s*;", prepare)
    if not capture:
        raise _Rejected(
            "prepare() no longer captures the bank (`tableBankPtr = "
            "&<builder>();`) - the bank would stay unbuilt until something on "
            "the audio path touched it")
    builder = capture.group(1)
    builder_body = bodies.get(builder)
    if builder_body is None:
        raise _Rejected(
            "prepare() captures the bank from `%s()`, which has no "
            "brace-matched body in this header" % builder)
    if not re.search(r"\bcreateTableBank\s*\(", builder_body):
        raise _Rejected(
            "`%s()` does not call createTableBank() - prepare() captures "
            "something that is not the wavetable bank builder" % builder)
    first_return = prepare.find("return")
    if first_return != -1 and capture.start() > first_return:
        raise _Rejected(
            "prepare() captures the bank after its first `return` - the early "
            "exit would leave the bank unbuilt for the audio path")
    others = sorted(
        name for name, body in bodies.items()
        if name != builder and re.search(r"\bcreateTableBank\s*\(", body))
    if others:
        raise _Rejected(
            "createTableBank() is called outside the prepare-time builder, by "
            "%s - a second bank build path can be reached from the audio "
            "thread" % ", ".join(others))

    # (e) the default state is "no bank".
    if not re.search(
            r"const\s+TableBank\s*\*\s*tableBankPtr\s*=\s*nullptr\s*;", code):
        raise _Rejected(
            "`const TableBank* tableBankPtr = nullptr;` member missing - an "
            "instance could start out pointing at a bank prepare() never built")
    return None


def fail(msg):
    print("WAVETABLE-PREPARE FAIL: %s" % msg)
    getattr(sys, "exit")(1)


def run_text(header_text):
    try:
        _verify(header_text)
    except _Rejected as r:
        return str(r)
    return None


def main():
    if not SRC.exists():
        fail("missing source file %s" % SRC)
    text = SRC.read_text(encoding="utf-8")

    verdict = run_text(text)
    if verdict is not None:
        fail(verdict)
    print("wavetable-prepare: prepare() builds the bank, process() only reads "
          "the prepared pointer and renders silence without it")

    # Negative self-probes: each mutation reintroduces the lazy audio-path
    # build in a different shape. The real tree is never mutated.
    probes = [
        ("restore the lazy tables() accessor on the audio path",
         lambda s: s.replace("buildTableBankOnce", "tables").replace(
             "(*tableBankPtr)[waveIndex]", "tables()[waveIndex]", 1)),
        ("call the bank builder directly from the audio path",
         lambda s: s.replace("(*tableBankPtr)[waveIndex]",
                             "buildTableBankOnce()[waveIndex]", 1)),
        ("inline a function-local static bank in process()",
         lambda s: s.replace(
             "        const auto waveIndex = juce::jlimit<std::size_t>(",
             "        static const auto bank = createTableBank();\n"
             "        const auto waveIndex = juce::jlimit<std::size_t>(", 1)),
        ("assign the bank lazily from the audio path",
         lambda s: s.replace(
             "        if (tableBankPtr == nullptr || phaseIncrement <= 0.0",
             "        tableBankPtr = &buildTableBankOnce();\n"
             "        if (tableBankPtr == nullptr || phaseIncrement <= 0.0", 1)),
        ("drop the audio-thread null guard",
         lambda s: s.replace(
             "if (tableBankPtr == nullptr || phaseIncrement <= 0.0 "
             "|| sampleRate <= 0.0)",
             "if (phaseIncrement <= 0.0 || sampleRate <= 0.0)", 1)),
        ("drop the prepare-time bank capture",
         lambda s: s.replace("tableBankPtr = &buildTableBankOnce();\n\n", "", 1)),
    ]
    for label, mutate in probes:
        mutated = mutate(text)
        if mutated == text:
            fail("no-op probe (%s): mutation did not change the source - the "
                 "negative check is vacuous" % label)
        verdict = run_text(mutated)
        if verdict is None:
            fail("negative probe '%s' was NOT rejected - checker is vacuous"
                 % label)
        print("wavetable-prepare: negative probe '%s' rejected (%s...)"
              % (label, verdict[:72]))

    # No-op guard: a harmless comment edit that even names `static` and
    # createTableBank() must still pass, because comment stripping removes it.
    neutral = text.replace(
        "// prepare() has not run: there is no bank to read, so stay silent",
        "// No function-local static and no createTableBank() call belongs\n"
        "        // on the audio path; this comment must not trip the check.\n"
        "        // prepare() has not run: there is no bank to read, so stay silent",
        1)
    if neutral == text:
        fail("no-op guard: neutral comment edit did not change the source - "
             "probe is stale")
    verdict = run_text(neutral)
    if verdict is not None:
        fail("benign comment edit was REJECTED - checker over-fires: %s"
             % verdict)
    print("wavetable-prepare: harmless comment edit passes (probe specificity "
          "proven)")

    # The real tree is never mutated; re-verify the untouched source once more.
    if run_text(SRC.read_text(encoding="utf-8")) is not None:
        fail("final live-source re-verification failed")
    print("wavetable-prepare: OK")
    return 0


if __name__ == "__main__":
    getattr(sys, "exit")(main())
