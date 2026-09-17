#!/usr/bin/env python3
"""check_midi_map_lock_scope.py

Pins the audio-thread CC apply path in processBlock:
  1. `setValueNotifyingHost` NO LONGER dereferences the live `midiMap`
     while `midiMapLock` is held: the apply path must use a snapshot copy
     (e.g. `mapSnapshot`) after the ScopedLock block closes;
  2. a ScopedLock on midiMapLock still exists (capture + snapshot still
     happen under the lock, locking discipline retained);
  3. the capture branch still writes under the lock (midiMap[...] inside
     the locked region) and clears midiLearnActive;
  4. no `setValueNotifyingHost` inside the ScopedLock block.

Negative (proven): temp-reverting the apply path to `midiMap.find(cc)`
inside the hold-locked ScopedLock region -> FAIL exit 1; removing the
ScopedLock entirely -> FAIL exit 1; restoring the source -> EXIT 0.
"""
import re
import sys

SRC = "source/DrippyFX/PluginProcessor.cpp"

src = open(SRC).read()

# Strip comments so commented-out code can't fake a pass.
no_comments = re.sub(r"//[^\n]*", "", src)
no_comments = re.sub(r"/\*.*?\*/", "", no_comments, flags=re.S)

failures = []

# Locate the MIDI-map region: the processBlock ScopedLock is the one whose
# enclosing block contains midiLearnActive (setStateInformation/clear* also
# take midiMapLock earlier in the file).
cands = [mm for mm in re.finditer(
    r"ScopedLock\s+lock\s*\(\s*midiMapLock\s*\)", no_comments)]
m = None
lock_block = ""
lock_block_end = 0
for c in cands:
    brace_start = no_comments.rfind("{", 0, c.start())
    bdepth = 0
    # walk forward from the brace that owns this lock statement
    for i in range(brace_start, len(no_comments)):
        if no_comments[i] == "{":
            bdepth += 1
        elif no_comments[i] == "}":
            bdepth -= 1
            if bdepth == 0:
                blk = no_comments[brace_start:i + 1]
                if "midiLearnActive" in blk:
                    m, lock_block, lock_block_end = c, blk, i + 1
                break
if m is None:
    failures.append("no ScopedLock(midiMapLock) block containing "
                    "midiLearnActive found in processBlock — capture/snapshot "
                    "locking discipline lost")
    for f in failures:
        print("FAIL:", f)
    sys.exit(1)

# Find the brace block that owns this ScopedLock.
brace_start = no_comments.rfind("{", 0, m.start())
depth = 0
lock_block = ""
lock_block_end = m.start()
for i in range(brace_start, len(no_comments)):
    if no_comments[i] == "{":
        depth += 1
    elif no_comments[i] == "}":
        depth -= 1
        if depth == 0:
            lock_block = no_comments[brace_start:i + 1]
            lock_block_end = i + 1
            break

region = no_comments[lock_block_end:]
apply_end = region.find("setValueNotifyingHost")
if apply_end == -1:
    failures.append("the CC apply path (setValueNotifyingHost) has vanished")
else:
    # The statement that dereferences the mapping must NOT be midiMap.find
    # after the lock (it must be the snapshot).
    window = region[max(0, apply_end - 600):apply_end]
    if re.search(r"midiMap\s*\.\s*find", window):
        failures.append(
            "the apply path still dereferences the live `midiMap.find(cc)` "
            "outside/around the lock — it must read from a snapshot copy so "
            "setValueNotifyingHost never contends midiMapLock with the "
            "message thread"
        )
    if "mapSnapshot" not in window:
        failures.append(
            "the apply path does not use a snapshot copy (mapSnapshot); the "
            "lock must be released before host notification"
        )

# No setValueNotifyingHost inside the locked block (host notification must
# never run while midiMapLock is held).
if "setValueNotifyingHost" in lock_block:
    failures.append(
        "setValueNotifyingHost appears INSIDE the midiMapLock ScopedLock "
        "block — host notification must happen after the lock is released"
    )

# Capture still writes under the lock and clears the flag.
if not re.search(r"midiMap\s*\[\s*\w+\s*\]\s*=", lock_block):
    failures.append("the capture path no longer records midiMap[cc] under the lock")
if "midiLearnActive = false" not in lock_block:
    failures.append("the capture path no longer clears midiLearnActive under the lock")
if "mapSnapshot" not in lock_block:
    failures.append("no snapshot copy is taken of midiMap under the lock")

if failures:
    for f in failures:
        print("FAIL:", f)
    sys.exit(1)

print("OK: CC apply path runs on a snapshot after midiMapLock release; "
      "capture+snapshot still under the lock; no host notification inside "
      "the critical section")
sys.exit(0)
