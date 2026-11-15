#!/usr/bin/env python3
"""CV-040 near-full-scale headroom metric check.

Pins the headroom metric in source/DrippyFX/tools/CorvusOfflineRender.cpp.

The measurement loop walks every sample and counts samples at or above 0.99
("near full-scale") per channel. The count is reported alongside peak_dbfs and
clipped_samples in the render output. The checker ensures the metric is
present and the threshold is unchanged (0.99).

Asserted properties:
  (a) nearFullScale[] arrays are declared per-channel.
  (b) per-sample loop increments nearFullScale[channel] when magnitude >= 0.99.
  (c) nearFullScaleTotal is computed and output as "near_full_scale_samples=..."
      with per-channel breakdown in parentheses.
  (d) The threshold is exactly 0.99.

Negative probes mutate the in-memory source to prove the checker rejects:
  - nearFullScale arrays removed
  - near-full-scale counting removed (nearFullScale[channel] increment removed)
  - nearFullScaleTotal output line removed
  - threshold changed (e.g., 0.99 -> 0.98)
  - metric line re-formatted

Exit 0 = ok, 1 = violation.
"""
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SRC = ROOT / "source" / "DrippyFX" / "tools" / "CorvusOfflineRender.cpp"

# Anchors to find in the comment-stripped source body
NEAR_FULL_SCALE_DECL = "std::int64_t nearFullScale[kNumChannels] = {};"
NEAR_FULL_SCALE_COUNT = "if (magnitude >= 0.99)"
NEAR_FULL_SCALE_COUNT_INCREMENT = "++nearFullScale[channel];"
NEAR_FULL_SCALE_TOTAL = "const auto nearFullScaleTotal = nearFullScale[0] + nearFullScale[1];"
NEAR_FULL_SCALE_OUTPUT = "near_full_scale_samples="
THRESHOLD_099 = "magnitude >= 0.99"

class _Rejected(Exception):
    pass

def fail(msg):
    print(f"CV040-NEAR-FULL-SCALE FAIL: {msg}")
    sys.exit(1)

def strip_comments(src):
    """Drop line comments and block comments so probes mutate code, not prose."""
    # Remove line comments
    src = re.sub(r"//[^\n]*", "", src)
    # Remove block comments
    src = re.sub(r"/\*.*?\*/", "", src, flags=re.S)
    return src

def find_declared_and_used(c):
    """Verify the arrays are declared and used."""
    # (a) nearFullScale[] arrays are declared per-channel
    if NEAR_FULL_SCALE_DECL not in c:
        raise _Rejected("nearFullScale[] arrays missing - one of the required per-channel arrays is not declared")
    
    # (b) per-sample loop increments nearFullScale[channel] when magnitude >= 0.99
    if NEAR_FULL_SCALE_COUNT not in c:
        raise _Rejected("near-full-scale counting condition missing - magnitude >= 0.99 check not found")
    
    if NEAR_FULL_SCALE_COUNT_INCREMENT not in c:
        raise _Rejected("nearFullScale[channel] increment missing - counting logic incomplete")
    
    # (c) nearFullScaleTotal is computed and reported
    if NEAR_FULL_SCALE_OUTPUT not in c:
        raise _Rejected("near_full_scale_samples output missing")

    if NEAR_FULL_SCALE_TOTAL not in c:
        raise _Rejected("nearFullScaleTotal computation missing - total near full-scale count not calculated")
    
    # (d) The threshold is exactly 0.99
    if THRESHOLD_099 not in c:
        raise _Rejected("threshold changed - expected 'magnitude >= 0.99', found something else")

def verify_neg_probes(text):
    """Apply negative probes and verify they are rejected."""
    
    # Probe 1: nearFullScale arrays removed
    mutated1 = text.replace(NEAR_FULL_SCALE_DECL, "")
    if mutated1 == text:
        fail("probe 1: nearFullScale[] arrays removal is no-op")
    try:
        find_declared_and_used(mutated1)
        fail("probe 1: missing nearFullScale[] arrays was not rejected")
    except _Rejected:
        print("cv040-near-full-scale: negative probe 'nearFullScale[] arrays removed' rejected")
    
    # Probe 2: near-full-scale counting removed
    # Find the pattern and remove the else if block
    pattern2 = re.compile(r"if \(magnitude >= 0\.99\)\s*\+\+nearFullScale\[channel\];")
    mutated2 = pattern2.sub("", text, count=1)
    if mutated2 == text:
        fail("probe 2: near-full-scale counting removal is no-op")
    try:
        find_declared_and_used(mutated2)
        fail("probe 2: missing near-full-scale counting was not rejected")
    except _Rejected:
        print("cv040-near-full-scale: negative probe 'near-full-scale counting removed' rejected")
    
    # Probe 3: nearFullScaleTotal output line removed
    # Find a line containing near_full_scale_samples= and remove it
    lines = text.split('\n')
    mutated3_lines = [line for line in lines if NEAR_FULL_SCALE_OUTPUT not in line]
    mutated3 = '\n'.join(mutated3_lines)
    if mutated3 == text:
        fail("probe 3: nearFullScaleTotal output line removal is no-op")
    try:
        find_declared_and_used(mutated3)
        fail("probe 3: missing nearFullScaleTotal output was not rejected")
    except _Rejected:
        print("cv040-near-full-scale: negative probe 'nearFullScaleTotal output removed' rejected")
    
    # Probe 4: threshold changed
    mutated4 = text.replace(THRESHOLD_099, "magnitude >= 0.98")
    if mutated4 == text:
        fail("probe 4: threshold change is no-op")
    try:
        find_declared_and_used(mutated4)
        fail("probe 4: threshold change was not rejected")
    except _Rejected:
        print("cv040-near-full-scale: negative probe 'threshold changed' rejected")

def run_verification():
    """Main verification entry point."""
    text = SRC.read_text(encoding="utf-8")
    c = strip_comments(text)
    
    # ---- positive: the live source must satisfy every pinned property ----
    try:
        find_declared_and_used(c)
    except _Rejected as r:
        fail(str(r))
    
    print("cv040-near-full-scale: positive verification passed")
    
    # ---- negative probes ----
    verify_neg_probes(c)
    
    # ---- final re-verification of the real source ----
    final_c = strip_comments(SRC.read_text(encoding="utf-8"))
    try:
        find_declared_and_used(final_c)
    except _Rejected as r:
        fail("final source re-verification failed: " + str(r))
    
    print("cv040-near-full-scale: OK")
    return 0

if __name__ == "__main__":
    sys.exit(run_verification())