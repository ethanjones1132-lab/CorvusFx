#!/usr/bin/env python3
"""CV-075: an instrument preset recall brackets each write in a gesture pair.

Before this patch setCurrentProgram wrote all eight physical values with
setValueNotifyingHost and no gesture, so the host saw per-parameter silent
jumps rather than one coherent automation/undo edit. The recall helper must
now follow the FX recall shape: beginChangeGesture, notify, close the gesture
from a catch before rethrowing, endChangeGesture. Only the recall path may
open gestures; processBlock is the CV-029 staging boundary and must stay
free of host notifications and gestures.

In-memory probes remove the pair, move the opener after its write, and inject
an ungestured write into the recall body; every mutation must be rejected.
"""
import re
import sys
from pathlib import Path

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

ROOT = Path(__file__).resolve().parent.parent
SOURCE = (ROOT / "source" / "DrippyFX" / "instrument"
          / "CorvusInstrumentProcessor.cpp")
PROCESSOR = "CorvusInstrumentProcessor"

NOTIFY = re.compile(r"(?P<receiver>[\w.>]+)\s*->\s*setValueNotifyingHost\s*\(")
GESTURE = re.compile(
    r"(?P<receiver>[\w.>]+)\s*->\s*(?P<kind>beginChangeGesture|endChangeGesture)\s*\(\s*\)")
CATCH_CLOSE = re.compile(
    r"catch\s*\([^)]*\)\s*\{[^}]*->\s*endChangeGesture\s*\(\s*\)\s*;[^}]*throw\s*;")
RECALL_CALL = re.compile(r"\bsetPhysicalValue\s*\(")
PRESET_VALUE_CALLS = 8


def strip_comments(text):
    text = re.sub(r"/\*.*?\*/", lambda m: "\n" * m.group(0).count("\n"),
                  text, flags=re.S)
    return re.sub(r"//[^\n]*", "", text)


def braced_span(text, opening):
    depth = 0
    for i in range(opening, len(text)):
        if text[i] == "{":
            depth += 1
        elif text[i] == "}":
            depth -= 1
            if depth == 0:
                return opening, i + 1, text[opening + 1:i]
    return None


def function_body(code, name):
    match = re.search(
        rf"\b(?:void|int)\s+{PROCESSOR}::{name}\s*\([^)]*\)\s*\{{",
        code, flags=re.S)
    if not match:
        return None
    return braced_span(code, match.end() - 1)


def verify(source_text=None):
    if source_text is None:
        source_text = SOURCE.read_text(encoding="utf-8", errors="replace")
    code = strip_comments(source_text)
    errors = []

    recall = function_body(code, "setCurrentProgram")
    if recall is None:
        return [f"could not find {PROCESSOR}::setCurrentProgram body"]
    body = recall[2]

    process = function_body(code, "processBlock")
    if process is None:
        errors.append(f"could not find {PROCESSOR}::processBlock body")
    elif GESTURE.search(process[2]) or NOTIFY.search(process[2]):
        errors.append("processBlock must not open a gesture or notify the host "
                      "(CV-029 staging boundary)")

    for gesture in GESTURE.finditer(code):
        if not recall[0] < gesture.start() < recall[1]:
            line = code.count("\n", 0, gesture.start()) + 1
            errors.append(f"{gesture.group('kind')} outside the preset recall "
                          f"path (stripped line {line}); gestures belong to "
                          "setCurrentProgram only")

    gestures = list(GESTURE.finditer(body))
    writes = list(NOTIFY.finditer(body))
    if not writes:
        errors.append("setCurrentProgram has no setValueNotifyingHost write to check")
    if len(re.findall(r"\bsetValueNotifyingHost\s*\(", body)) != len(writes):
        errors.append("setCurrentProgram has a setValueNotifyingHost write the "
                      "checker cannot bind to a named receiver; route it through "
                      "the gestured helper")
    for write in writes:
        receiver = write.group("receiver")
        begins = [m for m in gestures
                  if m.group("kind") == "beginChangeGesture"
                  and m.group("receiver") == receiver
                  and m.start() < write.start()]
        ends = [m for m in gestures
                if m.group("kind") == "endChangeGesture"
                and m.group("receiver") == receiver
                and m.start() > write.start()]
        if not begins or not ends:
            errors.append(f"setCurrentProgram: {receiver}->setValueNotifyingHost "
                          "is not enclosed by its matching begin/endChangeGesture pair")
            continue
        begin = begins[-1]
        end = ends[0]
        if any(m.group("kind") == "endChangeGesture"
               and m.group("receiver") == receiver
               and begin.start() < m.start() < write.start() for m in gestures):
            errors.append(f"setCurrentProgram: {receiver} gesture ends before its "
                          "host write")
        if any(m.group("kind") == "beginChangeGesture"
               and m.group("receiver") == receiver
               and write.start() < m.start() < end.start() for m in gestures):
            errors.append(f"setCurrentProgram: {receiver} gesture opens again "
                          "before it closes")

    if len(gestures) < 2 or not CATCH_CLOSE.search(body):
        errors.append("the recall helper must close its gesture from a catch "
                      "block before rethrowing (FX recall pattern)")

    if len(RECALL_CALL.findall(body)) < PRESET_VALUE_CALLS:
        errors.append("every recalled preset value must be written through the "
                      "gestured setPhysicalValue helper")
    return errors


