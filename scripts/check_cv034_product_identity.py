#!/usr/bin/env python3
"""CV-034 / CV-068 product+identity check for the built Corvus FX bundle.

Pins the v1.0.0 buyer-facing product metadata in source/DrippyFX/CMakeLists.txt:

  - the DrippyFX (Corvus FX) juce_add_plugin block must declare
    PRODUCT_NAME "Corvus FX": JUCE turns this into a "Corvus FX.vst3"
    Windows bundle (folder and inner binary, see _juce_create_windows_package)
    and the host-visible JucePlugin_Name returned by getName();
  - the FX must present "Corvus Audio" as its manufacturer (CV-068), the same
    company name the Instrument reports in the host plugin list;
  - stable identity must survive that manufacturer rename: the
    PLUGIN_MANUFACTURER_CODE/PLUGIN_CODE pair Drip/Dfx1 is unchanged, and the
    bundle ID that JUCE used to derive from COMPANY_NAME "DrippyFX" plus the
    CMake target name "DrippyFX" is now declared explicitly as BUNDLE_ID
    "com.DrippyFX.DrippyFX". JUCE's fallback is "com.<COMPANY_NAME>.<target>"
    (see docs/CMake API.md); without the explicit value the renamed company
    would mint a second bundle identity and orphan existing installs.
  - the CorvusInstrument block keeps its independent identity unchanged
    ("Corvus Instrument", com.corvusaudio.CorvusInstrument, "Corvus Audio",
    Crvs/Cvi1) and must not collide with the Corvus FX product name.

Negative probes temp-mutate an in-memory copy of the CMakeLists and require
the checker itself to reject each mutation:
  1. restoring the original wrong product name PRODUCT_NAME "DrippyFX";
  2. FX manufacturer reverting Corvus Audio -> DrippyFX (CV-068 regression);
  3. FX BUNDLE_ID drift away from com.DrippyFX.DrippyFX;
  4. deleting the explicit FX BUNDLE_ID (JUCE would re-derive a new identity);
  5. declaring a second BUNDLE_ID on the FX block;
  6. FX plugin-code drift Dfx1 -> Cvi1;
  7. renaming the Instrument "Corvus FX" (identity collision).

Exits 0 on green, 1 with diagnostics otherwise.
"""
import re
import sys
from pathlib import Path

CMAKE = Path(__file__).resolve().parent.parent / "source" / "DrippyFX" / "CMakeLists.txt"

# The bundle ID JUCE derived for the FX before CV-068
# ("com." + COMPANY_NAME "DrippyFX" + "." + CMake target "DrippyFX").
# CV-068 pins it explicitly so the manufacturer rename cannot rewrite it.
FX_BUNDLE_ID = "com.DrippyFX.DrippyFX"
FX_BUNDLE_LITERAL = f'BUNDLE_ID "{FX_BUNDLE_ID}"'

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
    if company != "Corvus Audio":
        err(f"[{source_name}] FX COMPANY_NAME is '{company}', expected "
            "'Corvus Audio' (CV-068: the FX must present the Corvus Audio "
            "manufacturer in the host plugin list, like the Instrument)")

    bundle_count = len(re.findall(r"\bBUNDLE_ID\b", fx))
    bundle = value(fx, "BUNDLE_ID")
    if bundle_count == 0:
        err(f"[{source_name}] DrippyFX block declares no explicit BUNDLE_ID "
            f"(expected {FX_BUNDLE_ID}: with COMPANY_NAME now 'Corvus Audio', "
            "JUCE's com.<company>.<target> fallback would orphan existing "
            "installs, CV-068)")
    elif bundle_count > 1:
        err(f"[{source_name}] DrippyFX block declares {bundle_count} BUNDLE_ID "
            f"entries, expected exactly one ({FX_BUNDLE_ID}); a second entry "
            "mints an unapproved bundle identity")
    elif bundle != FX_BUNDLE_ID:
        err(f"[{source_name}] FX BUNDLE_ID is '{bundle}', expected "
            f"'{FX_BUNDLE_ID}' (the pre-CV-068 derived bundle identity must "
            "survive the manufacturer rename; changing it orphans installs)")

    mfr = value(fx, "PLUGIN_MANUFACTURER_CODE")
    if mfr != "Drip":
        err(f"[{source_name}] FX PLUGIN_MANUFACTURER_CODE is '{mfr}', expected "
            "'Drip' (stable manufacturer code must survive the rename)")

    code = value(fx, "PLUGIN_CODE")
    if code != "Dfx1":
        err(f"[{source_name}] FX PLUGIN_CODE is '{code}', expected 'Dfx1' "
            "(stable plugin code must survive the rename; JUCE derives the "
            "VST3 class IDs from the codes)")

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
    # Normalise line endings: the Windows checkout keeps CMakeLists.txt CRLF,
    # the probe literals below are written with plain "\n".
    raw = raw.replace("\r\n", "\n").replace("\r", "\n")
    base = strip_cmake_comments(raw)
    check(base, "CMakeLists.txt")

    # Negative probes: the checker must reject the original wrong product
    # name, a manufacturer revert to the old company name, and every
    # unapproved identity drift. The FX block anchors carry the target name so
    # they never match the Instrument block (which shares "Corvus Audio").
    fx_company_anchor = 'juce_add_plugin(DrippyFX\n    COMPANY_NAME "Corvus Audio"'
    fx_company_revert = 'juce_add_plugin(DrippyFX\n    COMPANY_NAME "DrippyFX"'

    probe(base,
          apply_mutation(base, 'PRODUCT_NAME "Corvus FX"', 'PRODUCT_NAME "DrippyFX"'),
          "original wrong product name 'DrippyFX' restored", "PRODUCT_NAME")

    probe(base,
          apply_mutation(base, fx_company_anchor, fx_company_revert),
          "FX manufacturer revert Corvus Audio->DrippyFX", "COMPANY_NAME")

    probe(base,
          apply_mutation(base, FX_BUNDLE_LITERAL,
                         'BUNDLE_ID "com.corvusaudio.CorvusFX"'),
          "FX bundle-ID drift com.DrippyFX.DrippyFX->com.corvusaudio.CorvusFX",
          "BUNDLE_ID")

    probe(base,
          apply_mutation(base, "    " + FX_BUNDLE_LITERAL + "\n", ""),
          "explicit FX BUNDLE_ID deleted", "BUNDLE_ID")

    probe(base,
          apply_mutation(base, "    " + FX_BUNDLE_LITERAL + "\n",
                         "    " + FX_BUNDLE_LITERAL + "\n"
                         '    BUNDLE_ID "com.corvusaudio.CorvusFX"\n'),
          "second BUNDLE_ID injected on the FX block", "BUNDLE_ID")

    probe(base,
          apply_mutation(base, "PLUGIN_CODE Dfx1", "PLUGIN_CODE Cvi1"),
          "FX plugin-code drift Dfx1->Cvi1", "PLUGIN_CODE")

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

    print("OK: CV-034/CV-068 product identity pinned "
          "(FX product 'Corvus FX' -> 'Corvus FX.vst3' bundle / host-visible "
          "'Corvus FX'; manufacturer 'Corvus Audio'; stable identity "
          "DrippyFXTarget/Drip/Dfx1 with explicit bundle ID "
          f"'{FX_BUNDLE_ID}'; Instrument identity unchanged)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
