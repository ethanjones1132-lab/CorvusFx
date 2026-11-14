#!/usr/bin/env python3
"""Headless checker: MIDI-learn arm-path locking invariants.

Asserts (in PluginProcessor.h):
  (a) CV-027: startMidiLearn resolves the target to a fixed roster slot and
      publishes that atomic slot before arming; it keeps no shared juce::String
      parameter id for the audio thread to read.
  (b) stopMidiLearn still clears midiLearnActive (single atomic flag,
      intentionally lock-free).
  (c) the audio-thread capture hands the CC + armed slot to the message-thread
      fold through preallocated atomics and never writes the map.
Exit 0 = ok, 1 = violation with line-cited diagnostics.
"""
import re
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SRC = ROOT / "source" / "DrippyFX"

def fail(msg):
    print(f"MIDI-LEARN-LOCK FAIL: {msg}")
    sys.exit(1)

path = SRC / "PluginProcessor.h"
if not path.exists():
    fail(f"missing source file {path}")
text = path.read_text(encoding="utf-8")

def strip_comments(src):
    src = re.sub(r"//[^\n]*", "", src)
    src = re.sub(r"/\*.*?\*/", "", src, flags=re.S)
    return src

def extract_fn(name, src=None, pattern=None):
    src = src if src is not None else text
    if pattern is not None:
        m = re.search(pattern % re.escape(name) if "%s" in pattern else pattern, src)
    else:
        m = re.search(rf"bool\s+(?:\w+::)?{name.strip()}\s*\(", src) if name.startswith("hasMidi") \
            else re.search(rf"void\s+(?:\w+::)?{name.strip()}\s*\(", src)
    if not m:
        fail(f"{name} definition missing")
    i = src.find("{", m.end())
    if i == -1:
        fail(f"{name} has no {{ body")
    depth = 0; j = i
    while j < len(src):
        if src[j] == "{": depth += 1
        elif src[j] == "}":
            depth -= 1
            if depth == 0: break
        j += 1
    line = src[:m.start()].count("\n") + 1
    return src[i:j + 1], line

# (a) CV-027: startMidiLearn resolves the target to the fixed roster slot and
#     publishes only that atomic slot before arming. The audio-thread capture
#     must not be able to see a torn juce::String id, so the arm path keeps no
#     shared String at all.
start, line = extract_fn("startMidiLearn")
start_code = strip_comments(start)
if "midiLearnParamSlot" not in start_code:
    fail(f"startMidiLearn (PluginProcessor.h:{line}) no longer resolves/publishes "
         "the atomic roster slot — the audio-thread capture has no lock-free "
         "armed target (CV-027)")
if "midiLearnParamID" in start_code:
    fail(f"startMidiLearn (PluginProcessor.h:{line}) still publishes a shared "
         "juce::String parameter id — the audio-thread capture would have to "
         "read a torn String (CV-027)")
if "midiLearnActive = true" not in start:
    fail("startMidiLearn no longer arms midiLearnActive — MIDI learn arming is "
         "broken")
if (start_code.find("midiLearnParamSlot")
        > start_code.find("midiLearnActive = true")):
    fail(f"startMidiLearn (PluginProcessor.h:{line}) arms midiLearnActive "
         "before publishing the atomic roster slot — a capture could read a "
         "stale slot (CV-027)")
print("midi-learn-lock: startMidiLearn publishes the atomic roster slot before "
      "arming (no shared juce::String)")

# (b) stopMidiLearn still clears the flag
stop, stline = extract_fn("stopMidiLearn")
if "midiLearnActive = false" not in stop:
    fail(f"stopMidiLearn (PluginProcessor.h:{stline}) no longer clears midiLearnActive — "
         "an armed listen could never be cancelled")
print("midi-learn-lock: stopMidiLearn still clears midiLearnActive")

# (b) CV-027: the audio-thread capture must NOT mutate the shared map or read
#     the juce::String armed id. It records the captured CC + armed roster slot
#     in preallocated atomics and disarms; the message-thread fold applies the
#     mapping under midiMapLock.
cpp = (SRC / "PluginProcessor.cpp").read_text(encoding="utf-8")


def capture_body(src_text):
    try:
        pb, _ = extract_fn("processBlock", src_text)
    except SystemExit:
        return None
    m = re.search(r"if\s*\(\s*midiLearnActive\s*\)", pb)
    if not m:
        return None
    i = pb.find("{", m.end())
    if i == -1:
        return None
    depth = 0
    for j in range(i, len(pb)):
        if pb[j] == "{":
            depth += 1
        elif pb[j] == "}":
            depth -= 1
            if depth == 0:
                return pb[i:j + 1]
    return None


