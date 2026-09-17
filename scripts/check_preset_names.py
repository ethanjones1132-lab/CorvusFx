#!/usr/bin/env python3
"""Headless name-row correspondence pin for the DrippyFX 36-preset system.

The preset system keeps the SAME 36 user-facing names in three hand-maintained
places that no existing checker compares against each other:

  (a) getProgramName()'s `static const juce::String n[36] { ... }` table
      (source/DrippyFX/PluginProcessor.cpp)
  (b) PluginEditor.cpp's `presetSelector.addItem("<name>", <id>)` rows
      (must match (a) element-for-element once sorted by item id, with the
      disabled `---` separator rows excluded)
  (c) loadPreset()'s per-row designation comments `// <i>: <Name>-...`
      (must match (a) in array order, so the comment names describe the actual
      DSP row values)

A silent rename/swap in any ONE of the three desynchronizes what the user picks
from what the plugin reports or actually loads. This checker fails with a
cited diagnostic if any of the three views drifts apart.

Exits 0 on green, 1 with a diagnostic list on any violation.
"""
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
PROC = ROOT / "source" / "DrippyFX" / "PluginProcessor.cpp"
EDIT = ROOT / "source" / "DrippyFX" / "PluginEditor.cpp"
EXPECTED_PROGRAMS = 36


def norm(s: str) -> str:
    return s.strip().lower().replace('"', "")


def extract_get_program_names(proc_text: str):
    m = re.search(
        r"static\s+const\s+juce::String\s+n\[36\]\s*=\s*\{(.*?)\}\s*;",
        proc_text,
        flags=re.S,
    )
    if not m:
        return []
    return re.findall(r'"([^"]*)"', m.group(1))


def extract_editor_items(edit_text: str):
    """Pull (id, name) pairs from `<name>, <id>)` addItem calls, normalized."""
    pairs = []
    for m in re.finditer(r'"((?:[^"\\]|\\.)*)"\s*,\s*(\d+)\s*\)', edit_text):
        name = m.group(1).replace('\\"', '"').replace("\\\\", "\\")
        pairs.append((int(m.group(2)), name))
    return pairs


def extract_presets_table_region(proc_text: str) -> str:
    """Return ONLY the `static const P presets[36]` table region (brace-matched).

    Anchoring on the table instead of the whole loadPreset body means a
    second `// N: Name`-shaped comment block appearing in a later body can
    never contribute phantom rows.
    """
    start_marker = "static const P presets[36] = {"
    start = proc_text.find(start_marker)
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


def extract_load_preset_comment_names(proc_text: str):
    """Extract `// <n>: <Name>` designation comments from the presets table region."""
    body = extract_presets_table_region(proc_text)
    if not body:
        return []
    out = []
    # name = everything up to the ` — ` em-dash description separator (spaces
    # included so a hyphenated preset name like "Low-Fi" survives intact);
    # a row with no em-dash description takes the whole comment text.
    for m in re.finditer(r"^\s*//\s*(\d+):\s*(.*)$", body, flags=re.M):
        idx = int(m.group(1))
        text = m.group(2).strip()
        name = text.split(" — ")[0].strip()
        name = re.sub(r"[,.;:!\s]+$", "", name)
        out.append((idx, name))
    return out


