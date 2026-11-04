#!/usr/bin/env python3
"""Headless checker: CV-041 — "preset" is a non-automatable recall trigger.

Registering "preset" as an ordinary automatable integer made every host expose
and record an automation lane for it. Each automation write landed in
parameterChanged(), which ran loadPreset(idToPreset[id]) and rewrote the whole
parameter set mid-playback. CV-041 registers the parameter non-automatable;
recall from the editor combo, a host program change and state restore must all
keep working exactly as before.

Asserts on the real tree (comment-stripped, brace-matched bodies):

  (A) registration
      * createParameterLayout registers exactly one AudioParameterInt for
        "preset"/"Preset" whose positional range is [0,42] with default 2
        (byte-for-byte the old parameter identity), and that registration
        carries AudioParameterIntAttributes().withAutomatable(false);
      * the registration never says withAutomatable(true).

  (B) recall path unchanged
      * parameterChanged()'s "preset" branch keeps the restoringPresetState
        guard BEFORE loadPreset(idToPreset[id]);
      * loadPreset() still writes every struct P field, in declaration order,
        through setValueNotifyingHost(param->convertTo0to1(v)), with the same
        parameter ids;
      * setStateInformation() never calls loadPreset(), and brackets
        apvts.replaceState() with restoringPresetState.store(true)/(false);
      * setCurrentProgram() still maps i -> presetToId[i] through
        setValueNotifyingHost();
      * getStateInformation() still serializes apvts.copyState(), so the
        preset value rides along with the session;
      * PluginProcessor.h still declares the atomic restoringPresetState flag;
      * PluginEditor.cpp still constructs PresetComboAttachment for
        apvts.getParameter("preset").

Negative probes mutate in-memory copies only (the real tree is never written):
drop withAutomatable(false); flip it to true; delete a loadPreset set() site;
reorder two set() sites; drop loadPreset's setValueNotifyingHost; neuter the
restoringPresetState guard; drop setStateInformation's store(true) or
store(false); add a loadPreset() call to setStateInformation; break
setCurrentProgram's presetToId[i] mapping; drop getStateInformation's
copyState(); remove the editor attachment. A probe whose pattern is absent
fails the run as a stale probe. Benign comment/whitespace edits — including a
spacing edit inside the new registration — must still pass.

Exit 0 = ok, 1 = violation with a cited diagnostic.
"""
import re
import sys
from pathlib import Path

# Diagnostics may quote source text; a cp1252 console must not crash a verdict.
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

ROOT = Path(__file__).resolve().parent.parent
SRC = ROOT / "source" / "DrippyFX"
CPP = SRC / "PluginProcessor.cpp"
HDR = SRC / "PluginProcessor.h"
EDIT = SRC / "PluginEditor.cpp"

EXPECTED_FIELDS = (
    "fat", "cD", "cR", "cM", "dT", "dFb", "dM", "dDmp", "dMod",
    "rS", "rDmp", "rM", "rMod", "mDrv", "mWid", "mMid", "mSide",
    "distByp", "chorusByp", "delayByp", "reverbByp", "masterByp", "oTrim",
)

EXPECTED_WRITES = (
    ("fatness", "fat"),
    ("chorus_depth", "cD"),
    ("chorus_rate", "cR"),
    ("chorus_mix", "cM"),
    ("delay_time", "dT"),
    ("delay_feedback", "dFb"),
    ("delay_mix", "dM"),
    ("delay_damping", "dDmp"),
    ("delay_mod", "dMod"),
    ("reverb_size", "rS"),
    ("reverb_damping", "rDmp"),
    ("reverb_mix", "rM"),
    ("reverb_mod", "rMod"),
    ("master_drive", "mDrv"),
    ("master_width", "mWid"),
    ("master_mid_drive", "mMid"),
    ("master_side_drive", "mSide"),
    ("distortion_bypass", "distByp"),
    ("chorus_bypass", "chorusByp"),
    ("delay_bypass", "delayByp"),
    ("reverb_bypass", "reverbByp"),
    ("master_bypass", "masterByp"),
    ("output_trim", "oTrim"),
)

EDITOR_ATT_RE = re.compile(
    r'std::make_unique<PresetComboAttachment>\s*\(\s*\*\s*'
    r'audioProcessor\.apvts\.getParameter\s*\(\s*"preset"\s*\)\s*,\s*'
    r'presetSelector\s*,\s*&audioProcessor\.undoManager\s*\)')


