#!/usr/bin/env python3
"""Headless checker: CV-023 instrument FX parameters must follow the smoothed
flight amount *inside* the block instead of taking one settings snapshot per
host block.

`CorvusInstrumentProcessor::processBlock` used to do:

    fxAmount.setTargetValue(...);
    flightAmount.setTargetValue(...);
    const auto settings = settingsForFlight(flightAmount.getCurrentValue());
    flightAmount.skip(buffer.getNumSamples());
    effects->distortion.beginBlock(...);   // + chorus/delay/reverb/master
    for (auto sample = 0; sample < buffer.getNumSamples(); ++sample) { ... }

The smoother moved per sample but the effects saw ONE parameter set for the
whole block, so every modulated flight/fx sweep stepped at the block boundary
(zipper noise) and the value used was the pre-skip one. The fix refreshes the
flight-derived settings, the `flightAmount` advance and the five block-scoped
`beginBlock(...)` coefficient caches once per fixed sub-chunk (32 samples,
~0.73 ms at 44.1 kHz), inside the existing per-sample loop:

    auto fxChunkRemaining = 0;
    InstrumentEffectsSettings settings {};
    for (auto sample = 0; sample < buffer.getNumSamples(); ++sample)
    {
        ... pristine per-sample dry capture, unchanged ...
        if (fxChunkRemaining == 0)
        {
            fxChunkRemaining = juce::jmin(
                fxParameterChunkSize, buffer.getNumSamples() - sample);
            settings = settingsForFlight(flightAmount.getCurrentValue());
            flightAmount.skip(fxChunkRemaining);
            effects->distortion.beginBlock(...);   // + chorus/delay/reverb/master
        }
        --fxChunkRemaining;
        ... per-sample DSP and dry/wet blend, unchanged ...
    }

The chunk head sits after the pristine dry capture (check_instrument_dry_capture
pins the capture ahead of every `effects->...` call) and before the DSP chain,
so the capture, sample order, denormal guard and channel clearing are untouched.

Asserts (comment-stripped, whitespace-flattened, brace-matched processBlock):
  (a) the two `setTargetValue(...)` seeds stay before the per-sample loop, and
      NO `settingsForFlight(`, `flightAmount.skip(` or `.beginBlock(` may run
      before it - that is exactly the one-snapshot-per-block shape;
  (b) inside the per-sample loop there is exactly one `settingsForFlight(`
      and exactly one `flightAmount.skip(`, both inside the chunk head
      `if (fxChunkRemaining == 0) { ... }`, which also assigns the chunk
      length as `juce::jmin(fxParameterChunkSize, buffer.getNumSamples() -
      sample)` (the last chunk is clamped to the block end);
  (c) the chunk head snapshots with `getCurrentValue()` (the pre-skip value,
      matching the old convention) and `flightAmount` is never advanced with
      `getNextValue()`/`getTargetValue()` inside the loop - the ONLY advance
      in the file is the per-chunk `skip(fxChunkRemaining)`, so the smoother
      advances by exactly the summed chunk length;
  (d) the five beginBlock calls (distortion -> chorus -> delay -> reverb ->
      master) appear once, in DSP order, inside the chunk head AFTER the
      snapshot + skip, and nowhere else in the loop (a mid-stream or
      once-per-block cache recompute is rejected);
  (e) `--fxChunkRemaining;` appears exactly once, after the head and before
      the first per-sample DSP call, so the head runs once per chunk;
  (f) the per-sample wet path is untouched (`wet = fxAmount.getNextValue()`).

Behavioural model (parsed from the source, not hard-coded): the chunk counter
is simulated with `chunk = <fxParameterChunkSize>` and
`len = min(chunk, n - sample)` for several block sizes. A 512-sample block must
produce >= 2 chunk heads (so beginBlock values are recomputed inside the
block) and the summed chunk lengths must equal the block length exactly (so
`flightAmount` lands on the same value the old single `skip(n)` produced).

Self-probes (negative checks, sibling checker style) run on mutated in-memory
TEMP texts - the real tree is never mutated. A no-op mutation guard fails on a
stale probe. The pre-fix shape is rebuilt from the live text and must be
rejected.

Exit 0 = ok, 1 = violation with a cited diagnostic.
"""
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SRC = (ROOT / "source" / "DrippyFX" / "instrument"
       / "CorvusInstrumentProcessor.cpp")

