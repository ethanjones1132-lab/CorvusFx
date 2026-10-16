# PRIORITIES.md — Corvus VST (DrippyFX)

> **Last updated:** 2026-10-15 (Root planning docs refreshed to match implemented reality: Corvus Instrument vertical slice + theme toggle shipped)
> **Canonical location:** repo root. `docs/PRIORITIES.md` is a historical long-form archive (stale after 2026-07-26); do not treat it as SoT.

## Active Priorities

| Priority | Item | Status | Notes |
|----------|------|--------|-------|
| P1 | **Corvus Instrument vertical slice** | ✅ Implemented and locally verified | Design + plan landed 2026-08-08 (`docs/superpowers/specs/2026-08-08-corvus-instrument-design.md`, `docs/superpowers/plans/2026-08-08-corvus-instrument-vertical-slice.md`). Implementation exists at `source/DrippyFX/dsp/CorvusEffects.h`, `source/DrippyFX/instrument/*`, and CMake targets `DrippyFX`, `CorvusInstrument`, `CorvusDSPTests`, `CorvusFXStateTests`; plugin codes are Crvs/Cvi1 with five signature patches. Verified through the portable Mac gate (75 source checkers, portable Release build, CorvusDSPTests / CorvusFXStateTests, both AU validators, shared-effects fingerprint 0xe8dffa927c566497). Windows DAW runtime smoke and signed distribution are not claimed. · src: 1727ed9, 4a73450, docs/integration/2026-10-14-clean-baseline.md |
| P2 | **Dark/light theme toggle** | ✅ Implemented | Ctrl+T toggle, persisted preference across launches, theme-aware look-and-feel for all panels and animated background, visible THEME button in editor. Implemented in `source/DrippyFX/PluginEditor.*` · src: c5c7a8f, 7fc4bbb, fde17c2, 0549f69, 31e1e71, bb2e6b6, ea0fbd1, 82995c8, cc881e2 |
| P3 | **Profile-guided optimization (PGO) build** | ⬜ Backlog | ~1% CPU savings; requires build infrastructure · src: 4959538, ROADMAP.md |
| P3 | **Planning docs dual-tree cleanup** | 🔶 In progress | Root SoT refreshed this cycle. Optional later: archive or clearly banner `docs/{PRIORITIES,ROADMAP,AGENTS}.md` so agents stop reading stale copies. · src: 3b445e4 |

## Product lines (current)

| Product | Role | State |
|---------|------|-------|
| **Corvus FX (DrippyFX)** | Multi-FX VST3 effect | Shipping quality baseline; Phase 4 UI complete; Phase 5 CPU work largely done |
| **Corvus Instrument** | Separate synth + shared FX chain | Vertical slice implemented and locally verified: oscillator, 16-voice engine, ADSR, shared Corvus FX chain, five signature patches, deterministic tests; plugin codes Crvs/Cvi1. Mac portable gate verified; no Windows DAW runtime smoke or signed distribution claimed. |

## Completed Milestones

