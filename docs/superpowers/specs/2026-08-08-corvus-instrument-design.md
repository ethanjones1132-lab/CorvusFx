# Corvus Instrument Design

**Date:** 2026-08-08

**Status:** Approved product design

**Product center:** Atmospheric, cinematic, and evolving motion

**Architecture:** Separate instrument plugin sharing the Corvus effects DSP core.

## Objective

Create a sellable software instrument that turns simple oscillator sources into finished, expressive, moving sounds through the existing Corvus distortion, chorus, delay, reverb, and master architecture.

Corvus Instrument is not intended to match broad flagship synthesizers feature for feature. Its advantage is immediacy: musicians should reach a distinctive, mix-ready moving sound without first becoming synthesis experts.

## Current-state constraint

Corvus FX is currently an audio effect:

- The JUCE target is configured with `IS_SYNTH FALSE`.
- MIDI input supports controller learn rather than note-driven voice generation.
- The processor consumes an audio buffer and applies a global cascade of five effects modules.
- DSP classes and processor responsibilities are concentrated in the current processor files.

Adding note synthesis directly to the existing plugin would mix two host identities, complicate state and I/O behavior, and risk existing DAW sessions. The design therefore preserves Corvus FX and creates a separate instrument target.

## Selected architecture

The repository will expose three boundaries:

### Corvus DSP core

A shared internal library containing the reusable distortion, chorus, delay, reverb, master-output, oversampling, interpolation, smoothing, and safety utilities.

The extraction must preserve the current Corvus FX sound. Refactoring is complete only when deterministic audio fixtures show equivalent output within an explicitly documented floating-point tolerance.

### Corvus FX

The existing audio-effect target remains an effect with its current plugin identity, input behavior, state compatibility, and preset behavior. Existing users and DAW sessions must not be silently migrated to the instrument.

### Corvus Instrument

A new JUCE instrument target with:

- A distinct plugin identifier and product name.
- `IS_SYNTH TRUE` and MIDI note input.
- Stereo output without required audio input.
- Its own parameter layout, state format, presets, editor, validation, packaging, and release history.
- A global Corvus effects chain after the polyphonic voice mix.

## Signal path

```text
MIDI notes and expression
  -> polyphonic voice allocation
  -> oscillator A + oscillator B + sub/noise
  -> per-voice multimode filter
  -> per-voice amplitude envelope
  -> stereo voice mix
  -> Corvus distortion
  -> Corvus chorus
  -> Corvus delay
  -> Corvus reverb
  -> Corvus master output and safety limiting
```

The Corvus effects remain global rather than duplicated per voice. This preserves their cohesive mix behavior and prevents polyphony from multiplying the most expensive effects processing.

## First sellable scope

### Voice engine

- Sixteen-note maximum polyphony.
- Deterministic oldest-released voice stealing, falling back to oldest active voice.
- Note-on, note-off, sustain pedal, all-notes-off, and panic behavior.
- Pitch bend, velocity, channel pressure, mod wheel, and glide.
- Click-free voice start, release, and stealing.

### Oscillators

- Two band-limited wavetable oscillators.
- Curated factory wavetable set with visible waveform and position control.
- Octave, semitone, fine tune, phase, level, pan, and wavetable position.
- One to four unison voices with detune and stereo spread.
- Sub oscillator with sine and square choices.
- Noise source with level and color control.

The first version does not include wavetable importing, drawing, resynthesis, granular playback, or sample playback.

### Filter and envelopes

- One per-voice state-variable filter.
- Low-pass, band-pass, and high-pass modes.
- Cutoff, resonance, drive, key tracking, and envelope amount.
- One amplitude ADSR.
- One modulation ADSR.

### Modulation

- Two tempo-syncable LFOs with sine, triangle, saw, ramp, and square shapes.
- Eight explicit modulation slots.
- Sources: modulation envelope, LFO 1, LFO 2, velocity, pressure, mod wheel, and note tracking.
- Destinations limited to documented synth and effects parameters that can be modulated safely.
- Per-slot depth with bipolar display.

Per-note sources such as velocity, pressure, note tracking, and the modulation envelope may target only per-voice oscillator and filter parameters. Global effects parameters may be targeted only by global LFOs and performance macros. This prevents one voice from unpredictably changing the shared effects state for every other voice.

The first version does not provide unlimited routing, arbitrary audio-rate modulation, or user scripting.

### Performance macros

Every preset includes four performance macros.

- Macro 1 is always **Flight**.
- Flight maps up to eight preset-authored destinations across oscillator, filter, motion, and effects parameters.
- The remaining three macros receive concise preset-specific names and may each map up to six destinations.
- Macro movement must be smooth, bounded, and free of unsafe feedback or output jumps.

Flight is the defining interaction: one gesture should move a patch through a musically coherent transformation such as clean to distorted, narrow to wide, immediate to distant, or stable to animated.

### Effects

The instrument exposes the complete Corvus chain:

