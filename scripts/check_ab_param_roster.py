#!/usr/bin/env python3
"""Headless checker: A/B-compare parameter roster pinned against the APVTS layout.

abParamIds[24] (PluginProcessor.cpp) and NUM_AB_PARAMS = 24 (PluginProcessor.h)
are hand-maintained copies of the parameter set. If a future parameter
rename/add drifts the table from createParameterLayout, loadSlotA restores only
the stale ids and the new/renamed knob snaps to its default after every A/B
toggle with no error.

Asserts (comment-stripped):
  (a) abParamIds[] extracted by regex is unique and equals the layout id set
      (pctParam/msParam/hzParam first-string args + direct
      make_unique<juce::AudioParameterBool/Int> first args, minus "preset").
  (b) NUM_AB_PARAMS in PluginProcessor.h equals len(abParamIds).

Negative self-probes on mutated copies (real tree never mutated, no-op
mutation aborts as a stale alarm): drop "overall" from abParamIds; add
"preset" to abParamIds; rename a layout id without the table.
Exit 0 = ok, 1 = violation.
"""
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SRC = ROOT / "source" / "DrippyFX"


def fail(msg):
    print(f"AB-ROSTER FAIL: {msg}")
    sys.exit(1)


def strip_comments(src):
    src = re.sub(r"//[^\n]*", "", src)
    src = re.sub(r"/\*.*?\*/", "", src, flags=re.S)
    return src


cpp_path = SRC / "PluginProcessor.cpp"
hdr_path = SRC / "PluginProcessor.h"
for p in (cpp_path, hdr_path):
    if not p.exists():
        fail(f"missing source file {p}")
cpp_raw = cpp_path.read_text()
hdr_raw = hdr_path.read_text()
cpp = strip_comments(cpp_raw)
hdr = strip_comments(hdr_raw)

# (1) extract abParamIds[] (the line range is the SoT for the A/B roster)
ab_ids = None
ab_decl_line = None
m_array = re.search(r"constexpr\s+const\s+char\*\s+abParamIds\s*\[\s*(\w+)\s*\]\s*=\s*\{", cpp)
if not m_array:
    m_array = re.search(r"const\s+char\*\s+abParamIds\s*\[\s*\d*\s*\]\s*=\s*\{", cpp)
if not m_array:
    fail("abParamIds[] declaration missing from PluginProcessor.cpp")
declared_size = m_array.group(1) if m_array.group(1).isdigit() else None
i = cpp.find("{", m_array.start())
depth = 0
j = i
while j < len(cpp):
    if cpp[j] == "{":
        depth += 1
    elif cpp[j] == "}":
        depth -= 1
        if depth == 0:
            break
    j += 1
body = cpp[i:j + 1]
ab_ids = re.findall(r'"([A-Za-z0-9_]+)"', body)
ab_decl_line = cpp_raw[:m_array.start()].count("\n") + 1
if not ab_ids:
    fail(f"abParamIds[] (PluginProcessor.cpp:{ab_decl_line}) parsed to an empty id list")
if len(set(ab_ids)) != len(ab_ids):
    dupes = sorted({x for x in ab_ids if ab_ids.count(x) > 1})
    fail(f"abParamIds[] (PluginProcessor.cpp:{ab_decl_line}) contains duplicate ids: {dupes}")

# (2) extract the createParameterLayout id set minus "preset"
m_layout = re.search(r"::createParameterLayout\s*\(\s*\)", cpp)
if not m_layout:
    fail("createParameterLayout definition missing from PluginProcessor.cpp")
i = cpp.find("{", m_layout.start())
depth = 0
j = i
while j < len(cpp):
    if cpp[j] == "{":
        depth += 1
    elif cpp[j] == "}":
        depth -= 1
        if depth == 0:
            break
    j += 1
layout_body = cpp[i:j + 1]
layout_ids = set(re.findall(r'\b(?:pctParam|hzParam|msParam)\s*\(\s*"([A-Za-z0-9_]+)"', layout_body))
layout_ids |= set(re.findall(r'make_unique<juce::AudioParameter(?:Bool|Int)>\s*\(\s*"([A-Za-z0-9_]+)"', layout_body))
layout_ids.discard("preset")  # preset is the combo box selector, never A/B'd
if not layout_ids:
    fail("createParameterLayout body parsed to an empty helper/id set — extraction regex drifted?")

# (3) set equality: the A/B tables must equal the layout minus "preset"
missing_in_ab = sorted(layout_ids - set(ab_ids))
extra_in_ab = sorted(set(ab_ids) - layout_ids)
if missing_in_ab or extra_in_ab:
    fail(f"abParamIds[] (PluginProcessor.cpp:{ab_decl_line}) drifted from "
         f"createParameterLayout minus 'preset': layout-only={missing_in_ab} "
         f"ab-only={extra_in_ab} — a renamed/added parameter would snap to its "
         "default after every A/B toggle (loadSlotA restores only the stale ids)")
print(f"ab-roster: abParamIds == layout minus 'preset' ({len(ab_ids)}/{len(ab_ids)} ids)")

