#!/usr/bin/env python3
"""CV-072: the editor's A/B slot indicator must follow the processor's slot.

Before the fix the editor constructor was the only place that lit A or B. A
host state restore (setStateInformation), a program change or an undo can flip
the processor's active slot while the window is open, so a constructor-only
reflect leaves the other slot lit - and the SAVE button, whose target the
editor derives from the same slot, keeps banking into the wrong one.

This checker pins that:
  (a) PluginEditor.cpp timerCallback polls audioProcessor.isSlotA() every tick,
  (b) the two toggles are re-pointed only when they disagree with the polled
      slot (a disagreement guard precedes the first write), with
      juce::dontSendNotification so the reflect never fires click handlers,
  (c) the SAVE target (colour + tooltip, i.e. the state the editor derives
      from the slot) is refreshed from that same polled value on the same
      tick - a slot-blind or missing refresh is rejected,
  (d) the timer never writes the compare pair (CV-067 still owns the slots),
  (e) the editor still keeps its one-shot constructor reflect (CV-067), so the
      first frame is correct too.

Negative self-probes prove the checker fails on the pre-patch shape (a
constructor-only setToggleState with no timer-side refresh) and on each
partial or slot-blind variant. The real tree is never mutated.
"""

import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SRC = ROOT / "source" / "DrippyFX"
ED = SRC / "PluginEditor.cpp"
HDR = SRC / "PluginEditor.h"
EDITOR = "CorvusFXAudioProcessorEditor"

DONT_NOTIFY = r"juce\s*::\s*dontSendNotification"
TIMER = rf"void\s+{EDITOR}::timerCallback\s*\(\s*\)"
HELPER = rf"void\s+{EDITOR}::refreshSaveTarget\s*\(\s*bool\s+(\w+)\s*\)"
HELPER_DECL = r"void\s+refreshSaveTarget\s*\(\s*bool\s+\w+\s*\)\s*;"
POLL = (r"const\s+bool\s+(\w+)\s*=\s*audioProcessor\s*\.\s*isSlotA\s*"
        r"\(\s*\)\s*;")


def read_source(path):
    """Read a source file as LF-normalised UTF-8 (CRLF must not move anchors)."""
    return path.read_text(encoding="utf-8", errors="replace").replace(
        "\r\n", "\n")


def blank_comments(text):
    """Blank every comment character but keep offsets (and newlines) stable."""
    def block(match):
        return "".join("\n" if ch == "\n" else " " for ch in match.group(0))
    text = re.sub(r"/\*.*?\*/", block, text, flags=re.S)
    return re.sub(r"//[^\n]*", lambda m: " " * len(m.group(0)), text)


def braced_span(text, opening):
    depth = 0
    for i in range(opening, len(text)):
        if text[i] == "{":
            depth += 1
        elif text[i] == "}":
            depth -= 1
            if depth == 0:
                return opening, i + 1
    return None


def function_span(code, pattern):
    """Absolute (inner_start, inner_end) of the first matching body, or None."""
    match = re.search(pattern, code, flags=re.S)
    if not match:
        return None
    opening = code.find("{", match.end() - 1)
    if opening < 0:
        return None
    span = braced_span(code, opening)
    if span is None:
        return None
    return span[0] + 1, span[1] - 1