- ✅ Fix delay wow/flutter LFO rate bug — delta1 was (2*pi/sr)*(0.55/sr) instead of 2*pi*0.55/sr — 2026-07-29 (`4333761`)
- ✅ Hoist 7 sr-only constants from EnhancedDelay::beginBlock() to prepare() — 2026-07-29 (`b8ebf9a`)
- ✅ Hoist 6 sr-only std::exp()/block from beginBlock() to prepare() — Distortion/Chorus/Delay — 2026-07-29 (`6f94d28`)
- ✅ Compile warnings: 37 → 0 (FontOptions migration, casts, unicode fix) — 2026-07-27 (`6fa7349`)
- ✅ Randomize preset button (RND button, 23-param randomization) — 2026-07-28 (`0ceb202`)
- ✅ Undo/Redo support (Ctrl+Z/Y) — 2026-07-28 (`69f4bc1`)
- ✅ Knob right-click → MIDI learn — 2026-07-27 (`a5c09ae`)
- ✅ Preset A/B compare — 2026-07-27 (`d4f7e81`)
- ✅ All 4 saturation stages oversampled (Distortion, Chorus, Delay, Master) — 2026-07-01
- ✅ Zero per-sample transcendental calls — 2026-07-13
- ✅ Preset expansion 18→36 (CLEAN/WARM/CREATIVE/EXTREME/SIGNATURE/DREAM) — 2026-07-15
- ✅ Renamed NewProject→CorvusFX — 2026-07-03
- ✅ SSE-optimized oversampling FIR — 2026-07-09
- ✅ Click-free bypass crossfade — 2026-07-20
- ✅ Float32 LFO rotation-drift renormalization — 2026-07-20
- ✅ All 36 presets reachable via DAW host interface — 2026-07-20
- ✅ Hover tooltips activated — 2026-07-22
- ✅ Logarithmic dB scale level meters — 2026-07-20
- ✅ Master DC blocker added — 2026-07-22
- ✅ Per-sample delay_mod smoothing — 2026-07-25
- ✅ Delay ms-to-samples conversion bugfix — 2026-07-25
- ✅ Meter merge into main DSP loop — 2026-07-25
- ✅ Planning docs creation — 2026-07-26
- ✅ Per-module output clamping (Chorus/Delay) — 2026-07-26
- ✅ Equal-power reverb wet/dry crossfade — 2026-07-26 (`82a6235`)
- ✅ Cache msToSamples in ChorusBlockCoeffs (eliminates redundant double promotion in hot loop) — 2026-07-29 (`a79922c`)
- ✅ Set NEEDS_MIDI_INPUT TRUE in CMakeLists.txt for MIDI Learn VST3 compatibility — 2026-07-30 (`d61ca20`)
- ✅ Add output_trim parameter for final gain staging (0-200%, smooth, UI knob) — 2026-07-30 (`bcce791`)
- ✅ Corvus Instrument design + vertical-slice plan docs — 2026-08-08 (`e4e8c72`, `89e0d67`)
- ✅ Root planning docs refreshed to match Aug 2026 product reality — 2026-08-22
- ✅ **Corvus Instrument vertical slice implemented** — band-limited wavetable oscillator, 16-voice polyphonic engine, ADSR, shared Corvus FX chain, 5 signature patches, deterministic DSP test harness, plugin codes Crvs/Cvi1 — 2026-09-20 (`1727ed9`, `4a73450`, `docs/integration/2026-10-14-clean-baseline.md`)
- ✅ **Dark/light theme toggle implemented** — Ctrl+T toggle, persisted preference, theme-aware look-and-feel, visible THEME button, animated background follows theme — 2026-10-13/14 (`c5c7a8f`, `7fc4bbb`, `fde17c2`, `0549f69`, `31e1e71`, `bb2e6b6`, `ea0fbd1`, `82995c8`, `cc881e2`)

## Doc map (agents)

| Path | Role |
|------|------|
| `PRIORITIES.md` (root) | **SoT** ranked backlog + completed milestones |
| `ROADMAP.md` (root) | **SoT** phased plan + success metrics |
| `AGENTS.md` (root) | **SoT** working rules, paths, pitfalls |
| `docs/superpowers/specs/2026-08-08-corvus-instrument-design.md` | Instrument product design (approved) |
| `docs/superpowers/plans/2026-08-08-corvus-instrument-vertical-slice.md` | Task-level implementation plan (open checkboxes) |
| `docs/PRIORITIES.md`, `docs/ROADMAP.md`, `docs/AGENTS.md` | Historical archives — prefer root |

## Next Milestone: v1.0.0 Release (Corvus FX + Instrument)

| Item | Status | Notes |
|------|--------|-------|
| Native Windows CMake Release build + test binaries | ⬜ Pending | `scripts/verify_corvus_source.sh`, `cmake --preset windows-vs2026-release`, `CorvusDSPTests.exe`, `CorvusFXStateTests.exe` · src: backlogs/corvus.md CV-001 |
| pluginval strictness 5 on Windows VST3 bundles | ⬜ Pending | Both `CorvusFX` and `CorvusInstrument` · src: backlogs/corvus.md CV-002 |
| Vertical-slice verification report | ⬜ Pending | `docs/reports/2026-08-08-corvus-instrument-vertical-slice.md` · src: backlogs/corvus.md CV-003 |
| Source sync verification before build | ⬜ Pending | `pwsh scripts/sync_corvus_source.ps1 -VerifyOnly` · src: backlogs/corvus.md CV-005, AGENTS.md |
| **Capture final Corvus FX editor screenshot** | ⬜ Ethan-only | Replace README screenshot TODO · src: README.md, backlogs/corvus.md Ethan-only |
| **Record and publish audio demos** | ⬜ Ethan-only | Replace README demo-link TODO · src: README.md, backlogs/corvus.md Ethan-only |
| **Run Windows DAW VST3 load/play/save/reopen smoke** | ⬜ Ethan-only | Both bundles · src: docs/integration/2026-10-14-clean-baseline.md, backlogs/corvus.md Ethan-only |
| **Create and publish GitHub v1.0.0 release** | ⬜ Ethan-only | With verified binaries · src: README.md, backlogs/corvus.md Ethan-only |
| **Run PGO training profile on Windows workstation** | ⬜ Ethan-only | · src: ROADMAP.md, backlogs/corvus.md Ethan-only |