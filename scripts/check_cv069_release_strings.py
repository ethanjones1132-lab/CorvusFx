#!/usr/bin/env python3
"""CV-069: release truth - every string a buyer can read matches the ship.

Two classes of lie reached the v1.0 build:

  (1) mojibake. The preset selector's tooltip, the five bypass tooltips and
      seventeen knob tooltips ended in a separator that had been re-encoded
      through cp1252 several times ("byte soup"). The tooltip window draws those
      bytes in the middle of an otherwise English sentence. CV-069 makes every
      row carry plain ASCII copy again and parks the old bytes in a trailing
      "CV-069 superseded" comment, which no code reads.
  (2) promises. `btnSlotA`'s tooltip advertised "recall slot A (spacebar)"
      while CorvusFXAudioProcessorEditor::keyPressed binds only Ctrl/Cmd+Z,
      Ctrl+Y, Ctrl+T and Alt+R. The A/B buttons are click-only; the copy says so
      now.

The documents change to match the code, never the other way round:

  (a) the delay's ping-pong spread is the literal `const float pingPong = 0.35f`
      in PluginProcessor.cpp - there is no spread parameter and no spread knob.
      README's delay table promised "adjustable spread"; it states the fixed
      0.35 and claims no control.
  (b) output_trim is registered through the shared pctParam helper (0..100,
      default 100), which is what README already stated. ROADMAP and PRIORITIES
      advertised 0-200% - a range the parameter cannot reach.
  (c) an A/B snapshot covers NUM_AB_PARAMS parameters (24, matching
      abParamIds[]). README said 24; ROADMAP said 23 twice and PRIORITIES said
      23 once.

Asserts:
  (i)   no non-comment character in PluginEditor.cpp is outside printable ASCII
        (a mojibake byte in a string literal or an identifier is a hard fail),
        and every tooltip that is effective on a component - a setupKnob
        tooltip argument or a later setTooltip, whichever comes last - is plain
        ASCII and non-empty;
  (ii)  no effective tooltip promises a spacebar recall unless keyPressed()
        really binds the space key - and if it does bind it, no tooltip may
        still claim there is no keyboard shortcut;
  (iii) both A/B buttons say the recall is a click (that is their only input);
  (iv)  every document line that mentions a "spread" states the 0.35 the delay
        block uses and promises no adjustable/spread knob or slider;
  (v)   the README parameter row, ROADMAP and PRIORITIES state the registered
        0..100% Output Trim range and default;
  (vi)  README, ROADMAP and PRIORITIES state the NUM_AB_PARAMS count, and
        abParamIds[] is that long.

Self-probes (negative checks on mutated in-memory texts; the real tree is never
mutated). Each mutation must be rejected:
  - mojibake restored inside the Output Trim tooltip;
  - mojibake restored inside the preset selector's tooltip;
  - "(spacebar)" promised on slot A again;
  - a space-key binding added to keyPressed, which falsifies the click-only copy;
  - README's ping-pong row promises an adjustable spread;
  - README's ping-pong row states a spread the delay block does not use;
  - ROADMAP restores the 0-200% Output Trim range;
  - PRIORITIES restores the 0-200% Output Trim range;
  - README's Output Trim table row widens to 0-200%;
  - Output Trim's default comes from the wrong factory field;
  - ROADMAP restores the 23-parameter A/B count;
  - PRIORITIES restores the 23-param randomization count.
A specificity probe rewords one tooltip without changing any fact and must stay
accepted. The live tree is re-read and re-verified at the end, so a second run on
clean source is green by construction.

Exit 0 = ok, 1 = violation with diagnostics.
"""

import re
import sys
from pathlib import Path

from _fx_factory_defaults import factory_default

ROOT = Path(__file__).resolve().parent.parent
SRC = ROOT / "source" / "DrippyFX"
ED = SRC / "PluginEditor.cpp"
PROC = SRC / "PluginProcessor.cpp"
HDR = SRC / "PluginProcessor.h"
README = ROOT / "README.md"
ROADMAP = ROOT / "ROADMAP.md"
PRIORITIES = ROOT / "PRIORITIES.md"
EDITOR = "CorvusFXAudioProcessorEditor"

