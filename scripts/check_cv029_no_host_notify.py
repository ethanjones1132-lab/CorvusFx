#!/usr/bin/env python3
"""Headless checker: CV-029 — no host-facing work on the audio thread.

A MIDI CC mapped to a parameter must never make processBlock perform
host-facing work. Before CV-029 the audio-thread CC apply loop called
`p->setValueNotifyingHost(normValue)` directly, so a mapped knob ran an APVTS
listener notification (and, for a CC mapped to the program parameter, a full
loadPreset() undo transaction) inside the render callback.

Asserts on the real tree (comment-stripped, brace-matched bodies):

  (A) audio thread is clean
      * no setValueNotifyingHost / beginChangeGesture / endChangeGesture /
        undoManager / beginNewTransaction / parameterChanged /
        sendValueChangedMessageToListeners / sendParameterGestureChanged
        anywhere between processBlock's opening brace and its matching close;
      * processBlock never calls loadPreset / setCurrentProgram and never calls
        the message-thread drain — so a CC cannot fan out into a whole preset
        change nor notify the host from the audio thread.

  (B) audio-thread mailbox + message-thread drain
      * the header declares a per-parameter pending slot (std::atomic<float>
        value + std::atomic<bool> pending) and both the stage and drain
        methods;
      * stageMidiHostNotify (audio thread) only stores value + a release flag:
        no host call, no allocation, no lock;
      * processBlock stages the mapped CC through stageMidiHostNotify;
      * drainPendingMidiHostNotifications (message thread) consumes each
        pending flag exactly once (`exchange(false, ...)`) and is the only
        place a CC reaches setValueNotifyingHost;
      * the processor owns the message-thread tick (juce::Timer started in the
        constructor, stopped first in the destructor, timerCallback drains), so
        a mapped knob works with the editor closed.

  (C) "preset" is refused at BOTH mapping sites
      * creation: startMidiLearn refuses `paramID == "preset"`, the audio-thread
        learn capture refuses `midiLearnParamID == "preset"`, and
        setStateInformation never restores a `paramID != "preset"` row;
      * application: the processBlock apply path breaks on
        `entry.second == "preset"` before it stages anything.

  (D) semantics preserved
      * the CC value is still `getControllerValue() / 127.0f` (unchanged, so the
        parameter's own rounding is untouched), the mapped parameter id is still
        resolved from the snapshot entry, the learn capture still writes
        `midiMap[cc] = midiLearnParamID` + clears midiLearnActive, and the
        CV-017 snapshot refill is intact.

Negative probes (in memory only — the real tree is never written) mutate the
live texts and must be rejected: host notify / gesture / undo re-added in
processBlock, drain call dropped from the timer, drain notify or one-shot
consume removed, pending flag never published, stage call dropped, and each of
the four "preset" gates removed. A probe whose pattern is absent is reported
as NO-OP and fails the run, so the probes cannot silently go stale.

Exit 0 = ok, 1 = violation with a line-cited diagnostic.
"""
import re
import sys
from pathlib import Path
from typing import NoReturn

# Diagnostics quote source text with non-ASCII arrows; a cp1252 console must not turn a verdict into a crash.
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

ROOT = Path(__file__).resolve().parent.parent
SRC = ROOT / "source" / "DrippyFX"
CPP = SRC / "PluginProcessor.cpp"
HDR = SRC / "PluginProcessor.h"
EDIT = SRC / "PluginEditor.cpp"

STAGE = "stageMidiHostNotify"
DRAIN = "drainPendingMidiHostNotifications"

# Host-facing calls that must never be reachable from a render callback.
AUDIO_THREAD_FORBIDDEN = (
    "setValueNotifyingHost",
    "beginChangeGesture",
    "endChangeGesture",
    "undoManager",
    "beginNewTransaction",
    "sendValueChangedMessageToListeners",
    "sendParameterGestureChanged",
    "parameterChanged",
)

# Preset fan-out: a CC must never change the whole program.
AUDIO_THREAD_FORBIDDEN_PRESET = ("loadPreset", "setCurrentProgram")

ALLOCATION_TOKENS = ("push_back", "emplace", "resize", "reserve",
                     "new ", "malloc", "std::string", "juce::String")


