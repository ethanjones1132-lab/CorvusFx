#!/usr/bin/env python3
"""Headless checker: audio-channel-count guards + scalar dry-input ordering.

The 2-channel write path (chData[2], stereo jlimit pair) only stays safe
because isBusesLayoutSupported accepts mono|stereo only and processBlock
clamps chProc to <= 2. Nothing else in the repo headless-pins these guards:
a future edit that adds a third accepted layout (e.g. quad as a "feature")
or drops the input==output clause for AU, or moves/drops the per-sample
scalar dry capture, crossfades against processed samples — which the
per-sample output-chain pin (check_processblock_output_chain.py) covers only
for the crossfade/output side, not the dry-feed ordering or channel capture.

Asserts (comment-stripped, on real tree):
  (a) isBusesLayoutSupported body rejects every layout whose main OUTPUT is
      not exactly mono() or stereo(), and returns false for a mismatch
      with the INPUT set when ! JucePlugin_IsSynth (the != return line).
  (b) processBlock keeps the `numChannels == 0 || numSamples == 0` early
      return and the `std::min(numChannels, 2)` chProc clamp.
  (c) the LIVE dry feed is the scalar shape, before any DSP:
      `const float dryL = chData[0][s];` and the mono-guarded
      `const float dryR = isMono ? dryL : chData[1][s];` are captured at the
      top of the per-sample loop, before the first DSP call, and the input
      meter plus final wet/dry crossfade read those scalars. Missing dry
      input, a dropped mono guard, a capture after DSP, or modified crossfade
      math is rejected. The legacy allocating dryBuffer feed shape is still
      accepted inside the checker's fixture so its ordering probes stay
      non-vacuous, but it is rejected as the live source (a revert would
      reintroduce block-length allocation on the audio thread).
Negative self-probes on mutated in-memory texts (real tree never mutated;
no-op mutation aborts as a stale alarm): add channel guards to
isBusesLayoutSupported → rejected; negate the min to make it pass quad →
rejected; move/drop the scalar dry capture → rejected; drop the mono guard →
rejected; drop the legacy copyFrom → rejected; change the crossfade math →
rejected; drop the early return → rejected.
Benign no-op edit outside the pinned shapes → accepted (probe specificity).

Exit 0 = ok, 1 = violation with a cited diagnostic.
"""
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SRC = ROOT / "source" / "DrippyFX"
CPP = SRC / "PluginProcessor.cpp"


def fail(msg):
    print(f"BUSES-CHANNEL-GUARD FAIL: {msg}")
    sys.exit(1)


def strip_comments(src):
    src = re.sub(r"/\*.*?\*/", "", src, flags=re.S)
    src = re.sub(r"//[^\n]*", "", src)
    return src


def brace_body(text, start_idx):
    """Return substring of the brace-matched block starting at the '{' nearest
    at-or-after start_idx."""
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
    return text[i:j + 1]


