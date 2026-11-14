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

Negative probes mutate in-memory copies of the LIVE tree (the real tree is
never written) and must be rejected: a ScopedLock(midiMapLock) re-added to the
callback, a live midiMap read re-added, the view refresh dropped, the pending
learn record dropped, the fold lock removed, the fold map write removed, the
fold republish removed. A probe whose pattern is absent fails as NO-OP, and a
benign comment edit must still pass (probe specificity).

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


def check(raw_cpp, raw_header, raw_tests):
    code = strip_comments(raw_cpp)
    header = strip_comments(raw_header)
    tests = strip_comments(raw_tests)

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

    return True


def main():
    for required in (CPP, HDR, TESTS):
        if not required.exists():
            fail(f"missing source file {required}")

    cpp_text = CPP.read_text(encoding="utf-8")
    hdr_text = HDR.read_text(encoding="utf-8")
    tests_text = TESTS.read_text(encoding="utf-8")

    try:
        check(cpp_text, hdr_text, tests_text)
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

    # ------------------------------------------------------------------
    # Negative probes on in-memory copies of the live tree.
    # ------------------------------------------------------------------
    def probe(label, mutate, why):
        mutated = mutate(cpp_text)
        if mutated == cpp_text:
            fail(f"probe '{label}': NO-OP MUTATION (pattern absent from the live "
                 f"source) — the negative probe is stale")
        try:
            check(mutated, hdr_text, tests_text)
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

    # Non-C++ probe surfaces: the header and test pins must also reject drift.
    def probe_text(label, mutate, why):
        mutated = mutate(hdr_text)
        if mutated == hdr_text:
            fail(f"probe '{label}': NO-OP MUTATION — the negative probe is stale")
        try:
            check(cpp_text, mutated, tests_text)
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
        check(benign, hdr_text, tests_text)
    except Reject as exc:
        fail(f"a benign comment edit was REJECTED — the checker over-fires: {exc}")
    print("cv027: benign no-op edit passes (probe specificity proven)")

    # Final live re-verification (the real tree was never written to).
    try:
        check(CPP.read_text(encoding="utf-8"), HDR.read_text(encoding="utf-8"),
              TESTS.read_text(encoding="utf-8"))
    except Reject as exc:
        fail(f"final source re-verification failed: {exc}")
    print("CV-027 OK")


if __name__ == "__main__":
    main()
