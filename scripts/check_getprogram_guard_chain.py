#!/usr/bin/env python3
"""Headless checker: getCurrentProgram id->index guard-chain pin.

getCurrentProgram (source/DrippyFX/PluginProcessor.cpp:265-283) converts
the combo "preset" id (raw APVTS read) into a program index via the
static presetFromId[43] reverse-lookup table:
    int id = (int)(apvts.getRawParameterValue("preset")->load() + 0.5f);
    static const int presetFromId[43] = { ... -1-seeded ... };
    if (id >= 0 && id < 43) { ... }
    int idx = presetFromId[id];
    if (idx >= 0) return idx;
    ..............
    return 0;

No other checker pins the guard chain: check_preset_tables.py pins the
presetFromId TABLE CONTENTS (43 entries, -1 rows, reversal-consistency
against idToPreset) but never the read/bound/guard/fallback code.

Designed-in hazards (both compile clean behind an otherwise-green gate):
  (a) dropping `idx >= 0` makes a separator-row lookup
      (ids 0,1,8,15,22,29,36) return -1 as the CURRENT program — hosts
      treat abnormal negative program indices erratically and
      getProgramName(-1) yields an empty/garbage name;
  (b) dropping `id < 43` turns any preset value beyond the table bound
      into an out-of-bounds read of the static table (UB).

Asserts (comment-stripped, brace-matched getCurrentProgram body):
  (a) the `+ 0.5f` rounding read of "preset";
  (b) the two-level bound `id >= 0 && id < 43` (or equivalent forms)
      preceding the presetFromId subscript;
  (c) the `if (idx >= 0) return idx;` separator guard;
  (d) `return 0;` as the only non-chain return value.

Self-probes (negative checks) run on mutated in-memory texts — the real
tree is never mutated. Exit 0 = ok, 1 = violation with diagnostics.
"""
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SRC = ROOT / "source" / "DrippyFX"


def fail(msg):
    print(f"GETPROGRAM-GUARD-CHAIN FAIL: {msg}")
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


def check(body_stripped):
    """Return None if ok, else a diagnostic string."""
    body = collapse_ws(body_stripped)

    # (a) rounding read of "preset"
    if not re.search(
            r'int id = \(int\)\(apvts\.getRawParameterValue\("preset"\)'
            r'->load\(\) \+ 0\.5f\);', body):
        return ('the rounding read `int id = (int)(apvts.getRawParameterValue'
                '("preset")->load() + 0.5f);` drifted or was dropped')

    # (b) two-level bound before the presetFromId subscript
    m = re.search(r'if \(id >= 0 && id < (\d+)\) \{', body)
    if not m:
        return ("the two-level bound `if (id >= 0 && id < 43) {` preceding "
                "the presetFromId subscript drifted (dropping `id < 43` "
                "turns any preset value beyond the table into an OOB read)")
    if m.group(1) != "43":
        return (f"the upper bound of the id check is {m.group(1)}, expected "
                f"43 (matches the static presetFromId[43] table size)")
    k = body.find("presetFromId[id]")
    if k == -1:
        return "the `presetFromId[id]` reverse-lookup subscript is gone"
    if body.find("if (id >= 0 && id < 43) {") > k:
        return "the bound guard is no longer before the presetFromId subscript"
    # table size declaration must stay in sync with the bound
    tm = re.search(r'static const int presetFromId\[(\d+)\]', body)
    if not tm or tm.group(1) != m.group(1):
        return ("the declared static presetFromId[N] size drifted out of "
                "sync with the `id < N` bound guard")

    # (c) separator guard `if (idx >= 0) return idx;`
    if not re.search(r'if \(idx >= 0\) return idx;', body):
        return ("the separator guard `if (idx >= 0) return idx;` drifted — "
                "dropping it makes a separator-row lookup (ids "
                "0,1,8,15,22,29,36) return -1 as the CURRENT program")
    # ...and it must be inside the bounded if-block (guard before fallback)
    gi = body.find("if (idx >= 0) return idx;")
    if gi < 0 or gi < body.find("if (id >= 0 && id < 43) {"):
        return "the idx >= 0 guard is not nested after the id-bound guard"

    # (d) return 0 fallback as the only non-chain return
    rets = re.findall(r'return [^;]*;', body)
    chain_returns = [r for r in rets if r.strip() == "return idx;"]
    other = [r for r in rets if r.strip() != "return idx;"]
    if len(chain_returns) != 1:
        return f"expected exactly one `return idx;` chain return, found {chain_returns}"
    if not (len(other) == 1 and other[0].strip() == "return 0;"):
        return (f"expected the only non-chain return to be `return 0;` "
                f"(safe program-0 fallback), found {other}")
    return None


