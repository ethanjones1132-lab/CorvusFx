#!/usr/bin/env python3
"""Headless checker: delay-feedback seed twin + pingPong/preDelay geometry pin.

smoothDelayFeedback's exponential feedback curve is hand-maintained TWICE:
prepareToPlay (source/DrippyFX/PluginProcessor.cpp:440-442) seeds
`fbRaw * fbRaw * 0.65f + fbRaw * 0.27f` and processBlock repeats the
identical expression per-block (:511-512). No checker mentions fbRaw or
the curve: an edit that changes ONE copy (prepare seeds a different
feedback curve than streaming — the delay knob audibly duller until the
next re-prepare) ships green. Separately the block-level geometry
literals `const float pingPong = 0.35f` and
`reverbPreDelay = 5.0f + reverbSize * 40.0f` (:615-616) feeding
delay.processSample and upgradedReverb.beginBlock are unpinned.

Asserts (comment-stripped, brace-matched):
  (a) the `fbRaw * fbRaw * 0.65f + fbRaw * 0.27f` expression appears in
      BOTH the prepareToPlay and processBlock bodies (twin pin), each
      fed by `fbRaw = apvts.getRawParameterValue("delay_feedback")->load()`.
  (b) the processBlock (or ReadIntoLocalCache region) keeps
      `const float pingPong = 0.35f` and
      `const float reverbPreDelay = 5.0f + reverbSize * 40.0f`.

Self-probes (negative checks, sibling checker style) run on mutated
in-memory TEMP texts — the real tree is never mutated. A no-op mutation
guard skips probes whose mutation didn't apply.

Exit 0 = ok, 1 = violation with line-cited diagnostics.
"""
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SRC = ROOT / "source" / "DrippyFX"

FB_EXPR = "fbRaw * fbRaw * 0.65f + fbRaw * 0.27f"
FB_SEED = 'apvts.getRawParameterValue("delay_feedback")->load() / 100.0f'
PING = "const float pingPong = 0.35f;"
PREDELAY = "const float reverbPreDelay = 5.0f + reverbSize * 40.0f;"

def fail(msg):
    print(f"DELAY-SEED-SHAPES FAIL: {msg}")
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

def check_body(body):
    """Twin-seed check against a comment-stripped body. True = pass."""
    if FB_EXPR not in body:
        return False
    if FB_SEED not in body:
        return False
    # seed line must precede the curve line
    if body.find(FB_SEED) > body.find(FB_EXPR):
        return False
    return True

def check_geometry(region):
    """pingPong/preDelay literals in the comment-stripped region."""
    return PING in region and PREDELAY in region

proc_c_path = SRC / "PluginProcessor.cpp"
if not proc_c_path.exists():
    fail(f"missing source file {proc_c_path}")
proc_c = proc_c_path.read_text(encoding="utf-8")

prep_body = extract_body(proc_c, "prepareToPlay")
proc_body = extract_body(proc_c, "processBlock")

if not check_body(prep_body):
    fail("prepareToPlay lost the delay-feedback seed twin: need "
         f"`float fbRaw = {FB_SEED};` feeding `{FB_EXPR}` "
         "(PluginProcessor.cpp prepareToPlay)")
if not check_body(proc_body):
    fail("processBlock lost the per-block delay-feedback curve refresh: need "
         f"`float fbRaw = {FB_SEED};` feeding `{FB_EXPR}` "
         "(PluginProcessor.cpp processBlock)")
if not check_geometry(proc_body):
    fail("processBlock lost the block-level geometry literals: need "
         f"`{PING}` and `{PREDELAY}` (PluginProcessor.cpp processBlock)")
print("delay-seed: fb curve twin present in prepareToPlay AND processBlock, "
      "pingPong/reverbPreDelay geometry pinned")

# ---------------------------------------------------------------------------
# Self-probes on mutated in-memory texts (real tree never mutated)
# ---------------------------------------------------------------------------

def recheck(mutated_full_text):
    try:
        p = extract_body(mutated_full_text, "prepareToPlay")
        b = extract_body(mutated_full_text, "processBlock")
    except SystemExit:
        return False
    return check_body(p) and check_body(b) and check_geometry(b)

def probe(description, mutator):
    tmp = proc_c.replace(*mutator)
    if tmp == proc_c:
        print(f"delay-seed: no-op mutation guard -> skipping invalid probe ({description})")
        return
    if recheck(tmp):
        print(f"delay-seed: SELF-PROBE FAIL (checker should reject): {description}")
        sys.exit(1)
    print(f"delay-seed: self-probe fired: {description} -> rejected")

# 1. change the curve in the prepareToPlay copy ONLY (0.65f -> 0.60f there)
lines = proc_c.splitlines()
fb_idx = [i for i, l in enumerate(lines) if FB_EXPR in l
          and not l.strip().startswith("//")]
if len(fb_idx) != 2:
    fail(f"self-probe baseline broken: expected exactly 2 fb curve lines, found {len(fb_idx)}")
mut1 = (lines[fb_idx[0]].replace("0.65f", "0.60f"), lines[fb_idx[0]].replace("0.65f", "0.60f"))
probe("prepareToPlay fb curve changed alone (prepare/process twin desync)", mut1)

# 2. change the curve in the processBlock copy ONLY
alt = lines[fb_idx[1]].replace("0.65f", "0.60f")
cur = lines[fb_idx[1]]
if alt == cur:
    fail("self-probe baseline broken: curve mutation is a no-op")
mut2 = (cur, alt)
probe("processBlock fb curve changed alone", mut2)

# 3. drop the pingPong literal
pp = next((l for l in lines if "const float pingPong = 0.35f;" in l
           and not l.strip().startswith("//")), None)
if pp is None:
    fail("self-probe baseline broken: pingPong literal not found")
probe("pingPong literal dropped", (pp + "\n", ""))

# 4. rewrite the preDelay form (drop the reverbSize coupling)
pd = next((l for l in lines if "reverbPreDelay = 5.0f + reverbSize * 40.0f" in l
           and not l.strip().startswith("//")), None)
if pd is None:
    fail("self-probe baseline broken: reverbPreDelay literal not found")
probe("reverbPreDelay form rewritten (5.0f constant)", (pd, pd.replace("5.0f + reverbSize * 40.0f", "50.0f")))

# 5. no-op: benign comment addition inside prepareToPlay must stay accepted
anchor = next(l for l in lines if "smoothChorusMix.reset" in l)
tmp5 = proc_c.replace(anchor, "// benign probe edit\n" + anchor, 1)
if tmp5 == proc_c:
    print("delay-seed: no-op probe skipped")
elif not recheck(tmp5):
    fail("no-op guard: benign edit was wrongly rejected")
print("delay-seed: no-op guard passed (benign edit accepted)")

print("DELAY-SEED-SHAPES OK")
