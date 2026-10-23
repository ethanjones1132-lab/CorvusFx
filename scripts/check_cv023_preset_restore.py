#!/usr/bin/env python3
"""Headless checker: the preset-restore guard stays narrow (CV-022, 0ae25eb).

`setStateInformation` restores the APVTS tree with `apvts.replaceState(...)`.
That call notifies the "preset" parameter listener, and the listener used to
map the restored combo id through `idToPreset` and call `loadPreset` -- so a
session recall silently reloaded a factory preset on top of the saved state.

The landed fix is deliberately narrow:

    restoringPresetState.store(true);
    apvts.replaceState(juce::ValueTree::fromXml(parameterState));
    restoringPresetState.store(false);

with a single early return in the "preset" branch of `parameterChanged`:

    if (restoringPresetState.load())
        return;

and the ordinary path still mapping a real combo id through `idToPreset` to
`loadPreset`.

Asserts on the real tree (comment-stripped, brace-matched):
  (a) `restoringPresetState` is an instance `std::atomic<bool>` initialized
      false in the processor class;
  (b) `setStateInformation` has exactly one `replaceState` call, bracketed by
      exactly one `store(true)` before it and one `store(false)` after it, so
      the flag cannot leak set past the restore;
  (c) `setStateInformation` never calls `loadPreset` (the whole point of the
      guard: restoring state must not reselect a preset);
  (d) the "preset" branch of `parameterChanged` starts with the restore return
      and a valid id still maps through `idToPreset` to `loadPreset`;
  (e) the flag is referenced exactly three times in the .cpp (two stores plus
      one guard) so it cannot silently widen into a global preset-off switch.

Negative probes (in-memory mutated copies; a no-op mutation aborts as a stale
alarm, the real tree is never mutated):
  - drop the early return -> rejected (restore reloads a preset again);
  - drop the store(true) -> rejected (the flag never covers replaceState);
  - call loadPreset during restore -> rejected;
  - invert the guard -> rejected (real preset selections would be ignored);
  - benign comment/whitespace edit -> accepted (probe specificity).

Exit 0 = ok, 1 = violation with a cited diagnostic, 2 = setup/read failure.
"""
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
HEADER = ROOT / "source" / "DrippyFX" / "PluginProcessor.h"
SOURCE = ROOT / "source" / "DrippyFX" / "PluginProcessor.cpp"


def strip_comments(text):
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


def braced_body(text, opening):
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


def function_body(text, name):
    pattern = (rf"\bvoid\s+CorvusFXAudioProcessor::{name}"
               rf"\s*\([^)]*\)\s*\{{")
    match = re.search(pattern, text, flags=re.S)
    if not match:
        return None
    return braced_body(text, match.end() - 1)


def check_text(header_text, source_text):
    errors = []
    header_code = strip_comments(header_text)
    source_code = strip_comments(source_text)

    # (a) per-instance flag, initialized false.
    class_match = re.search(r"\bclass\s+CorvusFXAudioProcessor\b[^;]*\{",
                            header_code, flags=re.S)
    class_body = (braced_body(header_code, class_match.end() - 1)
                  if class_match else None)
    if class_body is None:
        errors.append("could not find the CorvusFXAudioProcessor class")
    elif not re.search(
            r"\bstd::atomic\s*<\s*bool\s*>\s+restoringPresetState"
            r"\s*\{\s*false\s*\}\s*;", class_body):
        errors.append("restoringPresetState must be an instance "
                      "std::atomic<bool> initialized false")

    # (b) + (c) the restore scope in setStateInformation.
    restore_body = function_body(source_code, "setStateInformation")
    if restore_body is None:
        errors.append("could not find the setStateInformation body")
    else:
        replace_calls = list(re.finditer(r"\bapvts\s*\.\s*replaceState\s*\(",
                                         restore_body))
        stores = list(re.finditer(
            r"\brestoringPresetState\s*\.\s*store\s*\(\s*(true|false)\s*\)"
            r"\s*;", restore_body))
        true_stores = [m for m in stores if m.group(1) == "true"]
        false_stores = [m for m in stores if m.group(1) == "false"]
        if len(replace_calls) != 1:
            errors.append("setStateInformation must have exactly one "
                          "apvts.replaceState call (found %d)"
                          % len(replace_calls))
        if len(true_stores) != 1 or len(false_stores) != 1:
            errors.append("setStateInformation must set restoringPresetState "
                          "true exactly once and false exactly once (found "
                          "%d/%d)" % (len(true_stores), len(false_stores)))
        if len(replace_calls) == 1 and len(true_stores) == 1 \
                and len(false_stores) == 1:
            call = replace_calls[0]
            if not (true_stores[0].start() < call.start()
                    < false_stores[0].start()):
                errors.append("replaceState must run between the "
                              "restoringPresetState true and false stores")
        if re.search(r"\bloadPreset\s*\(", restore_body):
            errors.append("setStateInformation calls loadPreset - restoring a "
                          "session must not reselect a factory preset")

    # (d) the live preset path stays guarded but functional.
    changed_body = function_body(source_code, "parameterChanged")
    if changed_body is None:
        errors.append("could not find the parameterChanged body")
    else:
        preset_match = re.search(
            r"if\s*\(\s*parameterID\s*==\s*\"preset\"\s*\)\s*\{",
            changed_body)
        preset_body = (braced_body(changed_body, preset_match.end() - 1)
                       if preset_match else None)
        if preset_body is None:
            errors.append("parameterChanged must retain its preset branch")
        else:
            guard = re.match(
                r"\s*if\s*\(\s*restoringPresetState\s*\.\s*load\s*\(\s*\)"
                r"\s*\)\s*return\s*;", preset_body)
            real_preset = re.search(
                r"if\s*\(\s*id\s*>=\s*2\s*&&\s*id\s*<=\s*42\s*&&\s*"
                r"idToPreset\s*\[\s*id\s*\]\s*>=\s*0\s*\)\s*"
                r"loadPreset\s*\(\s*idToPreset\s*\[\s*id\s*\]\s*\)\s*;",
                preset_body)
            if guard is None:
                errors.append("the preset branch must start with "
                              "`if (restoringPresetState.load()) return;`")
            if real_preset is None:
                errors.append("valid preset ids must still map through "
                              "idToPreset to loadPreset")
            elif guard is not None and guard.end() > real_preset.start():
                errors.append("the restore guard must precede the real "
                              "preset load path")

    # (e) the flag stays scoped to the two places above.
    uses = len(re.findall(r"\brestoringPresetState\b", source_code))
    if uses != 3:
        errors.append("restoringPresetState is referenced %d times in "
                      "PluginProcessor.cpp; the narrow fix needs exactly 3 "
                      "(two stores around replaceState plus the preset guard)"
                      % uses)

    return errors


