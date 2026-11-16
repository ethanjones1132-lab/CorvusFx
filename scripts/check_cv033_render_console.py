#!/usr/bin/env python3
"""CV-033 offline render console contract check.

Pins source/DrippyFX/tools/CorvusOfflineRender.cpp and its two build entries in
source/DrippyFX/CMakeLists.txt. The render tool exists because the release audio
demos must come from the shipped processor, without a host:

  A. Build: both console targets are still declared - CorvusRenderFX and
     CorvusRenderInstrument - each compiling the one shared tool source, each
     defining its own product selector, and neither adding an explicit JUCE GUI
     module to the link line.
  B. Headless: the shared source includes no product editor header and names no
     GUI/editor/audio-device symbol. The tool instantiates the processor and
     calls processBlock; it must not need a window or an audio device.
  C. Options: --seconds, --preset, --out, --sample-rate and --bit-depth are
     still parsed; the sample rate reaches prepareToPlay(); the writer still
     offers 24-bit PCM and IEEE 32-bit float; and the preset still loads through
     the product's own getProgramName()/setCurrentProgram() program interface.

Negative probes mutate in-memory copies (never the real tree) and must be
rejected:
  N1. drop `juce_add_console_app(CorvusRenderFX`
  N2. drop the shared tool source from target_sources
  N3. add `#include "../PluginEditor.h"` to the shared source
  N4. add a createEditor() call to the shared source
  N5. drop the --sample-rate option
  N6. drop the --seconds option
  N7. drop the 32-bit float sample format
  N8. drop the setCurrentProgram() call
  N9. add an explicit juce_gui_basics link to a render target

Benign probes must still pass:
  B1. a CMake comment appended to the build file
  B2. a source block comment that mentions the editor and a GUI window
  B3. an unrelated extra option block added to the parser

Exit 0 only when the real tree passes, every negative is rejected, and every
benign edit is accepted.
"""

import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
CMAKE = ROOT / "source" / "DrippyFX" / "CMakeLists.txt"
SRC = ROOT / "source" / "DrippyFX" / "tools" / "CorvusOfflineRender.cpp"

TARGET_FX = "juce_add_console_app(CorvusRenderFX"
TARGET_INSTRUMENT = "juce_add_console_app(CorvusRenderInstrument"
SHARED_SOURCE = "tools/CorvusOfflineRender.cpp"
SELECTOR_FX = "CORVUS_RENDER_PRODUCT_FX=1"
SELECTOR_INSTRUMENT = "CORVUS_RENDER_PRODUCT_INSTRUMENT=1"

# Option anchors are the parser's own comparisons, so prose in a comment cannot
# satisfy them.
OPT_SECONDS = '== "--seconds"'
OPT_PRESET = '== "--preset"'
OPT_OUT = '== "--out"'
OPT_SAMPLE_RATE = '== "--sample-rate"'
OPT_BIT_DEPTH = '== "--bit-depth"'

FLOAT_SAMPLE_FORMAT = "SampleFormat::floatingPoint"
BITS_24 = "kDefaultBitsPerSample"
BITS_32 = "kFloatBitsPerSample"
PREPARE_RATE = "prepareToPlay (options.sampleRate"
SET_PROGRAM = "setCurrentProgram (options.preset)"
PROGRAM_NAME = "getProgramName (i)"

EDITOR_INCLUDE_RE = re.compile(r'#include\s*[<"][^>"\n]*Editor[^>"\n]*[>"]')
GUI_SYMBOLS = (
    "AudioProcessorEditor",
    "createEditor",
    "DocumentWindow",
    "juce_gui_basics",
    "juce_gui_extra",
)
DEVICE_SYMBOLS = (
    "AudioDeviceManager",
    "AudioAppComponent",
    "AudioSourcePlayer",
)


def strip_cpp_comments(text):
    """Drop // and /* */ comments so probes mutate code, not prose."""
    text = re.sub(r"/\*.*?\*/", "", text, flags=re.S)
    return re.sub(r"//[^\n]*", "", text)


def read_normalised(path):
    """Read a text file with LF endings so multi-line anchors are portable."""
    text = path.read_text(encoding="utf-8", errors="replace")
    return text.replace("\r\n", "\n").replace("\r", "\n")


def strip_cmake_comments(text):
    return re.sub(r"#[^\n]*", "", text)


