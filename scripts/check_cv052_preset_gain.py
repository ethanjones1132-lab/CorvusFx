#!/usr/bin/env python3
"""CV-052/CV-060 factory preset output-trim guard.

Pins the gain staging of the three factory presets that clipped at their default
settings inside the `static const P presets[36]` table in
source/DrippyFX/PluginProcessor.cpp: Thick Sauce (index 8, CV-052), Aggressive
Drive (index 19, CV-052) and Cathedral Drift (index 27, CV-060).

The `oTrim` column is the last field of struct P and is what loadPreset()
writes into the `output_trim` parameter, so it is the per-preset output gain.
The fix is those three numbers only; no DSP, no drive/fatness, no clamp, and
no other preset row may move.

Asserted properties (source file only):
  (a) rows 8, 19 and 27 carry an `oTrim` above 0 and at or below the pinned
      ceiling (85 for Thick Sauce, 70 for Aggressive Drive, 92 for
      Cathedral Drift);
  (b) every other row's `oTrim` is exactly 100;
  (c) the fatness (`fat`) and master drive (`mDrv`) columns of the trimmed
      rows are unchanged (72/40, 88/70 and 0/0);
  (d) where the pre-fix peak was measured, scaling it by oTrim/100 keeps the
      preset at or below 0.98 float at its defaults: Cathedral Drift measured
      1.003052 at oTrim 100, so 92 lands it at ~0.9228; Thick Sauce measured
      1.023 and lands at ~0.8696;
  (e) loadPreset() still routes the `oTrim` column into `output_trim`, so the
      trim column is really the preset's output gain.

Negative probes re-run the gate on mutated copies of the parsed table and must
reject: today's pre-fix trims (100/100/100), each ceiling + 1, a zero trim, a
non-target row trimmed down, a changed fatness/drive value, and a dropped
output_trim write. A benign comment edit must still pass.

Exit 0 = ok, 1 = violation with a cited diagnostic.
"""
import copy
import re
import sys
from pathlib import Path

# Diagnostics may quote source text; a cp1252 console must not crash a verdict.
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

ROOT = Path(__file__).resolve().parent.parent
CPP = ROOT / "source" / "DrippyFX" / "PluginProcessor.cpp"

EXPECTED_ROWS = 36
TRIM_FIELD = "oTrim"
FAT_FIELD = "fat"
DRIVE_FIELD = "mDrv"

# Preset index -> pinned upper bound for the whole-number output trim (percent,
# the `output_trim` parameter is 0..100 by default). Pre-fix every row here was
# 100 and clipped: Thick Sauce peaked at 1.023, Aggressive Drive put 36% of its
# samples out of range, Cathedral Drift peaked at 1.003052.
TRIMMED_ROWS = {8: 85, 19: 70, 27: 92}
DEFAULT_TRIM = 100.0

# Render target behind CV-T1: at its defaults no factory preset may push the
# output past 0.98 float. Where a single pre-fix peak is on record, the trim is
# also checked arithmetically: peak * oTrim/100 <= HEADROOM_TARGET. Aggressive
# Drive has no single peak on record (it was reported as a percentage of
# out-of-range samples), so it is guarded by its ceiling alone.
HEADROOM_TARGET = 0.98
PREFIX_PEAK = {8: 1.023, 27: 1.003052}

# The drive/fatness columns of the trimmed rows must not move.
PINNED_FAT = {8: 72.0, 19: 88.0, 27: 0.0}
PINNED_DRIVE = {8: 40.0, 19: 70.0, 27: 0.0}


def row_label(indices):
    ordered = sorted(indices)
    return ", ".join(str(i) for i in ordered[:-1]) + f" and {ordered[-1]}"


TRIMMED_LABEL = row_label(TRIMMED_ROWS)

OUTPUT_TRIM_WRITE_RE = r'set\s*\(\s*"output_trim"\s*,\s*p\.oTrim\s*\)\s*;'


class Reject(Exception):
    """Structural violation detected in a (real or fixture) table text."""


def fail(msg):
    print(f"FAIL: CV-052 preset gain staging: {msg}")
    sys.exit(1)


# ---------------------------------------------------------------------------
# Parsing helpers (comment stripping preserves line numbers)
# ---------------------------------------------------------------------------
def strip_comments(text):
    text = re.sub(r"/\*.*?\*/",
                  lambda m: "\n" * m.group(0).count("\n"), text, flags=re.S)
    return re.sub(r"//[^\n]*", "", text)


def brace_body(text, pos):
    """(open, close, body) of the first '{' at/after pos, brace-matched."""
    lb = text.find("{", pos)
    if lb == -1:
        return None
    depth = 0
    for k in range(lb, len(text)):
        if text[k] == "{":
            depth += 1
        elif text[k] == "}":
            depth -= 1
            if depth == 0:
                return lb, k + 1, text[lb:k + 1]
    return None


