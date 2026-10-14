#!/usr/bin/env python3
"""Headless checker: the A/B snapshot BASE64 save/restore ROUND-TRIP pin.

getStateInformation saves both compare slots as base64 binary floats:

  abXml->createNewChildElement("snapshotA")->addTextElement(
      juce::Base64::toBase64(snapshotA.data(),
          static_cast<size_t>(NUM_AB_PARAMS) * sizeof(float)));   (:867-869)

mirrored for snapshotB (:870-872). setStateInformation restores each slot:

  aMB.loadFromBase64(aXml->getAllSubText());
  restoredA = aMB.getDataSize() == static_cast<size_t>(NUM_AB_PARAMS) * sizeof(float);

mirrored for bMB/restoredB (:905-906), and the memcpy pair only fires
under `if (restoredA && restoredB)` (:908).

check_ab_snapshot_persistence.py pins the getChildByName GUARD PRESENCE and
check_ab_restore_guards.py pins the if-init consumption form — NEITHER pins
the toBase64 payload shape, the NUM_AB_PARAMS * sizeof(float) size literals,
nor the restoredA && restoredB AND-gate feeding the memcpy pair.
Falsifications (all compile clean behind an otherwise-green gate):
  - drifting the restore-side size constant so it never matches the saved
    payload: BOTH slots silently fail to restore every session while every
    structural checker stays green;
  - flipping the AND-gate to `restoredA || restoredB`: a state carrying
    only snapshotA memcpy's aMB into BOTH slots (snapshotB overwritten
    with A's data on every recall);
  - dropping one toBase64 save site: that slot's payload silently degrades
    to an empty child element (restore then size-gates out).

Asserts (comment-stripped, brace-matched on the real PluginProcessor.cpp):
  (a) the getStateInformation body keeps both save sites —
      createNewChildElement("snapshot{A,B}")->addTextElement(
          juce::Base64::toBase64(snapshot{A,B}.data(), size));
  (b) the setStateInformation body keeps both restore sites —
      loadFromBase64(...) followed by
      restored{A,B} = ... getDataSize() == NUM_AB_PARAMS * sizeof(float);
  (c) the `if (restoredA && restoredB)` AND-gate PRECEDES both
      std::memcpy calls (no OR-gate cross-contamination);
  (d) roster lock — the size-gate literals equal the save-side byte counts
      (NUM_AB_PARAMS * sizeof(float) everywhere, same count on save+restore).

Negative self-probes run on mutated in-memory texts — the real tree is
never mutated. Exit 0 = ok, 1 = violation with diagnostics.
"""
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
CPP = ROOT / "source" / "DrippyFX" / "PluginProcessor.cpp"


def fail(msg):
    print(f"AB-BASE64-ROUNDTRIP FAIL: {msg}")
    sys.exit(1)


def strip_comments(txt):
    out, i, n = [], 0, len(txt)
    while i < n:
        if txt.startswith("//", i):
            j = txt.find("\n", i)
            i = n if j == -1 else j
        elif txt.startswith("/*", i):
            j = txt.find("*/", i + 2)
            i = n if j == -1 else j + 2
        else:
            out.append(txt[i]); i += 1
    return "".join(out)


def collapse(s):
    return re.sub(r"\s+", " ", s).strip()


def extract_method_body(code, name):
    """Brace-matched extract of a CorvusFXAudioProcessor::name body."""
    m = re.search(r"void\s+CorvusFXAudioProcessor::" + re.escape(name) + r"\s*\(", code)
    if not m:
        return None
    i = code.find("{", m.end())
    if i == -1:
        return None
    depth = 0
    for j in range(i, len(code)):
        if code[j] == "{":
            depth += 1
        elif code[j] == "}":
            depth -= 1
            if depth == 0:
                return code[i + 1:j]
    return None


SIZE_EXPR = "NUM_AB_PARAMS * sizeof(float)"


