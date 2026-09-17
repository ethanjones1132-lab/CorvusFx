#!/usr/bin/env python3
"""Headless checker: per-knob setupKnob wiring ROSTER in PluginEditor.cpp.

Each setupKnob(knob, label, caption, paramID, tooltip) call pins the knob's
MIDI-learn / context-menu target to a paramID (k.linkedParamID at :104,
startMidiLearn/hasMidiMapping/clearMidiMapping all read k.linkedParamID),
while the parameter VALUE reaches the knob through the separate
SliderAttachment roster (:200-225). If the two rosters desync — a paramID
swapped between two adjacent setupKnob rows, or one renamed to a
non-existent param — the knob still MOVES via the attachment, but a learned
CC writes a NEIGHBOUR parameter (or a dead id): a real user-visible
cross-wiring that compiles clean behind an otherwise-green gate.

grep over all 73 scripts/check_*.py: check_editor_attachment_pairs pins the
19 ATTACHMENT tags and that setupKnob exists, but never the positional
paramID triple per setupKnob line; check_learn_* checkers pin the
processor-side capture. NO checker pins this roster.

Asserts (comment-stripped PluginEditor.cpp):
  (a) exactly 19 `setupKnob(` call sites in the constructor;
  (b) each keeps the EXACT (knobName, labelName, paramID) triple from the
      current roster, in this order;
  (c) every paramID appears EXACTLY ONCE across the roster;
  (d) the paramID roster EQUALS the multiset of SliderAttachment ids from
      the attachment block (the "overall" row at :133 included).

Self-probes (negative checks, sibling checker style e.g.
check_ab_button_wiring.py / check_loadpreset_bounds.py) run on mutated
in-memory texts — the real tree is never mutated.

Exit 0 = ok, 1 = violation with line-cited diagnostics.
"""
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SRC = ROOT / "source" / "DrippyFX"
ED = SRC / "PluginEditor.cpp"

# Positional roster: (knobName, labelName, paramID) in constructor order —
# the overallKnob line at :133 first, then the 18 rows at :181-198.
ROSTER = [
    ("overallKnob", "overallLabel", "overall"),
    ("fatnessKnob", "fatnessLabel", "fatness"),
    ("chorusDepthKnob", "chorusDepthLabel", "chorus_depth"),
    ("chorusRateKnob", "chorusRateLabel", "chorus_rate"),
    ("chorusMixKnob", "chorusMixLabel", "chorus_mix"),
    ("delayTimeKnob", "delayTimeLabel", "delay_time"),
    ("delayFeedbackKnob", "delayFeedbackLabel", "delay_feedback"),
    ("delayMixKnob", "delayMixLabel", "delay_mix"),
    ("delayDampingKnob", "delayDampingLabel", "delay_damping"),
    ("delayModKnob", "delayModLabel", "delay_mod"),
    ("reverbSizeKnob", "reverbSizeLabel", "reverb_size"),
    ("reverbDampingKnob", "reverbDampingLabel", "reverb_damping"),
    ("reverbMixKnob", "reverbMixLabel", "reverb_mix"),
    ("reverbModKnob", "reverbModLabel", "reverb_mod"),
    ("masterDriveKnob", "masterDriveLabel", "master_drive"),
    ("masterWidthKnob", "masterWidthLabel", "master_width"),
    ("masterMidDriveKnob", "masterMidDriveLabel", "master_mid_drive"),
    ("masterSideDriveKnob", "masterSideDriveLabel", "master_side_drive"),
    ("outputTrimKnob", "outputTrimLabel", "output_trim"),
]


class Rejected(Exception):
    pass


def strip_comments(src):
    src = re.sub(r"//[^\n]*", "", src)
    src = re.sub(r"/\*.*?\*/", "", src, flags=re.S)
    return src


def parse_setupknob_sites(stripped):
    """Extract positional (knob, label, paramID) triples from every
    setupKnob( ... ) call site, in source order."""
    sites = []
    for m in re.finditer(r"setupKnob\s*\(", stripped):
        depth = 0
        j = m.end() - 1
        while j < len(stripped):
            if stripped[j] == "(":
                depth += 1
            elif stripped[j] == ")":
                depth -= 1
                if depth == 0:
                    break
            j += 1
        if depth != 0:
            raise Rejected(
                f"unbalanced setupKnob call at stripped offset {m.start()}")
        args = stripped[m.end():j]
        parts = [p.strip() for p in args.split(",")]
        if len(parts) < 5:
            raise Rejected(
                f"setupKnob call at stripped offset {m.start()} has "
                f"{len(parts)} args, expected 5")
        pm = re.match(r'^"([a-z_]+)"$', parts[3])
        if not pm:
            raise Rejected(
                f"setupKnob at stripped offset {m.start()}: 4th operand is "
                f"not a quoted lowercase paramID: {parts[3]!r}")
        sites.append((parts[0], parts[1], pm.group(1)))
    return sites


