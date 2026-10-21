#!/usr/bin/env python3
"""Headless checker: per-block meter-atomic STORE shapes pin.

processBlock's meter-store block (source/DrippyFX/PluginProcessor.cpp
:813-828) sits inside `if (chProc >= 1)` and writes 8 levelMeters
atomics in exactly TWO shapes fed by `const float rmsSmooth = 0.995f`:
  4 peaks  keep the monotonic high-water
      store(std::max(levelMeters.<id>.load(), <v>_), relaxed)
  4 RMS    keep the per-block blend
      store(levelMeters.<id>.load() * rmsSmooth
            + <v>_ * (1.0f - rmsSmooth), relaxed)
and both right-channel RMS locals keep the mono fallback
      float <x>RmsR_ = (chProc >= 2) ? std::sqrt(<x>RmsSumR_ /
            static_cast<float>(numSamples)) : <x>RmsL_;
No other checker pins these shapes: check_meter_timer.py pins the
EDITOR-side timer reading + decayPeaks order; check_buses_channel_guard
pins the dry-feed copyFrom.

Designed-in hazards (both compile clean behind an otherwise-green
gate): (a) a peak store rewritten to the RMS blend form makes peaks
decay continuously and the editor-side decayPeaks
(PluginEditor.cpp:296) fights a decaying source — meter bars sag
mid-sustained-note; (b) dropping the `(chProc >= 2)` fallback from a
right-channel RMS local computes sqrt over an accumulation that never
ran on mono buses (guarded by the per-sample `if (!isMono)` branch),
yielding NaN/garbage pinned to a nonexistent channel.

Asserts (comment-stripped, brace-matched processBlock body, in the
region from `const float rmsSmooth = 0.995f;` to the end of body):
  (a) `const float rmsSmooth = 0.995f` present;
  (b) the 4 peak stores (inPeakL, inPeakR, outPeakL, outPeakR) keep
      the std::max high-water form exactly once each;
  (c) the 4 RMS stores (inRmsL, inRmsR, outRmsL, outRmsR) keep the
      rmsSmooth blend form exactly once each;
  (d) inRmsR_/outRmsR_ keep the (chProc >= 2) ? sqrt : left fallback.

Self-probes (negative checks, sibling checker style) run on mutated
in-memory TEMP texts — the real tree is never mutated. A no-op
mutation guard skips probes whose mutation didn't apply.

Exit 0 = ok, 1 = violation with line-cited diagnostics.
"""
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SRC = ROOT / "source" / "DrippyFX"

PEAK_IDS = ["inPeakL", "inPeakR", "outPeakL", "outPeakR"]
RMS_IDS = ["inRmsL", "inRmsR", "outRmsL", "outRmsR"]


def fail(msg):
    print(f"METER-STORE-SHAPE FAIL: {msg}")
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


PEAK_RE = re.compile(
    r"levelMeters\.(\w+)\s*\.store\(std::max\(levelMeters\.\1\s*\.load\(\),"
    r"\s*(\w+)_\s*\),\s*std::memory_order_relaxed\);")
RMS_RE = re.compile(
    r"levelMeters\.(\w+)\s*\.store\(levelMeters\.\1\s*\.load\(\)"
    r"\s*\*\s*rmsSmooth\s*\+\s*(\w+)_\s*\*\s*\(1\.0f\s*-\s*rmsSmooth\),"
    r"\s*std::memory_order_relaxed\);")
FALLBACK_RE = re.compile(
    r"float (\w+R_)\s*=\s*\(chProc\s*>=\s*2\)\s*\?"
    r"\s*std::sqrt\((\w+SumR_)\s*/\s*static_cast<float>\(numSamples\)\)"
    r"\s*:\s*(\w+);")


