#!/usr/bin/env python3
"""Gate check: reverb allpass modulation must actually move.

The reverb_mod tooltip advertises "organic movement to the reverb tail".
The allpass diffuser call site must derive its modulation offset from the
master LFO recurrence (modSin/modCos), like the comb call site does — not
from a constant expression that makes the network static.

Fails (exit 1) if:
  - the allpass call site no longer reads modSin/modCos, or
  - the apSinDelta/apCosDelta precompute loop disappears from beginBlock().
"""
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SRC = ROOT / "source" / "DrippyFX" / "PluginProcessor.h"


def fail(msg: str) -> None:
    print(f"FAIL check_reverb_allpass_mod: {msg}")
    sys.exit(1)


def main() -> int:
    text = SRC.read_text(encoding="utf-8", errors="replace")

    # 1. Allpass call site must derive apMod from the master LFO recurrence.
    call = re.search(
        r"for\s*\(\s*int\s+i\s*=\s*0\s*;\s*i\s*<\s*NUM_AP\s*;\s*\+\+i\s*\)\s*\{[^}]*?float\s+apMod\s*=\s*([^;]+);",
        text,
        re.S,
    )
    if not call:
        fail("no apMod computation found in the NUM_AP loop (PluginProcessor.h)")
    expr = call.group(1)
    if "modSin" not in expr or "modCos" not in expr:
        line = text[: call.start()].count("\n") + 1
        fail(
            f"apMod (line {line}) does not derive from modSin/modCos — "
            f"allpass modulation is static: apMod = {expr.strip()}"
        )

    # 2. Per-allpass phase-offset precompute must exist in beginBlock().
    for name in ("apSinDelta", "apCosDelta"):
        pre = re.search(
            rf"for\s*\(\s*int\s+i\s*=\s*0\s*;\s*i\s*<\s*NUM_AP\s*;\s*\+\+i\s*\)\s*\{{[^}}]*?{name}\[i\]\s*=\s*std::",
            text,
            re.S,
        )
        if not pre:
            fail(f"apSinDelta/apCosDelta precompute ({name}[i] = std::…) missing from beginBlock()")

    # 3. Comb modulation must remain intact (nothing traded away for this fix).
    if "combCosDelta[i]" not in text or "combSinDelta[i]" not in text:
        fail("comb modulation recurrence arrays missing — comb path must stay unchanged")

    print("OK check_reverb_allpass_mod: allpass modulation derives from master LFO (modSin/modCos)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
