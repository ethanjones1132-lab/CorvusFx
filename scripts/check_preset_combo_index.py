#!/usr/bin/env python3
"""Headless checker: preset ComboBox item-ID <-> preset index mapping pin.

The FX editor's preset ComboBox holds 42 entries whose ids 1..42 are NOT a
preset index: six of them (1, 8, 15, 22, 29, 36) are disabled
"--- CATEGORY ---" separators and the remaining 36 are the factory presets
0..35. The "preset" parameter stores the ITEM ID, which parameterChanged()
resolves through idToPreset[]. The stock
juce::AudioProcessorValueTreeState::ComboBoxAttachment instead stores the
zero-based list INDEX spread linearly over the parameter range, which shifts
every selection by one row (one click loads the neighbouring preset, or a
separator id that loads nothing).

This checker pins the whole junction:
  (a) PluginEditor.cpp adds exactly 42 items with ids 1..42 in source order,
      disables exactly ids 1, 8, 15, 22, 29, 36, labels those six as
      "--- ... ---" separators, and leaves every other item enabled;
  (b) PluginEditor.h defines PresetComboAttachment, which passes the item id
      through verbatim BOTH ways — parameter -> combo via
      setSelectedId(juce::roundToInt(...), juce::sendNotificationSync) behind
      an ignoreCallbacks/ScopedValueSetter guard, user -> parameter via
      setValueAsCompleteGesture((float) comboBox.getSelectedId()) — with a
      balanced addListener/removeListener pair and an initial
      sendInitialUpdate();
  (c) PluginEditor.cpp constructs exactly that attachment for "preset" (apvts
      parameter + presetSelector + the processor undo manager), keeps the
      stock ComboBoxAttachment out of the editor, and never reads
      presetSelector.getSelectedItemIndex() (index semantics);
  (d) PluginProcessor.cpp keeps the "preset" AudioParameterInt covering ids
      0..42 and idToPreset[] mapping the 36 enabled ids to 0..35 in order and
      every separator id to -1.

Self-probes mutate in-memory copies only; the real tree is never touched.
Exit 0 = ok, 1 = violation with cited diagnostics.
"""
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SRC = ROOT / "source" / "DrippyFX"
ED = SRC / "PluginEditor.cpp"
ED_H = SRC / "PluginEditor.h"
PROC = SRC / "PluginProcessor.cpp"

ITEM_COUNT = 42
PRESET_COUNT = 36
SEPARATOR_IDS = (1, 8, 15, 22, 29, 36)

ADD_ITEM_RE = re.compile(
    r'presetSelector\.addItem\(\s*"([^"]*)"\s*,\s*(\d+)\s*\)')
SET_ENABLED_RE = re.compile(
    r'presetSelector\.setItemEnabled\(\s*(\d+)\s*,\s*(true|false)\s*\)')
PRESET_ATT_RE = re.compile(
    r'std::make_unique<PresetComboAttachment>\s*\(\s*\*\s*'
    r'audioProcessor\.apvts\.getParameter\s*\(\s*"preset"\s*\)\s*,\s*'
    r'presetSelector\s*,\s*&audioProcessor\.undoManager\s*\)')
STOCK_COMBO_RE = re.compile(r'AudioProcessorValueTreeState::ComboBoxAttachment')
INDEX_ACCESS_RE = re.compile(r'presetSelector\.getSelectedItemIndex\s*\(')
CLASS_RE = re.compile(
    r'class\s+PresetComboAttachment\s*:\s*private\s+juce::ComboBox::Listener'
    r'\s*\{(.*?)\n\};', re.S)
PRESET_PARAM_RE = re.compile(
    r'AudioParameterInt>\s*\(\s*"preset"\s*,\s*"Preset"\s*,\s*'
    r'(-?\d+)\s*,\s*(-?\d+)\s*,\s*(-?\d+)\s*\)')
ID_TO_PRESET_RE = re.compile(
    r'static\s+const\s+int\s+idToPreset\s*\[\s*(\d+)\s*\]\s*=\s*\{(.*?)\}\s*;',
    re.S)


def strip_comments(txt):
    out, i, n = [], 0, len(txt)
    while i < n:
        if txt.startswith("//", i):
            j = txt.find("\n", i)
            i = n if j == -1 else j
        elif txt.startswith("/*", i):
            j = txt.find("*/", i + 2)
            i = n if j == -1 else j + 2
        else:
            out.append(txt[i]); i += 1
    return "".join(out)