def render_target_blocks(cmake_text):
    """Text of each render target region, keyed by target name."""
    text = strip_cmake_comments(cmake_text)
    starts = [m.start() for m in re.finditer(
        r"juce_add_console_app\(CorvusRender(?:FX|Instrument)", text)]
    blocks = {}
    for index, start in enumerate(starts):
        end = starts[index + 1] if index + 1 < len(starts) else len(text)
        block = text[start:end]
        name = "CorvusRenderInstrument" if "CorvusRenderInstrument" in block[:80] \
            else "CorvusRenderFX"
        blocks[name] = block
    return blocks


def build_checks(cmake_text):
    res = []
    blocks = render_target_blocks(cmake_text)

    res.append(("FX render target declared", TARGET_FX in strip_cmake_comments(cmake_text),
                TARGET_FX))
    res.append(("instrument render target declared",
                TARGET_INSTRUMENT in strip_cmake_comments(cmake_text),
                TARGET_INSTRUMENT))

    for name in ("CorvusRenderFX", "CorvusRenderInstrument"):
        block = blocks.get(name, "")
        res.append((name + " compiles the shared tool source",
                    SHARED_SOURCE in block, SHARED_SOURCE))

    fx = blocks.get("CorvusRenderFX", "")
    inst = blocks.get("CorvusRenderInstrument", "")
    res.append(("FX target selects the FX processor", SELECTOR_FX in fx, SELECTOR_FX))
    res.append(("instrument target selects the instrument processor",
                SELECTOR_INSTRUMENT in inst, SELECTOR_INSTRUMENT))

    for name, block in (("CorvusRenderFX", fx), ("CorvusRenderInstrument", inst)):
        gui = [symbol for symbol in GUI_SYMBOLS if symbol in block]
        res.append((name + " adds no explicit GUI module", not gui,
                    ", ".join(gui) if gui else "no juce_gui_* link"))

    res.append(("the shared tool source exists", SRC.is_file(), str(SRC)))
    return res


def headless_checks(source_text):
    res = []
    editor_include = EDITOR_INCLUDE_RE.search(source_text)
    res.append(("no product editor include", editor_include is None,
                editor_include.group(0) if editor_include else "no editor include"))

    for symbol in GUI_SYMBOLS:
        res.append(("no GUI/editor symbol '" + symbol + "'", symbol not in source_text,
                    symbol))

    for symbol in DEVICE_SYMBOLS:
        res.append(("no audio-device symbol '" + symbol + "'", symbol not in source_text,
                    symbol))

    return res


def option_checks(source_text):
    res = []
    for label, anchor in (("--seconds parsed", OPT_SECONDS),
                          ("--preset parsed", OPT_PRESET),
                          ("--out parsed", OPT_OUT),
                          ("--sample-rate parsed", OPT_SAMPLE_RATE),
                          ("--bit-depth parsed", OPT_BIT_DEPTH)):
        res.append((label, anchor in source_text, anchor))

    res.append(("sample rate reaches prepareToPlay", PREPARE_RATE in source_text,
                PREPARE_RATE))
    res.append(("--bit-depth accepts 24-bit PCM", BITS_24 in source_text, BITS_24))
    res.append(("--bit-depth accepts 32-bit float", BITS_32 in source_text, BITS_32))
    res.append(("32-bit is written as IEEE float", FLOAT_SAMPLE_FORMAT in source_text,
                FLOAT_SAMPLE_FORMAT))
    res.append(("preset loads through setCurrentProgram", SET_PROGRAM in source_text,
                SET_PROGRAM))
    res.append(("preset names come from getProgramName", PROGRAM_NAME in source_text,
                PROGRAM_NAME))
    return res


def run_checks(cmake_text, source_text, verbose=True):
    code = strip_cpp_comments(source_text)
    checks = build_checks(cmake_text) + headless_checks(code) + option_checks(code)
    ok = True
    for label, good, detail in checks:
        if verbose:
            print(("PASS " if good else "FAIL ") + "cv033-render-console: " + label
                  + " (" + detail + ")")
        ok = ok and good
    return 0 if ok else 1


def expect_reject(label, cmake_text, source_text):
    if run_checks(cmake_text, source_text, verbose=False) == 0:
        print("GATE_FAIL: negative check '" + label + "' did NOT fail -"
              " checker too weak")
        return False
    print("PASS cv033-render-console: negative rejected -> " + label)
    return True


def expect_accept(label, cmake_text, source_text):
    if run_checks(cmake_text, source_text, verbose=False) != 0:
        print("GATE_FAIL: benign edit '" + label + "' was rejected -"
              " checker over-fitted to the current text")
        return False
    print("PASS cv033-render-console: benign edit accepted -> " + label)
    return True


