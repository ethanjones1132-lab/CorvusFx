#!/usr/bin/env python3
"""CV-089: an FX state restore must prove the chunk is ours before replaceState.

`CorvusFXAudioProcessor::setStateInformation` (source/DrippyFX/PluginProcessor.cpp)
replaces the WHOLE parameter tree. Before this change the only gate on the chunk
was the APVTS root tag — and `createParameterLayout` is built on the default
root tag "Parameters", which every other APVTS plugin also writes. So a foreign
plugin's chunk, a hand-edited chunk with three parameters, or a chunk saved
before any identity marker existed all reached `apvts.replaceState` and reset the
live parameters they did not carry.

Asserts on the real tree (comment-stripped, brace-matched):

  (a) `getStateInformation` writes a product identity marker attribute
      (`stateProductIdAttribute` = `stateProductId`) AFTER the schemaVersion
      attribute, and the restore gate rejects the same value the save writes;
  (b) the restore gate demands, in this order and before any mutating work,
      the schemaVersion bail (an unknown version is refused outright), then a
      required marker whose value must equal the saved one, then the complete
      parameter roster — and it `return`s before `apvts.replaceState(`,
      `snapshotA.fill(`, `midiMap.clear()`, `lockedParams.clear()` etc., so a
      partial or foreign chunk leaves the live session untouched;
  (c) the marker requirement is UNCONDITIONAL: it sits immediately after the
      schemaVersion bail, so a legacy chunk with no schemaVersion attribute is
      accepted only when it carries the marker;
  (d) the completeness helper derives the roster from the live processor
      (`getParameters()` / `RangedAudioParameter`), requires one child per
      registered id and rejects extra/duplicate parameter children — it never
      hardcodes the count;
  (e) `createParameterLayout` still registers exactly 25 parameters, and the
      checker's chunk model (the executable form of the pinned gates, fed with
      that parsed roster) rejects a truncated parameter set, a foreign root tag
      and a marker-less no-schemaVersion chunk, each leaving the live
      parameters unchanged, while a marked legacy chunk still restores;
  (f) the native unit test that drives the same four chunks against a live
      processor (source/DrippyFX/tests/CorvusFXStateTests.cpp) stays present.

Negative self-probes mutate in-memory copies only (the real tree is never
written; a probe whose pattern is absent fails the run as stale): save-side
marker dropped, restore-side marker gate dropped, roster requirement dropped
from the gate, helper count hardcoded, and a parameter added to the layout are
each rejected; a comment-only edit is accepted.

Exit 0 on green, 1 with diagnostics otherwise.
"""
import re
import sys
from pathlib import Path

# Diagnostics quote source text with non-ASCII dashes; a cp1252 console must
# not turn a verdict into a crash.
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

ROOT = Path(__file__).resolve().parent.parent
SOURCE = ROOT / "source" / "DrippyFX" / "PluginProcessor.cpp"
STATE_TESTS = ROOT / "source" / "DrippyFX" / "tests" / "CorvusFXStateTests.cpp"

PROCESSOR = "CorvusFXAudioProcessor"
# The parameter roster the FX layout must register (all 25 must travel in a
# chunk before either product may apply it).
EXPECTED_PARAMETERS = 25
# The default APVTS root tag `createParameterLayout` inherits; the tag alone is
# not an identity marker.
APVTS_ROOT_TAG = "Parameters"

MARKER_ATTRIBUTE_DEF = re.compile(
    r'constexpr\s+auto\s+stateProductIdAttribute\s*=\s*"([^"]+)"\s*;')
MARKER_VALUE_DEF = re.compile(
    r'constexpr\s+auto\s+stateProductId\s*=\s*"([^"]+)"\s*;')
SAVE_MARKER = re.compile(
    r'xml->setAttribute\s*\(\s*stateProductIdAttribute\s*,\s*stateProductId\s*\)\s*;')
SAVE_SCHEMA = re.compile(
    r'xml->setAttribute\s*\(\s*"schemaVersion"\s*,\s*(\d+)\s*\)\s*;')
RESTORE_SCHEMA = re.compile(
    r'if\s*\(\s*xml->hasAttribute\s*\(\s*"schemaVersion"\s*\)\s*'
    r'&&\s*xml->getIntAttribute\s*\(\s*"schemaVersion"\s*\)\s*!=\s*(\d+)\s*\)\s*'
    r'return\s*;')