class Reject(Exception):
    """Structural violation detected in a (real or fixture) source text."""


class StaleProbe(Exception):
    """A self-probe pattern no longer matches text it claims to target."""


def fail(msg) -> NoReturn:
    print(f"CV-029 FAIL: {msg}")
    sys.exit(1)


# ---------------------------------------------------------------------------
# Parsing helpers (comment stripping preserves line numbers)
# ---------------------------------------------------------------------------
def strip_comments(text):
    text = re.sub(r"/\*.*?\*/",
                  lambda m: "\n" * m.group(0).count("\n"), text, flags=re.S)
    return re.sub(r"//[^\n]*", "", text)


def line_of(text, pos):
    return text.count("\n", 0, pos) + 1


def brace_body(text, pos):
    """(open, close, body) of the first '{' at/after pos, brace-matched."""
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


def method_body(code, signature):
    """Body of `CorvusFXAudioProcessor::<signature>` (brace-matched)."""
    m = re.search(r"\bCorvusFXAudioProcessor::" + signature + r"\s*\(", code)
    if not m:
        return None
    found = brace_body(code, m.end())
    return found[2] if found else None


def header_method_body(header, name):
    """Body of a method defined inline in the processor header."""
    m = re.search(r"\b" + name + r"\s*\(", header)
    if not m:
        return None
    found = brace_body(header, m.end())
    return found[2] if found else None


def editor_method_body(editor, signature):
    m = re.search(r"\bCorvusFXAudioProcessorEditor::" + signature + r"\s*\(",
                  editor)
    if not m:
        return None
    found = brace_body(editor, m.end())
    return found[2] if found else None


# ---------------------------------------------------------------------------
# The gate
# ---------------------------------------------------------------------------
def _require(body, pattern, where, why, flags=0):
    hit = re.search(pattern, body, flags)
    if not hit:
        raise Reject(f"{where}: {why}")
    return hit


