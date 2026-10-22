#!/usr/bin/env python3
"""Headless regression for the CV-023 editor slice.

Two defects are pinned together because they share PluginEditor.cpp:

  (1) The knob context menu is shown asynchronously. Each menu item used to
      capture raw `&proc` / `&k` references, so a menu callback that fired
      after the knob or editor was destroyed touched freed memory. The editor
      must capture the parameter id by value and guard every deferred
      component/processor access with juce::Component::SafePointer.
  (2) The master-control rows consumed the whole content height before the
      2x2 FX grid was laid out, leaving the grid a collapsed ~20px. The grid
      is now carved out first, and each section derives explicit rectangles
      for its knob, label and bypass controls.

Edits outside those two areas must still pass (a benign no-op probe is run on
an in-memory copy; the real tree is never mutated).

Geometry model
--------------
The checker parses the reference-pixel constants declared at the top of
PluginEditor.cpp::resized() and replays the same integer rectangle arithmetic
for the supported minimum (1000x600) and default (1200x700) sizes. It asserts,
for every knob, label and bypass control:

  * positive width/height and a usable minimum size;
  * containment inside its owning section/rail and inside the editor;
  * no pairwise overlap with any sibling control.

Negative probes (in-memory only, each must be rejected):
  * collapse the grid by changing the row divisor (the old 20px bug);
  * squeeze the delay column until its last knob is below the usable width;
  * collapse the bypass width to zero;
  * reintroduce a raw `&k` capture in the async context menu;
  * drop the slot-B reseed (the preserved A/B initialization contract).

Exit 0 only when the real tree passes every assertion, every probe is
rejected, and the benign edit is accepted.
"""
import math
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
ED = ROOT / "source" / "DrippyFX" / "PluginEditor.cpp"

MIN_SIZE = (1000, 600)
DEFAULT_SIZE = (1200, 700)

INT_CONSTANTS = [
    "kTopSectionRef", "kTitleRef", "kPresetInsetXRef", "kPresetInsetYRef",
    "kPresetLabelRef", "kPresetButtonRailRef", "kPresetButtonHeightRef",
    "kPresetButtonMinHeightRef", "kMeterRef", "kFooterRef",
    "kContentInsetXRef", "kContentInsetYRef", "kRailGapRef", "kRailMinRef",
    "kRailMaxRef", "kOverallRowRef", "kOverallKnobRef", "kOverallLabelRef",
    "kMasterDriveRowRef", "kMasterDriveKnobRef", "kMasterDriveLabelRef",
    "kMasterBypassWidthRef", "kMasterBypassHeightRef", "kMasterSideRowRef",
    "kMasterSideKnobRef", "kMasterSideGapRef", "kMasterSideLabelRef",
    "kOutputTrimKnobRef", "kOutputTrimLabelRef", "kRailKnobInsetRef",
    "kGridGapRef", "kGridRowsRef", "kSectionPadXRef", "kSectionPadYRef",
    "kSectionLabelRef", "kSectionBypassRef", "kSectionBypassGapRef",
    "kSectionBypassWidthRef", "kSectionMinGapRef", "kSectionMaxGapRef",
    "kSectionMinKnobRef", "kDistortionMaxKnobRef", "kChorusMaxKnobRef",
    "kDelayMaxKnobRef", "kReverbMaxKnobRef",
]

USABLE_KNOB = 44
USABLE_LABEL_H = 14
USABLE_LABEL_W = 40
USABLE_BYPASS_W = 40
USABLE_BYPASS_H = 16


class Reject(Exception):
    pass


def strip_comments(text):
    text = re.sub(r"/\*.*?\*/", "", text, flags=re.S)
    return re.sub(r"//[^\n]*", "", text)


def brace_block(text, open_idx):
    depth = 0
    for i in range(open_idx, len(text)):
        if text[i] == "{":
            depth += 1
        elif text[i] == "}":
            depth -= 1
            if depth == 0:
                return text[open_idx:i + 1]
    raise Reject("unbalanced brace block")