class Reject(Exception):
    """Structural violation detected in a (real or fixture) source text."""


class StaleProbe(Exception):
    """A self-probe pattern no longer matches text it claims to target."""


def fail(msg):
    print(f"CV-041 FAIL: {msg}")
    sys.exit(1)


# ---------------------------------------------------------------------------
# Parsing helpers (comment stripping preserves line numbers)
# ---------------------------------------------------------------------------
def strip_comments(text):
    text = re.sub(r"/\*.*?\*/",
                  lambda m: "\n" * m.group(0).count("\n"), text, flags=re.S)
    return re.sub(r"//[^\n]*", "", text)


def brace_body(text, pos):
    """(open, close, body) of the first '{' at/after pos, brace-matched."""
    lb = text.find("{", pos)
    if lb == -1:
        return None
    depth = 0
    for k in range(lb, len(text)):
        if text[k] == "{":
            depth += 1
        elif text[k] == "}":
            depth -= 1
            if depth == 0:
                return lb, k + 1, text[lb:k + 1]
    return None


def method_body(code, signature):
    """Body of `CorvusFXAudioProcessor::<signature>` (brace-matched)."""
    m = re.search(r"\bCorvusFXAudioProcessor::" + signature + r"\s*\(", code)
    if not m:
        return None
    found = brace_body(code, m.end())
    return found[2] if found else None


def _require(body, pattern, where, why, flags=0):
    hit = re.search(pattern, body, flags)
    if not hit:
        raise Reject(f"{where}: {why}")
    return hit


