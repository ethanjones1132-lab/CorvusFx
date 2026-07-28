# AGENTS.md — Corvus VST (DrippyFX) Agent Working Rules

> **Last updated:** 2026-07-28

## Project Structure

- **Git SoT (source):** `C:\Projects\Corvus VST\source\DrippyFX\`
- **Build target:** `C:\Users\ethan\Downloads\DrippyFX_v1.0.0_Complete\DrippyFX\`
- **Git root:** `C:\Projects\Corvus VST`
- **VST3 binary:** `C:\Projects\Corvus VST\drippy\NewProject.vst3\Contents\x86_64-win\DrippyMk1.vst3`
- **VS solution:** `C:\Users\ethan\Downloads\DrippyFX_v1.0.0_Complete\NewProject\Builds\VisualStudio2026\NewProject.sln`
- **JUCE SDK:** `C:\Users\ethan\Downloads\juce-8.0.12-windows\JUCE`

## Working Rules

1. **Edit git SoT first, then sync to Downloads** — Always edit `source/DrippyFX/` and copy the 5 files to Downloads before building.
2. **One improvement per run** — Pick the highest-impact item, implement, rebuild, deploy, commit.
3. **Always sync explicitly** — `cp "$SRC/PluginProcessor.h" "$SRC/PluginProcessor.cpp" "$SRC/PluginEditor.h" "$SRC/PluginEditor.cpp" "$SRC/CMakeLists.txt" "$DST/"` — no glob.
4. **Build: SharedCode gate first** (13s), then full .sln (3min) if gate passes.
5. **Verify binary changed vs previous commit** — use `scripts/verify_drippy_binary_change.py` or manual MD5 pre-commit.
6. **Preset interop 4-way invariant** — On preset-count changes: getNumPrograms(), idToPreset[], presetToId[], presetFromId[] + guards must all stay in sync.
7. **Conventional commits:** `quality(scope): description` — what, why, impact.

## Planning Docs

- `PRIORITIES.md` — Ranked backlog and completed milestones
- `ROADMAP.md` — Phased plan with success metrics
- `AGENTS.md` — This file: working rules

## Known Pitfalls (see `maintenance-pass` skill for full list)

- Git SoT / Downloads desync causes silent build failures — sync before every build
- MSBuild incremental misses header changes — verify MD5, force rebuild if needed
- Preset array, idToPreset, presetToId, presetFromId must all grow together on expansion
- `patch` tool corrupts C++ on Windows — use binary-mode Python scripts for multi-line edits