def benign_edits(source_text):
    """A comment edit and a whitespace edit that must not change the verdict."""
    comment = source_text.replace(
        "void CorvusFXAudioProcessor::parameterChanged",
        "// harmless checker probe: guarding preset dispatch is intentional.\n"
        "void CorvusFXAudioProcessor::parameterChanged", 1)
    whitespace = re.sub(r"\n    if \(parameterID == \"preset\"\)",
                        "\n\tif (parameterID == \"preset\")", source_text,
                        count=1)
    probes = []
    stale = []
    for label, probe in (("comment", comment), ("whitespace", whitespace)):
        if probe == source_text:
            stale.append(label)
        else:
            probes.append((label, probe))
    return probes, stale


def run(header_text, source_text):
    errors = check_text(header_text, source_text)
    return errors


def main():
    for path in (HEADER, SOURCE):
        if not path.exists():
            print("PRESET-RESTORE-SCOPE SETUP FAIL: missing %s" % path)
            return 2
    try:
        header_text = HEADER.read_text(encoding="utf-8", errors="replace")
        source_text = SOURCE.read_text(encoding="utf-8", errors="replace")
    except OSError as exc:
        print("PRESET-RESTORE-SCOPE SETUP FAIL: %s" % exc)
        return 2

    errors = run(header_text, source_text)
    if errors:
        print("PRESET-RESTORE-SCOPE FAIL: preset restore scope violated:")
        for error in errors:
            print("  - %s" % error)
        return 1
    print("preset-restore-scope: replaceState is bracketed by "
          "restoringPresetState true/false, the preset listener returns while "
          "restoring, and real ids still reach loadPreset via idToPreset")

    # Negative probes: each reintroduces the reported defect in a different
    # shape. They run on in-memory copies only.
    probes = [
        ("drop the early return in the preset branch",
         lambda h, s: s.replace(
             "        if (restoringPresetState.load())\n            return;\n",
             "", 1)),
        ("drop the store(true) around replaceState",
         lambda h, s: s.replace(
             "        restoringPresetState.store(true);\n", "", 1)),
        ("call loadPreset from setStateInformation",
         lambda h, s: s.replace(
             "        apvts.replaceState(juce::ValueTree::fromXml("
             "parameterState));",
             "        apvts.replaceState(juce::ValueTree::fromXml("
             "parameterState));\n        loadPreset(0);", 1)),
        ("invert the preset-branch guard",
         lambda h, s: s.replace(
             "if (restoringPresetState.load())",
             "if (!restoringPresetState.load())", 1)),
    ]
    for label, mutate in probes:
        mutated = mutate(header_text, source_text)
        if mutated == source_text:
            print("PRESET-RESTORE-SCOPE FAIL: probe '%s' is stale: mutation "
                  "did not apply - cannot trust the negative check" % label)
            return 1
        errors = run(header_text, mutated)
        if not errors:
            print("PRESET-RESTORE-SCOPE FAIL: probe '%s' was NOT rejected - "
                  "checker is vacuous" % label)
            return 1
        print("preset-restore-scope: probe '%s' rejected (%s)"
              % (label, errors[0][:88]))

    # Specificity: benign edits outside the pinned shapes still pass.
    probes, stale = benign_edits(source_text)
    if stale:
        print("PRESET-RESTORE-SCOPE FAIL: benign probe(s) %s are stale: the "
              "edit did not apply" % ", ".join(stale))
        return 1
    for label, probe in probes:
        errors = run(header_text, probe)
        if errors:
            print("PRESET-RESTORE-SCOPE FAIL: benign %s edit was rejected - "
                  "checker over-fires: %s" % (label, errors[0]))
            return 1
        print("preset-restore-scope: benign %s edit accepted (probe "
              "specificity proven)" % label)

    if run(HEADER.read_text(encoding="utf-8", errors="replace"),
           SOURCE.read_text(encoding="utf-8", errors="replace")):
        print("PRESET-RESTORE-SCOPE FAIL: final live-source re-verification "
              "failed")
        return 1
    print("PRESET-RESTORE-SCOPE OK (4 negatives, comment + whitespace edits "
          "accepted)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
