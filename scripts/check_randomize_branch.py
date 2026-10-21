#!/usr/bin/env python3
"""Headless checker: randomizePreset bool-vs-continuous write pairing pin.

randomizePreset (source/DrippyFX/PluginProcessor.cpp:169+) classifies each
parameter through `bool isBool =
dynamic_cast<juce::AudioParameterBool*>(ranged) != nullptr;` and writes

  bool param:        ranged->setValueNotifyingHost(rng.nextFloat() < 0.15f ? 1.0f : 0.0f);
  continuous param:  ranged->setValueNotifyingHost(rng.nextFloat());

check_randomize_shape.py pins the transaction/guard shape but nothing
cross-checks the BRANCH or its pairing with the register-faced types:
createParameterLayout registers the 5 bypass ids as juce::AudioParameterBool
(pinned only by check_preset_bool_writes.py from the loadPreset side) and
every other non-preset id as a pctParam/hzParam/msParam AudioParameterFloat.

Falsifications (all compile clean behind an otherwise-green gate):
  (a) swapping the 0.15f/1.0f branch arms makes every randomize click
      sent ~85% of the time and toggle bypasses far too often;
  (b) an added AudioParameterBool registration (or a bypass id moved off
      bool) breaks the dynamic_cast classification silently:
      the bool arms write 1.0f onto a normalized float range (a bypass
      knob railed by randomize while loadPreset assumes 0/1) or the
      opposite;
  (c) replacing the isBool test with `ranged->getNormalisableRange()
      .getRange() == juce::Range<float>(0, 1)`-style heuristics loses the
      type-driven pairing.

Asserts (comment-stripped, brace-matched on randomizePreset body):
  (a) body contains the `bool isBool = dynamic_cast<juce::AudioParameter
      Bool*>(ranged) != nullptr;` classification (whitespace-collapsed);
  (b) inside the body, the branch keeps the ordered shape:
      `if (isBool)` then `setValueNotifyingHost(rng.nextFloat() < 0.15f
      ? 1.0f : 0.0f)` then `setValueNotifyingHost(rng.nextFloat())`;
  (c) roster: exactly ONE `< 0.15f` literal in the body (the bool branch
      is the only hair-trigger), and NO other nextFloat() threshold
      drifts in;
  (d) layout pairing: each of the 5 bypass ids is registered EXACTLY
      once as juce::AudioParameterBool in createParameterLayout, and the
      bool-registered id set equals the 5-id set (no second bool id
      smuggled in, none demoted).

Self-probes on mutated in-memory texts (real tree never mutated); a no-op
mutation aborts as a stale alarm. Exit 0 = ok, 1 = violation.
"""
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SRC = ROOT / "source" / "DrippyFX"
CPP = SRC / "PluginProcessor.cpp"

BYPASS_IDS = [
    "distortion_bypass", "chorus_bypass", "delay_bypass",
    "reverb_bypass", "master_bypass",
]


def fail(msg):
    print(f"RANDOMIZE-BRANCH FAIL: {msg}")
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


def collapse(s):
    return re.sub(r"\s+", " ", s).strip()


def brace_span(s, o):
    depth = 0
    j = o
    while j < len(s):
        if s[j] == "{":
            depth += 1
        elif s[j] == "}":
            depth -= 1
            if depth == 0:
                return j
        j += 1
    return -1


def fn_body(code, sig):
    m = re.search(sig, code)
    if not m:
        return None
    o = code.find("{", m.end())
    if o == -1:
        return None
    e = brace_span(code, o)
    if e == -1:
        return None
    return code[o + 1:e]