def parse_struct_fields(code):
    match = re.search(r"\bstruct\s+P\s*\{([^}]*)\}", code)
    if not match:
        raise Reject("struct P field list not found")
    fields = []
    for raw in match.group(1).split(","):
        names = re.findall(r"[A-Za-z_]\w*", raw)
        if not names:
            continue
        # "float fat" -> "fat", "oTrim;" -> "oTrim"
        fields.append(names[-1])
    for name in (FAT_FIELD, DRIVE_FIELD, TRIM_FIELD):
        if name not in fields:
            raise Reject(f"struct P no longer has a {name} field")
    if fields[-1] != TRIM_FIELD:
        raise Reject(
            "struct P no longer ends with the oTrim column (last column is "
            f"{fields[-1]!r}) - the preset rows cannot be read as gain staging")
    return fields


def parse_preset_rows(code, fields):
    match = re.search(r"static\s+const\s+P\s+presets\s*\[\s*(\d+)\s*\]\s*=\s*\{",
                      code)
    if not match:
        raise Reject("presets[36] declaration not found")
    declared = int(match.group(1))
    found = brace_body(code, match.end() - 1)
    if found is None:
        raise Reject("presets[36] initializer not brace-matched")
    entries = re.findall(r"\{([^{}]*)\}", found[2])
    if len(entries) != declared:
        raise Reject(
            f"presets table parsed to {len(entries)} rows but the array "
            f"declares {declared}")
    if len(entries) != EXPECTED_ROWS:
        raise Reject(
            f"presets table has {len(entries)} rows, expected {EXPECTED_ROWS}")

    rows = []
    for index, entry in enumerate(entries):
        values = [v.strip() for v in entry.split(",")]
        if len(values) != len(fields):
            raise Reject(
                f"preset row {index} has {len(values)} fields, struct P "
                f"declares {len(fields)}")
        parsed = []
        for name, raw in zip(fields, values):
            try:
                parsed.append(float(raw.rstrip("fF")))
            except ValueError:
                raise Reject(
                    f"preset row {index} column {name} value {raw!r} is not a "
                    "plain number")
        rows.append(parsed)
    return rows


def evaluate(rows, fields, code):
    """Gate parsed preset rows plus the loadPreset output_trim wiring."""
    errors = []
    trim = fields.index(TRIM_FIELD)
    fat = fields.index(FAT_FIELD)
    drive = fields.index(DRIVE_FIELD)

    for index in range(len(rows)):
        value = rows[index][trim]
        if index in TRIMMED_ROWS:
            ceiling = TRIMMED_ROWS[index]
            if not value > 0:
                errors.append(
                    f"preset row {index} oTrim is {value:g}; it must stay above 0")
            elif value > ceiling:
                errors.append(
                    f"preset row {index} oTrim is {value:g}; the pinned ceiling "
                    f"for this row is {ceiling} (raised trim re-clips the preset)")
        elif value != DEFAULT_TRIM:
            errors.append(
                f"preset row {index} oTrim is {value:g}; every row except "
                f"{TRIMMED_LABEL} must stay at {DEFAULT_TRIM:g}")

    # CV-T1: the trimmed rows must land under the float ceiling at defaults.
    for index, peak in sorted(PREFIX_PEAK.items()):
        projected = peak * rows[index][trim] / DEFAULT_TRIM
        if projected > HEADROOM_TARGET:
            errors.append(
                f"preset row {index} projects a peak of {projected:.4f} "
                f"(measured {peak:g} at oTrim {DEFAULT_TRIM:g}, scaled by the "
                f"row's oTrim {rows[index][trim]:g}); it must stay at or below "
                f"{HEADROOM_TARGET:g} so the preset cannot clip at its defaults")

    for index, expected in PINNED_FAT.items():
        if rows[index][fat] != expected:
            errors.append(
                f"preset row {index} fatness is {rows[index][fat]:g}; the fix "
                f"is gain staging only, expected {expected:g}")
    for index, expected in PINNED_DRIVE.items():
        if rows[index][drive] != expected:
            errors.append(
                f"preset row {index} master_drive is {rows[index][drive]:g}; "
                f"the fix is gain staging only, expected {expected:g}")

    if not re.search(OUTPUT_TRIM_WRITE_RE, code):
        errors.append(
            "loadPreset() no longer writes the oTrim column into output_trim "
            '(`set("output_trim", p.oTrim);` missing)')

    return errors


def verify(raw_cpp):
    code = strip_comments(raw_cpp)
    fields = parse_struct_fields(code)
    rows = parse_preset_rows(code, fields)
    return evaluate(rows, fields, code), rows, fields, code