# A tooltip (or any other Component copy) that a buyer can read.
SETTOOLTIP_RE = re.compile(
    r'([A-Za-z_]\w*)\s*\.\s*setTooltip\s*\(\s*"((?:[^"\\]|\\.)*)"\s*\)')
# setupKnob(knob, label, "CAPTION", "paramID", "tooltip") - the editor's own
# tooltip argument, which is what the tooltip block shipped before CV-069.
SETUPKNOB_RE = re.compile(
    r'setupKnob\s*\(\s*(\w+)\s*,\s*\w+\s*,\s*"([^"]*)"\s*,\s*"([^"]*)"\s*,'
    r'\s*"((?:[^"\\]|\\.)*)"\s*\)')
KEYPRESSED_RE = (rf"bool\s+{EDITOR}::keyPressed\s*\(\s*"
                 rf"const\s+juce::KeyPress\s*&\s*\w+\s*\)")
SPACE_BIND_RE = re.compile(
    r"KeyPress\s*::\s*spaceKey|getKeyCode\s*\(\s*\)\s*==\s*'\s?'")
SPACE_PROMISE_RE = re.compile(r"space\s*bar|spacebar|space\s+key|\(space\)",
                             re.I)
NO_SHORTCUT_RE = re.compile(r"no\s+keyboard\s+shortcut", re.I)

PINGPONG_RE = re.compile(r"const\s+float\s+pingPong\s*=\s*([0-9.]+)f\s*;")
PCTPARAM_RANGE_RE = re.compile(
    r"auto\s+pctParam\s*=[^{]*\{[^{}]*?NormalisableRange<float>\s*\(\s*"
    r"([-0-9.]+)\s*,\s*([-0-9.]+)", re.S)
TRIM_RE = re.compile(
    r'\bpctParam\s*\(\s*"output_trim"\s*,\s*"([^"]*)"\s*,\s*p\.(\w+)\s*\)')
NUMAB_RE = re.compile(r"NUM_AB_PARAMS\s*=\s*(\d+)\s*;")
ABIDS_RE = re.compile(
    r"abParamIds\s*\[\s*(\d+)\s*\]\s*=\s*\{(.*?)\}", re.S)

README_PINGPONG_ROW_RE = re.compile(
    r"^\|\s*\*\*Ping-pong\*\*\s*\|\s*([^|]*)\|", re.M)
README_TRIM_ROW_RE = re.compile(
    r"^\|[ \t]*\*\*Output Trim\*\*[ \t]*\|[ \t]*([^|\n]*)\|"
    r"[ \t]*([^|\n]*)\|[ \t]*([^|\n]*)\|[ \t]*$", re.M)
README_SNAPSHOT_RE = re.compile(r"all\s+(\d+)\s+non-preset\s+parameters")
ROADMAP_SNAPSHOT_RE = re.compile(r"snapshot/restore\s+(\d+)\s+parameters")
PARAM_RANDOMIZE_RE = re.compile(r"(\d+)-param\s+randomization")

ADJUSTABLE_RE = re.compile(r"adjustab|\bknob\b|\bslider\b", re.I)
SPREAD_RE = re.compile(r"\bspread\b", re.I)
TRIM_MENTION_RE = re.compile(r"output[\s_]?trim", re.I)


# ---------------------------------------------------------------------------
# helpers
# ---------------------------------------------------------------------------
def read_source(path):
    """Read as LF-normalised UTF-8 (CRLF must not move any anchor)."""
    return path.read_text(encoding="utf-8", errors="replace").replace(
        "\r\n", "\n")


def blank_comments(text):
    """Blank comment characters, keeping offsets and newlines stable."""
    def block(match):
        return "".join("\n" if ch == "\n" else " " for ch in match.group(0))
    text = re.sub(r"/\*.*?\*/", block, text, flags=re.S)
    return re.sub(r"//[^\n]*", lambda m: " " * len(m.group(0)), text)


