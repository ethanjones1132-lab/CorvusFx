#!/usr/bin/env python3
"""Headless checker: pin the loadPreset call-site roster + its undo transaction.

CV-066 leaves exactly THREE loadPreset call sites in the whole plugin source,
one per recall path, and each one has to stay where it belongs:

  1. CorvusFXAudioProcessor::parameterChanged  -> loadPreset(idToPreset[id]);
     the editor combo / listener path, still behind the "preset" id window and
     the restoringPresetState guard (check_cv023_preset_restore.py pins those);
  2. CorvusFXAudioProcessor::setCurrentProgram -> loadPreset(i);
     the direct host program-change reload (CV-066), followed by the
     presetToId[] parameter write that raises the echo loadPreset() skips;
  3. CorvusFXAudioProcessor::CorvusFXAudioProcessor -> loadPreset(0);
     the silent construction-time default load (CV-066), inside its
     SilentPresetLoad guard so it raises no transaction/gesture/notification.

loadPreset itself opens its named undo transaction (conditionally, so the
silent construction load skips it) BEFORE any setValueNotifyingHost write.

Risk being pinned: a future caller (an editor click handler, a processBlock
convenience call, or a second processor path) would stomp all 24 parameters
without host-notification semantics / its own undo story, shipping silently
behind an otherwise-green gate — the undo-wiring checker pins transaction
EXISTENCE only, not call-site topology, and the combo-runtime checker pins
table composition only.

Asserts (comment-stripped):
  (a) exactly THREE `loadPreset(` call sites across PluginProcessor.cpp AND
      PluginEditor.cpp (the CorvusFXAudioProcessor::loadPreset definition,
      the header declaration, and comments are excluded from the count);
  (b) each site lives in one of the three named processor functions and takes
      that function's pinned argument: `idToPreset[` (parameterChanged),
      `i` (setCurrentProgram), `0` (the constructor). No site may live in
      PluginEditor.cpp, setStateInformation, processBlock or randomizePreset.
  (c) the loadPreset definition body still opens with
      beginNewTransaction("Load Preset") before any setValueNotifyingHost
      (existence cross-check with check_undo_wiring.py, not duplicated here).

Self-probes (negative checks) run on mutated in-memory TEMP texts — the real
tree is never mutated. A no-op mutation guard skips probes whose mutation
didn't apply.

Exit 0 = ok, 1 = violation with line-cited diagnostics.
"""
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SRC = ROOT / "source" / "DrippyFX"

# The CV-066 call-site roster: function -> the argument prefix that identifies
# the site as that function's own load.
ALLOWED = {
    "CorvusFXAudioProcessor": "loadPreset(0)",
    "parameterChanged": "loadPreset(idToPreset[",
    "setCurrentProgram": "loadPreset(i)",
}

PROCESSOR = "PluginProcessor.cpp"


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
    paths = [SRC / PROCESSOR, SRC / "PluginEditor.cpp"]
    texts = []
    for p in paths:
        if not p.exists():
            fail(f"missing source file {p}")
        texts.append((p, strip_comments(p.read_text(encoding="utf-8"))))
    return texts


def brace_span(txt, open_index):
    """(open, end, text) of the brace-matched block starting at open_index."""
    depth = 0
    for j in range(open_index, len(txt)):
        if txt[j] == "{":
            depth += 1
        elif txt[j] == "}":
            depth -= 1
            if depth == 0:
                return open_index, j + 1, txt[open_index:j + 1]
    return None


def function_span(txt, marker):
    """Brace-matched span of the function whose signature starts with marker."""
    k = txt.find(marker)
    if k == -1:
        return None
    o = txt.find("{", k)
    if o == -1:
        return None
    return brace_span(txt, o)


def extract_body(txt, fn_name):
    """Extract the brace-matched body of CorvusFXAudioProcessor::fn_name
    in txt (comment-stripped)."""
    span = function_span(txt, f"CorvusFXAudioProcessor::{fn_name}(")
    if span is None:
        fail(f"could not find CorvusFXAudioProcessor::{fn_name}( definition")
    return span[2]


def call_site_roster(texts):
    """All `loadPreset(` occurrences except the definition."""
    sites = []
    for p, s in texts:
        for i in call_sites(s):
            # definition site: the `loadPreset(int index)` definition signature —
            # a real call site would never pass `int index)` as its argument list
            if s.startswith("loadPreset(int index)", i):
                continue
            sites.append((p, s, i))
    return sites


