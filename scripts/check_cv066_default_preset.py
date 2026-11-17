#!/usr/bin/env python3
"""Headless checker: CV-066 — a freshly inserted Corvus FX plays the default
preset (0, "Clean Sparkle") silently, and a host program recall does not load
the same preset twice.

The defect this pins. Before CV-066 a newly inserted processor kept whatever
its parameter defaults happened to leave behind, so the plugin showed one
preset name in the editor while its mix parameters belonged to no preset at
all; and setCurrentProgram() wrote the "preset" parameter, whose listener
echoed straight back into loadPreset() for the index it had just loaded, so a
host program change stamped the whole parameter set twice (the second time
behind the host's own change gesture).

The settled shape, all pinned here:

  PluginProcessor.h
    * `std::atomic<bool> presetLoadSilent{false};`
    * `std::atomic<int> hostProgramRecall{-1};`
  PluginProcessor.cpp
    * `class SilentPresetLoad final` — RAII guard that arms the flag on
      construction and clears it in the destructor (every exit path).
    * the constructor, after startTimerHz(30), runs
      `SilentPresetLoad silentLoad(presetLoadSilent); loadPreset(0);` and then
      re-seeds `lastGoodGeneration = readParameterGeneration(...)`. It opens no
      undo transaction, no change gesture and no host notification.
    * loadPreset (signature unchanged): bounds guard, then the echo skip
      `if (!presetLoadSilent.load() && hostProgramRecall.exchange(-1) == index)
      return;`, then a CONDITIONAL `beginNewTransaction("Load Preset")`. The
      write lambda's silent branch uses `param->setValue(param->convertTo0to1(v))`
      — no gesture, no notification, no transaction.
    * setCurrentProgram: inside the [0,36) guard,
      `hostProgramRecall.store(-1); loadPreset(i); hostProgramRecall.store(i);`
      BEFORE the existing pinned presetToId[] parameter write.
    * parameterChanged is untouched by the new flags (the echo skip lives in
      loadPreset, not in the listener).

Asserts are comment-stripped and brace-matched, so formatting edits stay
accepted; only the pinned shapes matter. Negative self-probes run on mutated
in-memory texts — the real tree is never mutated, and a mutation that does not
apply is a hard "stale probe" failure.

Exit 0 = ok, 1 = violation with a cited diagnostic.
"""
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SRC = ROOT / "source" / "DrippyFX"
CPP = SRC / "PluginProcessor.cpp"
HDR = SRC / "PluginProcessor.h"


def fail(msg):
    print(f"CV066-DEFAULT-PRESET FAIL: {msg}")
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


def squash(txt):
    """Remove every whitespace run, so shape asserts ignore formatting."""
    return re.sub(r"\s+", "", txt)


def brace_end(txt, open_index):
    """Index just past the brace-matched block that opens at open_index."""
    depth = 0
    for j in range(open_index, len(txt)):
        if txt[j] == "{":
            depth += 1
        elif txt[j] == "}":
            depth -= 1
            if depth == 0:
                return j + 1
    return None


def braced(txt, marker):
    """(open, end, block) of the first '{' at/after marker, or None."""
    k = txt.find(marker)
    if k == -1:
        return None
    o = txt.find("{", k)
    if o == -1:
        return None
    end = brace_end(txt, o)
    if end is None:
        return None
    return o, end, txt[o:end]


