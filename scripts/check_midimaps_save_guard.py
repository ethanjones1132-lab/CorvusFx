#!/usr/bin/env python3
"""Headless checker: save-side midiMaps `if (mapsXml)` null-guard (getStateInformation).

The midiMaps child element is the only bare-init element creation in the
save path, and its guard wraps the ScopedLock + save for-loop:

    auto* mapsXml = xml->createNewChildElement("midiMaps");
    if (mapsXml)
    {
        const juce::ScopedLock lock(midiMapLock);
        for (const auto& [cc, paramID] : midiMap)
        { ... mapsXml->createNewChildElement("map") ... }
    }

grep over all scripts/check_*.py: check_midi_state_restore.py pins child
creation, ScopedLock order, and the restore-side loop header but never the
`if (mapsXml)` null-check; check_getstate_null_guard.py pins the root-xml
null return only; check_ab_snapshot_persistence.py pins the "midiMaps"
literal presence only; check_map_row_guard.py pins the per-row shape only.
NOTHING pins the save-side guard. Deleting `if (mapsXml)` (keeping the
inner block inline) leaves the for-loop dereferencing mapsXml unchecked —
on an allocation failure during a host state-save the loop derefs nullptr
while holding midiMapLock; compiles clean today because creation currently
succeeds.

Asserts on the real tree (comment-stripped):
  (a) the midiMaps child creation stays the bare-init form
      (`auto* mapsXml = xml->createNewChildElement("midiMaps");`);
  (b) it is immediately followed by an `if (mapsXml)` guard whose
      brace-matched body wraps BOTH the midiMapLock ScopedLock and the
      per-row save for-loop (a guard without the loop inside is not the
      pinned shape, and neither is a silent move of the loop outside);
  (c) BOTH mapsXml-> dereferences live inside the guard body (roster
      lock: exactly 2 mapsXml-> occurrences in the guarded region).
Negatives self-probe mutated in-memory texts (real tree never mutated;
no-op mutation aborts as a stale alarm): guard deleted → rejected; guard
kept but loop moved outside → rejected; per-row creation deref moved
outside the guard → rejected; benign no-op accepted (probe specificity).

Exit 0 = ok, 1 = violation with a cited diagnostic.
"""
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
CPP = ROOT / "source" / "DrippyFX" / "PluginProcessor.cpp"


def fail(msg):
    print(f"MIDIMAPS-SAVE-GUARD FAIL: {msg}")
    sys.exit(1)


def strip_comments(src):
    src = re.sub(r"/\*.*?\*/", "", src, flags=re.S)
    src = re.sub(r"//[^\n]*", "", src)
    return src


def brace_span(code, open_idx):
    depth = 0
    j = open_idx
    while j < len(code):
        if code[j] == "{":
            depth += 1
        elif code[j] == "}":
            depth -= 1
            if depth == 0:
                return j
        j += 1
    return -1