def check(raw_cpp, raw_header, raw_editor):
    """Gate one cpp/header/editor triple. Raises Reject on any violation."""
    code = strip_comments(raw_cpp)
    header = strip_comments(raw_header)
    editor = strip_comments(raw_editor)

    # ---- (A) the audio thread performs no host-facing work ----------------
    pb = method_body(code, "processBlock")
    if pb is None:
        raise Reject("could not locate the PluginProcessor::processBlock body "
                     "(brace-matched) — the audio-thread gate cannot run")
    for token in AUDIO_THREAD_FORBIDDEN:
        hit = re.search(re.escape(token), pb)
        if hit:
            raise Reject(
                f"PluginProcessor.cpp:{line_of(code, code.find(pb) + hit.start())}"
                f" — `{token}` is reachable inside processBlock: host-facing "
                f"work must never run on the audio thread (CV-029)")
    for token in AUDIO_THREAD_FORBIDDEN_PRESET:
        hit = re.search(re.escape(token) + r"\s*\(", pb)
        if hit:
            raise Reject(
                f"PluginProcessor.cpp:{line_of(code, code.find(pb) + hit.start())}"
                f" — processBlock calls `{token}(`: a CC must never fan out into "
                f"a whole preset change on the audio thread (CV-029)")
    if re.search(re.escape(DRAIN) + r"\s*\(", pb):
        raise Reject(
            f"processBlock calls {DRAIN}() — the mailbox drain notifies the "
            f"host and must run on the message thread only (CV-029)")

    # ---- (B) the mailbox and its message-thread drain ---------------------
    slot_decl = re.search(r"struct\s+MidiHostNotifySlot\s*", header)
    slot_body = brace_body(header, slot_decl.end()) if slot_decl else None
    if slot_body is None:
        raise Reject("PluginProcessor.h: the per-parameter pending slot struct "
                     "(MidiHostNotifySlot) is missing — the audio thread needs "
                     "a lock-free value slot to write (CV-029)")
    slot_fields = slot_body[2]
    for pattern, why in (
            (r"std::atomic\s*<\s*float\s*>\s+value",
             "the pending slot has no std::atomic<float> value"),
            (r"std::atomic\s*<\s*bool\s*>\s+pending",
             "the pending slot has no std::atomic<bool> pending flag")):
        if not re.search(pattern, slot_fields):
            raise Reject(f"PluginProcessor.h: MidiHostNotifySlot — {why}; the "
                         f"audio thread could not publish a request without a "
                         f"lock (CV-029)")
    for name in (STAGE, DRAIN):
        if not re.search(r"\b" + name + r"\s*\(", header):
            raise Reject(f"PluginProcessor.h: `{name}` is not declared — the "
                         f"audio-thread stage / message-thread drain pair is "
                         f"incomplete (CV-029)")

    stage = method_body(code, STAGE)
    if stage is None:
        raise Reject(f"PluginProcessor.cpp: the {STAGE} body is missing — the "
                     f"CC apply path cannot record a pending value (CV-029)")
    stage_line = line_of(code, code.find(stage))
    _require(stage, r"value\s*\.\s*store\s*\(",
             f"PluginProcessor.cpp:{stage_line}",
             "the audio-thread stage never stores the requested value")
    _require(stage, r"pending\s*\.\s*store\s*\(\s*true\s*,\s*"
                    r"std::memory_order_release\s*\)",
             f"PluginProcessor.cpp:{stage_line}",
             "the audio-thread stage does not publish the pending flag with a "
             "release store (the drain could read a torn value)")
    if re.search(r"setValueNotifyingHost|beginChangeGesture|endChangeGesture|"
                 r"undoManager", stage):
        raise Reject(f"PluginProcessor.cpp:{stage_line} — the audio-thread "
                     f"stage performs host-facing work; it must only record the "
                     f"newest requested value (CV-029)")
    for token in ALLOCATION_TOKENS:
        if token in stage:
            raise Reject(f"PluginProcessor.cpp:{stage_line} — the audio-thread "
                         f"stage allocates ({token.strip()}); the pending slot "
                         f"must be preallocated (CV-029)")
    if not re.search(r"midiHostNotifySlots", stage):
        raise Reject(f"PluginProcessor.cpp:{stage_line} — the stage no longer "
                     f"writes the preallocated midiHostNotifySlots roster")

    drain = method_body(code, DRAIN)
    if drain is None:
        raise Reject(f"PluginProcessor.cpp: the {DRAIN} body is missing — a "
                     f"staged CC would never reach the host (CV-029)")
    drain_line = line_of(code, code.find(drain))
    _require(drain, r"setValueNotifyingHost",
             f"PluginProcessor.cpp:{drain_line}",
             "the message-thread drain never calls setValueNotifyingHost — the "
             "staged CC value is dropped")
    _require(drain, r"pending\s*\.\s*exchange\s*\(\s*false",
             f"PluginProcessor.cpp:{drain_line}",
             "the drain does not consume each pending flag exactly once "
             "(exchange(false, ...)); a parameter would be notified on every "
             "tick instead of at most once per tick")
    _require(drain, r"midiHostNotifySlots",
             f"PluginProcessor.cpp:{drain_line}",
             "the drain no longer walks the per-parameter pending slots")
    if re.search(r"midiMapLock|ScopedLock", drain):
        raise Reject(f"PluginProcessor.cpp:{drain_line} — the drain takes a "
                     f"lock; the roster is immutable after construction and "
                     f"the drain is message-thread only (CV-029)")

    # the audio-thread apply path must stage through the mailbox
    _require(pb, re.escape(STAGE) + r"\s*\(",
             "PluginProcessor.cpp:processBlock",
             f"the CC apply path no longer stages the mapped value through "
             f"{STAGE}() — it would have to notify the host directly, which is "
             f"exactly the CV-029 bug")

    # the drain must run on a message-thread tick the processor owns: the
    # editor exists only while its window is open, and a DAW plays with it
    # closed, so an editor-only drain silently stops every mapped knob.
    if not re.search(r"\bprivate\s+juce::Timer\b|\bpublic\s+juce::Timer\b",
                     header):
        raise Reject("PluginProcessor.h: CorvusFXAudioProcessor does not "
                     "derive from juce::Timer — the CC mailbox has no "
                     "editor-independent message-thread drain (CV-029)")
    ctor = method_body(code, "CorvusFXAudioProcessor")
    if ctor is None or not re.search(r"\bstartTimerHz\s*\(|\bstartTimer\s*\(",
                                     ctor):
        raise Reject("PluginProcessor.cpp: the constructor never starts the "
                     "processor timer — with the editor closed a staged CC "
                     "would never reach the host (CV-029)")
    dtor = method_body(code, "~CorvusFXAudioProcessor")
    if dtor is None or not re.search(r"\bstopTimer\s*\(\s*\)", dtor):
        raise Reject("PluginProcessor.cpp: the destructor does not stopTimer() "
                     "— the drain could run on a half-destroyed processor "
                     "(CV-029)")
    tick = method_body(code, "timerCallback")
    if tick is None or not re.search(r"\b" + DRAIN + r"\s*\(", tick):
        raise Reject("PluginProcessor.cpp: CorvusFXAudioProcessor::"
                     "timerCallback does not call " + DRAIN + "() — a mapped "
                     "knob would never reach the host (CV-029)")

    # ---- (C) "preset" refused at both mapping sites -----------------------
    arm = header_method_body(header, "startMidiLearn")
    if arm is None:
        raise Reject("PluginProcessor.h: startMidiLearn is missing — the "
                     "MIDI-learn creation site cannot be gated")
    arm_guard = _require(
        arm, r'paramID\s*==\s*"preset"', "PluginProcessor.h:startMidiLearn",
        'startMidiLearn accepts "preset" as a learn target — a CC could then '
        'fan out into a whole preset change (CV-029)')
    if not re.search(r"\breturn\s*;", arm[arm_guard.end():]):
        raise Reject("PluginProcessor.h:startMidiLearn — the \"preset\" check "
                     "does not return early, so the mapping is still created")

    capture_guard = _require(
        pb, r'midiLearnParamID\s*==\s*"preset"',
        "PluginProcessor.cpp:processBlock",
        'the learn capture no longer refuses midiLearnParamID == "preset" — a '
        'CC could be recorded as a program-change mapping')
    capture_write = re.search(r"midiMap\s*\[\s*cc\s*\]\s*=\s*midiLearnParamID",
                              pb)
    if not capture_write:
        raise Reject("PluginProcessor.cpp:processBlock — the learn capture no "
                     'longer writes midiMap[cc] = midiLearnParamID')
    if capture_guard.start() > capture_write.start():
        raise Reject('PluginProcessor.cpp:processBlock — the "preset" refusal '
                     'sits AFTER the midiMap write; the mapping would already '
                     'exist (CV-029)')

    restore = method_body(code, "setStateInformation")
    if restore is None:
        raise Reject("PluginProcessor.cpp: setStateInformation body missing")
    _require(restore, r'paramID\s*!=\s*"preset"',
             "PluginProcessor.cpp:setStateInformation",
             'the MIDI-map restore accepts "preset" mappings — a saved state '
             'could re-arm a CC that fans out into a whole preset change '
             '(CV-029)')

    apply_guard = _require(
        pb, r'second\s*==\s*"preset"', "PluginProcessor.cpp:processBlock",
        'the audio-thread apply path no longer rejects "preset" (CV-029)')
    stage_call = re.search(re.escape(STAGE) + r"\s*\(", pb)
    if apply_guard.start() > stage_call.start():
        raise Reject('PluginProcessor.cpp:processBlock — the apply-path '
                     '"preset" refusal sits AFTER the staging call; the preset '
                     'value would already be staged (CV-029)')

    # ---- (D) existing CC semantics preserved ------------------------------
    _require(pb, r"getControllerValue\s*\(\s*\)\s*/\s*127\.0f",
             "PluginProcessor.cpp:processBlock",
             "the CC → normalised value mapping (getControllerValue() / 127.0f) "
             "changed — the parameter's own rounding must stay untouched")
    _require(pb, r"getParameter\s*\(\s*\w+\s*(?:->|\.)\s*second\s*\)",
             "PluginProcessor.cpp:processBlock",
             "the apply path no longer resolves the mapped parameter id from "
             "the snapshot entry")
    _require(pb, r"midiLearnActive\s*=\s*false",
             "PluginProcessor.cpp:processBlock",
             "the learn capture no longer clears midiLearnActive")
    _require(pb, r"mapSnapshot\s*\.\s*clear\s*\(\s*\)",
             "PluginProcessor.cpp:processBlock",
             "the CV-017 map snapshot refill (mapSnapshot.clear()) is gone")
    _require(pb, r"mapSnapshot\s*\.\s*emplace_back\s*\(",
             "PluginProcessor.cpp:processBlock",
             "the CV-017 map snapshot refill (mapSnapshot.emplace_back) is gone")
    return True