def main():
    for path in (CMAKE, SRC):
        if not path.is_file():
            print("GATE_FAIL: " + str(path) + " missing")
            return 1

    cmake_text = read_normalised(CMAKE)
    source_text = read_normalised(SRC)

    if run_checks(cmake_text, source_text) != 0:
        return 1

    # Negative probes: each must make the checker fail.
    drop = strip_cmake_comments(cmake_text).replace(TARGET_FX, "juce_add_console_app(Removed")
    if drop == strip_cmake_comments(cmake_text):
        print("GATE_FAIL: negative 'FX render target dropped' mutation is a no-op")
        return 1
    if not expect_reject("FX render target dropped from the build", drop, source_text):
        return 1

    no_shared = cmake_text.replace(SHARED_SOURCE, "tools/SomeOtherTool.cpp")
    if no_shared == cmake_text:
        print("GATE_FAIL: negative 'shared tool source dropped' mutation is a no-op")
        return 1
    if not expect_reject("shared tool source dropped from target_sources",
                         no_shared, source_text):
        return 1

    editor_include = '#include "../PluginEditor.h"\n' + source_text
    if not expect_reject("editor header included by the console tool",
                         cmake_text, editor_include):
        return 1

    create_editor = source_text.replace(
        "    writeOut (\"wrote=\" + outFile.getFullPathName());",
        "    auto* editor = processor.createEditor();\n"
        "    writeOut (\"wrote=\" + outFile.getFullPathName());")
    if create_editor == source_text:
        print("GATE_FAIL: negative 'createEditor call added' mutation is a no-op")
        return 1
    if not expect_reject("createEditor() added to the console tool",
                         cmake_text, create_editor):
        return 1

    no_sample_rate = source_text.replace(OPT_SAMPLE_RATE, '== "--removed-rate"')
    if no_sample_rate == source_text:
        print("GATE_FAIL: negative '--sample-rate dropped' mutation is a no-op")
        return 1
    if not expect_reject("--sample-rate option dropped", cmake_text, no_sample_rate):
        return 1

    no_seconds = source_text.replace(OPT_SECONDS, '== "--removed-seconds"')
    if no_seconds == source_text:
        print("GATE_FAIL: negative '--seconds dropped' mutation is a no-op")
        return 1
    if not expect_reject("--seconds option dropped", cmake_text, no_seconds):
        return 1

    no_float = source_text.replace(FLOAT_SAMPLE_FORMAT, "SampleFormat::automatic")
    if no_float == source_text:
        print("GATE_FAIL: negative 'float sample format dropped' mutation is a no-op")
        return 1
    if not expect_reject("32-bit IEEE float writing dropped", cmake_text, no_float):
        return 1

    no_set_program = source_text.replace(SET_PROGRAM, "")
    if no_set_program == source_text:
        print("GATE_FAIL: negative 'setCurrentProgram call dropped' mutation is a no-op")
        return 1
    if not expect_reject("preset no longer loaded through setCurrentProgram",
                         cmake_text, no_set_program):
        return 1

    gui_link = cmake_text.replace(
        "target_link_libraries(CorvusRenderFX\n    PRIVATE\n        juce::juce_audio_utils",
        "target_link_libraries(CorvusRenderFX\n    PRIVATE\n        juce::juce_gui_basics"
        "\n        juce::juce_audio_utils")
    if gui_link == cmake_text:
        print("GATE_FAIL: negative 'GUI module linked' mutation is a no-op")
        return 1
    if not expect_reject("explicit juce_gui_basics link added to a render target",
                         gui_link, source_text):
        return 1

    # Benign probes: unrelated edits must not trip the checker.
    if not expect_accept("CMake comment appended",
                         cmake_text + "\n# benign probe: unrelated comment\n",
                         source_text):
        return 1

    commented = source_text.replace(
        "#include <JuceHeader.h>",
        "/*\n    benign probe: this comment talks about an editor window and a\n"
        "    GUI, and even shows #include \"../PluginEditor.h\", but no real\n"
        "    include is added.\n*/\n#include <JuceHeader.h>")
    if commented == source_text:
        print("GATE_FAIL: benign 'comment mentioning the editor' edit is a no-op")
        return 1
    if not expect_accept("documentation comment mentioning the editor",
                         cmake_text, commented):
        return 1

    extra_option = source_text.replace(
        OPT_OUT,
        '== "--extra-probe")\n        {\n            options.overwrite = false;\n'
        "        }\n        else if (argument " + OPT_OUT)
    if extra_option == source_text:
        print("GATE_FAIL: benign 'extra option block' edit is a no-op")
        return 1
    if not expect_accept("unrelated extra option block added",
                         cmake_text, extra_option):
        return 1

    print("OK cv033 render console contract pinned (two headless console targets,"
          " shared tool source, required options)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