- Distortion.
- Chorus.
- Delay.
- Reverb.
- Master output.

Each module retains click-free bypass and safe smoothing. Instrument presets store complete synth, modulation, macro, and effects state.

## Presets and sonic identity

The external beta includes approximately 24 high-quality presets divided across:

- Evolving pads.
- Cinematic atmospheres.
- Motion textures.
- Expressive keys and plucks.
- Supporting basses.
- Supporting leads.

The initial identity centers atmospheric, cinematic, and evolving motion. Bass and lead capability demonstrates range but does not control the positioning.

Existing Corvus FX presets may supply effects settings, but they are not instrument presets and will not be presented as such without oscillator, envelope, macro, level, and playability design.

## Editor design

The first editor uses a clear single-window hierarchy:

1. Preset, master level, polyphony, panic, and global controls.
2. Oscillator A and B panels with waveform visualization.
3. Sub/noise, filter, envelopes, and LFOs.
4. Flight and three additional performance macros in a persistent center strip.
5. The five color-coded Corvus effects modules.
6. A compact modulation assignment view.

The editor should feel visually immediate and responsive without imitating another product's trade dress. Detailed visual exploration occurs after the audio vertical slice proves the instrument concept.

## Compatibility and migration

- Preserve the existing Corvus FX plugin identifier.
- Assign Corvus Instrument a new identifier.
- Keep FX and instrument preset namespaces separate.
- Version the instrument state from its first release.
- Reject malformed state safely and retain the current patch.
- Provide explicit migrations for future instrument-state versions.
- Validate that extracting shared DSP does not change existing FX preset output unexpectedly.

## Licensing and packaging gate

Corvus FX is currently presented as MIT-licensed and open source. Before commercial distribution, confirm ownership and contribution history, then choose an explicit licensing boundary for the shared DSP and instrument-specific source. The commercial artifact, installer, end-user terms, support policy, and update policy must agree with that decision.

This is a release gate, not a reason to delay the audio vertical slice.

## Error and safety behavior

- Panic immediately releases or resets all voices without leaving stuck notes.
- Invalid MIDI data is ignored safely.
- Sample-rate or block-size changes reinitialize affected DSP without stale buffers.
- NaN or infinite samples trigger a bounded reset and silence rather than propagating.
- Feedback parameters remain inside proven safe limits under modulation and macro control.
- Preset changes are click-free or explicitly fade through a safe transition.
- Output limiting prevents unsafe full-scale bursts during voice stealing, unison changes, and preset recall.

## Delivery sequence

### Phase 1: behavior-preserving DSP boundary

Extract the reusable effects core and prove Corvus FX output equivalence. Preserve the existing plugin identity and preset behavior.

### Phase 2: playable vertical slice

Implement one band-limited oscillator, MIDI note lifecycle, polyphony, amplitude envelope, stereo mix, and the shared global effects chain. Produce five signature patches before expanding features.

### Phase 3: first sellable engine

Add the second oscillator, sub/noise, filter, modulation envelope, LFOs, eight-slot modulation, unison, expression, glide, and Flight macros.

### Phase 4: editor and sound library

Build the focused editor, complete approximately 24 beta presets, and produce dry-versus-Corvus audio demonstrations.

### Phase 5: external validation and release hardening

Distribute to at least three outside musicians, resolve installation and playability blockers, validate in real DAWs, complete packaging and licensing decisions, and prepare the commercial release.

## Verification

### Automated DSP and state tests

- Oscillator frequency and phase behavior at multiple sample rates.
- Band-limiting and aliasing checks across the MIDI range.
- Note-on, note-off, sustain, panic, and voice-stealing lifecycle.
- Envelope and LFO timing, including tempo synchronization.
- Modulation and macro bounds.
- No NaN, infinite, or denormal propagation.
- State save/load round trips.
- Corvus FX behavior-equivalence fixtures after shared-core extraction.

### Performance gates

- Stable operation at 48 kHz with a 64-sample buffer.
- Sixteen active notes without dropouts on the supported Windows baseline.
- Predictable CPU scaling for unison and oversampling.
- No output burst during worst-case preset, voice-steal, or panic transitions.

### Host and release gates

- Plugin validation passes for both FX and instrument targets.
- VST3 loads, saves, recalls, automates, and unloads correctly in real DAWs.
- Existing Corvus FX sessions continue to resolve the FX plugin.
- A clean-machine installation smoke succeeds.
- Audio demos clearly communicate the product without technical narration.

## Product proof

The design advances beyond beta only when:

- Five signature patches sound materially more distinctive than their dry sources.
- Three outside musicians install and record something useful without direct guidance.
- The Flight interaction is understood without a tutorial.
- External feedback supports the atmospheric, cinematic, and evolving-motion position.
- At least one musician demonstrates payment intent through a purchase, preorder, or explicit price-qualified commitment.

The product succeeds when Corvus is chosen for fast, expressive moving sounds rather than compared feature by feature with general-purpose synthesizers.
