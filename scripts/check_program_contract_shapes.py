#!/usr/bin/env python3
"""Headless checker: host-program-contract trio pin (setCurrentProgram /
getProgramName / changeProgramName).

setCurrentProgram (PluginProcessor.cpp): `if (i >= 0 && i < 36)` then
`apvts.getParameter("preset")` with an `if (p)` null guard before
setValueNotifyingHost.
getProgramName: static 36-name table returned via
`(i >= 0 && i < 36) ? n[i] : juce::String()`.
changeProgramName: deliberate no-op `void CorvusFXAudioProcessor::
changeProgramName(int, const juce::String&) {}`.

No other checker pins these: check_preset_tables.py pins getNumPrograms()
==36 and the name-table COUNT; check_preset_combo_runtime.py pins the
presetToId[] contents and the deref existence inside setCurrentProgram —
none pins (a) the bounds, (b) the empty-string fallback, (c) the no-op
body, or (d) the `if (p)` null-parameter guard.

Designed-in hazards (compile clean behind an otherwise-green gate):
  - dropping the bounds lets a host call getProgramName(47) read past the
    static array (OOB juce::String construction in a host-visible
    message-thread call);
  - `return n[0]` fallback makes every out-of-range program report
    "Clean Sparkle" so a host UI mislabels;
  - removing `if (p)` null-checks a nonexistent parameter deref.

Asserts are comment-stripped, brace-matched on the three bodies.
Negative self-probes run on mutated in-memory texts — the real tree is
never mutated. Exit 0 = ok, 1 = violation with diagnostics.
"""
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SRC = ROOT / "source" / "DrippyFX"


def fail(msg):
    print(f"PROGRAM-CONTRACT-TRIO FAIL: {msg}")
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
    # find the '{' at the end of the signature (first '{' after marker is
    # fine here: the three bodies have no default-arg braces)
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


def collapse_ws(s):
    return re.sub(r"\s+", " ", s).strip()


def check_set_current_program(body):
    body = collapse_ws(body)
    m = re.search(r'if \(i >= 0 && i < (\d+)\) \{', body)
    if not m:
        return ("the setCurrentProgram bounds guard "
                "`if (i >= 0 && i < 36) {` drifted — dropping the upper "
                "bound turns any host program index beyond 35 into an OOB "
                "read of presetToId")
    if m.group(1) != "36":
        return (f"the setCurrentProgram id bound is {m.group(1)}, expected "
                f"36 (matches the presetToId[36] table size)")
    if 'apvts.getParameter("preset")' not in body:
        return 'the `apvts.getParameter("preset")` deref is gone'
    if not re.search(r'if \(p\) p->setValueNotifyingHost\(', body):
        return ("the `if (p)` null-parameter guard before "
                "setValueNotifyingHost drifted — a nonexistent \"preset\" "
                "parameter would be null-dereffed")
    if re.search(r'setValueNotifyingHost', collapse_ws(body)) and \
            not re.search(r'convertTo0to1\(\(float\)presetToId\[i\]\)', body):
        return ("the `convertTo0to1((float)presetToId[i])` argument form "
                "drifted")
    return None


def check_get_program_name(body):
    body = collapse_ws(body)
    if "static const juce::String n[36]" not in body:
        return "the static 36-name table `static const juce::String n[36]` drifted"
    m = re.search(
        r'return \(i >= 0 && i < (\d+)\) \? n\[i\] : juce::String\(\);',
        body)
    if not m:
        return ("the getProgramName ternary "
                "`return (i >= 0 && i < 36) ? n[i] : juce::String();` "
                "drifted — dropping the bounds reads past the static table "
                "(OOB) and changing the fallback to n[0] mislabels every "
                "out-of-range program as \"Clean Sparkle\"")
    if m.group(1) != "36":
        return (f"the getProgramName bounds are {m.group(1)}, expected 36 "
                f"(matches the n[36] table size)")
    return None


def check_change_program_name(body):
    body = collapse_ws(body)
    if collapse_ws(body) != "{}":
        return ("changeProgramName must remain a deliberate empty no-op "
                "{} — the juce host contract here is that program names "
                "are read-only (only the preset combo changes programs)")
    return None


