#!/usr/bin/env python3
"""Headless checker: Oversampling2x up/down FIR state split.

Asserts (Phase-1 backlog item, jev-refill grade iter-026 substance 0.77):
  (a) Oversampling2x declares SEPARATE up-conversion and down-conversion
      state buffers (upState*/downState*) — no shared `stateL`/`stateR`
      circular buffer serving both conversions.
  (b) processSampleMono's upsampler reads the up-conversion state only.
  (c) The mono path's final state write before `idx++` targets a
      down-conversion state buffer — the parked odd-phase DSP output
      (dsp2) must never land in a buffer the next call's upsampler reads
      as base-rate filter history.
  (d) SSE staging (initSSE) and the half-band even-tap path are intact.
Exit 0 = ok, 1 = violation with line-cited diagnostics.

Negative self-probes (sibling style of check_baseline_fixture_test.py):
temp-mutate copies of the header, require the checker to reject each, and
guard against no-op mutations — so a regression in the checker ITSELF
(e.g. the body_of extraction greying out) fails loudly instead of
silently passing while asserting nothing.
"""
import re
import shutil
import sys
import tempfile
from pathlib import Path
from typing import NoReturn

ROOT = Path(__file__).resolve().parent.parent
SRC = ROOT / "source" / "DrippyFX"
HEADER = SRC / "dsp" / "CorvusEffects.h"


class Fail(Exception):
    pass


def fail(msg):
    raise Fail(msg)


def body_of(src, start_pat):
    mm = re.search(start_pat, src)
    if not mm:
        return None
    b = src.find("{", mm.start())
    if b == -1:
        return None
    d = 0; k = b
    while k < len(src):
        if src[k] == "{": d += 1
        elif src[k] == "}":
            d -= 1
            if d == 0: break
        k += 1
    return src[b:k + 1]


def check(text):
    """Run every assertion against `text`. Raises Fail on first violation."""
    # Isolate the Oversampling2x struct block.
    m = re.search(r"struct\s+Oversampling2x\b", text)
    if not m:
        fail("Oversampling2x struct missing from PluginProcessor.h")
    brace = text.find("{", m.start())
    depth = 0; i = brace; j = brace
    while j < len(text):
        if text[j] == "{": depth += 1
        elif text[j] == "}":
            depth -= 1
            if depth == 0: break
        j += 1
    block = text[brace:j + 1]

    # (a) separate state buffers declared
    if not re.search(r"float\s+upStateL\s*\[FILTER_TAPS\]", block) or \
       not re.search(r"float\s+upStateR", block):
        fail("Oversampling2x no longer declares upStateL/upStateR buffers")
    if not re.search(r"float\s+downStateL\s*\[FILTER_TAPS\]", block) or \
       not re.search(r"float\s+downStateR", block):
        fail("Oversampling2x no longer declares downStateL/downStateR buffers")
    if re.search(r"\bfloat\s+stateL\b", block) or re.search(r"\bfloat\s+stateR\b", block):
        fail("shared stateL/stateR buffer still declared — up/down conversions are no longer split")

    # (b) mono + stereo upsamplers read up-conversion state only
    mono = body_of(block, r"processSampleMono\s*\(")
    stereo = body_of(block, r"processSample\s*\(")
    if mono is None or stereo is None:
        fail("processSample/processSampleMono bodies not found")
    assert mono is not None and stereo is not None  # for the type checker
    for name, b in (("processSampleMono", mono), ("processSample", stereo)):
        up_sec = b.split("DSP at 2x rate")[0]
        down_sec = b.split("DSP at 2x rate")[-1]
        if "firSSE(downState" in up_sec or "firHalfBandSSE(downState" in up_sec:
            fail(f"{name}: upsampler reads the down-conversion state buffer")
        if "firSSE(upState" not in up_sec or "firHalfBandSSE(upState" not in up_sec:
            fail(f"{name}: upsampler does not read the upState buffer")
        if "firSSE(upState" in down_sec:
            fail(f"{name}: downsampler reads the up-conversion state buffer")

    # (c) mono path: tail write before idx++ must target the down-conversion state,
    #     and the value written is the dsp2 that downsampling parked there.
    mono_tail = mono[mono.index("DOWN SAMPLE"):]
    idx_rest = mono_tail
    final = re.search(r"(downStateL\[idx\]\s*=\s*dsp2;)\s*out\s*=\s*firSSE\(downStateL, idx\);\s*idx\s*=", idx_rest)
    if not final:
        fail("processSampleMono: final pre-idx++ state write no longer targets downStateL — the dsp2 tail may be parked into a buffer the next upsample reads")
    tail_val = final.group(1)
    if "dsp2" not in tail_val:
        fail(f"processSampleMono: final tail write '{tail_val.strip()}' is not the odd-phase dsp2 output")

    # (d) SSE staging + half-band even-tap path still intact
    if "initSSE" not in block or "coeffVecEven" not in block or "firHalfBandSSE" not in block:
        fail("SSE staging (initSSE/coeffVecEven) or half-band even-tap path removed")

    # (e) call sites compile-unchanged: processSampleMono callers intact
    if len(re.findall(r"processSampleMono\s*\(", text)) < 5:
        fail("unexpected loss of processSampleMono call sites in PluginProcessor.h")


