#!/usr/bin/env python3
"""Headless invariant check: Oversampling2x SSE coefficient staging + zero reset.

Pins two invariants of the 2x oversampler (source/DrippyFX/PluginProcessor.h):

  1. SSE staging — prepare() (or initSSE) must load coeffVec0, coeffVec1 AND
     coeffVecEven from the "coeffs" array and set sseInitialized = true.
     Without coeffVecEven the half-band even-tap odd phase would read an
     UNINITIALISED __m128 every call (undefined garbage through tealh output —
     the upStateL/upStateR/downStateL/downStateR fix keeps state correct, but the
     coefficient vector must be re-staged whenever the plugin re-prepares).

  2. Full reset — reset() must zero ALL FOUR FIR history buffers
     (upStateL/upStateR/downStateL/downStateR) before clearing idx, matching
     the split-buffer design (iter on state split): a reset that clears only
     upState* would leave stale downState tail as the first downsample input.

  3. reset() ORDER — the four memsets must precede the `idx = 0` store.

Negative self-probes (sibling style of check_baseline_fixture_test.py):
temp-mutate copies of the header, require the checker to reject each, and
guard against no-op mutations — so a regression in the checker ITSELF
(e.g. the reset-body extraction greying out) fails loudly instead of
silently passing while asserting nothing.

Exits 0 on green, 1 with diagnostics on any violation.
"""
import re
import shutil
import sys
import tempfile
from pathlib import Path

HEADER = Path(__file__).resolve().parent.parent / "source" / "DrippyFX" / "dsp" / "CorvusEffects.h"


def strip_comments(s):
    s = re.sub(r"/\*.*?\*/", "", s, flags=re.S)
    s = re.sub(r"//[^\n]*", "", s)
    return s


def run_text(text):
    """Return (ok: bool, errors: list[str]) for a comment-stripped header text."""
    code = strip_comments(text)
    errors = []

    # ── 1. SSE staging: all three coefficient vectors loaded from coeffs ──
    for coeff_name, tap_hint in [("coeffVec0", "coeffs[0..3]"),
                                 ("coeffVec1", "coeffs[4..7]"),
                                 ("coeffVecEven", "half-band even taps")]:
        pat = re.compile(re.escape(coeff_name) + r"\s*=\s*[^;]*_mm_load[^;]*;")
        matches = pat.findall(code)
        if not matches:
            errors.append(f"{coeff_name} is never loaded via _mm_load* — SSE staging for {tap_hint} "
                          "was lost; the half-band path would read uninitialised memory")
        elif len(matches) > 1:
            errors.append(f"{coeff_name} is loaded {len(matches)}× — duplicate staging, only ONE "
                          "assignment (in prepare/initSSE) is expected")

    # ...and the loads must reference the shared coeffs array (not some other array)
    m = re.search(r"struct\s+Oversampling2x\b.*", code, re.S)
    body_end = m.end() + 22000 if m else len(code)  # struct body is well under 22k chars of comments-stripped code
    body = code[m.start():m.end() + 22000] if m else code
    for name in ("coeffVec0", "coeffVec1", "coeffVecEven"):
        loads = re.findall(re.escape(name) + r"\s*=\s*([^;]+);", body)
        for load in loads:
            if "coeffs" not in load and "evenTaps" not in load:
                errors.append(f"{name} is assigned outside the shared `coeffs` array source: "
                              f"`{load.strip()[:80]}`")
    # ...and evenTaps (the even-tap lane staging array) must be initialised FROM coeffs
    if body.count("evenTaps[4]") != 1 or not re.search(r"evenTaps\[4\][^;]*=\s*\{[^}]*coeffs", body, re.S):
        errors.append("evenTaps staging array missing or not initialised from `coeffs` — the half-band "
                      "even lane would load unverified taps")

    # SSE initialised gate must be set once, truthfully
    if not re.search(r"sseInitialized\s*=\s*true\s*;", body):
        errors.append("sseInitialized is never set to true — prepare() must stage the SSE vectors")

    # ── 2. reset() zeroes every FIR history buffer ──
    rm = re.search(r"void\s+reset\s*\(\s*\)\s*\{", body)
    if not rm:
        errors.append("could not locate Oversampling2x::reset() — source shape changed, re-audit before trusting green")
    else:
        # reset body: from the brace to the matching close (no nested braces by design)
        rb = body[rm.end(): body.find("}", rm.end())]
        for buf in ("upStateL", "upStateR", "downStateL", "downStateR"):
            if not re.search(r"\b" + buf + r"\b", rb):
                errors.append(f"reset() does not clear FIR history buffer `{buf}` — stale tail would feed the "
                              "first downsample after reset")
        if not re.search(r"\bidx\s*=\s*0\s*;", rb):
            errors.append("reset() no longer clears `idx` — the circular FIR index must restart at 0")

        # ── 3. reset() ORDER: the four memsets must precede the `idx = 0` store ──
        # A reorder that stores idx=0 before clearing the buffers leaves one filter
        # pass consuming a stale tail through a wrapped index (click after
        # re-prepare). Assert memset ordering by byte offset inside the reset body.
        first_memset = rb.find("std::memset(")
        if first_memset == -1:
            errors.append("reset() contains no std::memset call sites at all — FIR history must be zeroed via memset before idx is cleared")
        else:
            memset_calls = [mm.start() for mm in re.finditer(r"std::memset\s*\(", rb)]
            idx_store = re.search(r"\bidx\s*=\s*0\s*;", rb)
            if idx_store is None:
                errors.append("could not locate the `idx = 0` store in reset() for the ordering assertion")
            else:
                idx_off = idx_store.start()
                if len(memset_calls) < 4:
                    errors.append(f"reset() contains only {len(memset_calls)} std::memset call(s); expected 4 (all FIR history buffers) before `idx = 0`")
                for n, off in enumerate(memset_calls[:4]):
                    if off > idx_off:
                        errors.append(f"reset() ordering violated: memset #{n + 1} occurs AFTER the `idx = 0` store — clearing idx before zeroing "
                                      "the FIR history leaves one filter pass reading a stale tail through a wrapped index")
                        break
        # the memsets must be contiguous (each covers a distinct known buffer, in the
        # canonical up-L, up-R, down-L, down-R order or at least covering each exactly once)
        if first_memset != -1:
            memset_region = rb[: len(rb)]
            for buf in ("upStateL", "upStateR", "downStateL", "downStateR"):
                cnt = len(re.findall(r"std::memset\s*\(\s*" + buf + r"\b", memset_region))
                if cnt != 1:
                    errors.append(f"reset() targets buffer `{buf}` with {cnt} std::memset calls; expected exactly 1")

    return not errors, errors


