#!/usr/bin/env python3
"""CV-011 FX preset index table check.

Pins the preset index tables in source/DrippyFX/PluginProcessor.cpp:

  A. getNumPrograms() returns 36.
  B. idToPreset[43], presetFromId[43] and presetToId[36] declare the size they
     actually carry.
  C. Every live combo id in idToPreset maps into 0..35, and every preset index
     0..35 owns a combo id in both idToPreset and presetFromId.
  D. presetFromId is the reverse of idToPreset on every combo id.
  E. presetToId is the exact inverse of idToPreset, with 36 unique combo ids in
     0..42.
  F. getNumPrograms() equals the preset count carried by presetToId.

Each failure cites source/DrippyFX/PluginProcessor.cpp:line.

Negative probes mutate the source text in memory only (the repo tree is never
written). Every probe first proves its mutation applied: the mutated text must
differ from the original and the re-parsed table must differ too. A probe whose
mutation is a no-op aborts the checker instead of trusting a rejection that
never happened.

Exit 0 only when the real tree passes, every negative mutation is rejected for
the intended reason, and the benign edits are accepted.
"""

import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SRC = ROOT / "source" / "DrippyFX" / "PluginProcessor.cpp"
SRC_REL = "source/DrippyFX/PluginProcessor.cpp"

EXPECTED_PROGRAMS = 36
EXPECTED_COMBO_IDS = 43
EXPECTED_REVERSE_IDS = 43
EXPECTED_FORWARD_IDS = 36

TABLE_NAMES = ("idToPreset", "presetFromId", "presetToId")
TABLE_SIZES = {
    "idToPreset": EXPECTED_COMBO_IDS,
    "presetFromId": EXPECTED_REVERSE_IDS,
    "presetToId": EXPECTED_FORWARD_IDS,
}


def read_normalised(path):
    """Read a text file with LF endings so offsets and lines are portable."""
    text = path.read_text(encoding="utf-8", errors="replace")
    return text.replace("\r\n", "\n").replace("\r", "\n")


def mask_cpp_comments(text):
    """Blank out // and /* */ comments, preserving offsets and line breaks.

    Parsing therefore sees code only: numeric comments around the tables are
    ignored, and a commented-out table cannot satisfy any check.
    """
    def blank_block(match):
        return "".join("\n" if ch == "\n" else " " for ch in match.group(0))

    masked = re.sub(r"/\*.*?\*/", blank_block, text, flags=re.S)
    return re.sub(r"//[^\n]*", lambda m: " " * len(m.group(0)), masked)


def line_of(text, offset):
    return text.count("\n", 0, offset) + 1


def find_table(text, name):
    """Parse `static const int NAME[N] = { ... };` with its body span."""
    pattern = (r"static\s+const\s+int\s+" + name
               + r"\s*\[\s*(\d+)\s*\]\s*=\s*\{(.*?)\}\s*;")
    masked = mask_cpp_comments(text)
    m = re.search(pattern, masked, flags=re.S)
    if not m:
        return None
    values = [int(v) for v in re.findall(r"-?\d+", m.group(2))]
    return {
        "name": name,
        "declared": int(m.group(1)),
        "values": values,
        "line": line_of(text, m.start()),
        "body_start": m.start(2),
        "body_end": m.end(2),
    }


def find_num_programs(text):
    """Parse `int CorvusFXAudioProcessor::getNumPrograms() { return N; }`."""
    pattern = (r"int\s+CorvusFXAudioProcessor::getNumPrograms\s*\(\s*\)\s*"
               r"\{\s*return\s+(\d+)\s*;\s*\}")
    m = re.search(pattern, mask_cpp_comments(text))
    if not m:
        return None
    return {"value": int(m.group(1)), "line": line_of(text, m.start())}


def first_line(text, needle):
    """Best-effort line for a failure when the structure itself is missing."""
    index = text.find(needle)
    return line_of(text, index) if index >= 0 else 1


