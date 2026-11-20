#!/usr/bin/env python3
"""Headless checker: CV-027 — processBlock takes no MIDI-map lock and never
allocates, including on the first MIDI-learn event.

The MIDI map used to be mutated on the audio thread under `midiMapLock` (the
learn capture inserted a map node on the first learned CC) and snapshotted into
a member vector while holding that same lock. The message thread could hold
that lock across clear/restore/XML work, so the callback could block, and the
first learn event allocated a std::map node (plus its juce::String key/value)
inside the render callback.

Pinned shape (CV-027):

  * PluginProcessor.h declares a fixed-size publication table, one sequence
    counter, two fixed-size audio-thread read buffers and three learn atomics:
        std::array<std::atomic<int>, MAX_MIDI_CCS> publishedMidiCcSlots;
        std::atomic<unsigned> midiMapSequence;
        std::array<int, MAX_MIDI_CCS> midiMapView;
        std::array<int, MAX_MIDI_CCS> midiMapScratch;
        std::atomic<int> midiLearnParamSlot / pendingLearnCc / pendingLearnSlot;
    and no `mapSnapshot` member (the old lock-scoped refill is gone).
  * publishMidiMap() (message thread) flattens midiMap into roster-slot
    indices behind the sequence counter (odd = write in progress).
  * refreshMidiMapView() (audio thread) try-reads that table into the scratch
    array, re-checks the sequence and only then adopts it as midiMapView; an
    in-flight publication leaves the previous view intact.
  * processBlock contains NO `midiMapLock`, NO `ScopedLock`, NO live `midiMap`
    access and no allocation token (reserve/push_back/emplace/resize/insert/
    assign/new/malloc/juce::String). It refreshes the view, records a learn in
    the pending atomics, and applies mapped CCs by roster slot.
  * foldPendingMidiLearn() (message thread) takes midiMapLock, writes
    `midiMap[cc] = paramID` and republishes; it is never called by processBlock.
  * CorvusFxStateTests.cpp carries the concurrency regression: a std::thread
    publishes map edits/folds while the test thread drives processBlock with a
    thread-local allocation probe that must read zero.

CV-083 pins the way those two callback loops READ a message:

  * Both midiMessages loops (learn capture and CC apply) skip any event whose
    `metadata.numBytes` is not 3 before touching it, and then read the three
    controller bytes straight out of `metadata.data` (status & 0xf0 == 0xb0,
    number = data[1], value = data[2]).
  * Neither loop calls `metadata.getMessage()`: a MidiMessage owns its storage
    and can heap-allocate for a long (e.g. SysEx) event, inside the render
    callback, even when the loop would then skip it.

CV-094 pins the instrument render loops (CorvusSynthEngine.h):

  * render() and renderWithDawnActivityGain() hand every host event to
    handleMidiMetadata(), which reads metadata.data[0..2] directly.
  * handleMidiMetadata() skips any event whose numBytes is not 2 or 3, and any
    event whose status byte is not a channel message (0x80..0xef), BEFORE
    touching the bytes — so a SysEx, meta or other long event is skipped whole
    and never partially applied.
  * Neither render loop (nor the dispatcher) may call metadata.getMessage(): a
    MidiMessage owns its storage and can heap-allocate for a long event inside
    the render callback. The message is constructed on the stack from the raw
    bytes instead, which stores a short message inline.

Negative probes mutate in-memory copies of the LIVE tree (the real tree is
never written) and must be rejected: a ScopedLock(midiMapLock) re-added to the
callback, a live midiMap read re-added, the view refresh dropped, the pending
learn record dropped, the fold lock removed, the fold map write removed, the
fold republish removed, a getMessage() call re-added to either instrument
render loop, the instrument raw-byte dispatcher dropped or its 2/3-byte guard
removed. A probe whose pattern is absent fails as NO-OP, and a benign comment
edit (one of them inside a callback MIDI loop) must still pass (probe
specificity).

Exit 0 = ok, 1 = violation with a cited diagnostic.
"""
import re
import sys
from pathlib import Path
from typing import NoReturn

# Diagnostics quote source text with non-ASCII arrows; a cp1252 console must
# not turn a verdict into a crash.
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

