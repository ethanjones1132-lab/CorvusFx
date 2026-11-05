#!/usr/bin/env python3
"""Check block-cache-only FX smoothers advance once per rendered block.

The five snapshots must remain non-consuming getCurrentValue() reads, then
their ramps advance with skip(numSamples) after the block caches use them and
before per-sample processing. In-memory probes guard each invariant without
modifying source files.
"""
import re
import sys
from pathlib import Path

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

ROOT = Path(__file__).resolve().parent.parent
SOURCE = ROOT / "source" / "DrippyFX" / "PluginProcessor.cpp"
PROCESSOR = "CorvusFXAudioProcessor"

SMOOTHERS = {
    "smoothChorusMix": "chorusMix",
    "smoothDelayDamping": "delayDamping",
    "smoothReverbSize": "reverbSize",
    "smoothReverbDamping": "reverbDamping",
    "smoothReverbMod": "sReverbMod",
}


def strip_comments(text):
    text = re.sub(r"/\*.*?\*/", lambda m: "\n" * m.group(0).count("\n"),
                  text, flags=re.S)
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


def process_body(code):
    match = re.search(
        rf'\bvoid\s+{PROCESSOR}::processBlock\s*\([^)]*\)\s*\{{',
        code, flags=re.S)
    return braced_span(code, match.end() - 1) if match else None


def verify(source_text=None):
    if source_text is None:
        source_text = SOURCE.read_text(encoding="utf-8", errors="replace")
    span = process_body(strip_comments(source_text))
    if span is None:
        return ["could not find CorvusFXAudioProcessor::processBlock body"]
    body = span[2]
    errors = []

    loop = re.search(r"\bfor\s*\(\s*int\s+s\s*=\s*0\s*;", body)
    if not loop:
        return ["could not find the per-sample processing loop"]

    snapshot_positions = {}
    for smoother, local in SMOOTHERS.items():
        snapshot = re.compile(
            rf'\bconst\s+float\s+{local}\s*=\s*{smoother}\s*\.\s*'
            r'getCurrentValue\s*\(\s*\)\s*;')
        snapshots = list(snapshot.finditer(body))
        if len(snapshots) != 1:
            errors.append(f"{smoother} must have exactly one {local} "
                          "getCurrentValue() block snapshot")
        else:
            snapshot_positions[smoother] = snapshots[0].start()

        skip = re.compile(rf'\b{smoother}\s*\.\s*skip\s*'
                          r'\(\s*numSamples\s*\)\s*;')
        skips = list(skip.finditer(body))
        if len(skips) != 1:
            errors.append(f"{smoother} must call skip(numSamples) exactly once")
        elif skips[0].start() >= loop.start():
            errors.append(f"{smoother}.skip(numSamples) must be before the "
                          "per-sample loop")

    if len(snapshot_positions) == len(SMOOTHERS) and max(snapshot_positions.values()) >= loop.start():
        errors.append("all five block snapshots must precede the per-sample loop")

    cache_uses = (
        (r'\bchorus\s*\.\s*beginBlock\s*'
         r'\([^;]*\bchorusMix\b[^;]*\)\s*;',
         ("smoothChorusMix",)),
        (r'\bdelay\s*\.\s*beginBlock\s*'
         r'\([^;]*\bdelayDamping\b[^;]*\)\s*;',
         ("smoothDelayDamping",)),
        (r'\bupgradedReverb\s*\.\s*beginBlock\s*'
        r'\([^;]*\breverbSize\b[^;]*\breverbDamping\b[^;]*'
         r'\bsReverbMod\b[^;]*\)\s*;',
         ("smoothReverbSize", "smoothReverbDamping", "smoothReverbMod")),
    )
    use_positions = []
    for pattern, consumed_smoothers in cache_uses:
        match = re.search(pattern, body, flags=re.S)
        if not match:
            errors.append("a block beginBlock() call no longer consumes its "
                          "smoothed snapshot")
        else:
            use_positions.append(match.start())
            for smoother in consumed_smoothers:
                if (smoother in snapshot_positions
                        and snapshot_positions[smoother] >= match.start()):
                    errors.append(f"{smoother} snapshot must precede its "
                                  "block beginBlock() cache use")

    if len(use_positions) == len(cache_uses):
        last_cache_use = max(use_positions)
        for smoother in SMOOTHERS:
            match = re.search(rf'\b{smoother}\s*\.\s*skip\s*'
                              r'\(\s*numSamples\s*\)\s*;', body)
            if match and match.start() <= last_cache_use:
                errors.append(f"{smoother}.skip(numSamples) must follow the "
                              "block beginBlock() cache uses")
    return errors


def fail_probe(label, detail):
    print(f"FAIL: probe '{label}' was not rejected — {detail}")
    sys.exit(1)


if not SOURCE.exists():
    print(f"FAIL: missing source file {SOURCE}")
    sys.exit(1)
source_text = SOURCE.read_text(encoding="utf-8", errors="replace")
errors = verify(source_text)
if errors:
    print("FAIL: CV-046 block smoother invariants violated:")
    for error in errors:
        print(f"  - {error}")
    sys.exit(1)
print("OK: five block-cache-only smoothers retain getCurrentValue snapshots")
print("OK: each smoother advances once after cache setup and before sample processing")

# A comment-only change must not affect the source invariants.
if verify(source_text + "\n// benign CV-046 checker probe\n"):
    fail_probe("comment-only edit", "comment-stripped source did not pass")
print("probe ok: comment-only edit -> accepted")

code = strip_comments(source_text)
for smoother in SMOOTHERS:
    skip = re.compile(rf'\b{smoother}\s*\.\s*skip\s*'
                      r'\(\s*numSamples\s*\)\s*;')
    without_skip, count = skip.subn("", code, count=1)
    if count != 1:
        print(f"FAIL: stale self-probe: {smoother} skip removal matched {count} times")
        sys.exit(1)
    if not verify(without_skip):
        fail_probe(f"{smoother} skip removed", "source without the advance passed")
    print(f"probe ok: {smoother} skip removed -> rejected")

for smoother, local in SMOOTHERS.items():
    snapshot = re.compile(
        rf'({smoother}\s*\.\s*)getCurrentValue(\s*\(\s*\))')
    changed, count = snapshot.subn(r'\1getNextValue\2', code, count=1)
    if count != 1:
        print(f"FAIL: stale self-probe: {smoother} snapshot mutation "
              f"matched {count} times")
        sys.exit(1)
    if not verify(changed):
        fail_probe(f"{smoother} snapshot changed to getNextValue()",
                   "consuming snapshot read passed")
    print(f"probe ok: {smoother} getNextValue snapshot -> rejected")