def braced_span(text, opening):
    depth = 0
    for i in range(opening, len(text)):
        if text[i] == "{":
            depth += 1
        elif text[i] == "}":
            depth -= 1
            if depth == 0:
                return opening, i + 1
    return None


def function_span(code, pattern):
    """Absolute (inner_start, inner_end) of the first matching body, or None."""
    match = re.search(pattern, code, flags=re.S)
    if not match:
        return None
    opening = code.find("{", match.end() - 1)
    if opening < 0:
        return None
    span = braced_span(code, opening)
    if span is None:
        return None
    return span[0] + 1, span[1] - 1


def plain_ascii(text):
    """True when every character is printable ASCII (32..126).

    Mojibake is never plain ASCII: the double-encoded separators carry U+00C3 /
    U+00C2 / U+00E2 sequences, U+00A0 no-break spaces and C1 control characters
    that the tooltip window paints as visible garbage.
    """
    return all(0x20 <= ord(ch) < 0x7F for ch in text)


def percents(text):
    """Every `NN%` / `NN.N%` number in a copy string, as floats."""
    return [float(m) for m in re.findall(r"(\d+(?:\.\d+)?)\s*%", text)]


def range_bounds(cell):
    """Bounds of a cell such as `0-100%` / `0-200%` (ASCII or en/em dash)."""
    bounds = []
    for part in re.split(r"[-\u2013\u2014]", cell):
        m = re.search(r"(\d+(?:\.\d+)?)\s*%?", part)
        if m:
            bounds.append(float(m.group(1)))
    return bounds


def range_pairs(line):
    """Every `A-B%` span in a line, as (low, high) float pairs."""
    pairs = []
    for m in re.finditer(r"(\d+(?:\.\d+)?)\s*[-\u2013\u2014]\s*"
                         r"(\d+(?:\.\d+)?)\s*%", line):
        pairs.append((float(m.group(1)), float(m.group(2))))
    return pairs


def effective_tooltips(ed_code):
    """component -> every tooltip literal set on it, in source order.

    Two sources bind tooltip copy: the `"..."` argument of a setupKnob row (what
    the constructor's tooltip block passes) and an explicit setTooltip("...")
    call. Whichever comes LAST in the constructor is the text a buyer reads.
    """
    events = []
    for m in SETUPKNOB_RE.finditer(ed_code):
        events.append((m.start(), m.group(1), m.group(4)))
    for m in SETTOOLTIP_RE.finditer(ed_code):
        events.append((m.start(), m.group(1), m.group(2)))
    events.sort(key=lambda event: event[0])
    history = {}
    for _pos, obj, shown in events:
        history.setdefault(obj, []).append(shown)
    return history