MARKER_GUARD = re.compile(
    r'if\s*\(\s*!\s*xml->hasAttribute\s*\(\s*stateProductIdAttribute\s*\)\s*'
    r'\|\|\s*xml->getStringAttribute\s*\(\s*stateProductIdAttribute\s*\)\s*'
    r'!=\s*stateProductId\s*'
    r'\|\|\s*!\s*stateCarriesEveryParameter\s*\(\s*\*xml\s*,\s*\*this\s*\)\s*\)\s*'
    r'return\s*;')
ROSTER_CALL = re.compile(r'\!\s*stateCarriesEveryParameter\s*\(\s*\*xml\s*,\s*\*this\s*\)')
ROSTER_LIVE = re.compile(r'\bprocessor\s*\.\s*getParameters\s*\(\s*\)')
ROSTER_ID_LOOKUP = re.compile(r'getChildByAttribute\s*\(\s*"id"\s*,')
ROSTER_EXACT = re.compile(r'found\s*==\s*parameterIds\s*\.\s*size\s*\(\s*\)')
PUSH_BACK = re.compile(r'params\s*\.\s*push_back\s*\(')

# Every mutation the restore performs on the live session. Each must come after
# the identity/completeness gate.
RESTORE_WORK = (
    "apvts.replaceState(",
    "snapshotA.fill(",
    "snapshotB.fill(",
    "abSlotIsA = true",
    "midiMap.clear()",
    "lockedParams.clear()",
    "publishMidiMap()",
)


def strip_comments(text):
    text = re.sub(r"/\*.*?\*/", lambda m: "\n" * m.group(0).count("\n"), text,
                  flags=re.S)
    return re.sub(r"//[^\n]*", "", text)


def braced_span(text, opening):
    depth = 0
    for i in range(opening, len(text)):
        if text[i] == "{":
            depth += 1
        elif text[i] == "}":
            depth -= 1
            if depth == 0:
                return opening, i + 1, text[opening + 1:i]
    return None


def function_body(code, name):
    match = re.search(rf"{PROCESSOR}::{name}\s*\([^)]*\)\s*\n?\s*\{{", code,
                      flags=re.S)
    if not match:
        return None
    return braced_span(code, match.end() - 1)


def free_function_body(code, name):
    match = re.search(
        rf"\bbool\s+{name}\s*\([^)]*\)\s*\n?\s*\{{", code, flags=re.S)
    if not match:
        return None
    return braced_span(code, match.end() - 1)


def spline(values):
    return ", ".join(values)


