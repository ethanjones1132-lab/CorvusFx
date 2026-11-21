#!/usr/bin/env python3
"""Headless checker: CV-101 - a host session restore cancels any MIDI-learn
hand-off armed by the previous session before the restored session is applied.

Asserts (PluginProcessor.cpp / setStateInformation, comment-stripped and
brace-matched):
  (a) a `stopMidiLearn();` call sits AFTER the CV-089 identity guard's early
      return and BEFORE the first `apvts.replaceState`. The armed learn is live
      processor state (midiLearnActive plus the two pending atomics), not part
      of the saved chunk, so without this a learn armed before the load stays
      armed and the next CC silently becomes a new mapping for the pre-load
      target instead of moving the restored knob.
  (b) pendingLearnCc and pendingLearnSlot are both reset to -1 in that same
      region, so a capture the audio thread staged just before this load cannot
      be folded into the restored session by the 30 Hz drain.
  (c) the cancel is unconditional (no if/else/while/switch/for/return in front
      of it) and the region never writes midiMap: only the armed hand-off is
      cancelled, so the restored `midiMaps` child still survives.

Negative probes (in memory only - the real tree is never written) delete the
whole cancel block, delete just the stopMidiLearn() call, comment the block
out, move it above the CV-089 guards, and move it after apvts.replaceState;
each mutation is applied before the rejection is asserted and each must be
rejected. A probe whose pattern no longer matches is reported as a stale
self-probe and fails the run. A benign comment edit next to the cancel and a
whitespace respelling of `stopMidiLearn()` must still pass.

Exit 0 = ok, 1 = violation with a line-cited diagnostic.
"""
import re
import sys
from pathlib import Path
from typing import NoReturn

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

ROOT = Path(__file__).resolve().parent.parent
SRC = ROOT / "source" / "DrippyFX"
CPP = SRC / "PluginProcessor.cpp"

STOP_LEARN = r"stopMidiLearn\s*\(\s*\)\s*;"
LEARN_CC = r"pendingLearnCc\s*\.\s*store\s*\(\s*-1\s*,"
LEARN_SLOT = r"pendingLearnSlot\s*\.\s*store\s*\(\s*-1\s*,"
REPLACE_STATE = r"apvts\s*\.\s*replaceState\s*\("
# The CV-089 identity guard: product marker attribute + complete parameter
# roster, both ending in the early `return;` that leaves the live session
# untouched.
IDENTITY_GUARD = (r"if\s*\([^{};]*hasAttribute\s*\(\s*stateProductIdAttribute"
                  r"\s*\)[^{};]*stateCarriesEveryParameter\s*\([^{};]*\)"
                  r"\s*\)\s*return\s*;")
GUARD_KEYWORD = r"\b(if|else|while|switch|for|return)\b"
# Writing the map in the cancel region would mean the fix wipes restored
# mappings instead of cancelling only the armed hand-off.
MAP_WRITE = r"\bmidiMap\s*(?:\.\s*clear\s*\(|\[)"


class Reject(Exception):
    """Structural violation detected in a (real or fixture) source text."""


def fail(msg) -> NoReturn:
    print(f"CV-101 FAIL: {msg}")
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