def check_editor_items(txt, errors):
    items = [(name, int(iid)) for name, iid in ADD_ITEM_RE.findall(txt)]
    if len(items) != ITEM_COUNT:
        errors.append(
            f"PluginEditor.cpp adds {len(items)} preset combo items, expected "
            f"{ITEM_COUNT} (36 presets + 6 category separators)")
        return
    ids = [iid for _, iid in items]
    if ids != list(range(1, ITEM_COUNT + 1)):
        errors.append(
            f"preset combo item ids are not exactly 1..{ITEM_COUNT} in source "
            f"order: {ids}")
    enabled_flags = {}
    for iid, flag in SET_ENABLED_RE.findall(txt):
        enabled_flags[int(iid)] = flag == "true"
    disabled = sorted(i for i, on in enabled_flags.items() if not on)
    if disabled != list(SEPARATOR_IDS):
        errors.append(
            f"disabled preset combo ids are {disabled}, expected exactly the "
            f"six long-standing separators {list(SEPARATOR_IDS)}")
    for name, iid in items:
        named_separator = name.strip().startswith("---")
        # JUCE addItem rows are enabled unless explicitly disabled.
        is_disabled = enabled_flags.get(iid, True) is False
        if iid in SEPARATOR_IDS:
            if not named_separator:
                errors.append(
                    f"item id {iid} is a separator but its label {name!r} "
                    f"does not start with '---'")
            if not is_disabled:
                errors.append(
                    f"separator item id {iid} ({name!r}) is not disabled; a "
                    f"selectable separator loads no preset")
        else:
            if named_separator:
                errors.append(
                    f"item id {iid} is labelled {name!r} like a separator but "
                    f"is a selectable preset row")
            if is_disabled:
                errors.append(
                    f"preset item id {iid} ({name!r}) is disabled; every "
                    f"non-separator row must stay selectable")


def check_attachment(txt_h, errors):
    m = CLASS_RE.search(txt_h)
    if not m:
        errors.append(
            "PluginEditor.h no longer defines PresetComboAttachment : private "
            "juce::ComboBox::Listener — the stock ComboBoxAttachment stores "
            "the list INDEX and shifts every preset selection by one row")
        return
    body = m.group(1)
    if not re.search(r'comboBox\.addListener\s*\(\s*this\s*\)', body):
        errors.append("PresetComboAttachment never addListener()s on the combo")
    if not re.search(r'comboBox\.removeListener\s*\(\s*this\s*\)', body):
        errors.append(
            "PresetComboAttachment never removeListener()s on the combo "
            "(dangling listener after the editor closes)")
    if not re.search(r'attachment\.sendInitialUpdate\s*\(\s*\)', body):
        errors.append(
            "PresetComboAttachment skips the initial sendInitialUpdate(); the "
            "combo would not show the parameter's current preset on open")
    if not re.search(
            r'setSelectedId\s*\(\s*juce::roundToInt\s*\([^)]*\)\s*,\s*'
            r'juce::sendNotificationSync\s*\)', body):
        errors.append(
            "PresetComboAttachment parameter -> combo path must call "
            "comboBox.setSelectedId(juce::roundToInt(<raw item id>), "
            "juce::sendNotificationSync) — no index mapping")
    if not re.search(r'ScopedValueSetter\s*<\s*bool\s*>\s*\w+\s*\(\s*'
                     r'ignoreCallbacks\s*,\s*true\s*\)', body):
        errors.append(
            "PresetComboAttachment lost its ignoreCallbacks/ScopedValueSetter "
            "guard: its own parameter-driven setSelectedId would echo back as "
            "a user gesture")
    if not re.search(r'if\s*\(\s*ignoreCallbacks\s*\)\s*return\s*;', body):
        errors.append(
            "PresetComboAttachment comboBoxChanged() no longer bails out on "
            "ignoreCallbacks")
    if not re.search(
            r'setValueAsCompleteGesture\s*\(\s*\(\s*float\s*\)\s*'
            r'comboBox\.getSelectedId\s*\(\s*\)\s*\)', body):
        errors.append(
            "PresetComboAttachment user -> parameter path must be "
            "setValueAsCompleteGesture((float) comboBox.getSelectedId()) so "
            "the preset ITEM ID is stored verbatim")
    if "getSelectedItemIndex" in body:
        errors.append(
            "PresetComboAttachment reads getSelectedItemIndex(); item index "
            "is not the preset id and reintroduces the CV-021 off-by-one")


def check_editor_wiring(txt, errors):
    if len(PRESET_ATT_RE.findall(txt)) != 1:
        errors.append(
            "PluginEditor.cpp must construct exactly one PresetComboAttachment "
            "for the apvts 'preset' parameter, presetSelector and "
            "&audioProcessor.undoManager")
    if STOCK_COMBO_RE.search(txt):
        errors.append(
            "stock AudioProcessorValueTreeState::ComboBoxAttachment is back "
            "in PluginEditor.cpp; it stores the combo list INDEX, so choosing "
            "a preset loads the neighbouring row")
    if INDEX_ACCESS_RE.search(txt):
        errors.append(
            "PluginEditor.cpp reads presetSelector.getSelectedItemIndex(); "
            "the preset parameter needs the item id, not the list index")


