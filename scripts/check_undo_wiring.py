#!/usr/bin/env python3
"""Headless checker: undo wiring invariants for the Ctrl+Z/Y feature.

Asserts (in the style of check_preset_tables.py):
  (a) `beginNewTransaction` has at least one call site in source/DrippyFX
  (b) the editor key handler still routes to audioProcessor.undoManager (undo + redo)
  (c) the apvts constructor still passes &undoManager
  (d) the AnimatedKnob left-button gesture path triggers onGestureStart
Exit 0 = ok, 1 = violation with line-cited diagnostics.
"""
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SRC = ROOT / "source" / "DrippyFX"

def fail(msg):
    print(f"UNDO-WIRING FAIL: {msg}")
    sys.exit(1)

def read(rel):
    p = SRC / rel
    if not p.exists():
        fail(f"missing source file {p}")
    return p.read_text(), p

proc_h, proc_h_path = read("PluginProcessor.h")
proc_c, proc_c_path = read("PluginProcessor.cpp")
edit_h, edit_h_path = read("PluginEditor.h")
edit_c, edit_c_path = read("PluginEditor.cpp")

# (a) at least one beginNewTransaction call site
sites = []
for name, txt, path in [
    ("PluginProcessor.h", proc_h, proc_h_path),
    ("PluginProcessor.cpp", proc_c, proc_c_path),
    ("PluginEditor.h", edit_h, edit_h_path),
    ("PluginEditor.cpp", edit_c, edit_c_path),
]:
    for i, line in enumerate(txt.splitlines(), 1):
        if "beginNewTransaction" in line and not line.strip().startswith("//"):
            sites.append(f"{path.name}:{i}")
if not sites:
    fail("no beginNewTransaction() call site found in source/DrippyFX — undo is a no-op")
print(f"undo: beginNewTransaction call sites -> {', '.join(sites)}")

# (b) editor key handler routes to audioProcessor.undoManager undo/redo
m = re.search(r"keyPressed\s*\(", edit_c)
if not m:
    fail("PluginEditor.cpp: keyPressed handler missing")
handler = edit_c[m.start():m.start() + 1200]
for need in ("audioProcessor.undoManager", ".undo()", ".redo()"):
    if need not in handler:
        fail(f"keyPressed handler no longer routes {need} through audioProcessor.undoManager")
print("undo: keyPressed routes Cmd+Z / Cmd+Shift+Z / Cmd+Y to audioProcessor.undoManager")

# (c) apvts constructor gets &undoManager
if not re.search(r"apvts\s*\([^)]*&\s*undoManager", proc_c, re.S):
    fail("apvts constructor no longer passes &undoManager")
print("undo: apvts constructed with &undoManager")

# (d) AnimatedKnob left-button gesture path calls onGestureStart
down = re.search(r"void\s+mouseDown\s*\(\s*const\s+juce::MouseEvent&\s+e\s*\)\s*override[^{]*\{", edit_h)
if not down:
    fail("AnimatedKnob::mouseDown override missing in PluginEditor.h")
body = edit_h[down.start():]
# grab the mouseDown body braces
depth = 0; i = edit_h.find("{", down.start()); j = i
while i < len(body) + down.start() and j < len(edit_h):
    if edit_h[j] == "{": depth += 1
    elif edit_h[j] == "}":
        depth -= 1
        if depth == 0: break
    j += 1
mdown_body = edit_h[i:j + 1]
if "onGestureStart" not in mdown_body:
    fail("AnimatedKnob::mouseDown left-button path no longer triggers onGestureStart (knob undo transactions unhooked)")
decl = re.search(r"std::function<void\(\)>\s+onGestureStart\s*;", edit_h)
if not decl:
    fail("AnimatedKnob no longer declares onGestureStart hook (PluginEditor.h)")
wired = re.search(r"k\.onGestureStart\s*=", edit_c)
if not wired:
    fail("setupKnob no longer wires k.onGestureStart to undoManager.beginNewTransaction (PluginEditor.cpp)")
print("undo: knob gesture start -> undoManager transaction wired in editor")

print("UNDO-WIRING OK")
