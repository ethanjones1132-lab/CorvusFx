#!/usr/bin/env python3
"""Headless checker: processBlock block-scope smoothed-snapshot roster pin.

processBlock (source/DrippyFX/PluginProcessor.cpp:621-629) takes a
block-level snapshot of 9 smooth<X> values via getTargetValue():
    fatness, chorusDepth, chorusRate, chorusMix,
    delayDamping, reverbSize, reverbDamping, reverbMix, sReverbMod
in that order, feeding the beginBlock() coefficient caches (delay :635,
upgradedReverb :639, distortion :666, chorus :670) and the
reverbPreDelay precompute (:632). No other checker pins this block's
roster: check_beginblock_fan.py pins the beginBlock CALL sites,
check_smoothing_twin_scale.py pins the per-body setTargetValue seeds,
and check_raw_param_ids.py's (c2) accepts either per-sample
getNextValue() or the block getTargetValue() read.

Designed-in hazard: swapping ONE line's .getTargetValue() to the
class-sibling .getNextValue() at block scope consumes one smoothing-ramp
step per block and ADVANCES the shared ramp before the per-sample
getNextValue() loop — every per-sample value lands one ramp step early
(out-of-sync smoothing). It compiles clean behind an otherwise-green
gate. Likewise, deleting or reordering one snapshot line breaks the
block-scope feeds (stale/undefined variable or swapped coefficient
mapping) while still compiling or failing only at build time elsewhere.

Asserts (comment-stripped, brace-matched processBlock body):
  (a) the region from the snapshot roster start down to
      `delay.beginBlock(` contains EXACTLY the ordered 9-line
      `const float <x> = smooth<Y>.getTargetValue();` roster above,
      with no extra getTargetValue lines before delay.beginBlock;
  (b) NO `.getNextValue()` call inside that region (the
      ramp-consumption swap hazard).

Self-probes (negative checks, sibling checker style) run on mutated
in-memory TEMP texts — the real tree is never mutated. A no-op mutation
guard skips probes whose mutation didn't apply.

Exit 0 = ok, 1 = violation with line-cited diagnostics.
"""
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SRC = ROOT / "source" / "DrippyFX"

# (local name, smoother member) in the pinned ORDER
EXPECTED_ROSTER = [
    ("fatness", "smoothFatness"),
    ("chorusDepth", "smoothChorusDepth"),
    ("chorusRate", "smoothChorusRate"),
    ("chorusMix", "smoothChorusMix"),
    ("delayDamping", "smoothDelayDamping"),
    ("reverbSize", "smoothReverbSize"),
    ("reverbDamping", "smoothReverbDamping"),
    ("reverbMix", "smoothReverbMix"),
    ("sReverbMod", "smoothReverbMod"),
]


def fail(msg):
    print(f"BLOCK-SNAPSHOT-ROSTER FAIL: {msg}")
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


def collapse_ws(s):
    return re.sub(r"\s+", " ", s).strip()


def check(body_stripped):
    """Return None if ok, else a diagnostic string."""
    # Find the first `const float ` snapshot line that reads
    # smoothFatness.getTargetValue() — the roster's head.
    first = re.search(
        r"const float fatness\s*=\s*smoothFatness\.getTargetValue\(\);",
        body_stripped)
    if not first:
        return ("block snapshot roster head "
                "`const float fatness = smoothFatness.getTargetValue();` "
                "not found in processBlock")
    # Region of interest: roster head ..  delay.beginBlock( inclusive-ish
    begin_k = body_stripped.find("delay.beginBlock(", first.end())
    if begin_k == -1:
        return "delay.beginBlock( call not found after the snapshot roster"
    region = body_stripped[first.start():begin_k]

    lines = [collapse_ws(l) for l in region.split("\n")]
    snap_re = re.compile(
        r"const float (\w+)\s*=\s*(\w+)\.getTargetValue\(\);")
    snaps = [m for l in lines if (m := snap_re.fullmatch(l))]
    # Ignore blank/const pingPong/preDelay lines between roster and beginBlock
    if len(snaps) != len(EXPECTED_ROSTER):
        got = [f"{m.group(1)}={m.group(2)}" for m in snaps]
        return (f"expected exactly {len(EXPECTED_ROSTER)} getTargetValue "
                f"snapshot lines before delay.beginBlock, found "
                f"{len(snaps)}: {got}")
    for idx, (m, (name, smoother)) in enumerate(zip(snaps, EXPECTED_ROSTER)):
        if m.group(1) != name:
            return (f"snapshot line {idx} local name drifted: expected "
                    f"`{name}`, got `{m.group(1)}`")
        if m.group(2) != smoother:
            return (f"snapshot line {idx} smoother drifted: expected "
                    f"`{smoother}.getTargetValue()`, got "
                    f"`{m.group(2)}.getTargetValue()`")
        # rebuild the exact expected collapsed text
        expect = f"const float {name} = {smoother}.getTargetValue();"
        if m.group(0) != expect:
            return f"snapshot line {idx} does not match `{expect}`"
    if len(snaps) != len(EXPECTED_ROSTER):
        return "roster order drifted"

    # (b) NO getNextValue() inside the snapshot..beginBlock region —
    # swapping one .getTargetValue() to .getNextValue() consumes one
    # ramp step per block and advances the shared ramp before the
    # per-sample getNextValue() loop.
    if re.search(r"\.getNextValue\(\)", region):
        return (".getNextValue() must NOT appear in the block-scope "
                "snapshot region (roster..delay.beginBlock): it consumes "
                "a smoothing-ramp step per block, desyncing the per-sample "
                "ramp loop")
    return None