def _verify(cpp_text, allow_legacy=False):
    code = strip_comments(cpp_text)

    # (a) isBusesLayoutSupported body
    m = re.search(
        r"bool\s+CorvusFXAudioProcessor::isBusesLayoutSupported\s*\(",
        code)
    if not m:
        return "isBusesLayoutSupported definition missing"
    body = brace_body(code, m.start())
    if not body:
        return "isBusesLayoutSupported body not brace-matched"
    if "juce::AudioChannelSet::mono()" not in body:
        return "isBusesLayoutSupported no longer accepts mono()"
    if "juce::AudioChannelSet::stereo()" not in body:
        return "isBusesLayoutSupported no longer accepts stereo()"
    out_conds = re.findall(
        r"getMainOutputChannelSet\(\)\s*!=\s*juce::AudioChannelSet::(\w+)\(\)",
        body)
    if set(out_conds) != {"mono", "stereo"} or len(out_conds) != 2:
        return ("isBusesLayoutSupported mono/stereo acceptance guard dropped "
                "or widened (expected EXACTLY a mono() and a stereo() output "
                f"comparison, found {out_conds})")
    if "getMainOutputChannelSet() != layouts.getMainInputChannelSet()" not in body:
        return ("isBusesLayoutSupported input==output clause dropped — "
                "an AU channel-mismatch build would feed wrong channels")

    # (b) processBlock early return + 2-channel clamp
    m = re.search(
        r"void\s+CorvusFXAudioProcessor::processBlock\s*\(", code)
    if not m:
        return "processBlock definition missing"
    body = brace_body(code, m.start())
    if not body:
        return "processBlock body not brace-matched"
    if "numChannels == 0 || numSamples == 0" not in body:
        return "processBlock early return on empty buffers dropped"
    if "std::min(numChannels, 2)" not in body:
        return "processBlock chProc clamp `std::min(numChannels, 2)` missing"

    # (c) dry feed before any DSP — scalar live shape (legacy only in fixture)
    loop = re.search(r"for\s*\(\s*int\s+s\s*=\s*0\s*;\s*s\s*<\s*numSamples", body)
    if not loop:
        return "per-sample `for (int s = 0; s < numSamples` loop not found"

    # Legacy shape: a prepared buffer feed ahead of the per-sample loop.
    feed_idx = body.find("dryBuffer.copyFrom(")
    size_guard = body.find("dryBuffer.getNumSamples()")
    if feed_idx != -1 or size_guard != -1:
        if not allow_legacy:
            return ("legacy allocating dryBuffer feed is back in processBlock "
                    "— its block-sized setSize/copy can allocate on the audio "
                    "thread; the scalar dryL/dryR capture must replace it")
        if feed_idx == -1 or feed_idx > loop.start():
            return ("dryBuffer.copyFrom feed no longer happens BEFORE the "
                    "per-sample loop — the crossfade would read zeros")
        if size_guard == -1 or size_guard > loop.start():
            return ("dryBuffer size-guard no longer happens before the "
                    "per-sample loop")

    # Current shape: scalar raw-input capture at the top of the loop. Both
    # channels are pinned, including the mono duplicate guard, and the
    # capture must precede the first DSP call and every chData write.
    dry_l = body.find("const float dryL = chData[0][s];", loop.start())
    dry_r = body.find("const float dryR = isMono ? dryL : chData[1][s];",
                      loop.start())
    if dry_l == -1 and dry_r == -1:
        if feed_idx == -1:
            return ("no dry input feed found — neither the scalar dryL/dryR "
                    "capture nor the legacy dryBuffer feed is present")
    else:
        if dry_l == -1 or dry_r == -1:
            return ("scalar dry feed incomplete — dryL must read chData[0][s] "
                    "and dryR must keep the `isMono ? dryL :` channel guard")
        if body.count("const float dryL = chData[0][s];") != 1 or \
           body.count("const float dryR = isMono ? dryL : chData[1][s];") != 1:
            return ("scalar dry feed duplicated or reshaped — dryL/dryR must "
                    "each be captured exactly once")
        if dry_l < loop.start() or dry_r < loop.start():
            return "scalar dry feed appears outside the per-sample loop"
        if dry_r < dry_l:
            return "scalar dryR capture precedes dryL — channel labels drifted"
        first_dsp = body.find("distortion.process(", loop.start())
        if first_dsp != -1 and dry_r > first_dsp:
            return ("scalar dry capture moved after the first DSP call — the "
                    "blend would read already-processed samples")
        write_l = body.find("chData[0][s] =", loop.start())
        if write_l != -1 and dry_r > write_l:
            return ("scalar dry capture moved after the chData write — the "
                    "blend would read the output, not the pristine input")
        if body.count("std::abs(dryL)") != 1 or \
           body.count("std::abs(dryR)") != 1:
            return ("input meter no longer reads the scalar dry capture — "
                    "meters would drift from the pristine input")
        if ("smpL = dryL * (1.0f - sOverall) + smpL * sOverall;"
                not in body or
                "smpR = dryR * (1.0f - sOverall) + smpR * sOverall;"
                not in body):
            return ("overall wet/dry crossfade no longer reads the scalar dry "
                    "capture with the pinned crossfade math — the dry path "
                    "would blend processed samples or a changed gain")
    return None


