#!/usr/bin/env python3
"""Headless checker: CV-030 block-level coefficient snapshot must read the
AUDIBLE smoothed value (getCurrentValue()), never the ramp target.

`CorvusFXAudioProcessor::processBlock` seeds its once-per-block coefficient
caches (delay / reverb / distortion / chorus beginBlock + the reverb pre-delay
geometry) from a 9-line block-scope snapshot of smooth<X> values:

    fatness, chorusDepth, chorusRate, chorusMix,
    delayDamping, reverbSize, reverbDamping, reverbMix, sReverbMod

Before CV-030 every one of those lines read `getTargetValue()`. That is the
FAR END of an in-flight ramp, so a block that begins while a knob is still
ramping seeded its caches with a coefficient the audio path had not reached
yet; percussive material then jumped when the next block landed on the value
the smoother had actually reached. The snapshot must read
`getCurrentValue()` — the value the previous block rendered, i.e. what the
user hears at the block boundary.

`getCurrentValue()` is a pure read: it does NOT advance the ramp. The ramp is
still advanced exactly once per sample by the per-sample `getNextValue()`
seeds, which are pinned here unchanged.

Asserts (comment-stripped, brace-matched processBlock body):
  (a) the block-scope snapshot region (roster head .. `delay.beginBlock(`)
      holds EXACTLY the ordered 9 `const float <x> = smooth<Y>.getCurrentValue();`
      lines, each exactly once;
  (b) that region contains NO `.getNextValue()` (would consume one ramp step
      per block and desync the per-sample ramp) and NO `.getTargetValue()`
      (the CV-030 stale-ramp-target read), and no `.skip(` /
      `setCurrentAndTargetValue` (no ramp advance at block scope);
  (c) the four per-sample smoother seeds that twin the block snapshot
      (sFatness / sChorusDepth / sChorusRate / sReverbMix) are untouched:
      each is a `smooth<Y>.getNextValue()` read inside the per-sample loop,
      and each of those four smoothers is advanced by getNextValue() exactly
      ONCE in processBlock and nowhere before the loop;
  (d) every snapshot local is still consumed by the coefficient feeds:
      `distortion.beginBlock(fatness)`,
      `chorus.beginBlock(chorusDepth, chorusMix, chorusRate)`,
      `delay.beginBlock(delayDamping)`,
      `upgradedReverb.beginBlock(reverbSize, reverbDamping, reverbMix,
      sReverbMod, ...)` and `reverbPreDelay = 5.0f + reverbSize * 40.0f`.

Self-probes (negative checks, sibling checker style) run on mutated in-memory
TEMP texts — the real tree is never mutated:
  - EVERY one of the 9 snapshot lines is reverted to getTargetValue() in
    turn; each revert must be rejected (the CV-030 regression);
  - a per-sample seed converted to getCurrentValue() must be rejected;
  - a stray getNextValue() / `.skip(` inserted into the snapshot region must
    be rejected.

Exit 0 = ok, 1 = violation with line-cited diagnostics.
"""
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SRC = ROOT / "source" / "DrippyFX"

