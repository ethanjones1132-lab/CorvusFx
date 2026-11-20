#!/usr/bin/env python3
"""Headless checker: CV-095 — a state restore leaves no MIDI-derived host
notification in flight from the previous session.

Asserts (PluginProcessor.cpp / setStateInformation, comment-stripped and
brace-matched):
  (a) at the restore point — between the pendingLearnCc/pendingLearnSlot clear
      and the publishMidiMap() that follows it — every mailbox slot's `pending`
      flag is cleared by an unconditional loop over numMidiHostNotifySlots that
      writes midiHostNotifySlots[...].pending = false. Without it, a CC the
      previous session's audio thread staged but the message-thread timer had
      not yet drained can fire setValueNotifyingHost after the restore and
      rewrite a freshly restored parameter.
  (b) the clear runs unconditionally (no if/else/while/switch/return guard in
      front of the loop), sits BEFORE publishMidiMap(), and comes AFTER
      apvts.replaceState, so the rebuilt table is published with an already
      empty mailbox and the cleared mailbox belongs to the restored session.
  (c) the slots' identity/value fields are left alone by that loop: no
      `slot.param =`, no `.id =`, no `.value.store(...)`, and no
      allocation/free/resize, so the roster is never freed or reallocated by a
      restore.
  (d) the drain contract is intact (CV-029): drainPendingMidiHostNotifications
      still walks midiHostNotifySlots and consumes each flag with
      exchange(false, acquire) and still calls setValueNotifyingHost, and
      stageMidiHostNotify still publishes with store(true, release). An
      ordinary CC after the restore therefore still notifies the host exactly
      once per drain tick.

Negative probes (in memory only — the real tree is never written) reconstruct
the pre-patch source by deleting the clear, and separately comment it out,
move it after publishMidiMap(), wrap it in an `if`, and break the drain's
one-shot consume; each mutation must be applied before the rejection is
asserted, and each must be rejected. A probe whose pattern no longer matches is
reported as a stale self-probe and fails the run. A benign edit inside the clear
(loop variable rename) and inside the drain (increment spelling) must still
pass.

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
STAGE = "stageMidiHostNotify"

LEARN_CC = r"pendingLearnCc\s*\.\s*store\s*\(\s*-1\s*,"
LEARN_SLOT = r"pendingLearnSlot\s*\.\s*store\s*\(\s*-1\s*,"
PUBLISH = r"publishMidiMap\s*\(\s*\)\s*;"
REPLACE_STATE = r"apvts\s*\.\s*replaceState\s*\("
LOOP_HEADER = r"for\s*\([^{}]*numMidiHostNotifySlots[^{}]*\)\s*\{"
MAILBOX_CLEAR = (r"midiHostNotifySlots\s*\[[^\]]*\]\s*\.\s*pending\s*\.\s*"
                 r"(?:store|exchange)\s*\(\s*false")
SLOT_MUTATION = (r"\.\s*(?:param|id|value)\s*=(?!=)"
                 r"|\.\s*value\s*\.\s*(?:store|exchange)")
SLOT_ALLOCATION = ("push_back", "emplace", "resize", "reserve", "malloc",
                   "calloc", "realloc", "free(", "new ", "delete ")


class Reject(Exception):
    """Structural violation detected in a (real or fixture) source text."""


def fail(msg) -> NoReturn:
    print(f"CV-095 FAIL: {msg}")
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
    """Locate the CV-095 clear inside setStateInformation.

    Returns a dict with the loop text plus absolute offsets, or raises Reject.
    """
    body = method_body(code, "setStateInformation")
    if body is None:
        raise Reject("PluginProcessor.cpp: setStateInformation body is missing "
                     "(brace-matched) — the restore-time mailbox clear cannot "
                     "be located (CV-095)")
    base = code.find(body)

    if not re.search(LEARN_CC, body):
        raise Reject(f"PluginProcessor.cpp:{line_of(code, base)} — "
                     f"setStateInformation no longer clears pendingLearnCc; the "
                     f"CV-095 clear must sit at the same restore point as the "
                     f"CV-027 learn clear")

    clears = list(re.finditer(LEARN_SLOT, body))
    if not clears:
        raise Reject(f"PluginProcessor.cpp:{line_of(code, base)} — "
                     f"setStateInformation no longer clears pendingLearnSlot; "
                     f"the CV-095 clear must sit at the same restore point as "
                     f"the CV-027 learn clear")
    learn = clears[-1]

    pub = re.compile(PUBLISH).search(body, learn.end())
    if pub is None:
        raise Reject(f"PluginProcessor.cpp:"
                     f"{line_of(code, base + learn.end())} — "
                     f"setStateInformation no longer calls publishMidiMap() "
                     f"after the learn clear; the rebuilt table would never be "
                     f"adopted and the mailbox clear has no anchor")

    segment = body[learn.end():pub.start()]
    segment_start = base + learn.end()

    m = re.search(LOOP_HEADER, segment)
    if m is None:
        raise Reject(f"PluginProcessor.cpp:"
                     f"{line_of(code, segment_start)} — the restore point "
                     f"between the pendingLearnSlot clear and publishMidiMap() "
                     f"does not clear the midiHostNotifySlots mailbox: a CC the "
                     f"previous session's audio thread staged can still be "
                     f"drained after the restore and rewrite a freshly restored "
                     f"parameter (CV-095)")
    found = brace_body(segment, m.start())
    if found is None:
        raise Reject(f"PluginProcessor.cpp:"
                     f"{line_of(code, segment_start + m.start())} — the mailbox "
                     f"clear loop is not brace-balanced")
    loop_rel = m.start()
    loop = segment[loop_rel:found[1]]
    loop_abs = segment_start + loop_rel

    if not re.search(MAILBOX_CLEAR, loop):
        raise Reject(f"PluginProcessor.cpp:{line_of(code, loop_abs)} — the "
                     f"restore-time loop walks the roster but never clears a "
                     f"pending flag (midiHostNotifySlots[...].pending = false); "
                     f"a staged CC from the previous session still notifies the "
                     f"host after the restore (CV-095)")

    prefix = segment[:m.start()]
    guard = re.search(r"\b(if|else|while|switch|return)\b", prefix)
    if guard:
        raise Reject(f"PluginProcessor.cpp:"
                     f"{line_of(code, segment_start + guard.start())} — the "
                     f"restore-time mailbox clear is guarded by "
                     f"`{guard.group(1)}`; every restore must clear it, "
                     f"including a state that carries no midiMaps child (CV-095)")

    mutated = re.search(SLOT_MUTATION, loop)
    if mutated:
        raise Reject(f"PluginProcessor.cpp:"
                     f"{line_of(code, loop_abs + mutated.start())} — the "
                     f"mailbox clear also rewrites a slot's identity/value "
                     f"field; a restore must only drop the pending flag and "
                     f"leave the constructor-built roster intact (CV-095)")
    for token in SLOT_ALLOCATION:
        if token in loop:
            raise Reject(f"PluginProcessor.cpp:{line_of(code, loop_abs)} — the "
                         f"mailbox clear touches `{token.strip()}`; the roster "
                         f"is preallocated and must never be freed, reallocated "
                         f"or grown by a restore (CV-095)")

    replace = re.search(REPLACE_STATE, body)
    if replace is None:
        raise Reject(f"PluginProcessor.cpp:{line_of(code, base)} — "
                     f"setStateInformation no longer calls apvts.replaceState; "
                     f"the restored-parameter anchor is gone")
    if not (base + replace.start() < loop_abs):
        raise Reject(f"PluginProcessor.cpp:{line_of(code, loop_abs)} — the "
                     f"mailbox clear runs BEFORE apvts.replaceState applies the "
                     f"saved parameters; the clear must belong to the restored "
                     f"session, not the one being replaced (CV-095)")

    return {"body": body, "loop": loop, "loop_abs": loop_abs,
            "segment_start": segment_start}


def _verify(code):
    """Gate one comment-stripped source text. Raises Reject on violation."""
    restore_point(code)

    drain = method_body(code, DRAIN)
    if drain is None:
        raise Reject(f"PluginProcessor.cpp: the {DRAIN} body is missing — a "
                     f"staged CC could never reach the host (CV-029)")
    drain_line = line_of(code, code.find(drain))
    if not re.search(r"pending\s*\.\s*exchange\s*\(\s*false\s*,\s*"
                     r"std::memory_order_acquire\s*\)", drain):
        raise Reject(f"PluginProcessor.cpp:{drain_line} — the drain no longer "
                     f"consumes each pending flag exactly once "
                     f"(exchange(false, acquire)); the restore-time clear must "
                     f"not change that contract (CV-029)")
    if "midiHostNotifySlots" not in drain:
        raise Reject(f"PluginProcessor.cpp:{drain_line} — the drain no longer "
                     f"walks the per-parameter pending slots")
    if "setValueNotifyingHost" not in drain:
        raise Reject(f"PluginProcessor.cpp:{drain_line} — the drain no longer "
                     f"forwards the staged value to the host")

    stage = method_body(code, STAGE)
    if stage is None:
        raise Reject(f"PluginProcessor.cpp: the {STAGE} body is missing — the "
                     f"audio thread could not publish a request (CV-029)")
    stage_line = line_of(code, code.find(stage))
    if not re.search(r"pending\s*\.\s*store\s*\(\s*true\s*,\s*"
                     r"std::memory_order_release\s*\)", stage):
        raise Reject(f"PluginProcessor.cpp:{stage_line} — the stage no longer "
                     f"publishes the pending flag with a release store "
                     f"(CV-029)")


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
        fail(f"stale self-probe '{label}' — the pattern no longer matches the "
             f"source, so the probe proves nothing")
    return new


def expect_reject(text, label, why):
    try:
        check(text)
    except Reject as exc:
        print(f"cv095 probe '{label}': rejected as expected ({exc})")
        return
    fail(f"probe '{label}' was NOT rejected — {why}")


def expect_pass(text, label):
    try:
        check(text)
    except Reject as exc:
        fail(f"benign {label} was REJECTED — the checker over-fires: {exc}")
    print(f"cv095: benign {label} passes (probe specificity proven)")


CPP_TEXT = CPP.read_text(encoding="utf-8") if CPP.exists() else None
if CPP_TEXT is None:
    fail(f"missing source file {CPP}")

try:
    check(CPP_TEXT)
except Reject as exc:
    fail(str(exc))
print("cv095: restore point clears every mailbox pending flag before "
      "publishMidiMap(), unguarded, with the roster/value fields untouched")
print("cv095: the learn clear and the drain loop are untouched by the fix and "
      "still satisfy their contracts")
print("cv095: the drain still consumes each flag once per tick and the stage "
      "still publishes it (CV-029 preserved)")

try:
    live = restore_point(strip_comments(CPP_TEXT))
except Reject as exc:
    fail(str(exc))

# (1) pre-patch reconstruction: delete the clear entirely -> must be rejected.
without = splice(strip_comments(CPP_TEXT), live["loop_abs"],
                 live["loop_abs"] + len(live["loop"]), "")
if without == strip_comments(CPP_TEXT):
    fail("stale self-probe 'delete-clear' — the mutation did not apply")
expect_reject(without, "clear deleted (pre-patch reconstruction)",
              "the previous session's staged CC could still be drained and "
              "rewrite a freshly restored parameter")

# (2) comment the clear out -> comment stripping must still reject it.
commented = splice(strip_comments(CPP_TEXT), live["loop_abs"],
                   live["loop_abs"] + len(live["loop"]),
                   "\n".join("// " + ln for ln in live["loop"].split("\n")))
if commented == strip_comments(CPP_TEXT):
    fail("stale self-probe 'comment-out-clear' — the mutation did not apply")
expect_reject(commented, "clear commented out",
              "commented-out code must not stand in for the clear")

# (3) move the clear after publishMidiMap() -> must be rejected.
moved = without
learn = list(re.finditer(LEARN_SLOT, moved))[-1]
pub = re.compile(PUBLISH).search(moved, learn.end())
if pub is None:
    fail("stale self-probe 'move-clear' — the publishMidiMap anchor "
         "disappeared")
moved = splice(moved, pub.end(), pub.end(), "\n" + live["loop"])
expect_reject(moved, "clear moved after publishMidiMap()",
              "the rebuilt table would be published while the old mailbox is "
              "still armed")

# (4) wrap the clear in an `if` -> must be rejected as conditional.
guarded = splice(strip_comments(CPP_TEXT), live["loop_abs"],
                 live["loop_abs"] + len(live["loop"]),
                 "if (restoringPresetState.load())\n{\n" + live["loop"] + "\n}")
if guarded == strip_comments(CPP_TEXT):
    fail("stale self-probe 'guarded-clear' — the mutation did not apply")
expect_reject(guarded, "clear guarded by an if",
              "at least one restore path could keep a foreign session's "
              "staged CC armed")

# (5) break the drain's one-shot consume -> must be rejected (CV-029 intact).
broken_drain = mutated_or_die(
    strip_comments(CPP_TEXT),
    r"pending\s*\.\s*exchange\s*\(\s*false\s*,\s*std::memory_order_acquire\s*\)",
    "pending.load(std::memory_order_acquire)",
    "drain-consume")
expect_reject(broken_drain, "drain no longer consumes the flag once",
              "a parameter would notify the host every tick; the restore fix "
              "must not weaken CV-029")

# (6) a benign edit inside the clear (loop variable rename) must still pass.
benign_loop = (live["loop"].replace("int i = 0", "int slotIndex = 0")
                           .replace(" i <", " slotIndex <")
                           .replace("++i", "++slotIndex")
                           .replace("(size_t) i", "(size_t) slotIndex"))
if benign_loop == live["loop"]:
    fail("stale self-probe 'benign-rename' — the loop text no longer matches")
expect_pass(splice(strip_comments(CPP_TEXT), live["loop_abs"],
                   live["loop_abs"] + len(live["loop"]), benign_loop),
            "loop-variable rename inside the clear")

# (7) a benign edit inside the drain (increment spelling) must still pass.
expect_pass(mutated_or_die(strip_comments(CPP_TEXT), r"\+\+notified\s*;",
                           "notified += 1;", "benign-drain-increment"),
            "drain increment respelling")

# (8) a benign comment edit elsewhere in the file must still pass.
expect_pass(mutated_or_die(CPP_TEXT, r"// MIDI Learn: map management",
                           "// MIDI Learn: map management (CV-095)",
                           "benign-comment"),
            "unrelated comment edit")

# Final live re-verification (the real tree was never written to).
try:
    check(CPP.read_text(encoding="utf-8"))
except Reject as exc:
    fail(f"final source re-verification failed: {exc}")
print("CV-095 OK")