def evaluate(text):
    """Return (checks, failures) for one source text.

    checks   -- list of (label, ok, line) in reporting order.
    failures -- list of (label, detail, line) for every failed check.
    """
    tables = {name: find_table(text, name) for name in TABLE_NAMES}
    programs = find_num_programs(text)

    id_line = tables["idToPreset"]["line"] if tables["idToPreset"] \
        else first_line(text, "idToPreset")
    from_line = tables["presetFromId"]["line"] if tables["presetFromId"] \
        else first_line(text, "presetFromId")
    to_line = tables["presetToId"]["line"] if tables["presetToId"] \
        else first_line(text, "presetToId")
    prog_line = programs["line"] if programs else first_line(text, "getNumPrograms")

    checks = []
    failures = []

    def add(label, ok, line, detail):
        checks.append((label, ok, line))
        if not ok:
            failures.append((label, detail, line))

    # A. getNumPrograms() returns 36.
    add("getNumPrograms() returns 36",
        programs is not None and programs["value"] == EXPECTED_PROGRAMS,
        prog_line,
        "getNumPrograms() returns "
        + (str(programs["value"]) if programs else "nothing parsable")
        + ", expected " + str(EXPECTED_PROGRAMS))

    # B. Declared sizes match the values actually present.
    for name in TABLE_NAMES:
        table = tables[name]
        expected = TABLE_SIZES[name]
        add(name + "[] declares " + str(expected) + " entries with "
            + str(expected) + " values",
            table is not None
            and table["declared"] == expected
            and len(table["values"]) == expected,
            table["line"] if table else first_line(text, name),
            name + "[] not found" if table is None
            else name + "[] declared [" + str(table["declared"]) + "] with "
            + str(len(table["values"])) + " values, expected "
            + str(expected))

    id2p = tables["idToPreset"]
    pfi = tables["presetFromId"]
    pti = tables["presetToId"]

    # C. Combo ids resolve into the preset range and every index is reachable.
    if id2p is not None:
        live = [v for v in id2p["values"] if v >= 0]
        add("every idToPreset combo id maps into 0..35",
            all(v == -1 or 0 <= v < EXPECTED_PROGRAMS
                for v in id2p["values"]),
            id2p["line"],
            "idToPreset values " + str(id2p["values"])
            + " contain something other than -1 or 0.."
            + str(EXPECTED_PROGRAMS - 1))
        add("every preset index has an idToPreset combo id",
            sorted(live) == list(range(EXPECTED_PROGRAMS)),
            id2p["line"],
            "idToPreset preset indices " + str(sorted(live))
            + " are not exactly 0.." + str(EXPECTED_PROGRAMS - 1))
    else:
        add("every idToPreset combo id maps into 0..35", False, id_line,
            "idToPreset[] not found")
        add("every preset index has an idToPreset combo id", False, id_line,
            "idToPreset[] not found")

    if pfi is not None:
        live = [v for v in pfi["values"] if v >= 0]
        add("every preset index has a presetFromId combo id",
            sorted(live) == list(range(EXPECTED_PROGRAMS)),
            pfi["line"],
            "presetFromId preset indices " + str(sorted(live))
            + " are not exactly 0.." + str(EXPECTED_PROGRAMS - 1))
    else:
        add("every preset index has a presetFromId combo id", False, from_line,
            "presetFromId[] not found")

    # D. presetFromId must be the reverse of idToPreset on every combo id.
    if id2p is not None and pfi is not None \
            and len(id2p["values"]) == len(pfi["values"]) == EXPECTED_COMBO_IDS:
        mismatch = next((i for i, (a, b) in enumerate(
            zip(id2p["values"], pfi["values"])) if a != b), None)
        add("presetFromId is the reverse of idToPreset",
            mismatch is None,
            pfi["line"],
            "presetFromId is the reverse of idToPreset"
            if mismatch is None
            else "presetFromId[" + str(mismatch) + "]="
            + str(pfi["values"][mismatch]) + " != idToPreset["
            + str(mismatch) + "]=" + str(id2p["values"][mismatch]))
    else:
        add("presetFromId is the reverse of idToPreset", False, from_line,
            "idToPreset[]/presetFromId[] missing or wrong length")

    # E. presetToId is the exact inverse: index -> id -> index.
    if id2p is not None and pfi is not None and pti is not None \
            and len(id2p["values"]) == EXPECTED_COMBO_IDS \
            and len(pfi["values"]) == EXPECTED_COMBO_IDS \
            and len(pti["values"]) == EXPECTED_FORWARD_IDS:
        bad = None
        for index, cid in enumerate(pti["values"]):
            if not (0 <= cid < EXPECTED_COMBO_IDS) \
                    or id2p["values"][cid] != index \
                    or pfi["values"][cid] != index:
                bad = (index, cid)
                break
        add("presetToId is the inverse of idToPreset",
            bad is None,
            pti["line"],
            "presetToId is not the inverse of idToPreset"
            if bad is None
            else "presetToId[" + str(bad[0]) + "]=" + str(bad[1])
            + " does not round-trip through idToPreset/presetFromId")

        add("presetToId has 36 unique combo ids in 0..42",
            len(set(pti["values"])) == EXPECTED_FORWARD_IDS
            and all(0 <= cid < EXPECTED_COMBO_IDS for cid in pti["values"]),
            pti["line"],
            "presetToId ids are not 36 unique values in 0.."
            + str(EXPECTED_COMBO_IDS - 1))
    else:
        add("presetToId is the inverse of idToPreset", False, to_line,
            "idToPreset[]/presetFromId[]/presetToId[] missing or wrong length")
        add("presetToId has 36 unique combo ids in 0..42", False, to_line,
            "presetToId[] missing or wrong length")

    # F. Host program count agrees with the forward table.
    add("getNumPrograms() equals the preset count",
        programs is not None and pti is not None
        and programs["value"] == len(pti["values"])
        and programs["value"] == EXPECTED_PROGRAMS,
        prog_line,
        "getNumPrograms() returns "
        + (str(programs["value"]) if programs else "nothing parsable")
        + " but presetToId[] carries "
        + (str(len(pti["values"])) if pti else "no parsable values"))

    return checks, failures


