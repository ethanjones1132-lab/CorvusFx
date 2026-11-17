#!/usr/bin/env python3
"""Headless checker: A/B slot BUTTON wiring roster in PluginEditor.cpp.

The A/B Compare UI entry points are hand-wired lambdas, not attachments,
so no APVTS roster checker sees them:
  - btnSlotA.onClick  -> loadSlotA()  + toggle-state pairing     (:236)
  - btnSlotB.onClick  -> loadSlotB()  + mirrored pairing         (:247)
  - btnSaveAB.onClick -> isSlotA() ? saveSlotA() : saveSlotB()   (:254)
CV-067 removed the editor's first-run reseed: the processor seeds both slots
once in its own constructor, so the editor constructor must stay inert (no
saveSlot call, no snapshot array write) and only reflect the active slot.
grep over all 72 scripts/check_*.py:
check_editor_attachment_pairs pins setupKnob/Attachment id rosters (lambdas
are not attachments — zero hits); check_ab_snapshot_persistence and
check_cv067_ab_snapshots pin the processor-side seeding and the inert editor;
check_undo_wiring pins processor-side beginNewTransaction cardinality only;
check_ab_slot_preset_parity / check_ab_null_param_guard pin the PROCESSOR
bodies. NO checker pins the editor-side lambda wiring.

Falsifications (all compile clean behind an otherwise-green gate):
  - loadSlotA lambda re-targeted at saveSlotA() — clicking A saves the live
    state over the stored snapshot instead of restoring; the undo
    transaction still fires so the gate's txn checkers stay green.
  - the toggle-state pairing deleted — after a click the ON state no longer
    tracks the active slot, so the SAVE button routes snapshots to the slot
    the user just LEFT (isSlotA() reads processor state, but the visual
    radio state lies).
  - the isSlotA() routing deleted in favour of an unconditional
    saveSlotA() — SAVE banked to A while the B radio is lit, silently
    overwriting slot A.
  - the editor constructor reseeds a slot again — opening or closing the
    window overwrites the processor's compare pair (CV-067).

Asserts (comment-stripped PluginEditor.cpp):
  (a) btnSlotA.onClick lambda: exactly one loadSlotA() call plus the
      two setToggleState pairing calls (A true / B false,
      dontSendNotification);
  (b) btnSlotB.onClick lambda: exactly one loadSlotB() call plus the
      mirrored pairing (B true / A false);
  (c) btnSaveAB.onClick lambda: the `isSlotA()` conditional routing to
      saveSlotA()/saveSlotB();
  (d) the editor constructor writes no slot at all (no saveSlot call, no
      snapshotA/snapshotB write) and still reflects the active slot through
      isSlotA().

Self-probes (negative checks, sibling checker style e.g.
check_loadpreset_bounds.py) run on mutated in-memory texts — the real tree
is never mutated. A no-op mutation guard skips probes whose mutation
didn't apply.

Exit 0 = ok, 1 = violation with line-cited diagnostics.
"""
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SRC = ROOT / "source" / "DrippyFX"
ED = SRC / "PluginEditor.cpp"


class Rejected(Exception):
    pass


def strip_comments(src):
    src = re.sub(r"//[^\n]*", "", src)
    src = re.sub(r"/\*.*?\*/", "", src, flags=re.S)
    return src


def lambda_body(stripped, anchor):
    """Return the brace-matched body text of the lambda assigned to anchor."""
    idx = stripped.find(anchor)
    if idx < 0:
        raise Rejected(f"anchor missing: {anchor}")
    b = stripped.find("{", idx)
    if b < 0:
        raise Rejected(f"no brace after {anchor}")
    depth = 0
    j = b
    while j < len(stripped):
        if stripped[j] == "{":
            depth += 1
        elif stripped[j] == "}":
            depth -= 1
            if depth == 0:
                break
        j += 1
    if depth != 0:
        raise Rejected(f"unbalanced lambda body after {anchor}")
    return stripped[b:j + 1]


def slot_write_outside_onclick(body):
    """A saveSlot reference that is NOT the SAVE button's own onClick line.
    The user's SAVE handler legitimately calls saveSlotA()/saveSlotB() from
    inside the constructor; an automatic reseed is anything else."""
    for line in body.splitlines():
        if "saveSlot" in line and ".onClick" not in line:
            return line.strip()
    return None


