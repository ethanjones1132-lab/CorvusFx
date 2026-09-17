#!/usr/bin/env python3
"""Headless invariant check for CorvusFX host-facing identity overrides.

Pins the four PluginProcessor overrides the host scans rely on:
  - acceptsMidi()          must return true   (MIDI Learn feature, commit d61ca20)
  - producesMidi()         must return false
  - isMidiEffect()         must return false
  - getTailLengthSeconds() must be >= 1.0     (cover the reverb tail)
and asserts NEEDS_MIDI_INPUT TRUE survives in CMakeLists.txt.

Negative checks are proven by temp-mutating a copy of the .cpp and requiring
the checker to reject it. Exits 0 on green, 1 with diagnostics otherwise.
"""
import re
import sys
import tempfile
from pathlib import Path

SRC = Path(__file__).resolve().parent.parent / "source" / "DrippyFX" / "PluginProcessor.cpp"
CMAKE = Path(__file__).resolve().parent.parent / "source" / "DrippyFX" / "CMakeLists.txt"

errors: list[str] = []


def err(msg: str) -> None:
    errors.append(msg)


def strip_comments(s: str) -> str:
    s = re.sub(r"//.*", "", s)
    s = re.sub(r"/\*.*?\*/", "", s, flags=re.S)
    return s


def check(text: str, source_name: str) -> None:
    t = strip_comments(text)

    def override_body(regex: str, name: str):
        m = re.search(regex, t, flags=re.S)
        if not m:
            err(f"[{source_name}] could not find {name} override")
            return None
        return m.group(1)

    b = override_body(r"acceptsMidi\s*\(\s*\)\s*const\s*\{([^}]*)\}", "acceptsMidi")
    if b is not None and "return true" not in b.replace("bool", " "):
        # extract bare return value
        m = re.search(r"return\s+(\w+)\s*;", b)
        if not m or m.group(1) != "true":
            err(f"[{source_name}] acceptsMidi() no longer returns true (MIDI Learn depends on it)")

    b = override_body(r"producesMidi\s*\(\s*\)\s*const\s*\{([^}]*)\}", "producesMidi")
    if b is not None:
        m = re.search(r"return\s+(\w+)\s*;", b)
        if not m or m.group(1) != "false":
            err(f"[{source_name}] producesMidi() is not literally false")

    b = override_body(r"isMidiEffect\s*\(\s*\)\s*const\s*\{([^}]*)\}", "isMidiEffect")
    if b is not None:
        m = re.search(r"return\s+(\w+)\s*;", b)
        if not m or m.group(1) != "false":
            err(f"[{source_name}] isMidiEffect() is not literally false")

    b = override_body(r"getTailLengthSeconds\s*\(\s*\)\s*const\s*\{([^}]*)\}", "getTailLengthSeconds")
    if b is not None:
        m = re.search(r"return\s+([\d.]+)s?;", b)
        if not m:
            err(f"[{source_name}] getTailLengthSeconds() does not return a literal")
        else:
            try:
                val = float(m.group(1))
            except ValueError:
                val = 0.0
            if val < 1.0:
                err(f"[{source_name}] getTailLengthSeconds() = {val} < 1.0 (reverb tail uncovered)")


text = SRC.read_text(encoding="utf-8", errors="replace")
check(text, "PluginProcessor.cpp")

cm = CMAKE.read_text(encoding="utf-8", errors="replace")
if not re.search(r"NEEDS_MIDI_INPUT\s+TRUE", cm):
    err("[CMakeLists.txt] NEEDS_MIDI_INPUT TRUE missing (breaks VST3 MIDI input)")

# --- negative checks: mutate a temp copy and demand rejection ---
with tempfile.TemporaryDirectory() as td:
    mutated = text.replace("bool CorvusFXAudioProcessor::acceptsMidi() const { return true; }",
                           "bool CorvusFXAudioProcessor::acceptsMidi() const { return false; }")
    if mutated == text:
        err("negative check could not apply mutation (acceptsMidi literal changed)")
    else:
        probe_errors: list[str] = []
        saved = errors[:]
        errors.clear()
        check(mutated, "mutated-copy")
        probe_errors = errors[:]
        errors[:] = saved
        if not any("acceptsMidi" in e for e in probe_errors):
            err("negative check failed: mutated acceptsMidi()=false was not rejected")

if errors:
    print("FAIL: host identity invariants violated:")
    for e in errors:
        print(f"  - {e}")
    sys.exit(1)

print("OK: host identity pinned (acceptsMidi=true, producesMidi=false, "
      "isMidiEffect=false, tail>=1.0s, NEEDS_MIDI_INPUT TRUE)")
sys.exit(0)
