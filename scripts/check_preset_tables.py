#!/usr/bin/env python3
"""Headless invariant check for DrippyFX preset id tables.

Parses the four structures in source/DrippyFX/PluginProcessor.cpp that must stay
in sync whenever preset count changes (AGENTS.md working rule 6):
  - getNumPrograms()         (must == 36 == idToPreset/presetToId cardinality)
  - idToPreset[43]           (combo item ID -> preset index, -1 = separator)
  - presetFromId[43]         (reverse of idToPreset)
  - presetToId[36]           (preset index -> combo item ID)

Exits 0 on green, 1 with a diagnostic list on any violation.
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


text = SRC.read_text(encoding="utf-8", errors="replace")


def strip_comments(s: str) -> str:
    s = re.sub(r"//.*", "", s)
    s = re.sub(r"/\*.*?\*/", "", s, flags=re.S)
    return s


def grab_array(name: str):
    # find `static const int NAME[N] = { ... };` spanning lines
    m = re.search(rf"static\s+const\s+int\s+{name}\s*\[\s*(\d+)\s*\]\s*=\s*\{{(.*?)\}}\s*;", text, flags=re.S)
    if not m:
        return None, None
    size = int(m.group(1))
    body = strip_comments(m.group(2))
    vals = [int(v) for v in re.findall(r"-?\d+", body)]
    return size, vals


def grab_int_expr(pattern: str, name: str):
    m = re.search(pattern, text)
    if not m:
        err(f"could not find {name}")
        return None
    return int(m.group(1))


# --- getNumPrograms() ---
n = grab_int_expr(r"getNumPrograms\s*\(\s*\)\s*\{\s*return\s+(\d+);", "getNumPrograms()")
if n is not None and n != EXPECTED_PROGRAMS:
    err(f"getNumPrograms() = {n}, expected {EXPECTED_PROGRAMS}")

# --- idToPreset ---
size_id2p, id2p = grab_array("idToPreset")
if id2p is None:
    err("could not find idToPreset[] table")
else:
    if size_id2p != len(id2p):
        err(f"idToPreset declared size {size_id2p} but {len(id2p)} values present")
    if len(id2p) != 43:
        err(f"idToPreset has {len(id2p)} entries, expected 43")
    # separator positions: 0,1,8,15,22,29,36 must be -1
    expected_seps = {0, 1, 8, 15, 22, 29, 36}
    seps = {i for i, v in enumerate(id2p) if v == -1}
    if seps != expected_seps:
        err(f"idToPreset separators {sorted(seps)} != expected {sorted(expected_seps)}")
    valid = [v for v in id2p if v >= 0]
    if sorted(valid) != list(range(EXPECTED_PROGRAMS)):
        err(f"idToPreset preset indices {sorted(valid)} != 0..{EXPECTED_PROGRAMS - 1}")

# --- presetFromId ---
size_pfi, pfi = grab_array("presetFromId")
if pfi is None:
    err("could not find presetFromId[] table")
else:
    if len(pfi) != 43:
        err(f"presetFromId has {len(pfi)} entries, expected 43")
    # -1 exactly at separator ids
    seps = {i for i, v in enumerate(pfi) if v == -1}
    if seps != EXPECTED_SEPARATORS:
        err(f"presetFromId separators {sorted(seps)} != expected {sorted(EXPECTED_SEPARATORS)}")
    vals = [v for v in pfi if v >= 0]
    if sorted(vals) != list(range(EXPECTED_PROGRAMS)):
        err(f"presetFromId indices {sorted(vals)} != 0..{EXPECTED_PROGRAMS - 1}")

# --- presetToId ---
size_pti, pti = grab_array("presetToId")
if pti is None:
    err("could not find presetToId[] table")
else:
    if len(pti) != EXPECTED_PROGRAMS:
        err(f"presetToId has {len(pti)} entries, expected {EXPECTED_PROGRAMS}")
    if len(set(pti)) != len(pti):
        err("presetToId contains duplicate ids")
    if min(pti) < 0 or max(pti) >= 43:
        err("presetToId ids out of [0,43) range")

# --- cross invariants: idToPreset == inverse(presetToId), presetFromId == inverse(idToPreset), presetToId == inverse(presetFromId) ---
if id2p and pti and len(id2p) == 43 and len(pti) == EXPECTED_PROGRAMS:
    for idx, cid in enumerate(pti):
        if not (0 <= cid < 43) or id2p[cid] != idx:
            err(f"round-trip presetToId[{idx}]={cid} but idToPreset[{cid}]="
                f"{id2p[cid] if 0 <= cid < len(id2p) else 'oob'}")
if id2p and pfi and len(id2p) == len(pfi) == 43:
    for cid, idx in enumerate(id2p):
        if pfi[cid] != idx:
            err(f"presetFromId[{cid}]={pfi[cid]} != idToPreset[{cid}]={idx}")

# --- getProgramName count ---
names = re.findall(r'static const juce::String n\[36\]\s*=\s*\{(.*?)\};', text, flags=re.S)
if names:
    count = len(re.findall(r'"[^"]*"', names[0]))
    if count != EXPECTED_PROGRAMS:
        err(f"getProgramName has {count} names, expected {EXPECTED_PROGRAMS}")
else:
    err("could not find getProgramName name table")

if errors:
    print("FAIL: preset id table invariants violated:")
    for e in errors:
        print(f"  - {e}")
    sys.exit(1)

print(f"OK: preset id tables consistent ({EXPECTED_PROGRAMS} programs, 43 combo ids, separators at {sorted(expected_seps)})")
sys.exit(0)
