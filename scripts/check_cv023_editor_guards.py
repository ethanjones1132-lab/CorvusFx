#!/usr/bin/env python3
"""Headless checker: editor menu lifetime + FX-grid usable bounds (CV-023).

Two defects share `source/DrippyFX/PluginEditor.cpp`:

  (1) The knob context menu is shown asynchronously. Menu item callbacks used
      to capture raw `&k`/`&proc` references, so a click that arrived after
      the knob or editor was destroyed touched freed memory. The landed fix
      captures the parameter id by value and guards every deferred access with
      juce::Component::SafePointer.

  (2) The master rail consumed the content height before the 2x2 FX grid was
      laid out, collapsing it (the old ~20px grid). The grid is now carved out
      of the right-hand area first, and each section reserves its bypass strip
      first, then divides the remaining rectangle into knob columns clamped by
      the available height so labels and bypass buttons always keep usable
      bounds at the supported minimum (1000x600) and default (1200x700) sizes.

Asserts on the real tree:
  (a) the onRightClick lambda has no capture-by-reference and no raw `this`
      capture in nested menu callbacks; knob/editor access goes through
      SafePointer::getComponent(); the menu is still asynchronous;
  (b) resized() still carves the grid before the rail, still reserves the
      bypass strip before computing knob sizes, and keeps the 16px bypass and
      14px label floors;
  (c) replaying the reference-pixel rectangle arithmetic at 1000x600 and
      1200x700 yields positive, usable knob/label/bypass rectangles for all
      four effect sections, contained in their section and free of overlaps.

Negative probes (in-memory mutated copies; a no-op mutation aborts as a stale
alarm, the real tree is never mutated):
  - reintroduce a raw `&k` capture in the async menu -> rejected;
  - collapse the grid row divisor (the old 20px bug) -> rejected;
  - collapse the section bypass width to zero -> rejected;
  - drop the bypass-strip reservation -> rejected;
  - benign comment edit outside the pinned shapes -> accepted.

Exit 0 = ok, 1 = violation with a cited diagnostic, 2 = setup/read failure.
"""
import math
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
ED = ROOT / "source" / "DrippyFX" / "PluginEditor.cpp"

MIN_SIZE = (1000, 600)
DEFAULT_SIZE = (1200, 700)

USABLE_KNOB = 44
USABLE_LABEL_W = 40
USABLE_LABEL_H = 14
USABLE_BYPASS_W = 40
USABLE_BYPASS_H = 16

INT_CONSTANTS = [
    "kTopSectionRef", "kMeterRef", "kFooterRef", "kContentInsetXRef",
    "kContentInsetYRef", "kRailGapRef", "kRailMinRef", "kRailMaxRef",
    "kGridGapRef", "kGridRowsRef", "kSectionPadXRef", "kSectionPadYRef",
    "kSectionLabelRef", "kSectionBypassRef", "kSectionBypassGapRef",
    "kSectionBypassWidthRef", "kSectionMinGapRef", "kSectionMaxGapRef",
    "kSectionMinKnobRef", "kDistortionMaxKnobRef", "kChorusMaxKnobRef",
    "kDelayMaxKnobRef", "kReverbMaxKnobRef",
]


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
# (a) async menu lifetime
# ---------------------------------------------------------------------------
def check_async_menu(code):
    idx = code.find("k.onRightClick")
    if idx < 0:
        raise Reject("the knob's onRightClick menu builder is missing")
    assign = code.find("=", idx)
    if assign < 0:
        raise Reject("the onRightClick assignment is malformed")
    open_capture = code.find("[", assign)
    close_capture = code.find("]", open_capture)
    if open_capture < 0 or close_capture < 0:
        raise Reject("the onRightClick lambda capture list is missing")
    capture_list = code[open_capture + 1:close_capture]
    brace = code.find("{", close_capture)
    if brace < 0:
        raise Reject("the onRightClick lambda body is missing")
    body_block = brace_block(code, brace)
    body = body_block[1:-1]
    segment = code[idx:brace + len(body_block)]

    # Any capture-by-reference in this deferred callback is a lifetime bug.
    # `(&k)` is a SafePointer constructor argument, not a capture, and lives
    # inside parentheses in the capture list.
    if re.search(r"(?:^|,)\s*&", capture_list):
        raise Reject("the async context menu captures a reference - a raw "
                     "&knob/&processor can outlive the editor")
    if re.search(r"\[\s*this\b", body):
        raise Reject("a deferred menu callback captures raw `this` instead of "
                     "a SafePointer")
    if re.search(r"paramID\s*=\s*k\.linkedParamID", segment) is None:
        raise Reject("the menu no longer captures the parameter id by value")
    if "juce::Component::SafePointer<AnimatedKnob>" not in segment:
        raise Reject("the menu no longer guards the knob with SafePointer")
    if "juce::Component::SafePointer<CorvusFXAudioProcessorEditor>" \
            not in segment:
        raise Reject("the menu no longer guards the editor with SafePointer")
    if re.search(r"safeKnob\s*\.\s*getComponent\s*\(\s*\)", body) is None:
        raise Reject("deferred knob access is not checked through SafePointer")
    if re.search(r"safeEditor\s*\.\s*getComponent\s*\(\s*\)", body) is None:
        raise Reject("deferred editor access is not checked through "
                     "SafePointer")
    if re.search(r"\bproc\s*\.", body):
        raise Reject("the menu still reaches through a raw processor reference")
    if re.search(r"\bk\s*\.", body):
        raise Reject("the menu still reaches through a raw knob reference")
    if "showMenuAsync" not in body:
        raise Reject("the context menu is no longer asynchronous")