def capture_violation(src_text):
    cap = capture_body(src_text)
    if cap is None:
        return "the midiLearnActive capture branch is missing from processBlock"
    code = strip_comments(cap)
    if re.search(r"\bmidiMap\s*\[", code):
        return ("the audio-thread capture writes midiMap[...] — the first learn "
                "event would allocate a map node in the callback (CV-027)")
    if "midiLearnParamID" in code:
        return ("the audio-thread capture reads midiLearnParamID (a "
                "juce::String) — it must use the atomic roster slot (CV-027)")
    if not re.search(r"pendingLearnCc\s*\.\s*store\s*\(", code):
        return ("the capture no longer records the captured CC in pendingLearnCc")
    if not re.search(r"pendingLearnSlot\s*\.\s*store\s*\(", code):
        return "the capture no longer records the armed slot in pendingLearnSlot"
    if "midiLearnActive = false" not in code:
        return "the capture no longer clears midiLearnActive"
    if "setValueNotifyingHost" in code:
        return "the capture jumps the parameter via setValueNotifyingHost"
    return None


violation = capture_violation(cpp)
if violation:
    fail(violation)

fold, fline = extract_fn("foldPendingMidiLearn", cpp)
fold_code = strip_comments(fold)
if "midiMapLock" not in fold_code:
    fail(f"foldPendingMidiLearn (PluginProcessor.cpp:{fline}) installs the "
         "learned mapping without midiMapLock")
fold_write = re.search(r"midiMap\s*\[\s*cc\s*\]\s*=\s*paramID", fold_code)
if not fold_write:
    fail(f"foldPendingMidiLearn (PluginProcessor.cpp:{fline}) no longer writes "
         "the learned mapping into midiMap")
if fold_code.find("midiMapLock") > fold_write.start():
    fail("foldPendingMidiLearn writes midiMap before acquiring midiMapLock")
pb_all, _ = extract_fn("processBlock", cpp)
if re.search(r"\bfoldPendingMidiLearn\s*\(", strip_comments(pb_all)):
    fail("processBlock calls foldPendingMidiLearn — the learn fold mutates the "
         "map and must run on the message thread (CV-027)")
print("midi-learn-lock: capture hands the armed slot to the message-thread "
      "fold; the fold writes midiMap under midiMapLock")

# (c) hasMidiMapping (def in PluginProcessor.cpp) acquires midiMapLock before
#     iterating the map: the map is mutated on the audio thread (learn capture)
#     and message thread (clear/restore) under the lock; the editor's knob
#     context menu (PluginEditor.cpp) calls this reader on the message thread,
#     so an unlocked iteration races a concurrent std::map insert (UB).
hasm, hline = extract_fn("hasMidiMapping", cpp)
hasm_code = strip_comments(hasm)
if "midiMapLock" not in hasm_code:
    fail(f"hasMidiMapping (PluginProcessor.cpp:{hline}) iterates midiMap without "
         "midiMapLock — audio-thread learn capture can insert mid-iteration and "
         "tear the map while the knob context menu reads it")
if "for (const auto& [cc, pid] : midiMap)" not in hasm_code:
    fail("hasMidiMapping no longer scans the midiMap entries — the "
         "Forget-MIDI-Mapping menu visibility check is broken")
print("midi-learn-lock: hasMidiMapping reads midiMap under midiMapLock")


# (d) getMidiMappings (header inline) must NOT expose a reference to the live
#     lock-guarded midiMap — it must return a snapshot copy taken under
#     midiMapLock, so a future caller (e.g. a mapping-list UI) can never
#     iterate the live map unsynchronized (same torn-map hazard
#     hasMidiMapping had before iter-060).
hdr_def = re.search(
    r"std::map<int,\s*juce::String>\s+getMidiMappings\s*\(\s*\)\s*const", text)
if not hdr_def:
    fail("getMidiMappings no longer returns a std::map<int, juce::String> by "
         "value — a reference return would leak the unsynchronized live map "
         "(torn-map hazard on any future caller)")
hdef, gline = extract_fn(
    "getMidiMappings", strip_comments(text),
    pattern=r"std::map<int,\s*juce::String>\s+getMidiMappings\s*\(\s*\)\s*const")
if "midiMapLock" not in hdef:
    fail(f"getMidiMappings (PluginProcessor.h:{gline}) builds its snapshot "
         "without midiMapLock — the copy itself races the audio-thread insert")
if "return midiMap" not in hdef:
    fail("getMidiMappings no longer returns the midiMap snapshot")
# and the old live-ref shape must be gone (comment-stripped, so a stale
# commented-out reference return cannot fake the pin)
if re.search(r"const\s+std::map<int,\s*juce::String>\s*&\s*getMidiMappings",
             strip_comments(text)):
    fail("getMidiMappings still exposes a live reference form of midiMap")
print("midi-learn-lock: getMidiMappings returns a midiMapLock-guarded snapshot")


