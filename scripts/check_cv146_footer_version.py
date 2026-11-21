#!/usr/bin/env python3
"""CV-146 footer build-version check for the Corvus FX editor.

A released Corvus FX build must be identifiable from its own editor UI, so the
footer band resized() already reserves must carry the version the build
actually has. This pins that wiring in source/DrippyFX/PluginEditor.cpp:

  A. resized() still declares `const int kFooterRef = 20;` and still carves
     that band out of the content area, capturing it:
     `footerBand = area.removeFromBottom(sc(kFooterRef));`
     Shrinking or dropping the band to make room for the text is rejected.
  B. paint() draws exactly one version stamp from the build, not a hard-coded
     number: a `g.drawText(...)` whose text argument uses
     ProjectInfo::versionString (the CMake project VERSION that JUCE generates
     into JuceHeader.h for every target that compiles this editor) or
     JucePlugin_VersionString.
  C. That version draw is anchored inside paint() (before resized()) and its
     rectangle is the captured footer band, not the editor bounds, so the
     existing knobs / FX grid / master rail are not disturbed.

Comments are masked before matching, so prose that quotes the draw (or a
commented-out draw) can neither satisfy nor trip these rules.

Negative probes mutate in-memory copies (never the real tree), prove the
mutation changed the text, and must be rejected:
  N1. replace the version source in the stamp with a hard-coded "v1.0.0"
  N2. drop the `footerBand = area.removeFromBottom(sc(kFooterRef));` capture
  N3. shrink the reserved band to `const int kFooterRef = 0;`
  N4. draw the stamp across getLocalBounds() instead of the footer band
  N5. comment out the only version draw (comments must not satisfy rule B)

Benign probes must still pass:
  B1. add a prose comment that quotes the version draw

Exit 0 only when the real tree passes, every negative is rejected, and the
benign edit is accepted.
"""

import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
ED = ROOT / "source" / "DrippyFX" / "PluginEditor.cpp"

PAINT_MARKER = "CorvusFXAudioProcessorEditor::paint"
RESIZED_MARKER = "CorvusFXAudioProcessorEditor::resized"

# The reserved footer band must stay 20 reference pixels tall; it is the space
# the version stamp lives in, not space the stamp may consume.
FOOTER_REF = 20
BAND_DECL_RE = re.compile(r"const\s+int\s+kFooterRef\s*=\s*(-?\d+)\s*;")
BAND_CAPTURE_RE = re.compile(
    r"(\w+)\s*=\s*area\s*\.\s*removeFromBottom\s*\(\s*sc\s*\(\s*"
    r"kFooterRef\s*\)\s*\)\s*;")

# Either the JUCE plugin define or the CMake project VERSION that JUCE
# generates into ProjectInfo::versionString for every target.
BUILD_VERSION_SOURCES = ("ProjectInfo::versionString",
                         "JucePlugin_VersionString")

# The whole version text expression, used by negative probe N1.
VERSION_SOURCE_EXPR_RE = re.compile(
    r'juce::String\s*\(\s*"v"\s*\)\s*\+\s*juce::String\s*\(\s*'
    r'(?:ProjectInfo::versionString|JucePlugin_VersionString)\s*\)')


def strip_cpp_comments(text):
    """Drop // and /* */ comments so probes mutate code, not prose."""
    text = re.sub(r"/\*.*?\*/", "", text, flags=re.S)
    return re.sub(r"//[^\n]*", "", text)


def read_normalised(path):
    """Read a text file with LF endings so multi-line anchors are portable."""
    text = path.read_text(encoding="utf-8", errors="replace")
    return text.replace("\r\n", "\n").replace("\r", "\n")


def split_args(call_args):
    """Split one drawText argument list on top-level commas."""
    args = []
    depth = 0
    in_string = False
    escaped = False
    current = []
    for ch in call_args:
        if in_string:
            current.append(ch)
            if escaped:
                escaped = False
            elif ch == "\\":
                escaped = True
            elif ch == '"':
                in_string = False
            continue
        if ch == '"':
            in_string = True
            current.append(ch)
            continue
        if ch in "([{":
            depth += 1
        elif ch in ")]}":
            depth -= 1
        if ch == "," and depth == 0:
            args.append("".join(current).strip())
            current = []
        else:
            current.append(ch)
    if current:
        args.append("".join(current).strip())
    return args


def find_draw_calls(code):
    """Return (start, args) for every g.drawText(...) call in stripped code."""
    calls = []
    needle = "g.drawText"
    index = code.find(needle)
    while index != -1:
        open_paren = code.find("(", index + len(needle))
        if open_paren == -1:
            break
        depth = 0
        in_string = False
        escaped = False
        close_paren = -1
        for pos in range(open_paren, len(code)):
            ch = code[pos]
            if in_string:
                if escaped:
                    escaped = False
                elif ch == "\\":
                    escaped = True
                elif ch == '"':
                    in_string = False
                continue
            if ch == '"':
                in_string = True
            elif ch == "(":
                depth += 1
            elif ch == ")":
                depth -= 1
                if depth == 0:
                    close_paren = pos
                    break
        if close_paren == -1:
            break
        calls.append((index, split_args(code[open_paren + 1:close_paren])))
        index = code.find(needle, close_paren)
    return calls


