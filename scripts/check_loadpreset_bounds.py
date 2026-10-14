#!/usr/bin/env python3
"""Headless checker: loadPreset's OWN bounds-return guard pin.

The loadPreset body opens with a definition-side bounds return BEFORE any
side effect:

  if (index < 0 || index >= 36) return;      (PluginProcessor.cpp:56)
  undoManager.beginNewTransaction("Load Preset");  (:57)
  ... presets[36] static table read via `const auto& p = presets[index];`

The call sites / tables are pinned elsewhere (check_preset_load_sites.py
pins the sole call site + transaction ordering, check_preset_tables.py pins
row contents, check_paramchanged_guard.py pins the 2..42 caller window) —
all of those defend the CALLER. NOTHING pins the CALLEE's own guard.
Falsifications (all compile clean behind an otherwise-green gate):
  - dropping the guard means loadPreset(-1) / loadPreset(36) reaches
    `presets[index]` on the static P[36] table — an OOB struct read feeding
    setValueNotifyingHost with garbage across all 23 non-preset parameters
    (hypothetical future caller without a presetToId[] hop);
  - hoisting the bounds check BELOW beginNewTransaction opens an undo
    transaction with no change (empty-history entry) — the txn-before-write
    invariant does not pin txn-after-bounds;
  - drifting the bound literal 36 -> 43 desyncs the guard from
    presets[36] and getNumPrograms() == 36 (a loadPreset(40) succeeds on
    a table that only has 36 rows once tables grow apart).

Asserts (comment-stripped, on the real PluginProcessor.cpp):
  (a) the loadPreset body's FIRST statement is
      `if (index < 0 || index >= 36) return;`;
  (b) `undoManager.beginNewTransaction("Load Preset");` appears AFTER the
      guard (transaction only begins once the index is proven in-range);
  (c) roster lock — the bound literal is EXACTLY 36 (sync with
      presets[36] and getNumPrograms()).

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
    print(f"LOADPRESET-BOUNDS FAIL: {msg}")
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


def extract_loadpreset_body(code):
    """Brace-matched extract of `void CorvusFXAudioProcessor::loadPreset(int index) { ... }`."""
    m = re.search(r"void\s+CorvusFXAudioProcessor::loadPreset\s*\(\s*int\s+index\s*\)", code)
    if not m:
        return None
    i = code.find("{", m.end())
    if i == -1:
        return None
    depth = 0
    for j in range(i, len(code)):
        if code[j] == "{":
            depth += 1
        elif code[j] == "}":
            depth -= 1
            if depth == 0:
                return code[i + 1:j]
    return None


def _verify(code):
    body = extract_loadpreset_body(strip_comments(code))
    if body is None:
        return "could not locate the loadPreset definition body"

    first_stmt = collapse(body).split(";")[0] + ";"

    # (a) first statement is the definition-side bounds return
    if first_stmt != "if (index < 0 || index >= 36) return;":
        return (f"loadPreset's first statement is '{first_stmt}', expected "
                f"'if (index < 0 || index >= 36) return;' — a dropped or "
                f"drifted guard lets loadPreset(-1)/loadPreset(36) reach "
                f"presets[index] (OOB struct read feeding "
                f"setValueNotifyingHost with garbage)")

    # (b) transaction AFTER the guard
    g = first_stmt
    # find the guard position and beginNewTransaction position in flattened body
    flat = collapse(body)
    pos_g = flat.find(g)
    pos_t = flat.find('undoManager.beginNewTransaction("Load Preset");')
    if pos_t == -1:
        return ('loadPreset no longer opens the "Load Preset" undo '
                'transaction — the restore path goes silent in the '
                'undo history')
    if pos_t < pos_g:
        return ("loadPreset begins its undo transaction BEFORE the bounds "
                "guard — a hoisted guard opens an undo transaction with no "
                "change when the index is out of range (empty-history entry)")
    return None


cpp_raw = CPP.read_text()
if not CPP.exists():
    fail(f"missing source file {CPP}")
code = cpp_raw

err = _verify(code)
if err:
    fail(err)

# (c) roster lock: the bound literal must be exactly 36 in the body
body = extract_loadpreset_body(strip_comments(code)) or ""
bounds = re.findall(r"index\s*(<|>=)\s*(\d+)", body)
if sorted(bounds, key=lambda b: body.find(f"index {b[0]}")) != [("<", "0"), (">=", "36")]:
    fail(f"loadPreset bounds roster drift: found {bounds}, expected "
         f"exactly [< 0, >= 36] — the guard must stay in sync with "
         f"presets[36] and getNumPrograms() == 36")
print("loadpreset-bounds: first statement guard, txn-after-bounds "
      "ordering, bound literal 36 roster pinned")

# ---------------------------------------------------------------------------
# negative self-probes on mutated in-memory texts (real tree never mutated)
# ---------------------------------------------------------------------------
probes = [
    ("guard deleted (OOB presets[index] read on out-of-range index)",
     "    if (index < 0 || index >= 36) return;",
     ""),
    ("guard hoisted BELOW beginNewTransaction (empty undo transaction "
     "on out-of-range index)",
     "    if (index < 0 || index >= 36) return;\n"
     "    undoManager.beginNewTransaction(\"Load Preset\");",
     "    undoManager.beginNewTransaction(\"Load Preset\");\n"
     "    if (index < 0 || index >= 36) return;"),
    ("bound literal drifted 36 -> 43 (table/guard desync vs presets[36])",
     "if (index < 0 || index >= 36) return;",
     "if (index < 0 || index >= 43) return;"),
    ("bound literal drifted 36 -> 0 (every load rejected, presets dead "
     "but transaction still opened)",
     "if (index < 0 || index >= 36) return;",
     "if (index < 0 || index >= 0) return;"),
]
for label, old, new in probes:
    mutated = cpp_raw.replace(old, new, 1)
    if mutated == cpp_raw:
        fail(f"no-op probe ({label}): mutation did not change the source — "
             "the negative check is stale")
    verdict = _verify(strip_comments(mutated))
    if verdict is None:
        fail(f"negative probe '{label}' was NOT rejected — checker is vacuous")
    print(f"loadpreset-bounds: negative probe '{label}' rejected")

# no-op guard: benign comment addition stays accepted
neutral = cpp_raw.replace(
    'if (index < 0 || index >= 36) return;',
    'if (index < 0 || index >= 36) return;  // probe comment')
if neutral == cpp_raw:
    fail("no-op guard: unanchored neutral edit did not change the source")
if _verify(strip_comments(neutral)) is not None:
    fail("neutral edit outside the pinned shapes was REJECTED — checker "
         "over-fires")
print("loadpreset-bounds: neutral no-op edit passes (probe specificity proven)")

# real tree never mutated — re-verify the live source once more before gating
err = _verify(strip_comments(CPP.read_text()))
if err:
    fail(f"final source re-verification failed: {err}")
print("LOADPRESET-BOUNDS OK")
sys.exit(0)
