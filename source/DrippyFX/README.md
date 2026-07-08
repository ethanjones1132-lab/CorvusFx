# DrippyFX / Corvus VST — JUCE source (in-repo)

Authoritative C++ sources for the shipped **DrippyMk1** VST3 binary tracked under `drippy/NewProject.vst3/`.

| File | Role |
|------|------|
| `PluginProcessor.h` | DSP engines (`ProfessionalDistortion`, `EnhancedChorus`, `EnhancedDelay`, `UpgradedReverb`, `MasterOutputStage`) |
| `PluginProcessor.cpp` | Processor, parameters, presets, `processBlock` |
| `PluginEditor.h` / `PluginEditor.cpp` | UI (knobs, meters, layout) |
| `CMakeLists.txt` | CMake build (VST3; requires `JUCE_PATH`) |

## Build (CMake)

```bash
export JUCE_PATH="C:/Users/ethan/Downloads/juce-8.0.12-windows/JUCE"
cd "C:/Projects/Corvus VST/source/DrippyFX"
cmake -G "Visual Studio 18 2026" -A x64 -DJUCE_PATH="$JUCE_PATH" -S . -B build
cmake --build build --config Release
```

## MSBuild (local dev tree)

The Visual Studio solution and `.jucer` project may still live under:

`C:/Users/ethan/Downloads/DrippyFX_v1.0.0_Complete/NewProject/`

After editing **this** in-repo copy, sync the same files into that `DrippyFX/` folder (or edit both) before MSBuild, then deploy the built `.vst3` to `drippy/.../DrippyMk1.vst3`. See `docs/AGENTS.md` for the full pipeline and commit rules.

## Commit hygiene

Any `quality(...)` commit that updates `DrippyMk1.vst3` **must** include matching diffs under `source/DrippyFX/` so commit messages stay auditable.