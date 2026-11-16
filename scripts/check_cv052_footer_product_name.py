#!/usr/bin/env python3
"""CV-052 footer product-name check for the Corvus FX editor.

A buyer reading the plugin's own footer must see the product name the v1.0.0
release and README use. Pins the one drawn footer string in
source/DrippyFX/PluginEditor.cpp:

  A. paint() still draws exactly one footer through
     g.drawText(<string>, getLocalBounds().removeFromBottom(15),
     juce::Justification::centred, true) - the call is anchored inside paint()
     (before resized()), on the same bottom-15 band, centred and ellipsised, so
     the rename cannot move, resize or un-centre the footer.
  B. That string is exactly "Corvus FX v1.0 | Professional Multi-FX Suite"
     (README H1 "Corvus FX"). The bundle name itself stays pinned by
     scripts/check_cv034_product_identity.py and is not re-checked here.
  C. No g.drawText call draws a string starting with the pre-release product
     spelling "CorvusFX" (no space): the footer is the only place the UI draws
     the product name, so a second drawn mention would contradict it. The
     "CorvusFX" applicationName preference string at the top of the file is a
     different, non-drawn identity and is deliberately not matched.

Negative probes mutate in-memory copies (never the real tree) and must be
rejected:
  N1. restore the old footer text "CorvusFX v1.0 | Professional Multi-FX Suite"
  N2. drop the footer draw call from paint()
  N3. drift the footer version to "Corvus FX v2.0"

Benign probes must still pass:
  B1. a code comment that quotes the old "CorvusFX v1.0" name (prose, not code)

Exit 0 only when the real tree passes, every negative is rejected, and the
benign edit is accepted.
"""

import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
ED = ROOT / "source" / "DrippyFX" / "PluginEditor.cpp"

# Buyer-facing product name the v1.0.0 release and README use (README H1).
FOOTER_TEXT = "Corvus FX v1.0 | Professional Multi-FX Suite"
STALE_TEXT = "CorvusFX v1.0"

PAINT_MARKER = "CorvusFXAudioProcessorEditor::paint"
RESIZED_MARKER = "CorvusFXAudioProcessorEditor::resized"

# The footer anchor is the whole draw call, so the string, the bottom-15 band,
# the centred justification and the ellipsis flag are pinned together.
FOOTER_CALL_RE = re.compile(
    r'g\.drawText\s*\(\s*"([^"\n]*)"\s*,\s*'
    r'getLocalBounds\s*\(\s*\)\s*\.\s*removeFromBottom\s*\(\s*15\s*\)\s*,\s*'
    r'juce::Justification::centred\s*,\s*true\s*\)'
)
# Any drawn string that starts with the old "CorvusFX" spelling (no space) is a
# stale product name. Only g.drawText arguments are scanned, so the
# applicationName "CorvusFX" preference literal is untouched by this rule.
DRAWN_LITERAL_RE = re.compile(r'g\.drawText\s*\(\s*"([^"\n]*)"')
STALE_DRAWN_PREFIX = "CorvusFX"


def strip_cpp_comments(text):
    """Drop // and /* */ comments so probes mutate code, not prose."""
    text = re.sub(r"/\*.*?\*/", "", text, flags=re.S)
    return re.sub(r"//[^\n]*", "", text)


def read_normalised(path):
    """Read a text file with LF endings so multi-line anchors are portable."""
    text = path.read_text(encoding="utf-8", errors="replace")
    return text.replace("\r\n", "\n").replace("\r", "\n")


def footer_checks(code):
    res = []

    paint_at = code.find(PAINT_MARKER)
    resized_at = code.find(RESIZED_MARKER)
    res.append(("paint() is defined", paint_at != -1, PAINT_MARKER))

    matches = list(FOOTER_CALL_RE.finditer(code))
    res.append(("exactly one footer draw call", len(matches) == 1,
                str(len(matches)) + " found"))

    in_paint = (bool(matches) and paint_at != -1 and resized_at != -1
                and paint_at < matches[0].start() < resized_at)
    res.append(("footer is drawn from paint()", in_paint,
                "paint() < drawText < resized()" if in_paint
                else "footer draw not between paint() and resized()"))

    drawn = matches[0].group(1) if len(matches) == 1 else ""
    res.append(("footer text is the v1.0.0 product name", drawn == FOOTER_TEXT,
                repr(drawn)))

    stale = [text for text in DRAWN_LITERAL_RE.findall(code)
             if text.startswith(STALE_DRAWN_PREFIX)]
    res.append(("no drawText draws the old 'CorvusFX' name", not stale,
                ", ".join(stale) if stale else "no stale drawText"))
    return res


def run_checks(source_text, verbose=True):
    checks = footer_checks(strip_cpp_comments(source_text))
    ok = True
    for label, good, detail in checks:
        if verbose:
            print(("PASS " if good else "FAIL ")
                  + "cv052-footer-product-name: " + label + " (" + detail + ")")
        ok = ok and good
    return 0 if ok else 1


def expect_reject(label, source_text):
    if run_checks(source_text, verbose=False) == 0:
        print("GATE_FAIL: negative check '" + label + "' did NOT fail -"
              " checker too weak")
        return False
    print("PASS cv052-footer-product-name: negative rejected -> " + label)
    return True


def expect_accept(label, source_text):
    if run_checks(source_text, verbose=False) != 0:
        print("GATE_FAIL: benign edit '" + label + "' was rejected -"
              " checker over-fitted to the current text")
        return False
    print("PASS cv052-footer-product-name: benign edit accepted -> " + label)
    return True


def main():
    if not ED.is_file():
        print("GATE_FAIL: " + str(ED) + " missing")
        return 1

    source_text = read_normalised(ED)

    if run_checks(source_text) != 0:
        return 1

    # Negative probes: each must make the checker fail.

    # N1 (mandatory): the pre-release footer text must be rejected.
    if source_text.count(FOOTER_TEXT) != 1:
        print("GATE_FAIL: footer text anchor appears "
              + str(source_text.count(FOOTER_TEXT)) + " times, expected 1")
        return 1
    reverted = source_text.replace(FOOTER_TEXT, STALE_TEXT)
    if reverted == source_text:
        print("GATE_FAIL: negative 'old footer text restored' mutation is a no-op")
        return 1
    if not expect_reject('old footer text "' + STALE_TEXT + '" restored', reverted):
        return 1

    dropped = FOOTER_CALL_RE.sub("", source_text)
    if dropped == source_text:
        print("GATE_FAIL: negative 'footer draw call dropped' mutation is a no-op")
        return 1
    if not expect_reject("footer draw call removed from paint()", dropped):
        return 1

    drifted = source_text.replace("Corvus FX v1.0 |", "Corvus FX v2.0 |")
    if drifted == source_text:
        print("GATE_FAIL: negative 'footer version drifted' mutation is a no-op")
        return 1
    if not expect_reject("footer version drifted to v2.0", drifted):
        return 1

    # Benign probe: the old name in a comment is prose, not a drawn string.
    benign = source_text.replace(
        "    // Version text\n",
        "    // Version text\n"
        "    // benign probe: this comment still quotes \"CorvusFX v1.0\" but\n"
        "    // comments are prose and must neither satisfy nor trip the scan.\n")
    if benign == source_text:
        print("GATE_FAIL: benign 'comment quoting the old name' edit is a no-op")
        return 1
    if not expect_accept("comment quoting the old 'CorvusFX v1.0' name", benign):
        return 1

    print('OK cv052 footer product name pinned ("' + FOOTER_TEXT + '" drawn'
          " from paint() on the bottom-15 centred band; old 'CorvusFX' literal"
          " rejected)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
