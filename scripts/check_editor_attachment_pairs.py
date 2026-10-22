#!/usr/bin/env python3
"""Headless checker: editor setupKnob/APVTS-attachment id pairing pin.

PluginEditor.cpp hand-maintains the SAME 19 param ids in two places:
  - 19 `setupKnob(<knob>, <label>, "<TXT>", "<param-id>", "<tooltip>")`
    calls (:133 plus :181-198) whose 4th arg seeds `k.linkedParamID`
    (right-click MIDI-Learn reads it at :119/121);
  - 19 `juce::AudioProcessorValueTreeState::SliderAttachment` declarations
    (:200-224 block) whose 2nd arg links the knob to apvts.
Plus 5 ButtonAttachment ids (one per "<module>_bypass") and the single
PresetComboAttachment wiring "preset" to presetSelector. That attachment is
deliberately NOT the stock ComboBoxAttachment: the preset parameter stores the
combo item ID (1-42, separators included), not a zero-based list index, so an
index-spreading attachment would shift every selection by one row.

No other checker cross-checks the two lists (check_undo_wiring.py pins only
setupKnob's onGestureStart lambda): editing a setupKnob 4th arg to a
different id leaves the SliderAttachment still driving the same juce
component, so armed MIDI-Learn learns/steers a DIFFERENT parameter than the
knob's attachment moves — silently mapping the wrong knob; and deleting one
SliderAttachment line loses the apvts linkage while the tooltip still
advertises it. Both compile clean behind an otherwise-green gate.

Asserts (comment-stripped PluginEditor.cpp):
  (a) exactly 19 setupKnob( calls, each carrying a quoted "<param-id>" as
      its 4th argument;
  (b) the 19-id set from setupKnob EQUALS the 19-id set from
      SliderAttachment second-arg ids, in matching call/declaration ORDER;
  (c) the 5 "<module>_bypass" ids each appear in exactly one
      ButtonAttachment;
  (d) exactly one PresetComboAttachment wires the "preset" parameter to
      presetSelector through the processor's undo manager, and the stock
      AudioProcessorValueTreeState::ComboBoxAttachment (whose zero-based item
      INDEX mapping shifts every preset selection by one row) is gone from the
      editor entirely.

Self-probes (negative checks, sibling checker style) run on mutated
in-memory TEMP texts — the real tree is never mutated. A no-op mutation
guard skips probes whose mutation didn't apply.

Exit 0 = ok, 1 = violation with line-cited diagnostics.
"""
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SRC = ROOT / "source" / "DrippyFX"
ED = SRC / "PluginEditor.cpp"

SETUPKNOB_RE = re.compile(
    r'setupKnob\(\s*[\w.]+\s*,\s*[\w.]+\s*,\s*"[^"]*"\s*,\s*"([^"]+)"')
SLIDER_ATT_RE = re.compile(
    r'AudioProcessorValueTreeState::SliderAttachment>\(\s*'
    r'audioProcessor\.apvts\s*,\s*"([^"]+)"')
BUTTON_ATT_RE = re.compile(
    r'AudioProcessorValueTreeState::ButtonAttachment>\(\s*'
    r'audioProcessor\.apvts\s*,\s*"([^"]+)"')
COMBO_ATT_RE = re.compile(
    r'PresetComboAttachment>\(\s*\*\s*audioProcessor\.apvts\.getParameter'
    r'\(\s*"([^"]+)"\s*\)\s*,\s*presetSelector\s*,\s*'
    r'&audioProcessor\.undoManager\s*\)')
STOCK_COMBO_ATT_RE = re.compile(
    r'AudioProcessorValueTreeState::ComboBoxAttachment')

EXPECTED_ORDER = [
    "overall", "fatness",
    "chorus_depth", "chorus_rate", "chorus_mix",
    "delay_time", "delay_feedback", "delay_mix", "delay_damping",
    "delay_mod",
    "reverb_size", "reverb_damping", "reverb_mix", "reverb_mod",
    "master_drive", "master_width", "master_mid_drive", "master_side_drive",
    "output_trim",
]
EXPECTED_BYPASS = [
    "distortion_bypass", "chorus_bypass", "delay_bypass",
    "reverb_bypass", "master_bypass",
]


def fail(msg):
    print(f"EDITOR-ATTACH-PAIRS FAIL: {msg}")
    sys.exit(1)


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


