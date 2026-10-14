#!/usr/bin/env python3
"""check_sync_script_contract.py — pin the vertical-slice Plan's Task-1
Step-3 sync-script contract BEFORE scripts/sync_corvus_source.ps1 exists.

SoT: docs/superpowers/plans/2026-08-08-corvus-instrument-vertical-slice.md
Task 1 Step 3 ("Write the explicit sync script"):
  The script accepts -VerifyOnly, validates the source and destination
  roots, uses an explicit relative-path array, creates only required
  destination directories, copies with Copy-Item -LiteralPath, and
  compares SHA-256 after copying. It must not delete or mirror entire
  directories.

Every later Plan task appends paths to this same script's source map, so a
sloppy first version (Get-ChildItem | Copy-Item style recursive mirror)
would silently propagate dir-mirror hazards into five later edits.

Checks:
  A. The Task 1 Step-3 block still declares the documented contract
     (read-only, marker-stripped): -VerifyOnly, explicit relative-path
     array, SHA-256 compare, Copy-Item -LiteralPath, no delete/mirror
     directories.
  B. Once scripts/sync_corvus_source.ps1 exists, the script itself must
     contain -VerifyOnly, an explicit path array token, a SHA-256 /
     Get-FileHash compare, Copy-Item -LiteralPath, and NO recursive
     Get-ChildItem-piped-to-Copy-Item mirror of the source root.
     SKIPPED while the file is absent — not a pass-fake: a printed SKIP
     line cites the rule. No sync script is authored from this Mac
     (Windows-only path semantics stay defer-to-Task-1).
Negative probes (never on the real tree):
  N1. drop the SHA-256 sentence from the Plan Step-3 block -> FAIL
  N2. drift the mirror prohibition sentence out of Step 3 -> FAIL
  N3. stub sync script using Get-ChildItem recursion and no hash -> FAIL
      (part B, exercised against a temp dir, not the real path)
Exit 0 only when the real Plan passes and every negative fires.
"""

import os
import re
import sys
import tempfile
import shutil

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
PLAN = os.path.join(ROOT, "docs", "superpowers", "plans",
                    "2026-08-08-corvus-instrument-vertical-slice.md")
SYNC = os.path.join(ROOT, "scripts", "sync_corvus_source.ps1")


def strip_markers(text: str) -> str:
    """Neutralize markdown emphasis/backticks so regexes match plain words."""
    return re.sub(r"`+", "", text)


def step3_block(plan_text: str) -> str:
    """Source region of Task 1 Step 3 (from its checkbox to the next one)."""
    strip = strip_markers(plan_text)
    m = re.search(r"^-\s*\[ \]\s*\*{0,2}\s*Step 3:.*$", strip, re.M)
    if not m:
        return ""
    nxt = re.search(r"^-\s*\[ \]\s*\*{0,2}\s*Step \d+:.*$", strip[m.end():],
                    re.M)
    end = m.end() + (nxt.start() if nxt else len(strip) - m.end())
    return strip[m.start():end]


def plan_checks(block: str):
    """Comment-stripped Step-3 block checks. (label, ok, detail) tuples."""
    res = []
    res.append(("block is non-empty", bool(block.strip()),
                "Step 3 checkbox found"))
    res.append(("-VerifyOnly flag declared",
                re.search(r"accepts\s+-VerifyOnly", block) is not None,
                "verify-only"))
    res.append(("validates source and destination roots",
                re.search(r"validates\s+the\s+source\s+and\s+destination",
                          block) is not None, "root validation"))
    res.append(("explicit relative-path array declared",
                re.search(r"explicit\s+relative-path\s+array", block,
                          re.I) is not None, "explicit path map"))
    res.append(("creates only required destination directories",
                re.search(r"creates\s+only\s+required\s+destination",
                          block) is not None, "mkdir discipline"))
    res.append(("copies with Copy-Item -LiteralPath",
                re.search(r"Copy-Item\s+-LiteralPath", block) is not None,
                "literal copy"))
    res.append(("compares SHA-256 after copying",
                re.search(r"compares\s+SHA-256\s+after\s+copying", block)
                is not None, "hash compare"))
    res.append(("must not delete or mirror entire directories",
                re.search(r"must\s+not\s+delete\s+or\s+mirror\s+entire",
                          block) is not None, "anti-mirror"))
    return res


