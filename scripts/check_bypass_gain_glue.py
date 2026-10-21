#!/usr/bin/env python3
"""Headless checker: click-free bypass-crossfade gain glue in plugin code.

The per-block bypass reads (`distortion_bypass` etc. via `->load() > 0.5f`)
are mapped into juce::LinearSmoothedValue bypassGain* targets in BOTH bodies:

  - prepareToPlay: bypassGainX.reset(sampleRate, bypassTime) then
    bypassGainX.setTargetValue(bX) where bX keeps the inverted literal
    `<bool> > 0.5f ? 0.0f : 1.0f` (so a stored "bypassed" state initializes
    the smoother at 0.0 = dry);
  - processBlock: bypassGainX.setTargetValue(<bool> ? 0.0f : 1.0f) right
    after the 5 bool reads.

Nothing else in the repo headless-pins this glue: check_raw_param_ids.py
pins only the boolean read form, and the output-chain checker pins the
per-sample crossfade READ side. A future edit that swaps 0.0f/1.0f in
either the bool→gain map or the prepare init, drops one body's
bypassGainX.setTargetValue ("simplification"), or removes a prepare-side
reset() makes a bypass toggle click or mute a module silently, while the
existing pins stay green.

Asserts on the real tree (comment-stripped where noted):
  (a) prepareToPlay keeps, for each of the 5 modules: a
      bypassGainX.reset(sampleRate, bypassTime) AND a
      bypassGainX.setTargetValue(bX) (raw, non-comment-stripped so
      whitespace-insensitive regexes fire), plus the inverted `bDist =
      ... > 0.5f ? 0.0f : 1.0f` literal forms;
  (b) the processBlock update region keeps, after the 5 bool reads, the 5
      `bypassGainX.setTargetValue(<bool> ? 0.0f : 1.0f)` lines;
  (c) all 5 bypassGain members are declared exactly once in
      PluginProcessor.h.

Negative self-probes on mutated in-memory texts (real tree never mutated;
no-op mutation aborts as a stale alarm): swap 0.0f/1.0f in the
processBlock map → rejected; drop one bypassGain setTargetValue →
rejected; strip a prepare reset → rejected. Benign no-op edit outside the
pinned shapes → accepted (probe specificity).

Exit 0 = ok, 1 = violation with a cited diagnostic.
"""
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SRC = ROOT / "source" / "DrippyFX"
CPP = SRC / "PluginProcessor.cpp"
H = SRC / "PluginProcessor.h"

MODULES = (
    ("Dist", "distortion_bypass", "distortionBypass", "bDist"),
    ("Chorus", "chorus_bypass", "chorusBypass", "bChor"),
    ("Delay", "delay_bypass", "delayBypass", "bDel"),
    ("Reverb", "reverb_bypass", "reverbBypass", "bRev"),
    ("Master", "master_bypass", "masterBypass", "bMast"),
)


def fail(msg):
    print(f"BYPASS-GAIN-GLUE FAIL: {msg}")
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