def verify(ed_text, hdr_text):
    """Return the list of violated CV-072 assertions (empty means pass)."""
    ed = blank_comments(ed_text)
    hdr = blank_comments(hdr_text)
    errors = []

    # -- (e) header: the derived SAVE-target helper must be declared ------
    if not re.search(HELPER_DECL, hdr):
        errors.append("PluginEditor.h lost the `void refreshSaveTarget(bool);` "
                      "declaration - the SAVE target has no slot-derived state")

    # -- (a)+(b) timerCallback polls the slot and re-points both toggles ---
    timer_span = function_span(ed, TIMER)
    timer = "" if timer_span is None else ed[timer_span[0]:timer_span[1]]
    if timer_span is None:
        errors.append("PluginEditor.cpp has no "
                      f"{EDITOR}::timerCallback() body - nothing refreshes the "
                      "A/B indicator after a host state restore")

    poll = re.search(POLL, timer) if timer else None
    slot = poll.group(1) if poll else None
    if timer and poll is None:
        errors.append("timerCallback never polls audioProcessor.isSlotA(); the "
                      "constructor-only reflect leaves the other slot lit after "
                      "a host state restore (CV-072)")

    guard_start = None
    if poll is not None:
        after = timer[poll.end():]
        guard = re.search(r"if\s*\(([^{}]*?)\)\s*\{", after, flags=re.S)
        if guard is None:
            errors.append("timerCallback polls the active slot but never guards "
                          "the toggle refresh with a disagreement check - it "
                          "would fight the click handlers every tick")
        else:
            guard_start = poll.end() + guard.start()
            cond = guard.group(1)
            if not re.search(rf"btnSlotA\s*\.\s*getToggleState\s*\(\s*\)\s*!=\s*"
                             rf"{re.escape(slot)}\b", cond):
                errors.append("timerCallback does not compare btnSlotA's shown "
                              "state against the polled slot (CV-072)")
            if not re.search(rf"btnSlotB\s*\.\s*getToggleState\s*\(\s*\)\s*==\s*"
                             rf"{re.escape(slot)}\b", cond):
                errors.append("timerCallback does not compare btnSlotB's shown "
                              "state against the polled slot (CV-072)")

            g_open = poll.end() + guard.end() - 1
            g_span = braced_span(timer, g_open)
            if g_span is None:
                errors.append("timerCallback's slot-disagreement guard has an "
                              "unreadable body")
            else:
                g_body = timer[g_span[0]:g_span[1]]
                if not re.search(rf"btnSlotA\s*\.\s*setToggleState\s*\(\s*"
                                 rf"{re.escape(slot)}\s*,\s*{DONT_NOTIFY}\s*\)",
                                 g_body):
                    errors.append("timerCallback's guard never sets btnSlotA to "
                                  "the polled slot with dontSendNotification")
                if not re.search(rf"btnSlotB\s*\.\s*setToggleState\s*\(\s*!\s*"
                                 rf"{re.escape(slot)}\s*,\s*{DONT_NOTIFY}\s*\)",
                                 g_body):
                    errors.append("timerCallback's guard never sets btnSlotB to "
                                  "!slot with dontSendNotification")

            first_write = re.search(r"btnSlotA\s*\.\s*setToggleState", timer)
            if first_write is not None and first_write.start() < guard_start:
                errors.append("timerCallback writes btnSlotA before the "
                              "disagreement guard - the refresh must be guarded, "
                              "not unconditional (CV-072)")

    # -- (c) the SAVE target is refreshed from the same polled slot --------
    if poll is not None:
        call = re.search(rf"refreshSaveTarget\s*\(\s*{re.escape(slot)}\s*\)\s*;",
                         timer)
        if call is None:
            errors.append("timerCallback does not refresh the SAVE target from "
                          "the polled slot (refreshSaveTarget(<slot>)); an undo "
                          "or preset load can leave SAVE pointing at the other "
                          "slot (CV-072)")
        elif call.start() < poll.start():
            errors.append("timerCallback refreshes the SAVE target from a slot "
                          "read that happens after the refresh")

    helper_match = re.search(HELPER, ed)
    helper = ""
    if helper_match is None:
        errors.append("PluginEditor.cpp has no "
                      f"{EDITOR}::refreshSaveTarget(bool) definition - the SAVE "
                      "target is not derived from the slot")
    else:
        helper_span = function_span(ed, HELPER)
        if helper_span is None:
            errors.append("PluginEditor.cpp: refreshSaveTarget's body is "
                          "unreadable - the SAVE target cannot be verified")
        else:
            helper = ed[helper_span[0]:helper_span[1]]
            param = helper_match.group(1)
            pair = re.search(rf"btnSaveAB\s*\.\s*setColour\s*\(\s*"
                             rf"juce::TextButton::buttonColourId\s*,\s*"
                             rf"{re.escape(param)}\s*\?[^;]*juce::Colour\s*\(\s*"
                             rf"(0x[0-9a-fA-F]+)\s*\)\s*:\s*juce::Colour\s*\(\s*"
                             rf"(0x[0-9a-fA-F]+)\s*\)", helper, flags=re.S)
            if pair is None:
                errors.append("refreshSaveTarget does not derive btnSaveAB's "
                              "colour from the active slot (CV-072)")
            elif pair.group(1).lower() == pair.group(2).lower():
                errors.append("refreshSaveTarget paints the same colour for "
                              "both slots - the SAVE target is slot-blind "
                              "(CV-072)")
            if not re.search(rf"btnSaveAB\s*\.\s*setTooltip\s*\(\s*"
                             rf"{re.escape(param)}\b", helper):
                errors.append("refreshSaveTarget does not derive btnSaveAB's "
                              "tooltip from the active slot (CV-072)")
            elif "slot A" not in helper or "slot B" not in helper:
                errors.append("refreshSaveTarget's tooltip does not name both "
                              "slot targets (CV-072)")

    # -- (d) the reflect never writes the compare pair ---------------------
    for label, body in (("timerCallback", timer), ("refreshSaveTarget", helper)):
        for needle in ("saveSlot", "snapshotA", "snapshotB"):
            if needle in body:
                errors.append(f"{label} references {needle}; the editor only "
                              "reflects the processor's slot and never writes "
                              "the compare pair (CV-067)")

    return errors