def script_checks(code: str):
    """Once the sync script exists, its shape must match the contract."""
    res = []
    res.append(("-VerifyOnly parameter accepted",
                re.search(r"-VerifyOnly|\bwitness\b|VerifyOnly", code)
                is not None, "verify flag"))
    res.append(("explicit path array present",
                re.search(r"\$[A-Za-z_]\w*\s*=\s*@\s*\(",
                          code) is not None, "path array"))
    res.append(("SHA-256 / Get-FileHash compare present",
                re.search(r"SHA-?256|Get-FileHash", code, re.I) is not None,
                "hash check"))
    res.append(("Copy-Item -LiteralPath copy present",
                re.search(r"Copy-Item\s+.*-LiteralPath",
                          code, re.S) is not None, "literal copy"))
    res.append(("NO Get-ChildItem -> Copy-Item recursive mirror",
                re.search(r"Get-ChildItem.*\|\s*Copy-Item", code, re.S)
                is None, "anti-mirror"))
    res.append(("NO -Recurse on Copy-Item of the source root",
                re.search(r"Copy-Item[^\n]*-Recurse", code) is None,
                "no recursive copy"))
    return res


def run_plan(text: str, verbose=True):
    block = step3_block(text)
    ok = True
    for label, good, detail in plan_checks(block):
        if verbose:
            print(("PASS " if good else "FAIL ") +
                  "sync-script(plan): " + label + " (%s)" % detail)
        ok = ok and good
    return 0 if ok else 1


def run_script(path: str, verbose=True):
    if os.path.isfile(path):
        with open(path, "r", encoding="utf-8", errors="replace") as f:
            code = f.read()
    else:
        with open(path, "r", encoding="utf-8", errors="replace") as f:
            code = f.read()
    ok = True
    for label, good, detail in script_checks(code):
        if verbose:
            print(("PASS " if good else "FAIL ") +
                  "sync-script(psl): " + label + " (%s)" % detail)
        ok = ok and good
    return 0 if ok else 1


def main():
    if not os.path.isfile(PLAN):
        print("GATE_FAIL: %s missing" % PLAN)
        return 1
    with open(PLAN, "r", encoding="utf-8") as f:
        plan_text = f.read()
    rc = run_plan(plan_text)
    if rc != 0:
        return 1

    # Part B: only while the sync script exists
    if os.path.isfile(SYNC):
        if run_script(SYNC) != 0:
            return 1
    else:
        print("SKIP sync-script(psl): no %s yet — script checks not "
              "engaged (will auto-activate when Plan Task 1 Step 3 is "
              "implemented on Windows)" % os.path.relpath(SYNC, ROOT))

    # Negative probes on temp copies (never the real tree)
    negs = [
        ("drop the SHA-256 compare sentence from Step 3",
         lambda s: s.replace("compares SHA-256 after copying.", "")),
        ("drop the anti-mirror prohibition from Step 3",
         lambda s: s.replace("It must not delete or mirror entire "
                             "directories.", "")),
        ("drift -VerifyOnly out of the Step-3 requirement",
         lambda s: s.replace("accepts `-VerifyOnly`", "accepts a mode arg")),
    ]
    tmpdir = tempfile.mkdtemp(prefix="check_sync_script_contract_")
    try:
        for label, mutate in negs:
            mutated = mutate(plan_text)
            if mutated == plan_text:
                print("GATE_FAIL: negative '%s' mutation is a no-op — "
                      "checker stale vs plan" % label)
                return 1
            if run_plan(mutated, verbose=False) == 0:
                print("GATE_FAIL: negative check '%s' did NOT fail — "
                      "checker too weak" % label)
                return 1
            print("PASS sync-script(plan): negative rejected -> " + label)

        # Part-B negative: hazardous stub sync script in a temp dir
        stub = os.path.join(tmpdir, "sync_corvus_source.ps1")
        with open(stub, "w", encoding="utf-8") as f:
            f.write("param([string]$Mode)\n"
                    "Get-ChildItem $src -Recurse | Copy-Item -Destination "
                    "$dst\n")
        if run_script(stub, verbose=False) == 0:
            print("GATE_FAIL: stub sync script (recursive mirror, no hash) "
                  "was NOT rejected — checker too weak")
            return 1
        print("PASS sync-script(psl): negative rejected -> Get-ChildItem "
              "mirror stub with no SHA-256 fails")
    finally:
        shutil.rmtree(tmpdir, ignore_errors=True)

    print("OK sync-script contract pinned (Plan Task-1 Step-3 contract "
          "guarded before the sync script exists)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
