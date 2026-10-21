#!/usr/bin/env python3
"""Headless checker: setStateInformation's replace-state guard shape.

Everything inside setStateInformation (replaceState, the A/B slot restore,
the midiMap clear + restore) is only safe because the body opens with
getXmlFromBinary and is guarded by `xml && xml->hasTagName(apvts.state
.getType())`. Nothing else in the repo headless-pins that guard: a future
edit that drops hasTagName (replaceState on an alien/garbage ValueTree
stomps live parameters mid-session), or hoists the abSlots/midiMap restore
work OUTSIDE the if body (they then dereference a possibly-null xml) would
compile clean behind an otherwise-green gate.

Asserts on the real tree (comment-stripped, brace-matched):
  (a) the body opens with getXmlFromBinary(data, sizeInBytes) and keeps the
      `if (xml && xml->hasTagName(apvts.state.getType()))` guard BEFORE any
      replaceState / child restore work;
  (b) apvts.replaceState(, the abSlots child restore block
      (getChildByName("abSlots")), and the midiMap clear+restore
      (midiMap.clear() and getChildByName("midiMaps")) all sit INSIDE the
      guarded body (brace-matched membership);
  (c) nothing dereferences `->` on the xml unique_ptr before the
      `if (xml && ...)` line is established.
Negative self-probes on mutated in-memory texts (real tree never mutated;
no-op mutation aborts as a stale alarm): drop hasTagName → rejected; move
the midiMap clear outside the guard → rejected; strip getXmlFromBinary →
rejected. Benign no-op edit outside the pinned shapes → accepted (probe
specificity).

Exit 0 = ok, 1 = violation with a cited diagnostic.
"""
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SRC = ROOT / "source" / "DrippyFX"
CPP = SRC / "PluginProcessor.cpp"


def fail(msg):
    print(f"SETSTATE-GUARD FAIL: {msg}")
    sys.exit(1)


def strip_comments(src):
    src = re.sub(r"/\*.*?\*/", "", src, flags=re.S)
    src = re.sub(r"//[^\n]*", "", src)
    return src


def brace_body(text, start_idx):
    """Return substring of the brace-matched block starting at the '{' nearest
    at-or-after start_idx."""
    i = text.find("{", start_idx)
    if i == -1:
        return None
    depth = 0
    j = i
    while j < len(text):
        if text[j] == "{":
            depth += 1
        elif text[j] == "}":
            depth -= 1
            if depth == 0:
                break
        j += 1
    return text[i:j + 1]


def _verify(cpp_text):
    code = strip_comments(cpp_text)

    m = re.search(
        r"void\s+CorvusFXAudioProcessor::setStateInformation\s*\(", code)
    if not m:
        return "setStateInformation definition missing"
    body_start = m.start()
    # Find the opening `{` of the function body (skip to after the signature
    # parens close).
    sig_close = code.find(")", m.start())
    if sig_close == -1:
        return "setStateInformation signature not paren-matched"
    body = brace_body(code, sig_close)
    if not body:
        return "setStateInformation body not brace-matched"

    rel = body  # work within the body text, offsets relative to body start

    # (a) binary decode + hasTagName guard before any restore work
    if "getXmlFromBinary(data, sizeInBytes)" not in rel:
        return "setStateInformation no longer decodes via getXmlFromBinary"
    guard = re.search(
        r"if\s*\(\s*xml\s*&&\s*xml->hasTagName\(apvts\.state\.getType\(\)\)\s*\)",
        rel)
    if not guard:
        return ("setStateInformation `if (xml && xml->hasTagName(apvts.state"
                ".getType()))` guard dropped — replaceState would stomp live "
                "parameters on an alien state blob")
    guard_end = guard.end()

    first_restorable = min(
        [p for p in (
            rel.find("apvts.replaceState("),
            rel.find('getChildByName("abSlots")'),
            rel.find('getChildByName("midiMaps")'),
            rel.find("midiMap.clear()"),
        ) if p != -1] or [-1])
    if first_restorable == -1:
        return "setStateInformation restore work not found"
    if first_restorable < guard_end:
        return ("setStateInformation restore work precedes the hasTagName "
                "guard")

    # (b) all restore work INSIDE the guarded if body (brace-matched)
    # Take the brace-matched block that opens at/after the guard's own `if`.
    guarded = brace_body(rel, guard.start())
    if not guarded:
        return "guarded body not brace-matched"
    for needle, label in (
            ("apvts.replaceState(", "replaceState"),
            ('getChildByName("abSlots")', "abSlots child restore"),
            ("midiMap.clear()", "midiMap clear"),
            ('getChildByName("midiMaps")', "midiMaps restore"),
    ):
        if needle not in guarded:
            return (f"{label} no longer sits INSIDE the hasTagName-guarded "
                    "body — it would dereference a possibly-null xml")

    # (c) nothing dereferences `->` on xml before the guard line
    head = rel[:guard.start()]
    if re.search(r"\bxml->", head):
        return ("setStateInformation dereferences `xml->` BEFORE the "
                "null/tag guard is established")
    return None


def main():
    if not CPP.exists():
        fail(f"missing source file {CPP}")
    cpp_raw = CPP.read_text(encoding="utf-8")
    err = _verify(cpp_raw)
    if err:
        fail(err)
    print("setstate-guard: hasTagName gate + replaceState/abSlots/midiMap "
          "restore all inside the guarded body, no xml-> deref before the "
          "guard")

    # probe 2 targets the raw (unstripped) text: the clear block with its
    # comment/indent — deletion moves the midiMap.clear() membership check
    # in both the raw and comment-stripped worlds.
    probe2_old = ("        {\n"
                  "            const juce::ScopedLock lock(midiMapLock);\n"
                  "            midiMap.clear();\n"
                  "        }")

    probes = [
        ("hasTagName guard dropped",
         "if (xml && xml->hasTagName(apvts.state.getType()))",
         "if (xml)"),
        ("midiMap clear stripped from the guarded body", probe2_old, ""),
        ("binary decode stripped",
         "std::unique_ptr<juce::XmlElement> xml(getXmlFromBinary(data, sizeInBytes));",
         "std::unique_ptr<juce::XmlElement> xml;"),
    ]

    for label, old, new in probes:
        if old not in cpp_raw:
            fail(f"no-op probe ({label}): pattern absent — probe is stale")
        mutated = cpp_raw.replace(old, new)
        if mutated == cpp_raw:
            fail(f"no-op probe ({label}): mutation did not change the source")
        try:
            err = _verify(mutated)
        except Exception as e:  # defensive: brace machinery must not mask
            err = str(e)
        if err:
            print(f"setstate-guard: negative probe '{label}' rejected "
                  f"({err[:80]}...)")
        else:
            fail(f"negative probe '{label}' was NOT rejected — checker is "
                 f"vacuous")

    # no-op guard: benign edit outside the pinned shapes must still pass
    shifted = cpp_raw.replace(
        'params.push_back(std::make_unique<juce::AudioParameterInt>("preset", "Preset", 0, 42, 2));',
        'params.push_back(std::make_unique<juce::AudioParameterInt>("preset", "Preset" , 0, 42, 2));')
    if shifted == cpp_raw:
        fail("no-op guard: unanchored neutral edit did not change the source")
    err = _verify(shifted)
    if err:
        fail(f"neutral edit outside the pinned shapes was REJECTED — checker "
             f"over-fires: {err}")
    print("setstate-guard: neutral no-op edit passes (probe specificity "
          "proven)")
    print("setstate-guard: OK")


if __name__ == "__main__":
    main()