# ---------------------------------------------------------------------------
# The gate
# ---------------------------------------------------------------------------
def restore_point(code):
    """Locate the CV-101 learn cancel inside setStateInformation.

    Returns the cancel block plus absolute offsets, or raises Reject.
    """
    body = method_body(code, "setStateInformation")
    if body is None:
        raise Reject("PluginProcessor.cpp: setStateInformation body is missing "
                     "(brace-matched) - the restore-time learn cancel cannot "
                     "be located (CV-101)")
    base = code.find(body)

    guard = re.search(IDENTITY_GUARD, body, flags=re.S)
    if guard is None:
        raise Reject(f"PluginProcessor.cpp:{line_of(code, base)} - the CV-089 "
                     f"identity guard (product marker + complete parameter "
                     f"roster, ending in an early return) is no longer "
                     f"recognisable; the CV-101 cancel must sit after it")
    guard_abs = base + guard.start()

    replace = re.search(REPLACE_STATE, body)
    if replace is None:
        raise Reject(f"PluginProcessor.cpp:{line_of(code, base)} - "
                     f"setStateInformation no longer calls apvts.replaceState; "
                     f"the restored-session anchor for the CV-101 cancel is "
                     f"gone")

    region_start = guard.end()
    if replace.start() < region_start:
        raise Reject(f"PluginProcessor.cpp:{line_of(code, base + replace.start())}"
                     f" - apvts.replaceState runs before the CV-089 identity "
                     f"guard's early return; the CV-101 cancel region is gone")
    region = body[region_start:replace.start()]
    region_abs = base + region_start

    stop = re.search(STOP_LEARN, region)
    if stop is None:
        raise Reject(f"PluginProcessor.cpp:{line_of(code, region_abs)} - "
                     f"setStateInformation never calls stopMidiLearn() between "
                     f"the CV-089 guards and apvts.replaceState; a learn armed "
                     f"by the previous session stays armed, so the next CC "
                     f"after the load silently maps the pre-load parameter "
                     f"instead of moving the restored knob (CV-101)")
    stop_abs = region_abs + stop.start()

    guard_kw = re.search(GUARD_KEYWORD, region[:stop.start()])
    if guard_kw:
        raise Reject(f"PluginProcessor.cpp:{line_of(code, region_abs + guard_kw.start())}"
                     f" - the CV-101 learn cancel is guarded by "
                     f"`{guard_kw.group(1)}`; every accepted restore must "
                     f"cancel it, including a state that carries no midiMaps "
                     f"child")

    cc = re.search(LEARN_CC, region)
    if cc is None:
        raise Reject(f"PluginProcessor.cpp:{line_of(code, region_abs)} - the "
                     f"CV-101 region no longer resets pendingLearnCc to -1; a "
                     f"capture staged by the audio thread just before the load "
                     f"can still be folded into the restored session (CV-101)")
    slot = re.search(LEARN_SLOT, region)
    if slot is None:
        raise Reject(f"PluginProcessor.cpp:{line_of(code, region_abs)} - the "
                     f"CV-101 region no longer resets pendingLearnSlot to -1; a "
                     f"capture staged by the audio thread just before the load "
                     f"can still be folded into the restored session (CV-101)")

    mapped = re.search(MAP_WRITE, region)
    if mapped:
        raise Reject(f"PluginProcessor.cpp:{line_of(code, region_abs + mapped.start())}"
                     f" - the CV-101 cancel region writes midiMap; only the "
                     f"armed hand-off may be cancelled, the restored midiMaps "
                     f"child must survive the restore")

    cc_end = region.find(";", cc.end())
    slot_end = region.find(";", slot.end())
    if cc_end == -1 or slot_end == -1:
        raise Reject(f"PluginProcessor.cpp:{line_of(code, region_abs)} - the "
                     f"CV-101 pending-learn resets are not complete "
                     f"statements; the cancel block cannot be delimited")
    block_start = stop.start()
    block_end = max(cc_end, slot_end) + 1

    return {"body": body, "base": base,
            "guard_abs": guard_abs,
            "region_abs": region_abs,
            "replace_abs": base + replace.start(),
            "stop_abs": stop_abs, "stop_len": stop.end() - stop.start(),
            "block_abs": region_abs + block_start,
            "block_len": block_end - block_start,
            "block_text": region[block_start:block_end]}


def _verify(code):
    """Gate one comment-stripped source text. Raises Reject on violation."""
    restore_point(code)
    body = method_body(code, "setStateInformation")
    if 'getChildByName("midiMaps")' not in body:
        raise Reject(f"PluginProcessor.cpp:{line_of(code, code.find(body))} - "
                     f"setStateInformation no longer restores the midiMaps "
                     f"child; the CV-101 cancel must not replace the mapping "
                     f"restore")


def check(raw_cpp):
    """Gate the live (or mutated) source text; raises Reject on violation."""
    _verify(strip_comments(raw_cpp))


# ---------------------------------------------------------------------------
# Self-probes (in memory only)
# ---------------------------------------------------------------------------
def splice(text, start, end, replacement):
    return text[:start] + replacement + text[end:]


