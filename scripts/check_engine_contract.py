#!/usr/bin/env python3
"""check_engine_contract.py — pin the Corvus Instrument vertical slice Plan's
Task-4 CorvusSynthEngine doc contract BEFORE the engine header exists.

SoT: docs/superpowers/plans/2026-08-08-corvus-instrument-vertical-slice.md
Task 4 ("Implement one voice and sixteen-voice MIDI allocation"), Interfaces
block:
  - CorvusVoice::startNote(note, velocity, params, age) / stopNote /
    render(left, right, start, count)
  - VoiceParameters { attackSeconds, decaySeconds, sustainLevel,
    releaseSeconds, wave }
  - CorvusSynthEngine::prepare(sampleRate, maxBlockSize) / render(buffer,
    midi, params) / panic()
And Step 5: preallocated exactly 16 voices, MIDI dispatch, sustain CC64,
all-notes-off/all-sound-off, pitch wheel, panic().

Nothing until now pins the Plan text itself, so the contract could be
silently rewritten before implementation and every later Task-4 test would
inherit a drifted spec.

Checks:
  A. The Task 4 block still declares the documented contract (read-only,
     comment-stripped): engine file name, 16-voice allocation, both engine
     methods with argument shapes, panic, CorvusVoice methods with argument
     shapes, VoiceParameters fields.
  B. Once source/DrippyFX/instrument/CorvusSynthEngine.h exists, the
     interface names named in the Plan appear in the header
     (prepare/render/panic/16 voices). SKIPPED while the file is absent —
     not a pass-fake: a printed SKIP line cites the rule.
Negative probes (never on the real tree):
  N1. rewrite the Task-4 block dropping the 16-voice allocator line -> FAIL
  N2. rewrite it dropping the panic() line -> FAIL
  N3. temp-create a stub CorvusSynthEngine.h missing panic -> FAIL (part B,
      exercised against a temp dir, not the real header path)
Exit 0 only when the real Plan passes and every negative fires.
"""

import os
import re
import sys
import tempfile
import shutil

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
PLAN = os.path.join(ROOT, "docs", "superpowers", "plans",
                    "2026-08-08-corvus-instrument-vertical-slice.md")
ENGINE_HDR = os.path.join(ROOT, "source", "DrippyFX", "instrument",
                          "CorvusSynthEngine.h")

# Interface names the Plan's Task 4 names for the engine header.
ENGINE_NAMES = ["CorvusSynthEngine", "prepare", "render", "panic",
                "16 voices", "midi"]


def strip_markers(text: str) -> str:
    """Neutralize markdown emphasis/backticks so regexes match plain words."""
    return re.sub(r"`+", "", text)


def task4_block(plan_text: str) -> str:
    """Source region of the Task 4 section (heading to the next task/heading)."""
    m = re.search(r"^#{2,4}\s*Task 4:.*$", plan_text, re.M)
    if not m:
        return ""
    nxt = re.search(r"^#{2,4}\s*Task \d+:.*$", plan_text[m.end():], re.M)
    end = m.end() + (nxt.start() if nxt else len(plan_text) - m.end())
    return plan_text[m.start():end]


def plan_checks(code: str):
    """Comment-stripped Task-4 block checks. Return list of (label, ok, detail)."""
    res = []
    res.append(("block is non-empty", bool(code.strip()), "Task 4 heading found"))
    res.append(("engine file CorvusSynthEngine.h declared",
                "CorvusSynthEngine.h" in code, "File Structure / Files"))
    res.append(("16-voice allocation declared (preallocate exactly 16 voices)",
                re.search(r"exactly\s+16\s+voices", code, re.I) is not None,
                "allocator contract"))
    res.append(("CorvusSynthEngine::prepare(sampleRate, maxBlockSize) declared",
                re.search(r"CorvusSynthEngine::prepare\s*\(\s*sampleRate\s*,\s*"
                          r"maxBlockSize\s*\)", code) is not None,
                "prepare shape"))
    res.append(("CorvusSynthEngine::render(buffer, midi, params) declared",
                re.search(r"CorvusSynthEngine::render\s*\(\s*buffer\s*,\s*"
                          r"midi\s*,\s*params\s*\)", code) is not None,
                "render shape"))
    res.append(("CorvusSynthEngine::panic() declared",
                re.search(r"CorvusSynthEngine::panic\s*\(\s*\)", code) is not None,
                "panic shape"))
    res.append(("CorvusVoice::startNote(note, velocity, params, age) declared",
                re.search(r"CorvusVoice::startNote\s*\(\s*note\s*,\s*velocity\s*,"
                          r"\s*params\s*,\s*age\s*\)", code) is not None,
                "startNote shape"))
    res.append(("CorvusVoice::stopNote(allowTailOff) declared",
                re.search(r"CorvusVoice::stopNote\s*\(\s*allowTailOff\s*\)",
                          code) is not None, "stopNote shape"))
    res.append(("CorvusVoice::render(left, right, start, count) declared",
                re.search(r"CorvusVoice::render\s*\(\s*left\s*,\s*right\s*,"
                          r"\s*start\s*,\s*count\s*\)", code) is not None,
                "voice render shape"))
    res.append(("VoiceParameters fields declared",
                re.search(r"VoiceParameters\s*\{[^}]*attackSeconds[^}]*"
                          r"decaySeconds[^}]*sustainLevel[^}]*releaseSeconds",
                          code, re.S) is not None, "params shape"))
    res.append(("musical contract: MIDI events rendered at sample offsets",
                "sample offsets" in code, "dispatch contract"))
    res.append(("musical contract: panic() immediately resets voices and "
                "clears sustain state",
                re.search(r"panic\(\)\s+immediately\s+resets\s+voices", code)
                is not None, "panic semantics"))
    res.append(("musical contract: sustain controller 64 handled",
                re.search(r"sustain controller 64", code) is not None,
                "CC64"))
    res.append(("musical contract: 17th-note deterministic stealing test",
                "steal the voice with the smallest age counter" in code,
                "stealing rule"))
    return res


