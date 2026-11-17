#!/usr/bin/env python3
"""Check (CV-067): the A/B compare slots belong to the processor, not the editor.

Premise (filed): the editor constructor reseeded both slots with
`if (!audioProcessor.hasPersistedABSnapshots()) saveSlotA(); saveSlotB();`
(PluginEditor.cpp). Two defects came with it:

  * opening the editor MUTATED plugin state. Any session whose host state
    carried no "abSlots" child was rewritten the moment a window opened, so a
    recall that should be inert could overwrite a compare pair.
  * a state saved before the seeded slots existed restored two all-zero arrays
    (snapshotA/snapshotB `fill(0.0f)` in setStateInformation) and depended on
    that editor reseed to become usable. With the window closed, or with any
    future editor change, recalling either slot wrote an all-zero mix.

The fix pins the ownership in the processor:

  (a) PluginProcessor.cpp constructor seeds both slots ONCE from the settled
      live parameter values (`seedABSnapshotsFromLiveParameters();`) after the
      CV-066 default `loadPreset(0);` has settled them, and marks them
      persisted (`abSnapshotsPersisted = true;`). The constructor ordering is
      part of the contract: a seed before the default preset load would
      capture the pre-load parameter defaults.
  (b) PluginEditor.cpp never writes the slots: its constructor contains no
      saveSlot call and no snapshot array write, and every saveSlot call in
      the file sits on an `onClick` handler line (user SAVE only). The
      constructor still reflects the active slot (isSlotA()).
  (c) setStateInformation keeps its unconditional stale-state reset, and then
      every path that did not restore a complete saved pair derives both slots
      from the parameters the restore just applied:
      `if (! abSnapshotsPersisted) seedABSnapshotsFromLiveParameters();` after
      the abSlots branch, with no `return` between the reset and that seed, so
      no restore path can finish with unseeded (all-zero) slots.

Negative self-probes on mutated in-memory texts (real tree never mutated,
no-op mutation aborts as a stale alarm): re-introduce the editor reseed;
remove the constructor seed; move the constructor seed before the default
preset load; remove the restore fallback seed; make the fallback seed
unconditional (it would stomp a restored pair with live values); insert a
`return` between the reset and the fallback. A benign edit outside the pinned
shapes must still pass.

Exit 0 = ok, 1 = violation with diagnostics.
"""
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SRC = ROOT / "source" / "DrippyFX"
CPP = SRC / "PluginProcessor.cpp"
HDR = SRC / "PluginProcessor.h"
ED = SRC / "PluginEditor.cpp"

PROCESSOR = "CorvusFXAudioProcessor"
EDITOR = "CorvusFXAudioProcessorEditor"
SEED_CALL = "seedABSnapshotsFromLiveParameters"


def strip_comments(text):
    text = re.sub(r"/\*.*?\*/", lambda m: "\n" * m.group(0).count("\n"),
                  text, flags=re.S)
    return re.sub(r"//[^\n]*", "", text)


def braced_span(text, opening):
    depth = 0
    for i in range(opening, len(text)):
        if text[i] == "{":
            depth += 1
        elif text[i] == "}":
            depth -= 1
            if depth == 0:
                return opening, i + 1, text[opening + 1:i]
    return None


def body_after(code, pattern):
    """Brace-matched body of the first regex match (brace at/after match end)."""
    match = re.search(pattern, code, flags=re.S)
    if not match:
        return None
    opening = code.find("{", match.end() - 1)
    if opening < 0:
        return None
    return braced_span(code, opening)


CTOR = rf"{PROCESSOR}::{PROCESSOR}\s*\("
SEED_DEF = rf"void\s+{PROCESSOR}::{SEED_CALL}\s*\(\s*\)"


