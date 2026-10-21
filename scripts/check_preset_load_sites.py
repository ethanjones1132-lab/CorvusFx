#!/usr/bin/env python3
"""Headless checker: pin the loadPreset call-site set + its undo transaction.

Today the ONLY loadPreset call site in the whole plugin source is inside
parameterChanged (source/DrippyFX/PluginProcessor.cpp:46). loadPreset itself
(source/DrippyFX/PluginProcessor.cpp:50-57) opens the named
beginNewTransaction("Load Preset") BEFORE any setValueNotifyingHost write,
so every preset stomp gets its own undo boundary.

Risk being pinned: a future caller (e.g. an editor click handler or a
 setCurrentProgram path change that calls loadPreset directly) would stomp
all 24 parameters without host-notification semantics / its own undo
story, shipping silently behind an otherwise-green gate — the undo
wiring checker pins transaction EXISTENCE only, not call-site topology,
and the combo-runtime checker pins table composition only.

Asserts (comment-stripped):
  (a) exactly ONE `loadPreset(` call site across PluginProcessor.cpp AND
      PluginEditor.cpp (the CorvusFXAudioProcessor::loadPreset definition,
      the header declaration, and comments are excluded from the count);
  (b) that sole call site lives inside the parameterChanged body and takes
      the idToPreset argument (preserving the guarded parameterChanged path);
  (c) the loadPreset definition body still opens with
      beginNewTransaction("Load Preset") (existence cross-check with
      check_undo_wiring.py, which is not duplicated here).

Self-probes (negative checks) run on mutated in-memory TEMP texts — the
real tree is never mutated. A no-op mutation guard skips probes whose
mutation didn't apply.

Exit 0 = ok, 1 = violation with line-cited diagnostics.
"""
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SRC = ROOT / "source" / "DrippyFX"

def fail(msg):
    print(f"PRESET-LOAD-SITES FAIL: {msg}")
    sys.exit(1)

def strip_comments(txt):
    """Remove // line comments and /* */ block comments."""
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

def call_sites(stripped_txt):
    """Generator of (index) of every `loadPreset(` occurrence that is a
    call site or definition — excludes the bare header declaration."""
    k = 0
    while True:
        k = stripped_txt.find("loadPreset(", k)
        if k == -1:
            return
        yield k
        k += 1

def load_sources():
    paths = [SRC / "PluginProcessor.cpp", SRC / "PluginEditor.cpp"]
    texts = []
    for p in paths:
        if not p.exists():
            fail(f"missing source file {p}")
        texts.append((p, strip_comments(p.read_text(encoding="utf-8"))))
    return texts

def sole_call_site(texts):
    """Return (file, index) of the single call site, or fail."""
    all_sites = []
    for p, s in texts:
        for i in call_sites(s):
            all_sites.append((p, s, i))
    # exclude the definition site: `... void CorvusFXAudioProcessor::loadPreset(
    # <args> )` — identify it by scanning for the definition marker ONCE.
    sites = []
    for p, s, i in all_sites:
        # definition site: the `loadPreset(int index)` definition signature —
        # a real call site would never pass `int index)` as its argument list
        if s.startswith("loadPreset(int index)", i):
            continue  # definition, not a call site
        sites.append((p, s, i))
    if len(sites) != 1:
        locs = ", ".join(str(p) for p, _, _ in sites) or "none"
        fail(f"expected exactly 1 loadPreset call site, found {len(sites)}: {locs}")
    return sites[0]

def extract_body(txt, fn_name):
    """Extract the brace-matched body of CorvusFXAudioProcessor::fn_name
    in txt (comment-stripped)."""
    marker = f"CorvusFXAudioProcessor::{fn_name}("
    k = txt.find(marker)
    if k == -1:
        fail(f"could not find {marker} definition")
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

def check(texts):
    """All parts against the list of (path, stripped_text). True = pass."""
    # (a)+(b) exactly one call site, inside parameterChanged
    p, s, i = sole_call_site(texts)
    y = p.with_suffix("").name
    if not y.endswith("PluginProcessor"):
        return False  # call site must live in the processor source
    # parameterChanged body extract
    k = s.find("CorvusFXAudioProcessor::parameterChanged(")
    if k == -1:
        return False
    o = s.find("{", k)
    depth, j = 0, o
    while j < len(s):
        if s[j] == "{": depth += 1
        elif s[j] == "}":
            depth -= 1
            if depth == 0: break
        j += 1
    body = s[o:j + 1]
    if i < o or i > j:
        return False  # sole call site not inside parameterChanged
    if "loadPreset(idToPreset[" not in body:
        return False
    # (c) loadPreset body opens with the named transaction
    lp = extract_body(s, "loadPreset")
    if 'beginNewTransaction("Load Preset")' not in lp:
        return False
    first_txn = lp.find('beginNewTransaction("Load Preset")')
    first_write = lp.find("setValueNotifyingHost")
    if first_write != -1 and first_write < first_txn:
        return False
    return True