# ---------------------------------------------------------------------------
# Real tree
# ---------------------------------------------------------------------------
for required in (CPP, HDR, EDIT):
    if not required.exists():
        fail(f"missing source file {required}")

cpp_text = CPP.read_text(encoding="utf-8")
hdr_text = HDR.read_text(encoding="utf-8")
edit_text = EDIT.read_text(encoding="utf-8")

try:
    check(cpp_text, hdr_text, edit_text)
except Reject as exc:
    fail(str(exc))

print("cv029: processBlock performs no setValueNotifyingHost / gesture / undo "
      "work (no preset fan-out on the audio thread)")
print("cv029: the CC apply path stages the newest value per parameter; the "
      "editor timer drains it at most once per parameter per tick")
print("cv029: \"preset\" is refused at mapping creation (arm + capture + "
      "restore) and at the audio-thread apply site")
print("cv029: real tree OK")


# ---------------------------------------------------------------------------
# Negative probes against the LIVE tree (in-memory copies only)
# ---------------------------------------------------------------------------
def mutate(text, pattern, repl, label, count=1):
    out, n = re.subn(pattern, repl, text, count=count)
    if n == 0 or out == text:
        raise StaleProbe(label)
    return out


def probe(label, why, cpp_mut=None, hdr_mut=None, editor_mut=None):
    new_cpp, new_hdr, new_edit = cpp_text, hdr_text, edit_text
    try:
        for mut in (cpp_mut or ()):
            new_cpp = mutate(new_cpp, *mut, label=label)
        for mut in (hdr_mut or ()):
            new_hdr = mutate(new_hdr, *mut, label=label)
        for mut in (editor_mut or ()):
            new_edit = mutate(new_edit, *mut, label=label)
    except StaleProbe:
        fail(f"probe '{label}': NO-OP MUTATION (pattern absent from the live "
             f"source) — the negative probe is stale")
    if (new_cpp, new_hdr, new_edit) == (cpp_text, hdr_text, edit_text):
        fail(f"probe '{label}': NO-OP MUTATION — the negative probe is stale")
    try:
        check(new_cpp, new_hdr, new_edit)
    except Reject as exc:
        print(f"cv029 probe '{label}': rejected as expected ({exc})")
        return
    fail(f"probe '{label}' was NOT rejected — {why}")


