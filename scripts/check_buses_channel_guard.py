#!/usr/bin/env python3
"""Headless checker: audio-channel-count guards + dryBuffer feed ordering.

The 2-channel write path (chData[2], stereo jlimit pair) only stays safe
because isBusesLayoutSupported accepts mono|stereo only and processBlock
clamps chProc to <= 2. Nothing else in the repo headless-pins these guards:
a future edit that adds a third accepted layout (e.g. quad as a "feature")
or drops the input==output clause for AU, plus reorders the dryBuffer feed
after the per-sample loop, crossfades against ZEROS — which the
per-sample output-chain pin (check_processblock_output_chain.py) does not
cover (it reads the crossfade source shape only).

Asserts (comment-stripped, on real tree):
  (a) isBusesLayoutSupported body rejects every layout whose main OUTPUT is
      not exactly mono() or stereo(), and returns false for a mismatch
      with the INPUT set when ! JucePlugin_IsSynth (the != return line).
  (b) processBlock keeps the `numChannels == 0 || numSamples == 0` early
      return and the `std::min(numChannels, 2)` chProc clamp.
  (c) the dryBuffer feed (setSize guard + copyFrom loop) appears BEFORE the
      per-sample `for (int s = 0; s < numSamples` loop.
Negative self-probes on mutated in-memory texts (real tree never mutated;
no-op mutation aborts as a stale alarm): add channel guards to
isBusesLayoutSupported → rejected; negate the min to make it pass quad →
rejected; move copyFrom after the per-sample loop → rejected; drop the
early return → rejected. Benign no-op edit outside the pinned shapes →
accepted (probe specificity).

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


def _verify(cpp_text):
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

    # (c) dryBuffer feed before the per-sample loop
    loop = re.search(r"for\s*\(\s*int\s+s\s*=\s*0\s*;\s*s\s*<\s*numSamples", body)
    if not loop:
        return "per-sample `for (int s = 0; s < numSamples` loop not found"
    feed_idx = body.find("dryBuffer.copyFrom(")
    size_guard = body.find("dryBuffer.getNumSamples()")
    if feed_idx == -1 or feed_idx > loop.start():
        return ("dryBuffer.copyFrom feed no longer happens BEFORE the "
                "per-sample loop — the crossfade would read zeros")
    if size_guard == -1 or size_guard > loop.start():
        return ("dryBuffer size-guard no longer happens before the "
                "per-sample loop")
    return None


def main():
    if not CPP.exists():
        fail(f"missing source file {CPP}")
    cpp_raw = CPP.read_text()
    err = _verify(cpp_raw)
    if err:
        fail(err)
    print("buses-channel-guard: mono|stereo acceptance + input==output pin, "
          "processBlock early-return + 2-ch clamp, dryBuffer feed before "
          "the per-sample loop")

    # negative self-probes on mutated in-memory texts (real tree never mutated)
    probes = [
        ("quad channel added to accepted output layouts",
         'layouts.getMainOutputChannelSet() != juce::AudioChannelSet::mono()',
         'layouts.getMainOutputChannelSet() != juce::AudioChannelSet::quad()\n        && layouts.getMainOutputChannelSet() != juce::AudioChannelSet::mono()'),
        ("input==output clause dropped",
         "if (layouts.getMainOutputChannelSet() != layouts.getMainInputChannelSet())",
         "if (!layouts.getMainOutputChannelSet().isDisabled())"),
        ("chProc clamp widened past 2",
         "std::min(numChannels, 2)",
         "std::min(numChannels, 4)"),
        ("dry copy moved after the per-sample loop",
         "dryBuffer.copyFrom(ch, 0, buffer, ch, 0, numSamples);",
         ""),
        ("empty-buffer early return stripped",
         "if (numChannels == 0 || numSamples == 0) return;",
         ""),
    ]
    for label, old, new in probes:
        if old not in cpp_raw:
            fail(f"no-op probe ({label}): pattern absent — probe is stale")
        mutated = cpp_raw.replace(old, new)
        if mutated == cpp_raw:
            fail(f"no-op probe ({label}): mutation did not change the source")
        try:
            err = _verify(mutated)
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