# (local name, smoother member) in the pinned snapshot ORDER
SNAPSHOT_ROSTER = [
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

# The per-sample seeds whose smoothers are ALSO snapshotted at block scope:
# exactly these four must keep advancing the ramp with getNextValue().
PER_SAMPLE_TWINS = [
    ("sFatness", "smoothFatness"),
    ("sChorusDepth", "smoothChorusDepth"),
    ("sChorusRate", "smoothChorusRate"),
    ("sReverbMix", "smoothReverbMix"),
]

CONSUMERS = [
    "distortion.beginBlock(fatness)",
    "chorus.beginBlock(chorusDepth, chorusMix, chorusRate)",
    "delay.beginBlock(delayDamping)",
    "upgradedReverb.beginBlock(reverbSize, reverbDamping, reverbMix, sReverbMod,",
    "const float reverbPreDelay = 5.0f + reverbSize * 40.0f;",
]


def fail(msg):
    print(f"CV030-BLOCK-COEFFS FAIL: {msg}")
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
        return None
    o = txt.find("{", k)
    if o == -1:
        return None
    depth, j = 0, o
    while j < len(txt):
        if txt[j] == "{": depth += 1
        elif txt[j] == "}":
            depth -= 1
            if depth == 0: break
        j += 1
    if depth != 0:
        return None
    return strip_comments(txt[o:j + 1])


def collapse_ws(s):
    return re.sub(r"\s+", " ", s).strip()


def loop_body_of(body):
    """Return the per-sample loop body, or None."""
    m = re.search(r"for\s*\(\s*int\s+s\s*=\s*0\s*;\s*s\s*<\s*numSamples", body)
    if not m:
        return None
    o = body.find("{", m.end())
    if o == -1:
        return None
    depth, j = 0, o
    while j < len(body):
        if body[j] == "{": depth += 1
        elif body[j] == "}":
            depth -= 1
            if depth == 0: break
        j += 1
    if depth != 0:
        return None
    return body[o + 1:j]


def snapshot_region(body):
    """(region, diagnostic) — roster head .. `delay.beginBlock(`."""
    first = re.search(
        r"const float fatness\s*=\s*smoothFatness\.getCurrentValue\(\);", body)
    if not first:
        return None, ("block snapshot roster head "
                      "`const float fatness = smoothFatness.getCurrentValue();` "
                      "not found in processBlock")
    begin_k = body.find("delay.beginBlock(", first.end())
    if begin_k == -1:
        return None, "delay.beginBlock( call not found after the snapshot roster"
    return body[first.start():begin_k], None


def check(full_text):
    """Return None if ok, else a diagnostic string."""
    body = extract_body(full_text, "processBlock")
    if body is None:
        return "could not extract the brace-matched processBlock body"

    region, err = snapshot_region(body)
    if err:
        return err

    # (a) ordered 9-line getCurrentValue roster, each exactly once.
    lines = [collapse_ws(l) for l in region.split("\n")]
    snap_re = re.compile(
        r"const float (\w+)\s*=\s*(\w+)\.getCurrentValue\(\);")
    snaps = [m for l in lines if (m := snap_re.fullmatch(l))]
    if len(snaps) != len(SNAPSHOT_ROSTER):
        got = [f"{m.group(1)}={m.group(2)}" for m in snaps]
        return (f"expected exactly {len(SNAPSHOT_ROSTER)} getCurrentValue "
                f"snapshot lines before delay.beginBlock, found "
                f"{len(snaps)}: {got}")
    for idx, (m, (name, smoother)) in enumerate(zip(snaps, SNAPSHOT_ROSTER)):
        expect = f"const float {name} = {smoother}.getCurrentValue();"
        if m.group(1) != name:
            return (f"snapshot line {idx} local name drifted: expected "
                    f"`{name}`, got `{m.group(1)}`")
        if m.group(2) != smoother:
            return (f"snapshot line {idx} smoother drifted: expected "
                    f"`{smoother}.getCurrentValue()`, got "
                    f"`{m.group(2)}.getCurrentValue()`")
        if m.group(0) != expect:
            return f"snapshot line {idx} does not match `{expect}`"

    # (b) block scope must not advance or target the ramp.
    if re.search(r"\.getNextValue\(\)", region):
        return (".getNextValue() in the block-scope snapshot region: it "
                "consumes one ramp step per block and desyncs the per-sample "
                "ramp loop")
    if re.search(r"\.getTargetValue\(\)", region):
        return (".getTargetValue() in the block-scope snapshot region: it "
                "reports the end of an in-flight ramp, so a block starting "
                "mid-ramp is seeded with a value the audio path has not "
                "reached yet (CV-030)")
    if re.search(r"\.skip\s*\(", region) or "setCurrentAndTargetValue" in region:
        return ("the block-scope snapshot region advances the smoother "
                "(skip/setCurrentAndTargetValue): the snapshot must be a pure "
                "read")

    # (c) the four twinned per-sample seeds are untouched.
    loop = loop_body_of(body)
    if loop is None:
        return "per-sample loop body could not be extracted from processBlock"
    before_loop = body[:body.find(loop)]
    for local, smoother in PER_SAMPLE_TWINS:
        seed = f"const float {local} = {smoother}.getNextValue();"
        loop_collapsed = [collapse_ws(l) for l in loop.split("\n")]
        hits = loop_collapsed.count(seed)
        if hits != 1:
            return (f"per-sample seed `{seed}` must appear exactly once in "
                    f"the per-sample loop, found {hits} — the CV-030 change "
                    "must leave every per-sample sampler seed untouched")
        if f"{smoother}.getNextValue()" in before_loop:
            return (f"{smoother}.getNextValue() appears BEFORE the per-sample "
                    "loop: the block snapshot pre-advances the shared ramp")
        advance_call = smoother + ".getNextValue()"
        advance_count = body.count(advance_call)
        if advance_count != 1:
            return (f"`{advance_call}` must be the ONLY ramp advance for that "
                    f"smoother, found {advance_count} in processBlock")

    # (d) the snapshot locals still feed the coefficient caches unchanged.
    collapsed_body = collapse_ws(body)
    for consumer in CONSUMERS:
        if collapse_ws(consumer) not in collapsed_body:
            return (f"coefficient feed `{consumer}` missing from processBlock "
                    "— the snapshot locals must still drive the beginBlock "
                    "caches")
    return None


proc_c_path = SRC / "PluginProcessor.cpp"
if not proc_c_path.exists():
    fail(f"missing source file {proc_c_path}")
proc_c = proc_c_path.read_text(encoding="utf-8")

err = check(proc_c)
if err:
    fail(err + " (PluginProcessor.cpp processBlock)")
print("cv030-block-coeffs: 9-line block snapshot reads getCurrentValue() "
      "(audible value), no ramp advance at block scope, 4 per-sample "
      "getNextValue seeds untouched, coefficient feeds intact")


# ---------------------------------------------------------------------------
# Self-probes on mutated in-memory texts (real tree never mutated)
# ---------------------------------------------------------------------------

def probe(description, old, new, count=1):
    tmp_raw = proc_c.replace(old, new, count)
    if tmp_raw == proc_c:
        print(f"cv030-block-coeffs: no-op mutation guard -> skipping invalid "
              f"probe ({description})")
        return False
    if check(tmp_raw) is None:
        print(f"cv030-block-coeffs: SELF-PROBE FAIL (checker should reject): "
              f"{description}")
        sys.exit(1)
    print(f"cv030-block-coeffs: self-probe fired: {description} -> rejected")
    return True


# 1. EVERY snapshot line reverted to getTargetValue() in turn — the exact
#    regression this checker exists to catch. Each single-line revert must
#    be rejected on its own, so no line can rot back silently. The line text
#    is located by regex so the alignment padding of the source is not
#    duplicated here (drift in either place is caught, not silently skipped).
def find_once(pattern):
    hits = re.findall(pattern, proc_c)
    if len(hits) != 1:
        fail(f"self-probe baseline broken: `{pattern}` matched {len(hits)} "
             "times in PluginProcessor.cpp (expected exactly 1)")
    return hits[0]


fired = 0
for name, smoother in SNAPSHOT_ROSTER:
    line = find_once(
        rf"const float {name}\s*=\s*{smoother}\.getCurrentValue\(\);")
    if probe(f"snapshot line `{name}` reverted to getTargetValue()",
             line, line.replace(".getCurrentValue()", ".getTargetValue()")):
        fired += 1
if fired != len(SNAPSHOT_ROSTER):
    fail(f"only {fired}/{len(SNAPSHOT_ROSTER)} snapshot reverts were probed — "
         "the roster text in this checker drifted from the source")

# 2. a per-sample seed converted to getCurrentValue() (would freeze the
#    per-sample ramp at the block-boundary value)
fat_seed = find_once(
    r"const float sFatness\s*=\s*smoothFatness\.getNextValue\(\);")
probe("per-sample sFatness seed converted to getCurrentValue()",
      fat_seed, fat_seed.replace(".getNextValue()", ".getCurrentValue()"))

# 3. a stray getNextValue() at block scope (ramp consumed before the loop)
probe("stray getNextValue() inserted into the snapshot region",
      "delay.beginBlock(delayDamping);",
      "const float strayProbe = smoothFatness.getNextValue();\n    "
      "delay.beginBlock(delayDamping);", 1)

# 4. a stray ramp advance (skip) at block scope
probe("stray .skip() inserted into the snapshot region",
      "delay.beginBlock(delayDamping);",
      "smoothFatness.skip(numSamples);\n    delay.beginBlock(delayDamping);", 1)

# 5. a snapshot local orphaned from its coefficient feed
probe("delay beginBlock feed drifted off the delayDamping snapshot",
      "delay.beginBlock(delayDamping);",
      "delay.beginBlock(0.5f);", 1)

# 6. no-op guard: benign comment addition inside the region must stay
#    accepted
tmp = proc_c.replace(
    "const float pingPong = 0.35f;",
    "// benign probe edit\n    const float pingPong = 0.35f;", 1)
if tmp == proc_c:
    print("cv030-block-coeffs: no-op probe skipped")
elif check(tmp) is not None:
    fail("no-op guard: benign edit was wrongly rejected")
print("cv030-block-coeffs: no-op guard passed (benign edit accepted)")

print("CV030-BLOCK-COEFFS OK")
