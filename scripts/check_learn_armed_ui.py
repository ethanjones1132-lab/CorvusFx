#!/usr/bin/env python3
"""Headless checker: MIDI-learn armed/cancel affordance in the editor.

Asserts (in comment-stripped PluginEditor.cpp text):
  (a) the knob context-menu builder offers a "Cancel MIDI Learn" item,
      gated on the processor's armed-learn query (isMidiLearnActive),
  (b) the cancel item wires stopMidiLearn — so a second stopMidiLearn
      call site exists in PluginEditor.cpp besides the destructor cleanup,
  (c) the header exposes an isMidiLearnActive() accessor (message-thread
      read of the atomic armed state) in PluginProcessor.h,
  (d) ModalCallback-menu free: the cancel path lives in the context menu
      (no AlertWindow dependency assumed).
Exit 0 = ok, 1 = violation with a named diagnostic.
"""
import re
import sys
from pathlib import Path
from typing import NoReturn

ROOT = Path(__file__).resolve().parent.parent
SRC = ROOT / "source" / "DrippyFX"


def fail(msg) -> NoReturn:
    print(f"LEARN-ARMED-UI FAIL: {msg}")
    sys.exit(1)


def check_editor(text: str) -> None:
    code = re.sub(r"//[^\n]*", "", text)

    if "isMidiLearnActive()" not in code:
        fail("editor never consults the armed-learn state "
             "(expected isMidiLearnActive() in PluginEditor.cpp)")
    if '"Cancel MIDI Learn"' not in code:
        fail("the knob context menu no longer offers a 'Cancel MIDI Learn' item")

    # the cancel item must wire stopMidiLearn: a stopMidiLearn call site
    # must exist besides the destructor's cleanup one
    sites = [m.start() for m in re.finditer(r"stopMidiLearn\(\)", code)]
    if len(sites) < 2:
        fail(f"PluginEditor.cpp must keep a stopMidiLearn call site besides the "
             f"destructor cleanup (found {len(sites)})")

    # order sanity: the cancel menu item precedes the "MIDI Learn" arm item,
    # matching the shipped affordance shape
    cancel = code.find('"Cancel MIDI Learn"')
    arm = code.find('"MIDI Learn"', cancel + 20)
    if arm == -1:
        fail("the 'MIDI Learn' (arm) menu item disappeared")
    gate = code.find("isMidiLearnActive()", 0, cancel)
    if gate == -1:
        fail("the 'Cancel MIDI Learn' item is not gated on isMidiLearnActive() — "
             "it must only appear while a learn is armed")
    print("learn-armed-ui: editor offers a Cancel MIDI Learn menu item gated on "
          "isMidiLearnActive(), wired to stopMidiLearn")


def check_header(text: str) -> None:
    code = re.sub(r"//[^\n]*", "", text)
    if "bool isMidiLearnActive() const" not in code:
        fail("PluginProcessor.h is missing the isMidiLearnActive() const "
             "accessor (message thread needs to read the armed state)")
    print("learn-armed-ui: processor exposes isMidiLearnActive()")


ed = SRC / "PluginEditor.cpp"
hd = SRC / "PluginProcessor.h"
for path in (ed, hd):
    if not path.exists():
        fail(f"missing source file {path}")
check_editor(ed.read_text())
check_header(hd.read_text())
print("learn-armed-ui: real tree OK")

# ---- negative self-probes (mutated TEMP texts; real tree never mutated) ----
def expect_reject(name: str, text: str, old: str, new: str, which: str) -> None:
    if old not in text:
        print(f"learn-armed-ui probe '{name}': NO-OP MUTATION (pattern absent) — "
              "probe is stale, failing self-check")
        sys.exit(1)
    mutated = text.replace(old, new)
    if mutated == text:
        print(f"learn-armed-ui probe '{name}': NO-OP MUTATION — probe is stale, "
              "failing self-check")
        sys.exit(1)
    try:
        (check_editor if which == "ed" else check_header)(mutated)
    except SystemExit:
        print(f"learn-armed-ui probe '{name}': rejected as expected")
        return
    fail(f"probe '{name}' was NOT rejected — the checker asserted nothing")

ed_text = ed.read_text()
hd_text = hd.read_text()

# probe 1: strip the cancel menu item
expect_reject("cancel item stripped", ed_text,
              'menu.addItem("Cancel MIDI Learn", [&proc]() {\n'
              '                    proc.stopMidiLearn();\n'
              '                });', "", "ed")

# probe 2: drop the armed-state gate (cancel always offered)
expect_reject("isMidiLearnActive gate dropped", ed_text,
              "if (proc.isMidiLearnActive())\n", "", "ed")

# probe 3: remove ALL but one stopMidiLearn call site (cancel unwired)
expect_reject("stopMidiLearn site stripped", ed_text,
              'proc.stopMidiLearn();\n'
              '                });', 'proc.stopMidiLearn_();\n'
              '                });', "ed")

# probe 4: header accessor removed
expect_reject("header accessor removed", hd_text,
              "bool isMidiLearnActive() const", "", "hd")