def main():
    if not CPP.exists():
        fail(f"missing source file {CPP}")
    cpp_raw = CPP.read_text(encoding="utf-8")
    err = _verify(cpp_raw)
    if err:
        fail(err)
    print("buses-channel-guard: mono|stereo acceptance + input==output pin, "
          "processBlock early-return + 2-ch clamp, live scalar dry capture "
          "before any DSP (legacy allocating feed rejected)")

    # The legacy dryBuffer feed stays accepted in this fixture (old-shape
    # probes), but the live tree must use the scalar capture and reject it.
    def legacy_dry_shape(cpp_text):
        legacy = cpp_text.replace(
            "        const float dryL = chData[0][s];\n"
            "        const float dryR = isMono ? dryL : chData[1][s];\n\n", "")
        legacy = legacy.replace(
            "            float inV_ = std::abs(dryL);",
            "            float inV_ = std::abs(dryBuffer.getReadPointer(0)[s]);")
        legacy = legacy.replace(
            "                float inVR_ = std::abs(dryR);",
            "                float inVR_ = std::abs(dryBuffer.getReadPointer(1)[s]);")
        legacy = legacy.replace(
            "            smpL = dryL * (1.0f - sOverall) + smpL * sOverall;\n"
            "            if (!isMono)\n"
            "                smpR = dryR * (1.0f - sOverall) + smpR * sOverall;",
            "            smpL = dryBuffer.getReadPointer(0)[s] * (1.0f - sOverall) + smpL * sOverall;\n"
            "            if (!isMono)\n"
            "                smpR = dryBuffer.getReadPointer(1)[s] * (1.0f - sOverall) + smpR * sOverall;")
        return legacy.replace(
            "    // ── Level meter accumulation (merged into main loop) ──",
            "    // Store dry signal\n"
            "    if (dryBuffer.getNumSamples() < numSamples || dryBuffer.getNumChannels() < chProc)\n"
            "        dryBuffer.setSize(chProc, numSamples, false, false, true);\n"
            "    for (int ch = 0; ch < chProc; ++ch)\n"
            "        dryBuffer.copyFrom(ch, 0, buffer, ch, 0, numSamples);\n\n"
            "    // ── Level meter accumulation (merged into main loop) ──")

    legacy = legacy_dry_shape(cpp_raw)
    if legacy == cpp_raw:
        fail("legacy dry shape fixture did not change the source")
    err = _verify(legacy, allow_legacy=True)
    if err:
        fail("legacy dryBuffer feed shape REJECTED in its own fixture — "
             f"old-shape probes lost: {err}")
    if _verify(legacy) is None:
        fail("legacy allocating dryBuffer feed is accepted as the LIVE source "
             "— reverting the scalar fix would pass the gate")
    print("buses-channel-guard: legacy feed accepted for probes but rejected "
          "as the live source")

    # negative self-probes on mutated in-memory texts (real tree never mutated)
    probes = [
        ("quad channel added to accepted output layouts",
         lambda s: s.replace(
             'layouts.getMainOutputChannelSet() != juce::AudioChannelSet::mono()',
             'layouts.getMainOutputChannelSet() != juce::AudioChannelSet::quad()\n'
             '        && layouts.getMainOutputChannelSet() != juce::AudioChannelSet::mono()')),
        ("input==output clause dropped",
         lambda s: s.replace(
             "if (layouts.getMainOutputChannelSet() != layouts.getMainInputChannelSet())",
             "if (!layouts.getMainOutputChannelSet().isDisabled())")),
        ("chProc clamp widened past 2",
         lambda s: s.replace("std::min(numChannels, 2)",
                             "std::min(numChannels, 4)")),
        ("scalar dry capture removed",
         lambda s: s.replace(
             "        const float dryL = chData[0][s];\n"
             "        const float dryR = isMono ? dryL : chData[1][s];\n\n", "")),
        ("scalar dry capture moved after DSP",
         lambda s: s.replace(
             "        const float dryL = chData[0][s];\n"
             "        const float dryR = isMono ? dryL : chData[1][s];\n\n", ""
         ).replace(
             "            smpL = dryL * (1.0f - sOverall) + smpL * sOverall;",
             "            const float dryL = chData[0][s];\n"
             "            const float dryR = isMono ? dryL : chData[1][s];\n"
             "            smpL = dryL * (1.0f - sOverall) + smpL * sOverall;")),
        ("scalar dry mono guard dropped",
         lambda s: s.replace(
             "const float dryR = isMono ? dryL : chData[1][s];",
             "const float dryR = chData[1][s];")),
        ("scalar dry channel source swapped",
         lambda s: s.replace("const float dryL = chData[0][s];",
                             "const float dryL = chData[1][s];")),
        ("overall crossfade math swapped",
         lambda s: s.replace(
             "smpL = dryL * (1.0f - sOverall) + smpL * sOverall;",
             "smpL = smpL * (1.0f - sOverall) + dryL * sOverall;")),
        ("legacy dry copy dropped",
         lambda s: legacy_dry_shape(s).replace(
             "    for (int ch = 0; ch < chProc; ++ch)\n"
             "        dryBuffer.copyFrom(ch, 0, buffer, ch, 0, numSamples);\n", "")),
        ("empty-buffer early return stripped",
         lambda s: s.replace(
             "if (numChannels == 0 || numSamples == 0) return;", "")),
    ]
    for label, mutate in probes:
        mutated = mutate(cpp_raw)
        if mutated == cpp_raw:
            fail(f"no-op probe ({label}): mutation did not change the source")
        try:
            err = _verify(mutated, allow_legacy=True)
        except Exception as e:  # defensive: brace machinery must not mask
            err = str(e)
        if err:
            print(f"buses-channel-guard: negative probe '{label}' rejected "
                  f"({err[:80]}...)")
        else:
            fail(f"negative probe '{label}' was NOT rejected — checker is "
                 f"vacuous")

    # no-op guard: benign edit outside the pinned shapes must still pass
    shifted = cpp_raw.replace(
        'params.push_back(std::make_unique<juce::AudioParameterInt>("preset", "Preset", 0, 42, 2));',
        'params.push_back(std::make_unique<juce::AudioParameterInt>("preset", "Preset" , 0, 42, 2));')
    if shifted == cpp_raw:
        fail("no-op guard: unanchored neutral edit did not change the source")
    err = _verify(shifted)
    if err:
        fail(f"neutral edit outside the pinned shapes was REJECTED — checker "
             f"over-fires: {err}")
    print("buses-channel-guard: neutral no-op edit passes (probe specificity "
          "proven)")
    print("buses-channel-guard: OK")


if __name__ == "__main__":
    main()