# ---------------------------------------------------------------------------
# the assertions
# ---------------------------------------------------------------------------
def verify(ed, proc, hdr, readme, roadmap, priorities):
    """Return the list of violated CV-069 assertions (empty means pass)."""
    errors = []
    ed_code = blank_comments(ed)
    proc_code = blank_comments(proc)

    # ---- (i) the copy a buyer reads is plain ASCII ------------------------
    for lineno, line in enumerate(ed_code.splitlines(), 1):
        stray = sorted({ch for ch in line
                        if ord(ch) > 0x7E or (ord(ch) < 0x20 and ch != "\t")})
        if stray:
            shown = ", ".join(f"U+{ord(ch):04X}" for ch in stray)
            errors.append(f"PluginEditor.cpp:{lineno} carries non-ASCII/"
                          f"control characters outside any comment ({shown}) - "
                          "mojibake in a shipped string")

    tips = effective_tooltips(ed_code)
    if not tips:
        errors.append('PluginEditor.cpp binds no tooltip copy at all (neither '
                      "a setupKnob tooltip argument nor a setTooltip call) - "
                      "the buyer-facing copy cannot be verified")
    for obj in sorted(tips):
        shown = tips[obj][-1]
        if not shown.strip():
            errors.append(f"{obj}'s tooltip is empty - a control shipped with "
                          "no description")
        elif not plain_ascii(shown):
            errors.append(f"{obj}'s effective tooltip is not plain ASCII, so "
                          f"mojibake reaches the tooltip window: {shown!r}")

    # ---- (ii) the spacebar promise ---------------------------------------
    kp_span = function_span(ed_code, KEYPRESSED_RE)
    if kp_span is None:
        has_space = False
        errors.append(f"PluginEditor.cpp has no {EDITOR}::keyPressed(const "
                      "juce::KeyPress&) body - shortcut claims in the copy "
                      "cannot be verified")
    else:
        kp = ed_code[kp_span[0]:kp_span[1]]
        has_space = bool(SPACE_BIND_RE.search(kp))

    for obj in sorted(tips):
        shown = tips[obj][-1]
        if SPACE_PROMISE_RE.search(shown) and not has_space:
            errors.append(f"{obj}'s tooltip promises a spacebar recall, but "
                          f"keyPressed() binds no space key: {shown!r}")
        if has_space and NO_SHORTCUT_RE.search(shown):
            errors.append(f"{obj}'s tooltip says there is no keyboard "
                          f"shortcut, but keyPressed() binds the space key: "
                          f"{shown!r}")

    # ---- (iii) the A/B buttons are mouse-only ----------------------------
    for btn in ("btnSlotA", "btnSlotB"):
        shown = tips.get(btn, [""])[-1]
        if btn not in tips:
            errors.append(f"{btn} has no tooltip - the recall is a click and "
                          "the copy must say so")
        elif not re.search(r"\bclick", shown, re.I):
            errors.append(f"{btn}'s tooltip does not say the recall is a "
                          f"click: {shown!r}")

    # ---- (iv) the documented ping-pong spread ----------------------------
    pp = PINGPONG_RE.search(proc_code)
    if pp is None:
        errors.append("PluginProcessor.cpp no longer defines `const float "
                      "pingPong = <x>f;` - the documented spread has no code "
                      "fact to match")
    else:
        spread = float(pp.group(1))
        row = README_PINGPONG_ROW_RE.search(readme)
        if row is None:
            errors.append("README's delay table has no `| **Ping-pong** |` row "
                          "- the spread it ships with is undocumented")
        else:
            cell = row.group(1)
            if f"{spread:g}" not in cell:
                errors.append(f"README's ping-pong row never states the "
                              f"{spread:g} spread the delay block uses: "
                              f"{cell.strip()!r}")
            if not re.search(r"\bfixed\b", cell, re.I):
                errors.append("README's ping-pong row does not say the spread "
                              f"is fixed: {cell.strip()!r}")
        for name, doc in (("README.md", readme), ("ROADMAP.md", roadmap),
                          ("PRIORITIES.md", priorities)):
            for lineno, line in enumerate(doc.splitlines(), 1):
                if not SPREAD_RE.search(line):
                    continue
                if f"{spread:g}" not in line:
                    errors.append(f"{name}:{lineno} mentions a spread but not "
                                  f"the {spread:g} the delay block uses: "
                                  f"{line.strip()[:120]!r}")
                if ADJUSTABLE_RE.search(line):
                    errors.append(f"{name}:{lineno} promises a spread control "
                                  "the plugin does not have: "
                                  f"{line.strip()[:120]!r}")

    # ---- (v) the documented Output Trim range ---------------------------
    helper = PCTPARAM_RANGE_RE.search(proc_code)
    trim = TRIM_RE.search(proc_code)
    if helper is None:
        errors.append("could not read the shared pctParam range out of "
                      "PluginProcessor.cpp - the Output Trim range has no "
                      "code fact to match")
    if trim is None:
        errors.append('PluginProcessor.cpp no longer registers "output_trim" '
                      "through pctParam(...) with a factory default")
    if helper is not None and trim is not None:
        trim_name = trim.group(1)
        try:
            trim_default = factory_default(proc_code, trim.group(2))
        except ValueError as exc:
            errors.append(f"could not read the Output Trim default: {exc}")
            trim_default = None
        lo, hi = float(helper.group(1)), float(helper.group(2))
        if trim_name != "Output Trim":
            errors.append(f'host-visible name for "output_trim" is '
                          f"{trim_name!r}, expected 'Output Trim'")

        row = README_TRIM_ROW_RE.search(readme)
        if row is None:
            errors.append("README's parameter table has no "
                          "`| **Output Trim** |` row")
        else:
            bounds = range_bounds(row.group(1))
            if len(bounds) < 2:
                errors.append("README's Output Trim row states no range: "
                              f"{row.group(1).strip()!r}")
            elif (abs(bounds[0] - lo) > 1e-6
                  or abs(bounds[-1] - hi) > 1e-6):
                errors.append(f"README's Output Trim row states "
                              f"{row.group(1).strip()!r}, the parameter is "
                              f"{lo:g}-{hi:g}%")
            defaults = percents(row.group(2))
            if trim_default is not None and (
                    len(defaults) != 1 or abs(defaults[0] - trim_default) > 1e-6):
                errors.append("README's Output Trim row states default "
                              f"{row.group(2).strip()!r}, the parameter "
                              f"defaults to {trim_default:g}%")

        for name, doc in (("README.md", readme), ("ROADMAP.md", roadmap),
                          ("PRIORITIES.md", priorities)):
            for lineno, line in enumerate(doc.splitlines(), 1):
                if not TRIM_MENTION_RE.search(line):
                    continue
                for value in percents(line):
                    if value < lo - 1e-6 or value > hi + 1e-6:
                        errors.append(f"{name}:{lineno} gives Output Trim "
                                      f"{value:g}%, outside the registered "
                                      f"{lo:g}-{hi:g}% range: "
                                      f"{line.strip()[:120]!r}")
                for low, high in range_pairs(line):
                    if low < lo - 1e-6 or high > hi + 1e-6:
                        errors.append(f"{name}:{lineno} states an Output Trim "
                                      f"range of {low:g}-{high:g}%, the "
                                      f"parameter is {lo:g}-{hi:g}%: "
                                      f"{line.strip()[:120]!r}")

        for name, doc in (("ROADMAP.md", roadmap),
                          ("PRIORITIES.md", priorities)):
            lines = [ln for ln in doc.splitlines()
                     if TRIM_MENTION_RE.search(ln)]
            if not lines:
                errors.append(f"{name} no longer mentions Output Trim - the "
                              "milestone record was dropped")
            elif not any(f"{lo:g}-{hi:g}%" in ln for ln in lines):
                errors.append(f"{name}'s Output Trim milestone never states "
                              f"the registered {lo:g}-{hi:g}% range")

    # ---- (vi) the A/B snapshot count ------------------------------------
    nab = NUMAB_RE.search(hdr)
    if nab is None:
        errors.append("PluginProcessor.h no longer declares NUM_AB_PARAMS - "
                      "the documented snapshot count has no code fact to match")
    else:
        count = int(nab.group(1))
        abids = ABIDS_RE.search(proc_code)
        if abids is None:
            errors.append("PluginProcessor.cpp has no abParamIds[] initialiser "
                          "- the snapshot roster cannot be counted")
        else:
            declared = int(abids.group(1))
            ids = re.findall(r'"([^"]*)"', abids.group(2))
            if declared != count or len(ids) != count:
                errors.append(f"abParamIds[{declared}] holds {len(ids)} ids but "
                              f"NUM_AB_PARAMS is {count} - the snapshot roster "
                              "and the documented count disagree")

        snap = README_SNAPSHOT_RE.search(readme)
        if snap is None:
            errors.append("README's Preset A/B Compare row no longer says how "
                          "many parameters a snapshot covers")
        elif int(snap.group(1)) != count:
            errors.append(f"README says a snapshot covers {snap.group(1)} "
                          f"parameters, NUM_AB_PARAMS is {count}")

        roadmap_snap = ROADMAP_SNAPSHOT_RE.search(roadmap)
        if roadmap_snap is None:
            errors.append("ROADMAP's Preset A/B compare milestone no longer "
                          "states the snapshot size")
        elif int(roadmap_snap.group(1)) != count:
            errors.append(f"ROADMAP says snapshots cover "
                          f"{roadmap_snap.group(1)} parameters, NUM_AB_PARAMS "
                          f"is {count}")

        for name, doc in (("ROADMAP.md", roadmap),
                          ("PRIORITIES.md", priorities)):
            seen = PARAM_RANDOMIZE_RE.findall(doc)
            if not seen:
                errors.append(f"{name} no longer states the randomization "
                              "size")
                continue
            for value in seen:
                if int(value) != count:
                    errors.append(f"{name} says randomization touches {value} "
                                  f"parameters, NUM_AB_PARAMS is {count}")

    return errors