ROOT = Path(__file__).resolve().parent.parent
CPP = ROOT / "source" / "DrippyFX" / "PluginProcessor.cpp"
HDR = ROOT / "source" / "DrippyFX" / "PluginProcessor.h"
TESTS = ROOT / "source" / "DrippyFX" / "tests" / "CorvusFxStateTests.cpp"
INSTRUMENT = ROOT / "source" / "DrippyFX" / "instrument" / "CorvusSynthEngine.h"


class Reject(Exception):
    """Structural violation detected in a (real or mutated) source text."""


def fail(msg) -> NoReturn:
    print(f"CV-027 FAIL: {msg}")
    sys.exit(1)


def strip_comments(text):
    text = re.sub(r"/\*.*?\*/", "", text, flags=re.S)
    return re.sub(r"//[^\n]*", "", text)


def block_at(text, pos):
    lb = text.find("{", pos)
    if lb == -1:
        return None
    depth = 0
    for k in range(lb, len(text)):
        if text[k] == "{":
            depth += 1
        elif text[k] == "}":
            depth -= 1
            if depth == 0:
                return lb, k + 1, text[lb:k + 1]
    return None


def method_body(code, name):
    m = re.search(r"\bCorvusFXAudioProcessor::" + re.escape(name) + r"\s*\(", code)
    if not m:
        return None
    found = block_at(code, m.end())
    return found[2] if found else None


def midi_loop_bodies(body):
    """Bodies of every `for (... : midiMessages)` loop inside processBlock."""
    bodies = []
    for m in re.finditer(r"for\s*\([^)]*:\s*midiMessages\s*\)", body):
        found = block_at(body, m.end())
        if found is None:
            raise Reject("PluginProcessor.cpp:processBlock: a midiMessages loop is "
                         "not brace-matched")
        bodies.append(found[2])
    return bodies


def _require(body, pattern, where, why):
    if not re.search(pattern, body):
        raise Reject(f"{where}: {why}")


ALLOCATION_TOKENS = (
    r"\.\s*reserve\s*\(",
    r"\.\s*push_back\s*\(",
    r"\.\s*emplace",
    r"\.\s*resize\s*\(",
    r"\.\s*insert\s*\(",
    r"\.\s*assign\s*\(",
    r"\bnew\b",
    r"\bmalloc\b",
    r"juce::String",
)


INSTRUMENT_LOOPS = ("render", "renderWithDawnActivityGain")
INSTRUMENT_DISPATCH = "handleMidiMetadata"


def synth_member_body(header, name):
    """Body of an inline member function of CorvusSynthEngine.h."""
    m = re.search(r"\bvoid\s+" + re.escape(name) + r"\s*\(", header)
    if not m:
        return None
    found = block_at(header, m.end())
    return found[2] if found else None


