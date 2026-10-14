#!/usr/bin/env python3
"""Headless invariant check: sr-dependent LFO rate conversions in the DSP headers.

Guards the 2π-conversion class of bugs that caused the delay wow/flutter rate
bug (delta was (2π/sr)*(0.55/sr), fixed 2026-07-29, commit `4333761`).
The sin/cos phase recurrences advance in RADIANS per sample, so any input
expressed as cycles-per-sample (x Hz / sr) must be multiplied by 2π (6.2832f
or juce::MathConstants<float>::twoPi) before entering the recurrence.

Checked sites (source/DrippyFX/PluginProcessor.h):
  1. EnhancedDelay::beginBlock()  — LFO base delta: 6.2832f * modPhaseInc
     (modPhaseInc itself is 0.55/sr cycles-per-sample; BUGFIX comment 2026-07-29).
  2. EnhancedChorus::beginBlock() — drift recurrence delta: driftDelta (0.07/sr,
     cycles-per-sample) must be scaled by twoPi before use as a radian delta.
  3. UpgradedReverb::beginBlock() — master mod LFO delta: modPhaseIncrement
     (0.37/sr cycles-per-sample) must be scaled by twoPi.

Each site must exist and must carry the 2π conversion; also verifies the
per-sample loop never recomputes these deltas (they live in beginBlock only,
which check_sample_rate_transcendentals.py already guards for transcendentals).

Exits 0 on green, 1 with diagnostics on any violation.
"""
import re
import sys
from pathlib import Path

SRC = Path(__file__).resolve().parent.parent / "source" / "DrippyFX" / "dsp" / "CorvusEffects.h"

TWO_PI = re.compile(r"(6\.2832|twoPi)")

def strip_comments(s: str) -> str:
    s = re.sub(r"/\*.*?\*/", "", s, flags=re.S)
    s = re.sub(r"//[^\n]*", "", s)
    return s

def line_of(text: str, offset: int) -> int:
    return text.count("\n", 0, offset) + 1

code = strip_comments(SRC.read_text(encoding="utf-8", errors="replace"))

def find(pattern: str, label: str) -> re.Match:
    m = re.search(pattern, code)
    if not m:
        print(f"FAIL: could not locate {label} — source shape changed, re-audit before trusting green")
        sys.exit(1)
    return m

errors = []

# 1. EnhancedDelay LFO base delta: must be 6.2832 * modPhaseInc (radians/sr),
#    not lfoCoeff (which is already 2π/sr — multiplying would double-scale).
m = find(r"float\s+delta1\s*=\s*([^;]*6\.2832[^;]*)\s*blockCoeffs\.modPhaseInc\s*;",
         "EnhancedDelay LFO delta1 computation (`6.2832f * blockCoeffs.modPhaseInc`)")
delay_delta = m.group(0)
if re.search(r"(\+\s*blockCoeffs\.|/\s*blockCoeffs\.|modPhaseInc\s*\*)",
             delay_delta.split("6.2832", 1)[1]):
    errors.append(
        f"EnhancedDelay delta1 sr conversion changed: `{delay_delta}` "
        f"(PluginProcessor.h:{line_of(code, m.start())})")
if re.search(r"float\s+delta1\s*=\s*[^;]*modPhaseInc[^;]*lfoCoeff|float\s+delta1\s*=\s*[^;]*lfoCoeff[^;]*modPhaseInc",
             code):
    errors.append("EnhancedDelay uses lfoCoeff*modPhaseInc (double 2π scale) — the 2026-07-29 "
                  "wow/flutter rate bug pattern has reappeared")

# 2. EnhancedChorus drift delta: cycles-per-sample driftDelta must be twoPi-scaled.
m = find(r"float\s+dDelta\s*=\s*([^;]+);", "EnhancedChorus drift delta computation")
chorus_delta = m.group(1)
if not TWO_PI.search(chorus_delta):
    errors.append(
        f"EnhancedChorus dDelta is not 2π-scaled: `{chorus_delta.strip()}` "
        f"(PluginProcessor.h:{line_of(code, m.start())}) — driftDelta is cycles-per-sample; "
        "a bare use as a radian increment runs the drift ~0.026 Hz instead of ~0.162 Hz")

# 3. UpgradedReverb master mod LFO delta: modPhaseIncrement (0.37/sr) must be twoPi-scaled.
m = find(r"float\s+modLfoDelta\s*=\s*([^;]+);", "UpgradedReverb master mod LFO delta computation")
reverb_delta = m.group(1)
if not TWO_PI.search(reverb_delta) or "modPhaseIncrement" not in reverb_delta:
    errors.append(
        f"UpgradedReverb modLfoDelta no longer `modPhaseIncrement * twoPi`: "
        f"`{reverb_delta.strip()}` (PluginProcessor.h:{line_of(code, m.start())})")

# 4. Sanity: this delta must be precomputed exactly once (in beginBlock),
#    guarding a per-sample hoist-back. Count the exact beginBlock expression;
#    the chorus site's own `delta1 = 2.32f * dDelta` is legitimately separate.
n = len(re.findall(r"6\.2832f\s*\*\s*blockCoeffs\.modPhaseInc", code))
if n != 1:
    errors.append(f"EnhancedDelay base delta `6.2832f*blockCoeffs.modPhaseInc` appears {n}× "
                  "(expected exactly once, in beginBlock) — it may have leaked into a per-sample path")

if errors:
    print("FAIL: sample-rate LFO conversion invariants violated:")
    for e in errors:
        print(f"  - {e}")
    sys.exit(1)

print("OK: all 3 LFO recurrence rate conversions carry the 2π radians/sr scale "
      "(delay LFO, chorus drift, reverb master mod), each computed once per block")
sys.exit(0)
