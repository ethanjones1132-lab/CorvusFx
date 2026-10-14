#!/usr/bin/env python3
"""Headless checker (read-only): A/B-compare snapshots persist with the plugin state.

Premise (filed iter-070, hand-verified): getStateInformation serialized only
apvts.copyState() + the midiMaps child — snapshotA/snapshotB (std::array<float,
24>, PluginProcessor.h) and abSlotIsA lived in NO serialized element, so
reloading a project silently lost both saved snapshots. Worse, the editor
constructor unconditionally called saveSlotA()/saveSlotB() (PluginEditor.cpp),
overwriting both slots with the CURRENT parameter values — so even without a
reload the saved-A snapshot was destroyed by a mere editor reopen, with no
warning.

Asserts (comment-stripped):
  (a) PluginProcessor.cpp getStateInformation creates an "abSlots" child with
      snapshotA/snapshotB base64 float payloads (NUM_AB_PARAMS sized) + a
      "slot" attribute, BEFORE copyXmlToBinary.
  (b) PluginProcessor.cpp setStateInformation reads the abSlots child back
      (convertFromBase64) and only on full success sets abSnapshotsPersisted.
  (c) PluginProcessor.h declares abSnapshotsPersisted defaulting to false.
  (d) PluginEditor.cpp constructor's saveSlotA()/saveSlotB() reseed runs ONLY
      under if (!audioProcessor.hasPersistedABSnapshots()).

Negative self-probes on mutated copies (no-op mutation aborts as a stale
alarm; real tree never mutated): strip the abSlots write; make the constructor
reseed unconditional; strip the abSlots restore; drop the snapshotA child.
Exit 0 = ok, 1 = violation.
"""
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SRC = ROOT / "source" / "DrippyFX"


def fail(msg):
    print(f"AB-SNAPSHOT-PERSISTENCE FAIL: {msg}")
    sys.exit(1)


def strip_comments(src):
    src = re.sub(r"//[^\n]*", "", src)
    src = re.sub(r"/\*.*?\*/", "", src, flags=re.S)
    return src


def body_of(stripped, pattern):
    """Return the brace-balanced body of the first match of pattern."""
    m = re.search(pattern, stripped)
    if not m:
        return None
    i = stripped.find("{", m.start())
    depth = 0
    j = i
    while j < len(stripped):
        if stripped[j] == "{":
            depth += 1
        elif stripped[j] == "}":
            depth -= 1
            if depth == 0:
                break
        j += 1
    return stripped[i : j + 1]


def run_core(cpp_text, ed_text):
    """Core assertions on a candidate pair. Raise _Rejected, or return True."""
    g = strip_comments(cpp_text)
    e = strip_comments(ed_text)
    save = body_of(g, r"void\s+\w+::getStateInformation\s*\(\s*juce::MemoryBlock&")
    if save is None:
        raise _Rejected("getStateInformation missing")
    if 'createNewChildElement("abSlots")' not in save:
        raise _Rejected("abSlots write missing from getStateInformation")
    if 'createNewChildElement("midiMaps")' not in save:
        raise _Rejected("midiMaps invariant drifted in getStateInformation")
    if "copyXmlToBinary" not in save:
        raise _Rejected("copyXmlToBinary missing from getStateInformation")
    if save.find('createNewChildElement("abSlots")') > save.find("copyXmlToBinary"):
        raise _Rejected("abSlots created after copyXmlToBinary — never serialized")
    if 'createNewChildElement("snapshotA")' not in save or \
       'createNewChildElement("snapshotB")' not in save:
        raise _Rejected("abSlots missing snapshotA/snapshotB children")
    if "Base64::toBase64" not in save or "NUM_AB_PARAMS" not in save:
        raise _Rejected("abSlots payload missing Base64/NUM_AB_PARAMS pin")
    if '"slot"' not in save or "abSlotIsA" not in save:
        raise _Rejected("abSlots missing the active-slot attribute")

    restore = body_of(g, r"void\s+\w+::setStateInformation\s*\(\s*const void\*")
    if restore is None:
        raise _Rejected("setStateInformation missing")
    if 'getChildByName("abSlots")' not in restore:
        raise _Rejected("abSlots restore missing from setStateInformation")
    if "convertFromBase64" not in restore:
        raise _Rejected("restore missing convertFromBase64")
    if "abSnapshotsPersisted = false;" not in restore:
        raise _Rejected("restore missing abSnapshotsPersisted=false reset")
    if "abSnapshotsPersisted = true;" not in restore:
        raise _Rejected("restore missing abSnapshotsPersisted=true on success")
    if "abSlotIsA" not in restore:
        raise _Rejected("restore missing the abSlotIsA restore")

    if "bool abSnapshotsPersisted = false;" not in g and \
       "bool abSnapshotsPersisted = false;" not in strip_comments(
           ed_text) and _hdr and "bool abSnapshotsPersisted = false;" not in _hdr:
        raise _Rejected("abSnapshotsPersisted declaration missing")

    if "if (!audioProcessor.hasPersistedABSnapshots())" not in e:
        raise _Rejected("constructor reseed unconditional/un-gated again")
    return True