if not SOURCE.exists():
    print(f"FAIL: missing source file {SOURCE}")
    sys.exit(1)

source_text = SOURCE.read_text(encoding="utf-8", errors="replace")
errors = verify(source_text)
if errors:
    print("FAIL: CV-075 instrument preset recall gesture invariants violated:")
    for error in errors:
        print(f"  - {error}")
    sys.exit(1)
print("OK: every instrument preset recall write is enclosed by a gesture pair")
print("OK: gestures stay out of processBlock and outside the recall path")


def fail_probe(label, why):
    print(f"FAIL: probe '{label}' was NOT rejected - {why}")
    sys.exit(1)


def fail_stale(label):
    print(f"FAIL: probe '{label}': NO-OP MUTATION - probe is stale")
    sys.exit(1)


def spliced(code, start, stop, insert):
    return code[:start] + insert + code[stop:]


if verify(source_text + "\n// harmless checker probe\n"):
    print("FAIL: harmless comment edit was rejected")
    sys.exit(1)
print("probe ok: harmless comment edit -> accepted")

# Revert to the pre-patch shape: drop every gesture call from the recall body.
code = strip_comments(source_text)
recall = function_body(code, "setCurrentProgram")
if recall is None:
    fail_stale("recall gesture removal")
inner = recall[2]
reverted = inner
for gesture in reversed(list(GESTURE.finditer(inner))):
    reverted = spliced(reverted, gesture.start(), gesture.end(), "")
mutated = spliced(code, recall[0] + 1, recall[0] + 1 + len(inner), reverted)
if reverted == inner:
    fail_stale("recall gesture removal")
if not verify(mutated):
    fail_probe("recall gesture pair removed", "an ungestured preset write passed")
print("probe ok: preset-recall gesture pair removed -> rejected")

# Reorder: move the opener to after the write it is supposed to bracket.
recall = function_body(code, "setCurrentProgram")
if recall is None:
    fail_stale("recall gesture reorder")
inner = recall[2]
write = NOTIFY.search(inner)
begin = None
if write is not None:
    candidates = [m for m in GESTURE.finditer(inner)
                  if m.group("kind") == "beginChangeGesture"
                  and m.group("receiver") == write.group("receiver")
                  and m.start() < write.start()]
    begin = candidates[-1] if candidates else None
if write is None or begin is None:
    fail_stale("recall gesture reorder")
semicolon = inner.find(";", write.end())
if semicolon < 0:
    fail_stale("recall gesture reorder")
opener = begin.group(0)
without = spliced(inner, begin.start(), begin.end(), "")
insert_at = semicolon - len(opener) + 1
reordered = spliced(without, insert_at, insert_at, "\n    " + opener)
mutated = spliced(code, recall[0] + 1, recall[0] + 1 + len(inner), reordered)
if reordered == inner:
    fail_stale("recall gesture reorder")
if not verify(mutated):
    fail_probe("recall gesture opener moved after its write",
               "a reordered gesture pair passed")
print("probe ok: recall gesture opener moved after its write -> rejected")

# A direct, ungestured write injected into the recall body is a silent jump.
recall = function_body(code, "setCurrentProgram")
if recall is None:
    fail_stale("ungestured recall write")
inner = recall[2]
injected = (inner + '\n    auto* stray = apvts.getParameter("attack");\n'
            "    stray->setValueNotifyingHost(0.5f);\n")
mutated = spliced(code, recall[0] + 1, recall[0] + 1 + len(inner), injected)
if injected == inner or not verify(mutated):
    fail_probe("ungestured recall write", "a silent preset write passed")
print("probe ok: ungestured write injected into recall -> rejected")

final_errors = verify()
if final_errors:
    print("FAIL: final source re-verification failed:")
    for error in final_errors:
        print(f"  - {error}")
    sys.exit(1)
print("CV-075 OK")
