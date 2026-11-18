#!/usr/bin/env python3
"""CV-066/CV-070: insertion is silent; host recall is not echoed twice.

The C++ FX render test checks actual raw values, audible output and undo.
This gate covers the constructor's lack of host-facing calls and the live
program recall ordering, not JUCE's delivery of parameter values.
"""
import re
from pathlib import Path

SOURCE = (Path(__file__).resolve().parent.parent / "source" / "DrippyFX"
          / "PluginProcessor.cpp")


def body(text, name):
    begin = text.index("{", text.index(f"CorvusFXAudioProcessor::{name}("))
    depth = 0
    for end in range(begin, len(text)):
        if text[end] == "{":
            depth += 1
        elif text[end] == "}":
            depth -= 1
            if depth == 0:
                return text[begin + 1:end]
    raise ValueError(f"unbalanced body: {name}")


def verify(text):
    text = re.sub(r"/\*.*?\*/|//[^\n]*", "", text, flags=re.S)
    ctor = body(text, "CorvusFXAudioProcessor")
    layout = body(text, "createParameterLayout")
    if re.search(r"\b(loadPreset|setCurrentProgram|beginNewTransaction|"
                 r"(?:begin|end)ChangeGesture|setValue(?:NotifyingHost)?)\s*\(",
                 ctor + layout):
        return "construction must not write to live parameters or to undo"
    if not re.search(r"\bfactoryPreset\s*\(\s*0\s*\)", layout):
        return "the layout must initialize from factory program zero"

    live = body(text, "setCurrentProgram")
    if not re.search(r"hostProgramRecall\.store\(-1\);\s*loadPreset\(i\);\s*"
                     r"hostProgramRecall\.store\(i\);.*?setValueNotifyingHost\(",
                     live, re.S):
        return "the host recall must apply the program before arming the listener echo skip"
    if not re.search(r"if\s*\(hostProgramRecall\.exchange\(-1\)\s*==\s*index\)"
                     r"\s*return;\s*undoManager\.beginNewTransaction\(",
                     body(text, "loadPreset")):
        return "the echo must be consumed before a live transaction opens"
    return None


source = SOURCE.read_text(encoding="utf-8")
if error := verify(source):
    raise SystemExit(f"CV-066/CV-070 FAIL: {error}")
for old, new in (
    ("factoryPreset(0)", "factoryPreset(1)"),
    ("publishMidiMap();", "publishMidiMap(); loadPreset(0);"),
    ("hostProgramRecall.exchange(-1)", "hostProgramRecall.load()"),
):
    mutated = source.replace(old, new, 1)
    if mutated == source or not verify(mutated):
        raise SystemExit(f"CV-066/CV-070 FAIL: invalid probe for {old}")
print("CV-066/CV-070: layout seeds silently; live program recall consumes its echo")