def verify(cpp_raw, header_raw):
    """Return a list of violation strings (empty = ok)."""
    errors = []
    code = strip_comments(cpp_raw)
    header = strip_comments(header_raw)
    flat_header = squash(header)

    # ---- 1. header atomics --------------------------------------------------
    for needle, label in (
            ("std::atomic<bool>presetLoadSilent{false};",
             "`std::atomic<bool> presetLoadSilent{false};`"),
            ("std::atomic<int>hostProgramRecall{-1};",
             "`std::atomic<int> hostProgramRecall{-1};`"),
    ):
        if needle not in flat_header:
            errors.append(f"PluginProcessor.h lost {label} — the silent "
                          "construction load and the host program-change echo "
                          "cannot be told apart from a live recall (CV-066)")

    # ---- 2. the SilentPresetLoad RAII guard ---------------------------------
    guard = braced(code, "class SilentPresetLoad final")
    if guard is None:
        errors.append("PluginProcessor.cpp lost the `class SilentPresetLoad "
                      "final` RAII guard — the construction-time preset load "
                      "would raise a transaction, gestures and host "
                      "notifications")
    else:
        flat_guard = squash(guard[2])
        if "explicitSilentPresetLoad(std::atomic<bool>&flag)" not in flat_guard:
            errors.append("SilentPresetLoad must take the "
                          "`std::atomic<bool>&` flag in its constructor")
        if "flag.store(true," not in flat_guard:
            errors.append("SilentPresetLoad must arm the flag on construction")
        if "~SilentPresetLoad(){flag.store(false," not in flat_guard:
            errors.append("SilentPresetLoad must clear the flag in its "
                          "destructor so an early return or exception cannot "
                          "leave every later recall silent")

    # ---- 3. the constructor's silent default load ---------------------------
    ctor = braced(code, "CorvusFXAudioProcessor::CorvusFXAudioProcessor(")
    if ctor is None:
        errors.append("could not find the CorvusFXAudioProcessor constructor "
                      "body")
    else:
        body = ctor[2]
        flat = squash(body)
        if flat.count("loadPreset(") != 1 or "loadPreset(0);" not in flat:
            errors.append("the constructor must load exactly one preset — the "
                          "factory default `loadPreset(0);` — so a freshly "
                          "inserted FX plays preset 0 (\"Clean Sparkle\")")
        guard_needle = "SilentPresetLoadsilentLoad(presetLoadSilent);"
        load_needle = "loadPreset(0);"
        reseed_needle = ("lastGoodGeneration="
                         "readParameterGeneration(lastGoodGeneration);")
        g = flat.find(guard_needle)
        load = flat.find(load_needle)
        reseed = flat.rfind(reseed_needle)
        if g == -1:
            errors.append("the constructor must arm the silent load "
                          "(`SilentPresetLoad silentLoad(presetLoadSilent);`) "
                          "before loading the default preset — otherwise the "
                          "load notifies the host and opens a gesture")
        elif load != -1:
            if g > load:
                errors.append("the constructor's SilentPresetLoad guard must be "
                              "armed BEFORE loadPreset(0)")
            elif "}" in flat[g + len(guard_needle):load]:
                errors.append("loadPreset(0) sits outside the SilentPresetLoad "
                              "scope — the guard's destructor already fired, so "
                              "the load is not silent")
        if load != -1 and (reseed == -1 or reseed < load):
            errors.append("the constructor must re-seed "
                          "`lastGoodGeneration = readParameterGeneration(...)` "
                          "AFTER the silent loadPreset(0), so the first block "
                          "does not fall back on the pre-load generation")
        for needle, call in (("beginNewTransaction", "an undo transaction"),
                             ("beginChangeGesture", "a change gesture"),
                             ("setValueNotifyingHost", "a host notification")):
            if needle in flat:
                errors.append(f"the constructor must not raise {call} "
                              f"({needle}) — a newly inserted FX has no user "
                              "edit and the host never asked for a change")

    # ---- 4. setCurrentProgram's direct reload + echo marker -----------------
    scp = braced(code, "CorvusFXAudioProcessor::setCurrentProgram(")
    if scp is None:
        errors.append("could not find the setCurrentProgram body")
    else:
        body = scp[2]
        band = re.search(r"if\s*\(\s*i\s*>=\s*0\s*&&\s*i\s*<\s*36\s*\)\s*\{",
                         body)
        band_end = brace_end(body, band.end() - 1) if band else None
        off = re.search(r"\bhostProgramRecall\s*\.\s*store\s*\(\s*-1\s*\)\s*;",
                        body)
        reload_ = re.search(r"\bloadPreset\s*\(\s*i\s*\)\s*;", body)
        on = re.search(r"\bhostProgramRecall\s*\.\s*store\s*\(\s*i\s*\)\s*;",
                       body)
        notify = re.search(r"setValueNotifyingHost\s*\(", body)
        if off is None or reload_ is None or on is None:
            errors.append("setCurrentProgram must load the selected preset "
                          "directly: `hostProgramRecall.store(-1); "
                          "loadPreset(i); hostProgramRecall.store(i);` inside "
                          "the [0,36) guard — without it a host program change "
                          "only re-labels the combo and leaves the previous "
                          "preset's mix parameters playing")
        else:
            if not (off.end() <= reload_.start()
                    and reload_.end() <= on.start()):
                errors.append("setCurrentProgram must clear the echo marker, "
                              "reload the preset and only then arm the marker "
                              "for the preset-parameter write, in that order — "
                              "an armed marker would make loadPreset(i) skip "
                              "its own load")
            if notify is not None and on.start() > notify.start():
                errors.append("setCurrentProgram arms hostProgramRecall AFTER "
                              "the preset-parameter write — the listener echo "
                              "would already have reloaded the preset a second "
                              "time")
            if band is None or band_end is None:
                errors.append("the setCurrentProgram [0,36) bounds guard is "
                              "missing")
            else:
                for match, label in ((off, "hostProgramRecall.store(-1)"),
                                     (reload_, "loadPreset(i)"),
                                     (on, "hostProgramRecall.store(i)")):
                    if not (band.start() < match.start() < band_end):
                        errors.append(f"setCurrentProgram's {label} must run "
                                      "inside the `if (i >= 0 && i < 36)` "
                                      "guard")

    # ---- 5. loadPreset: echo skip, silent writes, conditional transaction --
    lp = braced(code, "CorvusFXAudioProcessor::loadPreset(")
    if lp is None:
        errors.append("could not find the loadPreset definition body")
    else:
        body = lp[2]
        bounds = re.search(r"if\s*\(\s*index\s*<\s*0\s*\|\|\s*index\s*>=\s*36"
                           r"\s*\)\s*return\s*;", body)
        echo = re.search(
            r"if\s*\(\s*!\s*presetLoadSilent\s*\.\s*load\s*\(\s*\)\s*&&\s*"
            r"hostProgramRecall\s*\.\s*exchange\s*\(\s*-1\s*\)\s*==\s*index"
            r"\s*\)\s*return\s*;", body)
        txn = re.search(
            r"if\s*\(\s*!\s*presetLoadSilent\s*\.\s*load\s*\(\s*\)\s*\)\s*"
            r"undoManager\s*\.\s*beginNewTransaction\s*\(\s*\"Load Preset\""
            r"\s*\)\s*;", body)
        write = re.search(r'\bset\s*\(\s*"fatness"', body)
        if bounds is None:
            errors.append("loadPreset lost its own bounds return")
        if echo is None:
            errors.append("loadPreset must consume the host program-change echo: "
                          "`if (!presetLoadSilent.load() && "
                          "hostProgramRecall.exchange(-1) == index) return;` — "
                          "without it a setCurrentProgram() recall loads the "
                          "same preset twice")
        if txn is None:
            errors.append("loadPreset's `beginNewTransaction(\"Load Preset\")` "
                          "must stay conditional on `!presetLoadSilent.load()` "
                          "— the silent construction-time load must not leave "
                          "an undo entry")
        if body.count("beginNewTransaction") != 1:
            errors.append("loadPreset must open at most its one named "
                          "\"Load Preset\" transaction")
        if bounds is not None and echo is not None:
            if echo.start() < bounds.end():
                errors.append("the echo skip must run AFTER loadPreset's bounds "
                              "guard")
            if txn is not None:
                if not (echo.end() <= txn.start()):
                    errors.append("the echo skip must run BEFORE the \"Load "
                                  "Preset\" transaction so a skipped echo opens "
                                  "no empty undo entry")
                if write is not None and not (txn.start() < write.start()):
                    errors.append("loadPreset's transaction must open before "
                                  "its first parameter write")

        silent_branch = re.search(
            r"if\s*\(\s*presetLoadSilent\s*\.\s*load\s*\(\s*\)\s*\)\s*\{", body)
        if silent_branch is None:
            errors.append("the loadPreset write lambda lost its silent branch "
                          "`if (presetLoadSilent.load()) { ... }`")
        else:
            end = brace_end(body, silent_branch.end() - 1)
            block = body[silent_branch.start():end] if end else ""
            if not re.search(r"param\s*->\s*setValue\s*\(\s*param\s*->\s*"
                             r"convertTo0to1\s*\(\s*v\s*\)\s*\)\s*;", block):
                errors.append("the silent branch must write through "
                              "`param->setValue(param->convertTo0to1(v));`")
            for needle, what in (("beginChangeGesture", "a change gesture"),
                                 ("endChangeGesture", "a change gesture"),
                                 ("setValueNotifyingHost", "a host notification"),
                                 ("beginNewTransaction", "an undo transaction")):
                if needle in block:
                    errors.append(f"the silent load branch must not raise "
                                  f"{what} ({needle}) — a construction-time "
                                  "preset load is invisible to the host and to "
                                  "the undo history")
            notify_write = body.find("param->beginChangeGesture();")
            if notify_write != -1 and silent_branch.start() > notify_write:
                errors.append("the silent branch must come BEFORE the "
                              "beginChangeGesture/setValueNotifyingHost path")
        if not re.search(r"param\s*->\s*setValueNotifyingHost\s*\(\s*param\s*->"
                         r"\s*convertTo0to1\s*\(\s*v\s*\)\s*\)\s*;", body):
            errors.append("the live (non-silent) preset write must still go "
                          "through "
                          "`param->setValueNotifyingHost(param->convertTo0to1(v))`")

    # ---- 6. parameterChanged stays byte-for-byte unchanged ------------------
    changed = braced(code, "CorvusFXAudioProcessor::parameterChanged(")
    if changed is None:
        errors.append("could not find the parameterChanged body")
    elif "presetLoadSilent" in changed[2] or "hostProgramRecall" in changed[2]:
        errors.append("parameterChanged must stay byte-for-byte unchanged — the "
                      "silent flag and the program-recall echo marker belong to "
                      "loadPreset/setCurrentProgram, not to the preset listener")

    return errors


