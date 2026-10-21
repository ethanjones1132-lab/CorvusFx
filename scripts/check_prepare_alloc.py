#!/usr/bin/env python3
"""Headless checker: prepareToPlay allocation/prepare ordering in the plugin core.

The prepare side of the DSP contract lives in
`source/DrippyFX/PluginProcessor.cpp:397-405`:

    lastSampleRate = sampleRate;            // effects sample this later
    chorus.prepare(sampleRate);
    delay.prepare(sampleRate);
    distortion.prepare(sampleRate);
    upgradedReverb.prepare(sampleRate);
    masterOutput.prepare(sampleRate);
    dryBuffer.setSize(2, samplesPerBlock, false, true, true);

check_buses_channel_guard.py pins only the feed-ordering INSIDE processBlock
(dryBuffer.copyFrom before the per-sample loop) — nothing headless pins the
prepare-side allocation itself. A future edit that drops the dryBuffer.setSize
entirely (the processBlock feed then writes into a zero-size buffer → the
crossfade reads garbage/silence), shrinks it to 1 channel (the stereo dry path
reads channel 1 unallocated), reorders the setSize before lastSampleRate /
the prepares, or drops one effect prepare compiles clean behind an
otherwise-green gate.

Asserts on the real tree (comment-stripped, brace-matched prepareToPlay body):
  (a) `lastSampleRate = sampleRate` appears BEFORE the first .prepare( call;
  (b) all 5 effect .prepare(sampleRate) calls (chorus, delay, distortion,
      upgradedReverb, masterOutput) appear in order;
  (c) the 5-arg form `dryBuffer.setSize(2, samplesPerBlock, false, true, true)`
      appears AFTER the last .prepare call.

Negative self-probes on mutated in-memory texts (real tree never mutated;
no-op mutation aborts as a stale alarm): drop the setSize → rejected;
shrink 2→1 channel → rejected; move setSize above the lastSampleRate
assignment → rejected; drop one effect prepare → rejected. Benign no-op edit
outside the pinned shapes → accepted (probe specificity).

Exit 0 = ok, 1 = violation with a cited diagnostic.
"""
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SRC = ROOT / "source" / "DrippyFX"
CPP = SRC / "PluginProcessor.cpp"

EFFECTS = ("chorus", "delay", "distortion", "upgradedReverb", "masterOutput")


def fail(msg):
    print(f"PREPARE-ALLOC FAIL: {msg}")
    sys.exit(1)


def strip_comments(src):
    src = re.sub(r"/\*.*?\*/", "", src, flags=re.S)
    src = re.sub(r"//[^\n]*", "", src)
    return src


def brace_body(text, start_idx):
    i = text.find("{", start_idx)
    if i == -1:
        return None
    depth = 0
    j = i
    while j < len(text):
        if text[j] == "{":
            depth += 1
        elif text[j] == "}":
            depth -= 1
            if depth == 0:
                break
        j += 1
    return text[i : j + 1]


def extract_fn(code, name):
    m = re.search(r"void\s+CorvusFXAudioProcessor::%s\s*\(" % re.escape(name),
                  code)
    if not m:
        return None
    sig_close = code.find(")", m.start())
    if sig_close == -1:
        return None
    return brace_body(code, sig_close)