STAGE_CALL = r"(stageMidiHostNotify\s*\(\s*p\s*,\s*normValue\s*\)\s*;)"

# (A) host-facing work re-introduced on the audio thread
probe("setValueNotifyingHost re-added in processBlock",
      "the audio thread must never notify the host",
      cpp_mut=[(STAGE_CALL, r"\1\n p->setValueNotifyingHost(normValue);")])
probe("beginChangeGesture re-added in processBlock",
      "gestures are host-facing work",
      cpp_mut=[(STAGE_CALL, r"\1\n p->beginChangeGesture();")])
probe("endChangeGesture re-added in processBlock",
      "gestures are host-facing work",
      cpp_mut=[(STAGE_CALL, r"\1\n p->endChangeGesture();")])
probe("undo transaction re-added in processBlock",
      "an undo transaction must never start on the audio thread",
      cpp_mut=[(STAGE_CALL,
                r'\1\n undoManager.beginNewTransaction("CC");')])
probe("loadPreset re-added in processBlock",
      "a CC must never fan out into a whole preset change",
      cpp_mut=[(STAGE_CALL, r"\1\n loadPreset(0);")])
probe("drain called from processBlock",
      "the drain notifies the host and belongs to the message thread",
      cpp_mut=[(STAGE_CALL, r"\1\n drainPendingMidiHostNotifications();")])

# (B) mailbox / drain invariants
probe("processor timer never started",
      "with the editor closed a staged CC would never reach the host",
      cpp_mut=[(r"startTimerHz\s*\(\s*30\s*\)\s*;", "/*probe*/")])
