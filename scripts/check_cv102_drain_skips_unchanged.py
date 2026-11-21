#!/usr/bin/env python3
"""Headless checker: CV-102 — a CC that only repeats the value the parameter
already holds must not notify the host at all.

Before CV-102 every drained CC opened a change gesture, called
setValueNotifyingHost and closed the gesture, whether or not the value moved.
With a hardware controller resting on a knob that is mapped to a parameter, a
DAW in automation-write mode therefore recorded an automation point (and an
undo entry) thirty times a second for a knob that never moved.

Asserts (PluginProcessor.cpp / drainPendingMidiHostNotifications,
comment-stripped and brace-matched):

  (a) after the once-per-tick pending exchange and the null-parameter check,
      and BEFORE the first beginChangeGesture, the drain compares the staged
      value with the value the parameter would report to the host. The staged
      value must be mapped through the parameter's own conversion
      (convertTo0to1 / convertFrom0to1) and its own legal-value rounding
      (snapToLegalValue, the rounding its setValue applies), so a repeat CC
      lands exactly on the value already stored while a CC that reaches a
      different legal value stays a full step away. The comparison is a small
      tolerance window (std::abs(...) <= epsilon, 0 < epsilon <= 1e-3) and the
      guard body is `continue`, so an unchanged CC skips the whole
      gesture/notify block. A raw staged value, a comparison against 0.0f, or
      an exact `==` test does not satisfy this.

  (b) a CC that does move the value still notifies exactly once per tick: the
      drain keeps exactly one setValueNotifyingHost, it still follows a
      beginChangeGesture and is still closed by an endChangeGesture in the
      same iteration, and the drain's gesture pairs stay balanced (CV-042).
      The pending flag is still consumed once with exchange(false, acquire)
      and the null-parameter check still runs before any host call (CV-029 /
      CV-095).

Negative probes (in memory only — the real tree is never written):
  1. delete the comparison (the pre-patch drain) -> rejected;
  2. compare against 0.0f instead of the parameter's report -> rejected;
  3. compare against the staged raw value, without the parameter's own
     conversion/rounding -> rejected;
  4. move the comparison after the notify (notify before comparing) ->
     rejected;
  5. widen the tolerance to 0.5f so a real move is skipped -> rejected;
  6. drop the legal-value rounding (the literal round trip only) -> rejected,
     because a held CC on a coarse knob misses by up to half its legal step
     and would notify forever again.
A probe whose pattern no longer matches is reported as a stale self-probe and
fails the run. Benign edits that keep the comparison first — a comment next to
it, and the two operands of the difference swapped — must still pass.

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

DRAIN = "drainPendingMidiHostNotifications"

CONSUME = (r"pending\s*\.\s*exchange\s*\(\s*false\s*,\s*"
           r"std::memory_order_acquire\s*\)")
NULL_GUARD = (r"if\s*\(\s*slot\s*\.\s*param\s*==\s*nullptr\s*\)\s*"
              r"(?:\{\s*)?continue\s*;")
BEGIN = r"beginChangeGesture\s*\(\s*\)"
END = r"endChangeGesture\s*\(\s*\)"
NOTIFY = r"setValueNotifyingHost\s*\("
GET_VALUE = r"slot\s*\.\s*param\s*->\s*getValue\s*\(\s*\)"
ABS = r"std\s*::\s*abs\s*\("
TO_NORM = r"convertTo0to1\s*\("
FROM_NORM = r"convertFrom0to1\s*\("
SNAP = r"snapToLegalValue\s*\("
# `<= 1.0e-6f`, `<= 0.0001f`, ... — the tolerance half of the comparison.
EPSILON = re.compile(r"(?:<=|<)\s*([0-9]+(?:\.[0-9]*)?"
                     r"(?:[eE][-+]?[0-9]+)?)f?")
EPSILON_MAX = 1.0e-3

# The staged-value round trip in full: conversion + the parameter's rounding.
ROUND_TRIP_DEF = re.compile(
    r"const\s+float\s+\w+\s*=\s*\w+\s*\.\s*convertTo0to1\s*\(\s*"
    r"\w+\s*\.\s*snapToLegalValue\s*\(\s*"
    r"\w+\s*\.\s*convertFrom0to1\s*\(\s*\w+\s*\)\s*\)\s*\)\s*;", re.S)


class Reject(Exception):
    """Structural violation detected in a (real or fixture) source text."""


def fail(msg) -> NoReturn:
    print(f"CV-102 FAIL: {msg}")
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


def method_span(code, signature):
    """(open offset, close offset, body) of CorvusFXAudioProcessor::<name>."""
    m = re.search(r"\bCorvusFXAudioProcessor::" + signature + r"\s*\(", code)
    if not m:
        return None
    found = brace_body(code, m.end())
    if found is None:
        return None
    opening, closing, body = found
    return opening, closing, body


# ---------------------------------------------------------------------------
# The gate
# ---------------------------------------------------------------------------
def drain_scan(code):
    """Locate the CV-102 comparison inside the drain, or raise Reject.

    Returns the region (from the null-parameter check up to the first change
    gesture) plus the absolute offsets the self-probes splice against.
    """
    span = method_span(code, DRAIN)
    if span is None:
        raise Reject(f"PluginProcessor.cpp: the {DRAIN} body is missing "
                     f"(brace-matched) — a staged CC could never reach the host "
                     f"(CV-029)")
    start, _, drain = span
    line = line_of(code, start)

    consume = re.search(CONSUME, drain)
    if consume is None:
        raise Reject(f"PluginProcessor.cpp:{line} — the drain no longer "
                     f"consumes each pending flag exactly once "
                     f"(exchange(false, acquire)); a parameter would be "
                     f"notified every tick (CV-029)")

    guard = re.search(NULL_GUARD, drain)
    if guard is None:
        raise Reject(f"PluginProcessor.cpp:{line} — the drain no longer drops "
                     f"a null slot parameter before the host call")
    if guard.start() < consume.end():
        raise Reject(f"PluginProcessor.cpp:{line} — the null-parameter check "
                     f"no longer follows the once-per-tick pending exchange")

    begins = list(re.finditer(BEGIN, drain))
    ends = list(re.finditer(END, drain))
    notifies = list(re.finditer(NOTIFY, drain))
    if not begins:
        raise Reject(f"PluginProcessor.cpp:{line} — the drain no longer opens "
                     f"a change gesture around its host write (CV-042)")
    if len(begins) != 1:
        raise Reject(f"PluginProcessor.cpp:{line} — the drain opens "
                     f"{len(begins)} change gestures; a drained parameter takes "
                     f"exactly one (CV-042)")
    if not ends:
        raise Reject(f"PluginProcessor.cpp:{line} — the drain never closes the "
                     f"change gesture it opens around its host write (CV-042)")
    # One begin per drained parameter, two ends by design: one after the host
    # write and one in the catch that rethrows, so a throwing host call can
    # never leave the gesture open. CV-042 owns the full pairing invariant;
    # this checker only requires that every path closes what it opened.
    if re.search(r"catch\s*\([^)]*\)\s*\{[^{}]*endChangeGesture\s*\(\s*\)",
                 drain) is None:
        raise Reject(f"PluginProcessor.cpp:{line} — the drain's exception path "
                     f"no longer closes the change gesture before it rethrows; "
                     f"a throwing host write would leave a gesture open "
                     f"(CV-042)")
    if len(notifies) != 1:
        raise Reject(f"PluginProcessor.cpp:{line} — the drain makes "
                     f"{len(notifies)} setValueNotifyingHost writes; a changed "
                     f"CC must notify exactly once per parameter per tick "
                     f"(CV-029/CV-042)")
    notify = notifies[0]
    begin = begins[0]
    if begin.start() > notify.start():
        raise Reject(f"PluginProcessor.cpp:{line} — setValueNotifyingHost no "
                     f"longer follows beginChangeGesture (CV-042)")
    ends_after = [m for m in ends if m.start() > notify.start()]
    if not ends_after:
        raise Reject(f"PluginProcessor.cpp:{line} — the drain's "
                     f"setValueNotifyingHost is not closed by an "
                     f"endChangeGesture in the same iteration (CV-042)")
    closer = ends_after[0]
    if any(begin.end() < m.start() < closer.start() for m in begins[1:]):
        raise Reject(f"PluginProcessor.cpp:{line} — a change gesture opens "
                     f"again before the host write's own gesture closes "
                     f"(CV-042)")

    region = drain[guard.end():begin.start()]
    region_abs = start + guard.end()

    def where(rel):
        return line_of(code, region_abs + rel)

    if re.search(r"\bif\s*\(", region) is None:
        raise Reject(f"PluginProcessor.cpp:{where(0)} — the drain no longer "
                     f"compares the staged CC value with the value the "
                     f"parameter already reports before opening a gesture; a "
                     f"held CC would notify the host every tick and stamp an "
                     f"automation point for a knob that never moved (CV-102)")

    skip = re.search(r"continue\s*;", region)
    if skip is None:
        raise Reject(f"PluginProcessor.cpp:{where(0)} — the comparison does "
                     f"not `continue`; an unchanged CC would still fall "
                     f"through to the gesture/notify block (CV-102)")

    absolute = re.search(ABS, region)
    if absolute is None or absolute.end() > skip.start():
        raise Reject(f"PluginProcessor.cpp:{where(0)} — the comparison has no "
                     f"tolerance window (std::abs(...) <= epsilon) before its "
                     f"`continue`; an exact test would miss the parameter's own "
                     f"rounding (CV-102)")

    report = re.search(GET_VALUE, region)
    if report is None or not (absolute.start() < report.start() < skip.start()):
        raise Reject(f"PluginProcessor.cpp:{where(absolute.start())} — the "
                     f"comparison does not use the value the parameter would "
                     f"report to the host (slot.param->getValue()); comparing "
                     f"against a constant or a raw CC value cannot tell a held "
                     f"CC from a move (CV-102)")

    for pattern, what in ((TO_NORM, "convertTo0to1"),
                          (FROM_NORM, "convertFrom0to1")):
        hit = re.search(pattern, region)
        if hit is None or not (hit.start() < skip.start()):
            raise Reject(f"PluginProcessor.cpp:{where(absolute.start())} — the "
                         f"staged value is not mapped through the parameter's "
                         f"own conversion ({what}); range and skew must be the "
                         f"parameter's, not ours (CV-102)")

    snap = re.search(SNAP, region)
    if snap is None or not (snap.start() < skip.start()):
        raise Reject(f"PluginProcessor.cpp:{where(absolute.start())} — the "
                     f"comparison skips the parameter's own legal-value "
                     f"rounding (snapToLegalValue). A repeat CC on a stepped "
                     f"knob then misses by up to half a legal step, so a held "
                     f"CC would notify the host again on every tick (CV-102)")

    epsilon = EPSILON.search(region, absolute.end())
    if epsilon is None or not (epsilon.start() < skip.start()):
        raise Reject(f"PluginProcessor.cpp:{where(absolute.start())} — the "
                     f"comparison has no small epsilon tolerance "
                     f"(std::abs(...) <= 1e-6f ...); an exact == test cannot "
                     f"absorb float round-trip error (CV-102)")
    try:
        tolerance = float(epsilon.group(1))
    except ValueError:
        tolerance = -1.0
    if not (0.0 < tolerance <= EPSILON_MAX):
        raise Reject(f"PluginProcessor.cpp:{where(epsilon.start())} — the "
                     f"comparison tolerance {epsilon.group(0).strip()} is not a "
                     f"small epsilon: a window at or below zero never skips a "
                     f"held CC, and one wider than {EPSILON_MAX:g} would skip a "
                     f"CC that really moved the value (CV-102)")

    return {"drain": drain, "start": start, "region": region,
            "guard_end": start + guard.end(),
            "region_abs": region_abs,
            "region_end": start + begin.start()}


def check(raw_cpp):
    """Gate the live (or mutated) source text; raises Reject on violation."""
    drain_scan(strip_comments(raw_cpp))


# ---------------------------------------------------------------------------
# Self-probes (in memory only)
# ---------------------------------------------------------------------------
def splice(text, start, end, replacement):
    return text[:start] + replacement + text[end:]


def mutated_or_die(text, pattern, repl, label, flags=re.S):
    new, count = re.subn(pattern, repl, text, flags=flags)
    if count == 0 or new == text:
        fail(f"stale self-probe '{label}' — the pattern no longer matches the "
             f"source, so the probe proves nothing")
    return new


def expect_reject(text, label, why):
    try:
        check(text)
    except Reject as exc:
        print(f"cv102 probe '{label}': rejected as expected ({exc})")
        return
    fail(f"probe '{label}' was NOT rejected — {why}")


def expect_pass(text, label):
    try:
        check(text)
    except Reject as exc:
        fail(f"benign {label} was REJECTED — the checker over-fires: {exc}")
    print(f"cv102: benign {label} passes (probe specificity proven)")


CPP_TEXT = CPP.read_text(encoding="utf-8") if CPP.exists() else None
if CPP_TEXT is None:
    fail(f"missing source file {CPP}")

try:
    check(CPP_TEXT)
except Reject as exc:
    fail(str(exc))
print("cv102: the drain compares the staged CC with the value the parameter "
      "already reports, in the parameter's own units and legal-value rounding, "
      "before it opens a gesture")
print("cv102: an unchanged CC skips the gesture/notify block entirely (no "
      "automation point, no undo entry), and a changed CC still notifies "
      "exactly once per tick inside one matched gesture pair")

STRIPPED = strip_comments(CPP_TEXT)
try:
    live = drain_scan(STRIPPED)
except Reject as exc:
    fail(str(exc))

# (1) pre-patch reconstruction: delete the comparison -> must be rejected.
without = splice(STRIPPED, live["guard_end"], live["region_end"], "")
if without == STRIPPED:
    fail("stale self-probe 'delete-comparison' — the mutation did not apply")
expect_reject(without, "comparison deleted (pre-patch drain)",
              "a held CC would notify the host on every tick again")

# (2) compare against 0.0f instead of the parameter's report -> rejected.
zero = live["region"].replace("slot.param->getValue()", "0.0f")
if zero == live["region"]:
    fail("stale self-probe 'compare-against-zero' — the pattern no longer "
         "matches the comparison")
expect_reject(splice(STRIPPED, live["guard_end"], live["region_end"], zero),
              "compared against 0.0f instead of getValue()",
              "a constant target cannot tell a held CC from a move")

# (3) compare against the staged raw value, without the parameter's own
#     conversion/rounding -> rejected.
raw, count = ROUND_TRIP_DEF.subn(
    "const float stagedWouldReport = stagedNormalised;",
    live["region"])
if count == 0:
    fail("stale self-probe 'compare-against-raw' — the round-trip definition "
         "no longer matches the source")
expect_reject(splice(STRIPPED, live["guard_end"], live["region_end"], raw),
              "compared against the staged raw value",
              "cc/127 in our units ignores the parameter's range and rounding")

# (4) notify before comparing -> rejected.
moved = without
increment = re.search(r"\+\+notified\s*;", moved)
if increment is None:
    fail("stale self-probe 'notify-before-compare' — the ++notified anchor "
         "disappeared")
moved = splice(moved, increment.start(), increment.start(),
               live["region"].strip() + "\n        ")
expect_reject(moved, "comparison moved after the notify",
              "a notify-then-compare order still stamps the host for a held CC")

# (5) widen the tolerance so a real move is skipped -> rejected.
wide = mutated_or_die(live["region"], r"<=\s*[0-9]+\.[0-9]+e-?[0-9]+f",
                      "<= 0.5f", "wide-epsilon")
expect_reject(splice(STRIPPED, live["guard_end"], live["region_end"], wide),
              "tolerance widened to 0.5f",
              "a window that wide would swallow a CC that really moved the "
              "value")

# (6) drop the parameter's legal-value rounding -> rejected.
literal = mutated_or_die(live["region"], r"snapToLegalValue\s*\(",
                         "convertTo0to1(", "no-legal-value-rounding")
expect_reject(splice(STRIPPED, live["guard_end"], live["region_end"], literal),
              "legal-value rounding dropped (literal round trip only)",
              "a held CC on a stepped knob misses by up to half a legal step "
              "and notifies forever again")

# (7) a benign comment next to the comparison must still pass.
expect_pass(mutated_or_die(
    CPP_TEXT, r"\n(\s*)if \(std::abs\(stagedWouldReport",
    r"\n\1// CV-102 probe comment\n\1if (std::abs(stagedWouldReport",
    "benign-comment", flags=0),
    "comment next to the comparison")

# (8) a benign reorder that keeps the comparison first must still pass.
expect_pass(mutated_or_die(
    CPP_TEXT, r"std::abs\(stagedWouldReport - slot\.param->getValue\(\)\)",
    "std::abs(slot.param->getValue() - stagedWouldReport)",
    "benign-reorder", flags=0),
    "comparison operands swapped")

# Final live re-verification (the real tree was never written to).
try:
    check(CPP.read_text(encoding="utf-8"))
except Reject as exc:
    fail(f"final source re-verification failed: {exc}")
print("CV-102 OK")
