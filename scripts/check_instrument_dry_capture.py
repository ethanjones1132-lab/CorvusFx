#!/usr/bin/env python3
"""Headless checker: the Corvus Instrument dry feed must not allocate per block.

Pins the front half of `source/DrippyFX/instrument/CorvusInstrumentProcessor.cpp`
`CorvusInstrumentProcessor::processBlock`, where the synth-rendered stereo block
used to be copied into a scratch `dryBuffer` before the per-sample effects loop:

    if (dryBuffer.getNumSamples() < buffer.getNumSamples())
        dryBuffer.setSize(2, buffer.getNumSamples(), false, false, true);
    for (auto channel = 0; channel < 2; ++channel)
        dryBuffer.copyFrom(channel, 0, buffer, channel, 0,
                           buffer.getNumSamples());

`prepareToPlay` sizes `dryBuffer` to the host's block hint, but JUCE's prepared
block size is only a hint, not a contractual upper bound: a host that delivers a
larger block made the guard call `setSize` (and `copyFrom` copy the whole block)
on the audio thread. An arbitrary reserve does not fix that defect. The live
source instead captures the pristine L/R synth output once per sample, uses the
captures as the DSP inputs, and blends the same captures in the existing exact
dry/wet crossfade. The prepare-side storage may stay (header out of scope); only
the per-block feed must be gone.

Asserts on the real tree (comment-stripped, brace-matched processBlock body):
  (a) `processBlock` contains no `dryBuffer` use at all - the legacy
      `setSize`/`copyFrom` feed (block-sized allocation + copy) is rejected, as
      is a stray dry-buffer read that would mean the pristine capture is gone.
  (b) the first per-sample loop captures the pristine synth output into
      `const float dryLeft = buffer.getSample(0, sample);` and
      `const float dryRight = buffer.getSample(1, sample);` exactly once each,
      with L reading channel 0 and R reading channel 1 (a channel swap is
      rejected).
  (c) those captures sit BEFORE the first effect call and before the first
      `buffer` write in the loop, and the DSP seeds read the captures
      (`auto processedLeft = dryLeft;` / `... = dryRight;`), so both the effects
      chain and the blend get the pristine input rather than processed samples.
  (d) the dry/wet gain math is unchanged (`wet = fxAmount.getNextValue()`,
      `dry = 1.0f - wet`) and the blend writes the exact pinned crossfade:
      `buffer.setSample(0, sample, dryLeft * dry + processedLeft * wet);` and
      the R twin with `dryRight`/`processedRight`. Changed blend math and
      swapped channels are rejected.

Negative self-probes on mutated in-memory texts (the real tree is never mutated;
a mutation that changes nothing aborts as a stale alarm):
  - restore the allocating `dryBuffer` resize/copy feed -> rejected
  - drop the pristine capture -> rejected
  - move the capture after the DSP/output write -> rejected
  - swap the L/R capture channels -> rejected
  - swap the channels in the blend -> rejected
  - change the blend math / dry gain -> rejected
  - seed the DSP from the buffer instead of the capture -> rejected
  - benign edit outside the pinned shape -> accepted (probe specificity)

Exit 0 = ok, 1 = violation with a cited diagnostic.
"""
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SRC = ROOT / "source" / "DrippyFX" / "instrument" / "CorvusInstrumentProcessor.cpp"


class _Rejected(Exception):
    pass


def strip_comments(src):
    src = re.sub(r"//[^\n]*", "", src)
    src = re.sub(r"/\*.*?\*/", "", src, flags=re.S)
    return src


def brace_span(s, open_idx):
    depth = 0
    for j in range(open_idx, len(s)):
        if s[j] == "{":
            depth += 1
        elif s[j] == "}":
            depth -= 1
            if depth == 0:
                return j
    return -1


def extract_fn(code, class_name, fn_name):
    m = re.search(
        r"void\s+%s\s*::\s*%s\s*\("
        % (re.escape(class_name), re.escape(fn_name)),
        code,
    )
    if not m:
        return None
    sig_close = code.find(")", m.end())
    if sig_close == -1:
        return None
    open_idx = code.find("{", sig_close)
    if open_idx == -1:
        return None
    end_idx = brace_span(code, open_idx)
    if end_idx == -1:
        return None
    return code[open_idx + 1:end_idx]


