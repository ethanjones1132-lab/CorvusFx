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

ROOT = Path(__file__).resolve().parent.parent
SRC = ROOT / "source" / "DrippyFX"

def fail(msg):
    print(f"MIDI-STATE-RESTORE FAIL: {msg}")
    sys.exit(1)

path = SRC / "PluginProcessor.cpp"
if not path.exists():
    fail(f"missing source file {path}")
text = path.read_text()

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
