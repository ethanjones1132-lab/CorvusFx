#!/usr/bin/env python3
"""Check that a bad saved program index cannot drop a schema-valid restore.

Pins `CorvusInstrumentProcessor::setStateInformation` in
source/DrippyFX/instrument/CorvusInstrumentProcessor.cpp:

  (a) the schema/size guards still return before the restore;
  (b) `apvts.replaceState(candidate)` runs BEFORE any program-index handling,
      so a corrupt `currentProgram` can no longer discard the parameter tree;
  (c) the restored index is stored when it is inside [0, getNumPrograms()),
      and a clamped literal index (0) is stored otherwise;
  (d) `setStateInformation` never calls `setCurrentProgram` (it loads a preset
      into the parameters and would clobber the tree just restored) and never
      calls `loadPreset`.

Self-probes: a comment-only edit is accepted; re-introducing the early return
for an out-of-range index is rejected; calling `setCurrentProgram` from the
restore is rejected.
"""
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SOURCE = (ROOT / "source" / "DrippyFX" / "instrument"
          / "CorvusInstrumentProcessor.cpp")


def strip_comments(text: str) -> str:
    out = []
    i = 0
    quote = None
    escaped = False
    while i < len(text):
        char = text[i]
        next_char = text[i + 1] if i + 1 < len(text) else ""
        if quote is not None:
            out.append(char)
            if escaped:
                escaped = False
            elif char == "\\":
                escaped = True
            elif char == quote:
                quote = None
            i += 1
        elif char in ("\"", "'"):
            quote = char
            out.append(char)
            i += 1
        elif char == "/" and next_char == "/":
            out.extend((" ", " "))
            i += 2
            while i < len(text) and text[i] != "\n":
                out.append(" ")
                i += 1
        elif char == "/" and next_char == "*":
            out.extend((" ", " "))
            i += 2
            while i < len(text):
                if text[i] == "*" and i + 1 < len(text) and text[i + 1] == "/":
                    out.extend((" ", " "))
                    i += 2
                    break
                out.append("\n" if text[i] == "\n" else " ")
                i += 1
        else:
            out.append(char)
            i += 1
    return "".join(out)


def braced_body(text: str, opening: int):
    depth = 0
    quote = None
    escaped = False
    for i in range(opening, len(text)):
        char = text[i]
        if quote is not None:
            if escaped:
                escaped = False
            elif char == "\\":
                escaped = True
            elif char == quote:
                quote = None
        elif char in ("\"", "'"):
            quote = char
        elif char == "{":
            depth += 1
        elif char == "}":
            depth -= 1
            if depth == 0:
                return text[opening + 1:i]
    return None


def function_body(text: str, name: str):
    pattern = (rf"\bvoid\s+CorvusInstrumentProcessor::{name}"
               rf"\s*\([^)]*\)\s*\{{")
    match = re.search(pattern, text, flags=re.S)
    if not match:
        return None
    return braced_body(text, match.end() - 1)


REPLACE_STATE = re.compile(r"\bapvts\s*\.\s*replaceState\s*\(\s*candidate\s*\)\s*;")
PROGRAM_DECL = re.compile(r"\bconst\s+auto\s+restoredProgram\s*=[^;]*;")
CLAMP = re.compile(r"\belse\s+currentProgram\s*=\s*(-?\d+)\s*;")