CHUNK_CONST_RE = re.compile(
    r"constexpr\s+int\s+fxParameterChunkSize\s*=\s*(\d+)\s*;")
LOOP_RE = re.compile(
    r"for\s*\(\s*auto\s+sample\s*=\s*0\s*;\s*sample\s*<\s*"
    r"buffer\s*\.\s*getNumSamples\s*\(\s*\)\s*;\s*\+\+\s*sample\s*\)")
HEAD_RE = re.compile(r"if\s*\(\s*fxChunkRemaining\s*==\s*0\s*\)\s*\{")
CHUNK_LEN_RE = re.compile(
    r"fxChunkRemaining\s*=\s*juce::jmin\s*\(\s*fxParameterChunkSize\s*,\s*"
    r"buffer\s*\.\s*getNumSamples\s*\(\s*\)\s*-\s*sample\s*\)\s*;")
SKIP_RE = re.compile(
    r"flightAmount\s*\.\s*skip\s*\(\s*fxChunkRemaining\s*\)\s*;")
SNAPSHOT_RE = re.compile(
    r"settings\s*=\s*settingsForFlight\s*\(\s*flightAmount\s*\.\s*"
    r"getCurrentValue\s*\(\s*\)\s*\)\s*;")
DECREMENT_RE = re.compile(r"--\s*fxChunkRemaining\s*;")

BEGIN_BLOCK_ORDER = [
    "effects->distortion.beginBlock(",
    "effects->chorus.beginBlock(",
    "effects->delay.beginBlock(",
    "effects->reverb.beginBlock(",
    "effects->master.beginBlock(",
]

WET_ANCHOR = "const auto wet = fxAmount.getNextValue();"

# Bound on the refresh granularity. A chunk of a whole 512-sample block is not
# a sub-chunk; it is also rejected by the ">= 2 chunk heads" rule below.
MAX_CHUNK = 512

# Exact live-text fragments used by the pre-fix fixture and the probes.
DECL_FRAGMENT = (
    "    auto fxChunkRemaining = 0;\n"
    "    InstrumentEffectsSettings settings {};\n\n")

CHUNK_HEAD_FRAGMENT = (
    "        if (fxChunkRemaining == 0)\n"
    "        {\n"
    "            fxChunkRemaining = juce::jmin(\n"
    "                fxParameterChunkSize, buffer.getNumSamples() - sample);\n"
    "            settings = settingsForFlight(flightAmount.getCurrentValue());\n"
    "            flightAmount.skip(fxChunkRemaining);\n"
    "\n"
    "            effects->distortion.beginBlock(settings.distortionAmount);\n"
    "            effects->chorus.beginBlock(\n"
    "                settings.chorusDepth, settings.chorusMix, settings.chorusRate);\n"
    "            effects->delay.beginBlock(settings.delayDamping);\n"
    "            effects->reverb.beginBlock(\n"
    "                settings.reverbSize, settings.reverbDamping, settings.reverbMix,\n"
    "                settings.reverbModulation, 1.0f, 5.0f + settings.reverbSize * 40.0f);\n"
    "            effects->master.beginBlock();\n"
    "        }\n"
    "        --fxChunkRemaining;\n"
    "\n")