def check(txt_stripped):
    """Return None if ok, else a diagnostic string."""
    knob_ids = SETUPKNOB_RE.findall(txt_stripped)
    if len(knob_ids) != 19:
        return (f"expected exactly 19 setupKnob( calls with a quoted 4th "
                f"param id, found {len(knob_ids)}")
    att_ids = SLIDER_ATT_RE.findall(txt_stripped)
    if len(att_ids) != 19:
        return (f"expected exactly 19 SliderAttachment declarations, "
                f"found {len(att_ids)}")
    if knob_ids != att_ids:
        return ("setupKnob 4th-arg id list does not match the "
                "SliderAttachment 2nd-arg id list in ORDER: "
                f"knobs={knob_ids} vs attachments={att_ids}")
    if knob_ids != EXPECTED_ORDER:
        return (f"knob id order drifted from the expected roster: "
                f"{knob_ids}")
    btn_ids = BUTTON_ATT_RE.findall(txt_stripped)
    if sorted(btn_ids) != sorted(EXPECTED_BYPASS):
        return (f"ButtonAttachment ids must be exactly the 5 bypass ids "
                f"{EXPECTED_BYPASS}, got {btn_ids}")
    if len(set(btn_ids)) != len(btn_ids):
        return "a bypass id appears in more than one ButtonAttachment"
    combo_ids = COMBO_ATT_RE.findall(txt_stripped)
    if combo_ids != ["preset"]:
        return (f"PresetComboAttachment must wire exactly the 'preset' "
                f"parameter to presetSelector via &audioProcessor.undoManager, "
                f"got {combo_ids}")
    if STOCK_COMBO_ATT_RE.search(txt_stripped):
        return ("stock AudioProcessorValueTreeState::ComboBoxAttachment is "
                "back in PluginEditor.cpp; it maps the combo item INDEX, not "
                "the preset item id, shifting every selection by one row")
    return None


if not ED.exists():
    fail(f"missing source file {ED}")
ed_txt = strip_comments(ED.read_text(encoding="utf-8"))
err = check(ed_txt)
if err:
    fail(err + " (PluginEditor.cpp)")
print("editor-attach-pairs: 19 setupKnob ids == 19 SliderAttachment ids "
      "(same order), 5 ButtonAttachment bypass ids, item-id "
      "PresetComboAttachment 'preset' pinned (stock ComboBoxAttachment "
      "banned) in PluginEditor.cpp")

# ---------------------------------------------------------------------------
# Self-probes on mutated in-memory texts (real tree never mutated)
# ---------------------------------------------------------------------------

def probe(description, old, new, count=1):
    tmp_raw = ED.read_text(encoding="utf-8").replace(old, new, count)
    if tmp_raw == ED.read_text(encoding="utf-8"):
        print(f"editor-attach-pairs: no-op mutation guard -> skipping "
              f"invalid probe ({description})")
        return
    if check(strip_comments(tmp_raw)) is None:
        print(f"editor-attach-pairs: SELF-PROBE FAIL (checker should "
              f"reject): {description}")
        sys.exit(1)
    print(f"editor-attach-pairs: self-probe fired: {description} -> "
          f"rejected")


# 1. setupKnob 4th arg swapped to a DIFFERENT id (wrong-id hazard: MIDI-learn
#    would learn/steer a different parameter than the attachment moves)
probe('setupKnob id "chorus_mix" swapped to "chorus_depth"',
      '"MIX", "chorus_mix", "Chorus wet/dry balance',
      '"MIX", "chorus_depth", "Chorus wet/dry balance')

# 2. one SliderAttachment declaration deleted (lost apvts linkage)
probe("cMixAtt SliderAttachment line deleted",
      'cMixAtt = std::make_unique<juce::AudioProcessorValueTreeState'
      '::SliderAttachment>(audioProcessor.apvts, "chorus_mix", '
      'chorusMixKnob);\n    ', '')

# 3. SliderAttachment id order swapped between two declarations (linkage
#    order pin)
probe('rMixAtt/rModAtt attachment ids swapped',
      'AudioProcessorValueTreeState::SliderAttachment>(audioProcessor.'
      'apvts, "reverb_mix", rMixAtt'.replace("rMixAtt", "reverbMixKnob"),
      'AudioProcessorValueTreeState::SliderAttachment>(audioProcessor.'
      'apvts, "reverb_mod", rMixAtt'.replace("rMixAtt", "reverbMixKnob"))

# 4. the preset attachment reverted to the stock index-spreading
#    ComboBoxAttachment (the CV-021 defect: every selection shifts one row)
probe("preset attachment reverted to stock ComboBoxAttachment",
      'presetAtt = std::make_unique<PresetComboAttachment>('
      '*audioProcessor.apvts.getParameter("preset"), presetSelector, '
      '&audioProcessor.undoManager);',
      'presetAtt = std::make_unique<juce::AudioProcessorValueTreeState'
      '::ComboBoxAttachment>(audioProcessor.apvts, "preset", '
      'presetSelector);')

# 5. the pass-through attachment dropped entirely (combo silently unsynced
#    from the "preset" parameter)
probe("PresetComboAttachment wiring line deleted",
      'presetAtt = std::make_unique<PresetComboAttachment>('
      '*audioProcessor.apvts.getParameter("preset"), presetSelector, '
      '&audioProcessor.undoManager);', '')

# 6. no-op guard: benign comment addition must stay accepted
tmp = ED.read_text(encoding="utf-8").replace(
    "// Attachments\n", "// Attachments\n// benign probe edit\n", 1)
if tmp == ED.read_text(encoding="utf-8"):
    print("editor-attach-pairs: no-op probe skipped")
elif check(strip_comments(tmp)) is not None:
    fail("no-op guard: benign edit was wrongly rejected")
print("editor-attach-pairs: no-op guard passed (benign edit accepted)")

print("EDITOR-ATTACH-PAIRS OK")