def check_text(source_text: str):
    errors = []
    code = strip_comments(source_text)

    body = function_body(code, "setStateInformation")
    if body is None:
        return ["could not find CorvusInstrumentProcessor::setStateInformation body"]

    replace_calls = list(REPLACE_STATE.finditer(body))
    if len(replace_calls) != 1:
        errors.append("setStateInformation must have exactly one "
                      "apvts.replaceState(candidate) call")
        return errors
    replace_call = replace_calls[0]

    # (a) schema/size validation must survive, and it is the only thing allowed
    # to bail out before the tree is replaced.
    before = body[:replace_call.start()]
    if not re.search(r"\bschemaVersion\b", before):
        errors.append("schemaVersion validation must remain before replaceState")
    if not re.search(r"\breturn\s*;", before):
        errors.append("invalid/size/schema guards must still return before replaceState")
    if re.search(r"\bcurrentProgram\b|\bgetNumPrograms\s*\(\s*\)"
                 r"|\brestoredProgram\b", before):
        errors.append("program-index handling must run after replaceState, "
                      "not before it and never as an early return")

    # (c) in-range value is stored; out-of-range is clamped, not restored.
    after = body[replace_call.end():]
    in_range = re.search(
        r"restoredProgram\s*>=\s*0\s*&&\s*restoredProgram\s*<\s*"
        r"getNumPrograms\s*\(\s*\)", after)
    store = re.search(r"\bcurrentProgram\s*=\s*restoredProgram\s*;", after)
    clamp = CLAMP.search(after)
    if not in_range:
        errors.append("out-of-range program index must be tested against "
                      "[0, getNumPrograms()) after replaceState")
    if not store:
        errors.append("an in-range program index must be stored in currentProgram")
    if not clamp:
        errors.append("an out-of-range program index must store a clamped "
                      "literal index instead of returning")
    elif int(clamp.group(1)) < 0:
        errors.append("clamped program index must not be negative")
    if in_range and store and clamp:
        if not (in_range.start() < store.start() < clamp.start()):
            errors.append("restored index must be stored only when it is in "
                          "range, with the clamp as the fallback")

    # (d) restoring must not load a preset over the tree we just replaced.
    if re.search(r"\bsetCurrentProgram\s*\(", body):
        errors.append("setStateInformation must not call setCurrentProgram")
    if re.search(r"\bloadPreset\s*\(", body):
        errors.append("setStateInformation must not call loadPreset")

    return errors


def early_return_probe(code: str):
    """Rebuild the pre-CV-023 shape: bail out before replaceState."""
    replace_call = REPLACE_STATE.search(code)
    program_decl = PROGRAM_DECL.search(code)
    clamp = CLAMP.search(code)
    if not (replace_call and program_decl and clamp):
        return None
    if not (replace_call.start() < program_decl.start() < clamp.start()):
        return None
    legacy = (
        "const auto restoredProgram = static_cast<int>("
        "candidate.getProperty(\"currentProgram\", 0));\n"
        "    if (restoredProgram < 0 || restoredProgram >= getNumPrograms())\n"
        "        return;\n\n"
        "    apvts.replaceState(candidate);\n"
        "    currentProgram = restoredProgram;"
    )
    return code[:replace_call.start()] + legacy + code[clamp.end():]


source_text = SOURCE.read_text(encoding="utf-8", errors="replace")
errors = check_text(source_text)
if errors:
    print("FAIL: CV-023 program restore invariants violated:")
    for error in errors:
        print(f"  - {error}")
    sys.exit(1)

print("OK: out-of-range program index keeps the restored tree and clamps the index")

# A comment-only change must not affect the source contract.
comment_probe = source_text + "\n// harmless checker probe\n"
if check_text(comment_probe):
    print("FAIL: harmless comment edit was rejected")
    sys.exit(1)
print("probe ok: harmless comment edit -> accepted")

# Restoring the early return models the bug this slice fixes.
code = strip_comments(source_text)
legacy_text = early_return_probe(code)
if legacy_text is None:
    print("FAIL: early-return probe could not reshape the restore body")
    sys.exit(1)
if not check_text(legacy_text):
    print("FAIL: early return on a bad program index was accepted")
    sys.exit(1)
print("probe ok: early return before replaceState -> rejected")

# Loading a preset from the restore would clobber the restored parameters.
preset_load = REPLACE_STATE.sub(
    lambda match: match.group(0) + "\n    setCurrentProgram(0);", code, count=1)
if preset_load == code:
    print("FAIL: preset-load probe did not apply")
    sys.exit(1)
if not check_text(preset_load):
    print("FAIL: setCurrentProgram call inside setStateInformation was accepted")
    sys.exit(1)
print("probe ok: setCurrentProgram from setStateInformation -> rejected")
print("CV-023 PROGRAM-RESTORE SELF-PROBES OK "
      "(2 negatives, comment edit accepted)")
