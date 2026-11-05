#!/usr/bin/env python3
"""Check host-notifying writes are enclosed by parameter change gestures.

CV-042 covers the plugin-initiated writes in preset recall, randomization,
host program changes, the message-thread MIDI drain, and A/B recall. Each
write must have a matching begin/end pair on its parameter. processBlock is
the CV-029 audio-thread staging path and must never notify the host or open a
gesture.

In-memory probes remove a gesture from a real write path and inject one into
processBlock; both mutations must be rejected.
"""
import re
import sys
from pathlib import Path

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

ROOT = Path(__file__).resolve().parent.parent
SOURCE = ROOT / "source" / "DrippyFX" / "PluginProcessor.cpp"
PROCESSOR = "CorvusFXAudioProcessor"
PATHS = (
    "loadPreset", "randomizePreset", "setCurrentProgram",
    "drainPendingMidiHostNotifications", "loadSlotA", "loadSlotB",
)
NOTIFY = re.compile(r"(?P<receiver>[\w.>]+)\s*->\s*setValueNotifyingHost\s*\(")
GESTURE = re.compile(
    r"(?P<receiver>[\w.>]+)\s*->\s*(?P<kind>beginChangeGesture|endChangeGesture)\s*\(\s*\)")


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

    process = function_body(code, "processBlock")
    if process is None:
        return ["could not find CorvusFXAudioProcessor::processBlock body"]
    if re.search(r"\b(?:beginChangeGesture|endChangeGesture|setValueNotifyingHost)\s*\(", process[2]):
        errors.append("processBlock must not call a gesture method or "
                      "setValueNotifyingHost (CV-029 staging boundary)")

    for name in PATHS:
        found = function_body(code, name)
        if found is None:
            errors.append(f"could not find CorvusFXAudioProcessor::{name} body")
            continue
        body = found[2]
        writes = list(NOTIFY.finditer(body))
        if not writes:
            errors.append(f"{name} has no setValueNotifyingHost write to check")
            continue
        for write in writes:
            receiver = write.group("receiver")
            gestures = list(GESTURE.finditer(body))
            begins = [m for m in gestures if m.group("kind") == "beginChangeGesture"
                      and m.group("receiver") == receiver and m.start() < write.start()]
            ends = [m for m in gestures if m.group("kind") == "endChangeGesture"
                    and m.group("receiver") == receiver and m.start() > write.start()]
            if not begins or not ends:
                errors.append(f"{name}: {receiver}->setValueNotifyingHost is not "
                              "enclosed by its matching begin/endChangeGesture pair")
                continue
            begin = begins[-1]
            end = ends[0]
            if begin.start() >= end.start():
                errors.append(f"{name}: {receiver} gesture closes before it opens")
            if any(m.group("kind") == "endChangeGesture"
                   and m.group("receiver") == receiver
                   and begin.start() < m.start() < write.start() for m in gestures):
                errors.append(f"{name}: {receiver} gesture ends before its host write")
            if any(m.group("kind") == "beginChangeGesture"
                   and m.group("receiver") == receiver
                   and write.start() < m.start() < end.start() for m in gestures):
                errors.append(f"{name}: {receiver} gesture opens again before it closes")
    return errors


if not SOURCE.exists():
    print(f"FAIL: missing source file {SOURCE}")
    sys.exit(1)

source_text = SOURCE.read_text(encoding="utf-8", errors="replace")
errors = verify(source_text)
if errors:
    print("FAIL: CV-042 host change gesture invariants violated:")
    for error in errors:
        print(f"  - {error}")
    sys.exit(1)
print("OK: plugin-initiated host writes have matching parameter gestures")
print("OK: processBlock remains free of host notifications and gestures")


def fail_probe(label, why):
    print(f"FAIL: probe '{label}' was NOT rejected — {why}")
    sys.exit(1)


def fail_stale(label):
    print(f"FAIL: probe '{label}': NO-OP MUTATION — probe is stale")
    sys.exit(1)


if verify(source_text + "\n// harmless checker probe\n"):
    print("FAIL: harmless comment edit was rejected")
    sys.exit(1)
print("probe ok: harmless comment edit -> accepted")

# Delete the gesture opener from the preset-recall setter (in memory only).
code = strip_comments(source_text)
load = function_body(code, "loadPreset")
if load is None:
    fail_stale("loadPreset gesture removal")
target = re.search(r"(?P<receiver>\w+)\s*->\s*beginChangeGesture\s*\(\s*\)",
                   load[2])
if not target:
    fail_stale("loadPreset gesture removal")
mutated = (code[:load[0] + 1 + target.start()]
           + code[load[0] + 1 + target.end():])
if not verify(mutated):
    fail_probe("loadPreset gesture removed", "an ungestured preset write passed")
print("probe ok: preset-recall gesture removed -> rejected")

# A render callback gesture violates CV-029 even if unrelated writes are absent.
process = function_body(code, "processBlock")
if process is None:
    fail_stale("gesture inserted into processBlock")
mutated = code[:process[0] + 1] + "\n    param->beginChangeGesture();\n" + code[process[0] + 1:]
if not verify(mutated):
    fail_probe("gesture inserted into processBlock", "processBlock gesture passed")
print("probe ok: gesture inserted into processBlock -> rejected")

final_errors = verify()
if final_errors:
    print("FAIL: final source re-verification failed:")
    for error in final_errors:
        print(f"  - {error}")
    sys.exit(1)
print("CV-042 OK")