def _verify(cpp_text):
    """Raise _Rejected on a violation; return None when the shape is intact."""
    code = strip_comments(cpp_text)
    if not re.search(r"CorvusInstrumentProcessor", code):
        raise _Rejected("CorvusInstrumentProcessor not found in source")

    process = extract_fn(code, "CorvusInstrumentProcessor", "processBlock")
    if process is None:
        raise _Rejected(
            "CorvusInstrumentProcessor::processBlock body not found/brace-matched")

    # (a) No dry-buffer traffic may remain in the audio callback. The legacy
    # feed allocated (`setSize`) and copied (`copyFrom`) whole blocks here.
    dry_use = re.search(r"\bdryBuffer\b", process)
    if dry_use:
        member = re.search(r"\bdryBuffer\s*\.\s*(\w+)", process)
        what = member.group(1) + "(...)" if member else "reference"
        raise _Rejected(
            "processBlock still uses dryBuffer %s - the per-block dry "
            "feed was block-length dependent and could allocate on the audio "
            "thread; the pristine per-sample capture must replace it"
            % what)

    # The pristine source is the synth-rendered buffer, so render must happen
    # inside processBlock before the per-sample loop.
    render = re.search(
        r"\bsynthEngine\s*\.\s*render\s*\(\s*buffer\s*,", process)
    if not render:
        raise _Rejected(
            "processBlock no longer renders the synth into `buffer` before the "
            "dry capture - the pristine input source is gone")

    loop = re.search(
        r"for\s*\(\s*auto\s+sample\s*=\s*0\s*;\s*sample\s*<\s*"
        r"buffer\s*\.\s*getNumSamples\s*\(\s*\)\s*;\s*\+\+\s*sample\s*\)",
        process,
    )
    if not loop:
        raise _Rejected(
            "per-sample loop `for (auto sample = 0; sample < "
            "buffer.getNumSamples(); ++sample)` not found in processBlock")
    if render.start() > loop.start():
        raise _Rejected(
            "synthEngine.render sits after the per-sample loop - the capture "
            "would read stale or effect-written samples")

    open_idx = process.find("{", loop.end())
    if open_idx == -1:
        raise _Rejected("per-sample loop has no body brace")
    end_idx = brace_span(process, open_idx)
    if end_idx == -1:
        raise _Rejected("per-sample loop body braces unbalanced")
    body = process[open_idx + 1:end_idx]
    if len(body) < 500:
        raise _Rejected(
            "per-sample loop body is only %d chars - loop detection drifted; "
            "do not trust green" % len(body))

    # (b) Pristine per-sample stereo capture, channel-correct and unique.
    cap_l_anchor = "const float dryLeft = buffer.getSample(0, sample);"
    cap_r_anchor = "const float dryRight = buffer.getSample(1, sample);"
    cap_l = body.find(cap_l_anchor)
    cap_r = body.find(cap_r_anchor)
    if cap_l == -1:
        if re.search(
                r"\bdryLeft\s*=\s*buffer\s*\.\s*getSample\s*\(\s*1\b", body):
            raise _Rejected(
                "dryLeft captures buffer channel 1 - the pristine L/R captures "
                "are channel-swapped")
        raise _Rejected(
            "missing pristine left capture `const float dryLeft = "
            "buffer.getSample(0, sample);` before the effects chain")
    if cap_r == -1:
        if re.search(
                r"\bdryRight\s*=\s*buffer\s*\.\s*getSample\s*\(\s*0\b", body):
            raise _Rejected(
                "dryRight captures buffer channel 0 - the pristine L/R "
                "captures are channel-swapped")
        raise _Rejected(
            "missing pristine right capture `const float dryRight = "
            "buffer.getSample(1, sample);` before the effects chain")
    if body.count(cap_l_anchor) != 1 or body.count(cap_r_anchor) != 1:
        raise _Rejected(
            "pristine dry capture duplicated or reshaped - dryLeft/dryRight "
            "must each be captured exactly once per sample")
    if cap_r < cap_l:
        raise _Rejected("dryRight capture precedes dryLeft - channel labels drifted")

    # (c) DSP seeds consume the captures, and the captures precede all DSP and
    # all buffer writes (otherwise they would capture processed samples).
    seed_l_anchor = "auto processedLeft = dryLeft;"
    seed_r_anchor = "auto processedRight = dryRight;"
    seed_l = body.find(seed_l_anchor)
    seed_r = body.find(seed_r_anchor)
    if seed_l == -1 or seed_r == -1:
        if re.search(
                r"\bprocessedLeft\s*=\s*dryRight\b", body) or re.search(
                r"\bprocessedRight\s*=\s*dryLeft\b", body):
            raise _Rejected(
                "DSP seeds read the opposite dry capture - channel swap")
        raise _Rejected(
            "DSP seeds no longer read the pristine captures "
            "(`auto processedLeft = dryLeft;` / `... = dryRight;`)")

    first_dsp = re.search(r"\beffects\s*->\s*\w+\s*\.\s*\w+\s*\(", body)
    if not first_dsp:
        raise _Rejected(
            "no effects-chain call found in the per-sample loop - DSP order "
            "cannot be verified")
    first_write = re.search(
        r"\bbuffer\s*\.\s*(setSample|getWritePointer|clear)\s*\(", body)
    if not first_write:
        raise _Rejected(
            "no buffer output write found in the per-sample loop - the blend "
            "cannot be verified")
    first_overwrite = min(first_dsp.start(), first_write.start())
    if cap_l > first_overwrite or cap_r > first_overwrite:
        raise _Rejected(
            "pristine dry capture sits after DSP or an output overwrite - it "
            "would capture processed samples instead of the synth output")
    if seed_l > first_dsp.start() or seed_r > first_dsp.start():
        raise _Rejected(
            "DSP seed sits after the first effect call - the chain would not "
            "start from the pristine capture")
    if seed_l < cap_l or seed_r < cap_r:
        raise _Rejected(
            "DSP seed precedes its dry capture - declaration order drifted")

    # (d) Unchanged dry/wet gain math and exact pinned blend, channel-correct.
    wet_anchor = "const auto wet = fxAmount.getNextValue();"
    dry_anchor = "const auto dry = 1.0f - wet;"
    wet_pos = body.find(wet_anchor)
    dry_pos = body.find(dry_anchor)
    if wet_pos == -1 or dry_pos == -1:
        raise _Rejected(
            "dry/wet gain math changed - `wet = fxAmount.getNextValue()` and "
            "`dry = 1.0f - wet` must be kept")

    blend_l_anchor = (
        "buffer.setSample(0, sample, dryLeft * dry + processedLeft * wet);")
    blend_r_anchor = (
        "buffer.setSample(1, sample, dryRight * dry + processedRight * wet);")
    blend_l = body.find(blend_l_anchor)
    blend_r = body.find(blend_r_anchor)
    if blend_l == -1:
        if re.search(
                r"buffer\s*\.\s*setSample\s*\(\s*0\s*,\s*sample\s*,\s*"
                r"dryRight\b", body):
            raise _Rejected(
                "left blend uses the right dry capture - channel swap")
        raise _Rejected(
            "left dry/wet blend no longer uses the exact pristine capture math "
            "`dryLeft * dry + processedLeft * wet`")
    if blend_r == -1:
        if re.search(
                r"buffer\s*\.\s*setSample\s*\(\s*1\s*,\s*sample\s*,\s*"
                r"dryLeft\b", body):
            raise _Rejected(
                "right blend uses the left dry capture - channel swap")
        raise _Rejected(
            "right dry/wet blend no longer uses the exact pristine capture math "
            "`dryRight * dry + processedRight * wet`")
    if body.count(blend_l_anchor) != 1 or body.count(blend_r_anchor) != 1:
        raise _Rejected(
            "dry/wet blend duplicated or reshaped - each channel must be "
            "written exactly once from the pristine capture")
    if wet_pos > blend_l or dry_pos > blend_l:
        raise _Rejected(
            "dry/wet gains are computed after the blend - crossfade math drifted")
    return None


