#!/usr/bin/env python3
"""Headless checker: CV-100 — a preset load, Randomize or A/B recall clears
every slot's staged CC before it rewrites parameters.

Asserts (PluginProcessor.cpp, comment-stripped and brace-matched):
  (a) one helper, clearPendingMidiHostNotifications(SlotArray&, int), walks the
      roster for `count` slots and stores `false` into every slot's `pending`
      flag with a relaxed store. Only that flag is written: no `.param =`, no
      `.id =`, no `.value.store(...)`, no allocation, so the roster, its
      parameter pointers and its last values survive a recall untouched —
      exactly what the CV-095 restore loop does today.
  (b) loadPreset, randomizePreset, loadSlotA and loadSlotB each call that
      helper with the live roster (midiHostNotifySlots, numMidiHostNotifySlots),
      as a direct (depth-1) statement of the function body and BEFORE that
      function constructs its ParameterGenerationBatch. A CC the audio thread
      staged in the render block that was still open when the recall arrived
      is otherwise drained AFTER the recall rewrote the parameter: the host
      records a spurious setValueNotifyingHost write and the knob snaps back to
      the pre-recall value (the FL Studio bug this ticket closes).
  (c) the helper is defined before its first use — it is an anonymous-namespace
      template, so a call above the definition would not compile.
  (d) every ParameterGenerationBatch in the file belongs to one of the five
      known rewrite paths: the four recalls above plus setStateInformation,
      which keeps its own CV-095 restore-point clear (a restore must clear
      AFTER apvts.replaceState, so it is deliberately not converted to the
      helper). A new batch-opening path without a mailbox clear fails here
      instead of shipping a recall that can republish a stale CC.

Negative probes (in memory only — the real tree is never written) reconstruct
the pre-patch source by deleting one call site (loadSlotB), moving one call
after the batch is constructed (loadPreset), emptying the helper body, and
wrapping one call in a nested block; each mutation must be applied before the
rejection is asserted, and each must be rejected. A probe whose pattern no
longer matches is reported as a stale self-probe and fails the run. Benign
edits — a comment reworded next to a call, the clear call wrapped onto two
lines, and a loop-variable rename inside the helper — must still pass.

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

HELPER = "clearPendingMidiHostNotifications"
RECALLS = ("loadPreset", "randomizePreset", "loadSlotA", "loadSlotB")
RESTORE = "setStateInformation"
BATCH = r"ParameterGenerationBatch\s+batch\s*\(\s*presetBatchSequence\s*\)\s*;"
DEF = re.compile(r"\b" + HELPER + r"\s*\(([^)]*)\)[^;{}]*\{")
CALL = re.compile(r"\b" + HELPER + r"\s*\(\s*midiHostNotifySlots\s*,\s*"
                  r"numMidiHostNotifySlots\s*\)\s*;")
CALL_ANY = re.compile(r"\b" + HELPER + r"\s*\(")
LOOP_HEADER = r"for\s*\([^{}]*\)\s*\{"
ROSTER_STORE = (r"\]\s*\.\s*pending\s*\.\s*(?:store|exchange)\s*\(\s*false")
SLOT_MUTATION = (r"\.\s*(?:param|id|value)\s*=(?!=)"
                 r"|\.\s*value\s*\.\s*(?:store|exchange)")
SLOT_ALLOCATION = ("push_back", "emplace", "resize", "reserve", "malloc",
                   "calloc", "realloc", "free(", "new ", "delete ")
RESTORE_CLEAR_LOOP = r"for\s*\([^{}]*numMidiHostNotifySlots[^{}]*\)\s*\{"


class Reject(Exception):
    """Structural violation detected in a (real or fixture) source text."""


def fail(msg) -> NoReturn:
    print(f"CV-100 FAIL: {msg}")
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


def brace_depth(text, pos):
    """Nesting depth at pos, ignoring braces inside string/char literals."""
    depth = 0
    i = 0
    while i < pos:
        ch = text[i]
        if ch in "\"'":
            quote = ch
            i += 1
            while i < pos and text[i] != quote:
                if text[i] == "\\":
                    i += 1
                i += 1
        elif ch == "{":
            depth += 1
        elif ch == "}":
            depth -= 1
        i += 1
    return depth


def method_span(code, signature):
    """(offset of '{', body) of `CorvusFXAudioProcessor::<signature>`."""
    m = re.search(r"\bCorvusFXAudioProcessor::" + signature + r"\s*\(", code)
    if not m:
        return None
    found = brace_body(code, m.end())
    return (found[0], found[2]) if found else None


# ---------------------------------------------------------------------------
# The gate
# ---------------------------------------------------------------------------
def helper_gate(code):
    """Locate and validate the CV-100 mailbox-clear helper."""
    defs = list(DEF.finditer(code))
    if not defs:
        raise Reject(f"PluginProcessor.cpp: the {HELPER} definition is "
                     f"missing — no recall path can drop a CC staged by the "
                     f"render block that was open when it arrived (CV-100)")
    if len(defs) > 1:
        raise Reject(f"PluginProcessor.cpp:{line_of(code, defs[1].start())} — "
                     f"{HELPER} is defined more than once; every recall must "
                     f"clear through the same helper (CV-100)")
    d = defs[0]
    found = brace_body(code, d.start())
    if found is None:
        raise Reject(f"PluginProcessor.cpp:{line_of(code, d.start())} — the "
                     f"{HELPER} body is not brace-balanced")
    open_at, close_at, body = found

    loop_m = re.search(LOOP_HEADER, body)
    if loop_m is None:
        raise Reject(f"PluginProcessor.cpp:{line_of(code, open_at)} — "
                     f"{HELPER} no longer walks the roster in a loop, so only "
                     f"one slot's pending flag could ever be cleared (CV-100)")
    loop_found = brace_body(body, loop_m.start())
    if loop_found is None:
        raise Reject(f"PluginProcessor.cpp:"
                     f"{line_of(code, open_at + loop_m.start())} — the "
                     f"{HELPER} loop is not brace-balanced")
    loop = body[loop_m.start():loop_found[1]]
    loop_line = line_of(code, open_at + loop_m.start())

    header = loop[:loop.find("{")]
    if "count" not in header and "numMidiHostNotifySlots" not in header:
        raise Reject(f"PluginProcessor.cpp:{loop_line} — the {HELPER} loop is "
                     f"not bounded by the roster size (count / "
                     f"numMidiHostNotifySlots), so it does not clear every "
                     f"slot (CV-100)")
    if not re.search(ROSTER_STORE, loop):
        raise Reject(f"PluginProcessor.cpp:{loop_line} — the loop walks the "
                     f"roster but never stores false into a slot's pending "
                     f"flag; a CC staged before the recall still republishes "
                     f"its old value after it (CV-100)")
    mutated = re.search(SLOT_MUTATION, loop)
    if mutated:
        raise Reject(f"PluginProcessor.cpp:"
                     f"{line_of(code, open_at + loop_m.start() + mutated.start())}"
                     f" — {HELPER} also rewrites a slot's identity/value "
                     f"field; a recall must only drop the pending flag and "
                     f"leave the constructor-built roster intact (CV-100)")
    for token in SLOT_ALLOCATION:
        if token in loop:
            raise Reject(f"PluginProcessor.cpp:{loop_line} — {HELPER} touches "
                         f"`{token.strip()}`; the roster is preallocated and "
                         f"must never be freed, reallocated or grown by a "
                         f"recall (CV-100)")

    return {"start": d.start(), "open": open_at, "end": close_at,
            "body": body, "loop": loop}


def recall_gate(code, fn, helper):
    """Require the CV-100 clear at the top of one recall path."""
    span = method_span(code, fn)
    if span is None:
        raise Reject(f"PluginProcessor.cpp: the {fn} body is missing "
                     f"(brace-matched) — the CV-100 clear cannot be located")
    base, body = span

    batch = re.search(BATCH, body)
    if batch is None:
        raise Reject(f"PluginProcessor.cpp:{line_of(code, base)} — {fn} no "
                     f"longer constructs a ParameterGenerationBatch; its rewrite "
                     f"anchor is gone and the CV-100 clear has nothing to "
                     f"precede (CV-028)")
    batch_at = base + batch.start()

    calls = list(CALL.finditer(body))
    if not calls:
        if CALL_ANY.search(body):
            raise Reject(f"PluginProcessor.cpp:{line_of(code, base)} — {fn} "
                         f"calls {HELPER} with something other than the live "
                         f"roster (midiHostNotifySlots, "
                         f"numMidiHostNotifySlots); a recall must clear the "
                         f"mailbox it stages into (CV-100)")
        raise Reject(f"PluginProcessor.cpp:{line_of(code, base)} — {fn} "
                     f"rewrites parameters without clearing the staged CC "
                     f"mailbox: a CC the previous render block staged is still "
                     f"armed, the drain republishes the OLD value after the "
                     f"recall and the host records a spurious automation write "
                     f"(the knob snap-back, CV-100)")

    first = calls[0]
    call_at = base + first.start()
    call_line = line_of(code, call_at)
    if call_at < helper["start"]:
        raise Reject(f"PluginProcessor.cpp:{call_line} — {fn} calls {HELPER} "
                     f"above its definition; the helper is an "
                     f"anonymous-namespace template, so this does not compile")
    if not first.start() < batch.start():
        raise Reject(f"PluginProcessor.cpp:{call_line} — {fn} clears the "
                     f"mailbox AFTER its ParameterGenerationBatch is "
                     f"constructed; the batch opens while the previous block's "
                     f"CC is still armed (CV-100)")
    depth = brace_depth(body, first.start())
    if depth != 1:
        raise Reject(f"PluginProcessor.cpp:{call_line} — the CV-100 clear in "
                     f"{fn} is not a direct statement of the function body "
                     f"(brace depth {depth}); a guarded clear leaves at least "
                     f"one recall republishing a stale CC (CV-100)")

    return {"base": base, "call": call_at,
            "stmt_end": call_at + len(first.group(0)), "batch": batch_at}


def batch_sites(code):
    """(owner function, offset) for every ParameterGenerationBatch."""
    spans = {fn: method_span(code, fn) for fn in RECALLS + (RESTORE,)}
    sites = []
    for m in re.finditer(BATCH, code):
        owner = None
        for fn, span in spans.items():
            if span and span[0] <= m.start() < span[0] + len(span[1]):
                owner = fn
                break
        sites.append((owner, m.start()))
    return sites


def _verify(code):
    """Gate one comment-stripped source text. Raises Reject on violation."""
    helper = helper_gate(code)
    sites = {fn: recall_gate(code, fn, helper) for fn in RECALLS}

    for owner, pos in batch_sites(code):
        if owner is None:
            raise Reject(f"PluginProcessor.cpp:{line_of(code, pos)} — this "
                         f"ParameterGenerationBatch is not in one of the four "
                         f"recall paths or setStateInformation: a new rewrite "
                         f"path must clear the staged CC mailbox first, or it "
                         f"can republish an old CC value (CV-100)")

    restore = method_span(code, RESTORE)
    if restore is None:
        raise Reject(f"PluginProcessor.cpp: the {RESTORE} body is missing — "
                     f"the restore path's own mailbox clear (CV-095) cannot be "
                     f"located")
    if not re.search(RESTORE_CLEAR_LOOP, restore[1]):
        raise Reject(f"PluginProcessor.cpp:{line_of(code, restore[0])} — "
                     f"{RESTORE} keeps its own restore-point mailbox clear "
                     f"(CV-095) rather than calling the CV-100 helper; that "
                     f"loop is gone, so a restore can drain the previous "
                     f"session's staged CC into a freshly restored parameter")

    return {"helper": helper, "sites": sites}


def check(raw_cpp):
    """Gate the live (or mutated) source text; raises Reject on violation."""
    return _verify(strip_comments(raw_cpp))


# ---------------------------------------------------------------------------
# Self-probes (in memory only)
# ---------------------------------------------------------------------------
def splice(text, start, end, replacement):
    return text[:start] + replacement + text[end:]


def mutated_or_die(text, pattern, repl, label):
    new, count = re.subn(pattern, repl, text, flags=re.S)
    if count == 0 or new == text:
        fail(f"stale self-probe '{label}' — the pattern no longer matches the "
             f"source, so the probe proves nothing")
    return new


def expect_reject(text, label, why):
    try:
        check(text)
    except Reject as exc:
        print(f"cv100 probe '{label}': rejected as expected ({exc})")
        return
    fail(f"probe '{label}' was NOT rejected — {why}")


def expect_pass(text, label):
    try:
        check(text)
    except Reject as exc:
        fail(f"benign {label} was REJECTED — the checker over-fires: {exc}")
    print(f"cv100: benign {label} passes (probe specificity proven)")


CPP_TEXT = CPP.read_text(encoding="utf-8") if CPP.exists() else None
if CPP_TEXT is None:
    fail(f"missing source file {CPP}")

stripped = strip_comments(CPP_TEXT)
try:
    live = _verify(stripped)
except Reject as exc:
    fail(str(exc))

helper = live["helper"]
sites = live["sites"]
print(f"cv100: {HELPER} (PluginProcessor.cpp:"
      f"{line_of(stripped, helper['start'])}) clears every roster slot's "
      f"pending flag and leaves the roster, its pointers and its last values "
      f"untouched")
for fn in RECALLS:
    print(f"cv100: {fn} clears the mailbox at PluginProcessor.cpp:"
          f"{line_of(stripped, sites[fn]['call'])} before its "
          f"ParameterGenerationBatch")
print(f"cv100: {RESTORE} keeps its CV-095 restore-point clear, and no other "
      f"ParameterGenerationBatch exists in the file")

# (1) the pre-patch shape: one call site deleted -> must be rejected.
site_b = sites["loadSlotB"]
without_b = splice(stripped, site_b["call"], site_b["stmt_end"], "")
if without_b == stripped:
    fail("stale self-probe 'delete-call' — the mutation did not apply")
expect_reject(without_b, "loadSlotB call site deleted (pre-patch)",
              "a CC staged before the A/B recall would republish its old value "
              "after the snapshot was restored")

# (2) one call moved after the batch opens -> must be rejected.
site_p = sites["loadPreset"]
statement = stripped[site_p["call"]:site_p["stmt_end"]]
without_p = splice(stripped, site_p["call"], site_p["stmt_end"], "")
if without_p == stripped:
    fail("stale self-probe 'move-call' — the mutation did not apply")
moved_span = method_span(without_p, "loadPreset")
if moved_span is None:
    fail("stale self-probe 'move-call' — the loadPreset body disappeared")
moved_batch = re.search(BATCH, moved_span[1])
if moved_batch is None:
    fail("stale self-probe 'move-call' — the batch anchor disappeared")
insert_at = moved_span[0] + moved_batch.end()
moved = splice(without_p, insert_at, insert_at, "\n    " + statement)
expect_reject(moved, "loadPreset call moved after the batch opens",
              "the batch would commit with the previous block's CC still armed")

# (3) the helper emptied -> must be rejected.
emptied = splice(stripped, helper["open"], helper["end"], "{}")
if emptied == stripped:
    fail("stale self-probe 'empty-helper' — the mutation did not apply")
expect_reject(emptied, "helper body emptied",
              "no pending flag would be cleared, so every recall could "
              "republish a stale CC")

# (4) one call wrapped in a nested block -> must be rejected as guarded.
site_a = sites["loadSlotA"]
slot_stmt = stripped[site_a["call"]:site_a["stmt_end"]]
guarded = splice(stripped, site_a["call"], site_a["stmt_end"],
                 "{\n        " + slot_stmt + "\n    }")
if guarded == stripped:
    fail("stale self-probe 'guarded-call' — the mutation did not apply")
expect_reject(guarded, "loadSlotA clear wrapped in a nested block",
              "a conditional clear leaves at least one recall republishing a "
              "stale CC")

# (5) a benign comment edit next to the loadPreset clear must still pass.
expect_pass(mutated_or_die(CPP_TEXT, r"// CV-100: drop any CC staged",
                           "// CV-100: drop any CC staged (reworded)",
                           "benign-comment"),
            "comment reworded next to the loadPreset clear")

# (6) a benign reformat of the call onto two lines must still pass.
expect_pass(mutated_or_die(
    stripped,
    r"clearPendingMidiHostNotifications\(midiHostNotifySlots,\s*"
    r"numMidiHostNotifySlots\);",
    "clearPendingMidiHostNotifications(\n        midiHostNotifySlots, "
    "numMidiHostNotifySlots);",
    "benign-call-reformat"),
    "clear call wrapped onto two lines")

# (7) a benign loop-variable rename inside the helper must still pass.
renamed = (helper["body"].replace("int i = 0", "int slotIndex = 0")
                         .replace("i < count", "slotIndex < count")
                         .replace("++i", "++slotIndex")
                         .replace("(i)", "(slotIndex)"))
if renamed == helper["body"]:
    fail("stale self-probe 'benign-helper-rename' — the helper body no longer "
         "matches")
expect_pass(splice(stripped, helper["open"], helper["end"], renamed),
            "helper loop-variable rename")

# Final live re-verification (the real tree was never written to).
try:
    check(CPP.read_text(encoding="utf-8"))
except Reject as exc:
    fail(f"final source re-verification failed: {exc}")
print("CV-100 OK")