def check_instrument(synth):
    """CV-094: both instrument render loops dispatch on raw event bytes.

    `synth` is CorvusSynthEngine.h with comments already stripped.
    """
    loop_bodies = []
    for name in INSTRUMENT_LOOPS:
        body = synth_member_body(synth, name)
        if body is None:
            raise Reject(f"CorvusSynthEngine.h:{name} body not found/brace-matched "
                         f"— the instrument render loop must dispatch host MIDI "
                         f"itself (CV-094)")
        loop_bodies.append((name, body))

    for name, body in loop_bodies:
        where = f"CorvusSynthEngine.h:{name}"
        if re.search(r"\bgetMessage\s*\(", body):
            raise Reject(f"{where} calls getMessage() — a MidiMessage owns its "
                         f"storage and can heap-allocate for a long event; read "
                         f"metadata.data[0..2] instead (CV-094)")
        _require(body, r"\bfor\s*\([^)]*:\s*midi\s*\)", where,
                 "the render loop no longer iterates the host MidiBuffer")
        _require(body, r"\b" + INSTRUMENT_DISPATCH + r"\s*\(\s*metadata\b", where,
                 "the render loop no longer hands each host event to the "
                 "raw-byte dispatcher — it would have to build a MidiMessage "
                 "(CV-094)")
        for token in ("juce::String", "std::string", "std::vector",
                      ".push_back(", ".reserve(", ".resize("):
            if token in body:
                raise Reject(f"{where} contains {token!r} — the render callback "
                             f"must not allocate (CV-094)")

    dispatch = synth_member_body(synth, INSTRUMENT_DISPATCH)
    if dispatch is None:
        raise Reject(f"CorvusSynthEngine.h:{INSTRUMENT_DISPATCH} body missing — "
                     f"the render loops must dispatch on the raw event bytes "
                     f"(CV-094)")
    where = f"CorvusSynthEngine.h:{INSTRUMENT_DISPATCH}"
    if re.search(r"\bgetMessage\s*\(", dispatch):
        raise Reject(f"{where} calls getMessage() — a MidiMessage owns its "
                     f"storage and can heap-allocate for a long event; read "
                     f"metadata.data[0..2] instead (CV-094)")
    _require(dispatch, r"metadata\s*\.\s*data\s*\[\s*0\s*\]", where,
             "the dispatcher no longer reads the raw status byte from "
             "metadata.data")
    _require(dispatch, r"metadata\s*\.\s*numBytes\s*<\s*2", where,
             "the dispatcher no longer rejects sub-2-byte events before "
             "touching them (CV-094)")
    _require(dispatch, r"metadata\s*\.\s*numBytes\s*>\s*3", where,
             "the dispatcher no longer rejects events longer than 3 bytes — a "
             "SysEx or meta event would be partly applied instead of skipped "
             "whole (CV-094)")
    _require(dispatch, r"\bstatus\s*<\s*0x80", where,
             "the dispatcher no longer requires a channel-message status byte "
             "(CV-094)")
    _require(dispatch, r"\bstatus\s*>\s*0xef", where,
             "the dispatcher no longer rejects system (0xf0..) events — a SysEx "
             "would reach handleMidiMessage() (CV-094)")
    _require(dispatch, r"juce::MidiMessage\s*\([^;]*bytes\s*\[\s*0\s*\][^;]*"
                       r"bytes\s*\[\s*1\s*\]", where,
             "the dispatcher no longer builds the message on the stack from the "
             "raw bytes (CV-094)")
    _require(dispatch, r"\bhandleMidiMessage\s*\(", where,
             "the dispatcher no longer routes accepted events to "
             "handleMidiMessage() — note on/off, pitch wheel, sustain, panic "
             "and all-notes-off would be lost (CV-094)")

    if re.search(r"\bgetMessage\s*\(", synth):
        raise Reject("CorvusSynthEngine.h calls getMessage() outside a pinned "
                     "render loop — no instrument path may build a MidiMessage "
                     "from a host event's owned storage (CV-094)")