def fail(msg):
    print("INSTRUMENT-DRY-FEED FAIL: %s" % msg)
    getattr(sys, "exit")(1)


def run_text(cpp_text):
    try:
        _verify(cpp_text)
    except _Rejected as r:
        return str(r)
    return None


def main():
    if not SRC.exists():
        fail("missing source file %s" % SRC)
    text = SRC.read_text(encoding="utf-8")

    verdict = run_text(text)
    if verdict is not None:
        fail(verdict)
    print("instrument-dry-feed: processBlock uses per-sample pristine L/R "
          "captures, no dryBuffer feed, exact dry/wet blend")

    # Fixture: the legacy allocating feed must be rejected as the live source,
    # not silently accepted because the capture shape happens to remain.
    legacy = text.replace(
        "        const float dryLeft = buffer.getSample(0, sample);\n"
        "        const float dryRight = buffer.getSample(1, sample);\n"
        "        auto processedLeft = dryLeft;\n"
        "        auto processedRight = dryRight;\n",
        "        if (dryBuffer.getNumSamples() < buffer.getNumSamples())\n"
        "            dryBuffer.setSize(2, buffer.getNumSamples(), false, false, true);\n"
        "        for (auto channel = 0; channel < 2; ++channel)\n"
        "            dryBuffer.copyFrom(channel, 0, buffer, channel, 0,\n"
        "                               buffer.getNumSamples());\n"
        "        auto processedLeft = dryBuffer.getSample(0, sample);\n"
        "        auto processedRight = dryBuffer.getSample(1, sample);\n",
        1)
    if legacy == text:
        fail("legacy allocating feed fixture did not change the source - "
             "fixture is stale")
    if run_text(legacy) is None:
        fail("legacy allocating dryBuffer resize/copy feed is accepted as the "
             "LIVE source - a revert would pass the gate")
    print("instrument-dry-feed: legacy allocating feed rejected as the live "
          "source")

    probes = [
        ("drop the pristine right capture",
         lambda s: s.replace(
             "        const float dryRight = buffer.getSample(1, sample);\n",
             "", 1)),
        ("move the pristine capture after the DSP/output write",
         lambda s: s.replace(
             "        const float dryLeft = buffer.getSample(0, sample);\n"
             "        const float dryRight = buffer.getSample(1, sample);\n",
             "", 1).replace(
             "        const auto wet = fxAmount.getNextValue();",
             "        const float dryLeft = buffer.getSample(0, sample);\n"
             "        const float dryRight = buffer.getSample(1, sample);\n"
             "        const auto wet = fxAmount.getNextValue();", 1)),
        ("swap the left capture to channel 1",
         lambda s: s.replace(
             "const float dryLeft = buffer.getSample(0, sample);",
             "const float dryLeft = buffer.getSample(1, sample);", 1)),
        ("swap the right capture to channel 0",
         lambda s: s.replace(
             "const float dryRight = buffer.getSample(1, sample);",
             "const float dryRight = buffer.getSample(0, sample);", 1)),
        ("swap the channels in the blend",
         lambda s: s.replace(
             "buffer.setSample(0, sample, dryLeft * dry + processedLeft * wet);",
             "buffer.setSample(0, sample, dryRight * dry + processedLeft * wet);", 1)),
        ("swap the dry/wet blend coefficients",
         lambda s: s.replace(
             "buffer.setSample(0, sample, dryLeft * dry + processedLeft * wet);",
             "buffer.setSample(0, sample, dryLeft * wet + processedLeft * dry);", 1)),
        ("change the dry gain to wet",
         lambda s: s.replace(
             "const auto dry = 1.0f - wet;",
             "const auto dry = wet;", 1)),
        ("seed the DSP from the buffer instead of the capture",
         lambda s: s.replace(
             "auto processedLeft = dryLeft;",
             "auto processedLeft = buffer.getSample(0, sample);", 1)),
    ]
    for label, mutate in probes:
        mutated = mutate(text)
        if mutated == text:
            fail("no-op probe (%s): mutation did not change the source - the "
                 "negative check is vacuous" % label)
        verdict = run_text(mutated)
        if verdict is None:
            fail("negative probe '%s' was NOT rejected - checker is vacuous"
                 % label)
        print("instrument-dry-feed: negative probe '%s' rejected (%s...)"
              % (label, verdict[:72]))

    # No-op guard: a benign edit outside the pinned shape must still pass. The
    # prepare-time dryBuffer storage may stay (header out of scope) and is not
    # part of the audio-callback contract this checker pins.
    neutral = text.replace(
        "    dryBuffer.setSize(2, samplesPerBlock, false, false, true);",
        "    // Prepare-side storage is retained only for compatibility;\n"
        "    // processBlock never feeds a dry scratch buffer.\n"
        "    dryBuffer.setSize(2, samplesPerBlock, false, false, true);", 1)
    if neutral == text:
        fail("no-op guard: neutral edit did not change the source - probe is stale")
    verdict = run_text(neutral)
    if verdict is not None:
        fail("neutral edit outside the pinned processBlock shape was REJECTED - "
             "checker over-fires: %s" % verdict)
    print("instrument-dry-feed: benign non-callback edit passes (probe "
          "specificity proven)")

    # The real tree is never mutated; re-verify the untouched source once more.
    if run_text(SRC.read_text(encoding="utf-8")) is not None:
        fail("final live-source re-verification failed")
    print("instrument-dry-feed: OK")
    return 0


if __name__ == "__main__":
    getattr(sys, "exit")(main())
