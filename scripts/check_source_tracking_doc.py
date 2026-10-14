#!/usr/bin/env python3
"""check_source_tracking_doc.py — pin the vertical-slice Plan's
doc-modification contract for docs/SOURCE_TRACKING_VERIFICATION.md.

SoT: docs/superpowers/plans/2026-08-08-corvus-instrument-vertical-slice.md
  - File-Structure table names the doc "Updated source and binary
    verification map" (:41)
  - Task 1 lists it as Modify (:49) and its Step-6 commit list includes
    docs/SOURCE_TRACKING_VERIFICATION.md (:110)
  - Task 8 lists it as Modify again (:356) and its Step-2 requires REAL
    SHA-256 provenance hashes — no fabricated "verified" state (:379)

The doc currently carries only Windows-era anchors (C:/Projects SoT path,
DrippyMk1/DrippyMk2 provenance, the commit-hygiene rule). Nothing in the
gate re-verifies those anchors survive while Tasks 1-8 append the
vertical-slice source map entries (dsp/CorvusEffects.h, instrument
headers, tests/CorvusDspTests.cpp).

Checks:
  A. Doc exists and retains: title line, Windows absolute paths under
     C:/Projects, DrippyMk1/DrippyMk2 provenance, the commit-hygiene
     rule sentence.
  B. The Plan cites the doc at the File-Structure table, Task-1 Modify
     list, Task-8 Modify list, Task-1 Step-6 commit list, and Task's
     real-SHA-256 verification step — read-only.
Negative probes (never on the real tree):
  N1. Strip the commit-hygiene section from the doc -> FAIL
  N2. Replace the doc with a fabricated "verified" snapshot stub that
      claims hashes without recording any -> FAIL
  N3. Drop the doc reference from the Plan's File-Structure table -> FAIL
  N0. No-op mutation guarded (mutation must actually change the text).
Exit 0 only when the real tree passes and every negative fires.
"""

import os
import re
import sys
import tempfile
import shutil

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
PLAN = os.path.join(ROOT, "docs", "superpowers", "plans",
                    "2026-08-08-corvus-instrument-vertical-slice.md")
DOC = os.path.join(ROOT, "docs", "SOURCE_TRACKING_VERIFICATION.md")


def strip_markers(text: str) -> str:
    """Neutralize markdown emphasis/backticks so regexes match plain words."""
    return re.sub(r"`+", "", text)


def doc_checks(doc_text: str):
    """Anchor checks on the source-tracking doc (comment-stripped)."""
    plain = strip_markers(doc_text)
    res = []
    res.append(("doc is non-empty", bool(plain.strip()), "existence"))
    res.append(("title names the tracking task",
                re.search(r"Source tracking verification \(task \w+\)",
                          plain) is not None, "title"))
    res.append(("Windows absolute SoT path present (C:/Projects ...)",
                re.search(r"C:/Projects/Corvus VST|C:.Projects.Corvus VST",
                          plain) is not None, "git-SoT path"))
    res.append(("DrippyMk1 provenance retained",
                "DrippyMk1" in plain, "binary provenance"))
    res.append(("DrippyMk2 provenance retained",
                "DrippyMk2" in plain, "binary provenance"))
    res.append(("commit-hygiene rule retains source+binary pairing",
                re.search(r"must\s+include\s+matching\s+source/DrippyFX/",
                          plain) is not None, "commit hygiene"))
    res.append(("binary-only quality commits still prohibited",
                re.search(r"binary-only\s+quality\s+commits\s+are\s+not\s+"
                          r"(allowed|rewritten)", plain, re.I) is not None,
                "commit hygiene"))
    return res


