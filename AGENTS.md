# AGENTS.md — Corvus VST (DrippyFX) Agent Working Rules

> **Last updated:** 2026-11-02 (pre-build verification targets the in-repo source tree)

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

### Windows build — in-repo source tree

- **Build source:** `source/DrippyFX/` in this checkout — run
  `scripts/sync_corvus_source.ps1 -VerifyOnly` before any Windows build to
  confirm every mapped file is present, readable and hashed in this tree.
- **VST3 binary:** `C:\Projects\Corvus VST\drippy\NewProject.vst3\Contents\x86_64-win\DrippyMk1.vst3`
- **JUCE SDK:** `C:\Users\ethan\Downloads\juce-8.0.12-windows\JUCE`
- **Legacy Downloads project tree (not the build source, nothing to sync):**
  `C:\Users\ethan\Downloads\DrippyFX_v1.0.0_Complete\` (including its
  `NewProject\Builds\VisualStudio2026\NewProject.sln`) — read only when a
  destination is passed explicitly with `-DestinationRoot`.

## Working Rules

1. **Edit `source/DrippyFX/` first and verify it before any Windows build** —
   run `scripts/sync_corvus_source.ps1 -VerifyOnly`; it hashes every mapped
   file in the in-repo tree and fails on a missing mapped path. No Downloads
   copy is involved unless you pass `-DestinationRoot` explicitly.
2. **Keep integration changes focused** — preserve branch intent and verify the resulting source and binaries.
3. **Always verify explicitly before a Windows build** — `-VerifyOnly` proves
   every mapped shared DSP, Instrument, and test file exists, is readable, and
   hashes in the in-repo source tree. With `-DestinationRoot <path>` it hashes
   that copy and fails on any difference or missing file; there is no implicit
   sync target.
4. **Build: SharedCode gate first** (13s), then the full build (3min) if the gate passes (Windows).
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

- Build from the in-repo `source/DrippyFX/` tree and run `scripts/sync_corvus_source.ps1 -VerifyOnly` before every Windows build — a stale external copy is no longer the default verification target
- MSBuild incremental misses header changes — verify MD5, force rebuild if needed
- Preset array, idToPreset, presetToId, presetFromId must all grow together on expansion (machine-checked by `scripts/check_preset_tables.py`)
- `patch` tool corrupts C++ on Windows — use binary-mode Python scripts for multi-line edits over there; on this Mac the built-in patch tool works fine
- HISTORICAL: the 5 one-shot Windows migration scripts under `source/DrippyFX/scripts/` (fix_destructor.py, fix_juce8_params.py, fix_levelmeters_access.py, fix_master_mono_oversample.py, update_roadmap.py) target Windows CRLF paths and their effects are ALREADY APPLIED in this tree — kept in-tree as a record of the migration, all carrying an "ALREADY APPLIED — DO NOT RERUN" header (machine-checked by `scripts/check_win_migration_scripts_flagged.py`). Never rerun them.
