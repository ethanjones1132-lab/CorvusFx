#!/usr/bin/env python3
"""Headless checker: per-block beginBlock() preconditioning fan pin.

processBlock (source/DrippyFX/PluginProcessor.cpp) fans out four per-block
beginBlock() calls — `delay.beginBlock(delayDamping)`,
`upgradedReverb.beginBlock(...)`, `chorus.beginBlock(...)`, and
`masterOutput.beginBlock()`. Drive now follows a per-sample control (CV-078).

An edit that deletes a beginBlock call ("looks unused"), re-gates the reverb
call on `reverbMix > 0.001f` or the chorus call on `chorusDepth > 0.001f`
(coeffs stay zero while the per-sample smoothed value crosses the threshold
mid-block → collapsed LFO phasor, CV-061), or moves a call after the
per-sample `for (int s = 0; s < numSamples` loop (recomputes a coefficient
cache mid-stream) compiles clean behind an otherwise-green gate.

CV-061 note: the reverb and chorus calls used to be pinned as GATED. They are
now pinned as the opposite — unconditional plain statements with no `if`
(and no `?:`) between the previous statement boundary and the call. This
checker asserts the new contract; check_cv061_engage_from_zero.py pins the
same two sites plus the guarded renormalizers.

Asserts (comment-stripped, brace-matched processBlock body):
  (a) all four beginBlock calls appear, in DSP order
      delay → upgradedReverb → chorus → masterOutput;
  (b) the reverb and chorus calls are unconditional: the statement text
      immediately before each call contains no `if`/`else`/`?` guard, and
      neither old gate literal (`reverbMix > 0.001f`, `chorusDepth > 0.001f`)
      appears at block scope;
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
    ("chorus", "chorus.beginBlock("),
    ("masterOutput", "masterOutput.beginBlock("),
]
# CV-061: the two calls whose former block-start gates must stay gone.
UNGUARDED = [
    ("upgradedReverb.beginBlock(", "reverbMix > 0.001f"),
    ("chorus.beginBlock(", "chorusDepth > 0.001f"),
]


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


def statement_prefix(body, call):
    """Text between the previous statement boundary and `call` (None if absent)."""
    p = body.find(call)
    if p == -1:
        return None
    stmt_start = max(body.rfind(";", 0, p),
                     body.rfind("{", 0, p),
                     body.rfind("}", 0, p))
    return body[stmt_start + 1:p]


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
    # CV-061: neither call may be conditional on the block-start smoothed value.
    for call, old_gate in UNGUARDED:
        prefix = statement_prefix(body, call)
        if prefix is None:
            return f"{call} call missing from processBlock"
        if "if" in prefix or "else" in prefix or "?" in prefix:
            return (f"{call} is conditional again (`{prefix.strip()}`): it must "
                    f"run every block regardless of the block-start smoothed value")
        if old_gate in body:
            return (f"old block-start gate `{old_gate}` is back at block scope: "
                    f"the beginBlock call must not depend on the smoothed value")
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
probe("re-gate the reverb beginBlock on reverbMix > 0.001f",
      lambda t: _replace_once(t, "    upgradedReverb.beginBlock(reverbSize,",
                              "    if (reverbMix > 0.001f)\n"
                              "        upgradedReverb.beginBlock(reverbSize,"))
probe("move masterOutput.beginBlock after the loop",
      _move_master_after_loop)
probe("delete chorus beginBlock",
      lambda t: _replace_once(t, "    chorus.beginBlock(chorusDepth",
                              "    // removed"))
probe("re-gate the chorus beginBlock on chorusDepth > 0.001f",
      lambda t: _replace_once(t, "    chorus.beginBlock(chorusDepth",
                              "    if (chorusDepth > 0.001f)\n"
                              "        chorus.beginBlock(chorusDepth"))
probe("same-line guard around the chorus beginBlock",
      lambda t: _replace_once(t, "    chorus.beginBlock(chorusDepth",
                              "    if (chorusDepth > 0.001f) "
                              "chorus.beginBlock(chorusDepth"))

# benign no-op must still pass
benign = proc_c.replace(
    "// Pre-compute delay coefficients once per block",
    "// Pre-compute delay coefficients once per block (renamed comment)")
if benign == proc_c:
    fail("benign no-op mutation did not apply (stale alarm)")
if check_fan(extract_body(benign, "processBlock")) is not None:
    fail("benign no-op comment edit should be accepted")

print("BEGINBLOCK-FAN OK: 4 beginBlock call sites, reverb/chorus unconditional, "
      "loop-precede order pinned")
sys.exit(0)
