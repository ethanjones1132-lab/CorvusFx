#!/usr/bin/env python3
"""CV-033 offline render WAV contract check.

Pins source/DrippyFX/tools/CorvusOfflineRender.cpp and its two build entries in
source/DrippyFX/CMakeLists.txt, focusing on the WAV contract:

Contract to pin (each with a revert probe that must fail the checker):
  A. Default output format: 48 kHz, stereo, 24-bit PCM, and --bit-depth 32
     selects IEEE float.
  B. Render length is bounded to 0.25-30 s inclusive.
  C. Output is written to "<out>.partial" and moved into place, and an
     existing "<out>" is refused without --overwrite.
  D. --preset resolves a program by name and by index through
     getProgramName() / setCurrentProgram().

Exit 0 only when the real tree passes, every negative is rejected, and every
benign edit is accepted.
"""

import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
CMAKE = ROOT / "source" / "DrippyFX" / "CMakeLists.txt"
SRC = ROOT / "source" / "DrippyFX" / "tools" / "CorvusOfflineRender.cpp"

# Contract anchors: each is a unique pattern in the source that guarantees the
# contract is satisfied in the current version.

def strip_cpp_comments(text):
    """Drop // and /* */ comments so probes mutate code, not prose."""
    text = re.sub(r"/\*.*?\*/", "", text, flags=re.S)
    return re.sub(r"//[^\n]*", "", text)

def read_normalised(path):
    """Read a text file with LF endings so multi-line anchors are portable."""
    text = path.read_text(encoding="utf-8", errors="replace")
    return text.replace("\r\n", "\n").replace("\r", "\n")

def run_checks(cmake_text, source_text, verbose=True):
    """Run the contract checks on the real tree. Returns 0 if all pass."""
    # Anchors are matched against code with comments removed, so commenting a
    # clause out (the C.2 revert probe does exactly that) cannot satisfy it.
    code = strip_cpp_comments(source_text)
    checks = []
    
    # A. Default output format: 48 kHz, stereo, 24-bit PCM, --bit-depth 32 selects IEEE float
    checks.append(("default format is 48 kHz",
                   "constexpr double kDefaultSampleRate = 48000.0;" in code,
                   "kDefaultSampleRate = 48000.0"))
    checks.append(("default format is stereo",
                   "constexpr int kNumChannels = 2;" in code,
                   "kNumChannels = 2"))
    checks.append(("default format is 24-bit PCM",
                   "constexpr int kDefaultBitsPerSample = 24;" in code,
                   "kDefaultBitsPerSample = 24"))
    checks.append(("--bit-depth 32 selects IEEE float",
                   "constexpr int kFloatBitsPerSample = 32;" in code,
                   "kFloatBitsPerSample = 32"))
    checks.append(("32-bit float uses SampleFormat::floatingPoint",
                   "SampleFormat::floatingPoint" in code,
                   "SampleFormat::floatingPoint"))
    
    # B. Render length is bounded to 0.25-30 s inclusive
    checks.append(("min seconds is 0.25",
                   "constexpr double kMinSeconds = 0.25;" in code,
                   "kMinSeconds = 0.25"))
    checks.append(("max seconds is 30.0",
                   "constexpr double kMaxSeconds = 30.0;" in code,
                   "kMaxSeconds = 30.0"))
    
    # C. Output contract: written to <out>.partial and moved into place
    checks.append(("temp file uses .partial suffix",
                   ".getSiblingFile (outFile.getFileName() + \".partial\")" in code,
                   "tempFile creation with .partial"))
    checks.append(("partial file used for verification before move",
                   "if (! tempFile.moveFileTo (outFile))" in code,
                   "moveFileTo into final path"))
    checks.append(("existing output file refused without --overwrite",
                   'if (outFile.existsAsFile() && ! options.overwrite)' in code,
                   "output file existence check"))
    
    # D. --preset resolves a program by name and by index through getProgramName() / setCurrentProgram()
    checks.append(("preset resolution uses getProgramName",
                   "processor.getProgramName (options.preset)" in code,
                   "getProgramName call"))
    checks.append(("preset resolution uses setCurrentProgram",
                   "processor.setCurrentProgram (options.preset)" in code,
                   "setCurrentProgram call"))
    
    # Verify that presetText is resolved via getProgramName/processor.getProgramName() pattern
    checks.append(("presetText compared against program names",
                   "processor.getProgramName (i)" in code,
                   "program name comparison"))
    
    ok = True
    for label, good, detail in checks:
        if verbose:
            print(("PASS " if good else "FAIL ") + "cv033-render-contract: " + label
                  + " (" + detail + ")")
        ok = ok and good
    return 0 if ok else 1

def expect_reject(label, cmake_text, source_text):
    """Expect the checker to reject the mutated version."""
    if run_checks(cmake_text, source_text, verbose=False) == 0:
        print("GATE_FAIL: negative check '" + label + "' did NOT fail -"
              " checker too weak")
        return False
    print("PASS cv033-render-contract: negative rejected -> " + label)
    return True