def sub1(text, pattern, repl, label):
    """First-occurrence substitution; a mutation that does not apply is fatal."""
    out, n = re.subn(pattern, repl, text, count=1)
    if n == 0 or out == text:
        fail(f"probe '{label}': NO-OP MUTATION — the pattern is absent from the "
             "live source, so the negative check is stale")
    return out


for path in (CPP, HDR):
    if not path.exists():
        fail(f"missing source file {path}")
try:
    cpp_text = CPP.read_text(encoding="utf-8")
    hdr_text = HDR.read_text(encoding="utf-8")
except OSError as exc:  # pragma: no cover - environment failure
    fail(f"could not read source: {exc}")

errors = verify(cpp_text, hdr_text)
if errors:
    fail("CV-066 default-preset invariants violated:\n  - "
         + "\n  - ".join(errors))
print("cv066: header carries presetLoadSilent + hostProgramRecall; the "
      "constructor's guarded loadPreset(0) is silent and re-seeds "
      "lastGoodGeneration; setCurrentProgram reloads directly and marks the "
      "echo; loadPreset skips the echo and stays silent at construction")

# ---------------------------------------------------------------------------
# Negative self-probes on mutated in-memory texts (real tree never mutated)
# ---------------------------------------------------------------------------

def probe(label, cpp_mut, hdr_mut=None):
    new_cpp = cpp_mut(cpp_text) if cpp_mut else cpp_text
    new_hdr = hdr_mut(hdr_text) if hdr_mut else hdr_text
    if (new_cpp, new_hdr) == (cpp_text, hdr_text):
        fail(f"probe '{label}': NO-OP MUTATION — the negative check is stale")
    if not verify(new_cpp, new_hdr):
        fail(f"negative probe '{label}' was NOT rejected — the checker is "
             "vacuous")
    print(f"cv066: negative probe '{label}' rejected")


