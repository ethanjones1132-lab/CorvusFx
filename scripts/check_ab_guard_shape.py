#!/usr/bin/env python3
"""Headless checker: abSlots nullptr-branch guard shape across the state IO.

The abSlots child element is the ONLY element creation in the save path
consumed as an initialisation-condition guard:

    if (auto* abXml = xml->createNewChildElement("abSlots"))
    {
        abXml->setAttribute("slot", ...);
        abXml->createNewChildElement("snapshotA")->addTextElement(
            juce::Base64::toBase64(snapshotA.data(), ... NUM_AB_PARAMS ...));
        abXml->createNewChildElement("snapshotB")->addTextElement(
            juce::Base64::toBase64(snapshotB.data(), ... NUM_AB_PARAMS ...));
    }

contrast the sibling midiMaps bare-init + `if (mapsXml)` body guard.
Refactors that "harmonise" the abSlots write into an unguarded
`auto* abXml = ...;` bare assignment leave the subsequent abXml-> writes
dereferencing nullptr on an allocation failure during a host state-save.
The mirrored restore side must keep the reverse shape: an abSlots child
lookup consumed as an if-init condition, never a bare assignment.

grep over all scripts/check_*.py: check_ab_snapshot_persistence.py pins the
"abSlots" tag presence/order only (its negatives mutate tag strings);
check_ab_restore_guards.py pins the RESTORE-side per-slot if-init chain;
check_getstate_null_guard.py pins the root-xml null return only;
check_midimaps_save_guard.py pins the sibling midiMaps guard only. NOTHING
pins the abSlots CREATE-side if-init form or the two-direction symmetry.

Asserts on the real tree (comment-stripped):
  (a) in getStateInformation the abSlots creation stays consumed ONLY as
      an if-init condition `if (auto* abXml =
      xml->createNewChildElement("abSlots"))` whose brace-matched body
      holds the slot attribute and BOTH Base64 snapshot writes; no
      `createNewChildElement("abSlots")` result consumed outside a guard
      (negative symmetry);
  (b) the sibling midiMaps child stays the bare-init form guarded by a
      separate `if (mapsXml)` body guard (the asymmetry that harmonisation
      would destroy is pinned BOTH ways);
  (c) in setStateInformation the abSlots lookup stays consumed ONLY as
      `if (auto* abXml = xml->getChildByName("abSlots"))`, never a bare
      assignment.
Negatives self-probe mutated in-memory texts (real tree never mutated;
no-op mutation aborts as a stale alarm): abSlots save harmonised to a
bare assignment → rejected; abSlots save guard dropped with body hoisted
→ rejected; a bare-init abSlots created outside a guard (new call) →
rejected; midiMaps harmonised to the if-init form → rejected (roster
asymmetry); restore-side rewrite to bare assignment → rejected; benign
no-op accepted (probe specificity).

Exit 0 = ok, 1 = violation with a cited diagnostic.
"""
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
CPP = ROOT / "source" / "DrippyFX" / "PluginProcessor.cpp"


def fail(msg):
    print(f"AB-GUARD-SHAPE FAIL: {msg}")
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


def fn_body(code, rx):
    m = re.search(rx, code)
    if not m:
        return None
    sig_close = code.find(")", m.start())
    i = code.find("{", sig_close)
    if i == -1:
        return None
    close = brace_span(code, i)
    if close == -1:
        return None
    return code[i:close + 1]