def extract_editor_ctor(stripped):
    """Brace-matched body of the editor constructor (CV-067: must be inert)."""
    m = re.search(
        r"CorvusFXAudioProcessorEditor::CorvusFXAudioProcessorEditor\s*\(",
        stripped)
    if not m:
        raise Rejected("editor constructor definition missing")
    i = stripped.find("{", m.end() - 1)
    if i < 0:
        raise Rejected("no brace after the editor constructor signature")
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
    if depth != 0:
        raise Rejected("unbalanced editor constructor body")
    return stripped[i:j + 1]


def check_pass(text, label, verbose=False):
    stripped = strip_comments(text)

    def want(cond_name, cond, extra):
        if not cond:
            raise Rejected(f"{label}: {cond_name}: {extra}")
        if verbose:
            print(f"ab-button-wiring: {label}: {cond_name} OK")

    bodyA = lambda_body(stripped, "btnSlotA.onClick")
    want("btnSlotA.onClick loadSlotA count",
         bodyA.count("loadSlotA()") == 1,
         f"must call loadSlotA() exactly once "
         f"(got {bodyA.count('loadSlotA()')})")
    want("btnSlotA.onClick no save/reverse call",
         "saveSlotA()" not in bodyA and "loadSlotB()" not in bodyA,
         "wiring drifted (save/reverse call)")
    want("btnSlotA.onClick toggle pairing",
         bodyA.count("setToggleState(") == 2,
         f"must keep exactly 2 setToggleState calls "
         f"(got {bodyA.count('setToggleState(')})")
    want("btnSlotA.onClick A-true pairing",
         re.search(r"btnSlotA\.setToggleState\(\s*true,", bodyA),
         "missing btnSlotA setToggleState(true)")
    want("btnSlotA.onClick B-false pairing",
         re.search(r"btnSlotB\.setToggleState\(\s*false,", bodyA),
         "missing btnSlotB setToggleState(false)")
    want("btnSlotA.onClick dontSendNotification",
         "dontSendNotification" in bodyA,
         "toggle pairing must stay dontSendNotification")

    bodyB = lambda_body(stripped, "btnSlotB.onClick")
    want("btnSlotB.onClick loadSlotB count",
         bodyB.count("loadSlotB()") == 1,
         f"must call loadSlotB() exactly once "
         f"(got {bodyB.count('loadSlotB()')})")
    want("btnSlotB.onClick no save/reverse call",
         "saveSlotB()" not in bodyB and "loadSlotA()" not in bodyB,
         "wiring drifted (save/reverse call)")
    want("btnSlotB.onClick toggle pairing",
         bodyB.count("setToggleState(") == 2,
         f"must keep exactly 2 setToggleState calls "
         f"(got {bodyB.count('setToggleState(')})")
    want("btnSlotB.onClick B-true pairing",
         re.search(r"btnSlotB\.setToggleState\(\s*true,", bodyB),
         "missing btnSlotB setToggleState(true)")
    want("btnSlotB.onClick A-false pairing",
         re.search(r"btnSlotA\.setToggleState\(\s*false,", bodyB),
         "missing btnSlotA setToggleState(false)")
    want("btnSlotB.onClick dontSendNotification",
         "dontSendNotification" in bodyB,
         "toggle pairing must stay dontSendNotification")

    bodyS = lambda_body(stripped, "btnSaveAB.onClick")
    want("btnSaveAB.onClick isSlotA routing",
         re.search(r"\bif\s*\(\s*audioProcessor\.isSlotA\(\)\s*\)\s*"
                   r"audioProcessor\.saveSlotA\(\);\s*else\s*"
                   r"audioProcessor\.saveSlotB\(\);", bodyS),
         "must keep the isSlotA() ? saveSlotA() : saveSlotB() routing")
    want("btnSaveAB.onClick no LOAD routine",
         "loadSlot" not in bodyS, "SAVE button wired to a LOAD routine")

    ctor = extract_editor_ctor(stripped)
    want("constructor writes no A/B slot",
         slot_write_outside_onclick(ctor) is None,
         "opening the editor must not reseed the processor's compare pair")
    want("constructor writes no snapshot array",
         "snapshotA" not in ctor and "snapshotB" not in ctor,
         "the snapshot arrays belong to the processor")
    want("constructor reflects the active slot (A)",
         re.search(r"btnSlotA\s*\.\s*setToggleState\s*\(\s*"
                   r"audioProcessor\s*\.\s*isSlotA\s*\(\s*\)", ctor),
         "missing the btnSlotA isSlotA() reflect")
    want("constructor reflects the active slot (B)",
         re.search(r"btnSlotB\s*\.\s*setToggleState\s*\(\s*!\s*"
                   r"audioProcessor\s*\.\s*isSlotA\s*\(\s*\)", ctor),
         "missing the btnSlotB !isSlotA() reflect")


