#!/usr/bin/env python3
"""Headless checker: A/B slot restore leaves the preset choice DOCUMENTED-STALE.

loadSlotA/loadSlotB (PluginProcessor.cpp) restore the 24 abParamIds[]
snapshot values via setValueNotifyingHost but never touch the "preset"
id, so the preset ComboBox keeps reporting the last-touched preset while
the knobs hold the other slot's recipe. That staleness is an
INTENTIONAL choice, not an oversight: writing the "preset" id from
loadSlot* would fire parameterChanged -> loadPreset, whose set() writes
stomp every non-preset parameter back to the factory recipe,
destructively overwriting the just-restored snapshot. A future edit that
"fixes" the stale combo by adding a preset write (without a
listener-quiet mechanism) or a refactor that deletes the documented
explanation must not ship silently.

Asserts (marker asserted on RAW text because it is itself a comment; all
structural asserts comment-stripped):
  (a) each loadSlotA/loadSlotB body carries the INTENTIONALLY STALE
      documentation marker;
  (b) neither body dereferences or writes the "preset" parameter id
      (no <raw> preset write / apvts.getParameter("preset") /
      getRawParameterValue("preset") / setValueNotifyingHost overload
      targeting preset) — the stale combo cannot regress toward a
      self-stomping write;
  (c) each body still restores exactly the 24-id snapshot write loop
      (setValueNotifyingHost(snapshotA[i]) / snapshotB[i]) — the
      documented-stale marker must not become a license to thin the
      restore itself.

Negative self-probes on mutated in-memory copies (real tree never
mutated, no-op mutation aborts as a stale alarm): marker deleted; preset
write injected; restore loop thinned to a no-op. Neutral no-op edit
outside the pinned shapes must still pass (specificity).
Exit 0 = ok, 1 = violation.
"""
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SRC = ROOT / "source" / "DrippyFX"
CPP = SRC / "PluginProcessor.cpp"

MARKER_A = "A/B preset choice INTENTIONALLY STALE: loadSlotA"
MARKER_B = "A/B preset choice INTENTIONALLY STALE: loadSlotB"
RESTORE_SANDBOXED = 'p->setValueNotifyingHost(snapshot'
FNS = ("loadSlotA", "loadSlotB")


def fail(msg):
    print(f"AB-SLOT-PRESET-PARITY FAIL: {msg}")
    sys.exit(1)


def strip_comments(src):
    src = re.sub(r"//[^\n]*", "", src)
    src = re.sub(r"/\*.*?\*/", "", src, flags=re.S)
    return src


def extract_body(text, fn_name):
    """Brace-matched body of `void CorvusFXAudioProcessor::loadSlotX()`."""
    m = re.search(r"::" + fn_name + r"\s*\(\s*\)", text)
    if not m:
        return None
    i = text.find("{", m.end())
    if i < 0:
        return None
    depth = 0
    for j in range(i, len(text)):
        if text[j] == "{":
            depth += 1
        elif text[j] == "}":
            depth -= 1
            if depth == 0:
                return text[i:j + 1]
    return None


cpp_raw = CPP.read_text(encoding="utf-8")
stripped = strip_comments(cpp_raw)

bodies = {}
for fn in FNS:
    body = extract_body(stripped, fn)
    if body is None:
        fail(f"loadSlot{fn[-1]} body not found in PluginProcessor.cpp "
             "(comment-stripped) — extraction regex drifted?")
    assert body is not None
    bodies[fn] = body

# (a) documented-stale marker in EACH loadSlot body (RAW text — the
# marker is a comment, so comment-stripping must be reserved for the
# structural asserts).
for fn, marker in ((FNS[0], MARKER_A), (FNS[1], MARKER_B)):
    body_raw = extract_body(cpp_raw, fn)
    if body_raw is None:
        fail(f"loadSlot{fn[-1]} body not found in raw text")
    if marker not in body_raw:
        fail(f"loadSlot{fn[-1]} lost its documented-stale marker — a "
             "refactor may have dropped the explanation of why the preset "
             "ComboBox stays on the last-touched preset")
print("ab-slot-preset-parity: documented-stale markers present in both loadSlot bodies")

# (b) NO preset-parameter write/deref in either body.
for fn in FNS:
    body = bodies[fn]
    bad_forms = [
        r'getRawParameterValue\s*\(\s*"preset"',
        r'getParameter\s*\(\s*"preset"',
        r'getParameterID\s*\(\s*\)\s*==\s*"preset"',
        r'setValueNotifyingHost\s*\([^)]*"preset"',
    ]
    for form in bad_forms:
        if re.search(form, body):
            fail(f"loadSlot{fn[-1]} references the 'preset' parameter id "
                 f"({form}) — a preset write here fires parameterChanged -> "
                 "loadPreset, whose set() writes stomp every non-preset "
                 "parameter back to the factory recipe and destroy the "
                 "snapshot the user just restored (see the documented-stale "
                 "marker)")