texts = load_sources()
proc_c_path = texts[0][0]
proc_c_raw = proc_c_path.read_text(encoding="utf-8")
if not check(texts):
    fail("loadPreset call-site shape drifted: need exactly ONE call site, "
         "inside parameterChanged taking idToPreset[...], with the "
         'beginNewTransaction("Load Preset") before any setValueNotifyingHost '
         "in the loadPreset body (PluginProcessor.cpp)")
print("load-sites: sole loadPreset call site is the guarded parameterChanged "
      "path; 'Load Preset' transaction opens before any write — pinned")

# ---------------------------------------------------------------------------
# Self-probes on mutated in-memory texts (real tree never mutated)
# ---------------------------------------------------------------------------

def probe(description, mutator):
    mutated = mutator(texts)
    if all(s == os_ for (p, s), (op, os_) in zip(mutated, texts)):
        print(f"load-sites: no-op mutation guard -> skipping invalid probe "
              f"({description})")
        return
    try:
        ok = check(mutated)
    except SystemExit:
        ok = False  # checker failed with a diagnostic = rejection fired
    if ok:
        print(f"load-sites: SELF-PROBE FAIL (checker should reject): "
              f"{description}")
        sys.exit(1)
    print(f"load-sites: self-probe fired: {description} -> rejected")

def mutate(texts, idx, old, new):
    p, s = texts[idx]
    if old not in s:
        return list(texts)  # no-op; caller guards
    m = [(pp, (ss.replace(old, new, 1) if pp == p else ss))
         for pp, ss in texts]
    return m

# 1. a bare loadPreset( call added in the editor (e.g. a future click handler)
def add_editor_call(ts):
    p, s = ts[1]
    anchor = "void CorvusFXAudioProcessorEditor::timerCallback()"
    if anchor not in s:
        return list(ts)
    k = s.find(anchor)
    o = s.find("{", k)
    if o == -1:
        return list(ts)
    ins = o + 1
    m = list(ts)
    m[1] = (p, s[:ins] + " loadPreset(0);" + s[ins:])
    return m
probe("bare loadPreset call added in the editor", add_editor_call)

# 2. a second call site added in PluginProcessor.cpp (duplicate load path)
def add_processor_call(ts):
    p, s = ts[0]
    k = s.find("void CorvusFXAudioProcessor::randomizePreset()")
    if k == -1:
        return list(ts)
    o = s.find("{", k)
    if o == -1:
        return list(ts)
    m = list(ts)
    m[0] = (p, s[:o + 1] + " loadPreset(0);" + s[o + 1:])
    return m
probe("second loadPreset call site added in the processor", add_processor_call)

# 3. 'Load Preset' transaction stripped from the loadPreset body
probe("'Load Preset' transaction stripped",
      lambda ts: mutate(ts, 0,
                        'undoManager.beginNewTransaction("Load Preset");',
                        ";"))

# 4. no-op: a benign comment edit inside parameterChanged must stay accepted
def benign_edit(ts):
    p, _ = ts[0]
    txt = p.read_text(encoding="utf-8")
    anchor = None
    for l in txt.splitlines():
        if "ComboBoxAttachment maps the parameter" in l:
            anchor = l
            break
    if anchor is None:
        return list(ts)
    new_txt = txt.replace(anchor, "// benign probe edit\n" + anchor, 1)
    m = list(ts)
    m[0] = (p, strip_comments(new_txt))
    return m
probe_noop = benign_edit(texts)
if all(s == os_ for (p, s), (op, os_) in zip(probe_noop, texts)):
    print("load-sites: no-op probe skipped (comment stripped equally)")
elif not check(probe_noop):
    fail("no-op guard: benign comment edit in parameterChanged was wrongly rejected")
else:
    print("load-sites: no-op guard passed (benign comment edit accepted)")

print("PRESET-LOAD-SITES OK")