# ---------------------------------------------------------------------------
# negative self-probes on mutated in-memory texts (real tree never mutated)
# ---------------------------------------------------------------------------
TRIM_TOOLTIP = ('"Output level trim - 0% = silent, 100% = unity gain");')
PRESET_TOOLTIP = ('"Select factory preset - 36 curated sounds from clean '
                  'enhancement to deep ambient soundscapes");')
SLOT_A_TIP = ("btnSlotA.setTooltip(\"Preset snapshot A - click the A button "
              "to recall it (no keyboard shortcut)\");")


def in_editor(old, new):
    def mutate(ed, proc, hdr, readme, roadmap, priorities):
        if old not in ed:
            return None
        return (ed.replace(old, new, 1), proc, hdr, readme, roadmap,
                priorities)
    return mutate


def in_processor(old, new):
    def mutate(ed, proc, hdr, readme, roadmap, priorities):
        return (ed, proc.replace(old, new, 1), hdr, readme, roadmap, priorities)
    return mutate


def in_readme(old, new):
    def mutate(ed, proc, hdr, readme, roadmap, priorities):
        if old not in readme:
            return None
        return (ed, proc, hdr, readme.replace(old, new, 1), roadmap, priorities)
    return mutate


def in_roadmap(old, new):
    def mutate(ed, proc, hdr, readme, roadmap, priorities):
        if old not in roadmap:
            return None
        return (ed, proc, hdr, readme, roadmap.replace(old, new, 1), priorities)
    return mutate


