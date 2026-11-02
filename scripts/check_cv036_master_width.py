#!/usr/bin/env python3
"""Headless checker: master width is 0..200% and the identity side gain (CV-036).

The shipped master width had two coupled defects:

  1. createParameterLayout registered it through the shared `pctParam` helper
     (range 0..100, default 100), so every stored preset width above 100 —
     the factory presets use 105 through 140 — was clamped back to 100 on load;
  2. the per-sample master gate remapped the smoothed value with the retired
     `width = 0.5f + sMasterWidth * 1.5f` expansion, so 0% rendered half-wide
     (never mono) and 100% rendered double-wide (never the original image).

The fix gives master_width its own juce::AudioParameterFloat with range
0..200, interval 0.1, default 100 and the same percent formatting as the
shared helper, and feeds `width = sMasterWidth` into the unchanged
`MasterOutputStage::process`, where `side *= width` applies it.

Asserts on the real tree (comment-stripped, brace-matched):
  (a) master_width is registered by its own direct AudioParameterFloat with
      NormalisableRange(0.0f, 200.0f, 0.1f) and default 100.0f, keeps the
      percent label/formatting contract, and is NOT registered via pctParam;
  (b) the shared pctParam helper still has its 0..100 / 0.1f range and the
      exact same set of other percentage registrations;
  (c) the highest stored preset mWid (from struct P / presets[36]) is 140 and
      fits inside the new range while exceeding the old 0..100 range;
  (d) both smoothing sites read `getRawParameterValue("master_width")->load()
      / 100.0f` and both fallbacks use declaredPercentTarget (declared default
      100 / 100 = 1.0 identity), with the consumer getNextValue in the loop;
  (e) the master gate renders `float width = sMasterWidth;` — no offset, no
      scale factor — and passes it to masterOutput.process;
  (f) MasterOutputStage::process still applies `side *= width`.

Negative probes (in-memory mutated copies; a stale mutation aborts, the real
tree is never mutated):
  - restore the retired 0.5f + sMasterWidth * 1.5f formula -> rejected;
  - zero the width -> rejected;
  - shrink the own range back to 0..100 (the preset clamp) -> rejected;
  - change the own default or interval -> rejected;
  - register master_width through pctParam again -> rejected;
  - change the shared pctParam range -> rejected;
  - rename another percent registration -> rejected;
  - change either smoothing read to /200 -> rejected;
  - swap a declaredPercentTarget fallback for declaredTarget -> rejected;
  - drop one smoothing site -> rejected;
  - raise a stored preset mWid past the range -> rejected;
  - drop `side *= width` -> rejected.
Benign probes (must stay accepted): add `const` to the width local; add
whitespace before the width semicolon.

Exit 0 = ok, 1 = violation with a cited diagnostic, 2 = setup/read failure.
"""
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SRC = ROOT / "source" / "DrippyFX"
CPP_PATH = SRC / "PluginProcessor.cpp"
EFFECTS_PATH = SRC / "dsp" / "CorvusEffects.h"

# Every id still registered through the shared pctParam helper. master_width is
# deliberately absent: it owns a wider range and must not rejoin this roster.
PCT_IDS = [
    "overall", "fatness", "chorus_depth", "chorus_mix",
    "delay_feedback", "delay_mix", "delay_damping", "delay_mod",
    "reverb_size", "reverb_damping", "reverb_mix", "reverb_mod",
    "master_drive", "master_mid_drive", "master_side_drive", "output_trim",
]

MAX_STORED_WIDTH = 140.0
OWN_RANGE_MAX = 200.0

SMOOTH_WIDTH = (
    'smoothMasterWidth.setTargetValue(finiteSmoothingTarget('
    'apvts.getRawParameterValue("master_width")->load() / 100.0f, '
    'fallbackMasterWidth));')

PREP_FALLBACK = (
    'const float fallbackMasterWidth = '
    'declaredPercentTarget(apvts, "master_width");')

PROC_FALLBACK = (
    'const float fallbackMasterWidth = '
    'std::isfinite(smoothMasterWidth.getTargetValue()) ? '
    'smoothMasterWidth.getTargetValue() : '
    'declaredPercentTarget(apvts, "master_width");')

