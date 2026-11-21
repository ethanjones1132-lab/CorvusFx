#!/usr/bin/env python3
"""CV-099: JUCE 8 MIDI metadata type qualification in CorvusSynthEngine.h.

CV-094 rewrote the render callback to hand the engine a raw
`juce::MidiMessageMetadata` view instead of constructing a MidiMessage. The
declaration was written with the JUCE 6/7 spelling of the type:

    void handleMidiMetadata(const juce::MidiBuffer::MidiMessageMetadata& metadata,

JUCE 8 declares the struct at namespace scope (`juce::MidiMessageMetadata` in
juce_MidiBuffer.h), not nested inside MidiBuffer, so the old qualification is
not a type and both call sites (CorvusRenderInstrument, and through it
CorvusInstrumentProcessor) fail to compile.

This checker pins two things in
source/DrippyFX/instrument/CorvusSynthEngine.h:

  (1) the stale nested spelling `MidiBuffer::MidiMessageMetadata` appears
      nowhere in the code (comments are stripped first, so the explanatory
      prose in the file may still name the mistake);
  (2) `handleMidiMetadata`'s first parameter is declared exactly as
      `const juce::MidiMessageMetadata& <name>` (whitespace-insensitive).

Qualification policy for the negative probes: the pin is the fully qualified
JUCE name, so three reverts are rejected - (a) putting `MidiBuffer::` back,
caught by rule (1); (b) nesting the type under itself
(`juce::MidiMessageMetadata::MidiMessageMetadata`), caught by rule (2); and
(c) dropping `juce::` entirely (`const MidiMessageMetadata&`), also caught by
rule (2). (c) is deliberately rejected: an unqualified name only compiles if
some translation unit happens to pull juce into scope with a using-directive,
which is not true for this header, and the task pins the JUCE-qualified type.
Reformatting the declaration or mentioning the old spelling in a comment is
benign and must still pass.

No compiler is run here; the reviewer builds the target after the gate.
Exit 0 = ok, 1 = violation, 2 = setup/read failure.
"""
import re
import sys
from pathlib import Path

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

ROOT = Path(__file__).resolve().parent.parent
SOURCE = (ROOT / "source" / "DrippyFX" / "instrument"
          / "CorvusSynthEngine.h")

STALE_TYPE_RE = re.compile(r"\bMidiBuffer\s*::\s*MidiMessageMetadata\b")
HANDLER_RE = re.compile(r"\bvoid\s+handleMidiMetadata\s*\(([^)]*)\)", re.S)
GOOD_PARAM_RE = re.compile(
    r"^const\s+juce::MidiMessageMetadata\s*&\s*[A-Za-z_]\w*$")

# The exact declaration in the good tree, used to aim updates at it.
GOOD_DECL_LITERAL = "const juce::MidiMessageMetadata& metadata,"


def fail(msg):
    print("CV099-MIDI-METADATA-TYPE FAIL: %s" % msg)
    sys.exit(1)


class _Rejected(Exception):
    pass


def strip_comments(src):
    src = re.sub(r"/\*.*?\*/", "", src, flags=re.S)
    return re.sub(r"//[^\n]*", "", src)


def collapse_ws(s):
    return re.sub(r"\s+", " ", s).strip()


def read_normalised(path):
    """Read with LF endings so the probe literals match on Windows checkouts."""
    text = path.read_text(encoding="utf-8", errors="replace")
    return text.replace("\r\n", "\n").replace("\r", "\n")


def _verify(text):
    """Raise _Rejected on any violation. None returned on success."""
    code = strip_comments(text)

    # (1) the JUCE 6/7 nested spelling must not survive anywhere in the code
    stale = STALE_TYPE_RE.search(code)
    if stale is not None:
        line = code[:stale.start()].count("\n") + 1
        raise _Rejected(
            "CorvusSynthEngine.h line ~%d still names the MIDI metadata type "
            "as `MidiBuffer::MidiMessageMetadata`; JUCE 8 declares it at "
            "namespace scope, so use `juce::MidiMessageMetadata`"
            % line)

    # (2) handleMidiMetadata takes exactly one const juce::MidiMessageMetadata&
    defs = list(HANDLER_RE.finditer(code))
    if len(defs) != 1:
        raise _Rejected(
            "handleMidiMetadata could not be located exactly once in "
            "CorvusSynthEngine.h (found %d declarations) - the JUCE 8 "
            "MIDI metadata parameter cannot be verified" % len(defs))
    params = [collapse_ws(p) for p in defs[0].group(1).split(",")]
    first = params[0] if params else ""
    if GOOD_PARAM_RE.match(first) is None:
        raise _Rejected(
            "handleMidiMetadata's first parameter is `%s`; it must be "
            "declared `const juce::MidiMessageMetadata& <name>` (JUCE 8's "
            "namespace-scope struct, fully qualified)" % first)


