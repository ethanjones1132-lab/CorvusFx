#!/usr/bin/env python3
"""Headless checker: prepareToPlay/processBlock smoothing-twin cross-body pin.

The 19 `smooth<X>.setTargetValue(apvts.getRawParameterValue("<id>")->load()...)`
lines are hand-maintained TWINS: prepareToPlay
(source/DrippyFX/PluginProcessor.cpp:433-454) seeds the targets at
re-prepare time and processBlock (:502-525) refreshes them per block.
check_raw_param_ids.py asserts each id's glue INSIDE each body but never
COMPARES the two bodies: a prepare-side `chorus_rate` line rewritten with
`/100.0f` while processBlock keeps the unscaled read seeds the smooth
target 100x high at every re-prepare until the first block lands
(audible wrong-rate chirp on module re-prepare only), and reordering one
body's lines diverges the twin copy histories — both compile clean.

Asserts (comment-stripped, brace-matched):
  (a) each body keeps exactly the same 19 smoothed ids in the SAME ORDER;
  (b) for each of the 19 ids the two bodies' setTargetValue expression
      texts are IDENTICAL (catches a single-side /100.0f add or drop).

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

EXPECTED_IDS = [
    "overall", "fatness",
    "chorus_depth", "chorus_rate", "chorus_mix",
    "delay_time", "delay_feedback", "delay_mix", "delay_damping", "delay_mod",
    "reverb_size", "reverb_damping", "reverb_mix", "reverb_mod",
    "master_drive", "master_width", "master_mid_drive", "master_side_drive",
    "output_trim",
]

# Match `smooth<Name>.setTargetValue(...);` possibly spanning lines
# (the delay_feedback twin wraps its expression in a brace block that
# collapses to one statement after comment-stripping is line-based, so
# match conservatively: target, then lazy capture up to `);`).
STMT_RE = re.compile(
    r"smooth([A-Za-z0-9]+)\.setTargetValue\((.*?)\)\s*;", re.S)


def fail(msg):
    print(f"SMOOTHING-TWIN FAIL: {msg}")
    sys.exit(1)


def strip_comments(txt):
    """Remove // line comments and /* */ block comments."""
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
    """Extract the brace-matched body of fn_name in txt (comment-stripped)."""
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


def body_twins(body):
    """Return [(id, collapsed expr)] for the smooth* setTargetValue lines."""
    return [(m.group(1), collapse_ws(m.group(2)))
            for m in STMT_RE.finditer(body)]


def id_matches(camel, pid):
    """smooth<Name> -> param id comparison ('ChorusDepth' vs 'chorus_depth')."""
    return camel.lower() == pid.replace("_", "").lower()


def check_twins(prep_twins, proc_twins):
    """True iff same 19 ids, same order, identical expr per id."""
    if len(prep_twins) != 19 or len(proc_twins) != 19:
        return False
    if not all(id_matches(i, p) for i, p in zip((x for x, _ in prep_twins), EXPECTED_IDS)):
        return False
    if not all(id_matches(i, p) for i, p in zip((x for x, _ in proc_twins), EXPECTED_IDS)):
        return False
    # full (id, expr) ordered-list equality: catches single-side scale adds
    # AND one-body-only line reorders (dict() would hide order divergence)
    return prep_twins == proc_twins


proc_c_path = SRC / "PluginProcessor.cpp"
if not proc_c_path.exists():
    fail(f"missing source file {proc_c_path}")
proc_c = proc_c_path.read_text(encoding="utf-8")

prep_twins = body_twins(extract_body(proc_c, "prepareToPlay"))
proc_twins = body_twins(extract_body(proc_c, "processBlock"))

if not check_twins(prep_twins, proc_twins):
    prep_ids = [i for i, _ in prep_twins]
    proc_ids = [i for i, _ in proc_twins]
    detail = ""
    if prep_ids != proc_ids:
        detail = f" (prepare order {prep_ids} != process order {proc_ids})"
    if dict(prep_twins) != dict(proc_twins):
        diffs = [i for i, e in prep_twins
                 if dict(proc_twins).get(i) != e]
        detail = f" (expression diverges for: {diffs})"
    fail("prepareToPlay/processBlock smoothing twins desynced:\n"
         "  prepare: " + "; ".join(f"{i}({e})" for i, e in prep_twins) +
         "\n  process: " + "; ".join(f"{i}({e})" for i, e in proc_twins) +
         detail)

print("smoothing-twin: 19 setTargetValue twins match across "
      "prepareToPlay and processBlock (scale + order pinned)")

# ---------------------------------------------------------------------------
# Self-probes on mutated in-memory texts (real tree never mutated)
# ---------------------------------------------------------------------------

def recheck(mutated_full_text):
    try:
        pt = body_twins(extract_body(mutated_full_text, "prepareToPlay"))
        bt = body_twins(extract_body(mutated_full_text, "processBlock"))
    except SystemExit:
        return False
    return check_twins(pt, bt)


def probe(description, mutator):
    if len(mutator) == 3:
        old, new, count = mutator
        tmp = proc_c.replace(old, new, count)
    else:
        tmp = proc_c.replace(*mutator)
    if tmp == proc_c:
        print(f"smoothing-twin: no-op mutation guard -> skipping invalid probe ({description})")
        return
    if recheck(tmp):
        print(f"smoothing-twin: SELF-PROBE FAIL (checker should reject): {description}")
        sys.exit(1)
    print(f"smoothing-twin: self-probe fired: {description} -> rejected")


# 1. add /100.0f to the prepare-side chorus_rate expression ONLY
#    (seed the smooth target 100x high at re-prepare)
cr_lines = [l for l in proc_c.splitlines()
            if "smoothChorusRate.setTargetValue" in l]
if len(cr_lines) != 2:
    fail(f"self-probe baseline broken: expected 2 smoothChorusRate lines, "
         f"found {len(cr_lines)}")
cr = cr_lines[0]  # prepareToPlay precedes processBlock in the file
# the processBlock copy is identical; mutate only the FIRST occurrence
# (prepareToPlay precedes processBlock in the file)
probe("prepare-side chorus_rate scaled /100.0f while process stays unscaled",
      (cr, cr.replace("->load()", "->load() / 100.0f"), 1))

# 2. reorder one body's delay-block target lines -> twin ORDER diverges.
#    Swap the processBlock-side delay_time line with the delay_mix line
#    that follows the feedback brace block (delay_time's first and
#    delay_mix's second occurrence, count=1 each side).
lines = proc_c.splitlines()
dm_line = next(l for l in lines if "smoothDelayMix.setTargetValue" in l)
dd_line = next(l for l in lines if "smoothDelayDamping.setTargetValue" in l)
probe("processBlock delay target block reordered (delay_mix / "
      "delay_damping lines swapped)", (dm_line + "\n" + dd_line,
                                       dd_line + "\n" + dm_line, 1))

# 3. no-op guard: benign comment addition inside prepareToPlay must
#    stay accepted
anchor = next(l for l in lines if "smoothChorusMix.reset" in l)
tmp5 = proc_c.replace(anchor, "// benign probe edit\n" + anchor, 1)
if tmp5 == proc_c:
    print("smoothing-twin: no-op probe skipped")
elif not recheck(tmp5):
    fail("no-op guard: benign edit was wrongly rejected")
print("smoothing-twin: no-op guard passed (benign edit accepted)")

print("SMOOTHING-TWIN OK")