def check_processor(txt, errors):
    m = PRESET_PARAM_RE.search(txt)
    if not m:
        errors.append("could not find the AudioParameterInt \"preset\" declaration")
    else:
        lo, hi, default = (int(m.group(1)), int(m.group(2)), int(m.group(3)))
        if (lo, hi) != (0, ITEM_COUNT):
            errors.append(
                f"\"preset\" parameter range is [{lo},{hi}], expected "
                f"[0,{ITEM_COUNT}] to hold every combo item id")
        if not (lo < default <= hi):
            errors.append(
                f"\"preset\" default {default} is outside the item-id range "
                f"[{lo},{hi}]")

    m = ID_TO_PRESET_RE.search(txt)
    if not m:
        errors.append("could not find the static idToPreset[] table")
        return
    declared = int(m.group(1))
    values = [int(v) for v in re.findall(r"-?\d+", strip_comments(m.group(2)))]
    if declared != ITEM_COUNT + 1 or len(values) != ITEM_COUNT + 1:
        errors.append(
            f"idToPreset declares {declared} entries / holds {len(values)}, "
            f"expected {ITEM_COUNT + 1} (ids 0..{ITEM_COUNT})")
        return
    expected = list(values)
    for iid in range(ITEM_COUNT + 1):
        if iid in SEPARATOR_IDS or iid == 0:
            expected[iid] = -1
        else:
            expected[iid] = iid - 1 - sum(1 for s in SEPARATOR_IDS if s < iid)
    for iid in range(ITEM_COUNT + 1):
        if values[iid] != expected[iid]:
            errors.append(
                f"idToPreset[{iid}]={values[iid]}, expected {expected[iid]} — "
                f"combo item id {iid} would load the wrong preset")
    used = sorted(v for v in values if v >= 0)
    if used != list(range(PRESET_COUNT)):
        errors.append(
            f"idToPreset covers preset indices {used}, expected exactly "
            f"0..{PRESET_COUNT - 1} once each")
    if "idToPreset[id]" not in strip_comments(txt):
        errors.append(
            "parameterChanged no longer resolves the combo item id through "
            "idToPreset[id]")


def check(cpp_txt, hdr_txt, proc_txt):
    errors = []
    check_editor_items(cpp_txt, errors)
    check_attachment(hdr_txt, errors)
    check_editor_wiring(cpp_txt, errors)
    check_processor(proc_txt, errors)
    return errors


if not ED.exists():
    print(f"PRESET-COMBO-INDEX FAIL: missing {ED}")
    getattr(sys, "exit")(1)
if not ED_H.exists():
    print(f"PRESET-COMBO-INDEX FAIL: missing {ED_H}")
    getattr(sys, "exit")(1)
if not PROC.exists():
    print(f"PRESET-COMBO-INDEX FAIL: missing {PROC}")
    getattr(sys, "exit")(1)

CPP_RAW = ED.read_text(encoding="utf-8")
HDR_RAW = ED_H.read_text(encoding="utf-8")
PROC_RAW = PROC.read_text(encoding="utf-8")
CPP_TXT = strip_comments(CPP_RAW)
HDR_TXT = strip_comments(HDR_RAW)
PROC_TXT = strip_comments(PROC_RAW)

FAILURES = check(CPP_TXT, HDR_TXT, PROC_TXT)
if FAILURES:
    print("PRESET-COMBO-INDEX FAIL: preset combo mapping violated:")
    for failure in FAILURES:
        print(f"  - {failure}")
    getattr(sys, "exit")(1)

print(f"preset-combo-index: {ITEM_COUNT} items ids 1..{ITEM_COUNT}, separators "
      f"{list(SEPARATOR_IDS)} disabled, PresetComboAttachment passes the item "
      f"id verbatim both ways, idToPreset maps the {PRESET_COUNT} enabled ids "
      f"to 0..{PRESET_COUNT - 1}")


# ---------------------------------------------------------------------------
# Self-probes on mutated in-memory copies (the real tree is never mutated)
# ---------------------------------------------------------------------------

def probe(description, cpp_new=None, hdr_new=None, proc_new=None):
    cpp = strip_comments(CPP_RAW if cpp_new is None else cpp_new)
    hdr = strip_comments(HDR_RAW if hdr_new is None else hdr_new)
    proc = strip_comments(PROC_RAW if proc_new is None else proc_new)
    if (cpp, hdr, proc) == (CPP_TXT, HDR_TXT, PROC_TXT):
        print(f"preset-combo-index: SELF-PROBE FAIL (mutation did not apply): "
              f"{description}")
        getattr(sys, "exit")(1)
    if not check(cpp, hdr, proc):
        print(f"preset-combo-index: SELF-PROBE FAIL (checker should reject): "
              f"{description}")
        getattr(sys, "exit")(1)
    print(f"preset-combo-index: self-probe fired: {description} -> rejected")


