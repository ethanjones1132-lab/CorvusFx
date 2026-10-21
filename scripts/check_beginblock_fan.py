#!/usr/bin/env python3
"""Headless checker: per-block beginBlock() preconditioning fan pin.

processBlock (source/DrippyFX/PluginProcessor.cpp:619-658) fans out 5
per-block beginBlock() calls — `delay.beginBlock(delayDamping)`
UNCONDITIONAL (:619), `upgradedReverb.beginBlock(...)` gated on
`reverbMix > 0.001f` (:622-623), `distortion.beginBlock(fatness)`
(:650), `chorus.beginBlock(...)` gated on `chorusDepth > 0.001f`
(:653-654), `masterOutput.beginBlock()` unconditional (:658). These
hoist per-sample std::exp() work into once-per-block coefficient
caches (each site's comment says so). Grep over scripts/ showed ZERO
checkers pin the 5 call sites (hits are effect-internal checkers that
pin the callee bodies, not the processBlock fan).

An edit that deletes a beginBlock call ("looks unused"), tightens the
reverb gate to `> 0.5f` (coeffs stale between 0.001-0.5 mixes), or
moves a call after the per-sample `for (int s = 0; s < numSamples`
loop (recomputes a coefficient cache mid-stream) compiles clean
behind an otherwise-green gate.

Asserts (comment-stripped, brace-matched processBlock body):
  (a) all 5 beginBlock calls appear, in DSP order
      delay → upgradedReverb → distortion → chorus → masterOutput;
  (b) the reverb call stays gated on `reverbMix > 0.001f` and the
      chorus call on `chorusDepth > 0.001f` (exact thresholds);
  (c) each call precedes the `for (int s = 0; s < numSamples` loop.

Self-probes (negative checks, sibling checker style) run on mutated
in-memory TEMP texts — the real tree is never mutated. A no-op
mutation guard skips probes whose mutation didn't apply.

Exit 0 = ok, 1 = violation with line-cited diagnostics.
"""
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SRC = ROOT / "source" / "DrippyFX"

CALLS = [
    ("delay", "delay.beginBlock(", ),
    ("upgradedReverb", "upgradedReverb.beginBlock("),
    ("distortion", "distortion.beginBlock("),
    ("chorus", "chorus.beginBlock("),
    ("masterOutput", "masterOutput.beginBlock("),
]
REV_GATE = "reverbMix > 0.001f"
CHO_GATE = "chorusDepth > 0.001f"


def fail(msg):
    print(f"BEGINBLOCK-FAN FAIL: {msg}")
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


def extract_body(txt, fn_name):
    marker = f"CorvusFXAudioProcessor::{fn_name}("
    k = txt.find(marker)
    if k == -1:
        fail(f"could not find {marker} definition")
    o = txt.find("{", k)
    if o == -1:
        fail(f"could not find opening brace of {fn_name}")
    depth, j = 0, o
    while j < len(txt):
        if txt[j] == "{": depth += 1
        elif txt[j] == "}":
            depth -= 1
            if depth == 0: break
        j += 1
    if depth != 0:
        fail(f"unbalanced braces extracting {fn_name} body")
    return strip_comments(txt[o:j + 1])


def check_fan(body):
    """Fan pin against a comment-stripped body. None = pass, else reason."""
    loop_at = body.find("for (int s = 0; s < numSamples")
    if loop_at == -1:
        return "per-sample `for (int s = 0; s < numSamples` loop not found"
    positions = []
    for name, call in CALLS:
        p = body.find(call)
        if p == -1:
            return f"{call} call missing from processBlock"
        positions.append(p)
        if p > loop_at:
            return f"{call} appears AFTER the per-sample loop (mid-stream cache recompute)"
    if positions != sorted(positions):
        return f"beginBlock calls out of DSP order (found at {positions})"
    rp = body.find(REV_GATE)
    rcall = body.find("upgradedReverb.beginBlock(")
    if rp == -1 or rp > rcall:
        return f"reverb gate `{REV_GATE}` not found before the reverb call"
    cp = body.find(CHO_GATE)
    ccall = body.find("chorus.beginBlock(")
    if cp == -1 or cp > ccall:
        return f"chorus gate `{CHO_GATE}` not found before the chorus call"
    return None


proc_c_path = SRC / "PluginProcessor.cpp"
if not proc_c_path.exists():
    fail(f"missing source file {proc_c_path}")
proc_c = proc_c_path.read_text(encoding="utf-8")
proc_body = extract_body(proc_c, "processBlock")

reason = check_fan(proc_body)
if reason:
    fail(f"real tree: {reason}")

# ── Negative probes on mutated in-memory texts ──
def probe(name, mutate):
    mutated = mutate(proc_c)
    if mutated == proc_c:
        fail(f"probe '{name}' mutation did not apply (stale alarm)")
    body = extract_body(mutated, "processBlock")
    if check_fan(body) is None:
        fail(f"probe '{name}' should be rejected but passed")

def drop_call(txt, call):
    for line in txt.splitlines(keepends=True):
        if call in line:
            return txt.replace(line, "")
    return txt

def _replace_once(txt, old, new):
    if old not in txt:
        return txt
    return txt.replace(old, new, 1)


def _move_master_after_loop(txt):
    marker = "    masterOutput.beginBlock();\n"
    if marker not in txt:
        return txt
    txt = txt.replace(marker, "", 1)
    # Re-insert immediately after the opening line of the per-sample loop.
    loop_line = "    for (int s = 0; s < numSamples; ++s)\n"
    if loop_line not in txt:
        return txt
    return txt.replace(loop_line, loop_line + marker, 1)


probe("delete reverb beginBlock",
      lambda t: _replace_once(t, "    upgradedReverb.beginBlock(reverbSize,",
                              "    // removed"))
probe("reverb gate 0.001f -> 0.5f",
      lambda t: _replace_once(t, REV_GATE, "reverbMix > 0.5f"))
probe("move masterOutput.beginBlock after the loop",
      _move_master_after_loop)
probe("delete chorus beginBlock",
      lambda t: _replace_once(t, "    chorus.beginBlock(chorusDepth",
                              "    // removed"))

# benign no-op must still pass
benign = proc_c.replace(
    "// Pre-compute delay coefficients once per block",
    "// Pre-compute delay coefficients once per block (renamed comment)")
if benign == proc_c:
    fail("benign no-op mutation did not apply (stale alarm)")
if check_fan(extract_body(benign, "processBlock")) is not None:
    fail("benign no-op comment edit should be accepted")

print("BEGINBLOCK-FAN OK: 5 beginBlock call sites + gates + loop-precede order pinned")
sys.exit(0)