def footer_version_checks(code):
    res = []

    paint_at = code.find(PAINT_MARKER)
    resized_at = code.find(RESIZED_MARKER)
    res.append(("paint() is defined", paint_at != -1, PAINT_MARKER))

    decl = BAND_DECL_RE.search(code)
    decl_ok = decl is not None and int(decl.group(1)) == FOOTER_REF
    res.append(("kFooterRef band is %d reference pixels" % FOOTER_REF,
                decl_ok,
                decl.group(0) if decl else "kFooterRef missing"))

    capture = BAND_CAPTURE_RE.search(code)
    band_var = capture.group(1) if capture else ""
    res.append(("resized() reserves and captures the kFooterRef band",
                capture is not None,
                capture.group(0) if capture else "band capture missing"))

    version_calls = []
    for start, args in find_draw_calls(code):
        first = args[0] if args else ""
        if any(source in first for source in BUILD_VERSION_SOURCES):
            version_calls.append((start, first, args[1] if len(args) > 1 else ""))

    res.append(("exactly one build-version draw call",
                len(version_calls) == 1,
                str(len(version_calls)) + " found"))

    in_paint = (len(version_calls) == 1 and paint_at != -1
                and resized_at != -1
                and paint_at < version_calls[0][0] < resized_at)
    res.append(("version stamp is drawn from paint()", in_paint,
                "paint() < drawText < resized()" if in_paint
                else "version draw not between paint() and resized()"))

    in_band = False
    if len(version_calls) == 1 and band_var:
        in_band = re.search(r"\b" + re.escape(band_var) + r"\b",
                            version_calls[0][2]) is not None
    res.append(("version stamp is drawn inside the reserved footer band",
                in_band,
                version_calls[0][2] if len(version_calls) == 1
                else "no version draw"))
    return res


def run_checks(source_text, verbose=True):
    checks = footer_version_checks(strip_cpp_comments(source_text))
    ok = True
    for label, good, detail in checks:
        if verbose:
            print(("PASS " if good else "FAIL ")
                  + "cv146-footer-version: " + label + " (" + detail + ")")
        ok = ok and good
    return 0 if ok else 1


def expect_reject(label, source_text):
    if run_checks(source_text, verbose=False) == 0:
        print("GATE_FAIL: negative check '" + label + "' did NOT fail -"
              " checker too weak")
        return False
    print("PASS cv146-footer-version: negative rejected -> " + label)
    return True


def expect_accept(label, source_text):
    if run_checks(source_text, verbose=False) != 0:
        print("GATE_FAIL: benign edit '" + label + "' was rejected -"
              " checker over-fitted to the current text")
        return False
    print("PASS cv146-footer-version: benign edit accepted -> " + label)
    return True


def main():
    if not ED.is_file():
        print("GATE_FAIL: " + str(ED) + " missing")
        return 1

    source_text = read_normalised(ED)

    if run_checks(source_text) != 0:
        return 1

    # N1: a hard-coded stamp must be rejected even though a version-shaped
    # string is drawn.
    hard_coded = VERSION_SOURCE_EXPR_RE.sub('juce::String("v1.0.0")',
                                            source_text)
    if hard_coded == source_text:
        print("GATE_FAIL: negative 'version stamp hard-coded' mutation"
              " is a no-op")
        return 1
    if not expect_reject('version stamp hard-codes "v1.0.0"', hard_coded):
        return 1

    # N2: dropping the band capture makes the draw lose its reserved band.
    dropped, dropped_count = BAND_CAPTURE_RE.subn("", source_text)
    if dropped_count != 1:
        print("GATE_FAIL: negative 'footer band capture dropped' mutation"
              " matched " + str(dropped_count) + " times, expected 1")
        return 1
    if not expect_reject("footer band capture dropped from resized()",
                         dropped):
        return 1

    # N3: shrinking the band to make room for the text must be rejected.
    old_decl = "const int kFooterRef = %d;" % FOOTER_REF
    shrunk = source_text.replace(old_decl, "const int kFooterRef = 0;")
    if shrunk == source_text:
        print("GATE_FAIL: negative 'footer band shrunk' mutation is a no-op")
        return 1
    if not expect_reject("reserved kFooterRef band shrunk to 0", shrunk):
        return 1

    # N4: a stamp that ignores the reserved band is not inside the footer.
    outside = source_text.replace("footerBand.reduced(6, 0)",
                                  "getLocalBounds()")
    if outside == source_text:
        print("GATE_FAIL: negative 'version stamp drawn outside band'"
              " mutation is a no-op")
        return 1
    if not expect_reject("version stamp drawn over getLocalBounds()", outside):
        return 1

    # N5: comments are masked, so a commented-out draw cannot satisfy rule B.
    commented = source_text.replace(
        'g.drawText(juce::String("v") + '
        'juce::String(ProjectInfo::versionString),',
        '// g.drawText(juce::String("v") + '
        'juce::String(ProjectInfo::versionString),', 1)
    if commented == source_text:
        print("GATE_FAIL: negative 'version draw commented out' mutation"
              " is a no-op")
        return 1
    if not expect_reject("only version draw is commented out", commented):
        return 1

    # B1: a prose comment quoting the draw is not code.
    benign = source_text.replace(
        "    // Version text\n",
        "    // Version text\n"
        "    // benign probe: g.drawText(ProjectInfo::versionString,\n"
        "    // footerBand) is prose and must neither satisfy nor trip the\n"
        "    // scan.\n", 1)
    if benign == source_text:
        print("GATE_FAIL: benign 'comment quoting the version draw' edit"
              " is a no-op")
        return 1
    if not expect_accept("comment quoting the version draw", benign):
        return 1

    print("OK cv146 footer version pinned (build version from"
          " ProjectInfo::versionString stamped inside the reserved kFooterRef"
          " band; hard-coded, unbanded and commented-out draws rejected)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