# Negative self-probe (sibling style): mutate a temp copy, require rejection,
# and guard against a no-op mutation so the probe cannot pass vacuously.
def run_text(src_text):
    """Run the hasMidiMapping assertions against a mutated source text.
    Returns None on pass (all assertions hold) or a diagnostic string."""
    try:
        h, _ = extract_fn("hasMidiMapping", src_text)
    except SystemExit:
        return "hasMidiMapping missing"
    h_code = strip_comments(h)
    if "midiMapLock" not in h_code:
        return "unlocked hasMidiMapping accepted"
    if "for (const auto& [cc, pid] : midiMap)" not in h_code:
        return "scan loop missing"
    return None


LOCK_BLOCK = (
    "    juce::CriticalSection& mapLock =\n"
    "        const_cast<juce::CriticalSection&>(midiMapLock);\n"
    "    const juce::ScopedLock lock(mapLock);\n"
)
SCAN_LOOP = "for (const auto& [cc, pid] : midiMap)"

probes = [
    ("lock stripped from hasMidiMapping",
     lambda s: s.replace(LOCK_BLOCK, "")),
    ("scan loop stripped from hasMidiMapping",
     lambda s: s.replace(SCAN_LOOP, "for (const auto& [cc, pid] : midiMapCopy)")),
]

for label, mutate in probes:
    mutated = mutate(cpp)
    if mutated == cpp:
        fail(f"no-op probe ({label}): mutation did not change the source — "
             "the negative check is vacuous")
    verdict = run_text(mutated)
    if verdict is None:
        fail(f"negative probe '{label}' was NOT rejected — checker is vacuous")
    print(f"midi-learn-lock: negative probe '{label}' rejected")

# Negative probes for the CV-027 capture hand-off: a live map write or a lost
# disarm in the audio-thread branch must be rejected.
capture_probes = [
    ("live map write re-added to the capture branch",
     lambda s: s.replace(
         "pendingLearnCc.store(cc, std::memory_order_relaxed);",
         "midiMap[cc] = midiLearnParamID;\n"
         "                    pendingLearnCc.store(cc, std::memory_order_relaxed);",
         1)),
    ("disarm stripped from the capture branch",
     lambda s: s.replace("                    midiLearnActive = false;", "", 1)),
    ("armed juce::String read re-added to the capture branch",
     lambda s: s.replace(
         "const int armedSlot =\n"
         "                midiLearnParamSlot.load(std::memory_order_relaxed);",
         "const int armedSlot = 0; (void) midiLearnParamID;", 1)),
]

for label, mutate in capture_probes:
    mutated = mutate(cpp)
    if mutated == cpp:
        fail(f"no-op probe ({label}): mutation did not change the source — "
             "the negative check is vacuous")
    if capture_violation(mutated) is None:
        fail(f"negative probe '{label}' was NOT rejected — checker is vacuous")
    print(f"midi-learn-lock: negative probe '{label}' rejected")

# Negative self-probes for the getMidiMappings pin (header text): same
# mutate-copy / require-rejection / no-op-guard discipline.
GETMAPPINGS_BODY = (
    "    std::map<int, juce::String> getMidiMappings() const\n"
    "    {\n"
    "        juce::CriticalSection& mapLock =\n"
    "            const_cast<juce::CriticalSection&>(midiMapLock);\n"
    "        const juce::ScopedLock lock(mapLock);\n"
    "        return midiMap;\n"
    "    }"
)
LIVE_REF_SIG = "const std::map<int, juce::String>& getMidiMappings() const { return midiMap; }"

hdr_probes = [
    ("lock stripped from getMidiMappings",
     lambda s: s.replace(GETMAPPINGS_BODY,
                         "    std::map<int, juce::String> getMidiMappings() const\n"
                         "    {\n"
                         "        return midiMap;\n"
                         "    }")),
    ("live-reference return restored on getMidiMappings",
     lambda s: s.replace(GETMAPPINGS_BODY, LIVE_REF_SIG)),
]

for label, mutate in hdr_probes:
    mutated_hdr = mutate(text)
    if mutated_hdr == text:
        fail(f"no-op probe ({label}): mutation did not change the header — "
             "the negative check is vacuous")
    stripped = strip_comments(mutated_hdr)
    verdict = None
    if not re.search(r"std::map<int,\s*juce::String>\s+getMidiMappings\s*\(\s*\)\s*const",
                     stripped):
        verdict = "by-value signature lost"
    else:
        try:
            b, _ = extract_fn(
                "getMidiMappings", stripped,
                pattern=r"std::map<int,\s*juce::String>\s+getMidiMappings\s*\(\s*\)\s*const")
        except SystemExit:
            verdict = "getMidiMappings body missing"
        else:
            if "midiMapLock" not in b:
                verdict = "unlocked getMidiMappings accepted"
            if re.search(r"const\s+std::map<int,\s*juce::String>\s*&\s*getMidiMappings", stripped):
                verdict = "live-reference return accepted"
    if verdict is None:
        fail(f"negative probe '{label}' was NOT rejected — checker is vacuous")
    print(f"midi-learn-lock: negative probe '{label}' rejected")
print("midi-learn-lock: OK")
