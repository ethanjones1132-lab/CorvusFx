#!/usr/bin/env python3
"""Headless checker: getStateInformation per-row mapXml save-loop shape.

The midiMaps save loop (inside `if (mapsXml)`) creates one `map` child per
midi-learn entry and writes BOTH attributes via setSelected derefs:

    auto* mapXml = mapsXml->createNewChildElement("map");
    mapXml->setAttribute("cc", cc);
    mapXml->setAttribute("param", paramID);

grep over all scripts/check_*.py: check_midi_state_restore.py pins the
child creation + ScopedLock order + loop header only; check_getstate_null_
guard.py pins the root-xml guard; check_ab_snapshot_persistence.py pins
tag presence only — NOTHING pins the per-row shape. A silent drift in
either setAttribute call (e.g. "cc" renamed, or the "param" line dropped)
produces a midi-learn mapping that silently fails to restore on a reload
(the setStateInformation map reader keys on cc/param); compiles clean
behind an otherwise-green gate.

Asserts on the real tree (comment-stripped):
  (a) inside the getStateInformation body, the
      `mapsXml->createNewChildElement("map")` site (bare, deliberately-
      consumed-as-is outside any if-init) is followed by BOTH
      `mapXml->setAttribute("cc", cc)` AND
      `mapXml->setAttribute("param", paramID)`;
  (b) NO stray `mapXml->` dereference other than the two pinned
      setAttribute calls (roster lock).
Negatives self-probe mutated in-memory texts (real tree never mutated;
no-op mutation aborts as a stale alarm): one setAttribute deleted →
rejected; "param" attribute renamed → rejected; setAttribute operands
swapped in id → rejected; benign no-op accepted (probe specificity).

Exit 0 = ok, 1 = violation with a cited diagnostic.
"""
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
CPP = ROOT / "source" / "DrippyFX" / "PluginProcessor.cpp"


def fail(msg):
    print(f"MAP-ROW-GUARD FAIL: {msg}")
    sys.exit(1)


def strip_comments(src):
    src = re.sub(r"/\*.*?\*/", "", src, flags=re.S)
    src = re.sub(r"//[^\n]*", "", src)
    return src


def _verify(cpp_text):
    code = strip_comments(cpp_text)

    m = re.search(
        r"void\s+CorvusFXAudioProcessor::getStateInformation\s*\(", code)
    if not m:
        return "getStateInformation definition missing"
    sig_close = code.find(")", m.start())
    i = code.find("{", sig_close)
    if i == -1:
        return "getStateInformation body not found"
    depth = 0
    j = i
    while j < len(code):
        if code[j] == "{":
            depth += 1
        elif code[j] == "}":
            depth -= 1
            if depth == 0:
                break
        j += 1
    else:
        return "getStateInformation body not brace-matched"
    body = code[i:j + 1]

    # (a) the per-row creation + both attribute writes, exact shape
    create = re.search(
        r'auto\s*\*\s*mapXml\s*=\s*mapsXml->createNewChildElement\s*\(\s*"map"\s*\)', body)
    if not create:
        return ('per-row `auto* mapXml = mapsXml->createNewChildElement("map")`'
                " save-loop line missing or drifted")
    tail = body[create.end():]
    cc = re.search(
        r'mapXml->setAttribute\s*\(\s*"cc"\s*,\s*cc\s*\)\s*;', tail)
    if not cc:
        return 'mapXml->setAttribute("cc", cc); missing or drifted — a map row would silently fail to restore its cc channel'
    param = re.search(
        r'mapXml->setAttribute\s*\(\s*"param"\s*,\s*paramID\s*\)\s*;',
        tail[cc.end():cc.end() + 200])
    if not param or param.start() > cc.end() + 200:
        return ('mapXml->setAttribute("param", paramID); must follow the cc '
                'write in the same loop body — a map row missing its param '
                'attribute silently fails to restore on reload')

    # (b) roster lock: only the two pinned mapXml derefs
    derefs = re.findall(r"mapXml->", tail)
    if len(derefs) != 2:
        return (f"expected exactly 2 mapXml-> dereferences in the save loop, "
                f"found {len(derefs)} — stray/extra mapXml consumption is "
                "not part of the pinned shape")

    return None


NOOP_MUTATION = "/*MAPROW-NOOP-STALENESS-PROBE*/"


def probe_rejects(text, name):
    err = _verify(text)
    if err is None:
        fail(f"negative probe '{name}' did NOT reject the mutated shape")


def probe_accepts(text, name):
    err = _verify(text)
    if err is not None:
        fail(f"specificity probe '{name}' unexpectedly REJECTED the real shape: {err}")


def main():
    cpp_text = CPP.read_text(encoding="utf-8")
    if NOOP_MUTATION in cpp_text:
        fail("stale no-op probe marker found in the real tree")

    err = _verify(cpp_text)
    if err:
        fail(err)

    # Negative probes on mutated in-memory texts (real tree never mutated).
    # (0) specificity: a benign no-op comment must not perturb the shape.
    probe_accepts(cpp_text.replace("getStateInformation", "getStateInformation" + " " + NOOP_MUTATION, 1),
                  "benign no-op")

    # (1) one setAttribute deleted (param row dropped) → must be rejected
    probe_rejects(cpp_text.replace('mapXml->setAttribute("param", paramID);', ""),
          "param setAttribute deleted")

    # (2) attributeName "cc" renamed → must be rejected
    probe_rejects(cpp_text.replace('mapXml->setAttribute("cc", cc);',
                           'mapXml->setAttribute("channel", cc);'),
          "cc attribute renamed")
    # (3) setAttribute call deleted (cc row dropped) → must be rejected
    probe_rejects(cpp_text.replace('mapXml->setAttribute("cc", cc);', ""),
          "cc setAttribute deleted")

    # (4) setAttribute operands swapped in id ("cc" ← paramID, "param" ← cc)
    probe_rejects(cpp_text.replace('mapXml->setAttribute("cc", cc);\n            mapXml->setAttribute("param", paramID);',
                           'mapXml->setAttribute("cc", paramID);\n            mapXml->setAttribute("param", cc);'),
          "operands swapped in id")

    # (5) mapXml child tag drifted ("map" → "entry") → must be rejected
    probe_rejects(cpp_text.replace('mapsXml->createNewChildElement("map")',
                           'mapsXml->createNewChildElement("entry")'),
          "per-row tag drifted")

    print("MAP-ROW-GUARD OK")
    return 0


if __name__ == "__main__":
    sys.exit(main())