# ---------------------------------------------------------------------------
# Self-probes: the gate must reject the pre-fix table and any raised ceiling.
# ---------------------------------------------------------------------------
def probe(rows, fields, code, label, index, column, value):
    """Mutate one preset cell on a copy and expect a rejection."""
    mutated = copy.deepcopy(rows)
    mutated[index][column] = value
    if mutated == rows:
        fail(f"probe '{label}' did not apply - the fixture is stale")
    if not evaluate(mutated, fields, code):
        fail(f"probe '{label}' was accepted (rows {index} "
             f"{fields[column]}={value:g})")
    print(f"probe ok: {label} -> rejected")


def main():
    try:
        raw = CPP.read_text(encoding="utf-8", errors="replace")
    except OSError as exc:
        fail(f"cannot read {CPP}: {exc}")

    try:
        errors, rows, fields, code = verify(raw)
    except Reject as exc:
        fail(str(exc))

    if errors:
        for error in errors:
            print(f"FAIL: CV-052 {error}")
        return 1

    trim = fields.index(TRIM_FIELD)
    fat = fields.index(FAT_FIELD)
    drive = fields.index(DRIVE_FIELD)

    for index in sorted(TRIMMED_ROWS):
        print(f"PASS: preset row {index} oTrim "
              f"{rows[index][fields.index(TRIM_FIELD)]:g} <= "
              f"{TRIMMED_ROWS[index]:g} and > 0")
    others = [i for i in range(len(rows)) if i not in TRIMMED_ROWS]
    print(f"PASS: {len(others)} other preset rows keep oTrim "
          f"{DEFAULT_TRIM:g}")
    for index in sorted(TRIMMED_ROWS):
        print(f"PASS: preset row {index} fatness "
              f"{rows[index][fields.index(FAT_FIELD)]:g} / master_drive "
              f"{rows[index][fields.index(DRIVE_FIELD)]:g} unchanged")
    for index, peak in sorted(PREFIX_PEAK.items()):
        projected = peak * rows[index][trim] / DEFAULT_TRIM
        print(f"PASS: preset row {index} projected peak {projected:.4f} <= "
              f"{HEADROOM_TARGET:g} (measured {peak:g} at oTrim "
              f"{DEFAULT_TRIM:g})")
    print('PASS: loadPreset() still writes the oTrim column into "output_trim"')

    # The exact pre-fix table: every trimmed row back at 100, i.e. today's
    # clipped state.
    probe(rows, fields, code, "pre-fix Thick Sauce trim restored (100)",
          8, trim, 100.0)
    probe(rows, fields, code, "pre-fix Aggressive Drive trim restored (100)",
          19, trim, 100.0)
    probe(rows, fields, code, "pre-fix Cathedral Drift trim restored (100)",
          27, trim, 100.0)
    probe(rows, fields, code, "Thick Sauce trim raised above 85",
          8, trim, 86.0)
    probe(rows, fields, code, "Aggressive Drive trim raised above 70",
          19, trim, 71.0)
    probe(rows, fields, code, "Cathedral Drift trim raised above 92",
          27, trim, 93.0)
    probe(rows, fields, code, "Thick Sauce trim muted to 0",
          8, trim, 0.0)
    probe(rows, fields, code, "unrelated row trimmed away from 100",
          3, trim, 90.0)
    probe(rows, fields, code, "Thick Sauce fatness moved",
          8, fat, 70.0)
    probe(rows, fields, code, "Aggressive Drive drive moved",
          19, drive, 65.0)
    probe(rows, fields, code, "Cathedral Drift fatness moved",
          27, fat, 5.0)
    probe(rows, fields, code, "Cathedral Drift drive moved",
          27, drive, 5.0)

    unwired = code.replace('set("output_trim", p.oTrim);', "")
    if unwired == code:
        fail("probe 'output_trim write removed' did not apply - stale fixture")
    try:
        if not verify(unwired)[0]:
            fail("probe 'output_trim write removed' was accepted")
        print("probe ok: output_trim write removed -> rejected")
    except Reject as exc:
        fail(f"probe 'output_trim write removed' broke parsing: {exc}")

    benign = raw + "\n// CV-052 benign comment edit\n"
    try:
        benign_errors, _, _, _ = verify(benign)
    except Reject as exc:
        fail(f"benign comment edit broke parsing: {exc}")
    if benign_errors:
        fail(f"benign comment edit was rejected: {benign_errors[0]}")
    print("probe ok: benign comment edit -> accepted")

    print(f"CV-052 PRESET GAIN OK ({len(rows)} rows, "
          f"{len(TRIMMED_ROWS)} trimmed, {len(others)} untouched)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