# ---------------------------------------------------------------------------
# Source assertions
# ---------------------------------------------------------------------------
def check_async_menu(code):
    idx = code.find("k.onRightClick")
    if idx < 0:
        raise Reject("the knob's onRightClick menu builder is missing")
    brace = code.find("{", idx)
    if brace < 0:
        raise Reject("the onRightClick lambda body is missing")
    body = brace_block(code, brace)
    segment = code[idx:brace + len(body)]

    # Any capture-by-reference in this deferred callback is a lifetime bug;
    # `&k` inside the SafePointer constructor argument is not a capture and
    # is preceded by '(' rather than '[' or ','.
    if re.search(r"[\[,]\s*&", segment):
        raise Reject("async context menu reintroduced a capture-by-reference "
                     "(raw &knob/&processor can outlive the editor)")
    if not re.search(r"paramID\s*=\s*k\.linkedParamID", segment):
        raise Reject("the menu no longer captures the parameter id by value")
    if "juce::Component::SafePointer<AnimatedKnob>" not in segment:
        raise Reject("the menu no longer guards the knob with SafePointer")
    if "juce::Component::SafePointer<CorvusFXAudioProcessorEditor>" not in segment:
        raise Reject("the menu no longer guards the editor with SafePointer")
    if "if (auto* knob = safeKnob.getComponent())" not in body:
        raise Reject("deferred knob access is not checked through SafePointer")
    if "if (auto* editor = safeEditor.getComponent())" not in body:
        raise Reject("deferred editor/processor access is not checked through "
                     "SafePointer")
    if re.search(r"\bproc\s*\.", body):
        raise Reject("the menu still reaches through a raw processor reference")
    if re.search(r"\bk\s*\.", body):
        raise Reject("the menu still reaches through a raw knob reference")
    if "showMenuAsync" not in body:
        raise Reject("the context menu is no longer asynchronous")


def check_ab_contract(code):
    m = re.search(r"if\s*\(\s*!audioProcessor\.hasPersistedABSnapshots\(\)\s*\)",
                  code)
    if not m:
        raise Reject("the A/B reseed guard (!hasPersistedABSnapshots) is gone")
    brace = code.find("{", m.end())
    if brace < 0:
        raise Reject("the A/B reseed guard body is missing")
    body = brace_block(code, brace)
    if body.count("saveSlotA()") != 1 or body.count("saveSlotB()") != 1:
        raise Reject("the A/B reseed must keep exactly one saveSlotA() and one "
                     "saveSlotB(); snapshotB is a zero-initialized array and "
                     "an unsaved B loads every parameter minimum")
    if body.find("saveSlotA()") > body.find("saveSlotB()"):
        raise Reject("A/B reseed order drifted (saveSlotA must precede B)")


def parse_constants(code):
    vals = {}
    for name in INT_CONSTANTS:
        m = re.search(r"const\s+int\s+" + name + r"\s*=\s*(-?\d+)\s*;", code)
        if not m:
            raise Reject("layout constant %s is missing from resized()" % name)
        vals[name] = int(m.group(1))
    m = re.search(r"const\s+float\s+kDelayColumnShare\s*=\s*"
                  r"([0-9]*\.?[0-9]+)f\s*;", code)
    if not m:
        raise Reject("layout constant kDelayColumnShare is missing")
    vals["kDelayColumnShare"] = float(m.group(1))

    # The geometry model below is only meaningful while the source really
    # uses these constants in the carved-grid / explicit-section shapes.
    required = [
        (r"railW\s*=\s*juce::jlimit\(\s*sc\(kRailMinRef\)\s*,\s*"
         r"area\.getWidth\(\)\s*/\s*3\s*,\s*sc\(kRailMaxRef\)\s*\)",
         "the rail/grid split no longer derives railW from the available area"),
        (r"gridArea\s*=\s*area\.removeFromRight\(\s*gridW\s*\)",
         "the FX grid is no longer carved out before the master rail"),
        (r"secH\s*=\s*juce::jmax\(\s*1\s*,\s*\(gridArea\.getHeight\(\)\s*-\s*"
         r"gap\)\s*/\s*kGridRowsRef\s*\)",
         "the grid rows no longer derive their height from gridArea"),
        (r"delayW\s*=\s*juce::roundToInt\(\s*\(botRow\.getWidth\(\)\s*-\s*gap\)"
         r"\s*\*\s*kDelayColumnShare\s*\)",
         "the delay column no longer reserves its own share of the bottom row"),
        (r"content\s*=\s*reserveBypass\(\s*content\s*,\s*bypass\s*\)",
         "section layout no longer reserves a bypass strip"),
        (r"layoutSection\(\s*delArea\s*,\s*sc\(kDelayMaxKnobRef\)",
         "the delay section no longer uses the shared explicit layout"),
        (r"layoutSection\(\s*revArea\s*,\s*sc\(kReverbMaxKnobRef\)",
         "the reverb section no longer uses the shared explicit layout"),
    ]
    for pattern, why in required:
        if re.search(pattern, code) is None:
            raise Reject(why)
    return vals