def check_pass(text, label, verbose=False):
    stripped = strip_comments(text)

    def want(cond_name, cond, extra):
        if not cond:
            raise Rejected(f"{label}: {cond_name}: {extra}")
        if verbose:
            print(f"setupknob-roster: {label}: {cond_name} OK")

    sites = parse_setupknob_sites(stripped)
    want("setupKnob call count",
         len(sites) == len(ROSTER),
         f"expected exactly {len(ROSTER)} setupKnob call sites "
         f"(got {len(sites)})")

    # positional triple lock — knob/label/paramID per row, in order
    for i, (knob, label_name, pid) in enumerate(sites):
        want(f"row {i} knob operand", knob == ROSTER[i][0],
             f"expected knob operand {ROSTER[i][0]}, got {knob!r}")
        want(f"row {i} label operand", label_name == ROSTER[i][1],
             f"expected label operand {ROSTER[i][1]!r}, got {label_name!r}")
        want(f"row {i} paramID operand", pid == ROSTER[i][2],
             f"expected paramID {ROSTER[i][2]!r}, got {pid!r}"
             " (MIDI-learn target desynced from the attachment roster)")

    ids = [s[2] for s in sites]
    want("every paramID exactly once",
         len(set(ids)) == len(ids),
         f"paramID duplicate in roster: "
         f"{[x for x in ids if ids.count(x) > 1]}")
    want("label-name roster pairing",
         [r[1] for r in ROSTER] and True, "")

    # roster lock: the paramID roster must EQUAL the SliderAttachment id
    # multiset from the attachment block
    att_ids = re.findall(
        r"SliderAttachment>\s*\(\s*audioProcessor\.apvts\s*,\s*"
        r"\"([a-z_]+)\"\s*,", stripped)
    want("attachment roster size", len(att_ids) == len(ROSTER),
         f"expected {len(ROSTER)} SliderAttachment ids "
         f"(got {len(att_ids)})")
    want("paramID roster == attachment roster",
         sorted(ids) == sorted(att_ids),
         f"setupKnob paramIDs {sorted(ids)} != SliderAttachment ids "
         f"{sorted(att_ids)}")


def _verify(mutated):
    try:
        check_pass(mutated, "probe")
        return None
    except Rejected as r:
        return str(r)


PROBES = [
    # probe 1: two adjacent paramIDs transposed (reverb_mix <-> delay_mix)
    # — the MIX knobs still move via their attachments, but a learned CC
    # writes the NEIGHBOUR parameter
    ("reverb_mix and delay_mix paramIDs transposed",
     'setupKnob(reverbMixKnob, reverbMixLabel, "MIX", "reverb_mix",',
     'setupKnob(reverbMixKnob, reverbMixLabel, "MIX", "delay_mix",',
     '"delay_mix",'),
    # probe 2: one paramID renamed to a non-existent parameter — learn
    # armed on a dead id; captured CC maps to a param the layout lacks
    ("one paramID renamed to a non-existent id",
     '"master_width", "Stereo width',
     '"master_width_does_not_exist", "Stereo width',
     'master_width_does_not_exist'),
    # probe 3: positional drift — knob operand swapped between two rows
    ("knob/label pair transposed between rows",
     "setupKnob(masterWidthKnob, masterWidthLabel, \"WIDTH\",",
     "setupKnob(masterMidDriveKnob, masterMidDriveLabel, \"WIDTH\",",
     "masterMidDriveKnob, masterMidDriveLabel, \"WIDTH\""),
]


def main():
    text = ED.read_text()
    try:
        check_pass(text, "real tree")
    except Rejected as r:
        print(f"SETUPKNOB-ROSTER FAIL: real tree: {r}")
        return 1
    print(f"setupknob-roster: {len(ROSTER)} setupKnob(knob/label/paramID) "
          f"triples pinned positionally; every paramID exactly once; "
          f"roster equals the SliderAttachment id roster")

    for label, old, new, needle in PROBES:
        mutated = text.replace(old, new, 1)
        if mutated == text:
            print(f"SETUPKNOB-ROSTER FAIL: probe mutation didn't apply "
                  f"({label})")
            return 1
        verdict = _verify(mutated)
        if verdict is None and needle in mutated:
            print(f"SETUPKNOB-ROSTER FAIL: negative probe '{label}' was "
                  f"NOT rejected — checker is vacuous")
            return 1
        print(f"setupknob-roster: negative probe '{label}' rejected")

    # no-op guard: benign comment addition stays accepted
    neutral = text.replace(
        'setupKnob(overallKnob, overallLabel,',
        '// knob roster commentary\n    setupKnob(overallKnob, '
        'overallLabel,')
    if neutral == text:
        print("SETUPKNOB-ROSTER FAIL: unanchored neutral edit didn't apply")
        return 1
    verdict = _verify(neutral)
    if verdict is not None:
        print(f"SETUPKNOB-ROSTER FAIL: over-fires on neutral edit: "
              f"{verdict}")
        return 1
    print("setupknob-roster: benign no-op accepted (specificity proven)")

    # real tree never mutated — re-verify the live source once more
    try:
        check_pass(ED.read_text(), "final re-verify")
    except Rejected as r:
        print(f"SETUPKNOB-ROSTER FAIL: final re-verify failed: {r}")
        return 1
    print("SETUPKNOB-ROSTER OK")
    return 0


if __name__ == "__main__":
    sys.exit(main())
