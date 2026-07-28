# ROADMAP.md — Corvus VST (DrippyFX)

> **Last updated:** 2026-07-28

## Phase 1: Foundation ✅ (2026-06-24 through 2026-07-09)

- Block-level coefficient caching for all 4 DSP modules
- 2x oversampling for all saturation stages (zero aliasing)
- Parameter smoothing (20ms LinearSmoothedValue)
- SSE-optimized FIR filter (4x throughput on oversampling path)
- Zero per-sample transcendental calls in hot path
- Renamed "NewProject" → "CorvusFX" throughout

## Phase 2: Presets & Interop ✅ (2026-07-10 through 2026-07-15)

- Bypass buttons for all 5 modules with click-free crossfade
- 36 factory presets across 6 vibe categories
- DAW program interop (setCurrentProgram/getCurrentProgram round-trip)
- JUCE 8 API migration (AudioParameterFloatAttributes)
- Master mid/side processing (independent mid/side drive, width control)

## Phase 3: Polish & Stability ✅ (2026-07-20 through 2026-07-25)

- LFO float32 rotation-drift renormalization
- DC blocker in master output stage
- Hover tooltips activated (TooltipWindow)
- Logarithmic dB scale level meters
- Click-free bypass crossfade (real implementation, not stale comment)
- Delay ms-to-samples conversion bugfix
- All 36 presets reachable via DAW host

## Phase 4: UI Completeness 🔶 (In progress)

- ✅ Knob right-click → MIDI learn — 2026-07-27 (`a5c09ae`)
- ✅ Preset A/B compare (snapshot/restore 23 parameters) — 2026-07-27 (`d4f7e81`)
- ✅ Combo box preset range fixed (0-29→0-42, all 36 presets reachable) — 2026-07-26 (`d9e9020`)
- ✅ Compile warnings reduced 37→0 (JUCE 8 FontOptions migration, float→int casts, unicode separators) — 2026-07-27 (`6fa7349`)
- ✅ Undo/redo support (Ctrl+Z/Y keyboard shortcuts, UndoManager) — 2026-07-28 (`69f4bc1`)
- ⬜ Dark/light theme toggle (future stretch)

## Phase 5: CPU Optimization ⬜ (Backlog)

- Profile-guided optimization (PGO) build
- SIMD for remaining hot inner loops (if profiling shows need)
- Antiderivative antialiasing as alternative to oversampling

## Success Metrics

| Metric | Current | Target |
|--------|---------|--------|
| Presets reachable via combo box | 36/36 | 36/36 ✅ |
| Presets reachable via DAW | 36/36 | 36/36 ✅ |
| Compile warnings | 0 | 0 ✅ |
| Per-sample transcendental calls | 0 | 0 ✅ |
| Knobs with MIDI learn | 18/18 | 18/18 ✅ |