proc_c_path = SRC / "PluginProcessor.cpp"
if not proc_c_path.exists():
    fail(f"missing source file {proc_c_path}")
proc_c = proc_c_path.read_text()

body = extract_body(proc_c, "getCurrentProgram")
err = check(body)
if err:
    fail(err + " (PluginProcessor.cpp getCurrentProgram)")
print("getprogram-guard-chain: rounding read of \"preset\", id < 43 "
      "bound, idx >= 0 separator guard, return-0 fallback pinned")

# ---------------------------------------------------------------------------
# Self-probes on mutated in-memory texts (real tree never mutated)
# ---------------------------------------------------------------------------

def probe(description, old, new, count=1):
    tmp_raw = proc_c.replace(old, new, count)
    if tmp_raw == proc_c:
        print(f"getprogram-guard-chain: no-op mutation guard -> skipping "
              f"invalid probe ({description})")
        return
    if check(extract_body(tmp_raw, "getCurrentProgram")) is None:
        print(f"getprogram-guard-chain: SELF-PROBE FAIL (checker should "
              f"reject): {description}")
        sys.exit(1)
    print(f"getprogram-guard-chain: self-probe fired: {description} -> "
          f"rejected")


# 1. separator guard dropped (a -1 separator row returned as the CURRENT
#    program; getProgramName(-1) is empty/garbage)
probe("idx >= 0 separator guard dropped (a -1 separator row would be "
      "returned as the current program)",
      "        int idx = presetFromId[id];\n"
      "        if (idx >= 0) return idx;",
      "        return presetFromId[id];")

# 2. upper bound dropped (OOB read of the static 43-entry table for any
#    preset value outside [0,43))
probe("id < 43 upper bound dropped (OOB read of presetFromId)",
      "if (id >= 0 && id < 43) {",
      "if (id >= 0) {")

# 3. fallback changed away from program 0 (returning presetFromId[0]
#    would return -1 itself on a separator id)
probe("fallback `return 0;` changed to `return presetFromId[0];` (a -1 "
      "escape from the guard chain)",
      "    return 0;\n}",
      "    return presetFromId[0];\n}")

# 4. rounding dropped (int truncation biases id selection below x.5)
probe("+ 0.5f rounding dropped from the preset read (truncation bias)",
      'int id = (int)(apvts.getRawParameterValue("preset")->load() + 0.5f);',
      'int id = (int)(apvts.getRawParameterValue("preset")->load());')

# 5. table bound desync (bound widened while the declared table size
#    stays 43 — the bound no longer protects the actual table)
probe("id bound widened to 44 while presetFromId stays [43] (bound no "
      "longer protects the table)",
      "if (id >= 0 && id < 43) {",
      "if (id >= 0 && id < 44) {")

# 6. no-op guard: benign comment addition inside the body stays accepted
tmp = proc_c.replace(
    'int id = (int)(apvts.getRawParameterValue("preset")->load() + 0.5f);',
    'int id = (int)(apvts.getRawParameterValue("preset")->load() + 0.5f); /* benign */',
    1)
if tmp == proc_c:
    print("getprogram-guard-chain: no-op probe skipped")
elif check(extract_body(tmp, "getCurrentProgram")) is not None:
    fail("no-op guard: benign edit was wrongly rejected")
print("getprogram-guard-chain: no-op guard passed (benign edit accepted)")

print("GETPROGRAM-GUARD OK")
