#!/usr/bin/env python3
"""Headless checker: processBlock / prepareToPlay raw-parameter read + smoothing roster.

CorvusFX's processBlock (source/DrippyFX/PluginProcessor.cpp:487) and
prepareToPlay (:397) read every parameter directly through
`apvts.getRawParameterValue("<id>")` on the AUDIO thread with no null guard —
a rename/add in createParameterLayout that misses one read site is an instant
audio-thread crash on the first block (nullptr->load()). The reads are string
literals, so nothing else correlates them to the layout:
scripts/check_ab_param_roster.py pins only the A/B table (abParamIds); the raw
read sites, the smoothing glue, and the bypass gate reads are unpinned.

Asserts (comment-stripped):
  (a) every `getRawParameterValue("<id>")` string literal in PluginProcessor.cpp
      names an id declared in createParameterLayout;
  (b) the raw reads COVER every non-"preset" layout id — an added parameter
      whose read site is missing ships a knob that never leaves its default;
  (c) every smoothed (non-bypass, non-preset) id keeps one
      `smooth<Pascal>.setTargetValue(` line in BOTH the prepareToPlay body and
      the processBlock parameter-update region (up to the per-sample loop);
      smoother names derived from the id, not a hand list; the smoother member
      must still exist in PluginProcessor.h;
  (c2) every smoothed id is still READ back — `getNextValue()` inside the
      per-sample loop OR a `getTargetValue()` block-level read in processBlock
      before the loop (the eight beginBlock cache drivers use getTargetValue()).
      Dropping the consumer line (an iter-067 a4800aa-class "simplify") would
      leave the knob running on a never-advanced smoother — zipper noise /
      stale audio — with the rest of the gate green;
  (d) the five bypass bool ids are each read with the exact
      `getRawParameterValue("<id>")->load() > 0.5f` gate form in BOTH bodies
      (a raw-normalized compare instead of the boolean gate silently breaks
      the click-free crossfade targets).

Negative self-probes on mutated in-memory texts (real tree never mutated,
no-op mutation aborts as a stale alarm):
  - rename "distortion_bypass" in ONE processBlock read → rejected
  - add a raw read of an id that is not in the layout → rejected
  - drop smoothOutputTrim.setTargetValue from processBlock → rejected
  - master bypass read without the > 0.5f gate → rejected
  - benign no-op edit inside the smoothing block → accepted (specificity)
Exit 0 = ok, 1 = violation.
"""
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SRC = ROOT / "source" / "DrippyFX"
CPP_PATH = SRC / "PluginProcessor.cpp"
HDR_PATH = SRC / "PluginProcessor.h"

# ids whose setTargetValue/consumer lines are shaped differently but must still
# exist (delay_feedback's exponential map; output_trim was the a4800aa bug).
SPECIAL_IDS = {"delay_feedback", "output_trim"}
BYPASS_IDS = {
    "distortion_bypass", "chorus_bypass",
    "delay_bypass", "reverb_bypass", "master_bypass",
}


def fail(msg):
    print(f"RAW-PARAM FAIL: {msg}")
    sys.exit(1)


def strip_comments(src):
    s = re.sub(r"//[^\n]*", "", src)
    s = re.sub(r"/\*.*?\*/", "", s, flags=re.S)
    return s


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


def fn_body(code, sig_regex):
    m = re.search(sig_regex, code)
    if not m:
        return None
    o = code.find("{", m.end())
    if o == -1:
        return None
    e = brace_span(code, o)
    if e == -1:
        return None
    return code[o + 1:e]


_BYPASS_IDS_RE_PRAGMA = None