def mutated_or_die(text, pattern, repl, label):
    new, count = re.subn(pattern, repl, text, flags=re.S)
    if count == 0 or new == text:
        fail(f"stale self-probe '{label}' - the pattern no longer matches the "
             f"source, so the probe proves nothing")
    return new


def expect_reject(text, label, why):
    try:
        check(text)
    except Reject as exc:
        print(f"cv101 probe '{label}': rejected as expected ({exc})")
        return
    fail(f"probe '{label}' was NOT rejected - {why}")


def expect_pass(text, label):
    try:
        check(text)
    except Reject as exc:
        fail(f"benign {label} was REJECTED - the checker over-fires: {exc}")
    print(f"cv101: benign {label} passes (probe specificity proven)")


CPP_TEXT = CPP.read_text(encoding="utf-8") if CPP.exists() else None
if CPP_TEXT is None:
    fail(f"missing source file {CPP}")

try:
    check(CPP_TEXT)
except Reject as exc:
    fail(str(exc))
print("cv101: setStateInformation cancels the armed MIDI learn and resets both "
      "pending learn atomics after the CV-089 guards and before the first "
      "apvts.replaceState")

stripped = strip_comments(CPP_TEXT)
try:
    live = restore_point(stripped)
except Reject as exc:
    fail(str(exc))

# (1) pre-patch reconstruction: delete the whole cancel block -> rejected.
without = splice(stripped, live["block_abs"],
                 live["block_abs"] + live["block_len"], "")
if without == stripped:
    fail("stale self-probe 'delete-cancel' - the mutation did not apply")
expect_reject(without, "learn cancel deleted (pre-patch reconstruction)",
              "a learn armed before the load would stay armed and capture the "
              "first CC after the restore")

# (2) delete only stopMidiLearn(), leaving the pending resets -> rejected.
no_stop = splice(stripped, live["stop_abs"],
                 live["stop_abs"] + live["stop_len"], "")
if no_stop == stripped:
    fail("stale self-probe 'delete-stop' - the mutation did not apply")
expect_reject(no_stop, "stopMidiLearn() deleted",
              "the pending resets alone do not disarm midiLearnActive, so the "
              "next CC still silently re-maps the pre-load knob")

# (3) comment the whole block out -> comment stripping must still reject it.
commented = splice(stripped, live["block_abs"],
                   live["block_abs"] + live["block_len"],
                   "\n".join("// " + ln
                             for ln in live["block_text"].split("\n")))
if commented == stripped:
    fail("stale self-probe 'comment-out-cancel' - the mutation did not apply")
expect_reject(commented, "learn cancel commented out",
              "commented-out code must not stand in for the cancel")

# (4) move the cancel above the CV-089 guards -> rejected.
above = splice(without, live["guard_abs"], live["guard_abs"],
               live["block_text"] + "\n")
if above == without:
    fail("stale self-probe 'move-above-guards' - the mutation did not apply")
expect_reject(above, "learn cancel moved above the CV-089 guards",
              "a foreign or partial chunk would cancel the restore and the "
              "cancel must belong to an accepted restore only")

# (5) move the cancel after apvts.replaceState -> rejected.
after = without
after_replace = live["replace_abs"] - live["block_len"]
semi = after.find(";", after_replace)
if semi == -1 or semi < after_replace:
    fail("stale self-probe 'move-after-restore' - the replaceState statement "
         "anchor disappeared")
after = splice(after, semi + 1, semi + 1, "\n" + live["block_text"])
expect_reject(after, "learn cancel moved after apvts.replaceState",
              "the restore would already have rewritten the session while the "
              "learn was still armed")

# (6) a benign comment edit next to the cancel must still pass.
expect_pass(mutated_or_die(CPP_TEXT, r"// CV-101:",
                           "// CV-101 benign probe:", "benign-comment"),
            "comment edit next to the learn cancel")

# (7) a benign whitespace respelling of the cancel must still pass.
expect_pass(mutated_or_die(CPP_TEXT, STOP_LEARN, "stopMidiLearn ( ) ;",
                           "benign-whitespace"),
            "stopMidiLearn() whitespace respelling")

# Final live re-verification (the real tree was never written to).
try:
    check(CPP.read_text(encoding="utf-8"))
except Reject as exc:
    fail(f"final source re-verification failed: {exc}")
print("CV-101 OK")