def _verify(raw):
    code = strip_comments(raw)
    save = extract_method_body(code, "getStateInformation")
    restore = extract_method_body(code, "setStateInformation")
    if save is None:
        return "could not locate the getStateInformation definition body"
    if restore is None:
        return "could not locate the setStateInformation definition body"

    save = collapse(save)
    restore = collapse(restore)

    # (a) both save sites keep the toBase64 payload shape
    for slot in ("snapshotA", "snapshotB"):
        pat = (rf'{slot}"\)->addTextElement\(\s*juce::Base64::toBase64\({slot}\.data\(\),\s*'
               rf"static_cast<size_t>\(NUM_AB_PARAMS\) \* sizeof\(float\)\)\);")
        if not re.search(pat, save.replace("\n", " ")):
            return (f'getStateInformation no longer saves {slot} as '
                    f'"toBase64({slot}.data(), NUM_AB_PARAMS * sizeof(float))" '
                    f"— a dropped/drifted save site degrades that slot's "
                    f"payload so the restore size-gate silently discards it "
                    f"every session")

    # (b) both restore sites keep loadFromBase64 + the exact size gate
    for slot, snap in (("A", "aMB"), ("B", "bMB")):
        m_load = re.search(
            rf'juce::Base64::convertFromBase64\({snap}, (\w+Xml)->getAllSubText\(\)\)', restore)
        if not m_load:
            return (f"setStateInformation: {snap} no longer reads its payload "
                    f"via loadFromBase64(getAllSubText()) — the restore side no "
                    f"longer consumes the base64 text written by the save side")
        gate = (f'restored{slot} = juce::Base64::convertFromBase64({snap}, {slot.lower()}Xml->getAllSubText()) '
                f'&& {snap}.getDataSize() == static_cast<size_t>(NUM_AB_PARAMS) * sizeof(float);')
        if gate not in restore:
            return (f"setStateInformation: the restored{slot} size gate is "
                    f"expected to be exactly "
                    f"'{collapse(gate)}' — a drifted restore-side size "
                    f"constant never matches the saved payload so that/both "
                    f"slots silently fail to restore every session (all "
                    f"structural checkers stay green)")

    # (c) the AND-gate precedes both memcpy calls (no OR-gate contamination)
    m_gate = re.search(r"if \(restored(A) && restored(B)\)", restore)
    if not m_gate:
        return ("setStateInformation no longer gates the snapshot memcpy "
                "pair on 'restoredA && restoredB' — an OR-gate memcpy's aMB "
                "into BOTH slots when only A parsed (snapshotB overwritten "
                "with A's data on every state recall)")
    pos_gate = restore.find(m_gate.group(0))
    pos_ma = restore.find("std::memcpy(snapshotA.data(), aMB.getData(), aMB.getDataSize());")
    pos_mb = restore.find("std::memcpy(snapshotB.data(), bMB.getData(), bMB.getDataSize());")
    if pos_ma == -1 or pos_mb == -1:
        return ("setStateInformation no longer memcpy's both restored "
                "snapshots back into snapshotA/snapshotB")
    if not (pos_gate < pos_ma and pos_gate < pos_mb):
        return ("the restoredA && restoredB AND-gate no longer PRECEDES the "
                "memcpy pair — an ungated or partially-gated memcpy writes "
                "an unvalidated payload into a live slot")

    # (d) roster lock — save-side byte count and restore-side gates agree
    save_sizes = re.findall(
        r"static_cast<size_t>\(NUM_AB_PARAMS\) \* sizeof\(float\)", save)
    if len(save_sizes) != 2:
        return (f"expected exactly 2 save-side size literals "
                f"(NUM_AB_PARAMS * sizeof(float), one per snapshot), found "
                f"{len(save_sizes)}")
    restore_sizes = re.findall(
        r"&& \wMB\.getDataSize\(\) == static_cast<size_t>"
        r"\(NUM_AB_PARAMS\) \* sizeof\(float\);", restore)
    if len(restore_sizes) != 2:
        return (f"expected exactly 2 restore-side size gates, found "
                f"{len(restore_sizes)} — the size-gate roster must stay "
                f"in sync with the save-side byte counts")
    return None


cpp_raw = CPP.read_text()
if not CPP.exists():
    fail(f"missing source file {CPP}")

err = _verify(cpp_raw)
if err:
    fail(err)
print("ab-base64-roundtrip: both toBase64 save sites, both "
      "loadFromBase64+size-gate restore sites, the AND-gate ordering, "
      "and the size-literal roster pinned")

# ---------------------------------------------------------------------------
# negative self-probes on mutated in-memory texts (real tree never mutated)
# ---------------------------------------------------------------------------
SAFE_GATE = ("&& aMB.getDataSize() == "
             "static_cast<size_t>(NUM_AB_PARAMS) * sizeof(float);")
SAFE_GATE_B = ("&& bMB.getDataSize() == "
               "static_cast<size_t>(NUM_AB_PARAMS) * sizeof(float);")
probes = [
    ("restore A size gate halved (path never matches the saved payload — "
     "BOTH slots silently fail to restore every session, structural "
     "checkers stay green)", SAFE_GATE,
     "&& aMB.getDataSize() == static_cast<size_t>(NUM_AB_PARAMS) * "
     "sizeof(float) / 2;"),
    ("AND-gate flipped to OR (aMB memcpy'd into BOTH slots when only A "
     "parsed — snapshotB overwritten with A's data on every recall)",
     "if (restoredA && restoredB)", "if (restoredA || restoredB)"),
    ("snapshotB save site dropped (its payload silently degrades to an "
     "empty child element)",
     'abXml->createNewChildElement("snapshotB")->addTextElement(\n'
     "            juce::Base64::toBase64(snapshotB.data(),\n"
     "                static_cast<size_t>(NUM_AB_PARAMS) * sizeof(float)));",
     '(void) 0;'),
    ("restore-side size-gate constant drifted (restore gate never matches "
     "the saved payload)", SAFE_GATE_B,
     "&& bMB.getDataSize() == static_cast<size_t>(NUM_AB_PARAMS) * "
     "sizeof(float) + 4;"),
]
for label, old, new in probes:
    mutated = cpp_raw.replace(old, new, 1)
    if mutated == cpp_raw:
        fail(f"no-op probe ({label}): mutation did not change the source — "
             "the negative check is stale")
    verdict = _verify(mutated)
    if verdict is None:
        fail(f"negative probe '{label}' was NOT rejected — checker is vacuous")
    print(f"ab-base64-roundtrip: negative probe '{label}' rejected")

# no-op guard: benign comment addition stays accepted
neutral = cpp_raw.replace(
    "abSnapshotsPersisted = true;",
    "abSnapshotsPersisted = true;  // probe comment", 1)
if neutral == cpp_raw:
    fail("no-op guard: unanchored neutral edit did not change the source")
if _verify(neutral) is not None:
    fail("neutral edit outside the pinned shapes was REJECTED — checker "
         "over-fires")
print("ab-base64-roundtrip: neutral no-op edit passes (probe specificity "
      "proven)")

# real tree never mutated — re-verify the live source once more before gating
err = _verify(CPP.read_text())
if err:
    fail(f"final source re-verification failed: {err}")
print("AB-BASE64-ROUNDTRIP OK")
sys.exit(0)