# (4) NUM_AB_PARAMS consistency with the array decl
m_num = re.search(r"NUM_AB_PARAMS\s*=\s*(\d+)", hdr)
if not m_num:
    fail("NUM_AB_PARAMS declaration missing from PluginProcessor.h")
num_declared = int(m_num.group(1))
num_hdr_line = hdr_raw[:m_num.start()].count("\n") + 1
if num_declared != len(ab_ids):
    fail(f"NUM_AB_PARAMS={num_declared} (PluginProcessor.h:{num_hdr_line}) != "
         f"len(abParamIds)={len(ab_ids)} (PluginProcessor.cpp:{ab_decl_line}) — "
         "snapshotA/snapshotB sized from NUM_AB_PARAMS would under/over-restore")
num_str = str(num_declared)
if declared_size is not None and declared_size != num_str:
    fail(f"abParamIds[{declared_size}] (PluginProcessor.cpp:{ab_decl_line}) "
         f"declared size disagrees with NUM_AB_PARAMS={num_str}")
print(f"ab-roster: NUM_AB_PARAMS={num_declared} matches len(abParamIds)={len(ab_ids)}")


# (5) negative self-probes on mutated copies (sibling style)
def run_text(cpp_text, hdr_text):
    """Re-run the core assertions on a mutated candidate. None=pass, else reason."""
    try:
        a, b = _verify(cpp_text, hdr_text)
    except _Rejected as r:
        return str(r)
    return None


class _Rejected(Exception):
    pass


def _verify(cpp_text, hdr_text):
    stripped = strip_comments(cpp_text)
    m = (re.search(r"const\s+char\*\s+abParamIds\s*\[\s*\d*\s*\]\s*=\s*\{", stripped)
         or re.search(r"const\s+char\s*\*\s+abParamIds\s*\[\s*\d*\s*\]\s*=\s*\{", stripped))
    if not m:
        raise _Rejected("abParamIds declaration missing")
    i = stripped.find("{", m.start())
    depth = 0
    j = i
    while j < len(stripped):
        if stripped[j] == "{":
            depth += 1
        elif stripped[j] == "}":
            depth -= 1
            if depth == 0:
                break
        j += 1
    ab = re.findall(r'"([A-Za-z0-9_]+)"', stripped[i:j + 1])
    ml = re.search(r"::createParameterLayout\s*\(\s*\)", stripped)
    if not ml:
        raise _Rejected("createParameterLayout missing")
    i2 = stripped.find("{", ml.start())
    depth = 0
    j2 = i2
    while j2 < len(stripped):
        if stripped[j2] == "{":
            depth += 1
        elif stripped[j2] == "}":
            depth -= 1
            if depth == 0:
                break
        j2 += 1
    lb = stripped[i2:j2 + 1]
    lids = set(re.findall(r'\b(?:pctParam|hzParam|msParam)\s*\(\s*"([A-Za-z0-9_]+)"', lb))
    lids |= set(re.findall(r'make_unique<juce::AudioParameter(?:Bool|Int)>\s*\(\s*"([A-Za-z0-9_]+)"', lb))
    lids.discard("preset")
    if len(set(ab)) != len(ab):
        raise _Rejected("duplicate ab ids accepted")
    if set(ab) != lids:
        raise _Rejected(
            f"roster drift accepted: layout-only={sorted(lids - set(ab))} "
            f"ab-only={sorted(set(ab) - lids)}")
    mn = re.search(r"NUM_AB_PARAMS\s*=\s*(\d+)", strip_comments(hdr_text))
    if not mn or int(mn.group(1)) != len(ab):
        raise _Rejected("NUM_AB_PARAMS mismatch accepted")
    return True, True


ARRAY_ANCHOR = ('abParamIds[24] = {\n    "overall",')
probes = [
    ("drop 'overall' from abParamIds",
     lambda s: s.replace(ARRAY_ANCHOR, 'abParamIds[24] = {\n    "fatness",')),
    ("add 'preset' to abParamIds",
     lambda s: s.replace('    "output_trim"\n};', '    "output_trim", "preset"\n};')),
    ("rename layout id without the table",
     lambda s: s.replace('pctParam("delay_mod", "Delay Mod", 30)',
                         'pctParam("delay_modx", "Delay Mod", 30)')),
    # no-op guard probe mutates UNPINNED text and must still pass
]
for label, mutate in probes:
    mutated = mutate(cpp_raw)
    if mutated == cpp_raw:
        fail(f"no-op probe ({label}): mutation did not change the source — "
             "the negative check is vacuous")
    verdict = run_text(mutated, hdr_raw)
    if verdict is None:
        fail(f"negative probe '{label}' was NOT rejected — checker is vacuous")
    print(f"ab-roster: negative probe '{label}' rejected")

# no-op guard: an edit outside the pinned ids must still pass
shifted = cpp_raw.replace("getNumPrograms() { return 36; }", "getNumPrograms() { return 37; }")
if shifted == cpp_raw:
    fail("no-op guard: unanchored neutral edit did not change the source")
if run_text(shifted, hdr_raw) is not None:
    fail("neutral edit outside the roster was REJECTED — checker over-fires")
print("ab-roster: neutral no-roster edit passes (probe specificity proven)")
print("ab-roster: OK")