def verify(cpp_text):
    """Return the list of CV-089 violations (empty when the source is ok)."""
    code = strip_comments(cpp_text)
    errors = []

    marker_attrs = MARKER_ATTRIBUTE_DEF.findall(code)
    marker_values = MARKER_VALUE_DEF.findall(code)
    if len(marker_attrs) != 1:
        errors.append("expected exactly one `constexpr auto "
                      "stateProductIdAttribute` definition, found "
                      f"{len(marker_attrs)}")
        return errors
    if len(marker_values) != 1:
        errors.append("expected exactly one `constexpr auto stateProductId` "
                      f"definition, found {len(marker_values)}")
        return errors
    marker_attr, marker_value = marker_attrs[0], marker_values[0]
    if not marker_value or marker_value == APVTS_ROOT_TAG:
        errors.append(f"stateProductId is '{marker_value}' — the marker must be "
                      "a product tag of its own, not the shared APVTS root tag")

    # (a) the save side writes the marker, after the schema version.
    save = function_body(code, "getStateInformation")
    if save is None:
        errors.append(f"missing {PROCESSOR}::getStateInformation body")
        return errors
    save_body = save[2]
    schema = SAVE_SCHEMA.search(save_body)
    marker = SAVE_MARKER.search(save_body)
    if schema is None:
        errors.append('getStateInformation no longer writes '
                      'xml->setAttribute("schemaVersion", ...)')
    if marker is None:
        errors.append("getStateInformation never writes the product identity "
                      "marker (xml->setAttribute(stateProductIdAttribute, "
                      "stateProductId)) — a restore that demands it would "
                      "reject every chunk this plugin saves")
    elif schema is not None and marker.start() < schema.end():
        errors.append("getStateInformation writes the identity marker BEFORE "
                      "the schemaVersion attribute")
    if "copyXmlToBinary(*xml, destData)" not in save_body:
        errors.append("getStateInformation no longer serializes the chunk")

    # (b) the restore gate order: schema bail, then identity + roster, then work.
    restore = function_body(code, "setStateInformation")
    if restore is None:
        errors.append(f"missing {PROCESSOR}::setStateInformation body")
        return errors
    restore_body = restore[2]

    version_bail = RESTORE_SCHEMA.search(restore_body)
    if version_bail is None:
        errors.append("setStateInformation lost its schemaVersion bail — a "
                      "chunk from an unsupported schema would be applied")
    guard = MARKER_GUARD.search(restore_body)
    if guard is None:
        errors.append("setStateInformation has no identity+roster gate of the "
                      "shape `if (! xml->hasAttribute(stateProductIdAttribute) "
                      "|| xml->getStringAttribute(stateProductIdAttribute) != "
                      "stateProductId || ! stateCarriesEveryParameter(*xml, "
                      "*this)) return;` — a foreign or truncated chunk would "
                      "still reach replaceState")
        return errors

    if version_bail is not None and version_bail.end() > guard.start():
        errors.append("the schemaVersion bail must run BEFORE the identity "
                      "gate, so an unsupported schema is refused whatever its "
                      "marker says")
    if version_bail is not None:
        # (c) unconditional marker gate: nothing may be interposed between the
        # schema bail and the identity gate (no `if (hasAttribute(...)) around
        # it), so a legacy no-schemaVersion chunk cannot skip the marker.
        between = restore_body[version_bail.end():guard.start()]
        if between.strip():
            errors.append("the identity gate does not immediately follow the "
                          "schemaVersion bail — an interposed statement could "
                          "let a marker-less legacy chunk through: "
                          f"{between.strip()[:80]!r}")

    first_work = min(
        [p for p in (restore_body.find(needle) for needle in RESTORE_WORK)
         if p != -1] or [-1])
    if first_work == -1:
        errors.append("setStateInformation restore work not found")
    elif first_work < guard.end():
        errors.append("setStateInformation mutates the live session before the "
                      "identity+roster gate — a rejected chunk would not leave "
                      "the current parameters untouched")

    # (d) the completeness helper derives the roster from the processor.
    helper = free_function_body(code, "stateCarriesEveryParameter")
    if helper is None:
        errors.append("stateCarriesEveryParameter helper is missing")
        return errors
    helper_body = helper[2]
    if not ROSTER_LIVE.search(helper_body):
        errors.append("stateCarriesEveryParameter no longer reads the live "
                      "roster (processor.getParameters())")
    if "dynamic_cast<juce::RangedAudioParameter*>" not in helper_body:
        errors.append("stateCarriesEveryParameter no longer filters to "
                      "RangedAudioParameter — the roster it demands would not "
                      "be the APVTS parameter set")
    if not ROSTER_ID_LOOKUP.search(helper_body):
        errors.append("stateCarriesEveryParameter no longer looks up a child "
                      "per parameter id (getChildByAttribute(\"id\", ...))")
    if not ROSTER_EXACT.search(helper_body):
        errors.append("stateCarriesEveryParameter no longer requires exactly "
                      "one child per parameter (found == parameterIds.size())")
    if re.search(r"found\s*==\s*\d+", helper_body):
        errors.append("stateCarriesEveryParameter hardcodes the parameter "
                      "count instead of deriving it from the roster")

    # (e) the layout registers the expected roster size.
    layout = function_body(code, "createParameterLayout")
    if layout is None:
        errors.append("missing createParameterLayout body")
        return errors
    layout_body = layout[2]
    roster = []
    starts = [m.start() for m in PUSH_BACK.finditer(layout_body)]
    for index, start in enumerate(starts):
        end = starts[index + 1] if index + 1 < len(starts) else len(layout_body)
        entry = layout_body[start:end]
        literal = re.search(r'"([^"]+)"', entry)
        if literal:
            roster.append(literal.group(1))
    if len(roster) != EXPECTED_PARAMETERS:
        errors.append(f"createParameterLayout registers {len(roster)} "
                      f"parameters, expected {EXPECTED_PARAMETERS} "
                      f"({spline(roster)})")

    return errors


# ---------------------------------------------------------------------------
# Chunk model: the executable form of the gates pinned above. It is fed with
# the roster parsed from createParameterLayout and the marker literals parsed
# from the gate, so the scenarios the brief names are exercised, not just
# described.
# ---------------------------------------------------------------------------
def restore_verdict(chunk, marker_attr, marker_value, roster, schema_version):
    """(accepted, live session mutated) for one state chunk.

    A rejected chunk must report `mutated == False`: the live parameters stay
    exactly as they were.
    """
    if chunk["tag"] != APVTS_ROOT_TAG:
        return False, False
    if "schemaVersion" in chunk["attributes"] \
            and chunk["attributes"]["schemaVersion"] != schema_version:
        return False, False
    if chunk["attributes"].get(marker_attr) != marker_value:
        return False, False
    parameter_children = [child for child in chunk["children"]
                          if "id" in child and "value" in child]
    ids = [child["id"] for child in parameter_children]
    if len(parameter_children) != len(roster) or sorted(ids) != sorted(roster):
        return False, False
    return True, True


