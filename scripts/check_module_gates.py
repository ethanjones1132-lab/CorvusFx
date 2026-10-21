#!/usr/bin/env python3
"""Headless checker: per-module DSP-enable gate conjunctions pin.

The 5 per-sample `if` guards that decide whether each module's process
body runs (source/DrippyFX/PluginProcessor.cpp:702-711, :721-732) have no
headless pin: an edit dropping one conjunct — deleting
`&& sDelayTime > 0.0f` — lets the DSP engine run with its knob at zero
(per-sample CPU burn while the user hears pure bypass, and the
delay/reverb internal state keeps evolving), and a removed gX test makes
the crossfade read an always-on wet path — all compile clean behind an
otherwise-green gate.

Asserts (comment-stripped, brace-matched processBlock body):
  (a) the 5 gate conditions appear verbatim, each PRECEDING its DSP call
      site in the body order:
      distortion:    gDist > 0.001f && sFatness > 0.001f
      chorus:        gChorus > 0.001f && sChorusDepth > 0.001f
      delay:         gDelay > 0.001f && sDelayMix > 0.001f && sDelayTime > 0.0f
      reverb:        gReverb > 0.001f && sReverbMix > 0.001f
      master:        gMaster > 0.001f
  (b) each gate's crossfade (smpX = smpX * (1.0f - gX) + outX * gX)
      stays INSIDE the gate body (move one gate after its crossfade ->
      the DSP call runs uncrossfaded).

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

# (module, full gate condition text comment-stripped, DSP call fragment,
#  crossfade left/right variable names)
MODULES = [
    ("distortion",
     "gDist > 0.001f && sFatness > 0.001f",
     "distortion.process("),
    ("chorus",
     "gChorus > 0.001f && sChorusDepth > 0.001f",
     "chorus.process(smpL, 0"),
    ("delay",
     "gDelay > 0.001f && sDelayMix > 0.001f && sDelayTime > 0.0f",
     "delay.processSample("),
    ("reverb",
     "gReverb > 0.001f && sReverbMix > 0.001f",
     "upgradedReverb.processSample("),
    ("master",
     "gMaster > 0.001f",
     "masterOutput.process("),
]


def fail(msg):
    print(f"MODULE-GATES FAIL: {msg}")
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


def brace_slice(txt, open_idx):
    depth, j = 0, open_idx
    while j < len(txt):
        if txt[j] == "{": depth += 1
        elif txt[j] == "}":
            depth -= 1
            if depth == 0: break
        j += 1
    if depth != 0:
        return None
    return txt[open_idx:j + 1]


def check(body):
    """Return None if ok, else a diagnostic string."""
    cursor = 0
    for name, gate, call in MODULES:
        gate_re = re.escape(collapse_ws(gate))
        m = re.search(gate_re, body[cursor:])
        if not m:
            return f"{name} gate `{collapse_ws(gate)}` not found in the " \
                   f"per-sample body (expected order: " \
                   f"distortion, chorus, delay, reverb, master; cursor " \
                   f"at {cursor})"
        gate_start = cursor + m.start()
        ib = body.find("{", cursor + m.end() - 1)
        if ib == -1:
            return f"{name} gate has no opening brace"
        gb = brace_slice(body, ib)
        if gb is None:
            return f"unbalanced braces in the {name} gate body"
        # (b) the module's DSP call and its crossfade must be INSIDE the gate
        cm = re.search(re.escape(call), gb)
        if not cm:
            return f"{name} DSP call `{call}` not found inside its gate body " \
                   f"(a removed gX test or hoisted call makes the crossfade " \
                   f"read an always-on wet path / uncrossfaded DSP)"
        # crossfade: find a share of the gX backend, e.g. gDist
        gvar = gate.split(">")[0].strip()
        xf = gb.find(f"1.0f - {gvar}")
        if xf == -1:
            return f"{name} crossfade (`1.0f - {gvar}`) not found inside " \
                   f"the gate body"
        if xf < cm.end():
            return f"{name} crossfade must come AFTER the DSP call inside " \
                   f"the gate"
        cursor = cursor + m.end()
    return None


proc_c_path = SRC / "PluginProcessor.cpp"
if not proc_c_path.exists():
    fail(f"missing source file {proc_c_path}")
proc_c = proc_c_path.read_text(encoding="utf-8")

body = extract_body(proc_c, "processBlock")
err = check(body)
if err:
    fail(err + " (PluginProcessor.cpp processBlock)")
print("module-gates: the 5 DSP-enable gate conjunctions pinned verbatim, "
      "each preceding its DSP call + crossfade inside the gate body")

# ---------------------------------------------------------------------------
# Self-probes on mutated in-memory texts (real tree never mutated)
# ---------------------------------------------------------------------------

def probe(description, old, new, count=1):
    tmp = proc_c.replace(old, new, count)
    if tmp == proc_c:
        print(f"module-gates: no-op mutation guard -> skipping invalid "
              f"probe ({description})")
        return
    err = check(extract_body(tmp, "processBlock"))
    if err is None:
        print(f"module-gates: SELF-PROBE FAIL (checker should reject): "
              f"{description}")
        sys.exit(1)
    print(f"module-gates: self-probe fired: {description} -> rejected")


# 1. drop the sFatness conjunct (distortion runs with knob at zero)
probe("distortion gate sFatness conjunct dropped",
      "gDist > 0.001f && sFatness > 0.001f",
      "gDist > 0.001f")

# 2. drop the sDelayTime > 0.0f clause (delay runs at zero time)
probe("delay gate sDelayTime > 0.0f clause dropped",
      "gDelay > 0.001f && sDelayMix > 0.001f && sDelayTime > 0.0f",
      "gDelay > 0.001f && sDelayMix > 0.001f")

# 3. move the delay gate AFTER its crossfade (call runs uncrossfaded)
delay_if = next(l for l in proc_c.splitlines()
                if "sDelayMix > 0.001f && sDelayTime > 0.0f" in l)
# locate the delay crossfade last line and append the gate there
xf_line = next(l for l in proc_c.splitlines()
               if "(1.0f - gDelay) + dR * gDelay" in l)
tmp = proc_c.replace(delay_if, "", 1)
tmp = tmp.replace(xf_line,
                  xf_line + "\n" + delay_if.replace("\n", ""), 1)
if tmp != proc_c:
    desc = "delay gate moved after its crossfade"
    err = check(extract_body(tmp, "processBlock"))
    if err is None:
        print(f"module-gates: SELF-PROBE FAIL (checker should reject): {desc}")
        sys.exit(1)
    print(f"module-gates: self-probe fired: {desc} -> rejected")
else:
    print("module-gates: no-op mutation guard -> skipping gate-move probe")

# 4. no-op guard: benign comment addition inside the per-sample body must
#    stay accepted
anchor = delay_if
tmp5 = proc_c.replace(anchor, "// benign probe edit\n" + anchor, 1)
if tmp5 == proc_c:
    print("module-gates: no-op probe skipped")
elif check(extract_body(tmp5, "processBlock")) is not None:
    fail("no-op guard: benign edit was wrongly rejected")
print("module-gates: no-op guard passed (benign edit accepted)")

print("MODULE-GATES OK")
