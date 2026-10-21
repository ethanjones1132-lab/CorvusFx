#!/usr/bin/env python3
"""Headless checker: MIDI-Learn lifecycle invariants.

Asserts (in the style of check_undo_wiring.py):
  (a) startMidiLearn / stopMidiLearn exist on the processor
  (b) the editor destructor calls stopMidiLearn() — no armed learn
      survives editor teardown
  (c) the editor's right-click menu still offers MIDI Learn (feature intact)
  (d) the capture branch records only the mapping — it does NOT jump the
      target parameter via setValueNotifyingHost
Exit 0 = ok, 1 = violation with line-cited diagnostics.
"""
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SRC = ROOT / "source" / "DrippyFX"

def fail(msg):
    print(f"MIDI-LEARN-LIFECYCLE FAIL: {msg}")
    sys.exit(1)

def read(rel):
    p = SRC / rel
    if not p.exists():
        fail(f"missing source file {p}")
    return p.read_text(encoding="utf-8"), p

proc_h, proc_h_path = read("PluginProcessor.h")
proc_c, proc_c_path = read("PluginProcessor.cpp")
edit_c, edit_c_path = read("PluginEditor.cpp")

# (a) processor API surface exists
if not re.search(r"void\s+startMidiLearn\s*\(", proc_h):
    fail("startMidiLearn missing from PluginProcessor.h")
if not re.search(r"void\s+stopMidiLearn\s*\(", proc_h):
    fail("stopMidiLearn missing from PluginProcessor.h")
if not re.search(r"midiLearnActive\s*=\s*false", proc_h):
    fail("stopMidiLearn no longer clears midiLearnActive")
print("midi-learn: processor exposes startMidiLearn/stopMidiLearn")

# (b) editor destructor stops the learn
m = re.search(r"~CorvusFXAudioProcessorEditor\s*\(\s*\)\s*\{?", edit_c)
if not m:
    fail("PluginEditor.cpp: editor destructor missing")
brace = edit_c.find("{", m.start())
if brace == -1:
    fail("PluginEditor.cpp: editor destructor body not found")
dtor = edit_c[brace:brace + 400]
if "audioProcessor.stopMidiLearn()" not in dtor.split("}")[0]:
    fail("editor destructor no longer calls audioProcessor.stopMidiLearn() — an armed learn survives teardown")
print("midi-learn: editor destructor calls audioProcessor.stopMidiLearn()")

# (c) the feature itself is still offered
if "startMidiLearn" not in edit_c or "MIDI Learn" not in edit_c:
    fail("PluginEditor.cpp no longer offers/wires the MIDI Learn menu entry")
print("midi-learn: right-click MIDI Learn menu entry still wired")

# (d) capture branch must not jump the parameter
cap = re.search(r"if\s*\(midiLearnActive\)\s*\{", proc_c)
if not cap:
    fail("PluginProcessor.cpp: midiLearnActive capture branch missing")
body_start = proc_c.find("{", cap.start())
if body_start == -1:
    fail("PluginProcessor.cpp: capture branch body not found")
depth = 0; i = body_start; j = body_start
while j < len(proc_c):
    if proc_c[j] == "{": depth += 1
    elif proc_c[j] == "}":
        depth -= 1
        if depth == 0: break
    j += 1
cap_body = proc_c[body_start:j + 1]
if "midiMap" not in cap_body:
    fail("capture branch no longer records midiMap[cc] = midiLearnParamID")
if "setValueNotifyingHost" in cap_body:
    fail("capture branch jumps the target parameter via setValueNotifyingHost — a stray CC during learn rewrites the knob")
print("midi-learn: capture records the mapping without jumping the parameter")

print("MIDI-LEARN-LIFECYCLE OK")