PROCESS_SIG = (
    r"void\s+process\s*\(\s*float\s*&\s*L\s*,\s*float\s*&\s*R\s*,"
    r"\s*float\s+midDrive\s*,\s*float\s+sideDrive\s*,\s*float\s+width\s*,"
    r"\s*bool\s+applySaturator\s*=\s*true\s*\)")


def strip_comments(src):
    src = re.sub(r"/\*.*?\*/", "", src, flags=re.S)
    src = re.sub(r"//[^\n]*", "", src)
    return src


def brace_body(code, open_idx):
    depth = 0
    for i in range(open_idx, len(code)):
        if code[i] == "{":
            depth += 1
        elif code[i] == "}":
            depth -= 1
            if depth == 0:
                return code[open_idx + 1:i]
    return None


def body_after(code, match):
    opening = code.find("{", match.end() - 1)
    if opening == -1:
        return None
    return brace_body(code, opening)


def fn_body(code, pattern):
    match = re.search(pattern, code)
    if not match:
        return None
    return body_after(code, match)


def struct_body(code, name):
    match = re.search(r"\bstruct\s+" + re.escape(name) + r"\b[^;{]*\{", code)
    if not match:
        return None
    return brace_body(code, match.end() - 1)


def function_bodies(text, pattern):
    bodies = []
    for match in re.finditer(pattern, text):
        body = body_after(text, match)
        if body is not None:
            bodies.append(body)
    return bodies


def collapse_ws(s):
    return re.sub(r"\s+", " ", s).strip()


class Reject(Exception):
    pass


def require(condition, why):
    if not condition:
        raise Reject(why)


def require_count(text, needle, expected, why):
    found = text.count(needle)
    if found != expected:
        raise Reject("%s (found %d, expected %d)" % (why, found, expected))


def parse_layout(code):
    layout = fn_body(code, r"::createParameterLayout\s*\(\s*\)")
    if layout is None:
        raise Reject("createParameterLayout body not found / brace-matched")
    return layout


def parse_pct_helper(layout):
    match = re.search(r"auto\s+pctParam\s*=\s*\[[^\]]*\]\s*\(", layout)
    if not match:
        raise Reject("shared pctParam helper not found in createParameterLayout")
    body = body_after(layout, match)
    if body is None:
        raise Reject("shared pctParam helper body not brace-matched")
    return body


def parse_direct_width(layout):
    match = re.search(
        r'make_unique<juce::AudioParameterFloat>\s*\(\s*"master_width"',
        layout)
    if not match:
        raise Reject(
            "master_width is not registered by its own direct "
            "juce::AudioParameterFloat — the 0..200% range (and the stored "
            "105-140 preset widths) cannot survive the shared pctParam 0..100")
    nxt = layout.find("params.push_back", match.end())
    region = layout[match.start():nxt if nxt != -1 else len(layout)]
    return region


def parse_presets(code):
    sp = re.search(r"struct\s+P\s*\{([^}]*)\}", code)
    if not sp:
        raise Reject("struct P field list not found")
    fields = [f.strip() for f in sp.group(1).split(",") if f.strip()]
    if "mWid" not in fields:
        raise Reject("struct P no longer has an mWid (master width) field")
    wid_index = fields.index("mWid")

    pm = re.search(r"static\s+const\s+P\s+presets\s*\[[^\]]*\]\s*=\s*\{", code)
    if not pm:
        raise Reject("presets[36] declaration not found")
    body = body_after(code, pm)
    if body is None:
        raise Reject("presets[36] initializer not brace-matched")
    entries = re.findall(r"\{([^{}]*)\}", body)
    if not entries:
        raise Reject("presets[36] initializer parsed to zero rows")

    widths = []
    for row, entry in enumerate(entries):
        values = [v.strip() for v in entry.split(",")]
        if len(values) != len(fields):
            raise Reject(
                "preset row %d has %d fields, struct P declares %d — the mWid "
                "column cannot be identified" % (row, len(values), len(fields)))
        try:
            widths.append(float(values[wid_index].rstrip("fF")))
        except ValueError:
            raise Reject(
                "preset row %d mWid value %r is not a plain number"
                % (row, values[wid_index]))
    return wid_index, widths