def check(raw_cpp, raw_header, raw_tests, raw_instrument):
    code = strip_comments(raw_cpp)
    header = strip_comments(raw_header)
    tests = strip_comments(raw_tests)
    synth = strip_comments(raw_instrument)

    pb = method_body(code, "processBlock")
    if pb is None:
        raise Reject("PluginProcessor.cpp: processBlock body not found/brace-matched")

    # ---- (1) the callback must not touch the map, its lock or any allocation
    if re.search(r"\bmidiMapLock\b", pb):
        raise Reject("processBlock references midiMapLock — the audio thread must "
                     "never take a lock the message thread can hold (CV-027)")
    if re.search(r"\bScopedLock\b", pb):
        raise Reject("processBlock takes a ScopedLock — the MIDI-map publication "
                     "must be a try-read, not a blocking lock (CV-027)")
    if re.search(r"\bmidiMap\b", pb):
        raise Reject("processBlock reads the live midiMap — the callback must read "
                     "the published CC→slot view only (CV-027)")
    for token in ALLOCATION_TOKENS:
        if re.search(token, pb):
            raise Reject(f"processBlock matches the allocation token {token!r} — "
                         f"the callback must not allocate, including on the first "
                         f"MIDI-learn event (CV-027)")
    if re.search(r"setValueNotifyingHost|beginChangeGesture|endChangeGesture|"
                 r"undoManager", pb):
        raise Reject("processBlock performs host-facing work — CV-029 requires the "
                     "message-thread drain to notify the host (CV-027/029)")
    if re.search(r"\bfoldPendingMidiLearn\s*\(", pb):
        raise Reject("processBlock calls foldPendingMidiLearn() — the learn fold "
                     "mutates the map and must run on the message thread (CV-027)")

    # ---- (2) lock-free try-read of the published table
    _require(pb, r"refreshMidiMapView\s*\(\s*\)\s*;",
             "PluginProcessor.cpp:processBlock",
             "the callback no longer refreshes its MIDI-map view")
    _require(pb, r"midiMapView\s*\[",
             "PluginProcessor.cpp:processBlock",
             "the apply path no longer reads the preallocated midiMapView table")

    # ---- (3) learn capture hands off through atomics only
    _require(pb, r"pendingLearnCc\s*\.\s*store\s*\(",
             "PluginProcessor.cpp:processBlock",
             "the learn capture no longer records the CC in pendingLearnCc — it "
             "must hand the first learn event to the message-thread fold")
    _require(pb, r"pendingLearnSlot\s*\.\s*store\s*\(",
             "PluginProcessor.cpp:processBlock",
             "the learn capture no longer records the armed roster slot in "
             "pendingLearnSlot")
    _require(pb, r"midiLearnActive\s*=\s*false",
             "PluginProcessor.cpp:processBlock",
             "the learn capture no longer disarms midiLearnActive")
    _require(pb, r"midiLearnParamSlot\s*\.\s*load\s*\(",
             "PluginProcessor.cpp:processBlock",
             "the learn capture no longer reads the armed atomic slot — it must "
             "never read the juce::String midiLearnParamID on the audio thread")
    if re.search(r"midiLearnParamID", pb):
        raise Reject("processBlock reads midiLearnParamID (a juce::String) — the "
                     "armed target must be published as the atomic roster slot "
                     "(CV-027)")

    # ---- (4) the CC apply path stages through the roster slot
    _require(pb, r"stageMidiHostNotify\s*\(",
             "PluginProcessor.cpp:processBlock",
             "the CC apply path no longer stages the mapped value for the "
             "message-thread drain")

    # ---- (5) message-thread publication + fold
    publish = method_body(code, "publishMidiMap")
    if publish is None:
        raise Reject("PluginProcessor.cpp: publishMidiMap body missing — the map "
                     "can no longer reach the audio thread (CV-027)")
    if len(re.findall(r"midiMapSequence\s*\.\s*fetch_add\s*\(\s*1", publish)) != 2:
        raise Reject("publishMidiMap must bracket the table write with two "
                     "midiMapSequence.fetch_add(1, ...) calls (odd = write in "
                     "progress, even = stable) (CV-027)")
    _require(publish, r"publishedMidiCcSlots\s*\[[^\]]*\]\s*\.\s*store\s*\(",
             "PluginProcessor.cpp:publishMidiMap",
             "publishMidiMap no longer writes the published CC→slot table")
    _require(publish, r"\bmidiMapLock\b",
             "PluginProcessor.cpp:publishMidiMap",
             "publishMidiMap reads midiMap without midiMapLock")
    if re.search(r"\bmidiMapView\b", publish):
        raise Reject("publishMidiMap writes the audio-thread view directly — the "
                     "callback owns midiMapView and must adopt publications "
                     "itself (CV-027)")

    refresh = method_body(code, "refreshMidiMapView")
    if refresh is None:
        raise Reject("PluginProcessor.cpp: refreshMidiMapView body missing — the "
                     "callback cannot adopt a published map (CV-027)")
    if len(re.findall(r"midiMapSequence\s*\.\s*load\s*\(", refresh)) < 2:
        raise Reject("refreshMidiMapView does not verify the sequence before and "
                     "after the copy — a torn view could be adopted (CV-027)")
    _require(refresh, r"midiMapView\s*=\s*midiMapScratch\s*;",
             "PluginProcessor.cpp:refreshMidiMapView",
             "refreshMidiMapView no longer adopts the coherent scratch copy")
    if re.search(r"midiMapLock|ScopedLock|juce::String", refresh):
        raise Reject("refreshMidiMapView takes a lock or touches a juce::String — "
                     "it runs on the audio thread (CV-027)")

    fold = method_body(code, "foldPendingMidiLearn")
    if fold is None:
        raise Reject("PluginProcessor.cpp: foldPendingMidiLearn body missing — a "
                     "captured learn would never reach the map (CV-027)")
    _require(fold, r"\bmidiMapLock\b",
             "PluginProcessor.cpp:foldPendingMidiLearn",
             "the fold mutates midiMap without midiMapLock")
    _require(fold, r"midiMap\s*\[\s*cc\s*\]\s*=\s*paramID",
             "PluginProcessor.cpp:foldPendingMidiLearn",
             "the fold no longer installs the captured mapping into midiMap")
    _require(fold, r"publishMidiMap\s*\(\s*\)",
             "PluginProcessor.cpp:foldPendingMidiLearn",
             "the fold no longer republishes the map for the audio thread")
    _require(fold, r"pendingLearnSlot\s*\.\s*exchange\s*\(",
             "PluginProcessor.cpp:foldPendingMidiLearn",
             "the fold no longer consumes the pending learn slot")

    # ---- (6) fixed-size declaration shapes in the header
    if re.search(r"\bmapSnapshot\b", header):
        raise Reject("PluginProcessor.h still declares mapSnapshot — the "
                     "lock-scoped refill is replaced by the fixed published table "
                     "(CV-027)")
    if not re.search(r"MAX_MIDI_CCS\s*=\s*128\b", header):
        raise Reject("PluginProcessor.h no longer pins MAX_MIDI_CCS = 128 — the "
                     "published table must cover the full legal CC domain 0..127 "
                     "(CV-027)")
    for pattern, why in (
            (r"std::array\s*<\s*std::atomic\s*<\s*int\s*>\s*,\s*MAX_MIDI_CCS\s*>\s*"
             r"publishedMidiCcSlots", "the fixed published CC→slot table"),
            (r"std::atomic\s*<\s*unsigned\s*>\s*midiMapSequence",
             "the publication sequence counter"),
            (r"std::array\s*<\s*int\s*,\s*MAX_MIDI_CCS\s*>\s*midiMapView",
             "the preallocated audio-thread view"),
            (r"std::array\s*<\s*int\s*,\s*MAX_MIDI_CCS\s*>\s*midiMapScratch",
             "the preallocated try-read scratch table"),
            (r"std::atomic\s*<\s*int\s*>\s*midiLearnParamSlot",
             "the armed atomic roster slot"),
            (r"std::atomic\s*<\s*int\s*>\s*pendingLearnCc",
             "the pending learn CC atomic"),
            (r"std::atomic\s*<\s*int\s*>\s*pendingLearnSlot",
             "the pending learn slot atomic")):
        if not re.search(pattern, header):
            raise Reject(f"PluginProcessor.h is missing {why} — the lock-free "
                         f"MIDI-map publication shape is incomplete (CV-027)")

    # ---- (7) the concurrency/allocation regression exists
    for pattern, why in (
            (r"#include\s*<thread>", "the std::thread concurrency test include"),
            (r"cv027TrackAllocations", "the thread-local allocation probe"),
            (r"resetCv027AllocationProbe\s*\(\s*\)", "probe start"),
            (r"stopCv027AllocationProbe\s*\(\s*\)", "probe stop"),
            (r"std::thread\s+publisher", "the concurrent publisher thread"),
            (r"processBlock\s*\(\s*buffer\s*,\s*controller\s*\)",
             "a callback driven with a mapped CC while the publisher runs"),
            (r"CorvusFxMidiMapConcurrencyTest", "the concurrency unit test")):
        if not re.search(pattern, tests):
            raise Reject(f"CorvusFxStateTests.cpp is missing {why} — the CV-027 "
                         f"concurrency/allocation regression is not present")

    # ---- (8) CV-083: the callback MIDI loops read raw bytes, never a MidiMessage
    loops = midi_loop_bodies(pb)
    if len(loops) < 2:
        raise Reject("processBlock no longer carries both midiMessages loops — the "
                     "learn capture and the CC apply path must read the raw "
                     "3-byte controller events directly (CV-083)")
    for index, loop in enumerate(loops, start=1):
        where = f"PluginProcessor.cpp:processBlock midiMessages loop {index}"
        if re.search(r"\bgetMessage\s*\(", loop):
            raise Reject(f"{where} calls getMessage() — a MidiMessage owns its "
                         f"storage and can heap-allocate for a long event; read "
                         f"metadata.data[0..2] instead (CV-083)")
        _require(loop, r"metadata\s*\.\s*numBytes\s*!=\s*3\s*\)\s*continue\s*;",
                 where,
                 "the loop no longer skips non-3-byte events before touching them "
                 "— a long event would be examined instead of ignored (CV-083)")
        _require(loop, r"\b(?:metadata\s*\.\s*data|bytes)\s*\[",
                 where,
                 "the loop no longer reads the raw MIDI bytes — the 3-byte "
                 "controller path must come from metadata.data (CV-083)")
        _require(loop, r"0xb0", where,
                 "the loop no longer identifies a controller by its status nibble "
                 "(status & 0xf0 == 0xb0) (CV-083)")

    # ---- (9) CV-094: the instrument render loops dispatch on the raw bytes
    check_instrument(synth)

    return True