def check(text):
    ok, errors = run_text(text)
    if not ok:
        print("FAIL: Oversampling2x SSE staging / reset invariants violated:")
        for e in errors:
            print(f"  - {e}")
    return ok, errors


def main():
    if not HEADER.exists():
        print(f"FAIL: missing source file {HEADER}")
        return 1
    src = HEADER.read_text(encoding="utf-8", errors="replace")
    ok, errors = check(src)
    if not ok:
        sys.exit(1)
    print("OK: Oversampling2x stages coeffVec0/coeffVec1/coeffVecEven from shared coeffs "
          "(sseInitialized=true) and reset() zeroes all FIR history buffers (upStateL/upStateR/"
          "downStateL/downStateR) plus idx")

    # Negative self-probes on temp copies (real tree untouched).
    for buf in ("upStateL", "downStateR"):
        if f"memset({buf}" not in src.replace(" ", "") and f"std::memset({buf}" not in src:
            print(f"FAIL: probe base pattern (memset of {buf}) not found in real source — checker stale vs source")
            return 1

    negs = [
        ("drop one of the four SSE coefficient stagings (coeffVec1)",
         lambda s: s.replace("coeffVec1 = _mm_loadu_ps(&coeffs[4]);", "/* staging lost */", 1)),
        ("clobber sseInitialized = true",
         lambda s: s.replace("sseInitialized = true", "sseInitialized = false", 1)),
        ("skip one FIR history buffer in reset()",
         lambda s: s.replace("std::memset(downStateR, 0, sizeof(downStateR));", "/* skipped */", 1)),
        ("reorder reset(): idx = 0 before the memsets",
         lambda s: s.replace(
             "std::memset(upStateL, 0, sizeof(upStateL));",
             "idx = 0; std::memset(upStateL, 0, sizeof(upStateL));", 1)),
        ("double-memset one buffer",
         lambda s: s.replace(
             "std::memset(downStateL, 0, sizeof(downStateL));",
             "std::memset(downStateL, 0, sizeof(downStateL)); std::memset(downStateL, 0, sizeof(downStateL));", 1)),
    ]
    tmpdir = tempfile.mkdtemp(prefix="check_oversampler_sse_init_")
    try:
        for label, mutate in negs:
            mutated = mutate(src)
            if mutated == src:
                print(f"FAIL: negative '{label}' mutation is a no-op — checker stale vs source")
                return 1
            p = Path(tmpdir) / "PluginProcessor.h"
            p.write_text(mutated, encoding="utf-8")
            ok2, _ = check(mutated)
            if ok2:
                print(f"FAIL: negative check '{label}' did NOT fail — checker too weak")
                return 1
            print(f"negative rejected -> {label}")
    finally:
        shutil.rmtree(tmpdir, ignore_errors=True)

    print("OK: self-probes demonstrate the checker still rejects staging/reset drift")
    return 0


if __name__ == "__main__":
    sys.exit(main())