# ---------------------------------------------------------------------------
# negative self-probes on mutated in-memory texts (real tree never mutated)
# ---------------------------------------------------------------------------
def inner_bounds(text, pattern):
    """Absolute (start, end) of a function body using offset-stable blanking."""
    return function_span(blank_comments(text), pattern)


def splice(text, start, end, replacement):
    return text[:start] + replacement + text[end:]


def drop_timer_slot_refresh(text):
    """P1: the pre-patch shape - constructor-only reflect, no timer refresh."""
    span = inner_bounds(text, TIMER)
    if span is None:
        return None
    inner = blank_comments(text)[span[0]:span[1]]
    poll = re.search(POLL, inner)
    guard = re.search(r"if\s*\([^{}]*getToggleState\s*\(\s*\)[^{}]*\)\s*\{",
                      inner, flags=re.S)
    if poll is None or guard is None or guard.start() < poll.start():
        return None
    blank = blank_comments(text)
    g_span = braced_span(blank, span[0] + guard.end() - 1)
    if g_span is None:
        return None
    call = re.search(r"refreshSaveTarget\s*\(\s*\w+\s*\)\s*;",
                     blank[g_span[1]:span[1]])
    if call is None:
        return None
    return splice(text, span[0] + poll.start(), g_span[1] + call.end(), "")


def unguard_timer_refresh(text):
    """P2: refresh unconditionally, with no disagreement check."""
    span = inner_bounds(text, TIMER)
    if span is None:
        return None
    inner = blank_comments(text)[span[0]:span[1]]
    guard = re.search(r"if\s*\(([^{}]*getToggleState\s*\(\s*\)[^{}]*)\)\s*\{",
                      inner, flags=re.S)
    if guard is None:
        return None
    return splice(text, span[0] + guard.start(1), span[0] + guard.end(1), "true")


def drop_b_toggle_write(text):
    """P3: refresh only A, leaving B showing the stale slot."""
    span = inner_bounds(text, TIMER)
    if span is None:
        return None
    inner = blank_comments(text)[span[0]:span[1]]
    guard = re.search(r"if\s*\([^{}]*getToggleState\s*\(\s*\)[^{}]*\)\s*\{",
                      inner, flags=re.S)
    if guard is None:
        return None
    g_span = braced_span(blank_comments(text), span[0] + guard.end() - 1)
    if g_span is None:
        return None
    stmt = re.search(r"[ \t]*btnSlotB\s*\.\s*setToggleState\s*\([^;]*\)\s*;"
                     r"[ \t]*\n?", blank_comments(text)[g_span[0]:g_span[1]])
    if stmt is None:
        return None
    return splice(text, g_span[0] + stmt.start(), g_span[0] + stmt.end(), "")


def hardcode_polled_slot(text):
    """P4: read no slot at all - the poll is replaced by a constant."""
    span = inner_bounds(text, TIMER)
    if span is None:
        return None
    inner = blank_comments(text)[span[0]:span[1]]
    poll = re.search(r"audioProcessor\s*\.\s*isSlotA\s*\(\s*\)", inner)
    if poll is None:
        return None
    return splice(text, span[0] + poll.start(), span[0] + poll.end(), "true")


def save_colour_slot_blind(text):
    """P5: paint the same SAVE colour for both slots."""
    span = inner_bounds(text, HELPER)
    if span is None:
        return None
    inner = blank_comments(text)[span[0]:span[1]]
    pair = re.search(r"\?\s*juce::Colour\s*\(\s*(0x[0-9a-fA-F]+)\s*\)\s*:\s*"
                     r"juce::Colour\s*\(\s*(0x[0-9a-fA-F]+)\s*\)", inner)
    if pair is None or pair.group(1).lower() == pair.group(2).lower():
        return None
    return splice(text, span[0] + pair.start(2), span[0] + pair.end(2),
                  pair.group(1))


