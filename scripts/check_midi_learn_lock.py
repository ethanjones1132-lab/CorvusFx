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

# audio-thread capture branch must remain under midiMapLock and record the
# armed param ID into midiMap (either `midiMap[cc] = ...` legacy single-CC
# shape or `midiMap[capturedCc] = ...` snapshot-lock-scope shape)
cpp = (SRC / "PluginProcessor.cpp").read_text(encoding="utf-8")
mcap = re.search(r"midiMap\s*\[\s*(?:cc|capturedCc)\s*\]\s*=\s*midiLearnParamID", cpp)
if not mcap:
    fail("audio-thread learn-capture branch (midiMap[...] = midiLearnParamID) missing from PluginProcessor.cpp")
cap = mcap.start()
lock_site = cpp.rfind("midiMapLock", 0, cap)
if lock_site == -1:
    fail("capture branch no longer runs inside a midiMapLock scope")
if "midiLearnActive" not in cpp[max(0, cap - 3000):cap]:
    fail("capture branch no longer checks midiLearnActive — armed learn would fire on every CC")
print("midi-learn-lock: audio-thread capture still reads both fields under midiMapLock")

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
