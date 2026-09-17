#!/usr/bin/env python3
"""Headless invariant check for DrippyFX preset id tables.

Parses the four structures in source/DrippyFX/PluginProcessor.cpp that must stay
in sync whenever preset count changes (AGENTS.md working rule 6):
  - getNumPrograms()         (must == 36 == idToPreset/presetToId cardinality)
  - idToPreset[43]           (combo item ID -> preset index, -1 = separator)
  - presetFromId[43]         (reverse of idToPreset; feeds getCurrentProgram)
  - presetToId[36]           (preset index -> combo item ID)

Exits 0 on green, 1 with a diagnostic list on any violation.

Negative self-probes run on mutated in-memory text (the real tree is never
mutated): transposing a presetFromId row (the 2026-07-20 DREAM bug class from
commit 130307c) and dropping the whole presetFromId table must each be
rejected; a benign no-op edit must be accepted. A no-op guard aborts the
probe when the mutation did not apply.
"""
import re
import sys
from pathlib import Path

SRC = Path(__file__).resolve().parent.parent / "source" / "DrippyFX" / "PluginProcessor.cpp"
EXPECTED_PROGRAMS = 36
EXPECTED_SEPARATORS = {0, 1, 8, 15, 22, 29, 36}

errors: list[str] = []


def err(msg: str) -> None:
    errors.append(msg)


def strip_comments(s: str) -> str:
    s = re.sub(r"//.*", "", s)
    s = re.sub(r"/\*.*?\*/", "", s, flags=re.S)
    return s


def grab_array(name: str, text: str):
    # find `static const int NAME[N] = { ... };` spanning lines
    m = re.search(rf"static\s+const\s+int\s+{name}\s*\[\s*(\d+)\s*\]\s*=\s*\{{(.*?)\}}\s*;", text, flags=re.S)
    if not m:
        return None, None
    size = int(m.group(1))
    body = strip_comments(m.group(2))
    vals = [int(v) for v in re.findall(r"-?\d+", body)]
    return size, vals


def check_text(text: str) -> bool:
    """Run full table invariant set against a PluginProcessor.cpp text."""
    del errors[:]
    expected_seps = {0, 1, 8, 15, 22, 29, 36}

    # --- getNumPrograms() ---
    n = grab_int_expr(r"getNumPrograms\s*\(\s*\)\s*\{\s*return\s+(\d+);", "getNumPrograms()", text)
    if n is not None and n != EXPECTED_PROGRAMS:
        err(f"getNumPrograms() = {n}, expected {EXPECTED_PROGRAMS}")

    # --- idToPreset ---
    size_id2p, id2p = grab_array("idToPreset", text)
    if id2p is None:
        err("could not find idToPreset[] table")
    else:
        if size_id2p != len(id2p):
            err(f"idToPreset declared size {size_id2p} but {len(id2p)} values present")
        if len(id2p) != 43:
            err(f"idToPreset has {len(id2p)} entries, expected 43")
        seps = {i for i, v in enumerate(id2p) if v == -1}
        if seps != expected_seps:
            err(f"idToPreset separators {sorted(seps)} != expected {sorted(expected_seps)}")
        valid = [v for v in id2p if v >= 0]
        if sorted(valid) != list(range(EXPECTED_PROGRAMS)):
            err(f"idToPreset preset indices {sorted(valid)} != 0..{EXPECTED_PROGRAMS - 1}")

    # --- presetFromId ---
    size_pfi, pfi = grab_array("presetFromId", text)
    if pfi is None:
        err("could not find presetFromId[] table")
    else:
        if len(pfi) != 43:
            err(f"presetFromId has {len(pfi)} entries, expected 43")
        seps = {i for i, v in enumerate(pfi) if v == -1}
        if seps != EXPECTED_SEPARATORS:
            err(f"presetFromId separators {sorted(seps)} != expected {sorted(EXPECTED_SEPARATORS)}")
        vals = [v for v in pfi if v >= 0]
        if sorted(vals) != list(range(EXPECTED_PROGRAMS)):
            err(f"presetFromId indices {sorted(vals)} != 0..{EXPECTED_PROGRAMS - 1}")

    # --- presetToId ---
    size_pti, pti = grab_array("presetToId", text)
    if pti is None:
        err("could not find presetToId[] table")
    else:
        if len(pti) != EXPECTED_PROGRAMS:
            err(f"presetToId has {len(pti)} entries, expected {EXPECTED_PROGRAMS}")
        if len(set(pti)) != len(pti):
            err("presetToId contains duplicate ids")
        if min(pti) < 0 or max(pti) >= 43:
            err("presetToId ids out of [0,43) range")

    # --- cross invariants: round trips in BOTH directions ---
    if id2p and pti and len(id2p) == 43 and len(pti) == EXPECTED_PROGRAMS:
        for idx, cid in enumerate(pti):
            if not (0 <= cid < 43) or id2p[cid] != idx:
                err(f"round-trip presetToId[{idx}]={cid} but idToPreset[{cid}]="
                    f"{id2p[cid] if 0 <= cid < len(id2p) else 'oob'}")
    if id2p and pfi and len(id2p) == len(pfi) == 43:
        for cid, (a, b) in enumerate(zip(id2p, pfi)):
            if a >= 0 and pfi[cid] != a:
                err(f"presetFromId[{cid}]={b} != idToPreset[{cid}]={a}")

    # --- getProgramName count ---
    names = re.findall(r'static const juce::String n\[36\]\s*=\s*\{(.*?)\};', text, flags=re.S)
    if names:
        count = len(re.findall(r'"[^"]*"', names[0]))
        if count != EXPECTED_PROGRAMS:
            err(f"getProgramName has {count} names, expected {EXPECTED_PROGRAMS}")
    else:
        err("could not find getProgramName name table")

    return not errors


