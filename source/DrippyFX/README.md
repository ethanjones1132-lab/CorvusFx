# Corvus FX / Corvus Instrument — JUCE source

This directory contains the tracked source and CMake configuration for the
**Corvus FX** effect and **Corvus Instrument** synth. The current CMake product
names are `Corvus FX` and `Corvus Instrument`; the FX CMake target remains
`DrippyFX` for plugin identity stability. Configured targets are not evidence
that binaries have been built or packaged. No v1.0.0 distributable is currently
available.

| File | Role |
|------|------|
| `PluginProcessor.h` | DSP engines (`ProfessionalDistortion`, `EnhancedChorus`, `EnhancedDelay`, `UpgradedReverb`, `MasterOutputStage`) |
| `PluginProcessor.cpp` | Processor, parameters, presets, `processBlock` |
| `PluginEditor.h` / `PluginEditor.cpp` | UI (knobs, meters, layout) |
| `CMakeLists.txt` | CMake build configuration (requires `JUCE_PATH`) |

## Build (CMake)

```bash
export JUCE_PATH="/path/to/JUCE"
cd path/to/repository/source/DrippyFX
cmake -G "Visual Studio 18 2026" -A x64 -DJUCE_PATH="$JUCE_PATH" -S . -B build
cmake --build build --config Release
```

The CMake configuration declares FX VST3/AU/Standalone formats and Instrument
VST3/Standalone formats. The FX VST3 product name is `Corvus FX`; the Instrument
product name is `Corvus Instrument`. No archive/package format or deployed
artifact filename is defined here. See the root README and draft release notes
for current availability and verification status.

## Commit hygiene

The tracked legacy `DrippyMk1.vst3` is not the output of this CMake
configuration. Do not treat it as a current Corvus FX release artifact or
rename it based on the CMake product name.