# ---------------------------------------------------------------------------
# (b) structural bounds guarantees in resized()
# ---------------------------------------------------------------------------
def parse_constants(code):
    values = {}
    for name in INT_CONSTANTS:
        match = re.search(r"const\s+int\s+" + name + r"\s*=\s*(-?\d+)\s*;",
                          code)
        if match is None:
            raise Reject("layout constant %s is missing from resized()"
                         % name)
        values[name] = int(match.group(1))
    match = re.search(r"const\s+float\s+kDelayColumnShare\s*=\s*"
                      r"([0-9]*\.?[0-9]+)f\s*;", code)
    if match is None:
        raise Reject("layout constant kDelayColumnShare is missing")
    values["kDelayColumnShare"] = float(match.group(1))

    required = [
        (r"railW\s*=\s*juce::jlimit\(\s*sc\(kRailMinRef\)\s*,\s*"
         r"area\.getWidth\(\)\s*/\s*3\s*,\s*sc\(kRailMaxRef\)\s*\)",
         "the rail width no longer derives from the available area"),
        (r"gridW\s*=\s*juce::jmax\(\s*1\s*,\s*area\.getWidth\(\)\s*-\s*"
         r"railW\s*-\s*railGap\s*\)",
         "the FX grid width no longer fills the area left of the rail"),
        (r"gridArea\s*=\s*area\.removeFromRight\(\s*gridW\s*\)",
         "the FX grid is no longer carved out before the master rail"),
        (r"secH\s*=\s*juce::jmax\(\s*1\s*,\s*\(gridArea\.getHeight\(\)\s*-\s*"
         r"gap\)\s*/\s*kGridRowsRef\s*\)",
         "the grid rows no longer derive their height from gridArea"),
        (r"content\s*=\s*reserveBypass\(\s*content\s*,\s*bypass\s*\)",
         "section layout no longer reserves a bypass strip before knobs"),
        (r"bypH\s*=\s*juce::jmax\(\s*sc\(kSectionBypassRef\)\s*,\s*16\s*\)",
         "the section bypass strip no longer has a 16px height floor"),
        (r"labelH\s*=\s*juce::jmax\(\s*sc\(kSectionLabelRef\)\s*,\s*14\s*\)",
         "the section label height no longer has a 14px floor"),
        (r"knobSize\s*=\s*juce::jmin\(\s*knobSize\s*,\s*juce::jmax\(\s*1\s*,"
         r"\s*content\.getHeight\(\)\s*-\s*labelH\s*\)\s*\)",
         "knob size is no longer clamped by the section height left after "
         "the label"),
        (r"knobSize\s*=\s*juce::jmax\(\s*1\s*,\s*knobSize\s*\)",
         "knob size no longer has a positive floor"),
    ]
    for pattern, why in required:
        if re.search(pattern, code) is None:
            raise Reject(why)

    reserve = code.find("content = reserveBypass(content, bypass);")
    knob_calc = code.find("int knobSize =")
    if reserve == -1 or knob_calc == -1 or reserve > knob_calc:
        raise Reject("section layout divides the knob columns before "
                     "reserving the bypass strip - labels/bypass can lose "
                     "their bounds")

    for area_name in ("distArea", "chorArea", "delArea", "revArea"):
        if re.search(r"layoutSection\(\s*%s\s*," % area_name, code) is None:
            raise Reject("section %s no longer uses the shared explicit "
                         "layout" % area_name)
    return values


# ---------------------------------------------------------------------------
# (c) integer rectangle replay matching PluginEditor.cpp::resized()
# ---------------------------------------------------------------------------
def sc(px, scale):
    return int(math.floor(px * scale + 0.5))


def reduced(rect, dx, dy):
    x, y, w, h = rect
    return (x + dx, y + dy, w - 2 * dx, h - 2 * dy)