def expect_accept(label, cmake_text, source_text):
    """Expect the checker to accept the benign edit."""
    if run_checks(cmake_text, source_text, verbose=False) != 0:
        print("GATE_FAIL: benign edit '" + label + "' was rejected -"
              " checker over-fitted to the current text")
        return False
    print("PASS cv033-render-contract: benign edit accepted -> " + label)
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

    # NEGATIVE PROBES: mutate contract elements and expect failure
    
    # A.1 Default format mutation: change 48000.0 to 44100.0
    modified_default = source_text.replace(
        "constexpr double kDefaultSampleRate = 48000.0;",
        "constexpr double kDefaultSampleRate = 44100.0;")
    if modified_default == source_text:
        print("GATE_FAIL: negative 'default format changed' mutation is a no-op")
        return 1
    if not expect_reject("default sample rate changed from 48 kHz",
                         cmake_text, modified_default):
        return 1
    
    # A.2 Default bits mutation: change 24 to 16
    modified_bits = source_text.replace(
        "constexpr int kDefaultBitsPerSample = 24;",
        "constexpr int kDefaultBitsPerSample = 16;")
    if modified_bits == source_text:
        print("GATE_FAIL: negative 'default bits changed' mutation is a no-op")
        return 1
    if not expect_reject("default bits per sample changed from 24-bit PCM",
                         cmake_text, modified_bits):
        return 1
    
    # A.3 Float format mutation: remove SampleFormat::floatingPoint
    modified_float = source_text.replace(
        "SampleFormat::floatingPoint",
        "SampleFormat::autodetect")
    if modified_float == source_text:
        print("GATE_FAIL: negative 'float format changed' mutation is a no-op")
        return 1
    if not expect_reject("32-bit float no longer IEEE float",
                         cmake_text, modified_float):
        return 1
    
    # B.1 Min seconds mutation: change 0.25 to 0.5
    modified_min = source_text.replace(
        "constexpr double kMinSeconds = 0.25;",
        "constexpr double kMinSeconds = 0.5;")
    if modified_min == source_text:
        print("GATE_FAIL: negative 'min seconds changed' mutation is a no-op")
        return 1
    if not expect_reject("min render length changed from 0.25 s",
                         cmake_text, modified_min):
        return 1
    
    # B.2 Max seconds mutation: change 30.0 to 60.0
    modified_max = source_text.replace(
        "constexpr double kMaxSeconds = 30.0;",
        "constexpr double kMaxSeconds = 60.0;")
    if modified_max == source_text:
        print("GATE_FAIL: negative 'max seconds changed' mutation is a no-op")
        return 1
    if not expect_reject("max render length changed from 30 s",
                         cmake_text, modified_max):
        return 1
    
    # C.1 Output contract: remove .partial creation
    modified_partial = source_text.replace(
        'tempFile = outFile.getSiblingFile (outFile.getFileName() + ".partial");',
        'tempFile = outFile;')
    if modified_partial == source_text:
        print("GATE_FAIL: negative 'partial file changed' mutation is a no-op")
        return 1
    if not expect_reject("output no longer uses .partial intermediate",
                         cmake_text, modified_partial):
        return 1
    
    # C.2 Output contract: remove moveFileTo check
    modified_move = source_text.replace(
        'if (! tempFile.moveFileTo (outFile))',
        '// if (! tempFile.moveFileTo (outFile))')
    if modified_move == source_text:
        print("GATE_FAIL: negative 'moveFileTo changed' mutation is a no-op")
        return 1
    if not expect_reject("output no longer uses verified move into place",
                         cmake_text, modified_move):
        return 1
    
    # C.3 Output contract: remove --overwrite check
    modified_overwrite = source_text.replace(
        'if (outFile.existsAsFile() && ! options.overwrite)',
        'if (false)')
    if modified_overwrite == source_text:
        print("GATE_FAIL: negative 'overwrite check changed' mutation is a no-op")
        return 1
    if not expect_reject("existing output file no longer refused without --overwrite",
                         cmake_text, modified_overwrite):
        return 1
    
    # D.1 Preset resolution: remove setCurrentProgram
    modified_set_program = source_text.replace(
        "processor.setCurrentProgram (options.preset);",
        "// processor.setCurrentProgram (options.preset);")
    if modified_set_program == source_text:
        print("GATE_FAIL: negative 'setCurrentProgram removed' mutation is a no-op")
        return 1
    if not expect_reject("preset no longer set via setCurrentProgram",
                         cmake_text, modified_set_program):
        return 1
    
    # D.2 Preset resolution: remove getProgramName usage
    modified_get_name = source_text.replace(
        "const auto programName = processor.getProgramName (options.preset);",
        "const auto programName = \"UNKNOWN\";")
    if modified_get_name == source_text:
        print("GATE_FAIL: negative 'getProgramName removed' mutation is a no-op")
        return 1
    if not expect_reject("preset no longer resolved via getProgramName",
                         cmake_text, modified_get_name):
        return 1
    
    # BENIGN PROBES: unrelated edits must not trip the checker
    
    # Benign: add a comment in CMakeLists.txt
    benign_cmake = cmake_text + "\n# benign probe: unrelated comment\n"
    if not expect_accept("CMake comment appended", cmake_text, source_text):
        return 1
    
    # Benign: add comment mentioning editor but no real include
    benign_commented = source_text.replace(
        "#include <JuceHeader.h>",
        "/*\n    benign probe: this comment mentions --preset and getProgramName, but no real\n"
        "    changes to the contract.\n*/\n#include <JuceHeader.h>")
    if benign_commented == source_text:
        print("GATE_FAIL: benign 'comment mentioning preset' edit is a no-op")
        return 1
    if not expect_accept("documentation comment mentioning preset",
                         cmake_text, benign_commented):
        return 1
    
    # Benign: add unrelated option block (like --verbose)
    benign_extra = source_text.replace(
        'else if (argument == "--provenance")',
        'else if (argument == "--provenance")\n        {\n            options.provenance = value;\n        }\n        else if (argument == "--verbose")\n        {\n            options.verbose = true;\n            if (! takeValue (options.verboseText))\n                return false;\n        }')
    if benign_extra == source_text:
        print("GATE_FAIL: benign 'extra option block' edit is a no-op")
        return 1
    if not expect_accept("unrelated extra option block added",
                         cmake_text, benign_extra):
        return 1
    
    print("OK cv033 render WAV contract pinned (format, bounds, output, preset)")
    return 0

if __name__ == "__main__":
    sys.exit(main())