probe("processor timer not stopped in the destructor",
      "the drain could run on a half-destroyed processor",
      cpp_mut=[(r"stopTimer\s*\(\s*\)\s*;", "/*probe*/")])
probe("processor timerCallback no longer drains",
      "a mapped knob would never reach the host",
      cpp_mut=[(r"timerCallback\s*\(\s*\)\s*\{\s*drainPendingMidiHostNotifications"
                r"\s*\(\s*\)\s*;", "timerCallback() { (void) 0;")])
probe("processor no longer derives from juce::Timer",
      "the drain would depend on the editor again",
      hdr_mut=[(r",\s*private\s+juce::Timer", "")])
probe("drain host notification dropped",
      "the drain must forward the staged value to the host",
      cpp_mut=[(r"slot\.param->setValueNotifyingHost\(\s*slot\.value\.load"
                r"\(\s*std::memory_order_relaxed\s*\)\s*\)\s*;", "(void) 0;")])
probe("drain no longer consumes the pending flag once",
      "the parameter would be notified on every tick, not once per tick",
      cpp_mut=[(r"slot\.pending\.exchange\(\s*false\s*,\s*"
                r"std::memory_order_acquire\s*\)",
                "slot.pending.load(std::memory_order_acquire)")])
probe("stage stops publishing the pending flag",
      "a staged value would never be drained",
      cpp_mut=[(r"slot\.pending\.store\(\s*true\s*,\s*"
                r"std::memory_order_release\s*\)\s*;", "(void) 0;")])
probe("stage call dropped from the apply path",
      "the audio thread would have no way to request a host update",
      cpp_mut=[(r"stageMidiHostNotify\s*\(\s*p\s*,\s*normValue\s*\)\s*;",
                "(void) p;")])
probe("pending slot downgraded to a plain float",
      "the audio thread would need a lock to publish a request",
      hdr_mut=[(r"std::atomic<float>\s+value\s*\{\s*0\.0f\s*\}\s*;",
                "float value { 0.0f };")])

# (C) "preset" gates at each mapping site
probe("arm-site preset gate removed",
      "startMidiLearn could arm a program-change CC target",
      hdr_mut=[(r"if\s*\(\s*paramID\s*==\s*\"preset\"\s*\)\s*\n\s*return;\s*",
                "")])
probe("capture-site preset gate removed",
      "the learn capture could record a CC → preset mapping",
      cpp_mut=[(r"if\s*\(\s*midiLearnParamID\s*==\s*\"preset\"\s*\)\s*\n"
                r"\s*continue;\s*", "")])
probe("restore-site preset gate removed",
      "a saved state could re-arm a CC → preset mapping",
      cpp_mut=[(r'paramID\s*!=\s*"preset"\s*&&\s*', "")])
probe("apply-site preset gate removed",
      "a stale CC → preset row could fan out into a program change",
      cpp_mut=[(r'if\s*\(\s*entry\.second\s*==\s*"preset"\s*\)\s*\n\s*break;\s*',
                "")])

# (D) semantics preserved (a stale gate must not pass vacuously)
probe("CC value scaling changed",
      "the cc/127 semantics (and the parameter's own rounding) must survive",
      cpp_mut=[(r"msg\.getControllerValue\(\)\s*/\s*127\.0f",
                "msg.getControllerValue() / 128.0f")])
probe("learn capture no longer clears midiLearnActive",
      "an armed learn would capture every later CC",
      cpp_mut=[(r"midiLearnActive\s*=\s*false\s*;", "midiLearnActive = true;")])

# no-op guard: a benign edit outside every pinned shape must still pass
benign = mutate(cpp_text, r"// MIDI Learn: apply CC to parameter mappings",
                "// MIDI Learn: apply CC to parameter mappings (CV-029)",
                label="benign edit")
try:
    check(benign, hdr_text, edit_text)
except Reject as exc:
    fail(f"a benign comment edit was REJECTED — the checker over-fires: {exc}")
print("cv029: benign no-op edit passes (probe specificity proven)")

# Final live re-verification (the real tree was never written to).
try:
    check(CPP.read_text(encoding="utf-8"), HDR.read_text(encoding="utf-8"),
          EDIT.read_text(encoding="utf-8"))
except Reject as exc:
    fail(f"final source re-verification failed: {exc}")
print("CV-029 OK")