def main():
    for required in (CPP, HDR, TESTS, INSTRUMENT):
        if not required.exists():
            fail(f"missing source file {required}")

    cpp_text = CPP.read_text(encoding="utf-8")
    hdr_text = HDR.read_text(encoding="utf-8")
    tests_text = TESTS.read_text(encoding="utf-8")
    synth_text = INSTRUMENT.read_text(encoding="utf-8")

    try:
        check(cpp_text, hdr_text, tests_text, synth_text)
    except Reject as exc:
        fail(str(exc))

    print("cv027: processBlock takes no midiMapLock/ScopedLock, reads no live "
          "midiMap and allocates nothing; the callback try-reads the published "
          "CC→slot view and records a learn in preallocated atomics")
    print("cv027: publishMidiMap/foldPendingMidiLearn keep the map, its lock and "
          "all String work on the message thread")
    print("cv027: the concurrent publisher + allocation-probe regression is "
          "present in CorvusFxStateTests.cpp")
    print("cv027: real tree OK")
    print("cv083: both callback MIDI loops skip non-3-byte events and read "
          "metadata.data[0..2]; no MidiMessage is built on the audio thread")
    print("cv094: both instrument render loops hand host events to "
          "handleMidiMetadata(), which skips every non-2/3-byte and non-channel "
          "event and builds the message inline from metadata.data")

    # ------------------------------------------------------------------
    # Negative probes on in-memory copies of the live tree.
    # ------------------------------------------------------------------
    def probe(label, mutate, why):
        mutated = mutate(cpp_text)
        if mutated == cpp_text:
            fail(f"probe '{label}': NO-OP MUTATION (pattern absent from the live "
                 f"source) — the negative probe is stale")
        try:
            check(mutated, hdr_text, tests_text, synth_text)
        except Reject as exc:
            print(f"cv027 probe '{label}': rejected as expected ({exc})")
            return
        fail(f"probe '{label}' was NOT rejected — {why}")

    REFRESH = r"(\brefreshMidiMapView\s*\(\s*\)\s*;)"
    probe("ScopedLock(midiMapLock) re-added to processBlock",
          lambda t: re.sub(REFRESH,
                           r"const juce::ScopedLock lock(midiMapLock);\n \1",
                           t, count=1),
          "the callback would block on the message-thread lock")
    probe("live midiMap read re-added to processBlock",
          lambda t: re.sub(REFRESH, r"\1\n (void) midiMap;", t, count=1),
          "the callback would race the message-thread map")
    probe("MIDI-map view refresh dropped",
          lambda t: re.sub(REFRESH, "", t, count=1),
          "the callback would never adopt a published map")
    probe("pending learn CC record dropped",
          lambda t: re.sub(
              r"\s*pendingLearnCc\s*\.\s*store\s*\(\s*cc\s*,[^;]*\)\s*;", "",
              t, count=1),
          "the first learn event could never reach the message-thread fold")

    def drop_fold_lock(t):
        return t.replace(
            "        const juce::ScopedLock lock(midiMapLock);\n"
            "        const juce::String& paramID = midiHostNotifySlots",
            "        const juce::String& paramID = midiHostNotifySlots", 1)

    probe("fold lock removed", drop_fold_lock,
          "the fold would mutate the map unsynchronized")
    probe("fold map write removed",
          lambda t: t.replace(
              "            midiMap[cc] = paramID;\n            changed = true;",
              "            changed = true;", 1),
          "a captured learn would never become a mapping")

    def drop_republish(t):
        return t.replace(
            "    if (changed)\n        publishMidiMap();",
            "    if (changed)\n        ;", 1)

    probe("fold republish removed", drop_republish,
          "the audio thread would never see the learned mapping")

    # CV-083: the loops must read the raw bytes, not build a MidiMessage.
    def getmessage_in_apply_loop(t):
        needle = ("            const auto* bytes = metadata.data;\n"
                  "            if ((bytes[0] & 0xf0) != 0xb0)\n"
                  "                continue;")
        return t.replace(
            needle,
            "            auto msg = metadata.getMessage();\n"
            "            if (! msg.isController())\n"
            "                continue;", 1)

    probe("MidiMessage built inside the CC apply loop",
          getmessage_in_apply_loop,
          "a long event would construct a MidiMessage (and may heap-allocate) "
          "inside the render callback")

    def getmessage_in_learn_loop(t):
        needle = ("                if (metadata.numBytes != 3)\n"
                  "                    continue;\n"
                  "                const auto* bytes = metadata.data;\n")
        return t.replace(
            needle,
            "                auto msg = metadata.getMessage();\n"
            "                if (! msg.isController())\n"
            "                    continue;\n"
            "                const auto* bytes = metadata.data;\n", 1)

    probe("MidiMessage built inside the learn-capture loop",
          getmessage_in_learn_loop,
          "a long event would construct a MidiMessage between the numBytes guard "
          "and the controller test")

    def drop_learn_numbytes_guard(t):
        return t.replace(
            "                if (metadata.numBytes != 3)\n"
            "                    continue;\n", "", 1)

    probe("learn-capture 3-byte guard removed", drop_learn_numbytes_guard,
          "a non-controller long event would be examined instead of skipped")

    # CV-094: the instrument render loops must dispatch on raw bytes, not build
    # a MidiMessage from the host event's owned storage.
    def probe_instrument(label, mutate, why):
        mutated = mutate(synth_text)
        if mutated == synth_text:
            fail(f"probe '{label}': NO-OP MUTATION (pattern absent from the live "
                 f"source) — the negative probe is stale")
        try:
            check(cpp_text, hdr_text, tests_text, mutated)
        except Reject as exc:
            print(f"cv094 probe '{label}': rejected as expected ({exc})")
            return
        fail(f"probe '{label}' was NOT rejected — {why}")

    NOTE_LOOP_TAIL = ("            handleMidiMetadata(metadata, parameters);\n"
                      "            renderedUntil = eventPosition;\n"
                      "        }\n"
                      "\n"
                      "        renderSpan(buffer, renderedUntil, ")
    DAWN_LOOP_TAIL = ("            handleMidiMetadata(metadata, parameters);\n"
                      "            renderedUntil = eventPosition;\n"
                      "        }\n"
                      "\n"
                      "        renderDawnSpan(buffer, renderedUntil,")

    def getmessage_in_note_loop(t):
        return t.replace(
            NOTE_LOOP_TAIL,
            "            const auto legacyEvent = metadata.getMessage();\n"
            "            juce::ignoreUnused(legacyEvent);\n" + NOTE_LOOP_TAIL, 1)

    probe_instrument("MidiMessage built inside the instrument render() loop",
                     getmessage_in_note_loop,
                     "a long event would construct a MidiMessage (and may "
                     "heap-allocate) inside the instrument render callback")

    def getmessage_in_dawn_loop(t):
        return t.replace(
            DAWN_LOOP_TAIL,
            "            const auto legacyEvent = metadata.getMessage();\n"
            "            juce::ignoreUnused(legacyEvent);\n" + DAWN_LOOP_TAIL, 1)

    probe_instrument("MidiMessage built inside renderWithDawnActivityGain()",
                     getmessage_in_dawn_loop,
                     "a long event would construct a MidiMessage (and may "
                     "heap-allocate) inside the Dawn render callback")

    def drop_instrument_dispatch(t):
        return t.replace(
            NOTE_LOOP_TAIL,
            "            renderedUntil = eventPosition;\n"
            "        }\n"
            "\n"
            "        renderSpan(buffer, renderedUntil, ", 1)

    probe_instrument("raw-byte dispatcher dropped from a render loop",
                     drop_instrument_dispatch,
                     "the loop would have to build a MidiMessage again, or drop "
                     "host MIDI entirely")

    def drop_instrument_length_guard(t):
        return t.replace(
            "        if (metadata.numBytes < 2 || metadata.numBytes > 3)\n"
            "            return;\n", "", 1)

    probe_instrument("instrument 2/3-byte length guard removed",
                     drop_instrument_length_guard,
                     "a SysEx or meta event would be partly applied instead of "
                     "skipped whole")

    def drop_instrument_channel_guard(t):
        return t.replace(
            "        if (status < 0x80 || status > 0xef)\n"
            "            return;\n", "", 1)

    probe_instrument("instrument channel-status guard removed",
                     drop_instrument_channel_guard,
                     "a system (0xf0..) or malformed event would reach "
                     "handleMidiMessage()")

    # Non-C++ probe surfaces: the header and test pins must also reject drift.
    def probe_text(label, mutate, why):
        mutated = mutate(hdr_text)
        if mutated == hdr_text:
            fail(f"probe '{label}': NO-OP MUTATION — the negative probe is stale")
        try:
            check(cpp_text, mutated, tests_text, synth_text)
        except Reject:
            print(f"cv027 probe '{label}': rejected as expected")
            return
        fail(f"probe '{label}' was NOT rejected — {why}")

    probe_text("published table downgraded to a plain array",
               lambda t: t.replace(
                   "std::array<std::atomic<int>, MAX_MIDI_CCS> publishedMidiCcSlots",
                   "std::array<int, MAX_MIDI_CCS> publishedMidiCcSlots", 1),
               "a plain int table would race the reader")

    # Benign no-op edit outside every pinned shape must still pass.
    benign = cpp_text.replace(
        "// MIDI Learn: apply CC to parameter mappings from MIDI input",
        "// MIDI Learn: apply CC to parameter mappings from MIDI input (CV-027)",
        1)
    if benign == cpp_text:
        fail("benign no-op guard: anchor pattern absent")
    try:
        check(benign, hdr_text, tests_text, synth_text)
    except Reject as exc:
        fail(f"a benign comment edit was REJECTED — the checker over-fires: {exc}")
    print("cv027: benign no-op edit passes (probe specificity proven)")

    # CV-083: a benign comment inside a callback MIDI loop must also pass, so the
    # loop pins fire on structure, not on any text edit near the raw-byte reads.
    benign_loop = cpp_text.replace(
        "            const float normValue = (float) bytes[2] / 127.0f;",
        "            // CV-083: value is the third byte of a 3-byte controller event\n"
        "            const float normValue = (float) bytes[2] / 127.0f;", 1)
    if benign_loop == cpp_text:
        fail("benign loop-comment guard: anchor pattern absent")
    try:
        check(benign_loop, hdr_text, tests_text, synth_text)
    except Reject as exc:
        fail(f"a benign comment inside a MIDI loop was REJECTED — the checker "
             f"over-fires: {exc}")
    print("cv083: benign comment inside a MIDI loop passes (probe specificity proven)")

    # CV-094: a benign comment edit inside an instrument render loop must also
    # pass, so the new pins fire on structure, not on any text near the dispatch.
    benign_synth = synth_text.replace(
        NOTE_LOOP_TAIL,
        "            // CV-094 benign probe: a comment inside the render loop.\n"
        + NOTE_LOOP_TAIL, 1)
    if benign_synth == synth_text:
        fail("benign instrument-comment guard: anchor pattern absent")
    try:
        check(cpp_text, hdr_text, tests_text, benign_synth)
    except Reject as exc:
        fail(f"a benign comment inside an instrument render loop was REJECTED — "
             f"the checker over-fires: {exc}")
    print("cv094: benign comment inside an instrument render loop passes "
          "(probe specificity proven)")

    # Final live re-verification (the real tree was never written to).
    try:
        check(CPP.read_text(encoding="utf-8"), HDR.read_text(encoding="utf-8"),
              TESTS.read_text(encoding="utf-8"),
              INSTRUMENT.read_text(encoding="utf-8"))
    except Reject as exc:
        fail(f"final source re-verification failed: {exc}")
    print("CV-027 OK")


if __name__ == "__main__":
    main()