class _Rejected(Exception):
    pass


_hdr = None  # populated before probes


cpp_path = SRC / "PluginProcessor.cpp"
hdr_path = SRC / "PluginProcessor.h"
ed_path = SRC / "PluginEditor.cpp"
for p in (cpp_path, hdr_path, ed_path):
    if not p.exists():
        fail(f"missing source file {p}")
cpp_raw = cpp_path.read_text()
ed_raw = ed_path.read_text()
hdr_raw = hdr_path.read_text()

# Real-tree assertions (same core, on the live tree)
try:
    run_core(cpp_raw, ed_raw)
except _Rejected as r:
    fail(f"live tree violates the A/B persistence contract: {r}")

hdr_stripped = strip_comments(hdr_raw)
if not re.search(r"bool\s+abSnapshotsPersisted\s*=\s*false\s*;", hdr_stripped):
    fail("PluginProcessor.h missing 'bool abSnapshotsPersisted = false;' — "
         "the editor must be able to read the restored-snapshots flag")
ed_stripped = strip_comments(ed_raw)
if not re.search(
    r"if\s*\(!audioProcessor\.hasPersistedABSnapshots\(\)\s*\)\s*\{[^}]*saveSlotA\(\)",
    ed_stripped,
    flags=re.S,
):
    fail("PluginEditor.cpp constructor saveSlotA() reseed is not inside the "
         "!abSnapshotsPersisted guard")
if not re.search(
    r"if\s*\(!audioProcessor\.hasPersistedABSnapshots\(\)\s*\)\s*\{[^}]*saveSlotB\(\)",
    ed_stripped,
    flags=re.S,
):
    fail("PluginEditor.cpp constructor saveSlotB() reseed is not inside the "
         "!abSnapshotsPersisted guard")
print("ab-persist: getStateInformation serializes snapshotA+snapshotB+slot "
      "under abSlots before copyXmlToBinary")
print("ab-persist: setStateInformation restores both snapshots + slot and "
      "flips abSnapshotsPersisted only on full success")
print("ab-persist: PluginEditor constructor reseed gated on "
      "!abSnapshotsPersisted")

# (5) negative self-probes on mutated copies (real tree never mutated)
_hdr = hdr_raw  # run_core consults the header for the flag declaration
probes = [
    ("make the constructor reseed unconditional again",
     (lambda s: s,
      lambda s: s.replace("if (!audioProcessor.hasPersistedABSnapshots())",
                          "if (true)")),),
    ("strip the abSlots write from getStateInformation",
     (lambda s: s.replace('createNewChildElement("abSlots")',
                          'createNewChildElement("abSlotz")'),
      lambda s: s),),
    ("strip the abSlots restore from setStateInformation",
     (lambda s: s.replace('getChildByName("abSlots")',
                          'getChildByName("abSlotz")'),
      lambda s: s),),
    ("drop the snapshotA child element",
     (lambda s: s.replace('createNewChildElement("snapshotA")',
                          'createNewChildElement("snapshotAz")'),
      lambda s: s),),
]
for label, (cpp_mutate, ed_mutate) in probes:
    mutated_cpp = cpp_mutate(cpp_raw)
    mutated_ed = ed_mutate(ed_raw)
    if mutated_cpp == cpp_raw and mutated_ed == ed_raw:
        fail(f"no-op probe ({label}): mutation did not change the source — "
             "the negative check is vacuous")
    try:
        run_core(mutated_cpp, mutated_ed)
        fail(f"negative probe '{label}' was NOT rejected — checker is vacuous")
    except _Rejected as r:
        print(f"ab-persist: negative probe '{label}' rejected ({r})")

# no-op guard: edits outside the pinned shapes must still pass
neutral_cpp = cpp_raw.replace('randomizeButton.setButtonText("RND");',
                              'randomizeButton.setButtonText("RND!");')
neutral_ed = ed_raw.replace('randomizeButton.setButtonText("RND");',
                            'randomizeButton.setButtonText("RND!");')
try:
    run_core(neutral_cpp, neutral_ed)
except _Rejected:
    fail("neutral edit outside the pinned shapes was REJECTED — checker over-fires")
print("ab-persist: neutral edits pass (probe specificity proven)")
print("ab-persist: OK")