def slot_write_outside_onclick(body):
    """A saveSlot reference that is NOT the SAVE button's own onClick line.

    The user's SAVE handler legitimately calls saveSlotA()/saveSlotB() from
    inside the editor constructor, so a bare substring test over the body
    rejects the very wiring CV-067 keeps. An automatic reseed is a saveSlot
    reference that sits on any other line.
    """
    for line in body.splitlines():
        if "saveSlot" in line and ".onClick" not in line:
            return line.strip()
    return None
RESTORE = (rf"void\s+{PROCESSOR}::setStateInformation\s*"
           r"\(\s*const\s+void\s*\*\s*\w+\s*,\s*int\s+\w+\s*\)")
EDITOR_CTOR = rf"{EDITOR}::{EDITOR}\s*\("

SEED_ONCE = re.compile(rf"{SEED_CALL}\s*\(\s*\)\s*;\s*"
                       r"abSnapshotsPersisted\s*=\s*true\s*;")
FALLBACK = re.compile(r"if\s*\(\s*!\s*abSnapshotsPersisted\s*\)\s*"
                      rf"{SEED_CALL}\s*\(\s*\)\s*;")
ZERO_RESET = re.compile(r"snapshotA\s*\.\s*fill\s*\(\s*0(?:\.0)?f?\s*\)")


def read_source(path):
    """Read a source file as LF-normalised UTF-8 (CRLF must not move anchors)."""
    return path.read_text(encoding="utf-8", errors="replace").replace("\r\n", "\n")


