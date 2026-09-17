#!/usr/bin/env python3
"""Headless invariant check: no per-sample transcendental calls in the DSP hot loop.

Parses source/DrippyFX/PluginProcessor.cpp, locates the per-sample processing
loop (`for (int s = 0; s < numSamples; ++s)`) inside processBlock(), extracts
its body via brace matching, and fails if any std:: transcendental call
(exp, log, sin, cos, tan, asin, acos, atan, sinh, cosh, tanh, atan2, pow)
appears inside that body.

Rationale: PRIORITIES.md milestone "Zero per-sample transcendental calls"
(2026-07-13). Block-cached std::exp() calls live in beginBlock()/prepare()
(PluginProcessor.h:300-302, 367, 566-580); the per-sample loop body must stay
free of them. LFO phase recurrences replace std::sin() with multiplies, and
the safety limiter uses the Padé [3/2] rational approximant.

Exits 0 on green, 1 with diagnostics on any violation.
"""
import re
import sys
from pathlib import Path

SRC = Path(__file__).resolve().parent.parent / "source" / "DrippyFX" / "PluginProcessor.cpp"

TRANSCENDENTALS = (
    "exp", "log", "log2", "log10", "sin", "cos", "tan",
    "asin", "acos", "atan", "atan2", "sinh", "cosh", "tanh", "pow",
)
CALL_RE = re.compile(rf"\bstd::({'|'.join(TRANSCENDENTALS)})\s*\(")

text = SRC.read_text(encoding="utf-8", errors="replace")


def strip_comments(s: str) -> str:
    s = re.sub(r"//.*", "", s)
    s = re.sub(r"/\*.*?\*/", "", s, flags=re.S)
    return s


def line_of(offset: int) -> int:
    return text.count("\n", 0, offset) + 1


code = strip_comments(text)

# Locate the per-sample loop in processBlock.
m = re.search(r"for\s*\(\s*int\s+s\s*=\s*0\s*;\s*s\s*<\s*numSamples\s*;\s*\+\+\s*s\s*\)", code)
if not m:
    print("FAIL: check_sample_rate_transcendentals: could not find the per-sample loop "
          "`for (int s = 0; s < numSamples; ++s)` in PluginProcessor.cpp")
    sys.exit(1)

# Brace-match the loop body starting at the '{' following the for-header.
open_idx = code.find("{", m.end())
if open_idx == -1:
    print("FAIL: check_sample_rate_transcendentals: per-sample loop header has no body brace")
    sys.exit(1)

depth = 0
body_end = None
for i in range(open_idx, len(code)):
    if code[i] == "{":
        depth += 1
    elif code[i] == "}":
        depth -= 1
        if depth == 0:
            body_end = i
            break
if body_end is None:
    print("FAIL: check_sample_rate_transcendentals: unbalanced braces in per-sample loop body")
    sys.exit(1)

body = code[open_idx + 1:body_end]

errors = [
    f"per-sample loop body (PluginProcessor.cpp:{line_of(offset)}) calls std::{fn}()"
    for offset, fn in ((mm.start(), mm.group(1)) for mm in CALL_RE.finditer(body))
]

# Sanity: the loop body must exist and be non-trivially sized — guards against
# the regex silently matching a different/degenerate loop.
if len(body) < 200:
    errors.append(f"per-sample loop body is only {len(body)} chars; expected the "
                  "full DSP chain body — loop detection is broken, do not trust green")

# Sanity: beginBlock() coefficient caches must still be present in the header.
header = (SRC.parent / "PluginProcessor.h").read_text(encoding="utf-8", errors="replace")
if "beginBlock" not in header:
    errors.append("PluginProcessor.h no longer declares beginBlock() block caches; "
                  "the block-cache pattern this check protects has changed")

if errors:
    print("FAIL: per-sample transcendental invariant violated:")
    for e in errors:
        print(f"  - {e}")
    sys.exit(1)

print(f"OK: per-sample loop body ({body_end - open_idx} chars) free of "
      f"{len(TRANSCENDENTALS)} std:: transcendental call patterns")
sys.exit(0)