print("ab-slot-preset-parity: no preset-parameter write/deref in either loadSlot body")

# (c) each body still carries its snapshot restore write.
for fn in FNS:
    body = bodies[fn]
    slot = "snapshotA" if fn == "loadSlotA" else "snapshotB"
    write = f"p->setValueNotifyingHost({slot}[i])"
    if write not in body:
        fail(f"loadSlot{fn[-1]} no longer restores via {write} — the "
             "documented-stale marker must not accompany a thinned restore")
    if f'getParameter(abParamIds[i])' not in body:
        fail(f"loadSlot{fn[-1]} no longer iterates the abParamIds[] roster")
print("ab-slot-preset-parity: snapshot restore loops intact (abParamIds roster-driven)")

# (d) guard: the restore loop must remain guarded by if (p) — sibling
# checker check_ab_null_param_guard.py owns this pin; assert locally so a
# refactor cannot strand an unguarded write next to a documented marker.
for fn in FNS:
    body = bodies[fn]
    if not re.search(r"if\s*\(\s*p\s*\)\s*p->setValueNotifyingHost", body):
        fail(f"loadSlot{fn[-1]} restore write lost its if(p) null guard")
print("ab-slot-preset-parity: if(p) null-guarded restore writes intact")


# (e) negative self-probes on mutated copies (sibling style)
def _reject(reason):
    raise _Rejected(reason)


class _Rejected(Exception):
    pass


def _verify(text):
    """Re-run the core assertions on a mutated candidate."""
    stripped = strip_comments(text)
    for fn in FNS:
        marker = MARKER_A if fn == "loadSlotA" else MARKER_B
        body = extract_body(stripped, fn)
        body_raw = extract_body(text, fn)
        assert body is not None and body_raw is not None, f"{fn} body not found"
        if marker not in body_raw:
            _reject(f"{fn} documented-stale marker missing")
        slot = "snapshotA" if fn == "loadSlotA" else "snapshotB"
        if f"p->setValueNotifyingHost({slot}[i])" not in body:
            _reject(f"{fn} restore write missing")
        if not re.search(r"if\s*\(\s*p\s*\)\s*p->setValueNotifyingHost", body):
            _reject(f"{fn} restore lost its if(p) null guard")
        if re.search(r'getParameter\s*\(\s*"preset"', body):
            _reject(f"{fn} premature preset coupling accepted")
    return True


def run_probe(label, mutate):
    mutated = mutate(cpp_raw)
    if mutated == cpp_raw:
        fail(f"no-op probe ({label}): mutation did not change the source — "
             "the negative check is vacuous")
    try:
        _verify(mutated)
    except _Rejected:
        print(f"ab-slot-preset-parity: negative probe '{label}' rejected")
    else:
        fail(f"negative probe '{label}' was NOT rejected — checker is vacuous")


run_probe(
    "marker deleted (stale combo regresses undocumented)",
    lambda s: s.replace(
        MARKER_A, "A/B preset choice NOTE: loadSlotA", 1))

run_probe(
    "preset write injected into loadSlotA",
    lambda s: s.replace(
        "        if (p) p->setValueNotifyingHost(snapshotA[i]);",
        '        if (p) p->setValueNotifyingHost(snapshotA[i]);\n'
        '        if (auto* q = apvts.getParameter("preset")) '
        'q->setValueNotifyingHost(q->convertTo0to1(2.0f));',
        1))

run_probe(
    "restore loop thinned to a no-op in loadSlotB",
    lambda s: s.replace(
        "        if (p) p->setValueNotifyingHost(snapshotB[i]);",
        "        (void) p;",
        1))

# no-op guard: an edit outside the pinned shapes must still pass
neutral = cpp_raw.replace(
    "void CorvusFXAudioProcessor::clearAllMidiMappings()",
    "void CorvusFXAudioProcessor::clearAllMidiMappings_renamed_for_probe()")
if neutral == cpp_raw:
    fail("no-op guard: unanchored neutral edit did not change the source")
try:
    _verify(neutral)
except _Rejected as r:
    fail(f"neutral edit outside the pinned shapes was REJECTED "
         f"({r}) — checker over-fires")
print("ab-slot-preset-parity: neutral edit outside the pinned shapes passes "
      "(probe specificity proven)")
print("ab-slot-preset-parity: OK")