PREFIX_SHAPE_FRAGMENT = (
    "    const auto settings = settingsForFlight(flightAmount.getCurrentValue());\n"
    "    flightAmount.skip(buffer.getNumSamples());\n"
    "\n"
    "    effects->distortion.beginBlock(settings.distortionAmount);\n"
    "    effects->chorus.beginBlock(\n"
    "        settings.chorusDepth, settings.chorusMix, settings.chorusRate);\n"
    "    effects->delay.beginBlock(settings.delayDamping);\n"
    "    effects->reverb.beginBlock(\n"
    "        settings.reverbSize, settings.reverbDamping, settings.reverbMix,\n"
    "        settings.reverbModulation, 1.0f, 5.0f + settings.reverbSize * 40.0f);\n"
    "    effects->master.beginBlock();\n"
    "\n")


class _Rejected(Exception):
    pass


def fail(msg):
    print("CV023-FX-SMOOTHING FAIL: %s" % msg)
    sys.exit(1)


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
        code)
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


def parse_chunk_size(code):
    m = CHUNK_CONST_RE.search(code)
    if not m:
        raise _Rejected(
            "chunk constant `constexpr int fxParameterChunkSize = <n>;` not "
            "found - the sub-chunk refresh granularity is not declared")
    n = int(m.group(1))
    if n <= 0:
        raise _Rejected(
            "fxParameterChunkSize must be a positive sample count, got %d" % n)
    if n > MAX_CHUNK:
        raise _Rejected(
            "fxParameterChunkSize = %d is larger than the %d-sample cap - the "
            "FX parameters would step once per host block again"
            % (n, MAX_CHUNK))
    return n


def simulate_chunks(num_samples, chunk):
    """Mirror the source counter: head when remaining == 0, then decrement."""
    remaining = 0
    heads = 0
    advanced = 0
    for sample in range(num_samples):
        if remaining == 0:
            remaining = min(chunk, num_samples - sample)
            advanced += remaining
            heads += 1
        remaining -= 1
    return heads, advanced


