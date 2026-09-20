# Source tracking verification (task t_b97d4512)

Date: 2026-07-08

## Baseline (before this change)

```text
git ls-tree -r HEAD --name-only | grep -E '\.(cpp|h|hpp|c)$'
# (empty — no C/C++ sources at HEAD before import)
```

```text
git log --all --diff-filter=D --summary -- '*.cpp' '*.h' '*.hpp'
# (empty — sources were never tracked, not deleted from history)
```

Tracked paths were binaries + docs only (`drippy/.../DrippyMk1.vst3`, `DrippyMk2/...`, scripts, docs).

## Actions taken

1. Imported authoritative JUCE sources from the local MSBuild tree into `source/DrippyFX/` (synced from `Downloads/.../DrippyFX/` at import time; matches deployed `DrippyMk1` era including chorus dry/wet cache in `PluginProcessor.h`).
2. Updated `docs/AGENTS.md`, `README.md`, `docs/PRIORITIES.md`, `.gitignore`, and maintenance scripts to treat `source/DrippyFX/` as git SoT and require source+binary `quality(...)` commits going forward.
3. Confirmed `.hermes/` is ignored and fleet state was removed from the index in commit `0faffac`.

## Post-import checks (run after commit)

```bash
cd "C:/Projects/Corvus VST"
git ls-tree -r HEAD --name-only | grep -E '\.(cpp|h|hpp|c)$'
# Expect: source/DrippyFX/PluginProcessor.{h,cpp}, PluginEditor.{h,cpp}

git ls-files .hermes
# Expect: (empty)

git log --oneline -3 --stat
```

## Commit hygiene (forward)

Per `docs/AGENTS.md` rule 1: any `quality(scope):` commit that touches `DrippyMk1.vst3` must include matching `source/DrippyFX/` diffs. Historical binary-only quality commits are not rewritten (out of scope).

## Corvus Instrument worktree and build handoff (2026-08-08)

The instrument vertical slice is developed in the isolated `feature/corvus-instrument-vertical-slice` worktree. Git source remains authoritative. The external JUCE tree is only a build target.

Explicit synchronization:

```powershell
.\scripts\sync_corvus_source.ps1
.\scripts\sync_corvus_source.ps1 -VerifyOnly
```

The script copies only its declared relative-path map, creates only required child directories, and compares SHA-256 for every file. It never deletes or mirrors a directory.

Release configure and test:

```powershell
& 'C:\Program Files\Microsoft Visual Studio\18\Community\Common7\IDE\CommonExtensions\Microsoft\CMake\CMake\bin\cmake.exe' `
  -G 'Visual Studio 18 2026' -A x64 `
  -DJUCE_PATH='C:\Users\ethan\Downloads\juce-8.0.12-windows\JUCE' `
  -S 'C:\Users\ethan\Downloads\DrippyFX_v1.0.0_Complete\DrippyFX' `
  -B 'C:\Users\ethan\Downloads\DrippyFX_v1.0.0_Complete\DrippyFX\build'

& 'C:\Program Files\Microsoft Visual Studio\18\Community\Common7\IDE\CommonExtensions\Microsoft\CMake\CMake\bin\cmake.exe' `
  --build 'C:\Users\ethan\Downloads\DrippyFX_v1.0.0_Complete\DrippyFX\build' `
  --config Release --target CorvusDSPTests
```

The existing FX shared-code target is named `DrippyFX`. `juce_generate_juce_header(DrippyFX)` is required because the imported source includes `JuceHeader.h`.

Baseline regression fixture:

```text
Corvus effects fingerprint: 0x144377379d3ea850
Required tolerance after shared-DSP extraction: exact fingerprint match and all samples finite.
```