# (a) the constructor's silent default load + its guard + the re-seed
probe("constructor's loadPreset(0) removed (a fresh insert plays no preset)",
      lambda t: sub1(t, r"\n        loadPreset\(0\);", "\n",
                     "constructor loadPreset(0) removed"))
probe("constructor's SilentPresetLoad guard dropped (the load notifies and "
      "opens a gesture)",
      lambda t: sub1(t, r"\n        SilentPresetLoad silentLoad\("
                        r"presetLoadSilent\);", "\n",
                     "SilentPresetLoad guard dropped"))
probe("constructor's lastGoodGeneration re-seed dropped (first block falls "
      "back on the pre-load generation)",
      lambda t: sub1(t, r"    lastGoodGeneration = readParameterGeneration"
                        r"\(lastGoodGeneration\);\n\}\n\nCorvusFXAudioProcessor"
                        r"::~CorvusFXAudioProcessor\(\)",
                     "}\n\nCorvusFXAudioProcessor::~CorvusFXAudioProcessor()",
                     "lastGoodGeneration re-seed dropped"))
probe("constructor opens an undo transaction (a fresh insert looks like a "
      "user edit)",
      lambda t: sub1(t, r"        loadPreset\(0\);",
                     '        undoManager.beginNewTransaction("Probe");\n'
                     "        loadPreset(0);",
                     "constructor transaction"))
