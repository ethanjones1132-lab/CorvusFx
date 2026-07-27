# PRIORITIES.md — Corvus VST (DrippyFX)

> **Last updated:** 2026-07-27

## Active Priorities

| Priority | Item | Status | Notes |
|----------|------|--------|-------|
| P3 | **Undo/redo support** — undo manager for parameter changes | ⬜ Open | Phase 4, needs JUCE UndoManager integration |
| P3 | **Profile-guided optimization (PGO) build** | ⬜ Backlog | ~1% CPU savings, requires build infrastructure |
| P3 | **Dark/light theme toggle** | ⬜ Backlog | Phase 4 stretch goal |

## Completed Milestones

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
