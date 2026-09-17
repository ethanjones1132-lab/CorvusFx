#!/usr/bin/env python3
"""Headless checker: EarlyReflections mute-on-room-size-change invariants.

Asserts (in the style of check_undo_wiring.py):
  (a) UpgradedReverb::beginBlock() still retargets earlyL/earlyR room size
      on EVERY block (the size mapping must stay live)
  (b) beginBlock() guards the earlyL.mute()/earlyR.mute() calls behind a
      lastRoomSize change test, so stale-tap clears only fire when the room
      actually moves — and the guard state (lastRoomSize) is declared
  (c) per-sample EarlyReflections::process() is untouched (no mute call there)
  (d) negative check: temp-mutated copy with the mute guard removed (mute()
      called on every block) must FAIL

Exit 0 = ok, 1 = violation with line-cited diagnostics.
"""
import os
import re
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SRC = Path(os.environ.get("EARLY_REFLECT_SRC", str(ROOT))) / "source" / "DrippyFX"


class Violation(Exception):
    pass


def check(srcdir: Path) -> list:
    def fail(msg):
        raise Violation(msg)

    p = srcdir / "PluginProcessor.h"
    if not p.exists():
        fail(f"missing source file {p}")
    text = p.read_text()
    lines = text.splitlines()
    notes = []

    # Locate UpgradedReverb::beginBlock body brace-matched
    m = re.search(
        r"void\s+beginBlock\s*\(\s*float\s+roomSize\s*,\s*float\s+damping", text)
    if not m:
        fail("PluginProcessor.h: UpgradedReverb::beginBlock not found")
    # take the LAST match candidate whose enclosing struct is UpgradedReverb —
    # find the brace after the parameter list
    b = text.find("{", m.start())
    if b == -1:
        fail("PluginProcessor.h: beginBlock body not found")
    depth, j = 0, b
    while j < len(text):
        if text[j] == "{":
            depth += 1
        elif text[j] == "}":
            depth -= 1
            if depth == 0:
                break
        j += 1
    body = text[m.start():j + 1]
    body_lines = body.splitlines()

    def ln_of_off(off):
        return text[:m.start() + off].count("\n") + 1 if off else -1

    # (a) every-block early retarget still applied
    retarget = [
        i for i, ln in enumerate(body_lines, 1)
        if re.search(r"early[LR]\.setRoomSize\s*\(", ln)
    ]
    if len(retarget) < 2:
        fail("beginBlock must still retarget BOTH earlyL and earlyR room size "
             "every block (earlyL.setRoomSize + earlyR.setRoomSize)")
    notes.append(f"early-reflect: per-block retarget -> lines "
                 f"{', '.join(str(i) for i in retarget)} of beginBlock body")

    # (b) mute calls exist and are guarded by a lastRoomSize change test
    mute_sites = [
        i for i, ln in enumerate(body_lines, 1)
        if re.search(r"early[LR]\.mute\s*\(", ln)
    ]
    if not mute_sites:
        fail("beginBlock no longer clears earlyL/earlyR on room-size change — "
             "stale taps from the old room would smear the new early field")
    # guard: some line in body tests lastRoomSize against a previous value
    guard = [
        i for i, ln in enumerate(body_lines, 1)
        if re.search(r"lastRoomSize", ln) and re.search(r"fabs|>|<|!=", ln)
    ]
    if not guard:
        fail("earlyL/earlyR mute() calls are not guarded by a lastRoomSize "
             "change test — muting every block would silence early energy "
             "and unguarded mute leaves the stale-tap smear unfixed")
    # guard line must precede the last mute site (mute inside the guard block)
    if min(min(mute_sites), max(mute_sites)) < min(guard):
        fail("mute() call precedes the lastRoomSize guard — the mute must be "
             "inside the guarded branch")
    notes.append(f"early-reflect: guarded mute -> guard line {guard[0]}, "
                 f"mute sites {mute_sites} of beginBlock body")

    # guard state declared in the class
    decl = [
        i for i, ln in enumerate(lines, 1)
        if re.search(r"\bfloat\s+lastRoomSize\b", ln)
    ]
    if not decl:
        fail("PluginProcessor.h: lastRoomSize state not declared — the guard "
             "has nothing to compare against")
    notes.append(f"early-reflect: lastRoomSize state -> "
                 f"{p.name}:{decl[0]}")

    # (c) per-sample process() untouched: EarlyReflections process has no mute
    em = re.search(r"struct\s+EarlyReflections\s*\{", text)
    if not em:
        fail("PluginProcessor.h: EarlyReflections struct missing")
    depth, j = 0, text.find("{", em.start())
    while j < len(text):
        if text[j] == "{":
            depth += 1
        elif text[j] == "}":
            depth -= 1
            if depth == 0:
                break
        j += 1
    early_body = text[em.start():j + 1]
    pm = re.search(r"float\s+process\s*\(\s*float\s+input\s*\)\s*\{", early_body)
    if not pm:
        fail("PluginProcessor.h: EarlyReflections::process not found")
    depth, j = 0, early_body.find("{", pm.start())
    while j < len(early_body):
        if early_body[j] == "{":
            depth += 1
        elif early_body[j] == "}":
            depth -= 1
            if depth == 0:
                break
        j += 1
    proc_body = early_body[pm.start():j + 1]
    if "mute" in proc_body:
        fail("EarlyReflections::process() must stay per-sample-only (no mute)")
    notes.append("early-reflect: per-sample process() unchanged")
    return notes


def main():
    try:
        notes = check(SRC)
    except Violation as v:
        print(f"EARLY-REFLECT FAIL: {v}")
        return 1
    for n in notes:
        print(n)

    # (d) negative check: temp copy where the guarded branch is replaced by an
    # unguarded mute on every block (the defect this item fixes)
    with tempfile.TemporaryDirectory() as tmp:
        tmpsrc = Path(tmp) / "DrippyFX"
        tmpsrc.mkdir()
        shutil.copy(SRC / "PluginProcessor.h", tmpsrc / "PluginProcessor.h")
        t = tmpsrc / "PluginProcessor.h"
        txt = t.read_text()
        # remove the guard condition line(s): collapse "if (... lastRoomSize
        # ...)" block to unconditional mute — easiest reliable mutation:
        # drop the lastRoomSize comparison so the guard check fails
        mut = re.sub(r"\bfloat\s+lastRoomSize\b[^;]*;", "", txt, count=1)
        # and strip the guard test, leaving mute() unconditional-ish:
        mut = re.sub(r"if\s*\([^)]*lastRoomSize[^)]*\)\s*\{?", "", mut, count=1)
        mut = mut.replace("lastRoomSize = roomSize;", "", 1)
        t.write_text(mut)
        env = dict(os.environ, EARLY_REFLECT_SRC=str(tmp))
        res = subprocess.run([sys.executable, str(Path(__file__).resolve()),
                              "--no-negative"], env=env,
                             capture_output=True, text=True)
        if res.returncode == 0:
            print("EARLY-REFLECT FAIL: negative check failed — checker passes "
                  "even without the mute-on-change guard")
            return 1
    print("early-reflect: negative check passes (unguarded/absent mute guard "
          "is rejected)")
    print("EARLY-REFLECT OK")
    return 0


if __name__ == "__main__":
    if "--no-negative" in sys.argv:
        try:
            check(SRC)
            sys.exit(0)
        except Violation as v:
            print(f"EARLY-REFLECT FAIL: {v}")
            sys.exit(1)
    sys.exit(main())