def run_checks(text, verbose=True):
    """Run the contract checks on one source text. Returns 0 if all pass."""
    checks, failures = evaluate(text)
    if verbose:
        for label, ok, line in checks:
            print(("PASS " if ok else "FAIL ") + "cv011-preset-index-tables: "
                  + label + " (" + SRC_REL + ":" + str(line) + ")")
        for label, detail, line in failures:
            print("  detail " + SRC_REL + ":" + str(line) + ": " + detail)
    return 0 if not failures else 1


def find_failure(failures, needle):
    """True when the rejection names the invariant the probe targeted."""
    return any(needle in detail or needle in label
               for label, detail, _line in failures)


def expect_reject(label, text, original, needle):
    """Expect the mutated text to fail, for the intended reason."""
    if text == original:
        print("GATE_FAIL: negative probe '" + label + "' mutation was a no-op;"
              " refusing to trust any rejection")
        return False
    _, failures = evaluate(text)
    if not failures:
        print("GATE_FAIL: negative check '" + label + "' did NOT fail -"
              " checker too weak")
        return False
    if not find_failure(failures, needle):
        print("GATE_FAIL: negative check '" + label + "' failed for an"
              " unexpected reason; wanted a '" + needle + "' failure, got:")
        for fail_label, detail, line in failures:
            print("    " + SRC_REL + ":" + str(line) + ": " + detail)
        return False
    print("PASS cv011-preset-index-tables: mutation applied and negative"
          " rejected -> " + label)
    return True


def expect_accept(label, text, original):
    """Expect a benign in-memory edit to still pass."""
    if text == original:
        print("GATE_FAIL: benign probe '" + label + "' edit was a no-op;"
              " refusing to trust the acceptance")
        return False
    if run_checks(text, verbose=False) != 0:
        print("GATE_FAIL: benign edit '" + label + "' was rejected -"
              " checker over-fitted to the current text")
        return False
    print("PASS cv011-preset-index-tables: mutation applied and benign edit"
          " accepted -> " + label)
    return True


def mutate_body(text, table, old, new):
    """Replace `old` once inside one table body. Returns (text, occurrences)."""
    body = text[table["body_start"]:table["body_end"]]
    occurrences = body.count(old)
    if occurrences == 0:
        return text, 0
    mutated_body = body.replace(old, new, 1)
    if mutated_body == body:
        return text, 0
    return (text[:table["body_start"]] + mutated_body
            + text[table["body_end"]:], occurrences)


