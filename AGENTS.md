# AGENTS.md — Corvus VST (DrippyFX) Agent Working Rules

> **Last updated:** 2026-10-14 (integrated baseline and portable verification)

## Project Structure

This repo is checked out on two machines; paths differ. Both point at the same
Git history — never fork the content.

### Source checkout — current working SoT

- **Repo root:** checkout root (this file's directory)
- **Git SoT (source):** `source/DrippyFX/` — the only place to edit plugin code
- **FX plugin files:** `PluginProcessor.h/.cpp`, `PluginEditor.h/.cpp`, and `CMakeLists.txt`
- **Shared DSP:** `dsp/CorvusEffects.h` — used by both FX and Instrument
- **Instrument and test sources:** `instrument/` and `tests/`
- **Headless checks:** `bash scripts/verify_corvus_source.sh` runs every `scripts/check_*.py`
- **Build verification:** configure CMake with a local `JUCE_PATH`, keep
  `CORVUS_COPY_PLUGIN_AFTER_BUILD=OFF`, build both VST3 targets plus
  `CorvusDSPTests` and `CorvusFXStateTests`, then run both test executables.
- macOS ARM builds require an SSE compatibility include path; Windows builds
  use native SSE. Build tools and JUCE live outside the source checkout.

### Windows build tree — build/deploy SoT

- **Git root:** `C:\Projects\Corvus VST`
- **Build target:** `C:\Users\ethan\Downloads\DrippyFX_v1.0.0_Complete\DrippyFX\`
- **VST3 binary:** `C:\Projects\Corvus VST\drippy\NewProject.vst3\Contents\x86_64-win\DrippyMk1.vst3`
- **VS solution:** `C:\Users\ethan\Downloads\DrippyFX_v1.0.0_Complete\NewProject\Builds\VisualStudio2026\NewProject.sln`
- **JUCE SDK:** `C:\Users\ethan\Downloads\juce-8.0.12-windows\JUCE`

## Working Rules

1. **Edit `source/DrippyFX/` first, then sync to Windows Downloads before
   building there** — use `scripts/sync_corvus_source.ps1` for its explicit source map and hash verification.
2. **Keep integration changes focused** — preserve branch intent and verify the resulting source and binaries.
3. **Always sync explicitly (Windows)** — use the sync script in copy mode,
   then `-VerifyOnly`; its map includes shared DSP, Instrument, and test files.
4. **Build: SharedCode gate first** (13s), then full .sln (3min) if gate passes (Windows).
5. **Verify binary changed vs previous commit** — MD5 the VST3 before/after each build (manual, no dedicated script in this repo).
6. **Preset interop 4-way invariant** — On preset-count changes: getNumPrograms(), idToPreset[], presetToId[], presetFromId[] + guards must all stay in sync (`scripts/check_preset_tables.py` verifies this in the gate).
7. **Conventional commits:** `type(scope): description` — what, why, impact.
8. The September local `.sprint/` driver is historical tooling, not required
   for this integrated baseline. Use the portable verification script above.

## Planning Docs

- `PRIORITIES.md` — Ranked backlog and completed milestones (root is SoT)
- `ROADMAP.md` — Phased plan with success metrics (root is SoT)
- `AGENTS.md` — This file: working rules
- `docs/{PRIORITIES,ROADMAP,AGENTS}.md` — historical archives; do not edit here

## Known Pitfalls

- Git SoT / Windows Downloads desync causes silent build failures — sync before every Windows build
- MSBuild incremental misses header changes — verify MD5, force rebuild if needed
- Preset array, idToPreset, presetToId, presetFromId must all grow together on expansion (machine-checked by `scripts/check_preset_tables.py`)
- `patch` tool corrupts C++ on Windows — use binary-mode Python scripts for multi-line edits over there; on this Mac the built-in patch tool works fine
- HISTORICAL: the 5 one-shot Windows migration scripts under `source/DrippyFX/scripts/` (fix_destructor.py, fix_juce8_params.py, fix_levelmeters_access.py, fix_master_mono_oversample.py, update_roadmap.py) target Windows CRLF paths and their effects are ALREADY APPLIED in this tree — kept in-tree as a record of the migration, all carrying an "ALREADY APPLIED — DO NOT RERUN" header (machine-checked by `scripts/check_win_migration_scripts_flagged.py`). Never rerun them.
