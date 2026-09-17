# AGENTS.md — Corvus VST (DrippyFX) Agent Working Rules

> **Last updated:** 2026-09-17 (paths aligned with this macOS sprint checkout)

## Project Structure

This repo is checked out on two machines; paths differ. Both point at the same
Git history — never fork the content.

### This checkout (macOS sprint box) — current working SoT

- **Repo root:** checkout root (this file's directory)
- **Git SoT (source):** `source/DrippyFX/` — the only place to edit plugin code
- **Plugin files (5):** `PluginProcessor.h`, `PluginProcessor.cpp`,
  `PluginEditor.h`, `PluginEditor.cpp`, `CMakeLists.txt` under `source/DrippyFX/`
- **Headless checks:** `scripts/check_*.py` — wired into `.sprint/verify-gate.sh`
- **Verification gate:** `bash .sprint/verify-gate.sh` (must exit 0; no full
  build on this machine)

### Windows build tree — build/deploy SoT

- **Git root:** `C:\Projects\Corvus VST`
- **Build target:** `C:\Users\ethan\Downloads\DrippyFX_v1.0.0_Complete\DrippyFX\`
- **VST3 binary:** `C:\Projects\Corvus VST\drippy\NewProject.vst3\Contents\x86_64-win\DrippyMk1.vst3`
- **VS solution:** `C:\Users\ethan\Downloads\DrippyFX_v1.0.0_Complete\NewProject\Builds\VisualStudio2026\NewProject.sln`
- **JUCE SDK:** `C:\Users\ethan\Downloads\juce-8.0.12-windows\JUCE`

On this Mac there is no Downloads/VS/JUCE tree — never invent or reference
Windows paths when editing here; full VST3 builds happen on Windows only.

## Working Rules

1. **Edit `source/DrippyFX/` first, then sync to Windows Downloads before
   building there** — copy all 5 files explicitly, no glob. On this Mac, edit
   `source/DrippyFX/` only and rely on the headless gate.
2. **One improvement per run** — Pick the highest-impact item, implement,
   rebuild (Windows), deploy, commit.
3. **Always sync explicitly (Windows)** — `cp "$SRC/PluginProcessor.h" "$SRC/PluginProcessor.cpp" "$SRC/PluginEditor.h" "$SRC/PluginEditor.cpp" "$SRC/CMakeLists.txt" "$DST/"` — no glob.
4. **Build: SharedCode gate first** (13s), then full .sln (3min) if gate passes (Windows).
5. **Verify binary changed vs previous commit** — MD5 the VST3 before/after each build (manual, no dedicated script in this repo).
6. **Preset interop 4-way invariant** — On preset-count changes: getNumPrograms(), idToPreset[], presetToId[], presetFromId[] + guards must all stay in sync (`scripts/check_preset_tables.py` verifies this in the gate).
7. **Conventional commits:** `type(scope): description` — what, why, impact.
8. **Sprint rules (this checkout):** One BACKLOG item per commit; driver owns
   git — never run `git commit`/`push`/`add`/`reset`/`rebase` yourself. See
   `.sprint/CHARTER.md`.

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