def _verify(cpp_text, h_text):
    code = strip_comments(cpp_text)

    prepare = extract_fn(code, "prepareToPlay")
    if not prepare:
        return "prepareToPlay body not found/brace-matched"
    block = extract_fn(code, "processBlock")
    if not block:
        return "processBlock body not found/brace-matched"

    for suffix, pid, boolname, bvar in MODULES:
        # (a) prepare side: inverted-literal seed + reset + setTargetValue
        seed = re.search(
            r"\b%s\s*=\s*apvts\.getRawParameterValue\(\"%s\"\)->load\(\)\s*>"
            r"\s*0\.5f\s*\?\s*0\.0f\s*:\s*1\.0f" % (bvar, pid),
            prepare,
        )
        if not seed:
            return ("prepareToPlay inverted bypass seed literal missing for "
                    "%s (`> 0.5f ? 0.0f : 1.0f`), or literal orientation "
                    "changed — a stored bypassed state would init wet" % pid)
        if "bypassGain%s.reset(sampleRate, bypassTime)" % suffix not in \
                prepare:
            return ("prepareToPlay no longer calls bypassGain%s.reset — "
                    "bypass crossfade loses its 30ms ramp on a re-prepare"
                    % suffix)
        if "bypassGain%s.setTargetValue(%s)" % (suffix, bvar) not in \
                prepare:
            return "prepareToPlay bypassGain%s glue missing" % suffix

        # (b) processBlock side: bool read then target map, in order
        bool_read = re.search(
            r"bool\s+%s\s*=\s*apvts\.getRawParameterValue\(\"%s\"\)->load\(\)"
            r"\s*>\s*0\.5f" % (boolname, pid),
            block,
        )
        if not bool_read:
            return ("processBlock boolean bypass read lost its "
                    "`> 0.5f` gate for %s" % pid)
        after = block[bool_read.end():]
        target = re.search(
            r"bypassGain%s\.setTargetValue\(\s*%s\s*\?\s*0\.0f\s*:\s*1\.0f"
            % (suffix, boolname),
            after,
        )
        if not target:
            return ("processBlock bypassGain%s.setTargetValue "
                    "`<bool> ? 0.0f : 1.0f` map missing or not after the "
                    "bool read — 0.0f/1.0f swap, dropped glue, or "
                    "reordering" % suffix)

    # (c) header declarations
    for suffix, _, _ , _ in MODULES:
        n = len(re.findall(
            r"\bjuce::LinearSmoothedValue<float>\s+bypassGain%s\s*;" % suffix,
            strip_comments(h_text)))
        if n != 1:
            return ("header must declare bypassGain%s exactly once, found %d"
                    % (suffix, n))
    return None


def main():
    if not CPP.exists():
        fail(f"missing source file {CPP}")
    if not H.exists():
        fail(f"missing header file {H}")
    cpp_raw = CPP.read_text(encoding="utf-8")
    h_raw = H.read_text(encoding="utf-8")
    err = _verify(cpp_raw, h_raw)
    if err:
        fail(err)
    print("bypass-gain-glue: 5 inverted prepare seeds, 5 prepare "
          "reset+setTargetValue, 5 processBlock `? 0.0f : 1.0f` maps, 5 "
          "header members")

    probe2_old = ("    bypassGainChorus.setTargetValue(chorusBypass "
                  "? 0.0f : 1.0f);")
    probes = [
        ("processBlock 0.0f/1.0f swap (Dist)",
         "bypassGainDist.setTargetValue(distortionBypass ? 0.0f : 1.0f);",
         "bypassGainDist.setTargetValue(distortionBypass ? 1.0f : 0.0f);"),
        ("one processBlock setTargetValue dropped", probe2_old, ""),
        ("prepare reset stripped (Delay)",
         "bypassGainDelay.reset(sampleRate, bypassTime);  "
         "bypassGainDelay.setTargetValue(bDel);",
         "bypassGainDelay.setTargetValue(bDel);"),
    ]

    for label, old, new in probes:
        if old not in cpp_raw:
            fail(f"no-op probe ({label}): pattern absent — probe is stale")
        mutated = cpp_raw.replace(old, new)
        if mutated == cpp_raw:
            fail(f"no-op probe ({label}): mutation did not change the source")
        try:
            err = _verify(mutated, h_raw)
        except Exception as e:  # defensive: probe machinery must not mask
            err = str(e)
        if err:
            print(f"bypass-gain-glue: negative probe '{label}' rejected "
                  f"({err[:80]}...)")
        else:
            fail(f"negative probe '{label}' was NOT rejected — checker is "
                 f"vacuous")

    # no-op guard: benign edit outside the pinned shapes must still pass
    shifted = cpp_raw.replace(
        'const double bypassTime = 0.03;',
        'const double bypassTime = -0.0 + 0.03;')
    if shifted == cpp_raw:
        fail("no-op guard: unanchored neutral edit did not change the source")
    err = _verify(shifted, h_raw)
    if err:
        fail(f"neutral edit outside the pinned shapes was REJECTED — checker "
             f"over-fires: {err}")
    print("bypass-gain-glue: neutral no-op edit passes (probe specificity "
          "proven)")
    print("bypass-gain-glue: OK")


if __name__ == "__main__":
    main()
