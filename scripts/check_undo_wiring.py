#!/usr/bin/env python3
"""Headless checker: undo wiring invariants for the Ctrl+Z/Y feature.

Asserts (in the style of check_preset_tables.py):
  (a) `beginNewTransaction` has at least one call site in source/DrippyFX
  (b) the editor key handler still routes to audioProcessor.undoManager (undo + redo)
  (c) the apvts constructor still passes &undoManager
  (d) the AnimatedKnob left-button gesture path triggers onGestureStart
  (e) the three NAMED transaction families still exist in
      PluginProcessor.cpp: "Load Preset", "Randomize", "A/B Compare" —
      deleting any of them (e.g. a "cleanup" that drops the Load Preset
      transaction) would pass (a) while knob-gesture transactions survive,
      so undo granularity silently degrades.
  Self-probes (negative checks, sibling checker style) run on mutated
  TEMP COPIES of the source text — the real tree is never mutated. A
  no-op mutation guard aborts the probe if the mutation didn't apply.

Exit 0 = ok, 1 = violation with line-cited diagnostics.
"""
import re
import sys
import tempfile
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

# (e) the three NAMED transaction families must each still exist in
# PluginProcessor.cpp: the "Load Preset" transaction (:57 area), the
# "Randomize" transaction (:171 area), and the four "A/B Compare"
# transactions. At-least-one part (a) passes even if these are deleted,
# so a future edit that drops a family breaks undo granularity silently.
NAMED_FAMILIES = [
    ('"Load Preset"', '"Load Preset"'),
    ('"Randomize"', '"Randomize"'),
    ('"A/B Compare"', '"A/B Compare"'),
]
proc_c_lines = proc_c.splitlines()
for label, needle in NAMED_FAMILIES:
    hits = [
        i for i, line in enumerate(proc_c_lines, 1)
        if "beginNewTransaction(" in line and needle.replace('"', "") in line
        and not line.strip().startswith("//")
    ]
    if not hits:
        fail(f"no beginNewTransaction({needle}) call site in PluginProcessor.cpp — undo granularity for the {label.strip(chr(34))} family is gone (Ctrl+Z after that action rewinds into a wrong transaction)")
    print(f"undo: beginNewTransaction({needle}) at {', '.join(f'PluginProcessor.cpp:{h}' for h in hits)}")

# Count A/B Compare must be the expected pair-of-pairs shape? Keep it
# cardinality-pinned loosely: >= 2 (slot A save/toggle + slot B save/toggle).
ab_hits = sum(
    1 for line in proc_c_lines
    if "beginNewTransaction(" in line and "A/B Compare" in line
    and not line.strip().startswith("//")
)
if ab_hits < 2:
    fail(f"only {ab_hits} beginNewTransaction(\"A/B Compare\") site(s) — the save-slot and toggle paths must each carry a transaction")

# ---------------------------------------------------------------------------
# Self-probes: negative checks on mutated TEMP COPIES (real tree never changed)
# ---------------------------------------------------------------------------

def run_checker_text(proc_c_text, edit_c_text, edit_h_text, proc_h_text):
    """Run parts (a)/(e) against supplied source texts; True = all pass."""
    # (a)
    sites2 = []
    for txt in (proc_h_text, proc_c_text, edit_h_text, edit_c_text):
        for line in txt.splitlines():
            if "beginNewTransaction" in line and not line.strip().startswith("//"):
                sites2.append(line)
    if not sites2:
        return False
    # (e) on the supplied PluginProcessor.cpp text
    lines2 = proc_c_text.splitlines()
    for label, needle in NAMED_FAMILIES:
        keyword = needle.replace('"', "")
        if not any(
            "beginNewTransaction(" in l and keyword in l
            and not l.strip().startswith("//")
            for l in lines2
        ):
            return False
    if sum(1 for l in lines2 if "beginNewTransaction(" in l and "A/B Compare" in l and not l.strip().startswith("//")) < 2:
        return False
    return True

def mutate_and_expect_fail(description, mutator, text, mutate_ok):
    tmp = text.replace(*mutator)
    if tmp == text:
        print(f"undo: no-op mutation guard -> skipping invalid probe ({description})")
        return
    if run_checker_text(tmp, tmp, tmp, tmp):
        print(f"undo: SELF-PROBE FAIL (checker should reject): {description}")
        sys.exit(1)
    print(f"undo: self-probe fired as designed: {description}")

# 1. remove the Randomize transaction line
randomize_line = next(
    (l for l in proc_c_lines if "beginNewTransaction(" in l and "Randomize" in l and not l.strip().startswith("//")),
    None,
)
if randomize_line is not None:
    mut = (randomize_line, "")
    tmp = proc_c.replace(*mut)
    if tmp == proc_c:
        print("undo: no-op mutation guard -> skipping invalid probe (Randomize)")
    elif run_checker_text(tmp, tmp, tmp, tmp):
        print("undo: SELF-PROBE FAIL (checker should reject): Randomize transaction line removed")
        sys.exit(1)
    else:
        print("undo: self-probe fired: Randomize transaction line removed -> rejected")
else:
    fail("self-probe baseline broken: Randomize transaction line not found in the real tree")

# 2. remove one "A/B Compare" family pair (A/B Compare sites gone entirely)
ab_lines = [l for l in proc_c_lines if "beginNewTransaction(" in l and "A/B Compare" in l and not l.strip().startswith("//")]
if ab_lines:
    tmp = proc_c
    for l in reversed(ab_lines):
        tmp = tmp.replace(l + "\n", "", 1)
    if tmp == proc_c:
        print("undo: no-op mutation guard -> skipping invalid probe (A/B Compare)")
    elif run_checker_text(tmp, tmp, tmp, tmp):
        print("undo: SELF-PROBE FAIL (checker should reject): all A/B Compare transactions removed")
        sys.exit(1)
    else:
        print("undo: self-probe fired: A/B Compare transactions removed -> rejected")
else:
    fail("self-probe baseline broken: A/B Compare transactions not found in the real tree")

# 3. remove the Load Preset transaction line
load_line = next(
    (l for l in proc_c_lines if "beginNewTransaction(" in l and "Load Preset" in l and not l.strip().startswith("//")),
    None,
)
if load_line is not None:
    tmp = proc_c.replace(load_line, "")
    if tmp == proc_c:
        print("undo: no-op mutation guard -> skipping invalid probe (Load Preset)")
    elif run_checker_text(tmp, tmp, tmp, tmp):
        print("undo: SELF-PROBE FAIL (checker should reject): Load Preset transaction line removed")
        sys.exit(1)
    else:
        print("undo: self-probe fired: Load Preset transaction line removed -> rejected")
else:
    fail("self-probe baseline broken: Load Preset transaction line not found in the real tree")

# 4. no-op mutation must NOT trip part (e): mutate an unrelated line and
#    the checker must still accept the text
noop_mutator = ("// UNDO NO-OP ANCHOR\n", "")
noop_tmp = proc_c.replace(proc_c_lines[0], proc_c_lines[0] + noop_mutator[0], 1)
if noop_tmp == proc_c:
    print("undo: no-op probe skipped (could not apply benign edit)")
elif not run_checker_text(noop_tmp, noop_tmp, noop_tmp, noop_tmp):
    fail("no-op guard: benign edit outside the transaction lines was wrongly rejected")
else:
    print("undo: no-op guard passed (benign edit accepted)")

print("UNDO-WIRING OK")
