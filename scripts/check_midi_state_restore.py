#!/usr/bin/env python3
"""Headless checker: MIDI-map state-restore invariants.

Asserts (in PluginProcessor.cpp / setStateInformation):
  (a) midiMap.clear() under midiMapLock runs UNCONDITIONALLY — i.e. the
      clear call site appears BEFORE the getChildByName("midiMaps") guard,
      not inside the child-present branch. A saved state from an older
      build (no midiMaps child) must not keep the previous session's maps.
  (b) repopulation still reads "cc" / "param" attributes from <map> entries.
Exit 0 = ok, 1 = violation with line-cited diagnostics.
"""
import re
import sys
from pathlib import Path
from typing import NoReturn

ROOT = Path(__file__).resolve().parent.parent
SRC = ROOT / "source" / "DrippyFX"

def fail(msg) -> NoReturn:
    print(f"MIDI-STATE-RESTORE FAIL: {msg}")
    sys.exit(1)

path = SRC / "PluginProcessor.cpp"
if not path.exists():
    fail(f"missing source file {path}")
text = path.read_text(encoding="utf-8")

# locate setStateInformation body
m = re.search(r"void\s+CorvusFXAudioProcessor::setStateInformation\s*\(", text)
if not m:
    fail("setStateInformation definition missing from PluginProcessor.cpp")
body_start = text.find("{", m.end())
depth = 0; i = body_start; j = body_start
while j < len(text):
    if text[j] == "{": depth += 1
    elif text[j] == "}":
        depth -= 1
        if depth == 0: break
    j += 1
body = text[body_start:j + 1]

clear = body.find("midiMap.clear()")
guard = body.find('getChildByName("midiMaps")')
if clear == -1:
    fail("setStateInformation no longer calls midiMap.clear() — stale CC mappings can never be dropped")
if guard == -1:
    fail("setStateInformation no longer looks up the midiMaps child — saved mappings are not restored")
if not (0 <= clear < guard):
    fail(f"midiMap.clear() (offset {clear}) sits at/inside the getChildByName guard (offset {guard}) — "
         "a state WITHOUT a midiMaps child keeps the previous session's maps armed")
print("midi-state-restore: midiMap.clear() runs unconditionally before the midiMaps-child guard")

# the clear must be lock-guarded
pre_clear = body[:clear]
lock_region = pre_clear[max(0, clear - 400):clear]
if "midiMapLock" not in lock_region:
    fail("midiMap.clear() before the guard is not under midiMapLock — thread-unsafe restore")
print("midi-state-restore: the unconditional clear is under midiMapLock")

# repopulation still reads cc/param
if 'getIntAttribute("cc")' not in body or 'getStringAttribute("param")' not in body:
    fail("restore loop no longer reads cc/param attributes from <map> entries")
print("midi-state-restore: repopulation still reads cc/param from saved <map> entries")

# (c) the restore loop must filter param IDs that no longer exist in the APVTS
#     — zombie mappings fire setValueNotifyingHost on nothing every CC message.
restore_loop_m = re.search(r"for\s*\(\s*auto\*\s*mapXml\s*:\s*mapsXml->getChildWithTagNameIterator\(\"map\"\)\)", body)
if not restore_loop_m:
    fail("setStateInformation restore loop (getChildWithTagNameIterator(\"map\")) missing")
loop_start = restore_loop_m.end()
# find loop end by brace matching from the next '{'
lb = body.find("{", loop_start)
d = 0; k = lb
while k < len(body):
    if body[k] == "{": d += 1
    elif body[k] == "}":
        d -= 1
        if d == 0: break
    k += 1
loop = body[lb:k + 1]
# strip comments so commented-out code can't fake a pass
code = re.sub(r"//[^\n]*", "", loop)
if "apvts.getParameter" not in code or ("!= nullptr" not in code and "nullptr" not in code):
    fail("restore loop does not filter param IDs against apvts.getParameter(...) != nullptr — "
         "a renamed/removed parameter ID would restore a dead CC mapping")
print("midi-state-restore: restore loop drops param IDs that no longer exist in the APVTS")

# --- Part (d): SAVE side — getStateInformation must hold midiMapLock over the
#     whole save loop, not just around attribute writes. Strip the lock (e.g. a
#     "simplify save" refactor) and the XmlElement writes can interleave with a
#     mid-copy audio-thread capture insert.
m2 = re.search(r"void\s+CorvusFXAudioProcessor::getStateInformation\s*\(", text)
if not m2:
    fail("getStateInformation definition missing from PluginProcessor.cpp")
g_start = text.find("{", m2.end())
depth = 0; i = g_start; j = g_start
while j < len(text):
    if text[j] == "{": depth += 1
    elif text[j] == "}":
        depth -= 1
        if depth == 0: break
    j += 1
save_body = re.sub(r"//[^\n]*", "", text[g_start:j + 1])

child_at = save_body.find('createNewChildElement("midiMaps")')
if child_at == -1:
    fail("getStateInformation no longer creates the midiMaps child — mappings are not saved")
lock_at = save_body.find("ScopedLock", child_at)
range_at = save_body.find("for (const auto& [cc, paramID] : midiMap)", child_at)
if range_at == -1:
    fail("getStateInformation save loop (for (const auto& [cc, paramID] : midiMap)) missing")
if lock_at == -1 or lock_at > range_at:
    fail(f"getStateInformation acquires the midiMapLock (offset {lock_at}) at/after the "
         f"save loop start (offset {range_at}) — the map iteration is unsynchronized against "
         "audio-thread capture inserts during save")
# the setAttribute writes must also come after the lock acquisition
first_attr = save_body.find('setAttribute("cc"', range_at)
if first_attr != -1 and lock_at > first_attr:
    fail("getStateInformation writes map attributes before acquiring midiMapLock")
print("midi-state-restore: save-side midiMap iteration/attribute writes are under midiMapLock")

# --- self-probe (negative): stripping the ScopedLock from the save body must
#     be rejected; a no-op mutation must still pass.
_probe = save_body.replace("const juce::ScopedLock lock(midiMapLock);", "/*probe*/")
_noop = save_body.replace("Save MIDI Learn mappings", "Save MIDI Learn mappingsX_probe")
def _ok(t):
    try:
        c2 = t.find('createNewChildElement("midiMaps")')
        l2 = t.find("ScopedLock", c2)
        r2 = t.find("for (const auto& [cc, paramID] : midiMap)", c2)
        return not (l2 == -1 or l2 > r2)
    except Exception:
        return False
if not _ok(_noop):
    fail("internal: no-op mutation changed the save-body probe outcome (checker self-guard)")
if _ok(_probe):
    fail("internal: probe tolerance too loose — a ScopedLock-stripped save body still passes")
print("midi-state-restore: save-side lock probe self-checks pass")