def _verify(cpp_text):
    code = strip_comments(cpp_text)

    # ---------- save side ----------
    body = fn_body(
        code, r"void\s+CorvusFXAudioProcessor::getStateInformation\s*\(")
    if body is None:
        return "getStateInformation definition missing"

    # (a) abSlots creation consumed ONLY as an if-init condition
    ab_open = re.search(
        r'if\s*\(\s*auto\s*\*\s*abXml\s*=\s*xml->createNewChildElement'
        r'\s*\(\s*"abSlots"\s*\)\s*\)', body)
    if not ab_open:
        return ('the abSlots save must stay consumed as an if-init condition '
                '`if (auto* abXml = xml->createNewChildElement("abSlots"))` '
                '— harmonising it into a bare assignment leaves the '
                'subsequent abXml-> writes dereferencing nullptr on an '
                'allocation failure during a host state-save')
    ab_close = brace_span(body, ab_open.start())
    if ab_close == -1:
        return "abSlots guard block not brace-matched"
    guard = body[ab_open.start():ab_close + 1]
    if 'setAttribute("slot"' not in guard or "abSlotIsA" not in guard:
        return "abSlots guard lost the slot attribute write"
    if guard.count("Base64::toBase64") != 2:
        return ("abSlots guard must hold BOTH Base64 snapshot writes "
                f"(found {guard.count('Base64::toBase64')})")
    if "NUM_AB_PARAMS" not in guard:
        return "abSlots guard lost the NUM_AB_PARAMS sized payload"
    # negative symmetry: NO other createNewChildElement("abSlots") call in
    # the body (a bare-init second call / duplicated creation is foreign)
    n_create = body.count('createNewChildElement("abSlots")')
    if n_create != 1:
        return (f"expected exactly 1 createNewChildElement(\"abSlots\") in "
                f"getStateInformation, found {n_create} — a creation consumed "
                "outside the pinned if-init guard is not part of the shape")

    # (b) the sibling midiMaps child stays the BARE-init form guarded by a
    #     separate if (mapsXml) body guard (the asymmetry is pinned both ways)
    if not re.search(
            r'auto\s*\*\s*mapsXml\s*=\s*xml->createNewChildElement\s*\(\s*'
            r'"midiMaps"\s*\)\s*;', body):
        return ('the midiMaps child must stay the bare-init form '
                '`auto* mapsXml = xml->createNewChildElement("midiMaps");` '
                '— harmonising BOTH creations erases the pinned asymmetry')
    if "if (mapsXml)" not in body:
        return "the sibling midiMaps `if (mapsXml)` body guard went missing"
    if re.search(
            r'if\s*\(\s*auto\s*\*\s*\w+\s*=\s*xml->createNewChildElement'
            r'\s*\(\s*"midiMaps"\s*\)\s*\)', body):
        return ('midiMaps harmonised into the if-init form — the pinned '
                'bare-init + body-guard asymmetry was destroyed in the '
                'other direction')

    # ---------- restore side ----------
    rbody = fn_body(
        code, r"void\s+CorvusFXAudioProcessor::setStateInformation\s*\(")
    if rbody is None:
        return "setStateInformation definition missing"
    if not re.search(
            r'if\s*\(\s*auto\s*\*\s*abXml\s*=\s*xml->getChildByName\s*\(\s*'
            r'"abSlots"\s*\)\s*\)', rbody):
        return ('the abSlots restore must stay consumed as an if-init '
                'condition `if (auto* abXml = xml->getChildByName('
                '"abSlots"))` — a bare assignment null-derefs abXml on a '
                'state that carries no abSlots child (older saves)')

    return None


NOOP_MUTATION = "/*ABGUARD-NOOP-STALENESS-PROBE*/"


def probe_rejects(text, name):
    err = _verify(text)
    if err is None:
        fail(f"negative probe '{name}' did NOT reject the mutated shape")


def probe_accepts(text, name):
    err = _verify(text)
    if err is not None:
        fail(f"specificity probe '{name}' unexpectedly REJECTED the real "
             f"shape: {err}")


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

    # (1) abSlots save harmonised into a bare assignment (null-deref class)
    probe_rejects(cpp_text.replace(
        'if (auto* abXml = xml->createNewChildElement("abSlots"))',
        'auto* abXml = xml->createNewChildElement("abSlots");'),
        "abSlots save harmonised to bare assignment")

    # (2) abSlots save guard dropped entirely with the snapshot writes left
    #     in place (allocation-failure deref class)
    probe_rejects(cpp_text.replace(
        'if (auto* abXml = xml->createNewChildElement("abSlots"))', "", 1),
        "abSlots save guard dropped")

    # (3) a SECOND abSlots creation call (consumption outside the pinned
    #     guard / duplicated write class)
    probe_rejects(cpp_text.replace(
        'createNewChildElement("snapshotA")',
        'createNewChildElement("abSlots") /*stray*/; createNewChildElement("snapshotA")', 1),
        "stray abSlots creation outside a guard")

    # (4) midiMaps harmonised into the if-init form (asymmetry destroyed in
    #     the OTHER direction)
    probe_rejects(cpp_text.replace(
        'auto* mapsXml = xml->createNewChildElement("midiMaps");',
        'if (auto* mapsXml = xml->createNewChildElement("midiMaps"))'),
        "midiMaps harmonised to if-init form")

    # (5) restore-side abSlots lookup rewritten to a bare assignment
    probe_rejects(cpp_text.replace(
        'if (auto* abXml = xml->getChildByName("abSlots"))',
        'auto* abXml = xml->getChildByName("abSlots");'),
        "abSlots restore rewritten to bare assignment")

    print("AB-GUARD-SHAPE OK")
    return 0


if __name__ == "__main__":
    sys.exit(main())