# ---------------------------------------------------------------------------
# The gate
# ---------------------------------------------------------------------------
def verify(raw_cpp, raw_header, raw_editor):
    """Gate one cpp/header/editor triple. Raises Reject on any violation."""
    code = strip_comments(raw_cpp)
    header = strip_comments(raw_header)
    editor = strip_comments(raw_editor)

    # ---- (A) the registration is non-automatable --------------------------
    layout = method_body(code, "createParameterLayout")
    if layout is None:
        raise Reject("PluginProcessor.cpp: createParameterLayout body is "
                     "missing — the preset parameter registration cannot be "
                     "checked")

    registrations = re.findall(
        r'AudioParameterInt\w*>\s*\(\s*"preset"', layout)
    if len(registrations) != 1:
        raise Reject(
            f"PluginProcessor.cpp:createParameterLayout registers {len(registrations)} "
            f"AudioParameterInt 'preset' parameters, expected exactly one")

    reg = _require(
        layout,
        r'AudioParameterInt>\s*\(\s*"preset"\s*,\s*"Preset"\s*,\s*'
        r'0\s*,\s*42\s*,\s*2\b',
        "PluginProcessor.cpp:createParameterLayout",
        'the "preset" AudioParameterInt identity changed — expected ID '
        '"preset", name "Preset", range [0,42], default 2 so saved sessions '
        'and host parameter identity survive (CV-041)')
    statement = layout[reg.start():]
    semicolon = statement.find(";")
    if semicolon == -1:
        raise Reject('PluginProcessor.cpp:createParameterLayout — the "preset" '
                     'registration statement is not terminated')
    statement = statement[:semicolon + 1]

    if re.search(r"withAutomatable\s*\(\s*true\s*\)", statement):
        raise Reject(
            'PluginProcessor.cpp:createParameterLayout — "preset" is registered '
            'withAutomatable(true): hosts would expose an automation lane whose '
            'writes fan out into loadPreset() and stamp every parameter '
            '(CV-041)')
    _require(
        statement,
        r"AudioParameterIntAttributes\s*\(\s*\)\s*\.\s*"
        r"withAutomatable\s*\(\s*false\s*\)",
        "PluginProcessor.cpp:createParameterLayout",
        '"preset" is not registered with '
        'AudioParameterIntAttributes().withAutomatable(false) — a plain host '
        'automation write would reach parameterChanged() -> loadPreset() and '
        'recall a whole preset mid-playback (CV-041)')

    # ---- (B) recall from combo / program change / state stays intact ------
    if not re.search(r"std::atomic\s*<\s*bool\s*>\s+restoringPresetState",
                     header):
        raise Reject("PluginProcessor.h: the restoringPresetState atomic flag "
                     "is missing — state restore could no longer suppress the "
                     "preset listener")

    changed = method_body(code, "parameterChanged")
    if changed is None:
        raise Reject("PluginProcessor.cpp: parameterChanged body is missing")
    branch_head = _require(
        changed, r'if\s*\(\s*parameterID\s*==\s*"preset"\s*\)',
        "PluginProcessor.cpp:parameterChanged",
        'the "preset" branch is missing — the editor combo / program change '
        'recall path is gone')
    found = brace_body(changed, branch_head.end())
    if not found:
        raise Reject("PluginProcessor.cpp:parameterChanged — the \"preset\" "
                     "branch is not brace-matched")
    branch = found[2]
    guard = _require(
        branch, r"restoringPresetState\s*\.\s*load\s*\(\s*\)",
        "PluginProcessor.cpp:parameterChanged",
        "the restoringPresetState guard is gone — state restore would re-enter "
        "loadPreset() while replaceState is still applying values")
    _require(
        branch[guard.end():], r"\breturn\s*;",
        "PluginProcessor.cpp:parameterChanged",
        "the restoringPresetState check no longer returns early, so a restore "
        "still fans out into loadPreset()")
    recall = _require(
        branch, r"loadPreset\s*\(\s*idToPreset\s*\[\s*id\s*\]\s*\)",
        "PluginProcessor.cpp:parameterChanged",
        'the combo / program recall no longer calls loadPreset(idToPreset[id])')
    if recall.start() < guard.start():
        raise Reject('PluginProcessor.cpp:parameterChanged — loadPreset() now '
                     'runs BEFORE the restoringPresetState guard')

    preset = method_body(code, "loadPreset")
    if preset is None:
        raise Reject("PluginProcessor.cpp: loadPreset body is missing")
    struct_m = re.search(r"struct\s+P\s*\{([^}]*)\}", preset)
    if not struct_m:
        raise Reject("PluginProcessor.cpp:loadPreset — `struct P` declaration "
                     "is missing")
    fields = [f.strip() for f in
              struct_m.group(1).replace("float", " ").replace(";", " ").split(",")
              if f.strip()]
    if tuple(fields) != EXPECTED_FIELDS:
        raise Reject(
            f"PluginProcessor.cpp:loadPreset — struct P field order changed "
            f"(found {fields}); every preset column must keep its parameter")
    sites = tuple(re.findall(
        r'\bset\s*\(\s*"([^"]+)"\s*,\s*p\.(\w+)\s*\)\s*;', preset))
    if sites != EXPECTED_WRITES:
        missing = [w for w in EXPECTED_WRITES if w not in sites]
        raise Reject(
            "PluginProcessor.cpp:loadPreset — the preset write sites no longer "
            f"cover every struct P field in declaration order (missing/moved: "
            f"{missing[:6]})")
    _require(
        preset,
        r"auto\s+set\s*=\s*\[\s*this\s*\]\s*\(\s*const\s+juce::String&\s+id"
        r"\s*,\s*float\s+v\s*\)",
        "PluginProcessor.cpp:loadPreset",
        "the per-field `set` lambda (id, float value) is missing")
    _require(
        preset,
        r"param\s*->\s*setValueNotifyingHost\s*\(\s*"
        r"param\s*->\s*convertTo0to1\s*\(\s*v\s*\)\s*\)",
        "PluginProcessor.cpp:loadPreset",
        "loadPreset no longer writes through "
        "setValueNotifyingHost(param->convertTo0to1(v)) — the host would not "
        "see the recalled values")

    save = method_body(code, "getStateInformation")
    if save is None:
        raise Reject("PluginProcessor.cpp: getStateInformation body is missing")
    _require(save, r"apvts\s*\.\s*copyState\s*\(\s*\)",
             "PluginProcessor.cpp:getStateInformation",
             "the session state no longer serializes apvts.copyState(); the "
             "preset value would not round-trip")

    restore = method_body(code, "setStateInformation")
    if restore is None:
        raise Reject("PluginProcessor.cpp: setStateInformation body is missing")
    if re.search(r"\bloadPreset\s*\(", restore):
        raise Reject("PluginProcessor.cpp:setStateInformation — it calls "
                     "loadPreset(); state restore must apply the stored values "
                     "directly instead of stamping a preset (CV-041)")
    guard_on = _require(
        restore, r"restoringPresetState\s*\.\s*store\s*\(\s*true\s*\)",
        "PluginProcessor.cpp:setStateInformation",
        "restoringPresetState is never set to true — replaceState would fan "
        "out into loadPreset()")
    replace_at = _require(
        restore, r"apvts\s*\.\s*replaceState\s*\(",
        "PluginProcessor.cpp:setStateInformation",
        "apvts.replaceState() is missing — the state is never applied")
    guard_off = _require(
        restore, r"restoringPresetState\s*\.\s*store\s*\(\s*false\s*\)",
        "PluginProcessor.cpp:setStateInformation",
        "restoringPresetState is never cleared — every later preset change "
        "would be ignored")
    if not (guard_on.start() < replace_at.start() < guard_off.start()):
        raise Reject("PluginProcessor.cpp:setStateInformation — the "
                     "restoringPresetState guard no longer brackets "
                     "apvts.replaceState()")

    program = method_body(code, "setCurrentProgram")
    if program is None:
        raise Reject("PluginProcessor.cpp: setCurrentProgram body is missing")
    _require(program, r"if\s*\(\s*i\s*>=\s*0\s*&&\s*i\s*<\s*36\s*\)",
             "PluginProcessor.cpp:setCurrentProgram",
             "the [0,36) program-index guard is missing")
    _require(program, r"presetToId\s*\[\s*i\s*\]",
             "PluginProcessor.cpp:setCurrentProgram",
             "setCurrentProgram no longer maps program i through presetToId[i]")
    _require(program,
             r"convertTo0to1\s*\(\s*\(\s*float\s*\)\s*"
             r"presetToId\s*\[\s*i\s*\]\s*\)",
             "PluginProcessor.cpp:setCurrentProgram",
             "setCurrentProgram no longer writes the mapped combo item id "
             "through convertTo0to1((float) presetToId[i])")
    _require(program, r"setValueNotifyingHost",
             "PluginProcessor.cpp:setCurrentProgram",
             "setCurrentProgram does not notify the host parameter")

    if len(EDITOR_ATT_RE.findall(editor)) != 1:
        raise Reject("PluginEditor.cpp: PresetComboAttachment is no longer "
                     "constructed exactly once for "
                     "audioProcessor.apvts.getParameter(\"preset\"), "
                     "presetSelector and &audioProcessor.undoManager — the "
                     "editor combo would stop showing/recalling presets")
    return True