def check(body_stripped):
    """Return None if ok, else a diagnostic string."""
    # (a) seed present, and the region runs from the seed line to the
    # end of processBlock (the meter block is the last work processBlock
    # does, DBGR confirms :813-828).
    seed_k = body_stripped.find("const float rmsSmooth = 0.995f;")
    if seed_k == -1:
        return ("`const float rmsSmooth = 0.995f;` not found in "
                "processBlock (the meter blend seed drifted or was "
                "dropped)")
    region = body_stripped[seed_k:]

    lines = [collapse_ws(l) for l in region.split("\n")]
    peaks, rmss = [], []
    for l in lines:
        m = PEAK_RE.fullmatch(l)
        if m:
            peaks.append(m)
            continue
        m = RMS_RE.fullmatch(l)
        if m:
            rmss.append(m)
            continue
        # a meter store line in a FOREIGN shape: the blend/high-water
        # taxonomy itself was broken for this store
        if re.match(r"levelMeters\.\w+\s*\.store\(", l):
            return (f"foreign store shape inside the meter block: "
                    f"`{l}` matches neither the std::max high-water "
                    f"peak form nor the rmsSmooth blend RMS form")

    # (b) peaks: exactly the 4 expected ids in order, monotonic form
    got = [m.group(1) for m in peaks]
    if got != PEAK_IDS:
        return (f"peak stores drifted: expected the 4 high-water ids "
                f"{PEAK_IDS} in order, found {got}")
    for m, pid in zip(peaks, PEAK_IDS):
        if not m.group(2) == pid[:0] + pid[0].lower() + pid[1:]:
            # value local must be <id>_ form sibling: inPeakL -> inPeakL_
            pass
        val = m.group(2)
        # expected value-local is the id without 'Peak'/'Rms'? No —
        # locals mirror the accumulators (inPeakL_ / outRmsR_).
        if val.lower() != pid.lower():
            return (f"peak store `{pid}` fed by unexpected value local "
                    f"`{val}_`")

    # (c) RMS: exactly the 4 expected ids in order, blend form
    got = [m.group(1) for m in rmss]
    if got != RMS_IDS:
        return (f"RMS stores drifted: expected the 4 blend ids "
                f"{RMS_IDS} in order (a peak rewritten to the blend "
                f"form lands here as a 5th or wrong-id entry), "
                f"found {got}")
    for m in rmss:
        pid = m.group(1)
        val = m.group(2)
        # e.g. inRmsL -> inRmsL_ : value local is pid with trailing '_'
        # (locals inRmsL_ / inRmsR_ / outRmsL_ / outRmsR_)
        if pid != val:
            return (f"RMS store `{pid}` fed by unexpected value local "
                    f"`{val}_`")

    # (d) both right-channel RMS locals keep the mono fallback shape
    fb = FALLBACK_RE.findall(region)
    if len(fb) != 2:
        return (f"expected 2 right-channel RMS fallback locals "
                f"(inRmsR_, outRmsR_) with the (chProc >= 2) ternary, "
                f"found {len(fb)}: {fb}")
    for local, sump, left in fb:
        if left != local[:-2] + "L_":
            return (f"RMS fallback `{local}` falls back to unexpected "
                    f"`{left}` (expected {local[:-2]}L_) — dropping the "
                    f"(chProc >= 2) guard computes sqrt over an "
                    f"accumulation that never ran on mono buses")
        if sump != local[:-2] + "SumR_":
            return f"RMS fallback `{local}` reads unexpected accumulator `{sump}`"
    return None


proc_c_path = SRC / "PluginProcessor.cpp"
if not proc_c_path.exists():
    fail(f"missing source file {proc_c_path}")
proc_c = proc_c_path.read_text(encoding="utf-8")

body = extract_body(proc_c, "processBlock")
err = check(body)
if err:
    fail(err + " (PluginProcessor.cpp processBlock)")
print("meter-store-shapes: 8 levelMeters atomics pinned (4 std::max "
      "high-water peaks + 4 rmsSmooth blend RMS) + both right-channel "
      "mono fallbacks inside the chProc >= 1 meter block")


# ---------------------------------------------------------------------------
# Self-probes on mutated in-memory texts (real tree never mutated)
# ---------------------------------------------------------------------------