def grab_int_expr(pattern: str, name: str, text: str):
    m = re.search(pattern, text)
    if not m:
        err(f"could not find {name}")
        return None
    return int(m.group(1))


real_text = SRC.read_text(encoding="utf-8", errors="replace")

if check_text(real_text):
    print(f"OK: preset id tables consistent ({EXPECTED_PROGRAMS} programs, 43 combo ids, "
          f"separators at {sorted(EXPECTED_SEPARATORS)}, presetFromId == inverse(idToPreset))")
else:
    print("FAIL: preset id table invariants violated:")
    for e in errors:
        print(f"  - {e}")
    sys.exit(1)

# --- negative self-probes on mutated in-memory text (real tree never mutated) ---

# 1. transpose two consecutive DREAM rows inside presetFromId ONLY
#    (the getCurrentProgram copy at PluginProcessor.cpp:270-277 — the
#    2026-07-20 DREAM bug class from commit 130307c). idToPreset is untouched,
#    so cardinality/separator checks alone would still pass.
dream_row_pfi = "        -1,30,31,32,33,34,35         // IDs 36-42"
assert real_text.count(dream_row_pfi) == 1, "probe baseline: presetFromId DREAM row not unique"
m1 = real_text.replace(dream_row_pfi, dream_row_pfi.replace("31,32", "32,31"))
assert m1 != real_text, "no-op guard: presetFromId transposition did not apply"
if check_text(m1):
    print("PRESET-TABLES FAIL: SELF-PROBE — presetFromId row transposition "
          "(getCurrentProgram DREAM-row bug class 130307c) was NOT rejected")
    sys.exit(1)
print("probe ok: presetFromId DREAM-row transposition -> rejected")

# 2. drop the whole presetFromId table (its checker must not silently skip)
m2 = re.sub(r"static\s+const\s+int\s+presetFromId\s*\[43\]\s*=\s*\{.*?\}\s*;", "", real_text, flags=re.S)
assert m2 != real_text, "no-op guard: presetFromId removal did not apply"
if check_text(m2):
    print("FAIL: SELF-PROBE (checker should reject): presetFromId table removed")
    sys.exit(1)
print("probe ok: presetFromId table removed -> rejected")

# 3. benign no-op outside the tables must be accepted
m3 = real_text.replace("bool CorvusFXAudioProcessor::acceptsMidi() const { return true; }",
                       "bool CorvusFXAudioProcessor::acceptsMidi() const { return true; } // ok")
assert m3 != real_text, "no-op guard: benign mutation did not apply"
if not check_text(m3):
    print("FAIL: no-op guard: benign edit was wrongly rejected")
    sys.exit(1)
print("probe ok: benign no-op edit -> accepted")

print("PRESET-TABLES SELF-PROBES OK (2 negatives fired, no-op guarded)")
sys.exit(0)
