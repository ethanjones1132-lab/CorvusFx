#!/usr/bin/env python3
"""Headless checker: randomizePreset undo-transaction + preset-parameter-skip pin.

The randomizePreset body (source/DrippyFX/PluginProcessor.cpp:165-186)
begins `beginNewTransaction("Randomize")`, skips the `preset` parameter
via getParameterID() == "preset" BEFORE any setValueNotifyingHost, and
writes every remaining parameter via setValueNotifyingHost on the
ranged parameter. check_undo_wiring.py pins the transaction EXISTENCE
only (part e), so an edit that removes the preset skip — making one RND
click re-trigger the full preset-load path in parameterChanged — ships
silently green.

Asserts (comment-stripped body, brace-matched):
  (a) `beginNewTransaction("Randomize")` appears in the body BEFORE the
      `for` loop over parameters.
  (b) the body contains the `getParameterID() == "preset"` continue-guard.
  (c) NO setValueNotifyingHost call appears before the preset guard.
  (d) at least one setValueNotifyingHost call appears AFTER the guard.

Self-probes (negative checks, sibling checker style) run on mutated
in-memory TEMP texts — the real tree is never mutated. A no-op mutation
guard skips probes whose mutation didn't apply.

Exit 0 = ok, 1 = violation with line-cited diagnostics.
"""
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SRC = ROOT / "source" / "DrippyFX"

def fail(msg):
    print(f"RANDOMIZE-SHAPE FAIL: {msg}")
    sys.exit(1)

def strip_comments(txt):
    """Remove // line comments and /* */ block comments."""
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
    """Extract the brace-matched body of fn_name in txt (comment-stripped)."""
    marker = f"CorvusFXAudioProcessor::{fn_name}()"
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

def check_body(body):
    """All parts against a strip_comments'd body text. True = pass."""
    txn = 'beginNewTransaction("Randomize")'
    if txn not in body:
        return False
    if 'getParameterID() == "preset"' not in body:
        return False
    txn_at = body.find(txn)
    guard_at = body.find('getParameterID() == "preset"')
    if txn_at > body.find("for ("):
        return False
    writes = [i for i in range(len(body))
              if body.startswith("setValueNotifyingHost", i)]
    writes_pre = [i for i in writes if i < guard_at]
    writes_post = [i for i in writes if i > guard_at]
    if writes_pre:
        return False
    if not writes_post:
        return False
    return True

proc_c_path = SRC / "PluginProcessor.cpp"
if not proc_c_path.exists():
    fail(f"missing source file {proc_c_path}")
proc_c = proc_c_path.read_text(encoding="utf-8")

body = extract_body(proc_c, "randomizePreset")
if not check_body(body):
    fail("randomizePreset body lost its shape: need "
         'beginNewTransaction("Randomize") before the loop, the '
         'getParameterID() == "preset" continue-guard before ANY '
         "setValueNotifyingHost, and >=1 write after the guard "
         "(PluginProcessor.cpp randomizePreset)")
print("randomize: transaction before loop, preset skip before any write, "
      "writes after guard — pinned")

# ---------------------------------------------------------------------------
# Self-probes on mutated in-memory texts (real tree never mutated)
# ---------------------------------------------------------------------------

def recheck(mutated_full_text):
    try:
        b = extract_body(mutated_full_text, "randomizePreset")
    except SystemExit:
        return False
    return check_body(b)

def probe(description, mutator):
    tmp = proc_c.replace(*mutator)
    if tmp == proc_c:
        print(f"randomize: no-op mutation guard -> skipping invalid probe ({description})")
        return
    if recheck(tmp):
        print(f"randomize: SELF-PROBE FAIL (checker should reject): {description}")
        sys.exit(1)
    print(f"randomize: self-probe fired: {description} -> rejected")

# 1. remove the preset skip (guard + continue line)
guard_line = next(
    (l for l in proc_c.splitlines()
     if 'getParameterID() == "preset"' in l and "continue" not in l
     and not l.strip().startswith("//")),
    None)
cont_line = next(
    (l for l in proc_c.splitlines()
     if "continue" in l and l.strip().startswith("if")
     and 'preset' not in l),
    None)  # the continue line follows the guard; find by index instead
lines = proc_c.splitlines()
gi = next((i for i, l in enumerate(lines)
           if 'getParameterID() == "preset"' in l
           and not l.strip().startswith("//")), None)
if gi is not None and gi + 1 < len(lines) and "continue" in lines[gi + 1]:
    mut = (lines[gi] + "\n" + lines[gi + 1] + "\n", "")
    probe("preset skip (guard + continue) removed", mut)
else:
    fail("self-probe baseline broken: preset guard + continue pair not found")

# 2. move the transaction after the loop: strip the transaction line, then
#    append it just before the closing brace
g = next((l for l in lines if 'beginNewTransaction("Randomize")' in l
          and not l.strip().startswith("//")), None)
if g is not None:
    tmp2 = proc_c.replace(g + "\n", "", 1)
    cb = extract_body(tmp2, "randomizePreset")
    # find original (comment-stripped) body end to splice the txn inside
    k = tmp2.find("CorvusFXAudioProcessor::randomizePreset()")
    o = tmp2.find("{", k)
    depth, j = 0, o
    while j < len(tmp2):
        if tmp2[j] == "{": depth += 1
        elif tmp2[j] == "}":
            depth -= 1
            if depth == 0: break
        j += 1
    tmp2 = tmp2[:j] + "    " + g.strip() + "\n" + tmp2[j:]
    if tmp2 == proc_c:
        print("randomize: no-op mutation guard -> skipping invalid probe (txn after loop)")
    elif recheck(tmp2):
        print("randomize: SELF-PROBE FAIL: transaction moved after the loop")
        sys.exit(1)
    else:
        print("randomize: self-probe fired: transaction moved after the loop -> rejected")
else:
    fail("self-probe baseline broken: Randomize transaction line not found")

# 3. add a stray write before the guard
if gi is not None:
    stray = "        ranged->setValueNotifyingHost(0.5f);\n"
    tmp3 = proc_c[:proc_c.find(lines[gi])] + stray + \
           proc_c[proc_c.find(lines[gi]):]
    if recheck(tmp3):
        print("randomize: SELF-PROBE FAIL: write placed before the guard passed")
        sys.exit(1)
    print("randomize: self-probe fired: write before the guard -> rejected")

# 4. no-op: benign comment addition inside the body must stay accepted
first_body_line = next(l for l in lines if "juce::Random rng;" in l)
tmp4 = proc_c.replace(first_body_line,
                      "// benign probe edit\n" + first_body_line, 1)
if tmp4 == proc_c:
    print("randomize: no-op probe skipped")
elif not recheck(tmp4):
    fail("no-op guard: benign edit inside randomizePreset was wrongly rejected")
print("randomize: no-op guard passed (benign edit accepted)")

print("RANDOMIZE-SHAPE OK")