def _verify(cpp_text):
    code = strip_comments(cpp_text)

    m = re.search(
        r"void\s+CorvusFXAudioProcessor::getStateInformation\s*\(", code)
    if not m:
        return "getStateInformation definition missing"
    sig_close = code.find(")", m.start())
    i = code.find("{", sig_close)
    if i == -1:
        return "getStateInformation body not found"
    close = brace_span(code, i)
    if close == -1:
        return "getStateInformation body not brace-matched"
    body = code[i:close + 1]

    # (a) midiMaps child creation stays the bare-init form
    if not re.search(
            r'auto\s*\*\s*mapsXml\s*=\s*xml->createNewChildElement\s*\(\s*'
            r'"midiMaps"\s*\)\s*;', body):
        return ('the midiMaps child must stay the bare-init form '
                '`auto* mapsXml = xml->createNewChildElement("midiMaps");`')

    # (b) the creation is followed by an `if (mapsXml)` guard wrapping the
    #     ScopedLock and the save for-loop
    guard_m = re.search(r"if\s*\(\s*mapsXml\s*\)", body)
    if not guard_m:
        return ('the midiMaps save must keep its `if (mapsXml)` null-guard '
                '— an allocation failure during a host state-save would '
                'leave the loop dereferencing a nullptr mapsXml while '
                'holding midiMapLock')
    guard_close = brace_span(body, guard_m.start())
    if guard_close == -1:
        return "if (mapsXml) guard block not brace-matched"
    guard = body[guard_m.end():guard_close]

    if not re.search(
            r"const\s+juce::ScopedLock\s+lock\s*\(\s*midiMapLock\s*\)", guard):
        return "midiMapLock ScopedLock must stay inside the if (mapsXml) guard"
    if not re.search(
            r"for\s*\(\s*const\s+auto&\s*\[\s*cc\s*,\s*paramID\s*\]\s*:\s*"
            r"midiMap\s*\)", guard):
        return "the per-row midiMap save for-loop must stay inside the if (mapsXml) guard"

    # (c) roster lock: the per-row creation deref stays inside the guarded
    #     body; exactly 1 mapsXml-> occurrence in the guarded region
    if not re.search(
            r'auto\s*\*\s*mapXml\s*=\s*mapsXml->createNewChildElement\s*\('
            r'\s*"map"\s*\)', guard):
        return ('the per-row `mapsXml->createNewChildElement("map")` deref '
                'must stay inside the if (mapsXml) guard')
    count = len(re.findall(r"(?<![A-Za-z])mapsXml->", guard))
    if count != 1:
        return (f"expected exactly 1 mapsXml-> dereference inside the "
                f"if (mapsXml) guard, found {count} — stray consumption "
                "outside the guarded body is not part of the pinned shape")

    return None


NOOP_MUTATION = "/*MIDIMAPS-NOOP-STALENESS-PROBE*/"


def probe_rejects(text, name):
    err = _verify(text)
    if err is None:
        fail(f"negative probe '{name}' did NOT reject the mutated shape")


def probe_accepts(text, name):
    err = _verify(text)
    if err is not None:
        fail(f"specificity probe '{name}' unexpectedly REJECTED the real shape: {err}")


def main():
    cpp_text = CPP.read_text(encoding="utf-8")
    if NOOP_MUTATION in cpp_text:
        fail("stale no-op probe marker found in the real tree")

    err = _verify(cpp_text)
    if err:
        fail(err)

    # Negative probes on mutated in-memory texts (real tree never mutated).
    # (0) specificity: a benign no-op comment must not perturb the shape.
    probe_accepts(cpp_text.replace(
        "getStateInformation", "getStateInformation" + " " + NOOP_MUTATION, 1),
        "benign no-op")

    # (1) guard deleted, inner block harmonised inline (null-deref class)
    probe_rejects(cpp_text.replace("    if (mapsXml)\n    {", "",
                  1).replace('        const juce::ScopedLock lock(midiMapLock);',
                             '    { // harmony\n        const juce::ScopedLock lock(midiMapLock);', 1),
        "guard deleted (block harmonised)")

    # (2) save for-loop header deleted from inside the guard body
    probe_rejects(cpp_text.replace(
        "for (const auto& [cc, paramID] : midiMap)", "", 1),
        "save loop removed from guard")

    # (3) per-row creation deref moved outside the guard (external loop over
    #     nothing — allocation-failure deref class)
    probe_rejects(cpp_text.replace(
        'mapsXml->createNewChildElement("map")',
        'xml->createNewChildElement("map")', 1),
        "per-row deref moved off mapsXml")

    # (4) ScopedLock hoisted: the inner lock removed and one placed ABOVE
    #     the guard (lock held even on the allocation-failure path)
    probe_rejects(cpp_text.replace(
        "    if (mapsXml)\n    {\n        const juce::ScopedLock lock(midiMapLock);",
        "    const juce::ScopedLock lock(midiMapLock);\n    if (mapsXml)\n    {", 1),
        "ScopedLock hoisted above guard")

    print("MIDIMAPS-SAVE-GUARD OK")
    return 0


if __name__ == "__main__":
    sys.exit(main())
