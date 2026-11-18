#!/usr/bin/env python3
"""Headless checker: CV-056 control labels agree with the parameter ranges.

The editor's knob tooltips and captions are hand-written copy strings that are
never compiled against a parameter. After CV-036 widened master_width to
0..200% the copy went stale (the tooltip still stopped at ">100% = widened"),
while Output Trim's tooltip kept advertising "200% = +6dB boost" for a
parameter the shared pctParam helper still registers at 0..100 - a user drags
TRIM to its 100% stop looking for the promised 6 dB that cannot exist.

The host-visible name of the "fatness" parameter was also still "Fatness"
while the editor row prints "DRIVE" and the README parameter table lists
"Drive", so a DAW automation lane and the plugin's own UI disagreed about the
name of the same control. The parameter ID stays "fatness" byte-for-byte
(saved sessions, factory presets, MIDI maps and get/setStateInformation all
key off it); only the display name changes.

Asserts (comment-stripped source):
  (a) `fatness` is registered exactly once, its host-visible name is "Drive",
      that name matches the editor caption "DRIVE" (case-insensitive), and
      the README parameter table carries a `| **Drive** |` row;
  (b) master_width's declared range is read out of PluginProcessor.cpp
      (0..200) and its editor tooltip states BOTH ends of that range and
      mentions no percentage outside it;
  (c) output_trim is registered through the shared pctParam helper (0..100),
      its tooltip states "100%" and mentions no percentage above 100 - in
      particular no "200%";
  (d) every other pctParam tooltip stays inside 0..100 as well (the general
      "no tooltip describes a value the parameter range cannot reach" rule);
  (e) the README's Master Width row never promises a ceiling above the
      declared range, and its default cell matches the declared default.
      NOTE: widening that row from 0-100% to 0-200% is owned by the sibling
      README brief, so this check pins the overpromise direction only - it
      accepts the row both before and after that edit, and rejects any value
      the parameter cannot reach.

Self-probes (negative checks, sibling checker style) on mutated in-memory
texts - the real tree is never mutated. A stale/no-op mutation is a failure,
never a silently skipped probe:
  - restore the pre-patch "Fatness" display name -> rejected;
  - restore the pre-patch width tooltip (no 200% ceiling) -> rejected;
  - restore the Output Trim "200% = +6dB boost" promise -> rejected;
  - desync the editor caption from the host-visible name -> rejected;
  - advertise 300% on the width tooltip -> rejected;
  - promise 0-500% on the README width row -> rejected;
  - bind the width default to the wrong factory field -> rejected;
  - benign reword of an unrelated tooltip -> accepted (specificity).

Exit 0 = ok, 1 = violation with diagnostics.
"""
import re
import sys
from pathlib import Path

from _fx_factory_defaults import factory_default

ROOT = Path(__file__).resolve().parent.parent
SRC = ROOT / "source" / "DrippyFX"
PROC = SRC / "PluginProcessor.cpp"
ED = SRC / "PluginEditor.cpp"
README = ROOT / "README.md"

PCT_CEILING = 100.0          # the shared pctParam helper's range cap
DRIVE_ID = "fatness"         # parameter id - must never change
DRIVE_NAME = "Drive"         # host-visible name the editor and README use
WIDTH_ID = "master_width"
TRIM_ID = "output_trim"

PCT_PARAM_RE = re.compile(
    r'\bpctParam\s*\(\s*"([a-z_0-9]+)"\s*,\s*"([^"]*)"\s*,')
SETUPKNOB_RE = re.compile(
    r'setupKnob\(\s*(\w+)\s*,\s*(\w+)\s*,\s*"([^"]*)"\s*,\s*"([a-z_0-9]+)"'
    r'\s*,\s*"([^"]*)"\s*\)')
WIDTH_RANGE_RE = re.compile(
    r'make_unique<juce::AudioParameterFloat>\s*\(\s*"master_width"'
    r'\s*,\s*"([^"]*)"\s*,\s*'
    r'juce::NormalisableRange<float>\(\s*([-\d.]+)f\s*,\s*([-\d.]+)f'
    r'\s*,\s*[-\d.]+f\s*\)\s*,\s*p\.(\w+)\s*,')
# README parameter-table row: group(1) = range cell, group(2) = default cell.
README_WIDTH_ROW_RE = re.compile(
    r"^\|\s*\*\*Master Width\*\*\s*\|\s*([^|]*)\|\s*([^|]*)\|", re.M)


def fail(msg):
    print(f"CV056-CONTROL-LABELS FAIL: {msg}")
    sys.exit(1)


def strip_comments(src):
    src = re.sub(r"//[^\n]*", "", src)
    src = re.sub(r"/\*.*?\*/", "", src, flags=re.S)
    return src


def percents(text):
    """Every `NN%` / `NN.N%` number in a copy string, as floats."""
    return [float(m) for m in re.findall(r"(\d+(?:\.\d+)?)\s*%", text)]


def pct_list(values):
    return ", ".join(f"{v:g}%" for v in values) or "none"


