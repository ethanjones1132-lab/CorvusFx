#!/usr/bin/env python3
"""CV-034 product/identity check for the built Corvus FX bundle.

Pins the v1.0.0 buyer-facing product metadata in source/DrippyFX/CMakeLists.txt:

  - the DrippyFX (Corvus FX) juce_add_plugin block must declare
    PRODUCT_NAME "Corvus FX": JUCE turns this into a "Corvus FX.vst3"
    Windows bundle (folder and inner binary, see _juce_create_windows_package)
    and the host-visible JucePlugin_Name returned by getName();
  - stable identity must survive the rename: COMPANY_NAME "DrippyFX" and the
    PLUGIN_MANUFACTURER_CODE/PLUGIN_CODE pair Drip/Dfx1 are unchanged, and
    with no explicit BUNDLE_ID on the block JUCE derives the bundle ID from
    COMPANY_NAME plus the CMake target name (both still "DrippyFX", see
    docs/CMake API.md), so the rename introduces no second identity. An
    injected BUNDLE_ID would mint a different bundle identity and is rejected.
  - the CorvusInstrument block keeps its independent identity unchanged
    ("Corvus Instrument", com.corvusaudio.CorvusInstrument, "Corvus Audio",
    Crvs/Cvi1) and must not collide with the Corvus FX product name.

Negative probes temp-mutate an in-memory copy of the CMakeLists and require
the checker itself to reject each mutation:
  1. restoring the original wrong product name PRODUCT_NAME "DrippyFX";
  2. FX company drift DrippyFX -> Corvus Audio;
  3. FX plugin-code drift Dfx1 -> Cvi1;
  4. adding an explicit BUNDLE_ID to the FX block (second identity);
  5. renaming the Instrument "Corvus FX" (identity collision).

Exits 0 on green, 1 with diagnostics otherwise.
"""
import re
import sys
from pathlib import Path

CMAKE = Path(__file__).resolve().parent.parent / "source" / "DrippyFX" / "CMakeLists.txt"

errors: list[str] = []


def err(msg: str) -> None:
    errors.append(msg)


def strip_cmake_comments(text: str) -> str:
    """Drop bracket comments and line comments so probes mutate code, not prose."""
    text = re.sub(r"#\[(=*)\[.*?\]\1\]", "", text, flags=re.S)
    text = re.sub(r"#[^\n]*", "", text)
    return text


def block_after(text: str, target: str):
    """Return the body of juce_add_plugin(<target> ...), or None."""
    m = re.search(
        r"juce_add_plugin\s*\(\s*" + re.escape(target) + r"\b(.*?\n\s*\))",
        text,
        flags=re.S,
    )
    return m.group(1) if m else None


def value(block: str, key: str):
    """Return a CMake keyword argument value, quoted or bare (e.g. PLUGIN_CODE Dfx1)."""
    m = re.search(r"\b" + key + r"\s+\"([^\"]*)\"", block)
    if m:
        return m.group(1)
    m = re.search(r"\b" + key + r"\s+([^\s\"\n()]+)", block)
    return m.group(1) if m else None


