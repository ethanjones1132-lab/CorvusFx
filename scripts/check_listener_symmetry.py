#!/usr/bin/env python3
"""Headless checker: preset-listener CONNECT/DISCONNECT symmetry pin.

The processor registers its ONE apvts parameter listener wiring as a
constructor/destructor pair:

  ctor:  apvts.addParameterListener("preset", this);     (PluginProcessor.cpp:21)
  dtor:  apvts.removeParameterListener("preset", this);  (:26)

This is the sole parameter-listener wiring in the tree; parameterChanged's
body and its call sites are pinned by other checkers, but NOTHING pins the
add/remove pair itself. Falsifications (all compile clean behind an
otherwise-green gate):
  - deleting the destructor's removeParameterListener call leaves the
    listener registered on a destroyed AudioProcesssorWithParameterTree
    invocation path (teardown callback delivered into a
    partially-deconstructed processor — use-after-free class);
  - removing only the constructor registration silences the preset
    ComboBox → loadPreset pipeline while every parameterChanged
    body-shape checker stays green;
  - renaming the "preset" id on ONE side only desyncs the pair
    (removeParameterListener for an id never registered is a silent
    no-op; addParameterListener under a different id silently
    disconnects the pipeline);
  - a double registration on one side breaks the 1:1 symmetric count.

Asserts (comment-stripped, on the real PluginProcessor.cpp):
  (a) exactly one `apvts.addParameterListener("preset", this);`
  (b) exactly one `apvts.removeParameterListener("preset", this);`
      with the SAME "preset" id literal;
  (c) count symmetry across the whole file: 1 add / 1 remove — no
      extra wiring of any id, no orphaned half.

Negative self-probes run on mutated in-memory texts — the real tree is
never mutated. Exit 0 = ok, 1 = violation with diagnostics.
"""
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SRC = ROOT / "source" / "DrippyFX"
CPP = SRC / "PluginProcessor.cpp"


def fail(msg):
    print(f"LISTENER-SYMMETRY FAIL: {msg}")
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


def contract_line(code):  # collapse all whitespace runs so shape asserts ignore indentation
    return collapse(code)


def _verify(code):
    if "{" not in code:
        return "implausible strip_comments result"
    flat = contract_line(code)

    adds = re.findall(
        r'apvts\.addParameterListener\(\s*"([^"]*)"\s*,\s*this\s*\)\s*;', flat)
    removes = re.findall(
        r'apvts\.removeParameterListener\(\s*"([^"]*)"\s*,\s*this\s*\)\s*;', flat)

    # count symmetry: exactly one add and one remove, for ANY id
    if len(adds) != 1:
        return (f"expected EXACTLY 1 apvts.addParameterListener wiring, "
                f"found {len(adds)} — a missing constructor registration "
                f"silences the preset ComboBox → loadPreset pipeline while "
                f"parameterChanged body checkers stay green")
    if len(removes) != 1:
        return (f"expected EXACTLY 1 apvts.removeParameterListener wiring, "
                f"found {len(removes)} — a missing destructor disconnection "
                f"delivers a teardown callback into a partially-deconstructed "
                f"processor (use-after-free class)")
    if adds[0] != removes[0]:
        return (f"listener id asymmetry: addParameterListener('{adds[0]}') "
                f"is disconnected as removeParameterListener('{removes[0]}') "
                f"— the remove call for an id never registered is a silent "
                f"no-op and the registered id leaks into teardown")
    if adds[0] != "preset":
        return (f"the sole listener id is '{adds[0]}', expected 'preset' — "
                f"a renamed id detaches the parameterChanged preset-branch "
                f"pipeline silently")
    return None


cpp_raw = CPP.read_text()
if not CPP.exists():
    fail(f"missing source file {CPP}")
code = strip_comments(cpp_raw)

err = _verify(code)
if err:
    fail(err)
print("listener-symmetry: 1 add / 1 remove both named 'preset', "
      "same-id pairing, whole-file count symmetry pinned")

# ---------------------------------------------------------------------------
# negative self-probes on mutated in-memory texts (real tree never mutated)
# ---------------------------------------------------------------------------
probes = [
    ("destructor removeParameterListener deleted (teardown callback into "
     "a partially-deconstructed processor — use-after-free class)",
     "    apvts.removeParameterListener(\"preset\", this);",
     "    (void)0;"),
    ("constructor addParameterListener deleted (preset ComboBox → "
     "loadPreset pipeline silently dead)",
     "    apvts.addParameterListener(\"preset\", this);",
     "    (void)0;"),
    ('remove-side id renamed "preset" -> "bility"',
     'apvts.removeParameterListener("preset", this);',
     'apvts.removeParameterListener("bility", this);'),
    ("double registration: add wiring duplicated (2 adds / 1 remove)",
     "    apvts.addParameterListener(\"preset\", this);",
     "    apvts.addParameterListener(\"preset\", this);\n"
     "    apvts.addParameterListener(\"preset\", this);"),
]
for label, old, new in probes:
    mutated = cpp_raw.replace(old, new, 1)
    if mutated == cpp_raw:
        fail(f"no-op probe ({label}): mutation did not change the source — "
             "the negative check is stale")
    verdict = _verify(strip_comments(mutated))
    if verdict is None:
        fail(f"negative probe '{label}' was NOT rejected — checker is vacuous")
    print(f"listener-symmetry: negative probe '{label}' rejected")

# no-op guard: benign comment addition stays accepted
neutral = cpp_raw.replace(
    'apvts.addParameterListener("preset", this);',
    'apvts.addParameterListener("preset", this);  // probe comment')
if neutral == cpp_raw:
    fail("no-op guard: unanchored neutral edit did not change the source")
if _verify(strip_comments(neutral)) is not None:
    fail("neutral edit outside the pinned shapes was REJECTED — checker "
         "over-fires")
print("listener-symmetry: neutral no-op edit passes (probe specificity proven)")

# real tree never mutated — re-verify the live source once more before gating
err = _verify(strip_comments(CPP.read_text()))
if err:
    fail(f"final source re-verification failed: {err}")
print("LISTENER-SYMMETRY OK")
sys.exit(0)
