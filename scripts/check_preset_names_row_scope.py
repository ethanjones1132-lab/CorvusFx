#!/usr/bin/env python3
"""Read-only scope pin for check_preset_names.py's designation-comment helper.

`extract_load_preset_comment_names` in scripts/check_preset_names.py must read
ONLY the `static const P presets[36]` table region (brace-matched), not the
whole loadPreset body: the region between the presets table and the next
`void` is large, and (a) a second `// N: Name`-shaped comment block appearing
in a later body would feed the helper phantom rows, (b) a stale/short row list
must hard-fail with a diagnostic, never silently proceed.

This checker (gate-glob-wired via scripts/check_*.py) asserts the helper's
slice equals the table region and that short/oversized row lists are rejected.
Negatives run on mutated IN-MEMORY texts — the real tree is never mutated.

Exits 0 on green, 1 on any scope violation.
"""
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
PROC = ROOT / "source" / "DrippyFX" / "PluginProcessor.cpp"
EXPECTED_PROGRAMS = 36


def extract_presets_table_region_text(proc_text: str) -> str:
    """Independent brace-matched extraction of the presets table region."""
    start = proc_text.find("static const P presets[36] = {")
    if start == -1:
        return ""
    depth = 0
    for i in range(start, len(proc_text)):
        ch = proc_text[i]
        if ch == "{":
            depth += 1
        elif ch == "}":
            depth -= 1
            if depth == 0:
                return proc_text[start:i + 1]
    return ""


def comment_rows_in(text: str):
    return re.findall(r"^\s*//\s*(\d+):\s*(.*)$", text, flags=re.M)


def idxs_sorted_clean(rows) -> bool:
    return [int(i) for (i, _) in rows] == list(range(EXPECTED_PROGRAMS))


def main() -> int:
    errors: list[str] = []
    proc_text = PROC.read_text(encoding="utf-8", errors="replace")

    table_region = extract_presets_table_region_text(proc_text)
    if not table_region:
        errors.append("presets table region (`static const P presets[36] = {`) not found")
    else:
        if "\nvoid " in table_region:
            errors.append("presets table region slice leaks past the table into another body "
                          "(functional boundary crossed)")

        # From the helper module itself (importlib; filename has a hyphen).
        import importlib.util
        spec = importlib.util.spec_from_file_location(
            "check_preset_names", ROOT / "scripts" / "check_preset_names.py")
        if spec is None or spec.loader is None:
            print("FAIL: could not load scripts/check_preset_names.py for scope inspection")
            return 1
        mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(mod)

        helper_rows = mod.extract_load_preset_comment_names(proc_text)
        helper_region = mod.extract_presets_table_region(proc_text)

        if helper_region != table_region:
            errors.append("helper's slice differs from the independently extracted "
                          "presets table region (scope drift)")
        if not helper_rows:
            errors.append("helper found no `// N: Name` designation comments in the "
                          "table region")
        else:
            if len(helper_rows) != EXPECTED_PROGRAMS:
                errors.append(f"helper extracted {len(helper_rows)} designation rows; "
                              f"the table region carries exactly "
                              f"{len(comment_rows_in(table_region))} `// N: Name` rows — "
                              f"short/oversized row lists must hard-fail, not proceed")
            idxs = [int(i) for (i, _) in helper_rows]
            if idxs != list(range(EXPECTED_PROGRAMS)):
                errors.append(f"helper row indices are not a clean 0..{EXPECTED_PROGRAMS - 1} "
                              f"sequence (got {idxs})")

        # ---- negative probes (in-memory mutations; real tree never mutated) ----

        def require_reject(name: str, mutated: str) -> None:
            diag = []
            region = extract_presets_table_region_text(mutated)
            rows = comment_rows_in(region) if region else []
            if region and "\nvoid " not in region and len(rows) == EXPECTED_PROGRAMS \
                    and idxs_sorted_clean(rows):
                diag.append("accepts")
            if diag:
                print(f"row-scope probe '{name}': mutation accepted when it should be "
                      f"rejected — checker scope is wrong")
                sys.exit(1)
            print(f"row-scope probe '{name}': rejected as expected")

        # probe 1: a `// 36:` phantom row appended inside the table region
        if not table_region:
            print("row-scope probe 'table region vanished': region not extractable — "
                  "restructure unsupported, skipping probe")
            return 1
        require_reject(
            "37th row added inside table",
            proc_text.replace("static const P presets[36] = {",
                              "static const P presets[36] = {\n        // 36: Phantom Row — bogus entry",
                              1))
        # probe 2: designation comments commented OUT of the table region
        # (helper sees zero rows -> hard diagnostic, not silent pass)
        stripped = re.sub(r"^\s*//\s*\d+:.*$", "", table_region, flags=re.M)
        mutated = proc_text.replace(table_region, stripped, 1)
        if extract_presets_table_region_text(mutated) != "":
            require_reject("designation comments removed from table region", mutated)

    if errors:
        print("FAIL: preset-names row-scope violations:")
        for e in errors:
            print(f"  - {e}")
        return 1

    print("OK: preset-names designation-comment helper reads only the presets table "
          "region; short/oversized row lists hard-fail")

    # benign no-op guard on the real text (in-memory copy)
    noop = proc_text.replace("// 0: Clean Sparkle — subtle widening",
                             "// 0: Clean Sparkle  — subtle widening")
    if noop != proc_text:
        region = extract_presets_table_region_text(noop)
        rows = comment_rows_in(region)
        if not (region and "\nvoid " not in region
                and idxs_sorted_clean(rows) and len(rows) == EXPECTED_PROGRAMS):
            print("row-scope probe 'benign no-op': rejected when it should pass — "
                  "checker false-positives")
            sys.exit(1)
        print("row-scope probe 'benign no-op': accepted (specificity guard)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