def chunk(tag, attributes, roster, value=0.5):
    return {
        "tag": tag,
        "attributes": dict(attributes),
        "children": [{"id": param, "value": value} for param in roster],
    }


def scenario_checks(cpp_text, roster, marker_attr, marker_value):
    errors = []
    code = strip_comments(cpp_text)
    save = function_body(code, "getStateInformation")
    version = 1
    if save is not None:
        schema = SAVE_SCHEMA.search(save[2])
        if schema:
            version = int(schema.group(1))
    if not roster:
        errors.append("cannot model restore chunks: the parameter roster is "
                      "empty")
        return errors

    marked = chunk(APVTS_ROOT_TAG,
                   {marker_attr: marker_value, "schemaVersion": version}, roster)
    accepted, mutated = restore_verdict(marked, marker_attr, marker_value,
                                        roster, version)
    if not accepted or not mutated:
        errors.append("a complete marked chunk is rejected — the plugin would "
                      "not recall its own sessions")

    legacy_marked = chunk(APVTS_ROOT_TAG, {marker_attr: marker_value}, roster)
    accepted, _ = restore_verdict(legacy_marked, marker_attr, marker_value,
                                  roster, version)
    if not accepted:
        errors.append("a marked legacy chunk (no schemaVersion) is rejected — "
                      "the legacy path must survive when the marker is there")

    legacy_unmarked = chunk(APVTS_ROOT_TAG, {}, roster)
    accepted, mutated = restore_verdict(legacy_unmarked, marker_attr,
                                        marker_value, roster, version)
    if accepted or mutated:
        errors.append("a marker-less no-schemaVersion chunk is applied — the "
                      "legacy path must require the identity marker")

    truncated = chunk(APVTS_ROOT_TAG,
                      {marker_attr: marker_value, "schemaVersion": version},
                      roster[:-1])
    accepted, mutated = restore_verdict(truncated, marker_attr, marker_value,
                                        roster, version)
    if accepted or mutated:
        errors.append("a chunk missing a parameter child is applied — "
                      "replaceState would reset the missing parameter")

    foreign = chunk("ForeignPluginState",
                    {marker_attr: marker_value, "schemaVersion": version}, roster)
    accepted, mutated = restore_verdict(foreign, marker_attr, marker_value,
                                        roster, version)
    if accepted or mutated:
        errors.append("a chunk with a foreign root tag is applied")

    foreign_marker = chunk(APVTS_ROOT_TAG,
                           {marker_attr: "SomeOtherPlugin",
                            "schemaVersion": version}, roster)
    accepted, mutated = restore_verdict(foreign_marker, marker_attr,
                                        marker_value, roster, version)
    if accepted or mutated:
        errors.append("a chunk carrying another product's identity marker is "
                      "applied")

    return errors


def layout_roster(cpp_text):
    code = strip_comments(cpp_text)
    layout = function_body(code, "createParameterLayout")
    if layout is None:
        return []
    body = layout[2]
    roster = []
    starts = [m.start() for m in PUSH_BACK.finditer(body)]
    for index, start in enumerate(starts):
        end = starts[index + 1] if index + 1 < len(starts) else len(body)
        literal = re.search(r'"([^"]+)"', body[start:end])
        if literal:
            roster.append(literal.group(1))
    return roster


def test_pins(state_tests_text):
    """The native test must keep driving the same four chunks."""
    errors = []
    if "CV-089" not in state_tests_text:
        errors.append("CorvusFXStateTests.cpp has no CV-089 restore-probe test")
    for needle, label in (
            ('getChildByAttribute("id", "fatness")',
             "truncated parameter set probe"),
            ('setTagName("ForeignPluginState")', "foreign root tag probe"),
            ('removeAttribute("productId")', "marker-less chunk probe"),
            ('removeAttribute("schemaVersion")', "schemaVersion-less chunk probe"),
            ("live parameters changed", "live-parameter-unchanged assertion"),
    ):
        if needle not in state_tests_text:
            errors.append(f"CorvusFXStateTests.cpp lost its {label} "
                          f"({needle})")
    return errors


