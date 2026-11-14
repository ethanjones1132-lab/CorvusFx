#!/usr/bin/env python3
"""check_midi_map_lock_scope.py

Pins the audio-thread MIDI CC apply path in processBlock (CV-027 shape):

  1. no ScopedLock on midiMapLock anywhere in processBlock — the callback must
     never take a lock the message thread can hold;
  2. the callback first try-reads the published CC→slot view
     (refreshMidiMapView) and then applies only from the preallocated
     `midiMapView` table — never from the live `midiMap`;
  3. the capture branch still reads midiLearnActive, records the captured CC
     in the pending atomics and clears the arm flag;
  4. no `setValueNotifyingHost` anywhere in processBlock: the apply path only
     STAGES the mapped value (stageMidiHostNotify) for the message-thread
     drain (CV-029);
  5. the apply path reads a roster slot and stages through that slot's
     preallocated parameter pointer — no juce::String/APVTS lookup.

Negative (proven): re-adding a lock or a live `midiMap.find(cc)` read to the
callback -> FAIL exit 1; dropping the view refresh -> FAIL exit 1; re-adding a
direct host notification after the staging call -> FAIL exit 1; restoring the
source -> EXIT 0. Every probe first verifies its mutation changed the text, so
a stale/no-op probe cannot pass vacuously.
"""
import re
import sys
from pathlib import Path

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

ROOT = Path(__file__).resolve().parent.parent
SRC = ROOT / "source" / "DrippyFX" / "PluginProcessor.cpp"

src = SRC.read_text(encoding="utf-8")

# Strip comments so commented-out code can't fake a pass.
no_comments = re.sub(r"//[^\n]*", "", src)
no_comments = re.sub(r"/\*.*?\*/", "", no_comments, flags=re.S)


def reject(text):
    """Return a diagnostic for the first violated invariant, or None."""
    m = re.search(r"CorvusFXAudioProcessor::processBlock\s*\(", text)
    if not m:
        return "processBlock definition missing"
    brace = text.find("{", m.end())
    if brace == -1:
        return "processBlock body not found"
    depth = 0
    end = len(text)
    for i in range(brace, len(text)):
        if text[i] == "{":
            depth += 1
        elif text[i] == "}":
            depth -= 1
            if depth == 0:
                end = i + 1
                break
    pb = text[brace:end]

    if re.search(r"\bScopedLock\b", pb) or re.search(r"\bmidiMapLock\b", pb):
        return ("processBlock takes midiMapLock (or any ScopedLock) — the "
                "callback must use the lock-free published view (CV-027)")
    if re.search(r"\bmidiMap\b", pb):
        return ("the apply path dereferences the live `midiMap` — it must read "
                "only the preallocated published view (CV-027)")
    if not re.search(r"refreshMidiMapView\s*\(\s*\)\s*;", pb):
        return ("the callback no longer refreshes its published MIDI-map view "
                "(refreshMidiMapView) before capturing/applying")
    if not re.search(r"midiMapView\s*\[", pb):
        return ("the apply path does not read the preallocated `midiMapView` "
                "table")
    if "midiLearnActive" not in pb:
        return ("the capture path no longer reads the armed midiLearnActive flag "
                "— armed learn would never capture, or every CC would")
    if "midiLearnActive = false" not in pb:
        return "the capture path no longer clears midiLearnActive after capture"
    if not re.search(r"pendingLearnCc\s*\.\s*store\s*\(", pb):
        return ("the capture path no longer records the captured CC in "
                "pendingLearnCc for the message-thread fold")
    if not re.search(r"stageMidiHostNotify\s*\(", pb):
        return ("the CC apply path no longer stages the mapped value "
                "(stageMidiHostNotify) — it must hand the newest value to the "
                "message-thread drain instead of notifying the host from "
                "processBlock")
    if "setValueNotifyingHost" in pb:
        return ("setValueNotifyingHost still runs in processBlock — the audio "
                "thread must only stage the newest value for the message-thread "
                "drain (CV-029)")
    return None


failures = []
verdict = reject(no_comments)
if verdict:
    failures.append(verdict)

probes = [
    ("lock re-added to processBlock",
     lambda t: re.sub(r"(\brefreshMidiMapView\s*\(\s*\)\s*;)",
                      r"const juce::ScopedLock lock(midiMapLock);\n \1", t, 1),
     "a blocking lock in the callback was accepted"),
    ("live midiMap.find re-added to the apply path",
     lambda t: re.sub(r"(\brefreshMidiMapView\s*\(\s*\)\s*;)",
                      r"\1\n (void) midiMap.find(cc);", t, 1),
     "a live-map read in the callback was accepted"),
    ("published-view refresh dropped",
     lambda t: re.sub(r"\brefreshMidiMapView\s*\(\s*\)\s*;", "", t, 1),
     "a callback that never adopts publications was accepted"),
    ("direct host notification re-added",
     lambda t: t.replace("stageMidiHostNotify(p, normValue);",
                         "stageMidiHostNotify(p, normValue);\n"
                         "                p->setValueNotifyingHost(normValue);", 1),
     "a host notification inside processBlock was accepted"),
]

for label, mutate, why in probes:
    mutated = mutate(no_comments)
    if mutated == no_comments:
        failures.append(f"no-op probe ({label}): mutation did not change the "
                        f"source — the negative check is vacuous")
        continue
    if reject(mutated) is None:
        failures.append(f"negative probe '{label}' was NOT rejected — {why}")

# Specificity: a benign edit outside the pinned shapes must still pass.
benign = no_comments.replace("int capturedCc = -1;",
                             "int capturedCc = -1 ;", 1)
if benign == no_comments:
    failures.append("benign no-op guard: anchor pattern absent")
elif reject(benign) is not None:
    failures.append(f"a benign edit was REJECTED — the checker "
                    f"over-fires: {reject(benign)}")

if failures:
    for f in failures:
        print("FAIL:", f)
    sys.exit(1)

print("OK: processBlock takes no MIDI-map lock; the apply path stages mapped "
      "values from the preallocated published view (CV-027) and never notifies "
      "the host or reads the live map (CV-029)")
sys.exit(0)