proc_c_path = SRC / "PluginProcessor.cpp"
if not proc_c_path.exists():
    fail(f"missing source file {proc_c_path_path}" if False else
         f"missing source file {proc_c_path}")
proc_c = proc_c_path.read_text()

for fn, checker in (("setCurrentProgram", check_set_current_program),
                    ("getProgramName", check_get_program_name),
                    ("changeProgramName", check_change_program_name)):
    err = checker(extract_body(proc_c, fn))
    if err:
        fail(err + f" (PluginProcessor.cpp {fn})")
print("program-contract-trio: setCurrentProgram bound+null-guard, "
      "getProgramName bounds+empty-string fallback, changeProgramName "
      "no-op pinned")

# ---------------------------------------------------------------------------
# Self-probes on mutated in-memory texts (real tree never mutated)
# ---------------------------------------------------------------------------

def probe(description, old, new, count=1, fn=None):
    tmp_raw = proc_c.replace(old, new, count)
    if tmp_raw == proc_c:
        print(f"program-contract-trio: no-op mutation guard -> skipping "
              f"invalid probe ({description})")
        return
    fn = fn or "setCurrentProgram"
    checker = {"setCurrentProgram": check_set_current_program,
               "getProgramName": check_get_program_name,
               "changeProgramName": check_change_program_name}[fn]
    if checker(extract_body(tmp_raw, fn)) is None:
        print(f"program-contract-trio: SELF-PROBE FAIL (checker should "
              f"reject): {description}")
        sys.exit(1)
    print(f"program-contract-trio: self-probe fired: {description} -> "
          f"rejected")


# setCurrentProgram
probe("setCurrentProgram id bound widened 36->43 (desync with presetToId)",
      "if (i >= 0 && i < 36) {",
      "if (i >= 0 && i < 43) {")
probe("setCurrentProgram null-parameter guard dropped (null-deref of a "
      "nonexistent \"preset\" parameter)",
      'if (p) p->setValueNotifyingHost(p->convertTo0to1((float)presetToId[i]));',
      'p->setValueNotifyingHost(p->convertTo0to1((float)presetToId[i]));')
probe("setCurrentProgram table subscript dropped (no preset id applied)",
      "p->setValueNotifyingHost(p->convertTo0to1((float)presetToId[i]));",
      "p->setValueNotifyingHost(p->convertTo0to1((float)presetToId[0]));",
      fn="setCurrentProgram")

# getProgramName
probe("getProgramName fallback `juce::String()` -> `n[0]` (every "
      "out-of-range program mislabeled \"Clean Sparkle\" in a host UI)",
      "return (i >= 0 && i < 36) ? n[i] : juce::String();",
      "return (i >= 0 && i < 36) ? n[i] : n[0];",
      fn="getProgramName")
probe("getProgramName bounds dropped (OOB read of the static name table "
      "for any host index outside [0,36))",
      "return (i >= 0 && i < 36) ? n[i] : juce::String();",
      "return n[i];",
      fn="getProgramName")

# changeProgramName
probe("changeProgramName no-op given a real body (out-of-contract "
      "program-name writes)",
      "void CorvusFXAudioProcessor::changeProgramName(int, const juce::String&) {}",
      "void CorvusFXAudioProcessor::changeProgramName(int, const juce::String&) "
      "{ /* edited */ }",
      fn="changeProgramName")

# no-op guard: benign comment addition stays accepted
tmp = proc_c.replace(
    "void CorvusFXAudioProcessor::changeProgramName(int, const juce::String&) {}",
    "void CorvusFXAudioProcessor::changeProgramName(int, const juce::String&) "
    "{} /* benign */", 1)
if tmp != proc_c:
    if check_change_program_name(extract_body(tmp, "changeProgramName")) \
            is not None:
        fail("no-op guard: benign edit was wrongly rejected")
print("program-contract-trio: no-op guard passed (benign edit accepted)")

print("PROGRAM-CONTRACT OK")