def check(text: str, source_name: str) -> None:
    t = strip_cmake_comments(text)

    if re.search(r'PRODUCT_NAME\s+"DrippyFX"', t):
        err(f"[{source_name}] stale v0 product name: PRODUCT_NAME \"DrippyFX\" "
            "still present (v1.0.0 product/bundle must be \"Corvus FX\", CV-034)")

    fx = block_after(t, "DrippyFX")
    if fx is None:
        err(f"[{source_name}] could not find the juce_add_plugin DrippyFX block")
        return

    product = value(fx, "PRODUCT_NAME")
    if product is None:
        err(f"[{source_name}] DrippyFX block has no PRODUCT_NAME")
    elif product != "Corvus FX":
        err(f"[{source_name}] FX PRODUCT_NAME is '{product}', expected "
            "'Corvus FX' (bundle must build as 'Corvus FX.vst3' and hosts must "
            "see 'Corvus FX', CV-034)")

    company = value(fx, "COMPANY_NAME")
    if company != "DrippyFX":
        err(f"[{source_name}] FX COMPANY_NAME is '{company}', expected "
            "'DrippyFX' (company identity drift; the default BUNDLE_ID is "
            "derived from COMPANY_NAME + the CMake target name)")

    mfr = value(fx, "PLUGIN_MANUFACTURER_CODE")
    if mfr != "Drip":
        err(f"[{source_name}] FX PLUGIN_MANUFACTURER_CODE is '{mfr}', expected "
            "'Drip' (stable manufacturer code must survive the rename)")

    code = value(fx, "PLUGIN_CODE")
    if code != "Dfx1":
        err(f"[{source_name}] FX PLUGIN_CODE is '{code}', expected 'Dfx1' "
            "(stable plugin code must survive the rename; JUCE derives the "
            "VST3 class IDs from the codes)")

    if re.search(r"\bBUNDLE_ID\b", fx):
        err(f"[{source_name}] DrippyFX block declares an explicit BUNDLE_ID "
            "(JUCE already derives the bundle ID from the unchanged "
            "COMPANY_NAME + target name; an override mints a second, "
            "unapproved bundle identity)")

    # The Instrument keeps its own independent name/identity; it must not be
    # renamed or converged with the Corvus FX product.
    inst = block_after(t, "CorvusInstrument")
    if inst is None:
        err(f"[{source_name}] could not find the juce_add_plugin "
            "CorvusInstrument block")
        return

    inst_product = value(inst, "PRODUCT_NAME")
    if inst_product != "Corvus Instrument":
        err(f"[{source_name}] Corvus Instrument PRODUCT_NAME is "
            f"'{inst_product}', expected 'Corvus Instrument' (the Instrument's "
            "independent name/identity stays unchanged by CV-034)")

    inst_bundle = value(inst, "BUNDLE_ID")
    if inst_bundle != "com.corvusaudio.CorvusInstrument":
        err(f"[{source_name}] Corvus Instrument BUNDLE_ID is '{inst_bundle}', "
            "expected 'com.corvusaudio.CorvusInstrument' (identity drift)")

    inst_company = value(inst, "COMPANY_NAME")
    if inst_company != "Corvus Audio":
        err(f"[{source_name}] Corvus Instrument COMPANY_NAME is "
            f"'{inst_company}', expected 'Corvus Audio' (identity drift)")

    inst_mfr = value(inst, "PLUGIN_MANUFACTURER_CODE")
    inst_code = value(inst, "PLUGIN_CODE")
    if inst_mfr != "Crvs" or inst_code != "Cvi1":
        err(f"[{source_name}] Corvus Instrument plugin codes are "
            f"'{inst_mfr}'/'{inst_code}', expected 'Crvs'/'Cvi1' (identity "
            "drift)")


def apply_mutation(base: str, old: str, new: str):
    """Apply one exact-count mutation, or None if the literal is absent/ambiguous."""
    count = base.count(old)
    if count != 1:
        return None
    return base.replace(old, new, 1)


def probe(base: str, mutated, desc: str, expect_substr: str) -> None:
    if mutated is None:
        err(f"negative check could not apply mutation ({desc})")
        return
    saved = errors[:]
    errors.clear()
    check(mutated, "mutated-cmake")
    found = errors[:]
    errors[:] = saved
    if not any(expect_substr in e for e in found):
        err(f"negative check failed: {desc} was not rejected "
            f"(expected a diagnostic containing '{expect_substr}')")


def main() -> int:
    raw = CMAKE.read_text(encoding="utf-8", errors="replace")
    base = strip_cmake_comments(raw)
    check(base, "CMakeLists.txt")

    # Negative probes: the checker must reject the original wrong product
    # name and every unapproved identity drift.
    probe(base,
          apply_mutation(base, 'PRODUCT_NAME "Corvus FX"', 'PRODUCT_NAME "DrippyFX"'),
          "original wrong product name 'DrippyFX' restored", "PRODUCT_NAME")

    probe(base,
          apply_mutation(base, 'COMPANY_NAME "DrippyFX"', 'COMPANY_NAME "Corvus Audio"'),
          "FX company drift DrippyFX->Corvus Audio", "COMPANY_NAME")

    probe(base,
          apply_mutation(base, "PLUGIN_CODE Dfx1", "PLUGIN_CODE Cvi1"),
          "FX plugin-code drift Dfx1->Cvi1", "PLUGIN_CODE")

    probe(base,
          apply_mutation(base, 'PRODUCT_NAME "Corvus FX"',
                         'BUNDLE_ID "com.drippyfx.drippyfx"\n    '
                         'PRODUCT_NAME "Corvus FX"'),
          "injected explicit BUNDLE_ID on the FX block", "BUNDLE_ID")

    probe(base,
          apply_mutation(base, 'PRODUCT_NAME "Corvus Instrument"',
                         'PRODUCT_NAME "Corvus FX"'),
          "Instrument renamed to the Corvus FX product name",
          "Corvus Instrument PRODUCT_NAME")

    if errors:
        print("FAIL: product/identity invariants violated:")
        for e in errors:
            print(f"  - {e}")
        return 1

    print("OK: CV-034 product identity pinned "
          "(FX product 'Corvus FX' -> 'Corvus FX.vst3' bundle / host-visible "
          "'Corvus FX'; stable identity DrippyFXTarget/DrippyFX/Drip/Dfx1 "
          "with derived bundle ID; Instrument identity unchanged)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