probe("constructor notifies the host directly (automation lane records the "
      "insert)",
      lambda t: sub1(t, r"        loadPreset\(0\);",
                     "        getParameters()[0]->setValueNotifyingHost(0.0f);\n"
                     "        loadPreset(0);",
                     "constructor host notification"))

# (b) setCurrentProgram's direct reload + marker order
probe("setCurrentProgram stops reloading the preset directly (a host program "
      "change only re-labels the combo)",
      lambda t: sub1(t, r"\n        loadPreset\(i\);", "\n",
                     "setCurrentProgram reload removed"))
probe("setCurrentProgram arms the echo marker before the direct reload (the "
      "reload would skip itself)",
      lambda t: sub1(t, r"        hostProgramRecall\.store\(-1\);\n"
                        r"        loadPreset\(i\);",
                     "        hostProgramRecall.store(i);\n"
                     "        loadPreset(i);",
                     "setCurrentProgram marker order swapped"))
def arm_marker_after_preset_write(t):
    """Move the echo marker arm below the preset-parameter write."""
    t = sub1(t,
             r"        hostProgramRecall\.store\(i\);\n        auto\* p = ",
             "        auto* p = ",
             "setCurrentProgram marker armed too late (remove)")
    return sub1(
        t,
        r"            if \(p\) p->setValueNotifyingHost\("
        r"p->convertTo0to1\(\(float\)presetToId\[i\]\)\);\n",
        "            if (p) p->setValueNotifyingHost("
        "p->convertTo0to1((float)presetToId[i]));\n"
        "            hostProgramRecall.store(i);\n",
        "setCurrentProgram marker armed too late (re-arm)")


probe("setCurrentProgram arms the echo marker after the preset-parameter "
      "write (the listener echo reloads the preset twice)",
      arm_marker_after_preset_write)

# (c) loadPreset's echo-skip consumption
probe("loadPreset drops the echo skip (a host program change loads the preset "
      "twice)",
      lambda t: sub1(t, r"\n    if \(!presetLoadSilent\.load\(\) && "
                        r"hostProgramRecall\.exchange\(-1\) == index\)\n"
                        r"        return;\n", "\n",
                     "echo skip removed"))
