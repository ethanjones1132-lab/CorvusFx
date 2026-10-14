# ROADMAP.md — Corvus VST (DrippyFX)

> **Last updated:** 2026-10-14 (Corvus instrument vertical slice implemented and locally verified)
> **Canonical location:** repo root. `docs/ROADMAP.md` is a historical archive (stale after ~2026-07-11).

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

## Phase 4: UI Completeness ✅ (2026-07-26 through 2026-07-30)

- ✅ Knob right-click → MIDI learn — 2026-07-27 (`a5c09ae`)
- ✅ Preset A/B compare (snapshot/restore 23 parameters) — 2026-07-27 (`d4f7e81`)
- ✅ Combo box preset range fixed (0-29→0-42, all 36 presets reachable) — 2026-07-26 (`d9e9020`)
- ✅ Compile warnings reduced 37→0 (JUCE 8 FontOptions migration, float→int casts, unicode separators) — 2026-07-27 (`6fa7349`)
- ✅ Undo/redo support (Ctrl+Z/Y keyboard shortcuts, UndoManager) — 2026-07-28 (`69f4bc1`)
- ✅ **Randomize preset button** (RND button, 23-param randomization) — 2026-07-28 (`0ceb202`)
- ✅ **Output trim control** (per-sample smoothed, 0-200%, UI TRIM knob, MIDI learnable) — 2026-07-30 (`bcce791`)
- ⬜ Dark/light theme toggle — authorized in Vantage; waiting on product-development child permit

## Phase 5: CPU Optimization 🔶 (Mostly complete; residual backlog)

- ✅ Fix delay wow/flutter LFO rate bug (frozen LFO since 2026-07-08 API cleanup) — 2026-07-29 (`4333761`)
- ✅ Hoist 6 sr-only std::exp()/block from beginBlock() to prepare() — 2026-07-29 (`6f94d28`)
- ✅ Hoist 7 sr-only block constants from EnhancedDelay to prepare() — 2026-07-29 (`b8ebf9a`)
- ✅ Cache msToSamples in ChorusBlockCoeffs (eliminates redundant double promotion in hot loop) — 2026-07-29 (`a79922c`)
- ✅ Set NEEDS_MIDI_INPUT TRUE in CMakeLists.txt for MIDI Learn VST3 compatibility — 2026-07-30 (`d61ca20`)
- ⬜ Profile-guided optimization (PGO) build
- ⬜ SIMD for remaining hot inner loops (if profiling shows need)
- ⬜ Antiderivative antialiasing as alternative to oversampling

## Phase 6: Corvus Instrument (vertical slice implemented; future product expansion separate) ✅ Locally verified

**Status:** Design approved 2026-08-08; vertical-slice plan executed and implemented in `source/DrippyFX` on 2026-09-20. The implemented slice is verified through the portable Mac gate: 75 source checkers, portable Release build, `CorvusDSPTests` / `CorvusFXStateTests`, both AU validators, and shared-effects fingerprint `0xe8dffa927c566497`. Windows DAW runtime smoke, signed distribution, and runtime acceptance beyond the Mac portable gate are not claimed.

| Track | Target | Status |
|-------|--------|--------|
| Shared DSP extraction | `source/DrippyFX/dsp/CorvusEffects.h` behavior-preserving within `1.0e-6f` fixture tolerance | ✅ Implemented and locked (`CorvusDSPTests`) |
| FX regression lock | Deterministic JUCE unit fixture + fingerprint for existing Corvus FX | ✅ Implemented and locked (fingerprint `0xe8dffa927c566497`) |
| Instrument target | Separate VST3/Standalone synth; unique plugin codes `Crvs`/`Cvi1`; MIDI polyphony | ✅ Implemented (`CorvusInstrument`, `IS_SYNTH TRUE`) |
| First voice engine | 16-voice, band-limited oscillator, amp envelope, global Corvus FX chain | ✅ Implemented |
| Signature patches | Five atmospheric factory patches for the vertical slice | ✅ Implemented |
| Explicit out of scope (slice) | Wavetable import, granular, sampling, sequencer, arpeggiator, custom UI, unlimited modulation | — |

**Authoritative docs:**

- Design: `docs/superpowers/specs/2026-08-08-corvus-instrument-design.md`
- Plan: `docs/superpowers/plans/2026-08-08-corvus-instrument-vertical-slice.md`

**Hard constraints (from plan):** edit git SoT under `source/DrippyFX` first; explicit sync to Downloads build tree; never replace Corvus FX host identity with the instrument; effects stay global after voice mix.

## Success Metrics

| Metric | Current | Target |
|--------|---------|--------|
| Presets reachable via combo box | 36/36 | 36/36 ✅ |
| Presets reachable via DAW | 36/36 | 36/36 ✅ |
| Compile warnings | 0 | 0 ✅ |
| Per-sample transcendental calls | 0 | 0 ✅ |
| Knobs with MIDI learn | 19/19 | 19/19 ✅ |
| Block-level sr-only hoist (exp + arithmetic) | 16/16 | 16/16 ✅ |
| Root planning docs current vs product reality | refreshed 2026-10-14 | current ✅ |
| Instrument vertical slice tasks closed | 7/8 tasks implemented and portable-gate verified; Task 8 acceptance open | Task 8 open (four-target build, artifact hashes, Standalone/DAW smoke) |