# Alias used by the real-tree gate and the self-probes below.
check = verify


# ---------------------------------------------------------------------------
# Real tree
# ---------------------------------------------------------------------------
for required in (CPP, HDR, EDIT):
    if not required.exists():
        fail(f"missing source file {required}")

cpp_text = CPP.read_text(encoding="utf-8")
hdr_text = HDR.read_text(encoding="utf-8")
edit_text = EDIT.read_text(encoding="utf-8")

try:
    check(cpp_text, hdr_text, edit_text)
except Reject as exc:
    fail(str(exc))

print("cv041: \"preset\" is registered as a non-automatable AudioParameterInt "
      "(id/name/range/default unchanged)")
print("cv041: combo / program-change / state recall paths intact; "
      "loadPreset still writes every struct P field in order")
print("cv041: real tree OK")


# ---------------------------------------------------------------------------
# Negative probes against the LIVE tree (in-memory copies only)
# ---------------------------------------------------------------------------
def mutate(text, pattern, repl, label, count=1):
    out, n = re.subn(pattern, repl, text, count=count)
    if n == 0 or out == text:
        raise StaleProbe(label)
    return out


def probe(label, why, cpp_mut=None, hdr_mut=None, editor_mut=None):
    new_cpp, new_hdr, new_edit = cpp_text, hdr_text, edit_text
    try:
        for mut in (cpp_mut or ()):
            new_cpp = mutate(new_cpp, *mut, label=label)
        for mut in (hdr_mut or ()):
            new_hdr = mutate(new_hdr, *mut, label=label)
        for mut in (editor_mut or ()):
            new_edit = mutate(new_edit, *mut, label=label)
    except StaleProbe:
        fail(f"probe '{label}': NO-OP MUTATION (pattern absent from the live "
             f"source) — the negative probe is stale")
    if (new_cpp, new_hdr, new_edit) == (cpp_text, hdr_text, edit_text):
        fail(f"probe '{label}': NO-OP MUTATION — the negative probe is stale")
    try:
        check(new_cpp, new_hdr, new_edit)
    except Reject as exc:
        print(f"cv041 probe '{label}': rejected as expected ({exc})")
        return
    fail(f"probe '{label}' was NOT rejected — {why}")