def timer_writes_compare_pair(text):
    """P6: the timer banks a snapshot - the editor writes the pair (CV-067)."""
    span = inner_bounds(text, TIMER)
    if span is None:
        return None
    return splice(text, span[0], span[0], "\n    audioProcessor.saveSlotA();")


def drop_save_target_refresh(text):
    """P7: the toggles move but the SAVE target stays behind."""
    span = inner_bounds(text, TIMER)
    if span is None:
        return None
    inner = blank_comments(text)[span[0]:span[1]]
    call = re.search(r"[ \t]*refreshSaveTarget\s*\([^;]*\)\s*;[ \t]*\n?", inner)
    if call is None:
        return None
    return splice(text, span[0] + call.start(), span[0] + call.end(), "")


def drop_save_tooltip(text):
    """P8: the SAVE colour is derived but its stated target is not."""
    span = inner_bounds(text, HELPER)
    if span is None:
        return None
    inner = blank_comments(text)[span[0]:span[1]]
    stmt = re.search(r"[ \t]*btnSaveAB\s*\.\s*setTooltip\s*\([^;]*\)\s*;"
                     r"[ \t]*\n?", inner)
    if stmt is None:
        return None
    return splice(text, span[0] + stmt.start(), span[0] + stmt.end(), "")


PROBES = [
    ("pre-patch: constructor-only reflect, no timer-side slot refresh",
     drop_timer_slot_refresh),
    ("timer refresh without the disagreement guard", unguard_timer_refresh),
    ("timer refresh drops the B toggle", drop_b_toggle_write),
    ("timer hardcodes the slot instead of polling the processor",
     hardcode_polled_slot),
    ("SAVE colour painted identically for both slots",
     save_colour_slot_blind),
    ("timer writes the A/B compare pair (CV-067 breach)",
     timer_writes_compare_pair),
    ("timer never refreshes the SAVE target", drop_save_target_refresh),
    ("SAVE tooltip no longer names the active slot", drop_save_tooltip),
]


def main():
    ed_raw = read_source(ED)
    hdr_raw = read_source(HDR)

    errors = verify(ed_raw, hdr_raw)
    if errors:
        print("CV-072 FAIL: the editor's A/B indicator does not track the "
              "processor's slot:")
        for error in errors:
            print(f"  - {error}")
        return 1

    print("CV-072 OK: editor timerCallback polls audioProcessor.isSlotA() and "
          "re-points both A/B toggles (dontSendNotification) only when they "
          "disagree")
    print("CV-072 OK: the SAVE target's colour + tooltip are re-derived from "
          "the same polled slot every tick")
    print("CV-072 OK: the refresh only reflects the processor's slot and never "
          "writes the compare pair (CV-067)")

    for label, mutate in PROBES:
        mutated = mutate(ed_raw)
        if mutated is None or mutated == ed_raw:
            print(f"CV-072 FAIL: stale self-probe '{label}': mutation did not "
                  "apply")
            return 1
        if not verify(mutated, hdr_raw):
            print(f"CV-072 FAIL: negative probe '{label}' was NOT rejected - "
                  "the checker is vacuous")
            return 1
        print(f"CV-072 probe ok: {label} -> rejected")

    # specificity guard: an edit outside the pinned shapes still passes
    neutral = ed_raw.replace('btnSaveAB.setButtonText("SAVE");',
                             'btnSaveAB.setButtonText( "SAVE" );')
    if neutral == ed_raw:
        print("CV-072 FAIL: no-op guard: unanchored neutral edit did not apply")
        return 1
    neutral_errors = verify(neutral, hdr_raw)
    if neutral_errors:
        print("CV-072 FAIL: benign edit outside the pinned shapes was rejected "
              "- the checker over-fires:")
        for error in neutral_errors:
            print(f"  - {error}")
        return 1
    print("CV-072 probe ok: benign edit outside the pinned shapes accepted")

    final_errors = verify(read_source(ED), read_source(HDR))
    if final_errors:
        print("CV-072 FAIL: final re-verification of the live tree failed:")
        for error in final_errors:
            print(f"  - {error}")
        return 1
    print("CV-072 OK: live tree re-verified")
    return 0


if __name__ == "__main__":
    sys.exit(main())
