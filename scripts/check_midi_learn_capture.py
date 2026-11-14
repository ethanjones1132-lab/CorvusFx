#!/usr/bin/env python3
"""Headless checker: MIDI-learn capture + the CV-027 published-map shape.

The processBlock MIDI path is pinned to the CV-027 lock-free publication:

    header:  std::array<std::atomic<int>, MAX_MIDI_CCS> publishedMidiCcSlots;
             std::atomic<unsigned> midiMapSequence;
             std::array<int, MAX_MIDI_CCS> midiMapView / midiMapScratch;
             std::atomic<int> midiLearnParamSlot / pendingLearnCc /
                              pendingLearnSlot;

    process: refreshMidiMapView();              // try-read, keep last good view
             if (midiLearnActive) { ... midiMapView[cc] steal guard ...
                  pendingLearnCc.store(cc) / pendingLearnSlot.store(slot)
                  midiLearnActive = false; }    // no map node, no String
             ... midiMapView[cc] -> midiHostNotifySlots[slot].param
                  -> stageMidiHostNotify(p, normValue);

    message: foldPendingMidiLearn()  -- midiMapLock + midiMap[cc] = paramID +
             publishMidiMap(); publish brackets the table write with two
             midiMapSequence.fetch_add(1, ...) calls.

Asserts:
  (a) the capture branch still clears midiLearnActive after capturing;
  (b) the captured CC is handed to the message thread through the pending
      atomics — never written into midiMap on the audio thread;
  (c) the capture refuses to steal a CC already mapped to a different slot
      (steal guard through the published view);
  (d) no setValueNotifyingHost and no map growth/allocation token inside
      processBlock;
  (e) the apply path reads the preallocated view and stages through the
      roster slot (no live map, no juce::String, no APVTS lookup);
  (f) the fold takes midiMapLock, installs midiMap[cc] = paramID and
      republishes; the publication brackets its write with the sequence;
  (g) the header declares the fixed-size tables and no `mapSnapshot` member
      (the old lock-scoped refill is gone).

Self-tests (all in memory — the real C++ tree is never written):
  * a positive fixture for the CV-027 shape;
  * rejected fixtures: lock-scoped local snapshot, capture writing midiMap,
    missing flag clear, apply reading the live map, mapSnapshot member,
    unlocked fold, allocation inside processBlock;
  * live-tree probes for every one of those drifts, each rejecting the
    mutation and each failing loudly as NO-OP if its pattern vanished;
  * a benign no-op edit must still pass (probe specificity).

Exit 0 = ok, 1 = violation with line-cited diagnostics.
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
SRC = ROOT / "source" / "DrippyFX"
CPP = SRC / "PluginProcessor.cpp"
HDR = SRC / "PluginProcessor.h"


class Reject(Exception):
    """Structural violation detected in a (real or fixture) source text."""


class StaleProbe(Exception):
    """A self-probe pattern no longer matches text it claims to target."""


def fail(msg) -> NoReturn:
    print(f"MIDI-LEARN-CAPTURE FAIL: {msg}")
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


def class_body(header):
    m = re.search(r"\bclass\s+CorvusFXAudioProcessor\b", header)
    if not m:
        return None
    found = block_at(header, m.end())
    return found[2] if found else None


GROWTH_RE = re.compile(
    r"\w+\s*\.\s*(push_back|resize|insert|assign|emplace|reserve)\s*\(")


def check(raw_cpp, raw_header):
    """Gate one cpp/header pair. Raises Reject on violation."""
    code = strip_comments(raw_cpp)
    header = strip_comments(raw_header)
    pb = method_body(code, "processBlock")
    if pb is None:
        raise Reject("could not locate the PluginProcessor::processBlock body")

    # ---- audio thread: no lock, no live map, no allocation -----------------
    if re.search(r"midiMapLock|ScopedLock", pb):
        raise Reject("processBlock takes a lock — the MIDI map must reach the "
                     "callback through the lock-free published view (CV-027)")
    if re.search(r"\bmidiMap\b", pb):
        raise Reject("processBlock reads the live midiMap — the capture and the "
                     "apply path must use the published view only (CV-027)")
    if "setValueNotifyingHost" in pb:
        raise Reject("processBlock calls setValueNotifyingHost — the capture "
                     "must never jump the parameter (CV-029)")
    growth = GROWTH_RE.search(pb)
    if growth:
        raise Reject(f"processBlock calls .{growth.group(1)}(...) — the callback "
                     f"must not grow or reserve storage (CV-027)")

    # ---- (a)(b)(c) learn capture hand-off --------------------------------
    if "midiLearnActive = false" not in pb:
        raise Reject("capture branch no longer clears midiLearnActive after "
                     "capture — an armed learn would capture every later CC")
    if not re.search(r"pendingLearnCc\s*\.\s*store\s*\(", pb):
        raise Reject("capture branch no longer records the captured CC in "
                     "pendingLearnCc — the message-thread fold has nothing to "
                     "apply (CV-027)")
    if not re.search(r"pendingLearnSlot\s*\.\s*store\s*\(", pb):
        raise Reject("capture branch no longer records the armed roster slot in "
                     "pendingLearnSlot (CV-027)")
    if not re.search(r"midiLearnParamSlot\s*\.\s*load\s*\(", pb):
        raise Reject("capture branch no longer reads the armed atomic slot — it "
                     "must never read the juce::String midiLearnParamID on the "
                     "audio thread (CV-027)")
    if not re.search(r"midiMapView\s*\[\s*\(?\s*size_t\s*\)?\s*cc\s*\]", pb):
        raise Reject("capture/apply path does not look up the CC in midiMapView "
                     "— the refuse-to-steal guard and the mapping lookup must "
                     "use the published view")
    guard = re.search(
        r"midiMapView\s*\[\s*\(?\s*size_t\s*\)?\s*cc\s*\]\s*>=?\s*0"
        r"[\s\S]{0,120}?midiMapView\s*\[\s*\(?\s*size_t\s*\)?\s*cc\s*\]"
        r"\s*!=\s*armedSlot", pb)
    if not guard:
        raise Reject("capture branch does not refuse to steal a CC already "
                     "mapped to a DIFFERENT roster slot (expected a midiMapView "
                     "comparison against armedSlot)")

    # ---- (e) apply path: view -> roster slot -> stage --------------------
    if not re.search(r"stageMidiHostNotify\s*\(", pb):
        raise Reject("the apply path no longer stages the mapped value "
                     "(stageMidiHostNotify)")
    if not re.search(r"midiHostNotifySlots\s*\[[^\]]*\]\s*\.\s*param", pb):
        raise Reject("the apply path no longer resolves the mapped parameter "
                     "through the preallocated roster (midiHostNotifySlots)")

    # ---- (g) header shape ------------------------------------------------
    body = class_body(header) or ""
    if re.search(r"\bmapSnapshot\b", header):
        raise Reject("the header still declares mapSnapshot — the lock-scoped "
                     "refill was replaced by the fixed published table (CV-027)")
    if not re.search(r"MAX_MIDI_CCS\s*=\s*128\b", body):
        raise Reject("the header no longer pins MAX_MIDI_CCS = 128 — the "
                     "published table must cover the full legal CC domain 0..127")
    for pattern, why in (
            (r"std::array\s*<\s*std::atomic\s*<\s*int\s*>\s*,\s*MAX_MIDI_CCS\s*>\s*"
             r"publishedMidiCcSlots", "the published CC→slot table"),
            (r"std::atomic\s*<\s*unsigned\s*>\s*midiMapSequence",
             "the publication sequence counter"),
            (r"std::array\s*<\s*int\s*,\s*MAX_MIDI_CCS\s*>\s*midiMapView",
             "the audio-thread view"),
            (r"std::array\s*<\s*int\s*,\s*MAX_MIDI_CCS\s*>\s*midiMapScratch",
             "the try-read scratch table"),
            (r"std::atomic\s*<\s*int\s*>\s*midiLearnParamSlot",
             "the armed atomic slot"),
            (r"std::atomic\s*<\s*int\s*>\s*pendingLearnCc",
             "the pending learn CC atomic"),
            (r"std::atomic\s*<\s*int\s*>\s*pendingLearnSlot",
             "the pending learn slot atomic")):
        if not re.search(pattern, body):
            raise Reject(f"the header does not declare {why} (CV-027)")

    # ---- (f) message-thread fold + publication ---------------------------
    fold = method_body(code, "foldPendingMidiLearn")
    if fold is None:
        raise Reject("foldPendingMidiLearn body missing — a captured learn "
                     "would never reach the map")
    if "midiMapLock" not in fold:
        raise Reject("foldPendingMidiLearn mutates midiMap without midiMapLock")
    if not re.search(r"midiMap\s*\[\s*cc\s*\]\s*=\s*paramID", fold):
        raise Reject("foldPendingMidiLearn no longer writes midiMap[cc] = "
                     "paramID")
    if not re.search(r"pendingLearnSlot\s*\.\s*exchange\s*\(", fold):
        raise Reject("foldPendingMidiLearn no longer consumes the pending learn "
                     "slot exactly once")
    if not re.search(r"publishMidiMap\s*\(\s*\)", fold):
        raise Reject("foldPendingMidiLearn no longer republishes the map")

    publish = method_body(code, "publishMidiMap")
    if publish is None:
        raise Reject("publishMidiMap body missing")
    if len(re.findall(r"midiMapSequence\s*\.\s*fetch_add\s*\(\s*1", publish)) != 2:
        raise Reject("publishMidiMap does not bracket the table write with two "
                     "sequence increments (odd = unstable, even = stable)")
    if not re.search(r"publishedMidiCcSlots\s*\[[^\]]*\]\s*\.\s*store\s*\(",
                     publish):
        raise Reject("publishMidiMap does not write publishedMidiCcSlots")

    refresh = method_body(code, "refreshMidiMapView")
    if refresh is None:
        raise Reject("refreshMidiMapView body missing — the callback cannot "
                     "adopt a published map")
    if len(re.findall(r"midiMapSequence\s*\.\s*load\s*\(", refresh)) < 2:
        raise Reject("refreshMidiMapView does not verify the sequence around the "
                     "copy — a torn view could be adopted")
    if not re.search(r"midiMapView\s*=\s*midiMapScratch\s*;", refresh):
        raise Reject("refreshMidiMapView never adopts the coherent scratch copy")
    return True


# ---------------------------------------------------------------------------
# Positive fixture for the CV-027 shape
# ---------------------------------------------------------------------------
FIXTURE_HEADER = """#pragma once
class CorvusFXAudioProcessor : public juce::AudioProcessor
{
public:
    void processBlock(juce::AudioBuffer<float>&, juce::MidiBuffer&);
private:
    std::map<int, juce::String> midiMap;
    juce::CriticalSection midiMapLock;
    static constexpr int MAX_MIDI_CCS = 128;
    std::array<std::atomic<int>, MAX_MIDI_CCS> publishedMidiCcSlots {};
    std::atomic<unsigned> midiMapSequence { 0 };
    std::array<int, MAX_MIDI_CCS> midiMapView {};
    std::array<int, MAX_MIDI_CCS> midiMapScratch {};
    std::atomic<int> midiLearnParamSlot { -1 };
    std::atomic<int> pendingLearnCc { -1 };
    std::atomic<int> pendingLearnSlot { -1 };
    std::atomic<bool> midiLearnActive { false };
};
"""

FIXTURE_CPP = """void CorvusFXAudioProcessor::publishMidiMap()
{
    midiMapSequence.fetch_add(1, std::memory_order_acq_rel);
    const juce::ScopedLock lock(midiMapLock);
    for (int cc = 0; cc < MAX_MIDI_CCS; ++cc)
        publishedMidiCcSlots[(size_t) cc].store(-1, std::memory_order_relaxed);
    midiMapSequence.fetch_add(1, std::memory_order_release);
}