def verify(cpp_text=None, hdr_text=None, ed_text=None):
    if cpp_text is None:
        cpp_text = read_source(CPP)
    if hdr_text is None:
        hdr_text = read_source(HDR)
    if ed_text is None:
        ed_text = read_source(ED)

    cpp = strip_comments(cpp_text)
    hdr = strip_comments(hdr_text)
    ed = strip_comments(ed_text)
    errors = []

    # -- (a) header: the seed helper and the persisted flag -----------------
    if not re.search(rf"void\s+{SEED_CALL}\s*\(\s*\)\s*;", hdr):
        errors.append(f"PluginProcessor.h lost the `void {SEED_CALL}();` "
                      "declaration - the processor-side seed has no entry")
    if not re.search(r"bool\s+abSnapshotsPersisted\s*=\s*false\s*;", hdr):
        errors.append("PluginProcessor.h lost `bool abSnapshotsPersisted = "
                      "false;` - the seeded/restored flag defaulted differently")

    # -- (b) the seed helper fills BOTH slots from live values, read-only ---
    seed_span = body_after(cpp, SEED_DEF)
    if seed_span is None:
        errors.append(f"PluginProcessor.cpp lost the {SEED_CALL} definition - "
                      "nothing seeds the slots at construction")
    else:
        seed_body = seed_span[2]
        if "for (int i = 0; i < NUM_AB_PARAMS; ++i)" not in seed_body:
            errors.append("the seed must cover the whole NUM_AB_PARAMS roster")
        if "getParameter(abParamIds[i])" not in seed_body:
            errors.append("the seed must resolve getParameter(abParamIds[i])")
        if not re.search(r"if\s*\(\s*p\s*\)", seed_body):
            errors.append("the seed must keep its `if (p)` null guard")
        for slot in ("snapshotA", "snapshotB"):
            writes = re.findall(slot + r"\[i\]\s*=", seed_body)
            if len(writes) != 1:
                errors.append(f"the seed must write {slot}[i] exactly once "
                              f"(found {len(writes)}) - an unseeded slot "
                              "recalls an all-zero mix")
            if not re.search(slot + r"\[i\]\s*=\s*p->getValue\s*\(\s*\)", seed_body):
                errors.append(f"the seed must copy the live {slot} value via "
                              "p->getValue()")
        for needle, label in (("beginNewTransaction", "an undo transaction"),
                              ("beginChangeGesture", "a change gesture"),
                              ("setValueNotifyingHost", "a host notification")):
            if needle in seed_body:
                errors.append(f"the seed must not raise {label} ({needle}) - a "
                              "seed is not a user edit")

    # -- (c) constructor: seed once, after the default preset load ----------
    ctor_span = body_after(cpp, CTOR)
    if ctor_span is None:
        errors.append(f"could not find the {PROCESSOR} constructor body")
    else:
        ctor = ctor_span[2]
        if not SEED_ONCE.search(ctor):
            errors.append("the constructor must seed both slots once and mark "
                          f"them persisted (`{SEED_CALL}(); "
                          "abSnapshotsPersisted = true;`) - without it a fresh "
                          "session has no usable A/B pair")
        seed_calls = re.findall(SEED_CALL + r"\s*\(\s*\)", ctor)
        if len(seed_calls) != 1:
            errors.append(f"the constructor must seed exactly once (found "
                          f"{len(seed_calls)} calls)")
        load = ctor.find("loadPreset(0);")
        seed_at = ctor.find(SEED_CALL)
        if load < 0:
            errors.append("the constructor lost its default `loadPreset(0);` - "
                          "the seed origin cannot be pinned")
        elif seed_at < 0 or seed_at < load:
            errors.append("the constructor seed must come AFTER the default "
                          "`loadPreset(0);` - a seed before it captures the "
                          "pre-load parameter defaults instead of the state a "
                          "fresh insert plays")
        flag_writes = re.findall(r"abSnapshotsPersisted\s*=\s*true\s*;", ctor)
        if len(flag_writes) != 1:
            errors.append(f"the constructor must mark the seeded pair once "
                          f"(found {len(flag_writes)} writes)")

    # -- (d) editor: inert. No automatic slot writes ------------------------
    ed_ctor_span = body_after(ed, EDITOR_CTOR)
    if ed_ctor_span is None:
        errors.append(f"could not find the {EDITOR} constructor body")
    else:
        ed_ctor = ed_ctor_span[2]
        if slot_write_outside_onclick(ed_ctor) is not None:
            errors.append("the editor constructor writes an A/B slot again - "
                          "opening the window must never reseed the processor's "
                          "compare pair")
        for needle in ("snapshotA", "snapshotB"):
            if needle in ed_ctor:
                errors.append(f"the editor constructor touches {needle} - the "
                              "arrays belong to the processor")
        if not re.search(r"btnSlotA\s*\.\s*setToggleState\s*\(\s*"
                         r"audioProcessor\s*\.\s*isSlotA\s*\(\s*\)", ed_ctor):
            errors.append("the editor constructor must still reflect the "
                          "processor's active slot (btnSlotA)")
        if not re.search(r"btnSlotB\s*\.\s*setToggleState\s*\(\s*!\s*"
                         r"audioProcessor\s*\.\s*isSlotA\s*\(\s*\)", ed_ctor):
            errors.append("the editor constructor must still reflect the "
                          "processor's active slot (btnSlotB)")
    for needle in ("snapshotA", "snapshotB"):
        if needle in ed:
            errors.append(f"PluginEditor.cpp references {needle} - the "
                          "snapshot arrays belong to the processor (CV-067)")
    for match in re.finditer(r"saveSlot[AB]\s*\(\s*\)", ed):
        line_start = ed.rfind("\n", 0, match.start()) + 1
        line_end = ed.find("\n", match.start())
        line = ed[line_start:line_end if line_end >= 0 else len(ed)]
        if ".onClick" not in line:
            errors.append("the editor calls saveSlot outside an onClick "
                          "handler - only the user SAVE click may write a slot")
            break

    # -- (e) restore: fall back to the restored parameters, never zeros -----
    restore_span = body_after(cpp, RESTORE)
    if restore_span is None:
        errors.append(f"could not find the {PROCESSOR}::setStateInformation "
                      "body")
    else:
        restore = restore_span[2]
        branch = re.search(r'if\s*\(\s*auto\s*\*\s*\w+\s*=\s*xml\s*->\s*'
                           r'getChildByName\s*\(\s*"abSlots"\s*\)\s*\)', restore)
        branch_span = None
        if branch is None:
            errors.append('setStateInformation lost its "abSlots" restore '
                          "branch")
        else:
            branch_span = braced_span(restore, restore.find("{", branch.end()))
        reset = ZERO_RESET.search(restore)
        if reset is None:
            errors.append("setStateInformation lost its stale-slot reset - a "
                          "partial state could inherit the previous session")
        fallback = FALLBACK.search(restore)
        if fallback is None:
            errors.append("setStateInformation lost the CV-067 fallback "
                          f"(`if (! abSnapshotsPersisted) {SEED_CALL}();`) - a "
                          "state saved before the slots existed would restore "
                          "an all-zero mix")
        else:
            seed_calls = re.findall(SEED_CALL + r"\s*\(\s*\)", restore)
            if len(seed_calls) != 1:
                errors.append(f"the restore must seed from the restored "
                              f"parameters exactly once (found "
                              f"{len(seed_calls)} calls)")
            if branch_span is not None and fallback.start() < branch_span[1]:
                errors.append("the fallback seed must run AFTER the optional "
                              "abSlots branch, or a saved pair never gets a "
                              "chance to restore")
            if reset is not None and fallback.start() < reset.end():
                errors.append("the fallback seed must run AFTER the stale-slot "
                              "reset")
            if reset is not None and fallback.start() > reset.end():
                between = restore[reset.end():fallback.start()]
                if re.search(r"\breturn\b", between):
                    errors.append("a return between the stale-slot reset and "
                                  "the fallback seed leaves the all-zero "
                                  "restore path alive")
    return errors