def verify(cpp_text, effects_text):
    code = strip_comments(cpp_text)
    effects = strip_comments(effects_text)

    layout = parse_layout(code)

    # --- (a) own range / default / formatting ------------------------------
    region = parse_direct_width(layout)
    require(
        re.search(
            r"NormalisableRange<float>\s*\(\s*0\.0f\s*,\s*200\.0f\s*,"
            r"\s*0\.1f\s*\)\s*,\s*100\.0f\s*,", region) is not None,
        "master_width must own NormalisableRange<float>(0.0f, 200.0f, 0.1f) "
        "with default 100.0f — a 0..100 range clamps the stored preset widths")
    require_count(region, '.withLabel("%")', 1,
                  "master_width must keep the percent label contract")
    require_count(region, 'juce::String(value, 1) + " %"', 1,
                  "master_width must keep the shared percent string formatting")
    require_count(region, 'text.replace("%", "").getFloatValue()', 1,
                  "master_width must keep the shared percent parse contract")
    require(
        len(re.findall(
            r'make_unique<juce::AudioParameterFloat>\s*\(\s*"master_width"',
            layout)) == 1,
        "exactly one direct master_width AudioParameterFloat declaration is "
        "expected in createParameterLayout")
    require(
        re.search(r'\bpctParam\s*\(\s*"master_width"', layout) is None,
        "master_width is registered through the shared pctParam helper again — "
        "that helper's 0..100 range clamps every preset width above 100")

    # --- (b) unchanged shared range and other percent registrations --------
    helper = parse_pct_helper(layout)
    require(
        re.search(r"NormalisableRange<float>\s*\(\s*0\s*,\s*100\s*,"
                  r"\s*0\.1f\s*\)", helper) is not None,
        "the shared pctParam helper no longer declares its 0..100 / 0.1f range "
        "— every other percentage knob would silently change range")
    pct_ids = re.findall(r'\bpctParam\s*\(\s*"([A-Za-z0-9_]+)"', layout)
    require(
        sorted(pct_ids) == sorted(PCT_IDS),
        "pctParam registration roster drifted: %r vs expected %r — only "
        "master_width may leave the shared helper"
        % (sorted(pct_ids), sorted(PCT_IDS)))

    # --- (c) stored preset widths and range coverage -----------------------
    wid_index, widths = parse_presets(code)
    require(
        len(widths) == 36,
        "expected 36 stored presets, parsed %d" % len(widths))
    highest = max(widths)
    require(
        abs(highest - MAX_STORED_WIDTH) < 1e-6,
        "highest stored preset mWid (struct P field %d) is %.1f, expected %.1f "
        "— preset width values must not change"
        % (wid_index, highest, MAX_STORED_WIDTH))
    require(
        highest > 100.0,
        "no stored preset width exceeds 100% — the 0..200 range would be "
        "unjustified / this checker would no longer catch the clamp bug")
    require(
        highest <= OWN_RANGE_MAX,
        "highest stored preset mWid %.1f exceeds the declared 0..%.0f range — "
        "the preset values would still clamp" % (highest, OWN_RANGE_MAX))

    # --- (d) both smoothing reads and fallbacks ----------------------------
    prepare = fn_body(code, r"::prepareToPlay\s*\(")
    if prepare is None:
        raise Reject("prepareToPlay body not found / brace-matched")
    prepare_flat = collapse_ws(prepare)
    require_count(
        prepare_flat, SMOOTH_WIDTH, 1,
        "prepareToPlay no longer maps master_width with "
        "`getRawParameterValue(...)->load() / 100.0f` through "
        "finiteSmoothingTarget")
    require_count(
        prepare_flat, PREP_FALLBACK, 1,
        "prepareToPlay master_width fallback is no longer "
        "declaredPercentTarget(apvts, \"master_width\") — the declared default "
        "must stay in smoothing units")

    proc = fn_body(code, r"::processBlock\s*\(")
    if proc is None:
        raise Reject("processBlock body not found / brace-matched")
    loop_match = re.search(
        r"for\s*\(\s*int\s+s\s*=\s*0\s*;\s*s\s*<\s*numSamples", proc)
    if not loop_match:
        raise Reject("processBlock per-sample loop not found")
    proc_region = collapse_ws(proc[:loop_match.start()])
    require_count(
        proc_region, SMOOTH_WIDTH, 1,
        "processBlock no longer maps master_width with "
        "`getRawParameterValue(...)->load() / 100.0f` through "
        "finiteSmoothingTarget")
    require_count(
        proc_region, PROC_FALLBACK, 1,
        "processBlock master_width fallback is no longer "
        "`isfinite(current target) ? current target : "
        "declaredPercentTarget(...)` — a stale or wrong-unit fallback would "
        "seed the smoother 100x off")

    loop_opening = proc.find("{", loop_match.end())
    loop_body = brace_body(proc, loop_opening) if loop_opening != -1 else None
    if loop_body is None:
        raise Reject("processBlock per-sample loop body not brace-matched")
    require(
        re.search(
            r"const\s+float\s+sMasterWidth\s*=\s*"
            r"smoothMasterWidth\.getNextValue\(\)\s*;", loop_body) is not None,
        "the per-sample loop no longer consumes "
        "smoothMasterWidth.getNextValue() for sMasterWidth")

    dpt = fn_body(code, r"float\s+declaredPercentTarget\s*\(")
    if dpt is None:
        raise Reject("declaredPercentTarget helper not found")
    require(
        "declaredTarget(state, paramId)" in dpt and "/ 100.0f" in dpt,
        "declaredPercentTarget is no longer declaredTarget / 100.0f — with "
        "default 100 that fallback must be the 1.0 identity")

    # --- (e) identity render width in the master gate ----------------------
    gate_match = re.search(r"gMaster > 0\.001f", proc)
    if not gate_match:
        raise Reject("master gate `gMaster > 0.001f` not found in processBlock")
    gate = body_after(proc, gate_match)
    if gate is None:
        raise Reject("master gate body not brace-matched")
    require(
        re.search(
            r"(?:const\s+)?float\s+width\s*=\s*sMasterWidth\s*;",
            gate) is not None,
        "master gate width is not the identity `float width = sMasterWidth;` "
        "— the retired 0.5f + sMasterWidth * 1.5f expansion makes 100% "
        "double-wide and 0% half-wide")
    require_count(
        gate, "masterOutput.process(ml, mr, midDrive, sideDrive, width);", 1,
        "masterOutput.process(ml, mr, midDrive, sideDrive, width) call missing "
        "or reshaped in the master gate")

    # --- (f) the stage still applies side *= width -------------------------
    master = struct_body(effects, "MasterOutputStage")
    if master is None:
        raise Reject("struct MasterOutputStage not found / brace-matched")
    processes = function_bodies(master, PROCESS_SIG)
    if not processes:
        raise Reject("MasterOutputStage::process body not found")
    process = processes[0]
    if len(process) < 700:
        raise Reject(
            "brace matching drifted (MasterOutputStage::process body is only "
            "%d chars) - do not trust green" % len(process))
    require_count(
        process, "side *= width;", 1,
        "MasterOutputStage::process no longer applies `side *= width;` — the "
        "width knob would stop changing the stereo image at all")