def range_bounds(cell):
    """Bounds of a README range cell such as `0-100%` / `0–200%`.

    The README writes the lower bound without its own `%` sign (and with an
    en dash), so a plain percent scan would see only the upper bound.
    """
    bounds = []
    for part in re.split(r"[-\u2013\u2014]", cell):
        m = re.search(r"(\d+(?:\.\d+)?)\s*%?", part)
        if m:
            bounds.append(float(m.group(1)))
    return bounds


def check(proc_text, ed_text, readme_text):
    """Return None if ok, else a diagnostic string."""
    proc = strip_comments(proc_text)
    ed = strip_comments(ed_text)

    # ---- (a) the Drive control's host-visible name -------------------------
    pct_params = PCT_PARAM_RE.findall(proc)
    if not pct_params:
        return "no pctParam(...) registrations found in PluginProcessor.cpp"
    names = {}
    for pid, name in pct_params:
        if pid in names:
            return f"parameter id {pid!r} registered more than once"
        names[pid] = name

    if DRIVE_ID not in names:
        return (f"parameter id {DRIVE_ID!r} is no longer registered - the id "
                f"is state/preset identity and must not change")
    if names[DRIVE_ID] != DRIVE_NAME:
        return (f'host-visible name for id "{DRIVE_ID}" is '
                f'{names[DRIVE_ID]!r}, expected {DRIVE_NAME!r} (the name the '
                f"editor row and the README parameter table use)")
    dupes = [pid for pid, name in names.items()
             if name == DRIVE_NAME and pid != DRIVE_ID]
    if dupes:
        return (f'display name {DRIVE_NAME!r} is also used by {dupes} - the '
                f"host list would show two identically named controls")

    rows = {}
    for _knob, _label, caption, pid, tooltip in SETUPKNOB_RE.findall(ed):
        if pid in rows:
            return f"setupKnob row for paramID {pid!r} appears more than once"
        rows[pid] = (caption, tooltip)
    if not rows:
        return "no setupKnob(...) rows found in PluginEditor.cpp"

    if DRIVE_ID not in rows:
        return f'no editor knob row is wired to paramID "{DRIVE_ID}"'
    caption, _tip = rows[DRIVE_ID]
    if caption.strip().upper() != DRIVE_NAME.upper():
        return (f'editor caption {caption!r} for id "{DRIVE_ID}" does not '
                f"match the host-visible name {DRIVE_NAME!r} - DAW automation "
                f"lane and UI would name the same knob differently")

    if not re.search(r"^\|\s*\*\*Drive\*\*\s*\|", readme_text, re.M):
        return ('README parameter table has no `| **Drive** |` row - the '
                "host-visible name must be the name the README documents")

    # ---- (b) master_width: tooltip must state the real 0..200 span --------
    if WIDTH_ID in names:
        return (f'"{WIDTH_ID}" is registered through the shared pctParam '
                f"helper (0..{PCT_CEILING:g}%) - CV-036 moved it to its own "
                f"0..200% range and that range must stay")
    wm = WIDTH_RANGE_RE.search(proc)
    if not wm:
        return ('could not read the declared range and factory default of '
                '"master_width" from PluginProcessor.cpp')
    if wm.group(1) != "Master Width":
        return (f'host-visible name for "master_width" is {wm.group(1)!r}, '
                f'expected "Master Width"')
    wmin, wmax = float(wm.group(2)), float(wm.group(3))
    try:
        wdefault = factory_default(proc, wm.group(4))
    except ValueError as exc:
        return f"could not read the master_width default: {exc}"
    if wmax <= PCT_CEILING:
        return (f'"master_width" range is 0..{wmax:g}% - the CV-036 widening '
                f"to 0..200% is gone, so the tooltip/README copy would "
                f"describe values the parameter can reach")
    if WIDTH_ID not in rows:
        return f'no editor knob row is wired to paramID "{WIDTH_ID}"'
    width_tip = rows[WIDTH_ID][1]
    width_pcts = percents(width_tip)
    if not width_pcts:
        return ("master_width tooltip states no percentage at all - it must "
                f"document the declared 0..{wmax:g}% span")
    if not any(abs(v - wmin) < 1e-6 for v in width_pcts):
        return (f"master_width tooltip never mentions {wmin:g}% (the "
                f"minimum of its declared range): {width_tip!r}")
    if not any(abs(v - wmax) < 1e-6 for v in width_pcts):
        return (f"master_width tooltip never mentions {wmax:g}% - the "
                f"declared range reaches {wmax:g}%, so the copy must state "
                f"that end (stale post-CV-036 copy): {width_tip!r}")
    bad = [v for v in width_pcts if v < wmin - 1e-6 or v > wmax + 1e-6]
    if bad:
        return (f"master_width tooltip describes {pct_list(bad)}, outside its "
                f"declared {wmin:g}..{wmax:g}% range: {width_tip!r}")

    # ---- (c)/(d) every percentage knob tooltip stays inside 0..100 --------
    if TRIM_ID not in names:
        return f'"{TRIM_ID}" is no longer registered through pctParam'
    for pid in sorted(names):
        if pid not in rows:
            return f'no editor knob row is wired to paramID "{pid}"'
        tooltip = rows[pid][1]
        bad = [v for v in percents(tooltip) if v < 0 or v > PCT_CEILING]
        if bad:
            return (f'tooltip for "{pid}" describes {pct_list(bad)}, outside '
                    f"the shared pctParam 0..{PCT_CEILING:g}% range: "
                    f"{tooltip!r}")
    trim_tip = rows[TRIM_ID][1]
    if not any(abs(v - PCT_CEILING) < 1e-6 for v in percents(trim_tip)):
        return (f'output_trim tooltip never mentions {PCT_CEILING:g}% - it '
                f"must describe the real 0..{PCT_CEILING:g}% span: "
                f"{trim_tip!r}")

    # ---- (e) README width row: no ceiling above the declared range --------
    rm = README_WIDTH_ROW_RE.search(readme_text)
    if not rm:
        return ("README parameter table has no `| **Master Width** |` row")
    readme_pcts = range_bounds(rm.group(1))
    if len(readme_pcts) < 2:
        return (f"README Master Width row does not state a range: "
                f"{rm.group(1).strip()!r}")
    lo, hi = readme_pcts[0], readme_pcts[-1]
    if abs(lo - wmin) > 1e-6:
        return (f"README Master Width row starts at {lo:g}%, the declared "
                f"range starts at {wmin:g}%")
    if hi > wmax + 1e-6:
        return (f"README Master Width row promises up to {hi:g}%, the "
                f"declared range stops at {wmax:g}%")
    readme_default = percents(rm.group(2))
    if len(readme_default) != 1:
        return (f"README Master Width row does not state a single percentage "
                f"default: {rm.group(2).strip()!r}")
    if abs(readme_default[0] - wdefault) > 1e-6:
        return (f"README Master Width row defaults to {readme_default[0]:g}%, "
                f"the parameter's declared default is {wdefault:g}%")
    return None