def remove_top(rect, amount):
    x, y, w, h = rect
    take = min(amount, h)
    return (x, y, w, take), (x, y + take, w, h - take)


def remove_bottom(rect, amount):
    x, y, w, h = rect
    take = min(amount, h)
    return (x, y + h - take, w, take), (x, y, w, h - take)


def remove_left(rect, amount):
    x, y, w, h = rect
    take = min(amount, w)
    return (x, y, take, h), (x + take, y, w - take, h)


def remove_right(rect, amount):
    x, y, w, h = rect
    take = min(amount, w)
    return (x + w - take, y, take, h), (x, y, w - take, h)


def centered(rect, width, height):
    x, y, w, h = rect
    cx = x + w // 2
    cy = y + h // 2
    return (cx - width // 2, cy - height // 2, width, height)


def jlimit(low, high, value):
    if value < low:
        return low
    if high < value:
        return high
    return value


def layout_section(section, max_knob, columns, values, scale):
    content = reduced(section,
                      sc(values["kSectionPadXRef"], scale),
                      sc(values["kSectionPadYRef"], scale))
    byp_h = max(sc(values["kSectionBypassRef"], scale), 16)
    by_row, content = remove_bottom(content, byp_h)
    _, content = remove_bottom(content,
                               sc(values["kSectionBypassGapRef"], scale))
    bypass = centered(by_row,
                      min(by_row[2],
                          sc(values["kSectionBypassWidthRef"], scale)),
                      byp_h)

    label_h = max(sc(values["kSectionLabelRef"], scale), 14)
    gap_x = jlimit(
        sc(values["kSectionMinGapRef"], scale),
        sc(values["kSectionMaxGapRef"], scale),
        (content[2] - columns * sc(values["kSectionMinKnobRef"], scale))
        // max(1, columns + 1))
    knob = min(max_knob,
               (content[2] - gap_x * (columns + 1)) // max(1, columns))
    knob = min(knob, max(1, content[3] - label_h))
    knob = max(1, knob)
    total_w = knob * columns + gap_x * (columns + 1)
    row = centered(content, total_w, knob + label_h)
    _, row = remove_left(row, gap_x)
    column_rects = []
    for _ in range(columns):
        col, row = remove_left(row, knob)
        knob_rect, col = remove_top(col, knob)
        label_rect, _ = remove_top(col, label_h)
        column_rects.append((knob_rect, label_rect))
        _, row = remove_left(row, gap_x)
    return column_rects, bypass, content


def build_grid(values, width, height):
    scale = min(width / 1200.0, height / 700.0)
    _, area = remove_top((0, 0, width, height),
                         sc(values["kTopSectionRef"], scale))
    # The level meter row is removed from the layout area too.
    _, area = remove_top(area, sc(values["kMeterRef"], scale))
    _, area = remove_bottom(area, sc(values["kFooterRef"], scale))
    area = reduced(area,
                   sc(values["kContentInsetXRef"], scale),
                   sc(values["kContentInsetYRef"], scale))

    rail_gap = sc(values["kRailGapRef"], scale)
    rail_w = jlimit(sc(values["kRailMinRef"], scale), area[2] // 3,
                    sc(values["kRailMaxRef"], scale))
    grid_w = max(1, area[2] - rail_w - rail_gap)
    grid, area = remove_right(area, grid_w)
    _, area = remove_right(area, rail_gap)

    gap = max(1, sc(values["kGridGapRef"], scale))
    sec_h = max(1, (grid[3] - gap) // values["kGridRowsRef"])
    top_row, grid = remove_top(grid, sec_h)
    top_w = max(1, (top_row[2] - gap) // 2)
    dist, top_row = remove_left(top_row, top_w)
    _, top_row = remove_left(top_row, gap)
    chorus = top_row

    _, bottom = remove_top(grid, gap)
    delay_w = int(math.floor((bottom[2] - gap)
                             * values["kDelayColumnShare"] + 0.5))
    delay, bottom = remove_left(bottom, delay_w)
    _, bottom = remove_left(bottom, gap)
    reverb = bottom

    sections = (
        ("distortion", dist, sc(values["kDistortionMaxKnobRef"], scale), 1),
        ("chorus", chorus, sc(values["kChorusMaxKnobRef"], scale), 3),
        ("delay", delay, sc(values["kDelayMaxKnobRef"], scale), 5),
        ("reverb", reverb, sc(values["kReverbMaxKnobRef"], scale), 4),
    )
    result = {}
    for name, section, max_knob, columns in sections:
        column_rects, bypass, content = layout_section(
            section, max_knob, columns, values, scale)
        result[name] = (section, column_rects, bypass, content)
    return result


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


def validate_grid(values, width, height):
    editor = (0, 0, width, height)
    grid = build_grid(values, width, height)
    for name, (section, column_rects, bypass, content) in grid.items():
        validate_control(name + " section", section, editor, 1, 1)
        if content[2] <= 0 or content[3] <= 0:
            raise Reject("%s has no knob area left after the bypass strip "
                         "and padding: %r" % (name, content))
        controls = []
        for index, (knob, label) in enumerate(column_rects, 1):
            validate_control("%s knob %d" % (name, index), knob, section,
                             USABLE_KNOB, USABLE_KNOB)
            validate_control("%s label %d" % (name, index), label, section,
                             USABLE_LABEL_W, USABLE_LABEL_H)
            if knob[3] + label[3] > content[3]:
                raise Reject("%s knob %d plus its label do not fit the "
                             "reserved height: %d > %d"
                             % (name, index, knob[3] + label[3], content[3]))
            controls.extend((knob, label))
        validate_control(name + " bypass", bypass, section,
                         USABLE_BYPASS_W, USABLE_BYPASS_H)
        if bypass[1] < content[1] + content[3]:
            raise Reject("%s bypass strip overlaps the knob area - the strip "
                         "must be reserved first" % name)
        controls.append(bypass)
        for i in range(len(controls)):
            for j in range(i + 1, len(controls)):
                if overlaps(controls[i], controls[j]):
                    raise Reject("%s controls overlap: %r and %r"
                                 % (name, controls[i], controls[j]))


def run(code):
    check_async_menu(code)
    values = parse_constants(code)
    for width, height in (MIN_SIZE, DEFAULT_SIZE):
        validate_grid(values, width, height)
    return values


def main():
    if not ED.exists():
        print("EDITOR-BOUNDS-LIFETIME SETUP FAIL: missing %s" % ED)
        return 2
    try:
        raw = ED.read_text(encoding="utf-8", errors="replace")
    except OSError as exc:
        print("EDITOR-BOUNDS-LIFETIME SETUP FAIL: %s" % exc)
        return 2

    code = strip_comments(raw)
    try:
        run(code)
    except Reject as exc:
        print("EDITOR-BOUNDS-LIFETIME FAIL: %s" % exc)
        return 1
    print("editor-bounds-lifetime: async menu callbacks use SafePointer and "
          "the FX grid keeps usable knob/label/bypass bounds at 1000x600 and "
          "1200x700")

    probes = [
        ("reintroduce a raw &k capture in the async menu",
         "k.onRightClick = [this, paramID = k.linkedParamID,",
         "k.onRightClick = [this, &k, paramID = k.linkedParamID,"),
        ("collapse the grid row divisor (old 20px bug)",
         "const int kGridRowsRef = 2;",
         "const int kGridRowsRef = 200;"),
        ("collapse the section bypass width to zero",
         "const int kSectionBypassWidthRef = 80;",
         "const int kSectionBypassWidthRef = 0;"),
        ("drop the bypass-strip reservation",
         "        content = reserveBypass(content, bypass);\n",
         ""),
    ]
    for label, old, new in probes:
        mutated = code.replace(old, new, 1)
        if mutated == code:
            print("EDITOR-BOUNDS-LIFETIME FAIL: probe '%s' is stale: mutation "
                  "did not apply - cannot trust the negative check" % label)
            return 1
        try:
            run(mutated)
        except Reject:
            print("editor-bounds-lifetime: probe '%s' rejected as expected"
                  % label)
            continue
        print("EDITOR-BOUNDS-LIFETIME FAIL: probe '%s' was NOT rejected - "
              "checker is vacuous" % label)
        return 1

    # Specificity: a comment edit outside the pinned shapes still passes.
    benign_raw = raw.replace("    // === BOTTOM ROW ===",
                             "    // === BOTTOM ROW (FX) ===", 1)
    if benign_raw == raw:
        print("EDITOR-BOUNDS-LIFETIME FAIL: benign comment probe is stale: "
              "the edit did not apply")
        return 1
    try:
        run(strip_comments(benign_raw))
    except Reject as exc:
        print("EDITOR-BOUNDS-LIFETIME FAIL: benign comment edit was rejected "
              "- checker over-fires: %s" % exc)
        return 1
    print("editor-bounds-lifetime: benign comment edit accepted (probe "
          "specificity proven)")

    try:
        run(strip_comments(
            ED.read_text(encoding="utf-8", errors="replace")))
    except Reject as exc:
        print("EDITOR-BOUNDS-LIFETIME FAIL: final live-source "
              "re-verification failed: %s" % exc)
        return 1
    print("EDITOR-BOUNDS-LIFETIME OK (4 negatives, comment edit accepted)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
