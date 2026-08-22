# PRIORITIES.md — Corvus VST (DrippyFX)

> **Last updated:** 2026-08-22 (Vantage product-builder — finish/update planning docs)
> **Canonical location:** repo root. `docs/PRIORITIES.md` is a historical long-form archive (stale after 2026-07-26); do not treat it as SoT.

## Active Priorities

| Priority | Item | Status | Notes |
|----------|------|--------|-------|
| P1 | **Corvus Instrument vertical slice** | 🔶 Planned | Design + plan landed 2026-08-08 (`docs/superpowers/specs/2026-08-08-corvus-instrument-design.md`, `docs/superpowers/plans/2026-08-08-corvus-instrument-vertical-slice.md`). Separate synth target; preserve FX identity; shared DSP extraction first. No implementation commits yet. |
| P2 | **Dark/light theme toggle** | ⬜ Backlog (authorized) | Vantage job `job-019ff3ae-32ca-79d0-86be-81b5e93f054b` / auth `job-authorization-01a012b7-df70-7bf0-8165-03ede607fe28` active under root-corvus-vst. No child permit currently available. Persist via existing editor state; keep preset/A-B/randomize/undo/MIDI-learn intact. |
| P3 | **Profile-guided optimization (PGO) build** | ⬜ Backlog | ~1% CPU savings; requires build infrastructure |
| P3 | **Planning docs dual-tree cleanup** | 🔶 In progress | Root SoT refreshed this cycle. Optional later: archive or clearly banner `docs/{PRIORITIES,ROADMAP,AGENTS}.md` so agents stop reading stale copies. |

## Product lines (current)

| Product | Role | State |
|---------|------|-------|
| **Corvus FX (DrippyFX)** | Multi-FX VST3 effect | Shipping quality baseline; Phase 4 UI complete; Phase 5 CPU work largely done |
| **Corvus Instrument** | Separate synth + shared FX chain | Design approved; vertical-slice plan open; not started in source |

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
- ✅ Root planning docs refreshed to match Aug 2026 product reality — 2026-08-22 (this permit)

## Doc map (agents)

| Path | Role |
|------|------|
| `PRIORITIES.md` (root) | **SoT** ranked backlog + completed milestones |
| `ROADMAP.md` (root) | **SoT** phased plan + success metrics |
| `AGENTS.md` (root) | **SoT** working rules, paths, pitfalls |
| `docs/superpowers/specs/2026-08-08-corvus-instrument-design.md` | Instrument product design (approved) |
| `docs/superpowers/plans/2026-08-08-corvus-instrument-vertical-slice.md` | Task-level implementation plan (open checkboxes) |
| `docs/PRIORITIES.md`, `docs/ROADMAP.md`, `docs/AGENTS.md` | Historical archives — prefer root |