def _verify(obj):
    try:
        _run_probe_text(obj)
        return None
    except Rejected as r:
        return str(r)


def _run_probe_text(text):
    """Run ALL structural probes on in-memory `text` (real tree untouched)."""
    check_pass(text, "probe")


PROBES = [
    # probe 1: loadSlotA re-targeted at saveSlotA — the A click BANKS the
    # live state over the stored snapshot instead of restoring it
    ("A click saves instead of loads",
     "btnSlotA.onClick = [this] { audioProcessor.loadSlotA();",
     "btnSlotA.onClick = [this] { audioProcessor.saveSlotA();",
     "audioProcessor.saveSlotA();"),
    # probe 2: A-lambda toggle pairing deleted — the radio state no longer
    # tracks the slot the user just loaded, and SAVE bank to the OTHER slot
    ("A-click toggle pairing deleted",
     "audioProcessor.loadSlotA(); btnSlotA.setToggleState(true, "
     "juce::dontSendNotification); btnSlotB.setToggleState(false, "
     "juce::dontSendNotification);",
     "audioProcessor.loadSlotA();",
     "audioProcessor.loadSlotA();"),
    # probe 3: SAVE routing collapsed; unconditional saveSlotA always fires
    ("SAVE routing collapsed to unconditional saveSlotA",
     "if (audioProcessor.isSlotA()) audioProcessor.saveSlotA(); "
     "else audioProcessor.saveSlotB();",
     "audioProcessor.saveSlotA();",
     "audioProcessor.saveSlotA();"),
    # probe 4: the editor constructor reseeds a slot again (CV-067)
    ("editor constructor reseeds slot A",
     "    btnSlotA.setToggleState(audioProcessor.isSlotA(), "
     "juce::dontSendNotification);",
     "    audioProcessor.saveSlotA();\n"
     "    btnSlotA.setToggleState(audioProcessor.isSlotA(), "
     "juce::dontSendNotification);",
     "audioProcessor.saveSlotA();"),
]


def _reject(mutated, label, needle):
    """Assert the mutation is rejected; no-op mutation -> skip probe."""
    applied = needle in mutated
    verdict = _verify(mutated)
    if verdict is None:
        if applied:
            return False  # rejected never happened -> caller must FAIL
        sys.stdout.write(
            f"AB-BUTTON-WIRING: no-op mutation guard -> skipping "
            f"invalid probe ({label})\n")
        return True
    return True


def main():
    text = ED.read_text(encoding="utf-8")
    try:
        check_pass(text, "real tree")
    except Rejected as r:
        print(f"AB-BUTTON-WIRING FAIL: {r}")
        return 1
    print("ab-button-wiring: slot A/B/SAVE lambdas + inert constructor pinned "
          "(1x loadSlotA + pairing, 1x loadSlotB + mirrored pairing, "
          "isSlotA routing, no constructor reseed, active-slot reflect)")

    for label, old, new, needle in PROBES:
        mutated = text.replace(old, new, 1)
        if mutated == text:
            print(f"ab-button-wiring: no-op mutation guard -> skipping "
                  f"invalid probe ({label})")
            continue
        verdict = _verify(mutated)
        if verdict is None and needle in mutated:
            print(f"AB-BUTTON-WIRING FAIL: negative probe '{label}' was "
                  f"NOT rejected — checker is vacuous")
            return 1
        print(f"ab-button-wiring: negative probe '{label}' rejected")

    # no-op guard: benign whitespace addition stays accepted
    neutral = text.replace(
        "btnSaveAB.setButtonText(\"SAVE\");",
        "btnSaveAB.setButtonText( \"SAVE\" );")
    if neutral == text:
        print("AB-BUTTON-WIRING FAIL: unanchored neutral edit didn't apply")
        return 1
    try:
        check_pass(neutral, "benign whitespace no-op")
    except Rejected as r:
        print(f"AB-BUTTON-WIRING FAIL: over-fires on neutral edit: {r}")
        return 1
    print("ab-button-wiring: benign no-op accepted (specificity proven)")

    # real tree never mutated — re-verify the live source once more
    try:
        check_pass(ED.read_text(encoding="utf-8"), "final re-verify")
    except Rejected as r:
        print(f"AB-BUTTON-WIRING FAIL: final re-verify failed: {r}")
        return 1
    print("AB-BUTTON-WIRING OK")
    return 0


if __name__ == "__main__":
    sys.exit(main())