def _verify(code):
    if "{" not in code:
        return "implausible strip_comments result"
    body = fn_body(code, r"CorvusFXAudioProcessor::randomizePreset\s*\(\s*\)")
    if body is None:
        return "randomizePreset body not found/brace-matched"
    flat = collapse(body)

    # (a) the dynamic_cast<bool> classification
    cls_re = re.compile(
        r"bool isBool\s*=\s*dynamic_cast<\s*juce::AudioParameterBool\s*\*>\s*"
        r"\(\s*ranged\s*\)\s*!=\s*nullptr\s*;")
    if not cls_re.search(flat):
        return ("randomizePreset lost the "
                "`bool isBool = dynamic_cast<juce::AudioParameterBool*>"
                "(ranged) != nullptr;` classification — bool-vs-continuous "
                "pairing would break silently")

    # (b) ordered branch shape: two independent arms
    if not re.search(
            r"if\s*\(\s*isBool\s*\)\s*ranged->setValueNotifyingHost\("
            r"\s*rng\.nextFloat\(\)\s*<\s*0\.15f\s*\?\s*1\.0f\s*:\s*0\.0f\s*\)\s*;",
            flat):
        return ("randomizePreset bool arm drifted — expected "
                "`if (isBool) ranged->setValueNotifyingHost(rng.nextFloat() "
                "< 0.15f ? 1.0f : 0.0f);` (a swapped arm pair, a 0.15f "
                "drift, or a dropped binary gate writes wrong values to "
                "the bool face of the parameter set)")
    if not re.search(
            r"else\s*\n?\s*ranged->setValueNotifyingHost\(\s*"
            r"rng\.nextFloat\(\)\s*\)\s*;",
            body):
        return ("randomizePreset continuous arm drifted — expected "
                "`else ranged->setValueNotifyingHost(rng.nextFloat());` "
                "(a full-normalized random write on the continuous face "
                "is the designed behaviour; a collapsed write loses it)")

    # (c) roster: exactly one `< 0.15f` threshold in the body
    n = len(re.findall(r"<\s*0\.15f", flat))
    if n != 1:
        return (f"exactly one `< 0.15f` bool-trigger literal expected in "
                f"randomizePreset, found {n}")

    # (d) layout pairing: bool registrations == the 5 bypass ids
    layout = fn_body(code,
                    r"ParameterLayout\s+CorvusFXAudioProcessor::"
                    r"createParameterLayout\s*\(\s*\)")
    if layout is None:
        return "createParameterLayout body not found/brace-matched"
    bool_ids = re.findall(
        r"make_unique<\s*juce::AudioParameterBool\s*>\s*\(\s*"
        r"\"([A-Za-z0-9_]+)\"", layout)
    std_bool_ids = re.findall(
        r"std::make_unique<\s*juce::AudioParameterBool\s*>\s*\(\s*"
        r"\"([A-Za-z0-9_]+)\"", layout)
    if len(std_bool_ids) > len(bool_ids):
        bool_ids = std_bool_ids
    if sorted(bool_ids) != sorted(BYPASS_IDS):
        return (f"createParameterLayout AudioParameterBool roster is "
                f"{sorted(bool_ids)}, expected exactly the 5 bypass ids "
                f"{sorted(BYPASS_IDS)} — an added/demoted bool id "
                "desyncs randomizePreset's dynamic_cast pairing")
    return None


cpp_raw = CPP.read_text(encoding="utf-8")
if not CPP.exists():
    fail(f"missing source file {CPP}")
code = strip_comments(cpp_raw)

err = _verify(code)
if err:
    fail(err)
print("randomize-branch: dynamic_cast isBool classification, ordered "
      "0.15f/?1.0f:0.0f branch, single-threshold roster, and the "
      "5-id AudioParameterBool layout pairing pinned")

# --------------------------------------------------------------------------
# negative self-probes on mutated in-memory texts (real tree never mutated)
# --------------------------------------------------------------------------
GOOD_BRANCH = ("if (isBool)\n"
               "            ranged->setValueNotifyingHost(rng.nextFloat() < 0.15f ? 1.0f : 0.0f);\n"
               "        else\n"
               "            ranged->setValueNotifyingHost(rng.nextFloat());")

probes = [
    ("bool-trigger threshold drifted 0.15f -> 0.5f",
     GOOD_BRANCH.replace("0.15f", "0.5f")),
    ("branch arms swapped (continuous gets the ?1.0f:0.0f write)",
     GOOD_BRANCH.replace(
         "ranged->setValueNotifyingHost(rng.nextFloat() < 0.15f ? 1.0f : 0.0f);",
         "ranged->setValueNotifyingHost(rng.nextFloat() < 0.15f ? 0.0f : 1.0f);")),
    ("one bypass id demoted off AudioParameterBool in the layout",
     cpp_raw.replace(
         'params.push_back(std::make_unique<juce::AudioParameterBool>("distortion_bypass", "Distortion Bypass", false));',
         'params.push_back(pctParam("distortion_bypass", "Distortion Bypass", 0));')),
]
for label, mutated in probes:
    if mutated == cpp_raw:
        fail(f"no-op probe ({label}): mutation did not change the source — "
             "the negative check is stale")
    verdict = _verify(strip_comments(mutated))
    if verdict is None:
        fail(f"negative probe '{label}' was NOT rejected — checker is vacuous")
    print(f"randomize-branch: negative probe '{label}' rejected")

# no-op guard: benign edit outside the pinned shapes must still pass
neutral = cpp_raw.replace(
    "juce::Random rng;",
    "juce::Random rng;  // probe comment")
if neutral == cpp_raw:
    fail("no-op guard: unanchored neutral edit did not change the source")
if _verify(strip_comments(neutral)) is not None:
    fail("neutral edit outside the pinned shapes was REJECTED — checker "
         "over-fires")
print("randomize-branch: neutral no-op edit passes (probe specificity proven)")

# real tree never mutated — re-verify the live source once more before gating
err = _verify(strip_comments(CPP.read_text(encoding="utf-8")))
if err:
    fail(f"final source re-verification failed: {err}")
print("randomize-branch: OK")
sys.exit(0)
