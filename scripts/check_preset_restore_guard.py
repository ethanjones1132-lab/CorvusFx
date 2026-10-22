#!/usr/bin/env python3
"""Check the per-instance preset restore guard and its live preset path."""
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
HEADER = ROOT / "source" / "DrippyFX" / "PluginProcessor.h"
SOURCE = ROOT / "source" / "DrippyFX" / "PluginProcessor.cpp"


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
    pattern = (rf"\bvoid\s+CorvusFXAudioProcessor::{name}"
               rf"\s*\([^)]*\)\s*\{{")
    match = re.search(pattern, text, flags=re.S)
    if not match:
        return None
    return braced_body(text, match.end() - 1)


def check_text(header_text: str, source_text: str):
    errors = []
    header_code = strip_comments(header_text)
    source_code = strip_comments(source_text)

    class_match = re.search(r"\bclass\s+CorvusFXAudioProcessor\b[^;]*\{",
                            header_code, flags=re.S)
    class_body = (braced_body(header_code, class_match.end() - 1)
                  if class_match else None)
    if class_body is None:
        errors.append("could not find CorvusFXAudioProcessor class")
    elif not re.search(
            r"\bstd::atomic\s*<\s*bool\s*>\s+restoringPresetState\s*\{\s*false\s*\}\s*;",
            class_body):
        errors.append("restore flag must be an instance std::atomic<bool> initialized false")

    restore_body = function_body(source_code, "setStateInformation")
    if restore_body is None:
        errors.append("could not find setStateInformation body")
    else:
        replace_calls = list(re.finditer(r"\bapvts\s*\.\s*replaceState\s*\(",
                                         restore_body))
        if not replace_calls:
            errors.append("setStateInformation must replace the restored APVTS state")
        stores = list(re.finditer(
            r"\brestoringPresetState\s*\.\s*store\s*\(\s*(true|false)\s*\)\s*;",
            restore_body))
        for call in replace_calls:
            prior_true = [m.start() for m in stores
                          if m.group(1) == "true" and m.start() < call.start()]
            prior_false = [m.start() for m in stores
                           if m.group(1) == "false" and m.start() < call.start()]
            next_false = [m.start() for m in stores
                          if m.group(1) == "false" and m.start() > call.end()]
            if (not prior_true or
                    (prior_false and max(prior_false) > max(prior_true)) or
                    not next_false):
                errors.append("replaceState must run between the restore flag true and false stores")
                break

    changed_body = function_body(source_code, "parameterChanged")
    if changed_body is None:
        errors.append("could not find parameterChanged body")
    else:
        preset_match = re.search(
            r"if\s*\(\s*parameterID\s*==\s*\"preset\"\s*\)\s*\{",
            changed_body)
        preset_body = (braced_body(changed_body, preset_match.end() - 1)
                       if preset_match else None)
        if preset_body is None:
            errors.append("parameterChanged must retain its preset parameter branch")
        else:
            guard = re.search(
                r"if\s*\(\s*restoringPresetState\s*\.\s*load\s*\(\s*\)\s*\)\s*return\s*;",
                preset_body)
            real_preset = re.search(
                r"if\s*\(\s*id\s*>=\s*2\s*&&\s*id\s*<=\s*42\s*&&\s*"
                r"idToPreset\s*\[\s*id\s*\]\s*>=\s*0\s*\)\s*"
                r"loadPreset\s*\(\s*idToPreset\s*\[\s*id\s*\]\s*\)\s*;",
                preset_body)
            if not guard:
                errors.append("preset callback must return while this instance restores state")
            if not real_preset:
                errors.append("valid preset ids must still map through idToPreset to loadPreset")
            if guard and real_preset and guard.start() > real_preset.start():
                errors.append("restore guard must precede the real preset load path")

    return errors


header_text = HEADER.read_text(encoding="utf-8", errors="replace")
source_text = SOURCE.read_text(encoding="utf-8", errors="replace")
errors = check_text(header_text, source_text)
if errors:
    print("FAIL: preset restore guard invariants violated:")
    for error in errors:
        print(f"  - {error}")
    getattr(sys, "exit")(1)

print("OK: session restore is guarded and valid preset selections still call loadPreset")

# A comment-only change must not affect the source contract.
comment_probe = source_text + "\n// harmless checker probe\n"
if check_text(header_text, comment_probe):
    print("FAIL: harmless comment edit was rejected")
    getattr(sys, "exit")(1)
print("probe ok: harmless comment edit -> accepted")

# Removing the restore-on store models an unguarded replaceState notification.
unguarded = re.sub(
    r"restoringPresetState\s*\.\s*store\s*\(\s*true\s*\)\s*;", "",
    source_text, count=1)
if unguarded == source_text:
    print("FAIL: unguarded restore probe did not apply")
    getattr(sys, "exit")(1)
if not check_text(header_text, unguarded):
    print("FAIL: unguarded replaceState was accepted")
    getattr(sys, "exit")(1)
print("probe ok: unguarded replaceState -> rejected")

# Reversing the guard would return for every ordinary preset selection.
normal_guard = "if (restoringPresetState.load())"
if source_text.count(normal_guard) != 1:
    print("FAIL: wide-guard probe could not find one restore guard")
    getattr(sys, "exit")(1)
wide_guard = source_text.replace(
    normal_guard, "if (!restoringPresetState.load())", 1)
if not check_text(header_text, wide_guard):
    print("FAIL: guard blocking real preset changes was accepted")
    getattr(sys, "exit")(1)
print("probe ok: guard blocking real preset changes -> rejected")
print("PRESET-RESTORE SELF-PROBES OK (2 negatives, comment edit accepted)")