def read_store():
    for path in (PROC, ED, README):
        if not path.exists():
            fail(f"missing source file {path}")
    return (PROC.read_text(encoding="utf-8"),
            ED.read_text(encoding="utf-8"),
            README.read_text(encoding="utf-8"))


def main():
    proc, ed, readme = read_store()
    err = check(proc, ed, readme)
    if err:
        fail(err)
    print('cv056-control-labels: host name "Drive" for id "fatness" matches '
          "the editor caption and the README row; master_width tooltip states "
          "its full 0..200% span; output_trim and every other pctParam "
          "tooltip stays inside 0..100%; README width row promises no "
          "unreachable value")

    def in_proc(old, new):
        return lambda p, e, r: (p.replace(old, new, 1), e, r)

    def in_ed(old, new):
        return lambda p, e, r: (p, e.replace(old, new, 1), r)

    def readme_row_overpromises(p, e, r):
        m = README_WIDTH_ROW_RE.search(r)
        if not m:
            return (p, e, r)
        row = m.group(0)
        spliced = (row[:m.start(1) - m.start()] + " 0-500% "
                   + row[m.end(1) - m.start():])
        return (p, e, r[:m.start()] + spliced + r[m.end():])

    probes = [
        ("pre-patch 'Fatness' display name restored",
         in_proc('pctParam("fatness", "Drive",',
                 'pctParam("fatness", "Fatness",')),
        ("pre-patch width tooltip restored (no 200% ceiling)",
         in_ed('200% = maximum width");', '>100% = widened");')),
        ("pre-patch Output Trim 200% promise restored",
         in_ed('100% = unity gain");',
               '100% = unity gain, 200% = +6dB boost");')),
        ("editor caption desynced from the host-visible name",
         in_ed('"DRIVE", "fatness"', '"FATNESS", "fatness"')),
        ("width tooltip advertises 300% (above the declared max)",
         in_ed('200% = maximum width");', '300% = maximum width");')),
        ("README Master Width row promises 0-500%",
         readme_row_overpromises),
        ("Master Width default comes from the wrong factory field",
         in_proc("0.1f), p.mWid,", "0.1f), p.mDrv,")),
    ]

    for desc, mutate in probes:
        mutated = mutate(proc, ed, readme)
        if mutated == (proc, ed, readme):
            fail(f"stale probe {desc!r}: mutation did not change the source - "
                 f"the negative check is vacuous")
        if check(*mutated) is None:
            fail(f"negative probe {desc!r} was NOT rejected - checker is "
                 f"vacuous")
        print(f"cv056-control-labels: negative probe fired: {desc} -> rejected")

    benign = in_ed('"Delay wet/dry balance");',
                   '"Delay wet/dry balance (100% = fully wet)");')
    mutated = benign(proc, ed, readme)
    if mutated == (proc, ed, readme):
        fail("benign probe anchor missing from PluginEditor.cpp - the "
             "delay_mix tooltip drifted; cannot trust the specificity probe")
    leftover = check(*mutated)
    if leftover is not None:
        fail(f"benign copy edit was wrongly rejected: {leftover}")
    print("cv056-control-labels: benign copy edit accepted (specificity "
          "proven)")

    print("CV056-CONTROL-LABELS OK")
    return 0


if __name__ == "__main__":
    sys.exit(main())