def fail_probe(label, detail):
    print(f"FAIL: probe '{label}' was not rejected - {detail}")
    sys.exit(1)


for path in (CPP, HDR, ED):
    if not path.exists():
        print(f"FAIL: missing source file {path}")
        sys.exit(1)

cpp_raw = read_source(CPP)
hdr_raw = read_source(HDR)
ed_raw = read_source(ED)

errors = verify(cpp_raw, hdr_raw, ed_raw)
if errors:
    print("FAIL: CV-067 A/B snapshot ownership invariants violated:")
    for error in errors:
        print(f"  - {error}")
    sys.exit(1)
print("OK: the processor constructor seeds both slots once from the settled "
      "live values, after the default preset load, and marks them persisted")
print("OK: the editor never reseeds (no saveSlot/snapshot write in its "
      "constructor) and still reflects the active slot")
print("OK: a state without a complete abSlots pair derives both slots from "
      "the restored parameters, so no restore path leaves an all-zero mix")

# ---------------------------------------------------------------------------
# negative self-probes on mutated in-memory texts (real tree never mutated)
# ---------------------------------------------------------------------------
EDITOR_REFLECT = ("    btnSlotA.setToggleState(audioProcessor.isSlotA(), "
                  "juce::dontSendNotification);")
CTOR_SEED = ("    seedABSnapshotsFromLiveParameters();\n"
             "    abSnapshotsPersisted = true;\n")
FALLBACK_TEXT = ("        if (! abSnapshotsPersisted)\n"
                 "            seedABSnapshotsFromLiveParameters();")


def mutate_editor_reseed(text):
    """P1: re-introduce the editor reseed the fix removed."""
    if text.count(EDITOR_REFLECT) != 1:
        return None
    return text.replace(
        EDITOR_REFLECT,
        "    audioProcessor.saveSlotA();\n"
        "    audioProcessor.saveSlotB();\n" + EDITOR_REFLECT, 1)


def mutate_editor_snapshot_write(text):
    """P2: the editor writing a snapshot array directly."""
    if text.count(EDITOR_REFLECT) != 1:
        return None
    return text.replace(
        EDITOR_REFLECT,
        "    audioProcessor.snapshotA[0] = 0.0f;\n" + EDITOR_REFLECT, 1)


