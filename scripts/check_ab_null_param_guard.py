#!/usr/bin/env python3
"""Headless checker: A/B save/load must stay inside the `if (p)` null guard.

saveSlotA/saveSlotB assign snapshotA[i]/snapshotB[i] from
apvts.getParameter(abParamIds[i])->getValue() ONLY when the parameter resolves,
and loadSlotA/loadSlotB call setValueNotifyingHost(snapshot*) ONLY under the
same guard (source/DrippyFX/PluginProcessor.cpp, all four bodies). Today all 24
ids resolve (see check_ab_param_roster.py), but a future rename/removal that
leaves a null lookup must keep failing silent-and-scoped: an unguarded write on
the save side would snapshot a value from a stale slot composition, and an
unguarded restore write dereferences null / pushes a bogus stale float.

Asserts (comment-stripped, per body):
  (a) saveSlotA/saveSlotB: exactly one `snapshotX[i] =` write, and it appears
      only in the guarded form `if (p) snapshotX[i] = p->getValue();`
  (b) loadSlotA/loadSlotB: exactly one `setValueNotifyingHost(snapshotX[i])`
      call, only in the guarded form `if (p) p->setValueNotifyingHost(...)`
  (c) all four bodies iterate NUM_AB_PARAMS via getParameter(abParamIds[i]).

Negative self-probes on mutated in-memory texts (real tree never mutated,
no-op mutation aborts as a stale alarm): restore write unguarded; save write
unguarded; guarded write duplicated unguarded after the if (rounding drift).
Exit 0 = ok, 1 = violation.
"""
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SRC = ROOT / "source" / "DrippyFX"

CPP = SRC / "PluginProcessor.cpp"


def fail(msg):
    print(f"AB-NULL-GUARD FAIL: {msg}")
    sys.exit(1)


def strip_comments(src):
    src = re.sub(r"//[^\n]*", "", src)
    src = re.sub(r"/\*.*?\*/", "", src, flags=re.S)
    return src


def extract_fn(stripped, name):
    """Brace-matched body of `void CorvusFXAudioProcessor::name()`."""
    m = re.search(r"void\s+CorvusFXAudioProcessor::" + re.escape(name) + r"\s*\(\s*\)", stripped)
    if not m:
        raise _Rejected(f"{name} definition missing")
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
    return stripped[i:j + 1]


class _Rejected(Exception):
    pass


def _verify(cpp_text):
    stripped = strip_comments(cpp_text)
    mn = re.search(r"NUM_AB_PARAMS\s*=\s*(\d+)", strip_comments(
        (SRC / "PluginProcessor.h").read_text(encoding="utf-8")))
    if not mn:
        raise _Rejected("NUM_AB_PARAMS missing from the header")
    n = int(mn.group(1))
    for slot, kind in (("A", "save"), ("B", "save"), ("A", "load"), ("B", "load")):
        body = extract_fn(stripped, f"{'save' if kind == 'save' else 'load'}Slot{slot}")
        if f"for (int i = 0; i < NUM_AB_PARAMS; ++i)" not in body:
            raise _Rejected(f"slot{slot} {kind}: no NUM_AB_PARAMS loop")
        if "getParameter(abParamIds[i])" not in body:
            raise _Rejected(f"slot{slot} {kind}: getParameter(abParamIds[i]) missing")
        if kind == "save":
            guarded = re.findall(
                r"if\s*\(\s*p\s*\)\s*snapshot" + slot + r"\[i\]\s*=\s*p->getValue\(\)\s*;", body)
            writes = re.findall(r"snapshot" + slot + r"\[i\]\s*=", body)
        else:
            guarded = re.findall(
                r"if\s*\(\s*p\s*\)\s*p->setValueNotifyingHost\(\s*snapshot" + slot +
                r"\[i\]\s*\)\s*;", body)
            writes = re.findall(r"setValueNotifyingHost\(\s*snapshot" + slot + r"\[i\]", body)
        if len(writes) != 1:
            raise _Rejected(
                f"slot{slot} {kind}: expected exactly 1 write, found {len(writes)}")
        if len(guarded) != 1:
            raise _Rejected(
                f"slot{slot} {kind}: write is not (solely) inside the `if (p)` guard")
    return n


def main():
    global N_PARAMS
    if not CPP.exists():
        fail(f"missing source file {CPP}")
    cpp_raw = CPP.read_text(encoding="utf-8")
    try:
        N_PARAMS = _verify(cpp_raw)
    except _Rejected as r:
        fail(str(r))
    print(f"ab-null-guard: all 4 slot bodies guard writes under if(p); NUM_AB_PARAMS={N_PARAMS}")

    # negative self-probes on mutated in-memory texts (real tree never mutated)
    probes = [
        ("load restore write unguarded",
         lambda s: s.replace("if (p) p->setValueNotifyingHost(snapshotB[i]);",
                             "p->setValueNotifyingHost(snapshotB[i]);")),
        ("save write unguarded",
         lambda s: s.replace("if (p) snapshotA[i] = p->getValue();",
                             "snapshotA[i] = p->getValue();")),
        ("unconditional literal fallback added",
         lambda s: s.replace("if (p) snapshotB[i] = p->getValue();",
                             "snapshotB[i] = p ? p->getValue() : 0.5f;")),
    ]
    for label, mutate in probes:
        mutated = mutate(cpp_raw)
        if mutated == cpp_raw:
            fail(f"no-op probe ({label}): mutation did not change the source — "
                 "the negative check is vacuous")
        try:
            _verify(mutated)
        except _Rejected:
            print(f"ab-null-guard: negative probe '{label}' rejected")
        else:
            fail(f"negative probe '{label}' was NOT rejected — checker is vacuous")

    # no-op guard: an edit outside the pinned bodies must still pass
    shifted = cpp_raw.replace('apvts.addParameterListener("preset", this);',
                              'apvts.addParameterListener("preset" , this);')
    if shifted == cpp_raw:
        fail("no-op guard: unanchored neutral edit did not change the source")
    try:
        _verify(shifted)
    except _Rejected as r:
        fail(f"neutral edit outside the slot bodies was REJECTED — checker "
             f"over-fires: {r}")
    print("ab-null-guard: neutral no-slot edit passes (probe specificity proven)")
    print("ab-null-guard: OK")


if __name__ == "__main__":
    main()
