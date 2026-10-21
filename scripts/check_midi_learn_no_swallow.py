#!/usr/bin/env python3
"""check_midi_learn_no_swallow.py

Asserts the MIDI-learn capture branch in the processBlock CC loop:
  1. it does NOT contain a bare `break` that exits the CC metadata loop
     (a break would swallow every later CC in the same audio buffer);
  2. the capture branch does NOT jump the parameter via
     `setValueNotifyingHost` (iter-019 no-jump guarantee);
  3. capture skips only its own iteration (a `continue` is present in the
     capture branch), keeping the mapping path active for other CCs.

Negatives (proven in iter-027): re-adding the bare break -> FAIL exit 1;
re-adding the capture jump -> FAIL exit 1; removing the continue -> FAIL 1.
Restore the original file to pass again.
"""
import re
import sys

SRC = "source/DrippyFX/PluginProcessor.cpp"

src = open(SRC, encoding="utf-8").read()

# Strip comments so a comment mentioning "break" can't fake anything,
# and so commented-out code can't satisfy checks either.
no_comments = re.sub(r"//[^\n]*", "", src)
no_comments = re.sub(r"/\*.*?\*/", "", no_comments, flags=re.S)

failures = []

# ---------------------------------------------------------------- helpers
def find_capture_branch(text):
    """Locate the `if (midiLearnActive)` block and return its brace body."""
    m = re.search(r"if\s*\(\s*midiLearnActive\s*\)", text)
    if not m:
        return None, None
    start = text.find("{", m.end())
    if start == -1:
        return m.start(), None
    depth = 0
    for i in range(start, len(text)):
        if text[i] == "{":
            depth += 1
        elif text[i] == "}":
            depth -= 1
            if depth == 0:
                return m.start(), text[start:i + 1]
    return m.start(), None

# ---------------------------------------------------------------- 1. no bare break exiting the CC loop in the capture branch
# (in the snapshot-lock-scope design the capture loop scans the whole
# buffer without exiting; any bare break here would stop that scan)
cap_start, cap_body = find_capture_branch(no_comments)
if cap_body is None:
    failures.append("could not locate the midiLearnActive capture branch")
else:
    if re.search(r"(?<!\w)break\s*;", cap_body):
        failures.append(
            "capture branch contains a bare `break;` — the capture loop must "
            "scan the full buffer without exiting it"
        )
    # ---------------------------------------------------------------- 3. the captured CC still skips its own apply step
    # Either `continue` inside the capture branch (legacy shape) or a
    # `cc == capturedCc` guard in the apply loop (snapshot shape).
    if not re.search(r"(?<!\w)continue\s*;", cap_body) and \
       not re.search(r"cc\s*==\s*capturedCc", no_comments[cap_start:]):
        failures.append(
            "the captured CC no longer skips its own mapping step — need a "
            "`continue` inside the capture branch or a `cc == capturedCc` "
            "guard in the apply loop (skip-only-this-CC semantics)"
        )

# 2. no jump inside the capture branch (iter-019 pin)
if cap_body is not None and "setValueNotifyingHost" in cap_body:
    failures.append(
        "capture branch calls setValueNotifyingHost — learning must record "
        "the mapping only (iter-019 removed the capture jump)"
    )

# sanity: the capture branch still records the mapping
if cap_body is not None and "midiMap[" not in cap_body:
    failures.append("capture branch no longer writes midiMap[...]")

# sanity: the loop still applies mappings for non-captured CCs
apply_region = no_comments[cap_start:] if cap_start is not None else no_comments
if "setValueNotifyingHost" not in apply_region:
    failures.append("the CC apply path (setValueNotifyingHost) has vanished")

# ---------------------------------------------------------------- report
if failures:
    for f in failures:
        print("FAIL:", f)
    sys.exit(1)

print("OK: midi-learn capture skips only its own CC (no bare break, "
      "no jump, skip-captured-CC guard present, other CCs still applied)")
sys.exit(0)
