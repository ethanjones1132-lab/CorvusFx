#!/usr/bin/env python3
"""Headless checker: getStateInformation's save-side xml null guard shape.

getStateInformation builds `std::unique_ptr<juce::XmlElement> xml(state
.createXml())` and then serializes the midiMaps + abSlots children and
calls copyXmlToBinary(*xml, destData). createXml() returns nullptr on a
corrupt/cyclic copyState tree — every subsequent `xml->` dereference is
then a message-thread null-deref crash on any host state save. The LOAD
side is already guarded (check_setstate_guard.py pins its hasTagName
guard); nothing else in the repo headless-pins the SAVE side: a future
edit that drops the `if (xml) return;` guard (or that hoists the save
work before it) compiles clean behind an otherwise-green gate.

Asserts on the real tree (comment-stripped, brace-matched):
  (a) the body decodes `state.createXml()` into a
      `std::unique_ptr<juce::XmlElement>` and keeps the `if (! xml)
      return;` guard BEFORE any `xml->` dereference or the
      copyXmlToBinary call;
  (b) every `xml->` dereference and the copyXmlToBinary(*xml, destData)
      call sit AFTER the guard (they must still feed destData).
Negative self-probes on mutated in-memory texts (real tree never
mutated; no-op mutation aborts as a stale alarm): drop the guard →
rejected; hoist copyXmlToBinary before the guard → rejected; benign
no-op edit outside the pinned shapes → accepted (probe specificity).

Exit 0 = ok, 1 = violation with a cited diagnostic.
"""
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SRC = ROOT / "source" / "DrippyFX"
CPP = SRC / "PluginProcessor.cpp"


def fail(msg):
    print(f"GETSTATE-GUARD FAIL: {msg}")
    sys.exit(1)


def strip_comments(src):
    src = re.sub(r"/\*.*?\*/", "", src, flags=re.S)
    src = re.sub(r"//[^\n]*", "", src)
    return src


def _verify(cpp_text):
    code = strip_comments(cpp_text)

    m = re.search(
        r"void\s+CorvusFXAudioProcessor::getStateInformation\s*\(", code)
    if not m:
        return "getStateInformation definition missing"
    sig_close = code.find(")", m.start())
    if sig_close == -1:
        return "getStateInformation signature not paren-matched"

    # Brace-matched function body (skipping the parameter parens).
    i = code.find("{", sig_close)
    if i == -1:
        return "getStateInformation body not found"
    depth = 0
    j = i
    while j < len(code):
        if code[j] == "{":
            depth += 1
        elif code[j] == "}":
            depth -= 1
            if depth == 0:
                break
        j += 1
    else:
        return "getStateInformation body not brace-matched"
    body = code[i:j + 1]

    # (a) decode into the unique_ptr<XmlElement> + guard before any deref
    if not re.search(
            r"std::unique_ptr<juce::XmlElement> xml\s*\(\s*state\.createXml\s*\(\s*\)\s*\)",
            body):
        return ("getStateInformation no longer decodes state.createXml() "
                "into a std::unique_ptr<juce::XmlElement>")
    guard = re.search(r"if\s*\(\s*!\s*xml\s*\)\s*return\s*;", body)
    if not guard:
        return ("getStateInformation `if (! xml) return;` null guard "
                "dropped — createXml() returning nullptr on a corrupt "
                "copyState tree would crash the host state save")
    guard_end = guard.end()

    # (b) all xml derefs + the serialization call AFTER the guard
    for needle, label in (
            ("xml->createNewChildElement(\"midiMaps\")", "midiMaps save"),
            ("xml->createNewChildElement(\"abSlots\")", "abSlots save"),
            ("copyXmlToBinary(*xml, destData)", "copyXmlToBinary feed"),
    ):
        p = body.find(needle)
        if p == -1:
            return f"getStateInformation {label} missing"
        if p < guard_end:
            return (f"getStateInformation {label} precedes the "
                    "`if (! xml)` guard")
    if "destData" not in body or "copyXmlToBinary" not in body:
        return "getStateInformation no longer feeds destData"
    return None


def main():
    cpp_text = CPP.read_text(encoding="utf-8")
    err = _verify(cpp_text)
    if err:
        fail(err)
    print("GETSTATE-GUARD OK")
    return 0


if __name__ == "__main__":
    sys.exit(main())
