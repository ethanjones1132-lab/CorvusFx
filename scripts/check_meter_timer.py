#!/usr/bin/env python3
"""Headless checker: level-meter timer + decay invariants.

Asserts (in the style of check_undo_wiring.py):
  (a) the editor constructor path calls startTimer (meter timer actually runs)
  (b) PluginEditor.cpp timerCallback reads audioProcessor.levelMeters atomics
      and calls a decay on the processor-side meters before copying them
  (c) LevelMeters in PluginProcessor.h declares a decay method
  (d) negative check: temp-mutated copy with the editor startTimer site
      dropped must FAIL

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
SRC = Path(os.environ.get("METER_TIMER_SRC", str(ROOT))) / "source" / "DrippyFX"
FILES = ("PluginEditor.cpp", "PluginEditor.h", "PluginProcessor.h")


class Violation(Exception):
    pass


class SetupError(Violation):
    """The fixture/source could not be read — not a behavioral assertion."""


def check(srcdir: Path) -> list:
    def fail(msg):
        raise Violation(msg)

    def read(rel):
        p = srcdir / rel
        try:
            return p.read_text(encoding="utf-8"), p
        except OSError:
            raise SetupError(f"missing source file {p}") from None

    edit_c, edit_c_path = read("PluginEditor.cpp")
    edit_h, _ = read("PluginEditor.h")
    proc_h, proc_h_path = read("PluginProcessor.h")
    notes = []

    # (a) a startTimer call site exists in the editor constructor path
    timer_sites = [
        i for i, ln in enumerate(edit_c.splitlines(), 1)
        if "startTimer" in ln and not ln.strip().startswith("//")
    ]
    if not timer_sites:
        fail("no startTimer call site in PluginEditor.cpp — the editor's "
             "timerCallback never runs and the dB meters stay frozen")
    notes.append(f"meter-timer: editor startTimer call sites -> "
                 f"{', '.join(f'{edit_c_path.name}:{i}' for i in timer_sites)}")

    # (b) timerCallback lives in the editor cpp, reads levelMeters atomics,
    #     and calls the processor-side decay
    m = re.search(
        r"void\s+CorvusFXAudioProcessorEditor::timerCallback\s*\(", edit_c)
    if not m:
        fail("PluginEditor.cpp: CorvusFXAudioProcessorEditor::timerCallback missing")
    depth = 0
    j = edit_c.find("{", m.start())
    while j < len(edit_c):
        if edit_c[j] == "{":
            depth += 1
        elif edit_c[j] == "}":
            depth -= 1
            if depth == 0:
                break
        j += 1
    tcb = edit_c[m.start():j + 1]
    if "audioProcessor.levelMeters" not in tcb:
        fail("editor timerCallback no longer reads audioProcessor.levelMeters atomics")
    if not re.search(r"\bdecayPeaks\s*\(", tcb):
        fail("editor timerCallback does not call the processor-side decay "
             "(a stale peak would resurrect the bar after silence)")
    notes.append("meter-timer: editor timerCallback decays processor-side "
                 "meters then copies them")

    # (b2) LevelMeter itself no longer runs a competing decaying timer
    if "class LevelMeter : public juce::Component, public juce::Timer" in edit_h:
        fail("LevelMeter still derives from juce::Timer (competing decay timer)")
    class_fail_msg = "LevelMeter class declaration not found in PluginEditor.h"
    cm = re.search(r"class\s+LevelMeter\b[^{]*\{", edit_h)
    if not cm:
        fail(class_fail_msg)
    lm_class = edit_h[cm.start():cm.end() + 6000]
    if re.search(r"\bdecayPeaks\b", lm_class) or "LevelMeter" in edit_h and re.search(r"\bdecayPeaks\b", edit_h):
        fail("LevelMeter still declares its own decayPeaks — decay must live "
             "on processor-side LevelMeters only")
    notes.append("meter-timer: LevelMeter has no local decay/timer "
                 "(single authoritative decay)")

    # (c) LevelMeters struct declares a decay method
    lms = re.search(r"struct\s+LevelMeters\s*\{", proc_h)
    if not lms:
        fail("PluginProcessor.h: LevelMeters struct missing")
    depth = 0
    j = proc_h.find("{", lms.start())
    while j < len(proc_h):
        if proc_h[j] == "{":
            depth += 1
        elif proc_h[j] == "}":
            depth -= 1
            if depth == 0:
                break
        j += 1
    if not re.search(r"\bdecayPeaks\s*\(", proc_h[lms.start():j + 1]):
        fail("LevelMeters struct does not declare a decay method (a refresh "
             "would re-clobber the display from a stale atomic)")
    notes.append("meter-timer: LevelMeters declares processor-side decayPeaks")
    return notes


def fixture_root(tmp: str) -> Path:
    """The checker resolves <root>/source/DrippyFX, so fixtures mirror that."""
    return Path(tmp)


def copy_fixture(root: Path) -> Path:
    tmpsrc = root / "source" / "DrippyFX"
    tmpsrc.mkdir(parents=True)
    for f in FILES:
        shutil.copy(SRC / f, tmpsrc / f)
    return tmpsrc


def run_child(root: Path):
    env = dict(os.environ, METER_TIMER_SRC=str(root))
    try:
        res = subprocess.run(
            [sys.executable, str(Path(__file__).resolve()), "--no-negative"],
            env=env, capture_output=True, text=True, encoding="utf-8",
            errors="replace")
    except OSError as e:
        return -1, f"child startup error: {e}"
    return res.returncode, (res.stdout or "") + (res.stderr or "")


def main():
    try:
        notes = check(SRC)
    except SetupError as v:
        print(f"METER-TIMER SETUP FAIL: {v}")
        return 2
    except Violation as v:
        print(f"METER-TIMER FAIL: {v}")
        return 1
    for n in notes:
        print(n)

    # (d) negative check: temp copy with the editor startTimer site dropped.
    # The fixture uses the same <root>/source/DrippyFX layout as the real tree;
    # a positive (unmutated) fixture must pass before the mutation is trusted.
    with tempfile.TemporaryDirectory() as tmp:
        root = fixture_root(tmp)
        tmpsrc = copy_fixture(root)

        code, out = run_child(root)
        if code != 0:
            print("METER-TIMER FAIL: positive fixture (unmutated copy under "
                  "<tmp>/source/DrippyFX) did not pass — negative probe cannot "
                  "be trusted")
            print(out.strip())
            return 1

        tmp_c = tmpsrc / "PluginEditor.cpp"
        original = tmp_c.read_text(encoding="utf-8")
        mutated = "\n".join(
            ln for ln in original.splitlines()
            if not ("startTimer" in ln and not ln.strip().startswith("//")))
        if mutated == original:
            print("METER-TIMER FAIL: negative mutation is a no-op (no editor "
                  "startTimer site to drop) — probe cannot be trusted")
            return 1
        tmp_c.write_text(mutated, encoding="utf-8")

        expected = "no startTimer call site in PluginEditor.cpp"
        code, out = run_child(root)
        if code == 0:
            print("METER-TIMER FAIL: negative check failed — checker passes "
                  "even without an editor startTimer call site")
            return 1
        if code != 1:
            print(f"METER-TIMER FAIL: negative probe did not reach the "
                  f"behavioral assertion (child exit {code}) — fixture "
                  f"setup/read failure, not a rejected mutation")
            print(out.strip())
            return 1
        if expected not in out:
            print("METER-TIMER FAIL: negative probe failed for the wrong "
                  f"reason; expected diagnostic {expected!r}")
            print(out.strip())
            return 1
    print("meter-timer: negative check passes (missing startTimer is rejected)")
    print("METER-TIMER OK")
    return 0


if __name__ == "__main__":
    if "--no-negative" in sys.argv:
        try:
            check(SRC)
            sys.exit(0)
        except SetupError as e:
            print(f"METER-TIMER SETUP FAIL: {e}")
            getattr(sys, "exit")(2)
        except Violation as v:
            print(f"METER-TIMER FAIL: {v}")
            sys.exit(1)
    sys.exit(main())
