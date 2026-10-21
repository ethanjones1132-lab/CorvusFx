#!/usr/bin/env python3
"""Headless checker: master-stage drive/width glue pin.

The composition lines feeding the master output stage
(source/DrippyFX/PluginProcessor.cpp per-sample "5. MASTER OUTPUT STAGE"
gate) carry the mid/side drive scaling and width expansion —
`midDrive = sMasterDrive * 1.8f + sMasterMidDrive * 1.8f`,
`sideDrive = sMasterDrive * 1.8f + sMasterSideDrive * 1.8f`,
`width = 0.5f + sMasterWidth * 1.5f` — and the
masterOutput.process(ml, mr, midDrive, sideDrive, width) call followed by
the two crossfades. Nothing pins these: an edit dropping the
sMasterMidDrive or sMasterSideDrive term (that knob silently stops
driving), halving a knob's effective range (width 1.5f -> 0.75f), or
swapping mid/side inside the call compiles clean behind an otherwise-green
gate.

Asserts (comment-stripped, brace-matched MASTER gate body inside
processBlock):
  (a) midDrive line keeps sMasterDrive * 1.8f + sMasterMidDrive * 1.8f
      (side-halving probe: 1.8f count per line exactly 2);
  (b) sideDrive line keeps sMasterDrive * 1.8f + sMasterSideDrive * 1.8f;
  (c) width keeps 0.5f + sMasterWidth * 1.5f;
  (d) masterOutput.process(ml, mr, midDrive, sideDrive, width) follows
      with mid before side;
  (e) both crossfades (smpL/smpR via 1.0f - gMaster) stay after the
      process call inside the gate.

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


def fail(msg):
    print(f"MASTER-STAGE-GLUE FAIL: {msg}")
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


def collapse_ws(s):
    return re.sub(r"\s+", " ", s).strip()


def check(body):
    """Return None if ok, else a diagnostic string."""
    gm = re.search(r"gMaster > 0\.001f", body)
    if not gm:
        return "master gate `gMaster > 0.001f` not found in the per-sample body"
    ib = body.find("{", gm.end() - 1)
    if ib == -1:
        return "master gate has no opening brace"
    gb = brace_slice(body, ib)
    if gb is None:
        return "unbalanced braces in the master gate body"

    # (a/b) the two drive composition lines: exactly two * 1.8f terms each,
    # sMasterDrive first, mid line before side line.
    midi = collapse_ws(gb).find(
        "float midDrive = sMasterDrive * 1.8f + sMasterMidDrive * 1.8f;")
    sidei = collapse_ws(gb).find(
        "float sideDrive = sMasterDrive * 1.8f + sMasterSideDrive * 1.8f;")
    if midi == -1 or sidei == -1:
        return ("mid/side drive composition lines must stay verbatim "
                "`sMasterDrive * 1.8f + sMasterMid[Side]Drive * 1.8f` "
                "(dropped term = that knob silently stops driving)")
    if sidei < midi:
        return "midDrive composition line must precede sideDrive"
    for i, line in enumerate([l for l in gb.splitlines()
                              if "Drive" in l and "1.8f" in l]):
        if line.count("* 1.8f") != 2:
            return (f"drive line {i} has {line.count('* 1.8f')} `* 1.8f` "
                    f"terms, expected exactly 2: `{collapse_ws(line)}`")

    # (c) width scaling stays 0.5f + sMasterWidth * 1.5f
    if "float width = 0.5f + sMasterWidth * 1.5f;" not in collapse_ws(gb):
        return ("width scaling must stay `0.5f + sMasterWidth * 1.5f` "
                "(a rewrite halves/widens the knob's effective range)")

    # (d) process call with mid before side
    cm = re.search(
        r"masterOutput\.process\((ml|mr),\s*(ml|mr),\s*midDrive,\s*sideDrive",
        gb)
    if not cm:
        return ("masterOutput.process(ml, mr, midDrive, sideDrive, width) "
                "call shape missing or mid/side args swapped")
    if cm.group(1) != "ml" or cm.group(2) != "mr":
        return "masterOutput.process receives ml before mr"

    # (e) both crossfades after the process call inside the gate
    for gvar, ch in (("ml", "L"), ("mr", "R")):
        xf = gb.find(f"(1.0f - gMaster) + {gvar} * gMaster")
        if xf == -1:
            return (f"master crossfade `smp{ch} = smp{ch} * (1.0f - gMaster) "
                    f"+ {gvar} * gMaster` not found inside the gate body")
        if xf < cm.end():
            return f"smp{ch} master crossfade must come AFTER the process call"
    return None


proc_c_path = SRC / "PluginProcessor.cpp"
if not proc_c_path.exists():
    fail(f"missing source file {proc_c_path}")
proc_c = proc_c_path.read_text(encoding="utf-8")

body = extract_body(proc_c, "processBlock")
err = check(body)
if err:
    fail(err + " (PluginProcessor.cpp processBlock master stage)")
print("master-stage-glue: mid/side drive (2x * 1.8f terms), width "
      "(0.5f + w * 1.5f), process order (ml, mr, mid, side) and "
      "crossfades pinned inside the master gate")

# ---------------------------------------------------------------------------
# Self-probes on mutated in-memory texts (real tree never mutated)
# ---------------------------------------------------------------------------

def probe(description, old, new, count=1):
    tmp = proc_c.replace(old, new, count)
    if tmp == proc_c:
        print(f"master-stage-glue: no-op mutation guard -> skipping invalid "
              f"probe ({description})")
        return
    err = check(extract_body(tmp, "processBlock"))
    if err is None:
        print(f"master-stage-glue: SELF-PROBE FAIL (checker should reject): "
              f"{description}")
        sys.exit(1)
    print(f"master-stage-glue: self-probe fired: {description} -> rejected")


# 1. drop the sMasterSideDrive term (side knob silently stops driving)
probe("sMasterSideDrive term dropped from sideDrive composition",
      "float sideDrive = sMasterDrive * 1.8f + sMasterSideDrive * 1.8f;",
      "float sideDrive = sMasterDrive * 1.8f;")

# 2. swap mid/side args in the process call
probe("mid/side args swapped in masterOutput.process call",
      "masterOutput.process(ml, mr, midDrive, sideDrive, width);",
      "masterOutput.process(ml, mr, sideDrive, midDrive, width);")

# 3. width scaling halved-halved: 1.5f -> 0.0f
probe("width scale 1.5f -> 0.0f",
      "float width = 0.5f + sMasterWidth * 1.5f;",
      "float width = 0.5f + sMasterWidth * 0.0f;")

# 3b. halve a drive range but keep the term-count edge: single 1.8f term
#     (term-count assert catches the dropped scaling even with shape intact)
probe("midDrive halved to a single 1.8f term (term-count assert)",
      "float midDrive = sMasterDrive * 1.8f + sMasterMidDrive * 1.8f;",
      "float midDrive = sMasterDrive * 1.8f * sMasterMidDrive;")

# 4. hoist the L crossfade above the process call (reads uncrossfaded wet)
probe("L master crossfade hoisted above the process call",
      "masterOutput.process(ml, mr, midDrive, sideDrive, width);\n"
      "            smpL = smpL * (1.0f - gMaster) + ml * gMaster;",
      "smpL = smpL * (1.0f - gMaster) + ml * gMaster;\n"
      "            masterOutput.process(ml, mr, midDrive, sideDrive, width);")

# 5. no-op guard: benign edit outside the pinned shapes must stay accepted
anchor = "float width = 0.5f + sMasterWidth * 1.5f; // 0.5 to 2.0 range"
if anchor not in proc_c:
    print("master-stage-glue: no-op probe anchor missing -> skipping")
else:
    tmp5 = proc_c.replace(anchor, anchor + " // benign probe edit", 1)
    if tmp5 == proc_c:
        print("master-stage-glue: no-op probe skipped")
    elif check(extract_body(tmp5, "processBlock")) is not None:
        fail("no-op guard: benign edit was wrongly rejected")
    print("master-stage-glue: no-op guard passed (benign edit accepted)")

print("MASTER-STAGE-GLUE OK")