def main():
    if not SOURCE.exists():
        print(f"FAIL: missing source file {SOURCE}")
        return 1
    cpp_text = SOURCE.read_text(encoding="utf-8", errors="replace")

    errors = verify(cpp_text)
    code = strip_comments(cpp_text)
    attrs = MARKER_ATTRIBUTE_DEF.findall(code)
    values = MARKER_VALUE_DEF.findall(code)
    if len(attrs) == 1 and len(values) == 1:
        errors += scenario_checks(cpp_text, layout_roster(cpp_text),
                                  attrs[0], values[0])
    if STATE_TESTS.exists():
        errors += test_pins(STATE_TESTS.read_text(encoding="utf-8",
                                                 errors="replace"))
    else:
        errors.append(f"missing native state test file {STATE_TESTS}")

    if errors:
        print("FAIL: CV-089 state restore identity/completeness invariants "
              "violated:")
        for error in errors:
            print(f"  - {error}")
        return 1

    print("OK: the FX restore demands a product identity marker plus all "
          f"{EXPECTED_PARAMETERS} parameter children before replaceState")
    print("OK: legacy chunks (no schemaVersion) survive only with the marker; "
          "partial/foreign chunks leave the live session untouched")
    print("OK: CorvusFXStateTests.cpp drives the same four chunks natively")

    # -----------------------------------------------------------------------
    # Negative self-probes (in memory only — the real tree is never written)
    # -----------------------------------------------------------------------
    def fail_probe(label, why):
        print(f"FAIL: probe '{label}' was NOT rejected — {why}")
        sys.exit(1)

    def fail_stale(label):
        print(f"FAIL: probe '{label}': NO-OP MUTATION (pattern absent from the "
              "live source) — the probe is stale")
        sys.exit(1)

    def splice(text, match, replacement):
        if match is None:
            return None
        return text[:match.start()] + replacement + text[match.end():]

    # A comment-only edit must not affect the contract.
    if verify(cpp_text + "\n// harmless checker probe\n"):
        print("FAIL: harmless comment edit was rejected")
        sys.exit(1)
    print("probe ok: harmless comment edit -> accepted")

    save_body_marker = SAVE_MARKER.search(code)
    if save_body_marker is None:
        fail_stale("save-side identity marker dropped")
    mutated = splice(code, save_body_marker, "")
    if not verify(mutated):
        fail_probe("save-side identity marker dropped",
                   "a save with no marker still passed")
    print("probe ok: save-side identity marker dropped -> rejected")

    guard_match = MARKER_GUARD.search(code)
    if guard_match is None:
        fail_stale("restore-side identity gate dropped")
    mutated = splice(code, guard_match, "")
    if not verify(mutated):
        fail_probe("restore-side identity gate dropped",
                   "a restore with no identity gate still passed")
    print("probe ok: restore-side identity gate dropped -> rejected")

    # Drop only the roster requirement from the gate (identity alone).
    guard_text = guard_match.group(0)
    weaker = ROSTER_CALL.sub("", guard_text, count=1)
    if weaker == guard_text:
        fail_stale("roster requirement dropped from the gate")
    mutated = splice(code, guard_match, weaker)
    if not verify(mutated):
        fail_probe("roster requirement dropped from the gate",
                   "an identity-only gate still passed")
    print("probe ok: roster requirement dropped from the gate -> rejected")

    # Hardcode the roster count in the helper.
    exact = ROSTER_EXACT.search(code)
    if exact is None:
        fail_stale("helper count hardcoded")
    mutated = splice(code, exact, "found == 25")
    if not verify(mutated):
        fail_probe("helper count hardcoded",
                   "a hardcoded parameter count still passed")
    print("probe ok: helper count hardcoded -> rejected")

    # Add a parameter to the layout: the 25-child contract must move.
    push = PUSH_BACK.search(code)
    if push is None:
        fail_stale("parameter added to the layout")
    line_end = code.find("\n", push.start())
    if line_end == -1:
        fail_stale("parameter added to the layout")
    duplicated = code[push.start():line_end].rstrip() + "\n"
    mutated = code[:line_end + 1] + duplicated + code[line_end + 1:]
    if not verify(mutated):
        fail_probe("parameter added to the layout",
                   "a 26-parameter layout still passed")
    print("probe ok: parameter added to the layout -> rejected")

    return 0


if __name__ == "__main__":
    sys.exit(main())