def mute_ctor_seed(text):
    """P3: drop the constructor seed + persisted mark."""
    if text.count(CTOR_SEED) != 1:
        return None
    return text.replace(CTOR_SEED, "", 1)


def move_ctor_seed_early(text):
    """P4: seed BEFORE the default preset load (captures pre-load defaults)."""
    if text.count(CTOR_SEED) != 1 or "    startTimerHz(30);\n" not in text:
        return None
    moved = text.replace(CTOR_SEED, "", 1)
    return moved.replace("    startTimerHz(30);\n",
                         "    startTimerHz(30);\n" + CTOR_SEED, 1)


def mute_fallback(text):
    """P5: drop the restore fallback seed."""
    if text.count(FALLBACK_TEXT) != 1:
        return None
    return text.replace(FALLBACK_TEXT, "", 1)


def ungate_fallback(text):
    """P6: seed unconditionally, stomping a restored pair with live values."""
    if text.count(FALLBACK_TEXT) != 1:
        return None
    return text.replace(
        FALLBACK_TEXT, "        seedABSnapshotsFromLiveParameters();", 1)


def early_return_before_fallback(text):
    """P7: a return after the zero reset skips the seed (zero-slot path)."""
    if text.count(FALLBACK_TEXT) != 1:
        return None
    return text.replace(
        FALLBACK_TEXT, "        return;\n" + FALLBACK_TEXT, 1)


PROBES = [
    ("editor reseed re-introduced", "ed", mutate_editor_reseed),
    ("editor writes a snapshot array", "ed", mutate_editor_snapshot_write),
    ("constructor seed removed", "cpp", mute_ctor_seed),
    ("constructor seed moved before the default preset load", "cpp",
     move_ctor_seed_early),
    ("restore fallback seed removed", "cpp", mute_fallback),
    ("restore fallback seed made unconditional", "cpp", ungate_fallback),
    ("return between the stale reset and the fallback seed", "cpp",
     early_return_before_fallback),
]

for label, target, mutate in PROBES:
    if target == "ed":
        mutated = mutate(ed_raw)
        candidate = (cpp_raw, hdr_raw, mutated)
    else:
        mutated = mutate(cpp_raw)
        candidate = (mutated, hdr_raw, ed_raw)
    if mutated is None or mutated == (ed_raw if target == "ed" else cpp_raw):
        print(f"FAIL: stale self-probe '{label}': mutation did not apply")
        sys.exit(1)
    if not verify(*candidate):
        fail_probe(label, "the mutated source passed every assertion")
    print(f"probe ok: {label} -> rejected")

# no-op guard: an edit outside the pinned shapes must still be accepted
neutral_ed = ed_raw.replace('btnSaveAB.setButtonText("SAVE");',
                            'btnSaveAB.setButtonText( "SAVE" );')
neutral_cpp = cpp_raw.replace('xml->setAttribute("schemaVersion", 1);',
                              'xml->setAttribute( "schemaVersion", 1 );')
if neutral_ed == ed_raw or neutral_cpp == cpp_raw:
    print("FAIL: no-op guard: unanchored neutral edit did not apply")
    sys.exit(1)
if verify(neutral_cpp, hdr_raw, neutral_ed):
    print("FAIL: benign edit outside the pinned shapes was rejected - the "
          "checker over-fires")
    for error in verify(neutral_cpp, hdr_raw, neutral_ed):
        print(f"  - {error}")
    sys.exit(1)
print("probe ok: benign edit outside the pinned shapes accepted")

# real tree never mutated - re-verify the live source once more
errors = verify()
if errors:
    print("FAIL: final re-verification of the live tree failed:")
    for error in errors:
        print(f"  - {error}")
    sys.exit(1)
print("CV067 AB SNAPSHOTS OK")