def plan_checks(plan_text: str):
    """Plan must still cite the doc at its documented surfaces. Read-only."""
    plain = strip_markers(plan_text)
    res = []
    res.append(("File-Structure table names the doc as verification map",
                re.search(r"SOURCE_TRACKING_VERIFICATION\.md\s*\|\s*Updated "
                          r"source and binary verification map", plain)
                is not None, "file-structure table"))
    res.append(("Task 1 lists the doc as Modify",
                re.search(r"Modify:\s*docs/SOURCE_TRACKING_VERIFICATION\.md",
                          plain) is not None, "task-1 file list"))
    res.append(("Task 8 lists the doc as Modify",
                re.search(r"Modify:\s*docs/SOURCE_TRACKING_VERIFICATION\.md",
                          plain) is not None, "task-8 file list"))
    res.append(("Task 1 Step-6 commit list includes the doc",
                re.search(r"git add\s+.*docs/SOURCE_TRACKING_VERIFICATION\.md",
                          plain, re.S) is not None, "step-6 commit"))
    res.append(("real SHA-256 provenance requirement present (Task 8)",
                re.search(r"Record\s+SHA-256\s+for", plain) is not None,
                "anti-fabrication"))
    return res


def run_doc(text: str, verbose=True):
    ok = True
    for label, good, detail in doc_checks(text):
        if verbose:
            print(("PASS " if good else "FAIL ") +
                  "src-tracking(doc): " + label + " (%s)" % detail)
        ok = ok and good
    return 0 if ok else 1


def run_plan(text: str, verbose=True):
    ok = True
    for label, good, detail in plan_checks(text):
        if verbose:
            print(("PASS " if good else "FAIL ") +
                  "src-tracking(plan): " + label + " (%s)" % detail)
        ok = ok and good
    return 0 if ok else 1


def main():
    missing = [p for p in (PLAN, DOC) if not os.path.isfile(p)]
    if missing:
        for p in missing:
            print("GATE_FAIL: %s missing" % p)
        return 1
    with open(PLAN, "r", encoding="utf-8") as f:
        plan_text = f.read()
    with open(DOC, "r", encoding="utf-8") as f:
        doc_text = f.read()

    # No-op guard: the mutation helper must actually change the text
    noop = doc_text.replace("SOURCE_TRACKING_VERIFICATION", "")
    if noop != doc_text:
        print("GATE_FAIL: no-op probe mutated the real doc unexpectedly")
        return 1

    if run_doc(doc_text) != 0:
        return 1
    if run_plan(plan_text) != 0:
        return 1

    negs = [
        ("strip the commit-hygiene section from the doc",
         doc_text,
         lambda s: s.split("## Commit hygiene")[0]),
        ("fabricate a verified snapshot stub with no real hashes",
         doc_text,
         lambda s: "# Source tracking verification (task t_b97d4512)\n\n"
                   "## Post-import checks (run after commit)\n\n"
                   "All artifact hashes verified.\n"),
        ("drop DrippyMk1/DrippyMk2 provenance from the doc",
         doc_text,
         lambda s: s.replace("DrippyMk1", "X").replace("DrippyMk2", "X")),
    ]
    tmpdir = tempfile.mkdtemp(prefix="check_source_tracking_doc_")
    try:
        for label, _, mutate in negs:
            mutated = mutate(doc_text)
            if mutated == doc_text:
                print("GATE_FAIL: negative '%s' mutation is a no-op — "
                      "checker stale vs doc" % label)
                return 1
            if run_doc(mutated, verbose=False) == 0:
                print("GATE_FAIL: negative check '%s' did NOT fail — "
                      "checker too weak" % label)
                return 1
            print("PASS src-tracking(doc): negative rejected -> " + label)

        # Plan-side negative: drop the doc from the File-Structure table
        # (mutate the marker-stripped text; run_plan strips again idempotently)
        p_source = strip_markers(plan_text)
        pmut = p_source.replace(
            "docs/SOURCE_TRACKING_VERIFICATION.md | Updated source and "
            "binary verification map", "docs/SOURCE_TRACKING_VERIFICATION.md")
        if pmut == p_source:
            print("GATE_FAIL: plan-side negative mutation is a no-op")
            return 1
        if run_plan(pmut, verbose=False) == 0:
            print("GATE_FAIL: plan-side negative did NOT fail — "
                  "checker too weak")
            return 1
        print("PASS src-tracking(plan): negative rejected -> doc lost its "
              "verification-map role in the File-Structure table")
    finally:
        shutil.rmtree(tmpdir, ignore_errors=True)

    print("OK source-tracking doc contract pinned (doc anchors + Plan "
          "citations guarded before Tasks 1-8 mutate the doc)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
