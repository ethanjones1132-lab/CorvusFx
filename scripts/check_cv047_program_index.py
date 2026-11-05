#!/usr/bin/env python3
"""Keep every cross-thread currentProgram access atomic and bounded.

The program index is shared by host callbacks/state serialization and the audio
thread. Relaxed atomic access is sufficient because this value does not publish
or guard any other data. The checker also self-probes plain read/write regressions.
"""
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
HEADER = (ROOT / "source" / "DrippyFX" / "instrument"
          / "CorvusInstrumentProcessor.h")
SOURCE = (ROOT / "source" / "DrippyFX" / "instrument"
          / "CorvusInstrumentProcessor.cpp")


def strip_comments_and_strings(text: str) -> str:
    """Mask comments and quoted literals without changing source positions."""
    out = list(text)
    i = 0
    quote = None
    escaped = False
    while i < len(text):
        char = text[i]
        nxt = text[i + 1] if i + 1 < len(text) else ""
        if quote is not None:
            if char != "\n":
                out[i] = " "
            if escaped:
                escaped = False
            elif char == "\\":
                escaped = True
            elif char == quote:
                quote = None
            i += 1
        elif char in ('"', "'"):
            quote = char
            out[i] = " "
            i += 1
        elif char == "/" and nxt == "/":
            out[i] = out[i + 1] = " "
            i += 2
            while i < len(text) and text[i] != "\n":
                out[i] = " "
                i += 1
        elif char == "/" and nxt == "*":
            out[i] = out[i + 1] = " "
            i += 2
            while i < len(text):
                if text[i] == "*" and i + 1 < len(text) and text[i + 1] == "/":
                    out[i] = out[i + 1] = " "
                    i += 2
                    break
                if text[i] != "\n":
                    out[i] = " "
                i += 1
        else:
            i += 1
    return "".join(out)


def check_text(header_text: str, source_text: str):
    errors = []
    header = strip_comments_and_strings(header_text)
    source = strip_comments_and_strings(source_text)
    if not re.search(r"\bstd::atomic\s*<\s*int\s*>\s+currentProgram\s*\{\s*0\s*\}", header):
        errors.append("currentProgram must be initialized as std::atomic<int>")

    # Remove the required declaration and every supported relaxed atomic access.
    remainder = re.sub(
        r"\bstd::atomic\s*<\s*int\s*>\s+currentProgram\s*\{\s*0\s*\}",
        " ", header)
    access = re.compile(
        r"\bcurrentProgram\s*\.\s*(?:load\s*\(\s*"
        r"std::memory_order_relaxed\s*\)|store\s*\(\s*"
        r"(?:index|restoredProgram|0)\s*,\s*"
        r"std::memory_order_relaxed\s*\))")
    source_remainder = access.sub(" ", source)
    if re.search(r"\bcurrentProgram\b", remainder):
        errors.append("header contains an unsupported currentProgram declaration/use")
    if re.search(r"\bcurrentProgram\b", source_remainder):
        errors.append("currentProgram has a non-atomic or non-relaxed source access")

    # Pin the current access surface so a removed access cannot silently evade
    # the negative probes while the checker still passes.
    if len(access.findall(source)) != 6:
        errors.append("expected three relaxed loads and three relaxed stores")
    return errors


header_text = HEADER.read_text(encoding="utf-8", errors="replace")
source_text = SOURCE.read_text(encoding="utf-8", errors="replace")
errors = check_text(header_text, source_text)
if errors:
    print("FAIL: CV-047 program-index atomic contract violated:")
    for error in errors:
        print(f"  - {error}")
    sys.exit(1)

print("OK: currentProgram uses relaxed atomic access on host and audio paths")

for label, mutated in (
    ("plain read", source_text.replace(
        "currentProgram.load(std::memory_order_relaxed)", "currentProgram", 1)),
    ("plain write", source_text.replace(
        "currentProgram.store(index, std::memory_order_relaxed)",
        "currentProgram = index", 1)),
):
    if mutated == source_text:
        print(f"FAIL: {label} negative probe did not apply")
        sys.exit(1)
    if not check_text(header_text, mutated):
        print(f"FAIL: unsynchronized {label} was accepted")
        sys.exit(1)
    print(f"probe ok: unsynchronized {label} -> rejected")

if check_text(header_text + "\n// harmless comment\n", source_text):
    print("FAIL: benign comment edit was rejected")
    sys.exit(1)
print("probe ok: benign comment edit -> accepted")
print("CV-047 PROGRAM-INDEX SELF-PROBES OK (2 negatives, benign edit accepted)")