def in_priorities(old, new):
    def mutate(ed, proc, hdr, readme, roadmap, priorities):
        if old not in priorities:
            return None
        return (ed, proc, hdr, readme, roadmap, priorities.replace(old, new, 1))
    return mutate


def widen_readme_trim_row(ed, proc, hdr, readme, roadmap, priorities):
    """README's Output Trim table row promises 0-200% again."""
    match = README_TRIM_ROW_RE.search(readme)
    if match is None:
        return None
    cell = " 0\u2013200% "
    mutated = (readme[:match.start(1)] + cell + readme[match.end(1):])
    return (ed, proc, hdr, mutated, roadmap, priorities)


PROBES = [
    ("mojibake restored inside the Output Trim tooltip",
     in_editor(TRIM_TOOLTIP,
               '"Output level trim \u00c3\u00a2\u00e2\u201a\u00ac\u00e2\u201e'
               '\u00a2 0% = silent, 100% = unity gain");')),
    ("mojibake restored inside the preset selector's tooltip",
     in_editor(PRESET_TOOLTIP,
               '"Select factory preset \u00c3\u00a2\u00e2\u201a\u00ac\u00e2'
               '\u201e\u00a2 36 curated sounds from clean enhancement to deep '
               'ambient soundscapes");')),
    ("slot A promises a spacebar recall again",
     in_editor(SLOT_A_TIP,
               'btnSlotA.setTooltip("Active slot A / recall slot A '
               '(spacebar)");')),
    ("keyPressed binds the space key while the copy says there is none",
     in_editor("    auto& um = audioProcessor.undoManager;",
               "    if (key.getKeyCode() == juce::KeyPress::spaceKey) "
               "return true;\n    auto& um = audioProcessor.undoManager;")),
    ("README promises an adjustable ping-pong spread",
     in_readme("Stereo ping-pong mode with a fixed 0.35 feedback spread "
               "(no spread control)",
               "Stereo ping-pong mode with a fixed 0.35 feedback spread and an "
               "adjustable spread knob")),
    ("README states a ping-pong spread the delay block does not use",
     in_readme("fixed 0.35 feedback spread", "fixed 0.75 feedback spread")),
    ("ROADMAP restores the 0-200% Output Trim range",
     in_roadmap("0-100%, UI TRIM knob", "0-200%, UI TRIM knob")),
    ("PRIORITIES restores the 0-200% Output Trim range",
     in_priorities("(0-100%, smooth, UI knob)", "(0-200%, smooth, UI knob)")),
    ("README's Output Trim table row widens to 0-200%",
     widen_readme_trim_row),
    ("Output Trim's default comes from the wrong factory field",
     in_processor('pctParam("output_trim", "Output Trim", p.oTrim)',
                  'pctParam("output_trim", "Output Trim", p.mDrv)')),
    ("ROADMAP restores the 23-parameter A/B count",
     in_roadmap("snapshot/restore 24 parameters",
                "snapshot/restore 23 parameters")),
    ("PRIORITIES restores the 23-param randomization count",
     in_priorities("24-param randomization", "23-param randomization")),
]

