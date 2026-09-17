#!/usr/bin/env python3
"""Headless checker: chorus per-sample voice-call pair pin.

processBlock (source/DrippyFX/PluginProcessor.cpp:665) derives
`const float sChorusFb = sChorusDepth * 0.25f;` and (:713-717) calls
`float cl = chorus.process(smpL, 0, sChorusRate, sChorusDepth, sChorusFb);`
then `float cr = chorus.process(smpR, 1, sChorusRate, sChorusDepth,
sChorusFb);` with `chorus.advanceWritePos();` last inside the chorus gate.
No other checker pins sChorusFb, advanceWritePos, or the channel-arg pair:
an edit that swaps the voice index 0<->1 modulates the wrong voice (stereo
de-correlation collapses to one LFO voice doubled), hoisting
advanceWritePos() above the two calls makes both voices read the next
write slot (chorus texture shift), and a 0.25f rewrite to 0.0f kills the
chorus feedback silently — all compile clean behind an otherwise-green
gate.

Asserts (comment-stripped, brace-matched processBlock body):
  (a) the `sChorusFb = sChorusDepth * 0.25f` form stays in the per-sample
      precompute block;
  (b) the chorus gate body keeps process(smpL, 0, ...) BEFORE
      process(smpR, 1, ...) with (sChorusRate, sChorusDepth, sChorusFb)
      trailing;
  (c) chorus.advanceWritePos() sits AFTER both calls inside the gate.

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

FB_LINE = "const float sChorusFb     = sChorusDepth * 0.25f;"
CALL_RE = re.compile(
    r"chorus\.process\(\s*(smp[LR])\s*,\s*(\d)\s*,\s*"
    r"(sChorusRate\s*,\s*sChorusDepth\s*,\s*sChorusFb)\s*\)")


def fail(msg):
    print(f"CHORUS-VOICE FAIL: {msg}")
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


def check(body):
    """Return None if ok, else a diagnostic string."""
    if not re.search(re.escape("= sChorusDepth * 0.25f;"), body):
        return "sChorusFb precompute `= sChorusDepth * 0.25f;` not found " \
               "in the per-sample body"
    # isolate the chorus gate body: `if (gChorus > ... && sChorusDepth...)
    # { ... chorus.advanceWritePos(); ... }`
    m = re.search(r"if \((gChorus[^)]*&&\s*sChorusDepth[^)]*)\)\s*\{", body)
    if not m:
        return "chorus gate `if (gChorus ... && sChorusDepth ...)` not found"
    o = m.end() - 1
    depth, j = 0, o
    while j < len(body):
        if body[j] == "{": depth += 1
        elif body[j] == "}":
            depth -= 1
            if depth == 0: break
        j += 1
    if depth != 0:
        return "unbalanced braces in the chorus gate body"
    gate = body[o:j + 1]
    calls = CALL_RE.findall(gate)
    if len(calls) != 2:
        return f"expected exactly 2 chorus.process calls in the gate, " \
               f"found {len(calls)}"
    if calls[0][0] != "smpL" or calls[0][1] != "0":
        return f"first chorus.process must be voice L with channel index 0, " \
               f"got ({calls[0][0]}, {calls[0][1]})"
    if calls[1][0] != "smpR" or calls[1][1] != "1":
        return f"second chorus.process must be voice R with channel index 1, " \
               f"got ({calls[1][0]}, {calls[1][1]})"
    for _, _, args in calls:
        if collapse_ws(args) != "sChorusRate, sChorusDepth, sChorusFb":
            return f"chorus.process trailing args wrong: `{args}`"
    w = gate.find("chorus.advanceWritePos();")
    seccall = list(CALL_RE.finditer(gate))[1].end()
    if w == -1:
        return "chorus.advanceWritePos(); not found inside the chorus gate"
    if w < seccall:
        return "chorus.advanceWritePos() must come AFTER both " \
               "chorus.process calls (hoisting it makes both voices read " \
               "the next write slot)"
    if w > gate.rfind("}"):
        return "chorus.advanceWritePos() outside the chorus gate body"
    return None


proc_c_path = SRC / "PluginProcessor.cpp"
if not proc_c_path.exists():
    fail(f"missing source file {proc_c_path}")
proc_c = proc_c_path.read_text()

body = extract_body(proc_c, "processBlock")
err = check(body)
if err:
    fail(err + f" (PluginProcessor.cpp processBlock)")
print("chorus-voice: sChorusFb 0.25f precompute + L/R voice-arg call pair + "
      "trailing advanceWritePos() pinned in processBlock")

# ---------------------------------------------------------------------------
# Self-probes on mutated in-memory texts (real tree never mutated)
# ---------------------------------------------------------------------------

def probe(description, old, new, count=1):
    tmp = proc_c.replace(old, new, count)
    if tmp == proc_c:
        print(f"chorus-voice: no-op mutation guard -> skipping invalid "
              f"probe ({description})")
        return
    err = check(extract_body(tmp, "processBlock"))
    if err is None:
        print(f"chorus-voice: SELF-PROBE FAIL (checker should reject): "
              f"{description}")
        sys.exit(1)
    print(f"chorus-voice: self-probe fired: {description} -> rejected")


# 1. swap the voice indices 0 <-> 1
probe("voice indices swapped (L now modulates voice 1, R voice 0)",
      "chorus.process(smpL, 0, sChorusRate, sChorusDepth, sChorusFb)",
      "chorus.process(smpL, 1, sChorusRate, sChorusDepth, sChorusFb)")
probe("voice indices swapped (R now modulates voice 0, L voice 1)",
      "chorus.process(smpR, 1, sChorusRate, sChorusDepth, sChorusFb)",
      "chorus.process(smpR, 0, sChorusRate, sChorusDepth, sChorusFb)")

# 2. hoist advanceWritePos() above the two calls
adv_line = next(l for l in proc_c.splitlines()
                if "chorus.advanceWritePos();" in l)
first_call = next(l for l in proc_c.splitlines()
                  if "chorus.process(smpL, 0" in l)
probe("advanceWritePos hoisted above the two process calls",
      first_call,
      adv_line + "\n" + first_call, 1)

# 3. sChorusFb 0.25f -> 0.0f (kills the chorus feedback silently)
if FB_LINE not in proc_c:
    fail(f"self-probe baseline broken: expected `{FB_LINE}` verbatim")
probe("sChorusFb scale 0.25f -> 0.0f",
      "= sChorusDepth * 0.25f", "= sChorusDepth * 0.0f")

# 4. no-op guard: benign comment addition inside the chorus gate must
#    stay accepted
anchor = adv_line
tmp5 = proc_c.replace(anchor, "// benign probe edit\n" + anchor, 1)
if tmp5 == proc_c:
    print("chorus-voice: no-op probe skipped")
elif check(extract_body(tmp5, "processBlock")) is not None:
    fail("no-op guard: benign edit was wrongly rejected")
print("chorus-voice: no-op guard passed (benign edit accepted)")

print("CHORUS-VOICE OK")
