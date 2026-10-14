#!/usr/bin/env python3
"""Headless runtime invariant check for the DrippyFX preset combo mapping.

check_preset_tables.py pins cardinality/mutuality of the four id tables in
the abstract. This checker pins the *runtime* junction between those tables
and the ComboBox item-ID space:
  (a) every presetToId[i] value lands inside the ComboBox item-ID range that
      loadPreset's parameterChanged() mapping assumes
      (2 <= id <= 42 — the guard `if (id >= 2 && id <= 42 && idToPreset[id] >= 0)`),
  (b) the presetToId[] table inside setCurrentProgram() (the ONLY copy in the
      .cpp — PluginProcessor.cpp:287) is exactly the inverse of idToPreset[]
      over the valid range, so host-driven preset changes land on the right row,
  (c) setCurrentProgram() actually dereferences presetToId in its
      setValueNotifyingHost conversion — the host path cannot fall back to
      something stale.

Exits 0 on green, 1 with index-cited diagnostics on any violation.
"""
import re
import sys
from pathlib import Path

SRC = Path(__file__).resolve().parent.parent / "source" / "DrippyFX" / "PluginProcessor.cpp"
EXPECTED_PROGRAMS = 36
ID_MIN = 2
ID_MAX = 42

errors: list[str] = []


def err(msg: str) -> None:
    errors.append(msg)


text = SRC.read_text(encoding="utf-8", errors="replace")


def strip_comments(s: str) -> str:
    s = re.sub(r"//.*", "", s)
    s = re.sub(r"/\*.*?\*/", "", s, flags=re.S)
    return s


def grab_array(name: str, text: str):
    m = re.search(rf"static\s+const\s+int\s+{name}\s*\[\s*(\d+)\s*\]\s*=\s*\{{(.*?)\}}\s*;", text, flags=re.S)
    if not m:
        return None, None
    size = int(m.group(1))
    body = strip_comments(m.group(2))
    return size, [int(v) for v in re.findall(r"-?\d+", body)]


# --- the ONLY presetToId copy in this .cpp (inside setCurrentProgram) ---
size_pti, pti = grab_array("presetToId", text.replace("presetFromId", "__unrelated__"))
if pti is None:
    err("could not find presetToId[] table")
else:
    if size_pti != EXPECTED_PROGRAMS:
        err(f"presetToId declared size {size_pti}, expected {EXPECTED_PROGRAMS}")
    if len(pti) != EXPECTED_PROGRAMS:
        err(f"presetToId has {len(pti)} values, expected {EXPECTED_PROGRAMS}")
    # (a) runtime range: parameterChanged() only loads ids in [2, 42]
    for i, v in enumerate(pti):
        if not (ID_MIN <= v <= ID_MAX):
            err(f"presetToId[{i}]={v} outside ComboBox item-ID range "
                f"[{ID_MIN},{ID_MAX}] — parameterChanged guard would drop it")

# (b) mutual runtime correspondence with idToPreset (separators never referenced)
size_id2p, id2p = grab_array("idToPreset", text)
if pti and id2p and len(pti) == EXPECTED_PROGRAMS and len(id2p) == 43:
    for i, cid in enumerate(pti):
        if not (0 <= cid < 43):
            continue
        if id2p[cid] != i:
            err(f"presetToId[{i}]={cid} but idToPreset[{cid}]={id2p[cid]} — "
                f"setCurrentProgram would point the combo at the wrong preset")

# (c) setCurrentProgram dereferences presetToId in the notify path
body_m = re.search(r"setCurrentProgram\s*\(\s*int\s+\w+\s*\)\s*\{(.*?)\n\}", text, flags=re.S)
if body_m:
    body = body_m.group(1)
    if "presetToId[i]" not in strip_comments(body) or "setValueNotifyingHost" not in body:
        err("setCurrentProgram body no longer maps i -> presetToId[i] via "
            "setValueNotifyingHost — host preset path broken")
else:
    err("could not isolate setCurrentProgram body")

if errors:
    print("FAIL: preset combo runtime invariants violated:")
    for e in errors:
        print(f"  - {e}")
    sys.exit(1)

print(f"OK: preset combo runtime invariants hold "
      f"({EXPECTED_PROGRAMS} ids within [{ID_MIN},{ID_MAX}], presetToId == "
      f"inverse(idToPreset), setCurrentProgram maps via presetToId)")
sys.exit(0)