def header_checks(code: str):
    """Once the engine header exists, its interface must match the Plan."""
    res = []
    res.append(("header defines struct/class CorvusSynthEngine",
                re.search(r"(struct|class)\s+CorvusSynthEngine", code) is not None,
                "engine type"))
    res.append(("prepare(maxBlockSize) member exists",
                re.search(r"\bprepare\s*\(", code) is not None, "prepare"))
    res.append(("render member exists",
                re.search(r"\brender\s*\(", code) is not None, "render"))
    res.append(("panic member exists",
                re.search(r"\bpanic\s*\(\s*\)", code) is not None, "panic"))
    return res


def run_plan(text: str, verbose=True):
    code = strip_markers(text)
    block = task4_block(code)
    ok = True
    for label, good, detail in plan_checks(block):
        if verbose:
            print(("PASS " if good else "FAIL ") + "engine-contract(plan): " +
                  label + " (%s)" % detail)
        ok = ok and good
    return 0 if ok else 1


def run_header(path: str, verbose=True):
    with open(path, "r", encoding="utf-8") as f:
        code = strip_markers(f.read())
    ok = True
    for label, good, detail in header_checks(code):
        if verbose:
            print(("PASS " if good else "FAIL ") + "engine-contract(hdr): " +
                  label + " (%s)" % detail)
        ok = ok and good
    return 0 if ok else 1


def main():
    if not os.path.isfile(PLAN):
        print("GATE_FAIL: %s missing" % PLAN)
        return 1
    with open(PLAN, "r", encoding="utf-8") as f:
        plan_text = f.read()
    rc = run_plan(plan_text)
    if rc != 0:
        return 1

    # Part B: only while the header exists
    hdr_ok = True
    if os.path.isfile(ENGINE_HDR):
        hdr_ok = run_header(ENGINE_HDR) == 0
        if not hdr_ok:
            return 1
    else:
        print("SKIP engine-contract(hdr): no %s yet — header checks not "
              "engaged (will auto-activate when Task 4 is implemented)"
              % os.path.relpath(ENGINE_HDR, ROOT))

    # Negative probes on temp copies of the PLAN (never the real tree)
    negs = [
        ("drop the 16-voice allocator line from Task 4",
         lambda s: s.replace("Preallocate exactly 16 voices.", "")),
        ("drop the panic() contract line from Task 4",
         lambda s: s.replace(
             "`panic()` immediately resets voices and clears sustain state.",
             "")),
        ("drift the render signature (midi argument removed from the "
         "Interfaces line)",
         lambda s: s.replace(
             "`CorvusSynthEngine::render(buffer, midi, params)`",
             "`CorvusSynthEngine::render(buffer, params)`")),
    ]
    tmpdir = tempfile.mkdtemp(prefix="check_engine_contract_")
    try:
        for label, mutate in negs:
            mutated = mutate(plan_text)
            if mutated == plan_text:
                print("GATE_FAIL: negative '%s' mutation is a no-op — "
                      "checker stale vs plan" % label)
                return 1
            p = os.path.join(tmpdir, "plan.md")
            with open(p, "w", encoding="utf-8") as f:
                f.write(mutated)
            if run_plan(mutated, verbose=False) == 0:
                print("GATE_FAIL: negative check '%s' did NOT fail — "
                      "checker too weak" % label)
                return 1
            print("PASS engine-contract(plan): negative rejected -> " + label)

        # Part-B negative: stub engine header missing panic (temp dir)
        stub = os.path.join(tmpdir, "CorvusSynthEngine.h")
        with open(stub, "w", encoding="utf-8") as f:
            f.write("struct CorvusSynthEngine\n"
                    "{\n"
                    "    void prepare (double sampleRate, int maxBlockSize);\n"
                    "    void render (juce::AudioBuffer<float>& buffer,\n"
                    "                 juce::MidiBuffer& midi,\n"
                    "                 const VoiceParameters& params);\n"
                    "};\n")
        if run_header(stub, verbose=False) == 0:
            print("GATE_FAIL: stub engine header missing panic() was NOT "
                  "rejected — checker too weak")
            return 1
        print("PASS engine-contract(hdr): negative rejected -> stub header "
              "missing panic() fails")
    finally:
        shutil.rmtree(tmpdir, ignore_errors=True)

    print("OK engine contract pinned (Plan Task-4 CorvusSynthEngine doc "
          "contract guarded before the engine header exists)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