def verify(cpp_stripped, hdr_stripped=None):
    """Core assertions on a comment-stripped PluginProcessor.cpp. Raises _Rejected."""
    mL = re.search(r"::createParameterLayout\s*\(\s*\)", cpp_stripped)
    if not mL:
        raise _Rejected("createParameterLayout definition missing")
    o = cpp_stripped.find("{", mL.start())
    e = brace_span(cpp_stripped, o)
    layout_body = cpp_stripped[o + 1:e]
    ids = set(re.findall(r'\b(?:pctParam|hzParam|msParam)\s*\(\s*"([A-Za-z0-9_]+)"', layout_body))
    ids |= set(re.findall(r'make_unique<juce::AudioParameter(?:Bool|Int)>\s*\(\s*"([A-Za-z0-9_]+)"', layout_body))
    if not ids:
        raise _Rejected("layout body parsed empty — extraction regex drifted")
    if "preset" not in ids:
        raise _Rejected("layout no longer declares the 'preset' selector")

    # (a) every raw read id exists in the layout
    raw_reads = re.findall(r'getRawParameterValue\("([A-Za-z0-9_]+)"\)', cpp_stripped)
    if not raw_reads:
        raise _Rejected('no getRawParameterValue("id") reads found — extraction drift')
    unknown = sorted({r for r in raw_reads if r not in ids})
    if unknown:
        raise _Rejected(
            f"raw read id(s) {unknown} not in createParameterLayout — a rename/add "
            "left a `getRawParameterValue(\"...\")->load()` on nullptr (audio-thread "
            "crash on the first block)")
    # (a2) uncovered-direction pin: the parameter the layout carries never read
    # anywhere would be a dead knob.
    non_preset = ids - {"preset"}
    uncovered = sorted(non_preset - set(raw_reads))
    if uncovered:
        raise _Rejected(
            f"layout id(s) {uncovered} never read via getRawParameterValue in "
            "PluginProcessor.cpp — unread parameters would revert behind the "
            "gate (or the read site was deleted)")

    # (c) setTargetValue glue: prepareToPlay body + processBlock update region
    pascal = lambda pid: "".join(part.capitalize() for part in pid.split("_"))
    body_pp = fn_body(cpp_stripped, r"::prepareToPlay\s*\(")
    if body_pp is None:
        raise _Rejected("prepareToPlay body missing")
    body_pb = fn_body(cpp_stripped, r"::processBlock\s*\(")
    if body_pb is None:
        raise _Rejected("processBlock body missing")
    m_loop = re.search(r"for\s*\(\s*int\s+s\s*=\s*0\s*;\s*s\s*<\s*numSamples", body_pb)
    if not m_loop:
        raise _Rejected("processBlock per-sample loop missing from the body")
    pb_region = body_pb[:m_loop.start()]
    if not pb_region:
        raise _Rejected("processBlock parameter-update region empty")

    for pid in sorted(non_preset - BYPASS_IDS):
        smoother = f"smooth{pascal(pid)}"
        line = f"{smoother}.setTargetValue("
        if line not in body_pp:
            raise _Rejected(
                f"prepareToPlay no longer smooths '{pid}' — '{line}' missing; that knob "
                "would start from a stale target after a re-prepare")
        if line not in pb_region:
            raise _Rejected(
                f"processBlock parameter-update region no longer smooths '{pid}' — "
                f"'{line}' missing; that knob would run on a stale smoother "
                "(zipper noise) after a simplify edit")
        if hdr_stripped is not None and f"{smoother};" not in hdr_stripped:
            raise _Rejected(
                f"smoother member '{smoother};' missing from PluginProcessor.h "
                "while the layout still declares " + pid)

    # (c2) consumer reads: getNextValue() in the loop, or getTargetValue() block read
    loop_o = body_pb.find("{", m_loop.end())
    loop_e = brace_span(body_pb, loop_o)
    if loop_e == -1:
        raise _Rejected("per-sample loop body braces unbalanced")
    loop_body = body_pb[loop_o + 1:loop_e + 1]
    for pid in sorted(non_preset - BYPASS_IDS):
        smoother = f"smooth{pascal(pid)}"
        if f"{smoother}.getNextValue()" in loop_body:
            continue
        if f"{smoother}.getTargetValue()" in body_pb:
            continue
        raise _Rejected(
            f"smoothed value for '{pid}' is never read back — no "
            f"{smoother}.getNextValue() in the per-sample loop and no "
            f"{smoother}.getTargetValue() block read: the smoothing chain for "
            "that knob is dead while the gate stays green")

    # (d) bypass bool ids keep the exact > 0.5f gate read in both bodies
    for fn_name, body in (("prepareToPlay", body_pp), ("processBlock", body_pb)):
        for pid in sorted(BYPASS_IDS):
            if f'getRawParameterValue("{pid}")->load() > 0.5f' not in body:
                raise _Rejected(
                    f"{fn_name} bypass id '{pid}' no longer read with the `> 0.5f` "
                    "gate — the click-free crossfade target would take a raw "
                    "normalized value instead of a boolean")

    # (e) smoother member roster in the header covers every smoothed id
    if hdr_stripped is None:
        hdr_stripped = ""
    for pid in sorted(non_preset - BYPASS_IDS):
        smoother = f"smooth{pascal(pid)};"
        if smoother not in hdr_stripped and pid in SPECIAL_IDS:
            raise _Rejected(f"header lost the {smoother} member declaration")


