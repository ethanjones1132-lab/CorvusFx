#!/usr/bin/env python3
"""Headless checker: parameterChanged's idToPreset in-range double-guard.

parameterChanged preset-branch (PluginProcessor.cpp): `int id =
static_cast<int>(newValue + 0.5f);` then
`if (id >= 2 && id <= 42 && idToPreset[id] >= 0) loadPreset(idToPreset[id]);`

No other checker pins this body: check_preset_tables.py pins the
idToPreset TABLE CONTENTS only (43 entries + reversal consistency);
check_preset_combo_runtime.py pins the presetToId[] current-program
junction and only MENTIONS the parameterChanged guard in its docstring —
none pins (a) the + 0.5f rounding form, (b) the `id >= 2 && id <= 42`
window, (c) the separator-row `idToPreset[id] >= 0` test in the same
condition, or (d) loadPreset(idToPreset[id]) as the only body statement.

Designed-in hazards (compile clean behind an otherwise-green gate):
  - lowering the window to `id >= 0` redirects separator ids 0/1 through
    idToPreset (rows 0-1 are -1); if BOTH guards drift, loadPreset(-1) is
    caught only by loadPreset's own index check, leaving the undo
    transaction begun with no preset loaded;
  - dropping `+ 0.5f` makes a stored 6.9999f (0-1 range quantisation)
    floor to 6 instead of rounding to the intended id 7 — silent
    off-by-one preset loads at the boundary;
  - dropping the separator-row test makes loadPreset(-1) reachable.

Asserts are comment-stripped, brace-matched on the parameterChanged body.
Negative self-probes run on mutated in-memory texts — the real tree is
never mutated. Exit 0 = ok, 1 = violation with diagnostics.
"""
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SRC = ROOT / "source" / "DrippyFX"


def fail(msg):
    print(f"PARAMCHANGED-GUARD FAIL: {msg}")
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


def extract_parameter_changed_body(txt):
    marker = "void CorvusFXAudioProcessor::parameterChanged("
    k = txt.find(marker)
    if k == -1:
        fail("could not find CorvusFXAudioProcessor::parameterChanged( definition")
    o = txt.find("{", k)
    if o == -1:
        fail("could not find opening brace of parameterChanged body")
    depth, j = 0, o
    while j < len(txt):
        if txt[j] == "{": depth += 1
        elif txt[j] == "}":
            depth -= 1
            if depth == 0: break
        j += 1

    if depth != 0:
        fail("unbalanced braces extracting parameterChanged body")
    return strip_comments(txt[o:j + 1])


def collapse_ws(s):
    return re.sub(r"\s+", " ", s).strip()


def check_param_changed_guard(body):
    body = collapse_ws(body)
    m = re.search(
        r'int id = static_cast<int> \( newValue \+ 0\.5f \);'.replace(" ", ""),
        body.replace(" ", ""))
    if not m:
        return ("the preset-id rounding read `int id = "
                "static_cast<int>(newValue + 0.5f);` drifted — dropping "
                "`+ 0.5f` floors a stored 6.9999f to 6 instead of rounding "
                "to the intended id 7 (silent off-by-one preset loads at "
                "the quantisation boundary)")
    m = re.search(
        r'if \( id >= (\d+) && id <= (\d+) && idToPreset \[ id \] >= 0 \)'.replace(" ", ""),
        body.replace(" ", ""))
    if not m:
        return ("the combined in-range guard "
                "`if (id >= 2 && id <= 42 && idToPreset[id] >= 0)` drifted "
                "— a widened window accepts separator ids 0/1, and a "
                "dropped separator-row test makes loadPreset(-1) reachable "
                "(undo transaction begun with no preset loaded)")
    if m.group(1) != "2" or m.group(2) != "42":
        return (f"the parameterChanged id window is "
                f"{m.group(1)}..{m.group(2)}, expected 2..42 (matches the "
                f"idToPreset[43] table: 42 usable combo rows after the "
                f"id 0/1 entries)")
    if not re.search(r'loadPreset \( idToPreset \[ id \] \)'.replace(" ", ""),
                     body.replace(" ", "")):
        return ("the body statement `loadPreset(idToPreset[id]);` drifted")
    return None


proc_c_path = SRC / "PluginProcessor.cpp"
if not proc_c_path.exists():
    fail(f"missing source file {proc_c_path}")
proc_c = proc_c_path.read_text()

err = check_param_changed_guard(extract_parameter_changed_body(proc_c))
if err:
    fail(err + " (PluginProcessor.cpp parameterChanged)")
print("paramchanged-guard: +0.5f rounding, 2..42 window, separator-row "
      "test, loadPreset body pinned")

# ---------------------------------------------------------------------------
# Self-probes on mutated in-memory texts (real tree never mutated)
# ---------------------------------------------------------------------------

def probe(description, old, new):
    tmp_raw = proc_c.replace(old, new, 1)
    if tmp_raw == proc_c:
        print(f"paramchanged-guard: no-op mutation guard -> skipping "
              f"invalid probe ({description})")
        return
    if check_param_changed_guard(
            extract_parameter_changed_body(tmp_raw)) is None:
        print(f"paramchanged-guard: SELF-PROBE FAIL (checker should "
              f"reject): {description}")
        sys.exit(1)
    print(f"paramchanged-guard: self-probe fired: {description} -> "
          f"rejected")


probe("parameterChanged window widened to id >= 0 (separator ids 0/1 "
      "redirected through idToPreset; if both guards drift, loadPreset(-1) "
      "begins an undo transaction with no preset loaded)",
      "if (id >= 2 && id <= 42 && idToPreset[id] >= 0)",
      "if (id >= 0 && id <= 42 && idToPreset[id] >= 0)")
probe("parameterChanged + 0.5f rounding dropped (6.9999f floors to 6 "
      "instead of rounding to id 7 — silent off-by-one preset loads at "
      "the boundary)",
      "int id = static_cast<int>(newValue + 0.5f);",
      "int id = static_cast<int>(newValue);")
probe("parameterChanged separator-row test dropped (loadPreset(-1) "
      "reachable from separator rows)",
      "if (id >= 2 && id <= 42 && idToPreset[id] >= 0)",
      "if (id >= 2 && id <= 42)")
probe("parameterChanged loadPreset operand swapped to [0] (every preset "
      "selection loads discharged through idToPreset[0] == -1)",
      "loadPreset(idToPreset[id]);",
      "loadPreset(idToPreset[0]);")

# no-op guard: benign comment addition stays accepted
tmp = proc_c.replace(
    "loadPreset(idToPreset[id]);",
    "loadPreset(idToPreset[id]); /* benign */", 1)
if tmp != proc_c:
    if check_param_changed_guard(
            extract_parameter_changed_body(tmp)) is not None:
        fail("no-op guard: benign edit was wrongly rejected")
print("paramchanged-guard: no-op guard passed (benign edit accepted)")

print("PARAMCHANGED-GUARD OK")
