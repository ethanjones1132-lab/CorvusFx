#!/usr/bin/env python3
"""Headless checker: undo-transaction banner roster pin.

PluginProcessor.cpp carries exactly five beginNewTransaction call sites:
  - 1x "Load Preset"   (loadPreset)
  - 1x "Randomize"     (randomize)
  - 4x "A/B Compare"   (the A/B copy/restore bodies)

check_undo_wiring.py pins the A/B Compare family only at >= 2 cardinality
and Load Preset / Randomize at existence — never the exact count=4 roster,
never Load-Preset/Randomize exactness, and never a foreign-banner
rejection (any OTHER string literal passed to beginNewTransaction).

Designed-in hazards (compile clean behind an otherwise-green gate):
  - deleting one A/B Compare banner leaves that restore path undo-silent:
    Ctrl+Z replays the PREVIOUS transaction and stomps an unrelated edit
    range;
  - renaming one banner ("A/B Compare" -> "A/B Restore") fragments the
    history into two names for one logical action;
  - a stray foreign banner (e.g. "Randomize ALL") brands a new
    transaction without a paired checker pin.

Asserts are comment-stripped. Negative self-probes run on mutated
in-memory texts — the real tree is never mutated.
Exit 0 = ok, 1 = violation with diagnostics.
"""
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
PROC = ROOT / "source" / "DrippyFX" / "PluginProcessor.cpp"

EXPECTED = {
    "Load Preset": 1,
    "Randomize": 1,
    "A/B Compare": 4,
}


def fail(msg):
    print(f"UNDO-TRANSACTIONS FAIL: {msg}")
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


def collect(txt):
    return re.findall(
        r'beginNewTransaction\s*\(\s*"((?:[^"\\]|\\.)*)"\s*\)', txt)


def check(banner_sites):
    counts = {}
    for name in banner_sites:
        counts[name] = counts.get(name, 0) + 1
    for name, want in EXPECTED.items():
        got = counts.get(name, 0)
        if got != want:
            return (f'expected exactly {want} beginNewTransaction("{name}") '
                    f"site(s), found {got} — a deleted banner leaves that "
                    f"path undo-silent (Ctrl+Z replays the PREVIOUS "
                    f"transaction), a renamed banner fragments the history "
                    f"into two names for one logical action")
    foreign = sorted(n for n in counts if n not in EXPECTED)
    if foreign:
        return ("unexpected foreign beginNewTransaction banner(s) " +
                ", ".join(f'"{n}" (x{counts[n]})' for n in foreign) +
                " — the banner name roster is pinned to the five "
                "Load Preset / Randomize / 4x A/B Compare transactions")
    return None


if not PROC.exists():
    fail(f"missing source file {PROC}")
ab = check(collect(strip_comments(PROC.read_text())))
if ab:
    fail(ab + " (PluginProcessor.cpp)")
print("undo-transactions: banner roster pinned "
      "(1x Load Preset, 1x Randomize, 4x A/B Compare, no foreign banners)")

# ---------------------------------------------------------------------------
# Self-probes on mutated in-memory texts (real tree never mutated)
# ---------------------------------------------------------------------------

AB_LINE = 'undoManager.beginNewTransaction("A/B Compare");'


def probe(description, old, new, count=1):
    tmp_raw = strip_comments(PROC.read_text()).replace(old, new, count)
    err = check(collect(tmp_raw))
    if err is None:
        print(f"undo-transactions: SELF-PROBE FAIL (checker should "
              f"reject): {description}")
        sys.exit(1)
    print(f"undo-transactions: self-probe fired: {description} -> rejected")


probe("one A/B Compare banner deleted (that restore path undo-silent)",
      AB_LINE + "\n", "", 1)
probe("one A/B Compare banner renamed (history fragments into two names)",
      'beginNewTransaction("A/B Compare")',
      'beginNewTransaction("A/B Restore")', 1)
probe("all four A/B Compare banners collapsed to one (restore paths "
      "undo-silent)", AB_LINE, 'beginNewTransaction("Load Preset");', 3)
probe("foreign banner added (unpinned transaction name)",
      AB_LINE, AB_LINE.replace(';', '') +
      ' || undoManager.beginNewTransaction("Randomize ALL");', 1)
probe("Randomize banner dropped (beginRandomize undo granularity gone)",
      'undoManager.beginNewTransaction("Randomize");\n', "", 1)

# no-op guard: benign comment stays rejected-from-count and accepted
raw_txt = PROC.read_text() + "\n// beginNewTransaction(\"A/B Compare\") future site\n"
tmp = strip_comments(raw_txt)
if check(collect(tmp)) is not None:
    fail("no-op guard: harmless commented-out banner wrongly counted")
print("undo-transactions: no-op guard passed (commented banner ignored)")

print("UNDO-TRANSACTIONS OK")