def run_text(text):
    """Return (ok: bool, diagnostic: str) for an arbitrary header text."""
    try:
        check(text)
        return True, ""
    except Fail as e:
        return False, str(e)


def main():
    if not HEADER.exists():
        print(f"OVERSAMPLER-STATE-SPLIT FAIL: missing source file {HEADER}")
        return 1
    text = HEADER.read_text(encoding="utf-8")
    ok, diag = run_text(text)
    if not ok:
        print(f"OVERSAMPLER-STATE-SPLIT FAIL: {diag}")
        return 1
    print("oversampler: up/down state buffers are declared separately")
    print("oversampler: upsamplers read only upState; downsamplers read only downState")

    m = re.search(r"downStateL\[idx\]\s*=\s*\w+;", text)
    if not m:
        print("OVERSAMPLER-STATE-SPLIT FAIL: probe base pattern (mono tail write) not found in real source — checkers stale vs source")
        return 1

    # Negative self-probes on temp copies (real tree untouched).
    src = text
    negs = [
        ("re-park the dsp2 tail into upStateL",
         lambda s: s.replace("downStateL[idx] = dsp2;",
                             "upStateL[idx] = dsp2;")),
        ("drop the mono tail state write",
         lambda s: s.replace("downStateL[idx] = dsp2;",
                             "/* stripped */;")),
        ("collapse the up-side buffer into the down-side's (upsampler reads downStateL)",
         lambda s: s.replace("firSSE(upStateL, idx);",
                             "firSSE(downStateL, idx);", 1)),
        ("strip the SSE half-band staging trace",
         lambda s: re.sub(r"coeffVecEven", "coeffVecEvn", s, count=4)),
    ]
    tmpdir = tempfile.mkdtemp(prefix="check_oversampler_split_")
    try:
        for label, mutate in negs:
            mutated = mutate(src)
            if mutated == src:
                print(f"OVERSAMPLER-STATE-SPLIT FAIL: negative '{label}' mutation is a no-op — checker stale vs source")
                return 1
            p = Path(tmpdir) / "PluginProcessor.h"
            p.write_text(mutated, encoding="utf-8")
            ok2, diag2 = run_text(mutated)
            if ok2:
                print(f"OVERSAMPLER-STATE-SPLIT FAIL: negative check '{label}' did NOT fail — checker too weak")
                return 1
            print(f"oversampler: negative rejected -> {label}")
    finally:
        shutil.rmtree(tmpdir, ignore_errors=True)

    print("oversampler: all mono call sites present")
    print("OVERSAMPLER-STATE-SPLIT OK")
    return 0


if __name__ == "__main__":
    sys.exit(main())