proc_c_path = SRC / "PluginProcessor.cpp"
if not proc_c_path.exists():
    fail(f"missing source file {proc_c_path}")
proc_c = proc_c_path.read_text(encoding="utf-8")

body = extract_body(proc_c, "processBlock")
err = check(body)
if err:
    fail(err + " (PluginProcessor.cpp processBlock)")
print("block-snapshot-roster: ordered 9-line getTargetValue snapshot "
      "block (fatness..sReverbMod) pinned, no getNextValue() in the "
      "snapshot..delay.beginBlock region")


# ---------------------------------------------------------------------------
# Self-probes on mutated in-memory texts (real tree never mutated)
# ---------------------------------------------------------------------------

def probe(description, old, new, count=1):
    tmp_raw = proc_c.replace(old, new, count)
    if tmp_raw == proc_c:
        print(f"block-snapshot-roster: no-op mutation guard -> skipping "
              f"invalid probe ({description})")
        return
    if check(extract_body(tmp_raw, "processBlock")) is None:
        print(f"block-snapshot-roster: SELF-PROBE FAIL (checker should "
              f"reject): {description}")
        sys.exit(1)
    print(f"block-snapshot-roster: self-probe fired: {description} -> "
          f"rejected")


# 1. one roster line DELETED (reverbMix snapshot gone: reverbPreDelay
#    precompute and the reverb beginBlock feed lose their seed)
probe("reverbMix snapshot line deleted",
      "const float reverbMix   = smoothReverbMix.getTargetValue();\n",
      "", 1)

# 2. one snapshot's getTargetValue swapped to getNextValue (ramp-consumption
#    swap hazard: advances the shared ramp before the per-sample loop)
probe("chorusRate snapshot swapped to getNextValue (ramp consumes a step "
      "per block, per-sample values land one step early)",
      "const float chorusRate  = smoothChorusRate.getTargetValue();",
      "const float chorusRate  = smoothChorusRate.getNextValue();")

# 3. roster ORDER drifted (two lines swapped between bodies)
probe("reverbSize/reverbDamping snapshot order swapped",
      "const float reverbSize  = smoothReverbSize.getTargetValue();\n"
      "    const float reverbDamping = smoothReverbDamping.getTargetValue();",
      "const float reverbDamping = smoothReverbDamping.getTargetValue();\n"
      "    const float reverbSize  = smoothReverbSize.getTargetValue();")

# 4. roster head drifted (fatness snapshot deleted entirely)
probe("fatness snapshot line deleted (roster head gone)",
      "const float fatness     = smoothFatness.getTargetValue();\n",
      "", 1)

# 5. a stray getNextValue() slipped into the snapshot region (extra hazard
#    form of (b): not one of the 9 roster lines, still advances the ramp)
probe("stray getNextValue() call inserted into the snapshot region",
      "delay.beginBlock(delayDamping);",
      "const float strayProbe = smoothFatness.getNextValue();\n    "
      "delay.beginBlock(delayDamping);", 1)

# 6. no-op guard: benign comment addition inside the region must stay
#    accepted
tmp = proc_c.replace(
    "const float pingPong = 0.35f;",
    "// benign probe edit\n    const float pingPong = 0.35f;", 1)
if tmp == proc_c:
    print("block-snapshot-roster: no-op probe skipped")
elif check(extract_body(tmp, "processBlock")) is not None:
    fail("no-op guard: benign edit was wrongly rejected")
print("block-snapshot-roster: no-op guard passed (benign edit accepted)")

print("BLOCK-SNAPSHOT-ROSTER OK")