def run_text(text):
    try:
        _verify(text)
    except _Rejected as r:
        return str(r)
    return None


def main():
    if not SOURCE.exists():
        print("CV099 SETUP FAIL: missing %s" % SOURCE)
        return 2
    try:
        source = read_normalised(SOURCE)
    except OSError as exc:
        print("CV099 SETUP FAIL: %s" % exc)
        return 2

    # ---- positive control: the live header must satisfy every property ----
    verdict = run_text(source)
    if verdict is not None:
        fail(verdict)
    print("cv099-midi-metadata-type: handleMidiMetadata takes "
          "`const juce::MidiMessageMetadata&` and no `MidiBuffer::"
          "MidiMessageMetadata` remains in the code")

    # ---- negative probes (in-memory mutations; each must be REJECTED) ----
    probes = [
        ("JUCE 6/7 nested qualification put back",
         lambda t: t.replace(
             GOOD_DECL_LITERAL,
             "const juce::MidiBuffer::MidiMessageMetadata& metadata,", 1),
         "MidiBuffer::MidiMessageMetadata"),
        ("type nested under itself (juce::MidiMessageMetadata::...)",
         lambda t: t.replace(
             GOOD_DECL_LITERAL,
             "const juce::MidiMessageMetadata::MidiMessageMetadata& metadata,",
             1),
         "const juce::MidiMessageMetadata&"),
        ("juce:: namespace qualifier dropped",
         lambda t: t.replace(
             GOOD_DECL_LITERAL,
             "const MidiMessageMetadata& metadata,", 1),
         "const juce::MidiMessageMetadata&"),
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
        print("cv099-midi-metadata-type: negative probe '%s' rejected (%s)"
              % (label, verdict[:100]))

    # ---- benign probes: content edits outside the pin must still pass ----
    # A comment naming the old spelling must not trip rule (1): comments are
    # stripped before the scan.
    benign_comment = source.replace(
        "    // CV-094: turn a host event into the engine's note/controller handling",
        "    // Benign probe: this used to say MidiBuffer::MidiMessageMetadata,\n"
        "    // and this comment must not fail the checker.\n"
        "    // CV-094: turn a host event into the engine's note/controller "
        "handling", 1)
    if benign_comment == source:
        fail("no-op benign comment probe: the comment was not inserted")
    verdict = run_text(benign_comment)
    if verdict is not None:
        fail("benign comment naming the old spelling was REJECTED - rule (1) "
             "is not comment-safe: %s" % verdict)
    print("cv099-midi-metadata-type: benign comment naming the old spelling "
          "accepted")

    # Reformatting the parameter list across lines is the same declaration.
    benign_reflow = source.replace(
        "    void handleMidiMetadata(const juce::MidiMessageMetadata& metadata,\n",
        "    void handleMidiMetadata(\n"
        "        const juce::MidiMessageMetadata& metadata,\n", 1)
    if benign_reflow == source:
        fail("no-op benign reflow probe: the declaration was not reflowed")
    verdict = run_text(benign_reflow)
    if verdict is not None:
        fail("benign reformat of the parameter list was REJECTED - checker "
             "over-fitted to the current text: %s" % verdict)
    print("cv099-midi-metadata-type: benign parameter reflow accepted")

    # ---- final re-verification of the real source ----
    final = run_text(read_normalised(SOURCE))
    if final is not None:
        fail("final source re-verification failed: %s" % final)
    print("cv099-midi-metadata-type: OK")
    return 0


if __name__ == "__main__":
    sys.exit(main())