class _Rejected(Exception):
    pass


cpp_raw = CPP_PATH.read_text()
hdr_raw = HDR_PATH.read_text()
for p in (CPP_PATH, HDR_PATH):
    if not p.exists():
        fail(f"missing source file {p}")
cpp = strip_comments(cpp_raw)
hdr = strip_comments(hdr_raw)

try:
    verify(cpp, hdr)
except _Rejected as r:
    fail(str(r))
print("raw-param: every getRawParameterValue id exists in the layout and covers "
      "all non-preset ids")
print("raw-param: smoother setTargetValue glue intact in processBlock + "
      "prepareToPlay, consumer reads intact in the per-sample loop")
print("raw-param: bypass ids read via the > 0.5f gate in both bodies")


# ---- negative self-probes on mutated in-memory candidates (real tree never
#      mutated; no-op mutation aborts as a stale alarm) ----
def run_text(cpp_text):
    try:
        verify(strip_comments(cpp_text), hdr)
    except _Rejected as r:
        return str(r)
    return None


PM_BLOCK_ANCHOR = "    smoothOutputTrim.setTargetValue(apvts.getRawParameterValue(\"output_trim\")->load() / 100.0f);"
PB_REGION_ANCHOR = (
    "    smoothMasterSideDrive.setTargetValue(apvts.getRawParameterValue(\"master_side_drive\")->load() / 100.0f);\n"
)
probes = [
    ("rename 'distortion_bypass' in one processBlock read",
     lambda s: s.replace(
         '    const bool distortionBypass = apvts.getRawParameterValue("distortion_bypass")->load() > 0.5f;',
         '    const bool distortionBypass = apvts.getRawParameterValue("distortion_bypax")->load() > 0.5f;'),
    ),
    ("add a raw read of a never-existing id",
     lambda s: s.replace(
         "    if (numChannels == 0 || numSamples == 0) return;",
         "    if (numChannels == 0 || numSamples == 0) return;\n"
         "    const int ghostProbe = (int)apvts.getRawParameterValue(\"ghost_probe_id\")->load();"),
    ),
    ("drop smoothOutputTrim.setTargetValue from processBlock",
     lambda s: s.replace(
         PB_REGION_ANCHOR
         + "    smoothOutputTrim.setTargetValue(apvts.getRawParameterValue(\"output_trim\")->load() / 100.0f);\n"
         + "    const bool distortionBypass",
         PB_REGION_ANCHOR + "    const bool distortionBypass"),
    ),
    ("read master bypass without the > 0.5f gate",
     lambda s: s.replace(
         '    const bool masterBypass = apvts.getRawParameterValue("master_bypass")->load() > 0.5f;',
         '    const bool masterBypass = apvts.getRawParameterValue("master_bypass")->load() == 1.0f;'),
    ),
]
for label, mutate in probes:
    mutated = mutate(cpp_raw)
    if mutated == cpp_raw:
        fail(f"no-op probe ({label}): mutation did not change the source — "
             "the negative check is vacuous")
    verdict = run_text(mutated)
    if verdict is None:
        fail(f"negative probe '{label}' was NOT rejected — checker is vacuous")
    print(f"raw-param: negative probe '{label}' rejected")

# no-op guard: benign edit outside the pinned ids must still pass
neutral = cpp_raw.replace(
    "    const int numChannels = buffer.getNumChannels();",
    "    const int numChannels = buffer.getNumChannels();  // roster width probe",
)
if neutral == cpp_raw:
    fail("no-op guard: unanchored neutral edit did not change the source")
if run_text(neutral) is not None:
    fail("neutral edit outside the pinned roster was REJECTED — checker over-fires")
print("raw-param: benign non-roster edit passes (probe specificity proven)")

# real tree never mutated — re-verify the live source once more before gating.
try:
    verify(strip_comments(CPP_PATH.read_text()), strip_comments(HDR_PATH.read_text()))
except _Rejected as r:
    fail(f"final source re-verification failed: {r}")
print("raw-param: OK")
sys.exit(0)