# (A) registration
probe("withAutomatable(false) dropped",
      "preset would be automatable again and an automation write would stamp "
      "the whole parameter set",
      cpp_mut=[(r"\.withAutomatable\s*\(\s*false\s*\)", "")])
probe("withAutomatable flipped to true",
      "hosts would expose the preset automation lane again",
      cpp_mut=[(r"\.withAutomatable\s*\(\s*false\s*\)",
                ".withAutomatable(true)")])

# (B) loadPreset coverage
probe("one loadPreset set() site deleted",
      "a recalled preset would leave that parameter at its previous value",
      cpp_mut=[(r'\n\s*set\s*\(\s*"output_trim"\s*,\s*p\.oTrim\s*\)\s*;',
                "")])
probe("two loadPreset set() sites reordered",
      "preset columns and parameters would no longer line up",
      cpp_mut=[(r'set\("fatness", p\.fat\);\s*set\("chorus_depth", p\.cD\);',
                'set("chorus_depth", p.cD); set("fatness", p.fat);')])
probe("loadPreset drops setValueNotifyingHost",
      "recalled values would never reach the host",
      cpp_mut=[(r"param->setValueNotifyingHost\(\s*param->convertTo0to1\(\s*v\s*\)\s*\)",
                "(void) v")])

# (C) restore guard
probe("restoringPresetState guard neutered",
      "replaceState would re-enter loadPreset() during state restore",
      cpp_mut=[(r"if\s*\(\s*restoringPresetState\s*\.\s*load\s*\(\s*\)\s*\)"
                r"\s*return\s*;", "")])
probe("setStateInformation store(true) dropped",
      "replaceState would fan out into loadPreset() and stamp the parameter "
      "set during a session load",
      cpp_mut=[(r"restoringPresetState\s*\.\s*store\s*\(\s*true\s*\)\s*;",
                "")])
probe("setStateInformation store(false) dropped",
      "every later preset change would be permanently ignored",
      cpp_mut=[(r"restoringPresetState\s*\.\s*store\s*\(\s*false\s*\)\s*;",
                "")])
probe("setStateInformation calls loadPreset",
      "state restore must apply stored values, not stamp a factory preset",
      cpp_mut=[(r"restoringPresetState\.store\(false\);",
                "loadPreset(0); restoringPresetState.store(false);")])

# (D) program change / state round-trip / editor attachment
probe("setCurrentProgram stops using presetToId[i]",
      "a host program change would recall the wrong preset slot",
      cpp_mut=[(r"convertTo0to1\s*\(\s*\(\s*float\s*\)\s*"
                r"presetToId\s*\[\s*i\s*\]\s*\)",
                "convertTo0to1((float) i)")])
probe("getStateInformation drops copyState",
      "the preset value would stop round-tripping with the session",
      cpp_mut=[(r"apvts\s*\.\s*copyState\s*\(\s*\)", "apvts.state")])
probe("editor PresetComboAttachment removed",
      "the editor combo would stop showing and recalling presets",
      editor_mut=[(r"std::make_unique<PresetComboAttachment>\s*\([^;]*\)",
                   "nullptr")])
probe("restoringPresetState flag removed from the header",
      "state restore could no longer suppress the preset listener",
      hdr_mut=[(r"std::atomic\s*<\s*bool\s*>\s+restoringPresetState"
                r"\s*\{\s*false\s*\}\s*;", "bool restoringPresetState = false;")])

# no-op guard: benign edits inside/around the pinned shapes must still pass
benign_cpp = mutate(cpp_text,
                    r"withAutomatable\(false\)",
                    "withAutomatable( false )",
                    label="benign registration spacing")
benign_cpp = mutate(benign_cpp,
                    r"int\s+id\s*=\s*static_cast<int>\(newValue \+ 0\.5f\);",
                    "// benign probe comment\n        "
                    "int id = static_cast<int>(newValue + 0.5f);",
                    label="benign comment in parameterChanged")
try:
    check(benign_cpp, hdr_text, edit_text)
except Reject as exc:
    fail(f"a benign comment/whitespace edit was REJECTED — the checker "
         f"over-fires: {exc}")
print("cv041: benign no-op edits pass (probe specificity proven)")

# Final live re-verification (the real tree was never written to).
try:
    check(CPP.read_text(encoding="utf-8"), HDR.read_text(encoding="utf-8"),
          EDIT.read_text(encoding="utf-8"))
except Reject as exc:
    fail(f"final source re-verification failed: {exc}")
print("CV-041 OK")