def probe(description, old, new, count=1):
    tmp_raw = proc_c.replace(old, new, count)
    if tmp_raw == proc_c:
        print(f"meter-store-shapes: no-op mutation guard -> skipping "
              f"invalid probe ({description})")
        return
    if check(extract_body(tmp_raw, "processBlock")) is None:
        print(f"meter-store-shapes: SELF-PROBE FAIL (checker should "
              f"reject): {description}")
        sys.exit(1)
    print(f"meter-store-shapes: self-probe fired: {description} -> "
          f"rejected")


# 1. a peak store rewritten to the RMS blend form (peaks decay
#    continuously; editor decayPeaks fights a decaying source —
#    meter bars sag mid-sustained-note)
probe("inPeakL store rewritten to the RMS blend form (peaks decay; "
      "editor decayPeaks fights a decaying source — bars sag)",
      "levelMeters.inPeakL .store(std::max(levelMeters.inPeakL .load(), inPeakL_),  std::memory_order_relaxed);",
      "levelMeters.inPeakL .store(levelMeters.inPeakL .load() * rmsSmooth + inPeakL_ * (1.0f - rmsSmooth), std::memory_order_relaxed);")

# 2. mono fallback dropped from inRmsR_ (sqrt over an accumulation that
#    never ran on mono buses — NaN/garbage pinned to a dead channel)
probe("inRmsR_ mono fallback dropped (sqrt over an accumulator that "
      "never ran on mono buses)",
      "float inRmsR_ = (chProc >= 2) ? std::sqrt(inRmsSumR_ / static_cast<float>(numSamples)) : inRmsL_;",
      "float inRmsR_ = std::sqrt(inRmsSumR_ / static_cast<float>(numSamples));")

# 3. an RMS store's blend dropped entirely (stale meter never updates)
probe("outRmsL blend store deleted (meter freezes at its seed value)",
      "levelMeters.outRmsL .store(levelMeters.outRmsL .load() * rmsSmooth + outRmsL_ * (1.0f - rmsSmooth), std::memory_order_relaxed);",
      "juce::ignoreUnused(outRmsL_);")

# 4. rmsSmooth constant drift (0.995f -> 0.0f: RMS becomes a pure
#    per-block copy, no smoothing)
probe("rmsSmooth seed drifted 0.995f -> 0.0f (blend becomes a bare copy)",
      "const float rmsSmooth = 0.995f;",
      "const float rmsSmooth = 0.0f;")

# 5. RMS id ORDER swapped (inRmsR before inRmsL: store-id sequence drift)
probe("inRmsL/inRmsR store order swapped (id sequence drift)",
      "levelMeters.inRmsL  .store(levelMeters.inRmsL .load() * rmsSmooth + inRmsL_ * (1.0f - rmsSmooth), std::memory_order_relaxed);\n"
      "        levelMeters.inRmsR  .store(levelMeters.inRmsR .load() * rmsSmooth + inRmsR_ * (1.0f - rmsSmooth), std::memory_order_relaxed);",
      "levelMeters.inRmsR  .store(levelMeters.inRmsR .load() * rmsSmooth + inRmsR_ * (1.0f - rmsSmooth), std::memory_order_relaxed);\n"
      "        levelMeters.inRmsL  .store(levelMeters.inRmsL .load() * rmsSmooth + inRmsL_ * (1.0f - rmsSmooth), std::memory_order_relaxed);")

# 6. no-op guard: benign comment addition inside the block must stay
#    accepted
tmp = proc_c.replace(
    "const float rmsSmooth = 0.995f;",
    "// benign probe edit\n        const float rmsSmooth = 0.995f;", 1)
if tmp == proc_c:
    print("meter-store-shapes: no-op probe skipped")
elif check(extract_body(tmp, "processBlock")) is not None:
    fail("no-op guard: benign edit was wrongly rejected")
print("meter-store-shapes: no-op guard passed (benign edit accepted)")

print("METER-SHAPES OK")
