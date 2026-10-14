#!/usr/bin/env python3
"""Headless checker: abSlots restore-slot if-init guards (setStateInformation).

The abSlots restore block consumes BOTH per-slot child lookups as if-init
conditions, nested inside the abSlots getChildByName guard:

    if (auto* abXml = xml->getChildByName("abSlots"))
    {
        ...
        if (auto* aXml = abXml->getChildByName("snapshotA"))
            ... aMB.loadFromBase64(aXml->getAllSubText());
        ...
        if (auto* bXml = abXml->getChildByName("snapshotB"))
            ... bMB.loadFromBase64(bXml->getAllSubText());

grep over all scripts/check_*.py: check_ab_snapshot_persistence.py pins the
"abSlots" tag presence/order only (and its negatives mutate tag strings) —
NOTHING pins the per-slot if-init consumption form. Rewriting the snapshotA
lookup into a bare assignment followed directly by
`aMB.loadFromBase64(aXml->getAllSubText());` null-derefs aXml inside a host
state-load when a state carries the abSlots child but a missing snapshotA
row (partial/older save); compiles clean today because the row is currently
always present.

Asserts on the real tree (comment-stripped):
  (a) inside the setStateInformation body, the abSlots lookup is consumed
      ONLY as an if-init condition (`if (auto* ... = xml->getChildByName
      ("abSlots"))`), never as a bare assignment;
  (b) nested INSIDE that guard block, both snapshotA and snapshotB
      lookups are consumed ONLY as if-init conditions with getAllSubText()
      deref inside the guarded body;
  (c) NO stray `aXml->` / `bXml->` / `abXml->` dereference outside a
      guarded body (roster lock).
Negatives self-probe mutated in-memory texts (real tree never mutated;
no-op mutation aborts as a stale alarm): aXml rewritten to bare
assignment → rejected; snapshotA row dropped entirely → rejected;
beneficial no-op accepted (probe specificity).

Exit 0 = ok, 1 = violation with a cited diagnostic.
"""
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
CPP = ROOT / "source" / "DrippyFX" / "PluginProcessor.cpp"


def fail(msg):
    print(f"AB-RESTORE-GUARDS FAIL: {msg}")
    sys.exit(1)


def strip_comments(src):
    src = re.sub(r"/\*.*?\*/", "", src, flags=re.S)
    src = re.sub(r"//[^\n]*", "", src)
    return src


def brace_span(code, open_idx):
    """Return (open, close) indices of the brace block starting at open_idx."""
    depth = 0
    j = open_idx
    while j < len(code):
        if code[j] == "{":
            depth += 1
        elif code[j] == "}":
            depth -= 1
            if depth == 0:
                return j
        j += 1
    return -1


def _verify(cpp_text):
    code = strip_comments(cpp_text)

    m = re.search(
        r"void\s+CorvusFXAudioProcessor::setStateInformation\s*\(", code)
    if not m:
        return "setStateInformation definition missing"
    sig_close = code.find(")", m.start())
    i = code.find("{", sig_close)
    if i == -1:
        return "setStateInformation body not found"
    close = brace_span(code, i)
    if close == -1:
        return "setStateInformation body not brace-matched"
    body = code[i:close + 1]

    # (a) abSlots lookup consumed ONLY as an if-init condition
    ab_open = re.search(
        r'if\s*\(\s*auto\s*\*\s*abXml\s*=\s*xml->getChildByName\s*\(\s*'
        r'"abSlots"\s*\)\s*\)', body)
    if not ab_open:
        return ('the abSlots child lookup must stay consumed as an if-init '
                'condition `if (auto* abXml = xml->getChildByName("abSlots"))`')
    ab_close = brace_span(body, ab_open.start())
    if ab_close == -1:
        return "abSlots guard block not brace-matched"
    guard = body[ab_open.end():ab_close]

    # (b) both per-slot lookups consumed ONLY as if-init conditions with
    #     the getAllSubText() deref inside their guarded bodies
    for slot, var, mb in (("snapshotA", "aXml", "aMB"), ("snapshotB", "bXml", "bMB")):
        sl_open = re.search(
            r'if\s*\(\s*auto\s*\*\s*' + var +
            r'\s*=\s*abXml->getChildByName\s*\(\s*"' + slot +
            r'"\s*\)\s*\)', guard)
        if not sl_open:
            return (f'the {slot} child lookup must stay consumed as an '
                    f'if-init condition `if (auto* {var} = '
                    f'abXml->getChildByName("{slot}"))` nested inside the '
                    'abSlots guard — a bare assignment null-derefs '
                    f'{var} on a partial/older save missing that row')
        sl_close = brace_span(guard, sl_open.start())
        if sl_close == -1:
            return f"{slot} guard block not brace-matched"
        sl_body = guard[sl_open.end():sl_close]
        if not re.search(
                var + r'->getAllSubText\s*\(\s*\)', sl_body):
            return (f"{var}->getAllSubText() deref missing from the {slot} "
                    "guarded body — the snapshot read never happens")
        if not re.search(
                r'juce::Base64::convertFromBase64\s*\(\s*' + mb + r'\s*,\s*' + var + r'->getAllSubText',
                sl_body):
            return (f'{mb}.loadFromBase64({var}->getAllSubText()) form missing '
                    f'in the {slot} guarded body')

    # (c) roster lock: no stray derefs of the three vars outside guarded bodies
    for var, n in (("abXml", 3), ("aXml", 1), ("bXml", 1)):
        count = len(re.findall(r"(?<![A-Za-z])" + var + r"->", guard))
        if count != n:
            return (f"expected exactly {n} {var}-> "

                    f"abSlots guard block, found {count} — stray "
                    "consumption outside a guarded body is not part of "
                    "the pinned shape")

    return None


NOOP_MUTATION = "/*ABREST-NOOP-STALENESS-PROBE*/"


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
    probe_accepts(cpp_text.replace("setStateInformation", "setStateInformation" + " " + NOOP_MUTATION, 1),
                  "benign no-op")

    # (1) snapshotA lookup rewritten to a bare assignment (null-deref class)
    probe_rejects(cpp_text.replace(
        'if (auto* aXml = abXml->getChildByName("snapshotA"))',
        'auto* aXml = abXml->getChildByName("snapshotA");'),
        "aXml rewritten to bare assignment")

    # (2) snapshotA row dropped entirely (partial/older save class)
    probe_rejects(cpp_text.replace(
        'if (auto* aXml = abXml->getChildByName("snapshotA"))', ""), "snapshotA row dropped")

    # (3) abSlots lookup harmonised into a bare assignment
    probe_rejects(cpp_text.replace(
        'if (auto* abXml = xml->getChildByName("abSlots"))',
        'auto* abXml = xml->getChildByName("abSlots");'),
        "abSlots bare assignment")

    # (4) snapshotB row dropped entirely
    probe_rejects(cpp_text.replace(
        'if (auto* bXml = abXml->getChildByName("snapshotB"))', ""),
        "snapshotB row dropped")

    # (5) slot tag drifted ("snapshotA" → "snapA")
    probe_rejects(cpp_text.replace(
        'abXml->getChildByName("snapshotA")', 'abXml->getChildByName("snapA")'),
        "snapshotA tag drifted")

    print("AB-RESTORE-GUARDS OK")
    return 0


if __name__ == "__main__":
    sys.exit(main())