probe("loadPreset's echo skip no longer ignores the silent load flag (a silent "
      "load consumes the program marker)",
      lambda t: sub1(t, r"if \(!presetLoadSilent\.load\(\) && "
                        r"hostProgramRecall\.exchange\(-1\) == index\)",
                     "if (hostProgramRecall.exchange(-1) == index)",
                     "echo skip silent guard dropped"))
probe("loadPreset's echo skip no longer consumes the marker (a stale marker "
      "would swallow the next real recall)",
      lambda t: sub1(t, r"hostProgramRecall\.exchange\(-1\) == index",
                     "hostProgramRecall.load() == index",
                     "echo skip marker consumption dropped"))

# (d) silent-mode no-transaction / no-gesture / no-notify
probe("loadPreset opens its undo transaction unconditionally (the silent "
      "construction load leaves an undo entry)",
      lambda t: sub1(t, r"if \(!presetLoadSilent\.load\(\)\)\n"
                        r"        undoManager\.beginNewTransaction"
                        r"\(\"Load Preset\"\);",
                     'undoManager.beginNewTransaction("Load Preset");',
                     "unconditional transaction"))
probe("silent load branch notifies the host instead of setValue()",
      lambda t: sub1(t, r"param->setValue\(param->convertTo0to1\(v\)\);",
                     "param->setValueNotifyingHost(param->convertTo0to1(v));",
                     "silent branch notification"))
probe("silent load branch opens a change gesture",
      lambda t: sub1(t, r"param->setValue\(param->convertTo0to1\(v\)\);",
                     "param->beginChangeGesture();\n"
                     "                param->setValue("
                     "param->convertTo0to1(v));",
                     "silent branch gesture"))
probe("silent load branch opens an undo transaction",
      lambda t: sub1(t, r"param->setValue\(param->convertTo0to1\(v\)\);",
                     'undoManager.beginNewTransaction("Probe");\n'
                     "                param->setValue("
                     "param->convertTo0to1(v));",
                     "silent branch transaction"))
probe("silent branch removed (every write notifies the host)",
      lambda t: sub1(t, r"            if \(presetLoadSilent\.load\(\)\)\n"
                        r"            \{\n"
                        r"                param->setValue\("
                        r"param->convertTo0to1\(v\)\);\n"
                        r"                return;\n"
                        r"            \}\n",
                     "",
                     "silent branch removed"))

# (e) the header atomics
probe("header's presetLoadSilent atomic removed",
      None,
      lambda t: sub1(t, r"std::atomic<bool> presetLoadSilent\{false\};",
                     "bool presetLoadSilent = false;",
                     "presetLoadSilent removed"))
probe("header's hostProgramRecall atomic removed",
      None,
      lambda t: sub1(t, r"std::atomic<int> hostProgramRecall\{-1\};",
                     "int hostProgramRecall = -1;",
                     "hostProgramRecall removed"))

# no-op guard: a benign comment edit inside the pinned region stays accepted
neutral = cpp_text.replace(
    "        SilentPresetLoad silentLoad(presetLoadSilent);",
    "        // benign probe comment\n"
    "        SilentPresetLoad silentLoad(presetLoadSilent);", 1)
if neutral == cpp_text:
    fail("no-op guard: unanchored neutral edit did not change the source")
if verify(neutral, hdr_text):
    fail("neutral edit outside the pinned shapes was REJECTED — the checker "
         "over-fires: " + verify(neutral, hdr_text)[0])
print("cv066: benign comment edit passes (probe specificity)")

# real tree never mutated - re-verify the live sources once more before gating
errors = verify(CPP.read_text(encoding="utf-8"), HDR.read_text(encoding="utf-8"))
if errors:
    fail("final source re-verification failed: " + errors[0])
print("CV066-DEFAULT-PRESET OK")
sys.exit(0)