def _verify(cpp_text):
    code = strip_comments(cpp_text)
    prepare = extract_fn(code, "prepareToPlay")
    if not prepare:
        return "prepareToPlay body not found/brace-matched"

    # (a) lastSampleRate seeded before the first effect prepare
    seed = re.search(r"\blastSampleRate\s*=\s*sampleRate\s*;", prepare)
    if not seed:
        return ("prepareToPlay no longer seeds `lastSampleRate = sampleRate` "
                "— effects would sample a stale rate")
    first_prepare = re.search(r"\bchorus\.prepare\s*\(", prepare)
    if not first_prepare:
        return ("prepareToPlay does not prepare the chorus first — effect "
                "prepare order lost")
    if first_prepare.start() < seed.end():
        return ("an effect .prepare( call happens BEFORE "
                "`lastSampleRate = sampleRate` — effects would sample a "
                "stale rate")

    # (b) all 5 effect prepares, in order
    last_end = 0
    for fx in EFFECTS:
        m = re.search(r"\b%s\.prepare\s*\(\s*sampleRate\s*\)" % fx, prepare)
        if not m:
            return ("prepareToPlay no longer calls %s.prepare(sampleRate) — "
                    "that module would stream unprepared" % fx)
        if m.start() < last_end:
            return ("effect .prepare( order drifted (%s out of DSP order) — "
                    "prepare sequence is pinned" % fx)
        last_end = m.end()

    # (c) 5-arg dryBuffer.setSize after the last prepare
    size_m = re.search(
        r"\bdryBuffer\.setSize\s*\(\s*2\s*,\s*samplesPerBlock\s*,\s*false\s*,"
        r"\s*true\s*,\s*true\s*\)",
        prepare,
    )
    if not size_m:
        return ("prepareToPlay lost the 5-arg "
                "`dryBuffer.setSize(2, samplesPerBlock, false, true, true)` — "
                "the processBlock feed would write into a zero-size buffer "
                "or a 1-channel stereo dry path would read channel 1 "
                "unallocated")
    if size_m.start() < last_end:
        return ("dryBuffer.setSize moved BEFORE the effect prepares — "
                "the pinned allocation-after-prepare order changed")
    return None


def main():
    if not CPP.exists():
        fail(f"missing source file {CPP}")
    cpp_raw = CPP.read_text(encoding="utf-8")
    err = _verify(cpp_raw)
    if err:
        fail(err)
    print("prepare-alloc: lastSampleRate seed precedes 5 effect prepares, "
          "DSP prepare order intact, 5-arg dryBuffer.setSize(2, ...) after "
          "the prepares")

    probes = [
        ("drop the dryBuffer.setSize",
         "dryBuffer.setSize(2, samplesPerBlock, false, true, true);",
         ""),
        ("shrink dryBuffer to 1 channel",
         "dryBuffer.setSize(2, samplesPerBlock, false, true, true);",
         "dryBuffer.setSize(1, samplesPerBlock, false, true, true);"),
        ("move setSize above the lastSampleRate seed",
         "    lastSampleRate = sampleRate;\n"
         "    chorus.prepare(sampleRate);",
         "    dryBuffer.setSize(2, samplesPerBlock, false, true, true);\n"
         "    lastSampleRate = sampleRate;\n"
         "    chorus.prepare(sampleRate);"),
        ("drop one effect prepare (distortion)",
         "    distortion.prepare(sampleRate);\n",
         "    // distortion.prepare(sampleRate);\n"),
    ]

    for label, old, new in probes:
        if old not in cpp_raw:
            fail(f"no-op probe ({label}): pattern absent — probe is stale")
        mutated = cpp_raw.replace(old, new)
        if mutated == cpp_raw:
            fail(f"no-op probe ({label}): mutation did not change the source")
        try:
            err = _verify(mutated)
        except Exception as e:  # defensive: probe machinery must not mask
            err = str(e)
        if err:
            print(f"prepare-alloc: negative probe '{label}' rejected "
                  f"({err[:80]}...)")
        else:
            fail(f"negative probe '{label}' was NOT rejected — checker is "
                 f"vacuous")

    # no-op guard: benign edit outside the pinned shapes must still pass
    shifted = cpp_raw.replace(
        "const double smoothTime = 0.02; // 20ms",
        "const double smoothTime = 0.02; // 20 ms")
    if shifted == cpp_raw:
        fail("no-op guard: unanchored neutral edit did not change the source")
    err = _verify(shifted)
    if err:
        fail(f"neutral edit outside the pinned shapes was REJECTED — checker "
             f"over-fires: {err}")
    print("prepare-alloc: neutral no-op edit passes (probe specificity "
          "proven)")
    print("prepare-alloc: OK")


if __name__ == "__main__":
    main()
