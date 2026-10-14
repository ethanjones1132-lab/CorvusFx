#!/usr/bin/env python3
"""Headless checker: MIDI-learn capture invariants in processBlock.

Asserts (in the audio-thread CC loop of PluginProcessor.cpp):
  (a) the capture branch still clears midiLearnActive after capturing,
  (b) the midiMap write for the captured CC happens inside the SAME held
      midiMapLock block (before the snapshot copy is taken),
  (c) no setValueNotifyingHost inside the capture branch (no jump),
  (d) capture REFUSES to overwrite a CC already mapped to a different
      parameter (the existing-lookup + different-param refusal must be
      present in the capture branch), so arming learn on a second knob
      cannot silently steal the first knob's CC.
Exit 0 = ok, 1 = violation with line-cited diagnostics.
"""
import re
import sys
from pathlib import Path
from typing import NoReturn

ROOT = Path(__file__).resolve().parent.parent
SRC = ROOT / "source" / "DrippyFX"


def fail(msg) -> NoReturn:
    print(f"MIDI-LEARN-CAPTURE FAIL: {msg}")
    sys.exit(1)


def check(text: str) -> None:
    # strip comments so commented code can't fake a pass
    code = re.sub(r"//[^\n]*", "", text)

    # find the processBlock CC loop: snapshot + lock block
    snap = code.find("std::map<int, juce::String> mapSnapshot")
    if snap == -1:
        fail("processBlock midiMap snapshot declaration missing")
    lock = code.find(" juce::ScopedLock lock(midiMapLock)", snap)
    if lock == -1:
        fail("capture block no longer acquires midiMapLock under the snapshot")
    # brace-match the lock block
    lb = code.find("{", lock)
    d = 0
    k = lb
    while k < len(code):
        if code[k] == "{":
            d += 1
        elif code[k] == "}":
            d -= 1
            if d == 0:
                break
        k += 1
    lock_block = code[lb:k + 1]

    # (b) the midiMap write for the captured CC lives INSIDE the lock block
    if "midiMap[cc] = midiLearnParamID" not in lock_block:
        fail("capture branch does not write midiMap under the held midiMapLock — "
             "the write must stay inside the lock block")
    # (a) the flag clear lives inside the lock block too
    if "midiLearnActive = false" not in lock_block:
        fail("capture branch no longer clears midiLearnActive after capture")
    # (c) no host jump inside the lock block
    if "setValueNotifyingHost" in lock_block:
        fail("capture branch calls setValueNotifyingHost — capture must not jump the host value")
    # (d) the refuse-to-steal guard: an existing-lookup plus a
    #     different-parameter comparison, INSIDE the lock block.
    if "midiMap.find(cc)" not in lock_block:
        fail("capture branch does not look up the pre-existing midiMap entry for the CC — "
             "overwriting an already-mapped CC silently steals it from the other parameter")
    if "existing->second != midiLearnParamID" not in lock_block:
        fail("capture branch does not refuse a CC already mapped to a DIFFERENT parameter "
             "(expected the existing->second != midiLearnParamID guard)")
    print("midi-learn-capture: capture clears the flag, writes midiMap inside the lock, "
          "no host jump, and refuses to overwrite a foreign CC mapping")


path = SRC / "PluginProcessor.cpp"
if not path.exists():
    fail(f"missing source file {path}")
check(path.read_text())
print("midi-learn-capture: real tree OK")

# ---- negative self-probes (mutated TEMP copies; real tree never mutated) ----
def expect_reject(name: str, old: str, new: str) -> None:
    t = path.read_text()
    if old not in t:
        print(f"midi-learn-capture probe '{name}': NO-OP MUTATION (pattern absent) — probe is stale, failing self-check")
        sys.exit(1)
    mutated = t.replace(old, new)
    if mutated == t:
        print(f"midi-learn-capture probe '{name}': NO-OP MUTATION — probe is stale, failing self-check")
        sys.exit(1)
    try:
        check(mutated)
    except SystemExit:
        print(f"midi-learn-capture probe '{name}': rejected as expected")
        return
    fail(f"probe '{name}' was NOT rejected — the checker asserted nothing")

# probe 1: strip the flag clear
expect_reject(
    "flag-clear stripped",
    "midiMap[cc] = midiLearnParamID;\n                        midiLearnActive = false;",
    "midiMap[cc] = midiLearnParamID;")
probe_path = path
# probes need mutation of the captured-branch shapes; run them here
_orig = path.read_text()

# probe 2: move the midiMap write outside the lock block (into the apply loop)
expect_reject(
    "midiMap write moved outside the lock",
    "capturedCc = cc;\n                        midiMap[cc] = midiLearnParamID;",
    "capturedCc = cc;")

# probe 3: re-add setValueNotifyingHost in the capture branch
expect_reject(
    "setValueNotifyingHost re-added in capture",
    "midiLearnActive = false;",
    "midiLearnActive = false;\n                            p->setValueNotifyingHost(0.0f);")

# probe 4: drop the refuse-to-steal guard (restore the old unconditional overwrite)
expect_reject(
    "refuse-to-steal guard removed",
    "auto existing = midiMap.find(cc);\n                        if (existing != midiMap.end() && existing->second != midiLearnParamID)\n                            continue;\n                        capturedCc = cc;",
    "capturedCc = cc;")

# probe 5: keep find but drop the different-param comparison
expect_reject(
    "different-param comparison removed",
    "existing->second != midiLearnParamID",
    "existing->second == midiLearnParamID")