def check(proc_text: str, edit_text: str):
    """Return the list of diagnostics for a given (processor, editor) text pair."""
    errors: list[str] = []

    # (a) getProgramName
    proc_names = extract_get_program_names(proc_text)
    if not proc_names:
        errors.append("could not find getProgramName() name table (static const juce::String n[36])")
    elif len(proc_names) != EXPECTED_PROGRAMS:
        errors.append(f"getProgramName has {len(proc_names)} names, expected {EXPECTED_PROGRAMS}")

    # (b) editor items sorted by id
    editor_items = extract_editor_items(edit_text)
    if len(editor_items) != 42:  # 36 names + 6 separators (ids 1..42, no id 0)
        errors.append(f"editor presetSelector has {len(editor_items)} addItem rows, expected "
                      f"42 (36 names + 6 separators)")
    editor_names_by_id = sorted(editor_items, key=lambda p: p[0])
    # separators are the `--- ... ---` strings; exclude them by content
    editor_real = [(i, n) for (i, n) in editor_names_by_id if not re.match(r"^-{2,}", n.strip())]
    if len(editor_real) == EXPECTED_PROGRAMS and len(proc_names) == EXPECTED_PROGRAMS:
        for k, ((_, ename), pname) in enumerate(zip(editor_real, proc_names)):
            if norm(ename) != norm(pname):
                errors.append(f"editor combo item {k + 1} is \"{ename}\" but "
                              f"getProgramName[{k}] is \"{pname}\" (row-name desync at "
                              f"combo ordinal {k + 1})")

    # (c) loadPreset row comments in array order
    comment_rows = extract_load_preset_comment_names(proc_text)
    if not comment_rows:
        errors.append("could not find loadPreset `// N: Name` designation comments")
    else:
        if len(comment_rows) != EXPECTED_PROGRAMS:
            errors.append(f"loadPreset carries {len(comment_rows)} `// N: Name` designation "
                          f"comments, expected {EXPECTED_PROGRAMS}")
        seen = [i for (i, _) in comment_rows]
        if seen != list(range(EXPECTED_PROGRAMS)):
            errors.append(f"loadPreset row comments are not a clean 0..{EXPECTED_PROGRAMS - 1} "
                          f"sequence (got {seen})")
        if len(comment_rows) == EXPECTED_PROGRAMS and len(proc_names) == EXPECTED_PROGRAMS:
            for (idx, cname), pname in zip(comment_rows, proc_names):
                if norm(cname) != norm(pname):
                    errors.append(f"loadPreset table row {idx} comment says \"{cname}\" but "
                                  f"getProgramName[{idx}] is \"{pname}\" (comment rows no "
                                  f"longer describe their own score columns)")
    return errors


def main() -> int:
    proc_text = PROC.read_text(encoding="utf-8", errors="replace")
    edit_text = EDIT.read_text(encoding="utf-8", errors="replace")
    errors = check(proc_text, edit_text)

    if errors:
        print("FAIL: preset name correspondence violations:")
        for e in errors:
            print(f"  - {e}")
        return 1

    print(f"OK: preset names consistent across getProgramName / editor combo / "
          f"loadPreset comments ({EXPECTED_PROGRAMS} programs)")

    # ---- negative self-probes (mutated in-memory texts; real tree never mutated) ----
    probes_fired = 0

    def require_reject(name: str, mutated_proc: str, mutated_edit: str) -> None:
        nonlocal probes_fired
        if check(mutated_proc, mutated_edit):
            probes_fired += 1
            print(f"preset-names probe '{name}': rejected as expected")
        else:
            print(f"preset-names probe '{name}': mutation accepted when it should be "
                  f"rejected — checker asserted nothing")
            sys.exit(1)

    def require_pass(name: str, mutated_proc: str, mutated_edit: str) -> None:
        if check(mutated_proc, mutated_edit):
            print(f"preset-names probe '{name}': rejected when it should pass — "
                  f"checker false-positives")
            sys.exit(1)
        print(f"preset-names probe '{name}': no-op neighbour passes (specificity guard)")

    # probe 1: temp-rename one getProgramName string (row-name desync)
    orig = '"Silk Thread"'
    if orig not in proc_text:
        print("preset-names probe 'getProgramName rename': NO-OP — stale, failing self-check")
        return 1
    require_reject("getProgramName rename", proc_text.replace(orig, '"Silk Fiber"'), edit_text)

    # probe 2: temp-swap two editor combo names via their addItem rows
    if '"Subtle Glue", 5' not in edit_text or '"Glass Canon", 6' not in edit_text:
        print("preset-names probe 'editor swap': NO-OP — stale, failing self-check")
        return 1
    e2 = edit_text.replace('"Subtle Glue", 5', '"Glass Canon", 5').replace(
        '"Glass Canon", 6', '"Subtle Glue", 6')
    require_reject("editor swap", proc_text, e2)

    # probe 3: temp-drop one loadPreset row comment name (comment airbrushed)
    if "// 1: Crystal Shimmer" not in proc_text:
        print("preset-names probe 'row comment drop': NO-OP — stale, failing self-check")
        return 1
    require_reject("row comment drop",
                   proc_text.replace("// 1: Crystal Shimmer", "// 1: unnamed"), edit_text)

    # no-op specificity guard: a comment-line tweak outside the name rows must pass
    require_pass("neighbour no-op", proc_text.replace("// 0: Clean Sparkle — subtle widening",
                                                     "// 0: Clean Sparkle  — subtle widening"),
                 edit_text)
    print(f"preset-names probes: {probes_fired} negatives fired, no-op neighbour passes")

    return 0


if __name__ == "__main__":
    sys.exit(main())
