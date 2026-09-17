#!/usr/bin/env python3
"""Headless checker: MIDI-learn arm-path locking invariants.

Asserts (in PluginProcessor.h):
  (a) startMidiLearn's body acquires midiMapLock (the armed CC-capture
      state midiLearnParamID / midiLearnActive is written on the message
      thread while the audio thread reads both fields under the same lock
      in the CC loop — the String assignment must be protected too).
  (b) stopMidiLearn still clears midiLearnActive (single atomic flag,
      intentionally lock-free).
Exit 0 = ok, 1 = violation with line-cited diagnostics.
"""
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SRC = ROOT / "source" / "DrippyFX"

def fail(msg):
    print(f"MIDI-LEARN-LOCK FAIL: {msg}")
    sys.exit(1)

path = SRC / "PluginProcessor.h"
if not path.exists():
    fail(f"missing source file {path}")
text = path.read_text()

def strip_comments(src):
    src = re.sub(r"//[^\n]*", "", src)
    src = re.sub(r"/\*.*?\*/", "", src, flags=re.S)
    return src

def extract_fn(name):
    m = re.search(rf"void\s+{name}\s*\(", text)
    if not m:
        fail(f"{name} definition missing from PluginProcessor.h")
    i = text.find("{", m.end())
    if i == -1:
        fail(f"{name} has no {{ body")
    depth = 0; j = i
    while j < len(text):
        if text[j] == "{": depth += 1
        elif text[j] == "}":
            depth -= 1
            if depth == 0: break
        j += 1
    line = text[:m.start()].count("\n") + 1
    return text[i:j + 1], line

# (a) startMidiLearn acquires midiMapLock (comments stripped so a code
#     comment mentioning the lock cannot fake a pass)
start, line = extract_fn("startMidiLearn")
start_code = strip_comments(start)
if "midiMapLock" not in start_code:
    fail(f"startMidiLearn (PluginProcessor.h:{line}) writes midiLearnParamID/"
         "midiLearnActive without midiMapLock — audio-thread capture branch can "
         "read a torn juce::String parameter ID")
for field in ("midiLearnParamID", "midiLearnActive = true"):
    if field not in start:
        fail(f"startMidiLearn no longer sets {field} — MIDI learn arming is broken")
print("midi-learn-lock: startMidiLearn arms midiLearnParamID/midiLearnActive under midiMapLock")

# (b) stopMidiLearn still clears the flag
stop, stline = extract_fn("stopMidiLearn")
if "midiLearnActive = false" not in stop:
    fail(f"stopMidiLearn (PluginProcessor.h:{stline}) no longer clears midiLearnActive — "
         "an armed listen could never be cancelled")
print("midi-learn-lock: stopMidiLearn still clears midiLearnActive")

# audio-thread capture branch must remain under midiMapLock and read both fields
cpp = (SRC / "PluginProcessor.cpp").read_text()
cap = cpp.find("midiMap[cc] = midiLearnParamID")
if cap == -1:
    fail("audio-thread learn-capture branch (midiMap[cc] = midiLearnParamID) missing from PluginProcessor.cpp")
lock_site = cpp.rfind("midiMapLock", 0, cap)
if lock_site == -1:
    fail("capture branch no longer runs inside a midiMapLock scope")
if "midiLearnActive" not in cpp[cap - 400:cap]:
    fail("capture branch no longer checks midiLearnActive — armed learn would fire on every CC")
print("midi-learn-lock: audio-thread capture still reads both fields under midiMapLock")