def _verify(cpp_text):
    """Raise _Rejected on a violation; return evidence when the shape is ok."""
    code = strip_comments(cpp_text)
    if "CorvusInstrumentProcessor" not in code:
        raise _Rejected("CorvusInstrumentProcessor not found in source")

    body = extract_fn(code, "CorvusInstrumentProcessor", "processBlock")
    if body is None:
        raise _Rejected(
            "CorvusInstrumentProcessor::processBlock body not found/"
            "brace-matched")
    flat = re.sub(r"\s+", " ", body)

    chunk = parse_chunk_size(code)

    loop = LOOP_RE.search(flat)
    if not loop:
        raise _Rejected(
            "per-sample loop `for (auto sample = 0; sample < "
            "buffer.getNumSamples(); ++sample)` not found in processBlock")
    loop_open = flat.find("{", loop.end())
    if loop_open == -1:
        raise _Rejected("per-sample loop has no body brace")
    loop_end = brace_span(flat, loop_open)
    if loop_end == -1:
        raise _Rejected("per-sample loop body braces unbalanced")
    pre = flat[:loop.start()]
    in_loop = flat[loop_open + 1:loop_end]
    if len(in_loop) < 500:
        raise _Rejected(
            "per-sample loop body is only %d chars - loop detection drifted; "
            "do not trust green" % len(in_loop))

    # (a) block-scope seeds stay, and the one-snapshot-per-block shape is gone.
    if "fxAmount.setTargetValue(" not in pre:
        raise _Rejected(
            "`fxAmount.setTargetValue(...)` block seed missing before the "
            "per-sample loop")
    if "flightAmount.setTargetValue(" not in pre:
        raise _Rejected(
            "`flightAmount.setTargetValue(...)` block seed missing before the "
            "per-sample loop")
    if "settingsForFlight(" in pre:
        raise _Rejected(
            "one-snapshot-per-block shape: settingsForFlight() is evaluated "
            "before the per-sample loop, so the FX parameters step once per "
            "host block instead of following the smoother inside the block")
    if "flightAmount.skip(" in pre:
        raise _Rejected(
            "flightAmount.skip() before the per-sample loop - the smoother "
            "would be advanced once per block instead of once per chunk")
    if ".beginBlock(" in pre:
        raise _Rejected(
            "beginBlock() before the per-sample loop - the block-scoped FX "
            "coefficient caches would be computed once per host block, not "
            "once per chunk")

    # (b) exactly one snapshot + one advance, both inside the chunk head.
    if in_loop.count("settingsForFlight(") != 1:
        raise _Rejected(
            "expected exactly one settingsForFlight() inside the per-sample "
            "loop (the per-chunk snapshot), found %d"
            % in_loop.count("settingsForFlight("))
    if in_loop.count("flightAmount.skip(") != 1:
        raise _Rejected(
            "expected exactly one flightAmount.skip() inside the per-sample "
            "loop (the per-chunk advance), found %d"
            % in_loop.count("flightAmount.skip("))
    if code.count("flightAmount.skip(") != 1:
        raise _Rejected(
            "flightAmount.skip() must appear exactly once in the whole "
            "processor (the chunk head), found %d - a second advance site "
            "would break the summed-chunk-length invariant"
            % code.count("flightAmount.skip("))

    # (c) no per-chunk ramp consumption besides skip().
    if "flightAmount.getNextValue(" in in_loop:
        raise _Rejected(
            "flightAmount.getNextValue() inside the per-sample loop consumes "
            "an extra smoothing step per call - the only advance must be "
            "skip(<chunk length>) in the chunk head")
    if "flightAmount.getTargetValue(" in in_loop:
        raise _Rejected(
            "flightAmount.getTargetValue() inside the per-sample loop "
            "re-reads the unsmoothed target per chunk - the chunk snapshot "
            "must use getCurrentValue() (the pre-skip smoothed value)")

    head = HEAD_RE.search(in_loop)
    if not head:
        raise _Rejected(
            "chunk head `if (fxChunkRemaining == 0) { ... }` not found inside "
            "the per-sample loop - the FX settings are not refreshed per "
            "sub-chunk")
    head_open = head.end() - 1
    head_end = brace_span(in_loop, head_open)
    if head_end == -1:
        raise _Rejected("chunk head braces unbalanced")
    head_region = in_loop[head_open + 1:head_end]

    # Chunk length must be clamped to the block end (last chunk shorter).
    if not CHUNK_LEN_RE.search(head_region):
        raise _Rejected(
            "chunk length must be assigned as `fxChunkRemaining = "
            "juce::jmin(fxParameterChunkSize, buffer.getNumSamples() - "
            "sample);` in the chunk head - a fixed length would overrun the "
            "block and advance the smoother past the block length")
    skip = SKIP_RE.search(head_region)
    if not skip:
        raise _Rejected(
            "`flightAmount.skip(fxChunkRemaining);` missing from the chunk "
            "head - the smoother advance must equal the chunk length")
    snap = SNAPSHOT_RE.search(head_region)
    if not snap:
        raise _Rejected(
            "chunk head must snapshot `settings = settingsForFlight("
            "flightAmount.getCurrentValue());` (per-chunk, pre-skip value)")
    if "getNextValue" in head_region:
        raise _Rejected(
            "getNextValue() inside the chunk head consumes an extra smoothing "
            "step per chunk - use getCurrentValue() and skip(chunk length)")
    if snap.start() > skip.start():
        raise _Rejected(
            "chunk snapshot must precede the smoother advance (the value "
            "used must be the pre-skip smoothed value, as before)")

    # (d) five beginBlock calls, DSP order, once, after snapshot + skip.
    for name in BEGIN_BLOCK_ORDER:
        if name not in head_region:
            raise _Rejected(
                "%s missing from the chunk head - a block-scoped FX "
                "coefficient cache would be stale for the whole block" % name)
    positions = [head_region.find(name) for name in BEGIN_BLOCK_ORDER]
    if positions != sorted(positions):
        raise _Rejected(
            "beginBlock calls out of DSP order in the chunk head "
            "(found at %s)" % positions)
    if positions[0] < skip.start():
        raise _Rejected(
            "beginBlock calls must run AFTER the chunk snapshot and smoother "
            "advance - otherwise the coefficient cache uses stale parameters")
    if in_loop.count(".beginBlock(") != len(BEGIN_BLOCK_ORDER):
        raise _Rejected(
            "found %d beginBlock() calls in the per-sample loop; expected "
            "exactly %d, all inside the chunk head (a call outside the head "
            "recomputes a block-scoped cache mid-stream or only once per "
            "block)" % (in_loop.count(".beginBlock("),
                        len(BEGIN_BLOCK_ORDER)))

    # (e) the counter must decrement exactly once per sample, before the DSP.
    decrement = DECREMENT_RE.search(in_loop)
    if not decrement:
        raise _Rejected(
            "`--fxChunkRemaining;` missing from the per-sample loop - the "
            "chunk head would run on every sample")
    if in_loop.count("--fxChunkRemaining") != 1:
        raise _Rejected(
            "`--fxChunkRemaining` must appear exactly once per sample, found "
            "%d decrements" % in_loop.count("--fxChunkRemaining"))
    if decrement.start() < head_end:
        raise _Rejected(
            "the chunk countdown sits inside the chunk head - it must run "
            "once per sample after the head")
    first_dsp = in_loop.find("effects->distortion.process(")
    if first_dsp == -1:
        raise _Rejected(
            "per-sample `effects->distortion.process(` call not found - the "
            "chunk countdown cannot be located relative to the DSP chain")
    if decrement.start() > first_dsp:
        raise _Rejected(
            "the chunk countdown must run before the per-sample DSP chain")

    # (f) the per-sample wet path is untouched.
    if WET_ANCHOR not in in_loop:
        raise _Rejected(
            "per-sample `wet = fxAmount.getNextValue()` missing - the "
            "fx_amount blend must stay per-sample")

    # (g) behavioural model: chunk heads >= 2 for 512 samples and the summed
    # chunk lengths exactly cover every block length (smoother advance == n).
    heads_512, advanced_512 = simulate_chunks(512, chunk)
    if heads_512 < 2:
        raise _Rejected(
            "with fxParameterChunkSize = %d a 512-sample block gets only %d "
            "chunk head(s) - beginBlock values would be computed once per "
            "block again" % (chunk, heads_512))
    for num_samples in (512, 480, 100, 33, 1):
        heads, advanced = simulate_chunks(num_samples, chunk)
        expected_heads = -(-num_samples // chunk)
        if heads != expected_heads:
            raise _Rejected(
                "chunk model: %d samples should take %d heads, got %d"
                % (num_samples, expected_heads, heads))
        if advanced != num_samples:
            raise _Rejected(
                "chunk model: summed chunk lengths = %d for a %d-sample "
                "block - flightAmount would advance by %d instead of %d"
                % (advanced, num_samples, advanced, num_samples))
    return chunk, heads_512, advanced_512


def run_text(cpp_text):
    try:
        return _verify(cpp_text), None
    except _Rejected as r:
        return None, str(r)


def build_prefix_shape(text):
    """Rebuild the pre-fix one-snapshot-per-block text from the live text."""
    t = text.replace(DECL_FRAGMENT, PREFIX_SHAPE_FRAGMENT, 1)
    if t == text:
        return None
    t2 = t.replace(CHUNK_HEAD_FRAGMENT, "", 1)
    if t2 == t:
        return None
    return t2


def normalise_newlines(text):
    """Mutate a line-ending-normalised copy so probes work on CRLF checkouts."""
    return text.replace("\r\n", "\n").replace("\r", "\n")


def main():
    if not SRC.exists():
        fail("missing source file %s" % SRC)
    text = normalise_newlines(SRC.read_text(encoding="utf-8"))

    evidence, verdict = run_text(text)
    if verdict is not None:
        fail(verdict)
    chunk, heads, advanced = evidence
    print("cv023-fx-smoothing: chunk=%d samples; a 512-sample block runs %d "
          "chunk heads and the smoother advances %d/512 samples"
          % (chunk, heads, advanced))
    print("cv023-fx-smoothing: settingsForFlight() + all 5 beginBlock() calls "
          "are recomputed once per chunk inside the per-sample loop")

    # The pre-fix shape must be rejected, not silently accepted.
    legacy = build_prefix_shape(text)
    if legacy is None:
        fail("pre-fix fixture did not change the source - fixture is stale")
    verdict = run_text(legacy)[1]
    if verdict is None:
        fail("the one-snapshot-per-block shape (settingsForFlight + "
             "skip(numSamples) + beginBlock fan hoisted before the loop) is "
             "accepted as the LIVE shape - a revert would pass the gate")
    print("cv023-fx-smoothing: one-snapshot-per-block shape rejected (%s...)"
          % verdict[:72])

    probes = [
        ("chunk constant widened to the whole 512-sample block (one head)",
         "constexpr int fxParameterChunkSize = 32;",
         "constexpr int fxParameterChunkSize = 512;"),
        ("chunk constant widened past the sub-chunk cap",
         "constexpr int fxParameterChunkSize = 32;",
         "constexpr int fxParameterChunkSize = 1024;"),
        ("smoother advanced by the whole block instead of the chunk length",
         "flightAmount.skip(fxChunkRemaining);",
         "flightAmount.skip(buffer.getNumSamples());"),
        ("chunk snapshot deleted from the chunk head",
         "            settings = settingsForFlight(flightAmount.getCurrentValue());\n",
         ""),
        ("chunk snapshot reads the unsmoothed target",
         "settings = settingsForFlight(flightAmount.getCurrentValue());",
         "settings = settingsForFlight(flightAmount.getTargetValue());"),
        ("chunk countdown deleted (head runs every sample)",
         "        --fxChunkRemaining;\n",
         ""),
        ("master beginBlock dropped from the chunk head",
         "            effects->master.beginBlock();\n",
         ""),
        ("last-chunk clamp removed from the chunk length",
         "            fxChunkRemaining = juce::jmin(\n"
         "                fxParameterChunkSize, buffer.getNumSamples() - sample);",
         "            fxChunkRemaining = fxParameterChunkSize;"),
        ("beginBlock fan hoisted before the per-sample loop",
         "    for (auto sample = 0; sample < buffer.getNumSamples(); ++sample)\n"
         "    {\n",
         "    effects->master.beginBlock();\n"
         "    for (auto sample = 0; sample < buffer.getNumSamples(); ++sample)\n"
         "    {\n"),
    ]
    for label, old, new in probes:
        mutated = text.replace(old, new, 1)
        if mutated == text:
            fail("no-op probe (%s): mutation did not change the source - the "
                 "negative check is vacuous" % label)
        verdict = run_text(mutated)[1]
        if verdict is None:
            fail("negative probe '%s' was NOT rejected - checker is vacuous"
                 % label)
        print("cv023-fx-smoothing: negative probe '%s' rejected (%s...)"
              % (label, verdict[:72]))

    # No-op guard: a benign comment edit must stay accepted.
    neutral = text.replace(
        "    auto fxChunkRemaining = 0;",
        "    // benign probe comment\n    auto fxChunkRemaining = 0;", 1)
    if neutral == text:
        fail("no-op guard: benign edit did not change the source - probe is "
             "stale")
    verdict = run_text(neutral)[1]
    if verdict is not None:
        fail("benign comment edit was REJECTED - checker over-fires: %s"
             % verdict)
    print("cv023-fx-smoothing: benign comment edit passes (probe specificity "
          "proven)")

    # The real tree is never mutated; re-verify the untouched source once more.
    if run_text(normalise_newlines(SRC.read_text(encoding="utf-8")))[1] is not None:
        fail("final live-source re-verification failed")
    print("CV023-FX-SMOOTHING OK")
    return 0


if __name__ == "__main__":
    sys.exit(main())