void CorvusFXAudioProcessor::refreshMidiMapView()
{
    const unsigned sequence = midiMapSequence.load(std::memory_order_acquire);
    for (int cc = 0; cc < MAX_MIDI_CCS; ++cc)
        midiMapScratch[(size_t) cc] =
            publishedMidiCcSlots[(size_t) cc].load(std::memory_order_relaxed);
    if (midiMapSequence.load(std::memory_order_acquire) != sequence)
        return;
    midiMapView = midiMapScratch;
}

void CorvusFXAudioProcessor::foldPendingMidiLearn()
{
    const int slot = pendingLearnSlot.exchange(-1, std::memory_order_acq_rel);
    const juce::String& paramID = midiHostNotifySlots[(size_t) slot].id;
    const juce::ScopedLock lock(midiMapLock);
    midiMap[cc] = paramID;
    publishMidiMap();
}

void CorvusFXAudioProcessor::processBlock(juce::AudioBuffer<float>&, juce::MidiBuffer& midiMessages)
{
    if (!midiMessages.isEmpty())
    {
        refreshMidiMapView();
        int capturedCc = -1;
        if (midiLearnActive)
        {
            const int armedSlot =
                midiLearnParamSlot.load(std::memory_order_relaxed);
            for (const auto& metadata : midiMessages)
            {
                auto msg = metadata.getMessage();
                if (msg.isController() && capturedCc == -1)
                {
                    const int cc = msg.getControllerNumber();
                    if (armedSlot < 0
                        || (midiMapView[(size_t) cc] >= 0
                            && midiMapView[(size_t) cc] != armedSlot))
                        continue;
                    capturedCc = cc;
                    pendingLearnCc.store(cc, std::memory_order_relaxed);
                    pendingLearnSlot.store(armedSlot, std::memory_order_relaxed);
                    midiLearnActive = false;
                }
            }
        }
        for (const auto& metadata : midiMessages)
        {
            auto msg = metadata.getMessage();
            if (!msg.isController())
                continue;
            const int cc = msg.getControllerNumber();
            if (cc == capturedCc)
                continue;
            const float normValue = msg.getControllerValue() / 127.0f;
            const int slot = midiMapView[(size_t) cc];
            if (slot < 0)
                continue;
            auto* p = midiHostNotifySlots[(size_t) slot].param;
            if (p != nullptr)
                stageMidiHostNotify(p, normValue);
        }
    }
}
"""


def expect_ok(label, cpp_text, hdr_text):
    try:
        check(cpp_text, hdr_text)
    except Reject as exc:
        fail(f"{label}: the accepted shape was REJECTED ({exc})")
    print(f"midi-learn-capture: {label} accepted")


def expect_reject(label, cpp_text, hdr_text):
    try:
        check(cpp_text, hdr_text)
    except Reject:
        print(f"midi-learn-capture: {label} rejected")
        return
    fail(f"{label}: the mutated shape was NOT rejected — the gate is vacuous")


def expect_noop_reject(label, before, after):
    if before == after:
        fail(f"no-op probe ({label}): mutation did not change the source")


def main():
    for required in (CPP, HDR):
        if not required.exists():
            fail(f"missing source file {required}")

    cpp_text = CPP.read_text(encoding="utf-8")
    hdr_text = HDR.read_text(encoding="utf-8")

    # ---- real tree -------------------------------------------------------
    try:
        check(cpp_text, hdr_text)
    except Reject as exc:
        fail(f"real tree: {exc}")
    print("midi-learn-capture: real tree uses the CV-027 published-view shape "
          "(no lock, no map write and no allocation in the callback)")

    # ---- self-tests on the positive fixture ------------------------------
    expect_ok("CV-027 positive fixture", FIXTURE_CPP, FIXTURE_HEADER)

    # ---- rejected fixture shapes ----------------------------------------
    old_lock = FIXTURE_CPP.replace(
        "        refreshMidiMapView();",
        "        const juce::ScopedLock lock(midiMapLock);\n"
        "        refreshMidiMapView();", 1)
    expect_noop_reject("lock-scoped callback", FIXTURE_CPP, old_lock)
    expect_reject("lock-scoped callback", old_lock, FIXTURE_HEADER)

    audio_map_write = FIXTURE_CPP.replace(
        "                    pendingLearnCc.store(cc, std::memory_order_relaxed);",
        "                    midiMap[cc] = midiLearnParamID;", 1)
    expect_noop_reject("map write in callback", FIXTURE_CPP, audio_map_write)
    expect_reject("map write in callback", audio_map_write, FIXTURE_HEADER)

    no_flag_clear = FIXTURE_CPP.replace(
        "                    midiLearnActive = false;", "", 1)
    expect_noop_reject("lost flag clear", FIXTURE_CPP, no_flag_clear)
    expect_reject("lost flag clear", no_flag_clear, FIXTURE_HEADER)

    live_map_apply = FIXTURE_CPP.replace(
        "            const int slot = midiMapView[(size_t) cc];",
        "            const int slot = midiMap[(size_t) cc];", 1)
    expect_noop_reject("live map apply", FIXTURE_CPP, live_map_apply)
    expect_reject("live map apply", live_map_apply, FIXTURE_HEADER)

    no_steal_guard = re.sub(
        r"\s*if \(armedSlot < 0\s*\n\s*\|\| \(midiMapView\[\(size_t\) cc\] >= 0\s*\n"
        r"\s*&& midiMapView\[\(size_t\) cc\] != armedSlot\)\)\s*\n\s*continue;",
        "", FIXTURE_CPP, count=1)
    expect_noop_reject("steal guard removed", FIXTURE_CPP, no_steal_guard)
    expect_reject("steal guard removed", no_steal_guard, FIXTURE_HEADER)

    snapshot_member = FIXTURE_HEADER.replace(
        "    std::map<int, juce::String> midiMap;",
        "    std::map<int, juce::String> midiMap;\n"
        "    std::vector<std::pair<int, juce::String>> mapSnapshot;", 1)
    expect_noop_reject("mapSnapshot member restored", FIXTURE_HEADER,
                       snapshot_member)
    expect_reject("mapSnapshot member restored", FIXTURE_CPP, snapshot_member)

    unlocked_fold = FIXTURE_CPP.replace(
        "    const juce::ScopedLock lock(midiMapLock);\n"
        "    midiMap[cc] = paramID;",
        "    midiMap[cc] = paramID;", 1)
    expect_noop_reject("unlocked fold", FIXTURE_CPP, unlocked_fold)
    expect_reject("unlocked fold", unlocked_fold, FIXTURE_HEADER)

    allocating = FIXTURE_CPP.replace(
        "            const int slot = midiMapView[(size_t) cc];",
        "            mapSnapshot.push_back(cc);\n"
        "            const int slot = midiMapView[(size_t) cc];", 1)
    expect_noop_reject("allocation in processBlock", FIXTURE_CPP, allocating)
    expect_reject("allocation in processBlock", allocating, FIXTURE_HEADER)

    # ---- live-tree negative probes --------------------------------------
    def probe(label, cpp_mut=None, hdr_mut=None):
        new_cpp, new_hdr = cpp_text, hdr_text
        try:
            if cpp_mut:
                new_cpp = cpp_mut(new_cpp)
            if hdr_mut:
                new_hdr = hdr_mut(new_hdr)
        except Exception as exc:  # noqa: BLE001 - probe machinery guard
            raise StaleProbe(f"{label}: {exc}") from exc
        if (new_cpp, new_hdr) == (cpp_text, hdr_text):
            fail(f"probe '{label}': NO-OP MUTATION (pattern absent from the live "
                 f"source) — the negative probe is stale")
        try:
            check(new_cpp, new_hdr)
        except Reject:
            print(f"midi-learn-capture probe '{label}': rejected as expected")
            return
        fail(f"probe '{label}' was NOT rejected — the gate is vacuous")

    REFRESH = r"(\brefreshMidiMapView\s*\(\s*\)\s*;)"
    probe("lock re-added to processBlock",
          cpp_mut=lambda t: re.sub(
              REFRESH, r"const juce::ScopedLock lock(midiMapLock);\n \1", t, 1))
    probe("live midiMap read re-added",
          cpp_mut=lambda t: re.sub(REFRESH, r"\1\n (void) midiMap;", t, 1))
    probe("pending learn CC record dropped",
          cpp_mut=lambda t: re.sub(
              r"\s*pendingLearnCc\s*\.\s*store\s*\(\s*cc\s*,[^;]*\)\s*;", "",
              t, 1))
    probe("flag clear dropped",
          cpp_mut=lambda t: t.replace("                    midiLearnActive = false;",
                                      "", 1))
    probe("fold lock dropped",
          cpp_mut=lambda t: t.replace(
              "        const juce::ScopedLock lock(midiMapLock);\n"
              "        const juce::String& paramID = midiHostNotifySlots",
              "        const juce::String& paramID = midiHostNotifySlots", 1))
    probe("fold map write dropped",
          cpp_mut=lambda t: t.replace(
              "            midiMap[cc] = paramID;\n            changed = true;",
              "            changed = true;", 1))
    probe("mapSnapshot member restored",
          hdr_mut=lambda t: t.replace(
              "    std::map<int, juce::String> midiMap;",
              "    std::map<int, juce::String> midiMap;\n"
              "    std::vector<std::pair<int, juce::String>> mapSnapshot;", 1))

    # ---- benign no-op edit must still pass ------------------------------
    benign = cpp_text.replace("int capturedCc = -1;", "int capturedCc = -1 ;", 1)
    if benign == cpp_text:
        fail("benign no-op guard: anchor pattern absent")
    try:
        check(benign, hdr_text)
    except Reject as exc:
        fail(f"a benign edit was REJECTED — the checker over-fires: {exc}")
    print("midi-learn-capture: benign no-op edit passes (probe specificity proven)")

    # Final live re-verification (the real tree was never written to).
    try:
        check(CPP.read_text(encoding="utf-8"), HDR.read_text(encoding="utf-8"))
    except Reject as exc:
        fail(f"final source re-verification failed: {exc}")
    print("MIDI-LEARN-CAPTURE OK")


if __name__ == "__main__":
    main()