def check(texts):
    """All parts against the list of (path, stripped_text). True = pass."""
    # (a) exactly THREE call sites, none of them in the editor
    sites = call_site_roster(texts)
    if len(sites) != 3:
        return False
    proc_path = None
    proc = None
    for p, s in texts:
        if p.name == PROCESSOR:
            proc = s
    if proc is None:
        return False

    spans = {}
    for signature in ALLOWED:
        span = function_span(proc, f"CorvusFXAudioProcessor::{signature}(")
        if span is None:
            return False
        spans[signature] = span

    seen = set()
    for p, s, i in sites:
        if p.name != PROCESSOR:
            return False  # no call site may live in the editor
        owner = None
        for signature, (o, end, _body) in spans.items():
            if o < i < end:
                owner = signature
                break
        if owner is None or owner in seen:
            return False  # outside the three named paths, or a duplicate
        seen.add(owner)
        if not s[i:].startswith(ALLOWED[owner]):
            return False  # wrong argument for that path
    if seen != set(ALLOWED):
        return False

    # (b) the parameterChanged site stays the guarded idToPreset[] hop
    changed = extract_body(proc, "parameterChanged")
    if "loadPreset(idToPreset[" not in changed:
        return False

    # (c) loadPreset body still opens the named transaction before any write
    lp = extract_body(proc, "loadPreset")
    first_txn = lp.find('beginNewTransaction("Load Preset")')
    if first_txn == -1:
        return False
    first_write = lp.find("setValueNotifyingHost")
    if first_write != -1 and first_write < first_txn:
        return False
    return True


texts = load_sources()
proc_c_path = texts[0][0]
if not check(texts):
    fail("loadPreset call-site roster drifted: need exactly THREE call sites, "
         "each inside its own processor path — loadPreset(idToPreset[id]) in "
         "parameterChanged, loadPreset(i) in setCurrentProgram, loadPreset(0) "
         "in the constructor — and none in PluginEditor.cpp, "
         "setStateInformation, processBlock or randomizePreset; the "
         '<beginNewTransaction("Load Preset") must stay before any '
         "setValueNotifyingHost in the loadPreset body (PluginProcessor.cpp)")
print("load-sites: exactly three loadPreset call sites — parameterChanged's "
      "guarded idToPreset[id], setCurrentProgram's direct i and the "
      "constructor's silent 0; 'Load Preset' transaction pinned")

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


def insert_in_function(texts, idx, marker, statement):
    p, s = texts[idx]
    span = function_span(s, marker)
    if span is None:
        return list(texts)
    ins = span[0] + 1
    m = list(texts)
    m[idx] = (p, s[:ins] + " " + statement + s[ins:])
    return m


# 1. a bare loadPreset( call added in the editor (e.g. a future click handler)
probe("bare loadPreset call added in the editor",
      lambda ts: insert_in_function(
          ts, 1, "CorvusFXAudioProcessorEditor::timerCallback()",
          "loadPreset(0);"))

# 2. a second call site added in PluginProcessor.cpp (duplicate load path)
probe("second loadPreset call site added in the processor",
      lambda ts: insert_in_function(
          ts, 0, "CorvusFXAudioProcessor::randomizePreset(", "loadPreset(0);"))

# 3. a render-callback call site (audio thread)
probe("loadPreset call added in processBlock",
      lambda ts: insert_in_function(
          ts, 0, "CorvusFXAudioProcessor::processBlock(", "loadPreset(0);"))

# 4. a state-restore call site (would stomp the restored tree)
probe("loadPreset call added in setStateInformation",
      lambda ts: insert_in_function(
          ts, 0, "CorvusFXAudioProcessor::setStateInformation(",
          "loadPreset(0);"))

# 5. the constructor's silent default load dropped (a fresh insert would no
#    longer play preset 0)
probe("constructor default loadPreset(0) removed",
      lambda ts: mutate(ts, 0, "        loadPreset(0);\n", ""))

# 6. 'Load Preset' transaction stripped from the loadPreset body
probe("'Load Preset' transaction stripped",
      lambda ts: mutate(ts, 0,
                        'undoManager.beginNewTransaction("Load Preset");',
                        ";"))

# 7. no-op: a benign comment edit inside parameterChanged must stay accepted
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