def main():
    if not SRC.is_file():
        print("GATE_FAIL: " + SRC_REL + " missing")
        return 1

    source_text = read_normalised(SRC)

    if run_checks(source_text) != 0:
        return 1

    id2p = find_table(source_text, "idToPreset")
    pfi = find_table(source_text, "presetFromId")
    pti = find_table(source_text, "presetToId")
    if id2p is None or pfi is None or pti is None:
        print("GATE_FAIL: cannot parse all three preset index tables; probes"
              " cannot run")
        return 1

    # NEGATIVE 1: swap two WARM ids inside presetToId. Cardinality, range and
    # uniqueness all still hold, so only the inverse invariant can catch it.
    mutated, applied = mutate_body(source_text, pti, "9,10", "10,9")
    if applied != 1 or mutated == source_text:
        print("GATE_FAIL: negative 'presetToId WARM ids swapped' target was"
              " not unique or the mutation was a no-op; refusing to trust any"
              " rejection")
        return 1
    reparsed = find_table(mutated, "presetToId")
    if reparsed is None or reparsed["values"] == pti["values"]:
        print("GATE_FAIL: negative 'presetToId WARM ids swapped' mutation did"
              " not change the parsed table; refusing to trust any rejection")
        return 1
    if not expect_reject("presetToId WARM ids swapped", mutated, source_text,
                         "inverse"):
        return 1

    # NEGATIVE 2: duplicate preset index 30 as 29 in presetFromId, so one
    # preset index no longer owns a combo id. idToPreset is untouched.
    mutated, applied = mutate_body(source_text, pfi,
                                   "30,31,32,33,34,35",
                                   "29,31,32,33,34,35")
    if applied != 1 or mutated == source_text:
        print("GATE_FAIL: negative 'presetFromId preset index duplicated'"
              " target was not unique or the mutation was a no-op; refusing to"
              " trust any rejection")
        return 1
    reparsed = find_table(mutated, "presetFromId")
    if reparsed is None or reparsed["values"] == pfi["values"]:
        print("GATE_FAIL: negative 'presetFromId preset index duplicated'"
              " mutation did not change the parsed table; refusing to trust"
              " any rejection")
        return 1
    if not expect_reject("presetFromId preset index duplicated", mutated,
                         source_text, "presetFromId"):
        return 1

    # NEGATIVE 3: getNumPrograms() no longer agrees with the 36 program table.
    original_programs = "int CorvusFXAudioProcessor::getNumPrograms() { return 36; }"
    if source_text.count(original_programs) != 1:
        print("GATE_FAIL: negative 'getNumPrograms changed to 35' target is not"
              " unique in the source; refusing to trust any rejection")
        return 1
    mutated = source_text.replace(
        original_programs,
        "int CorvusFXAudioProcessor::getNumPrograms() { return 35; }")
    if mutated == source_text:
        print("GATE_FAIL: negative 'getNumPrograms changed to 35' mutation was"
              " a no-op; refusing to trust any rejection")
        return 1
    reparsed_programs = find_num_programs(mutated)
    if reparsed_programs is None or reparsed_programs["value"] != 35:
        print("GATE_FAIL: negative 'getNumPrograms changed to 35' mutation did"
              " not change the parsed value; refusing to trust any rejection")
        return 1
    if not expect_reject("getNumPrograms changed to 35", mutated, source_text,
                         "getNumPrograms"):
        return 1

    # BENIGN 1: add a comment inside presetToId that mentions numeric ids.
    # The checker must strip comments rather than read them as table values.
    mutated, applied = mutate_body(
        source_text, pti, "37,38,39,40,41,42",
        "37,38,39,40,41,42\n        // benign probe: 43 36 35 30 29 0 1 2")
    if applied != 1 or mutated == source_text:
        print("GATE_FAIL: benign 'numeric comment inside presetToId' target was"
              " not unique or the edit was a no-op; refusing to trust the"
              " acceptance")
        return 1
    if not expect_accept("numeric comment inside presetToId", mutated,
                         source_text):
        return 1

    # BENIGN 2: an unrelated trailing comment changes no table.
    mutated = source_text + "\n// benign probe: unrelated trailing comment\n"
    if mutated == source_text:
        print("GATE_FAIL: benign 'trailing comment appended' edit was a no-op;"
              " refusing to trust the acceptance")
        return 1
    if not expect_accept("trailing comment appended", mutated, source_text):
        return 1

    print("OK cv011 FX preset index tables pinned (43 combo ids, 36 programs,"
          " table inverse, comments ignored)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