# A reword that changes no fact: must stay green (specificity guard).
NEUTRAL_OLD = "Bypass the distortion module entirely - click-free crossfade"
NEUTRAL_NEW = "Bypass the distortion module entirely - click-free cross-fade"


def load():
    return (read_source(ED), read_source(PROC), read_source(HDR),
            read_source(README), read_source(ROADMAP),
            read_source(PRIORITIES))


def main():
    base = load()

    errors = verify(*base)
    if errors:
        print("CV-069 FAIL: the copy a buyer reads does not match the ship:")
        for error in errors:
            print(f"  - {error}")
        return 1

    print("CV-069 OK: PluginEditor.cpp carries no non-ASCII byte outside a "
          "comment, and every effective tooltip is plain ASCII (the "
          "preset/bypass/knob copy a buyer reads)")
    print("CV-069 OK: no tooltip promises a spacebar; keyPressed() binds "
          "Ctrl/Cmd+Z, Ctrl+Y, Ctrl+T and Alt+R only, and both A/B buttons say "
          "the recall is a click")
    print("CV-069 OK: README states the delay's fixed 0.35 ping-pong spread and "
          "promises no spread control")
    print("CV-069 OK: README / ROADMAP / PRIORITIES state the registered "
          "Output Trim range and default")
    print("CV-069 OK: README / ROADMAP / PRIORITIES state the NUM_AB_PARAMS "
          "snapshot count")

    for label, mutate in PROBES:
        mutated = mutate(*base)
        if mutated is None or mutated == base:
            print(f"CV-069 FAIL: stale self-probe '{label}': mutation did not "
                  "apply")
            return 1
        if not verify(*mutated):
            print(f"CV-069 FAIL: negative probe '{label}' was NOT rejected - "
                  "the checker is vacuous")
            return 1
        print(f"CV-069 probe ok: {label} -> rejected")

    neutral = base[0].replace(NEUTRAL_OLD, NEUTRAL_NEW, 1)
    if neutral == base[0]:
        print("CV-069 FAIL: no-op guard: the anchored benign edit did not "
              "apply")
        return 1
    neutral_errors = verify(neutral, *base[1:])
    if neutral_errors:
        print("CV-069 FAIL: a benign reword was wrongly rejected - the "
              "checker over-fires:")
        for error in neutral_errors:
            print(f"  - {error}")
        return 1
    print("CV-069 probe ok: benign reword accepted (specificity proven)")

    final = verify(*load())
    if final:
        print("CV-069 FAIL: final re-verification of the live tree failed:")
        for error in final:
            print(f"  - {error}")
        return 1
    print("CV-069 OK: live tree re-verified (second run stays green)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