def run(cpp_text, effects_text):
    try:
        verify(cpp_text, effects_text)
    except Reject as exc:
        return str(exc)
    return None


def main():
    for path in (CPP_PATH, EFFECTS_PATH):
        if not path.exists():
            print("CV036-MASTER-WIDTH SETUP FAIL: missing %s" % path)
            return 2
    try:
        cpp = CPP_PATH.read_text(encoding="utf-8", errors="replace")
        effects = EFFECTS_PATH.read_text(encoding="utf-8", errors="replace")
    except OSError as exc:
        print("CV036-MASTER-WIDTH SETUP FAIL: %s" % exc)
        return 2

    verdict = run(cpp, effects)
    if verdict is not None:
        print("CV036-MASTER-WIDTH FAIL: %s" % verdict)
        return 1
    print("cv036-master-width: own 0..200%% range/default, stored preset mWid "
          "%.0f, unchanged shared percent roster, both /100 smoothing reads, "
          "identity width and side *= width pinned" % MAX_STORED_WIDTH)

    def cpp_mutate(old, new, count=0):
        return lambda c: (c.replace(old, new, count) if count else
                          c.replace(old, new))

    probes = [
        ("restore the retired 0.5f + sMasterWidth * 1.5f formula",
         "cpp", cpp_mutate(
             "float width = sMasterWidth;",
             "float width = 0.5f + sMasterWidth * 1.5f;", 1)),
        ("zero the width local",
         "cpp", cpp_mutate(
             "float width = sMasterWidth;",
             "float width = 0.0f;", 1)),
        ("shrink the own range back to 0..100",
         "cpp", cpp_mutate(
             "juce::NormalisableRange<float>(0.0f, 200.0f, 0.1f), 100.0f",
             "juce::NormalisableRange<float>(0.0f, 100.0f, 0.1f), 100.0f", 1)),
        ("change the own default 100.0f -> 50.0f",
         "cpp", cpp_mutate(
             "juce::NormalisableRange<float>(0.0f, 200.0f, 0.1f), 100.0f",
             "juce::NormalisableRange<float>(0.0f, 200.0f, 0.1f), 50.0f", 1)),
        ("change the own interval 0.1f -> 1.0f",
         "cpp", cpp_mutate(
             "200.0f, 0.1f), 100.0f",
             "200.0f, 1.0f), 100.0f", 1)),
        ("re-register master_width through the shared pctParam helper",
         "cpp", cpp_mutate(
             '    params.push_back(std::make_unique<juce::AudioParameterFloat>(\n'
             '        "master_width"',
             '    params.push_back(pctParam("master_width", "Master Width", 100));\n'
             '    params.push_back(std::make_unique<juce::AudioParameterFloat>(\n'
             '        "master_width"', 1)),
        ("widen the shared pctParam range to 0..200",
         "cpp", cpp_mutate(
             "juce::NormalisableRange<float>(0, 100, 0.1f)",
             "juce::NormalisableRange<float>(0, 200, 0.1f)", 1)),
        ("rename another percentage registration",
         "cpp", cpp_mutate(
             'pctParam("output_trim", "Output Trim", 100)',
             'pctParam("output_trimx", "Output Trim", 100)', 1)),
        ("change both smoothing reads to /200",
         "cpp", cpp_mutate(
             'getRawParameterValue("master_width")->load() / 100.0f',
             'getRawParameterValue("master_width")->load() / 200.0f')),
        ("swap a fallback to the native declaredTarget",
         "cpp", cpp_mutate(
             'declaredPercentTarget(apvts, "master_width")',
             'declaredTarget(apvts, "master_width")')),
        ("drop the prepareToPlay master_width smoothing site",
         "cpp", cpp_mutate(SMOOTH_WIDTH, "", 1)),
        ("raise a stored preset mWid above the range",
         "cpp", cpp_mutate(
             "80,  15, 140,   5,  30", "80,  15, 240,   5,  30", 1)),
        ("drop side *= width from MasterOutputStage::process",
         "effects", lambda t: t.replace("side *= width;", "side *= 1.0f;", 1)),
    ]
    for label, target, mutate in probes:
        before = cpp if target == "cpp" else effects
        mutated = mutate(before)
        if mutated == before:
            print("CV036-MASTER-WIDTH FAIL: probe '%s' is stale: mutation did "
                  "not apply - cannot trust the negative check" % label)
            return 1
        verdict = (run(mutated, effects) if target == "cpp"
                   else run(cpp, mutated))
        if verdict is None:
            print("CV036-MASTER-WIDTH FAIL: probe '%s' was NOT rejected - "
                  "checker is vacuous" % label)
            return 1
        print("cv036-master-width: probe '%s' rejected (%s)"
              % (label, verdict[:88]))

    benign = [
        ("add const to the width local",
         cpp.replace("float width = sMasterWidth;",
                     "const float width = sMasterWidth;", 1)),
        ("add whitespace before the width semicolon",
         cpp.replace("float width = sMasterWidth;",
                     "float width = sMasterWidth ;", 1)),
    ]
    for label, mutated in benign:
        if mutated == cpp:
            print("CV036-MASTER-WIDTH FAIL: benign probe '%s' is stale: the "
                  "edit did not apply" % label)
            return 1
        verdict = run(mutated, effects)
        if verdict is not None:
            print("CV036-MASTER-WIDTH FAIL: benign probe '%s' was rejected - "
                  "checker over-fires: %s" % (label, verdict))
            return 1
        print("cv036-master-width: benign probe '%s' accepted" % label)

    if run(CPP_PATH.read_text(encoding="utf-8", errors="replace"),
           EFFECTS_PATH.read_text(encoding="utf-8", errors="replace")) is not None:
        print("CV036-MASTER-WIDTH FAIL: final live-source re-verification "
              "failed")
        return 1
    print("CV036-MASTER-WIDTH OK (13 negatives, 2 benign edits accepted)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
