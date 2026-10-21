#!/usr/bin/env python3
"""Headless checker: loadPreset bool-bypass / AudioParameterBool pairing pin.

loadPreset writes the 5 bypass ids through the `set` lambda
`param->setValueNotifyingHost(param->convertTo0to1(v))`
(source/DrippyFX/PluginProcessor.cpp loadPreset) with RAW 0/1 arguments
from struct P (p.distByp etc.), while createParameterLayout() registers
those ids as juce::AudioParameterBool. This is correct ONLY because
convertTo0to1 is identity on the bool range: an edit that moves any
bypass id to a pctParam-style 0-100 float (like every sibling knob)
makes convertTo0to1(1) = 0.01 — a preset whose module is ON loads with
that module BYPASSED — and dropping a set() line leaves the bypass knob
at its stale value across preset change. Both compile clean behind an
otherwise-green gate; no sibling checker (tables/load-sites/combo-
runtime/randomize) pins this pairing.

Asserts (comment-stripped, brace-matched):
  (a) the `set` lambda keeps convertTo0to1(v) inside setValueNotifyingHost;
  (b) all 5 bool-bypass ids appear as set("<id>", p.<field>) exactly once
      each in loadPreset;
  (c) createParameterLayout() keeps juce::AudioParameterBool for each of
      the 5 ids.

Self-probes (negative checks, sibling checker style) run on mutated
in-memory TEMP texts — the real tree is never mutated. A no-op mutation
guard skips probes whose mutation didn't apply.

Exit 0 = ok, 1 = violation with diagnostics.
"""
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SRC = ROOT / "source" / "DrippyFX"

BYPASS_IDS = [
    "distortion_bypass", "chorus_bypass", "delay_bypass",
    "reverb_bypass", "master_bypass",
]


def fail(msg):
    print(f"PRESET-BOOL-WRITES FAIL: {msg}")
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


def check_load_body(load_body):
    """True iff (a) convertTo0to1 inside setValueNotifyingHost in `set`,
    (b) all 5 bypass ids set(...) exactly once each."""
    m = re.search(
        r"setValueNotifyingHost\s*\(\s*param\s*->\s*convertTo0to1\s*\(\s*v\s*\)\s*\)",
        load_body)
    if not m:
        return False
    norm = re.sub(r"\s+", " ", load_body)
    for pid in BYPASS_IDS:
        if len(re.findall(rf'set\s*\(\s*"{pid}"\s*,', norm)) != 1:
            return False
    return True


def check_layout_body(layout_body):
    """True iff each bypass id is registered as juce::AudioParameterBool."""
    for pid in BYPASS_IDS:
        pat = rf'juce::AudioParameterBool>?\s*\(\s*"{pid}"\s*,'
        if not re.search(pat, re.sub(r"\s+", " ", layout_body)):
            return False
    return True


def recheck(mutated_full_text):
    try:
        load_body = extract_body(mutated_full_text, "loadPreset")
        layout_body = extract_body(mutated_full_text, "createParameterLayout")
    except SystemExit:
        return False
    return (check_load_body(load_body)
            and check_layout_body(layout_body))


proc_c_path = SRC / "PluginProcessor.cpp"
if not proc_c_path.exists():
    fail(f"missing source file {proc_c_path}")
proc_c = proc_c_path.read_text(encoding="utf-8")

if not recheck(proc_c):
    load_body = extract_body(proc_c, "loadPreset")
    layout_body = extract_body(proc_c, "createParameterLayout")
    norm_load = re.sub(r"\s+", " ", load_body)
    if not re.search(
            r"setValueNotifyingHost\s*\(\s*param\s*->\s*convertTo0to1\s*\(\s*v\s*\)\s*\)",
            load_body):
        fail("loadPreset `set` lambda no longer routes through "
             "param->convertTo0to1(v) inside setValueNotifyingHost")
    missing = [pid for pid in BYPASS_IDS
               if len(re.findall(rf'set\s*\(\s*"{pid}"\s*,',
                                 norm_load)) != 1]
    if missing:
        fail(f"bypass set() sites wrong for: {missing} "
             f"(each must appear exactly once in loadPreset)")
    missing_bool = [pid for pid in BYPASS_IDS if not re.search(
        rf'juce::AudioParameterBool>?\s*\(\s*"{pid}"\s*,',
        re.sub(r"\s+", " ", extract_body(proc_c, "createParameterLayout")))]
    fail("AudioParameterBool registration missing for: "
         + ", ".join(missing_bool))

print(f"preset-bool-writes: convertTo0to1 set-lambda + 5 bypass set() sites "
      f"+ AudioParameterBool registrations pinned ({', '.join(BYPASS_IDS)})")

# ---------------------------------------------------------------------------
# Self-probes on mutated in-memory texts (real tree never mutated)
# ---------------------------------------------------------------------------

def probe(description, mutator):
    old, new = mutator[0], mutator[1]
    count = mutator[2] if len(mutator) > 2 else 1
    tmp = proc_c.replace(old, new, count)
    if tmp == proc_c:
        print(f"preset-bool-writes: no-op mutation guard -> skipping "
              f"invalid probe ({description})")
        return
    if recheck(tmp):
        print(f"preset-bool-writes: SELF-PROBE FAIL (checker should "
              f"reject): {description}")
        sys.exit(1)
    print(f"preset-bool-writes: self-probe fired: {description} -> rejected")


# 1. move distortion_bypass to a pctParam-style 0-100 float registration
#    (convertTo0to1(1) = 0.01 -> preset-on module loads bypassed)
probe("distortion_bypass registration moved to pctParam-style float",
      ('std::make_unique<juce::AudioParameterBool>("distortion_bypass", "Distortion Bypass", false)',
       'pctParam("distortion_bypass", "Distortion Bypass", 0)'))

# 2. drop one bypass set() line from loadPreset
byp_line = next(l for l in proc_c.splitlines()
                if 'set("chorus_bypass", p.chorusByp)' in l)
probe("chorus_bypass set() line dropped from loadPreset",
      (byp_line + "\n", "", 1))

# 3. no-op guard: benign comment addition inside loadPreset must stay accepted
anchor = next(l for l in proc_c.splitlines()
              if 'set("distortion_bypass", p.distByp)' in l)
tmp5 = proc_c.replace(anchor, "// benign probe edit\n" + anchor, 1)
if tmp5 == proc_c:
    print("preset-bool-writes: no-op probe skipped")
elif not recheck(tmp5):
    fail("no-op guard: benign edit was wrongly rejected")
print("preset-bool-writes: no-op guard passed (benign edit accepted)")

print("PRESET-BOOL-WRITES OK")