def probe_accept(description, cpp_new):
    errors = check(strip_comments(cpp_new), HDR_TXT, PROC_TXT)
    if errors:
        print(f"preset-combo-index: SELF-PROBE FAIL (benign edit rejected): "
              f"{description} -> {errors[0]}")
        getattr(sys, "exit")(1)
    print(f"preset-combo-index: self-probe accepted: {description}")


# 1. the exact CV-021 defect: stock index-spreading attachment restored
probe("preset attachment reverted to stock ComboBoxAttachment",
      cpp_new=CPP_RAW.replace(
          'std::make_unique<PresetComboAttachment>(*audioProcessor.apvts.'
          'getParameter("preset"), presetSelector, '
          '&audioProcessor.undoManager)',
          'std::make_unique<juce::AudioProcessorValueTreeState'
          '::ComboBoxAttachment>(audioProcessor.apvts, "preset", '
          'presetSelector)', 1))

# 2. a separator row made selectable again (user can land on a dead id)
probe("WARM separator id 8 re-enabled",
      cpp_new=CPP_RAW.replace(
          'presetSelector.setItemEnabled(8, false);', '', 1))

# 3. a preset row id shifted (duplicate/missing id in the 1..42 space)
probe("Clean Sparkle preset id 2 disabled",
      cpp_new=CPP_RAW.replace(
          'presetSelector.addItem("Clean Sparkle", 2);',
          'presetSelector.addItem("Clean Sparkle", 2); '
          'presetSelector.setItemEnabled(2, false);', 1))

probe('"Solar Flare" item id 42 shifted to 41',
      cpp_new=CPP_RAW.replace(
          'presetSelector.addItem("Solar Flare", 42);',
          'presetSelector.addItem("Solar Flare", 41);', 1))

# 4. a separator label demoted to a preset-looking name
probe('DREAM separator label "--- DREAM ---" renamed to "Dream"',
      cpp_new=CPP_RAW.replace(
          'presetSelector.addItem("--- DREAM ---", 36);',
          'presetSelector.addItem("Dream", 36);', 1))

# 5. user -> parameter path switched to list-index semantics
probe("combo -> parameter path reads getSelectedItemIndex()",
      hdr_new=HDR_RAW.replace(
          'attachment.setValueAsCompleteGesture((float) '
          'comboBox.getSelectedId());',
          'attachment.setValueAsCompleteGesture((float) '
          'comboBox.getSelectedItemIndex());', 1))

# 6. listener teardown dropped (attachment outlives its combo)
probe("comboBox.removeListener(this) deleted",
      hdr_new=HDR_RAW.replace('comboBox.removeListener(this);', '', 1))

# 7. parameter -> combo path downgraded to a silent update
probe("parameter -> combo update switched to dontSendNotification",
      hdr_new=HDR_RAW.replace(
          'comboBox.setSelectedId(juce::roundToInt(rawItemId), '
          'juce::sendNotificationSync);',
          'comboBox.setSelectedId(juce::roundToInt(rawItemId), '
          'juce::dontSendNotification);', 1))

# 8. processor lookup swapped between two neighbouring preset ids
def mutate_id_to_preset(text):
    m = ID_TO_PRESET_RE.search(text)
    if not m:
        return text
    body_old = m.group(0)
    body_new = body_old.replace("-1,30,31,32,33,34,35",
                                "-1,31,30,32,33,34,35", 1)
    return text[:m.start()] + body_new + text[m.end():]


probe("idToPreset ids 30/31 swapped",
      proc_new=mutate_id_to_preset(PROC_RAW))

# 9. no-op guard: a harmless comment must stay accepted
probe_accept("benign comment added beside the preset attachment",
             CPP_RAW.replace(
                 'presetAtt = std::make_unique<PresetComboAttachment>(',
                 '// benign probe edit\n    presetAtt = '
                 'std::make_unique<PresetComboAttachment>(', 1))

# 10. no-op guard: a harmless trailing comment inside the item table
probe_accept("benign trailing comment on an addItem row",
             CPP_RAW.replace(
                 'presetSelector.addItem("Clean Sparkle", 2);',
                 'presetSelector.addItem("Clean Sparkle", 2); // benign', 1))

# 11. a separator row deleted outright (the 6-separator layout is pinned)
probe("CREATIVE separator row id 15 deleted",
      cpp_new=CPP_RAW.replace(
          'presetSelector.addItem("--- CREATIVE ---", 15);', '', 1))

print("PRESET-COMBO-INDEX OK")