# ---------------------------------------------------------------------------
# Integer rectangle model matching PluginEditor.cpp::resized()
# ---------------------------------------------------------------------------
def sc(px, scale):
    return int(math.floor(px * scale + 0.5))


def reduced(r, dx, dy):
    x, y, w, h = r
    return (x + dx, y + dy, w - 2 * dx, h - 2 * dy)


def remove_top(r, amount):
    x, y, w, h = r
    take = min(amount, h)
    return (x, y, w, take), (x, y + take, w, h - take)


def remove_bottom(r, amount):
    x, y, w, h = r
    take = min(amount, h)
    return (x, y + h - take, w, take), (x, y, w, h - take)


def remove_left(r, amount):
    x, y, w, h = r
    take = min(amount, w)
    return (x, y, take, h), (x + take, y, w - take, h)


def remove_right(r, amount):
    x, y, w, h = r
    take = min(amount, w)
    return (x + w - take, y, take, h), (x, y, w - take, h)


def centered(r, w, h):
    # JUCE Rectangle::withSizeKeepingCentre uses the integer centre point:
    # centre = (x + width / 2, y + height / 2), then subtracts new size / 2.
    x, y, rw, rh = r
    cx = x + rw // 2
    cy = y + rh // 2
    return (cx - w // 2, cy - h // 2, w, h)


def jlimit(low, high, value):
    if value < low:
        return low
    if high < value:
        return high
    return value


def layout_section(section, max_knob, n, c, scale):
    content = reduced(section, sc(c["kSectionPadXRef"], scale),
                      sc(c["kSectionPadYRef"], scale))
    bypH = max(sc(c["kSectionBypassRef"], scale), 16)
    by_row, content = remove_bottom(content, bypH)
    _, content = remove_bottom(content, sc(c["kSectionBypassGapRef"], scale))
    bypass = centered(by_row, min(by_row[2], sc(c["kSectionBypassWidthRef"],
                                              scale)), bypH)

    label_h = max(sc(c["kSectionLabelRef"], scale), 14)
    gap_x = jlimit(
        sc(c["kSectionMinGapRef"], scale),
        sc(c["kSectionMaxGapRef"], scale),
        (content[2] - n * sc(c["kSectionMinKnobRef"], scale))
        // max(1, n + 1))
    knob = min(max_knob,
               (content[2] - gap_x * (n + 1)) // max(1, n))
    knob = min(knob, max(1, content[3] - label_h))
    knob = max(1, knob)
    total_w = knob * n + gap_x * (n + 1)
    row = centered(content, total_w, knob + label_h)
    _, row = remove_left(row, gap_x)
    columns = []
    for _ in range(n):
        col, row = remove_left(row, knob)
        k_rect, col = remove_top(col, knob)
        l_rect, _ = remove_top(col, label_h)
        columns.append((k_rect, l_rect))
        _, row = remove_left(row, gap_x)
    return columns, bypass


def build_geometry(c, width, height):
    scale = min(width / 1200.0, height / 700.0)
    area = (0, 0, width, height)

    top, area = remove_top(area, sc(c["kTopSectionRef"], scale))
    title_raw, top = remove_top(top, sc(c["kTitleRef"], scale))
    title = reduced(title_raw, sc(20, scale), sc(5, scale))
    preset_area = reduced(top, sc(c["kPresetInsetXRef"], scale),
                          sc(c["kPresetInsetYRef"], scale))
    preset_label, preset_row = remove_top(
        preset_area, sc(c["kPresetLabelRef"], scale))
    ab_area, preset_selector = remove_right(
        preset_row, sc(c["kPresetButtonRailRef"], scale))
    ab_h = jlimit(sc(c["kPresetButtonMinHeightRef"], scale),
                  sc(c["kPresetButtonHeightRef"], scale),
                  top[1] + top[3] - preset_row[1])

    meter_full, area = remove_top(area, sc(c["kMeterRef"], scale))
    meter = reduced(meter_full, area[2] // 4, 0)
    _, area = remove_bottom(area, sc(c["kFooterRef"], scale))
    area = reduced(area, sc(c["kContentInsetXRef"], scale),
                   sc(c["kContentInsetYRef"], scale))

    rail_gap = sc(c["kRailGapRef"], scale)
    rail_w = jlimit(sc(c["kRailMinRef"], scale), area[2] // 3,
                    sc(c["kRailMaxRef"], scale))
    grid_w = max(1, area[2] - rail_w - rail_gap)
    grid, area = remove_right(area, grid_w)
    _, area = remove_right(area, rail_gap)
    rail = area
    rail_container = rail

    overall_row, rail = remove_top(rail, sc(c["kOverallRowRef"], scale))
    o_size = min(sc(c["kOverallKnobRef"], scale),
                 rail_w - sc(c["kRailKnobInsetRef"], scale))
    o_size = min(o_size, overall_row[3] - sc(c["kOverallLabelRef"], scale))
    o_size = max(1, o_size)
    o_area = centered(overall_row, o_size,
                      o_size + sc(c["kOverallLabelRef"], scale))
    overall_knob, o_area = remove_top(o_area, o_size)
    overall_label = o_area

    md_row, rail = remove_top(rail, sc(c["kMasterDriveRowRef"], scale))
    mdr = reduced(md_row, sc(c["kRailKnobInsetRef"], scale), 0)
    by_w = min(sc(c["kMasterBypassWidthRef"], scale), mdr[2] // 2)
    mb_area, mdr = remove_right(mdr, by_w)
    m_size = min(sc(c["kMasterDriveKnobRef"], scale),
                 md_row[3] - sc(c["kMasterDriveLabelRef"], scale))
    m_size = min(m_size, mdr[2] - sc(10, scale))
    m_size = max(1, m_size)
    m_area = centered(mdr, m_size,
                      m_size + sc(c["kMasterDriveLabelRef"], scale))
    master_knob, m_area = remove_top(m_area, m_size)
    master_label = m_area
    master_bypass, _ = remove_top(
        mb_area, min(sc(c["kMasterBypassHeightRef"], scale), mb_area[3]))

    _, rail = remove_top(rail, sc(10, scale))

    mss_row, rail = remove_top(rail, sc(c["kMasterSideRowRef"], scale))
    ms_gap = sc(c["kMasterSideGapRef"], scale)
    ms_size = min(sc(c["kMasterSideKnobRef"], scale),
                  (mss_row[2] - ms_gap * 2) // 3)
    ms_size = min(ms_size,
                  mss_row[3] - sc(c["kMasterSideLabelRef"], scale))
    ms_size = max(1, ms_size)
    ms_start = centered(mss_row, ms_size * 3 + ms_gap * 2,
                        ms_size + sc(c["kMasterSideLabelRef"], scale))
    mss = []
    for _ in range(3):
        col, ms_start = remove_left(ms_start, ms_size)
        k_rect, col = remove_top(col, ms_size)
        l_rect, _ = remove_top(col,
                               sc(c["kMasterSideLabelRef"], scale))
        mss.append((k_rect, l_rect))
        _, ms_start = remove_left(ms_start, ms_gap)

    trim_row = rail
    trim_size = min(sc(c["kOutputTrimKnobRef"], scale),
                    trim_row[2] - sc(c["kRailKnobInsetRef"], scale))
    trim_size = min(trim_size,
                    trim_row[3] - sc(c["kOutputTrimLabelRef"], scale))
    trim_size = max(1, trim_size)
    t_area = centered(trim_row, trim_size,
                      trim_size + sc(c["kOutputTrimLabelRef"], scale))
    trim_knob, t_area = remove_top(t_area, trim_size)
    trim_label = t_area

    gap = max(1, sc(c["kGridGapRef"], scale))
    sec_h = max(1, (grid[3] - gap) // c["kGridRowsRef"])
    top_row, grid = remove_top(grid, sec_h)
    top_w = max(1, (top_row[2] - gap) // 2)
    dist, top_row = remove_left(top_row, top_w)
    _, top_row = remove_left(top_row, gap)
    chor = top_row
    _, bottom = remove_top(grid, gap)
    delay_w = int(math.floor((bottom[2] - gap) * c["kDelayColumnShare"] + 0.5))
    delay, bottom = remove_left(bottom, delay_w)
    _, bottom = remove_left(bottom, gap)
    rev = bottom

    dist_cols, dist_by = layout_section(
        dist, sc(c["kDistortionMaxKnobRef"], scale), 1, c, scale)
    chor_cols, chor_by = layout_section(
        chor, sc(c["kChorusMaxKnobRef"], scale), 3, c, scale)
    delay_cols, delay_by = layout_section(
        delay, sc(c["kDelayMaxKnobRef"], scale), 5, c, scale)
    rev_cols, rev_by = layout_section(
        rev, sc(c["kReverbMaxKnobRef"], scale), 4, c, scale)

    return {
        "editor": (0, 0, width, height),
        "title": title,
        "preset_label": preset_label,
        "preset_selector": preset_selector,
        "ab_area": ab_area,
        "ab_h": ab_h,
        "meter": meter,
        "rail": rail_container,
        "grid": grid,
        "overall": (overall_knob, overall_label),
        "master": (master_knob, master_label, master_bypass),
        "mss": mss,
        "trim": (trim_knob, trim_label),
        "sections": {"distortion": dist, "chorus": chor,
                     "delay": delay, "reverb": rev},
        "section_controls": {
            "distortion": (dist_cols, dist_by),
            "chorus": (chor_cols, chor_by),
            "delay": (delay_cols, delay_by),
            "reverb": (rev_cols, rev_by),
        },
    }


def contains(outer, inner):
    ox, oy, ow, oh = outer
    x, y, w, h = inner
    return (x >= ox and y >= oy and x + w <= ox + ow
            and y + h <= oy + oh)


def overlaps(a, b):
    ax, ay, aw, ah = a
    bx, by, bw, bh = b
    return (min(ax + aw, bx + bw) > max(ax, bx)
            and min(ay + ah, by + bh) > max(ay, by))


def validate_control(label, rect, container, min_w, min_h):
    x, y, w, h = rect
    if w <= 0 or h <= 0:
        raise Reject("%s has non-positive bounds %r" % (label, rect))
    if w < min_w or h < min_h:
        raise Reject("%s is too small to be usable: %dx%d (need >=%dx%d)"
                     % (label, w, h, min_w, min_h))
    if not contains(container, rect):
        raise Reject("%s is clipped by its container: %r not inside %r"
                     % (label, rect, container))


def validate_geometry(g, width, height):
    editor = (0, 0, width, height)
    for key in ("title", "preset_label", "preset_selector", "meter"):
        validate_control(key, g[key], editor, 1, 1)
    if g["ab_h"] < 1:
        raise Reject("A/B button row height collapsed")

    rail = g["rail"]
    controls = []

    validate_control("overall knob", g["overall"][0], rail,
                     USABLE_KNOB, USABLE_KNOB)
    validate_control("overall label", g["overall"][1], rail,
                     USABLE_KNOB, USABLE_LABEL_H)
    controls.extend(g["overall"])

    validate_control("master drive knob", g["master"][0], rail,
                     USABLE_KNOB, USABLE_KNOB)
    validate_control("master drive label", g["master"][1], rail,
                     USABLE_KNOB, USABLE_LABEL_H)
    validate_control("master bypass", g["master"][2], rail,
                     USABLE_BYPASS_W, USABLE_BYPASS_H)
    controls.extend(g["master"])

    for name, (knob, label) in zip(("width", "mid drive", "side drive"),
                                   g["mss"]):
        validate_control(name + " knob", knob, rail,
                         USABLE_KNOB, USABLE_KNOB)
        validate_control(name + " label", label, rail,
                         USABLE_KNOB, USABLE_LABEL_H)
        controls.extend((knob, label))

    validate_control("output trim knob", g["trim"][0], rail,
                     USABLE_KNOB, USABLE_KNOB)
    validate_control("output trim label", g["trim"][1], rail,
                     USABLE_KNOB, USABLE_LABEL_H)
    controls.extend(g["trim"])

    for i in range(len(controls)):
        for j in range(i + 1, len(controls)):
            if overlaps(controls[i], controls[j]):
                raise Reject("rail controls overlap: %r and %r"
                             % (controls[i], controls[j]))

    for section_name, section in g["sections"].items():
        validate_control(section_name + " section", section, editor, 1, 1)
        columns, bypass = g["section_controls"][section_name]
        section_controls = []
        for idx, (knob, label) in enumerate(columns):
            validate_control("%s knob %d" % (section_name, idx + 1),
                             knob, section, USABLE_KNOB, USABLE_KNOB)
            validate_control("%s label %d" % (section_name, idx + 1),
                             label, section, USABLE_LABEL_W, USABLE_LABEL_H)
            section_controls.extend((knob, label))
        validate_control(section_name + " bypass", bypass, section,
                         USABLE_BYPASS_W, USABLE_BYPASS_H)
        section_controls.append(bypass)
        for i in range(len(section_controls)):
            for j in range(i + 1, len(section_controls)):
                if overlaps(section_controls[i], section_controls[j]):
                    raise Reject("%s controls overlap: %r and %r"
                                 % (section_name, section_controls[i],
                                    section_controls[j]))

    delay_cols = g["section_controls"]["delay"][0]
    if len(delay_cols) != 5:
        raise Reject("delay section no longer renders five knobs")


def run_checks(text, verbose=True):
    code = strip_comments(text)
    check_async_menu(code)
    check_ab_contract(code)
    constants = parse_constants(code)
    for width, height in (MIN_SIZE, DEFAULT_SIZE):
        geom = build_geometry(constants, width, height)
        validate_geometry(geom, width, height)
        if verbose:
            print("editor-layout-async: geometry OK at %dx%d" % (width, height))
    return constants


def main():
    if not ED.exists():
        print("EDITOR-LAYOUT-ASYNC FAIL: missing source file %s" % ED)
        return 1
    raw = ED.read_text(encoding="utf-8")
    try:
        run_checks(raw)
    except Reject as exc:
        print("EDITOR-LAYOUT-ASYNC FAIL: %s" % exc)
        return 1

    print("editor-layout-async: async menu captures paramID by value and "
          "guards knob/editor with SafePointer")
    print("editor-layout-async: A/B reseed keeps saveSlotA() + saveSlotB() "
          "under !hasPersistedABSnapshots()")

    # ------------------------------------------------------------------
    # Negative probes (in-memory copies only; a no-op mutation is a stale
    # alarm and fails the run).
    # ------------------------------------------------------------------
    def probe(label, old, new, why):
        mutated = raw.replace(old, new, 1)
        if mutated == raw:
            raise Reject("probe '%s' is stale: mutation did not apply" % label)
        try:
            run_checks(mutated, verbose=False)
        except Reject:
            print("editor-layout-async probe '%s': rejected as expected"
                  % label)
            return
        raise Reject("probe '%s' was NOT rejected — %s" % (label, why))

    try:
        probe("collapsed grid (old 20px bug)",
              "const int kGridRowsRef = 2;",
              "const int kGridRowsRef = 200;",
              "the grid must derive a usable row height from gridArea")
        probe("delay last knob squeezed below usable width",
              "const float kDelayColumnShare = 0.58f;",
              "const float kDelayColumnShare = 0.20f;",
              "the fifth delay knob must keep a usable width")
        probe("bypass strip collapsed",
              "const int kSectionBypassWidthRef = 80;",
              "const int kSectionBypassWidthRef = 0;",
              "every bypass button must keep a usable rectangle")
        probe("raw knob capture in async menu",
              "k.onRightClick = [this, paramID = k.linkedParamID,",
              "k.onRightClick = [this, &k, paramID = k.linkedParamID,",
              "deferred menu callbacks must not capture raw references")
        probe("slot-B reseed dropped",
              "        audioProcessor.saveSlotB();\n",
              "",
              "snapshotB is a zero-initialized array; removing the reseed "
              "makes a fresh B load every parameter minimum")

        # Specificity guard: an edit outside the pinned shapes still passes.
        benign = raw.replace("// === BOTTOM ROW ===",
                             "// === BOTTOM ROW (FX) ===", 1)
        if benign == raw:
            raise Reject("benign probe is stale: mutation did not apply")
        run_checks(benign, verbose=False)
        print("editor-layout-async: benign source edit still accepted "
              "(probe specificity proven)")
    except Reject as exc:
        print("EDITOR-LAYOUT-ASYNC FAIL: %s" % exc)
        return 1

    print("EDITOR-LAYOUT-ASYNC OK")
    return 0


if __name__ == "__main__":
    raise SystemExit (main())
