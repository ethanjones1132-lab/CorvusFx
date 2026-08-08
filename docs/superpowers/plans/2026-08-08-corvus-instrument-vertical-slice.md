# Corvus Instrument Vertical Slice Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Preserve Corvus FX behavior while extracting its reusable DSP and shipping a separate VST3/Standalone instrument vertical slice with MIDI polyphony, one band-limited oscillator, amplitude envelope, the full global Corvus effects chain, state recall, and five signature atmospheric patches.

**Architecture:** Move the existing utility and effect structs from `PluginProcessor.h` into a shared header without rewriting their algorithms, then prove the existing FX target still renders the same deterministic fixture. Add a distinct JUCE synth target with a small voice engine feeding the shared effects modules globally after voice mixing; the first editor uses JUCE's generic parameter editor so audio and host behavior are proven before custom visual work.

**Tech Stack:** C++17, JUCE 8.0.12, CMake 3.15+, Visual Studio 18 2026, VST3 and Standalone targets, JUCE UnitTest, PowerShell source synchronization, MSBuild/CMake release verification.

## Global Constraints

- Edit the git source of truth under `C:\Projects\Corvus VST\source\DrippyFX` first.
- Sync every changed source explicitly to `C:\Users\ethan\Downloads\DrippyFX_v1.0.0_Complete\DrippyFX` before building.
- Preserve the existing Corvus FX manufacturer code, plugin code, host identity, presets, and state behavior.
- Corvus Instrument uses a new plugin target and unique code; it never replaces the FX binary.
- The shared-DSP extraction must be behavior-preserving within a documented absolute tolerance of `1.0e-6f` on deterministic fixtures.
- Use test-first changes and one coherent commit per task.
- Do not add wavetable import/editing, granular playback, sampling, a sequencer, arpeggiator, custom UI, or unlimited modulation in this vertical slice.
- Keep effects global after the stereo voice mix; do not allocate delay or reverb instances per voice.
- Verify each changed binary against its build output and prior committed artifact before claiming delivery.
- Do not modify or delete existing tracked Visual Studio build artifacts outside the task's explicit files.

---

## File Structure

| Path | Responsibility |
|---|---|
| `source/DrippyFX/dsp/CorvusEffects.h` | Existing shared utility and effect structs, mechanically extracted |
| `source/DrippyFX/instrument/WavetableOscillator.h` | Band-limited factory wavetable generation and playback |
| `source/DrippyFX/instrument/CorvusVoice.h` | One MIDI voice, oscillator, ADSR, velocity, and click-free lifecycle |
| `source/DrippyFX/instrument/CorvusSynthEngine.h` | Sixteen-voice allocation, MIDI dispatch, stereo rendering, panic |
| `source/DrippyFX/instrument/CorvusInstrumentProcessor.h` | New instrument AudioProcessor and parameter/state interface |
| `source/DrippyFX/instrument/CorvusInstrumentProcessor.cpp` | Instrument render path and global effects chain |
| `source/DrippyFX/instrument/CorvusInstrumentEditor.h` | Generic-editor wrapper with stable ownership |
| `source/DrippyFX/instrument/CorvusInstrumentEditor.cpp` | Generic editor construction |
| `source/DrippyFX/tests/CorvusDspTests.cpp` | DSP extraction, oscillator, voice, state, safety, and render tests |
| `source/DrippyFX/CMakeLists.txt` | Existing FX, new instrument, and console test targets |
| `scripts/sync_corvus_source.ps1` | Explicit validated source-to-build-tree synchronization |
| `docs/SOURCE_TRACKING_VERIFICATION.md` | Updated source and binary verification map |

### Task 1: Add a deterministic JUCE test target and baseline FX fixture

**Files:**
- Create: `source/DrippyFX/tests/CorvusDspTests.cpp`
- Modify: `source/DrippyFX/CMakeLists.txt`
- Create: `scripts/sync_corvus_source.ps1`
- Modify: `docs/SOURCE_TRACKING_VERIFICATION.md`

**Interfaces:**
- Produces: `CorvusDSPTests` console target
- Produces: `renderEffectsFixture() -> std::array<float, 512>`
- Produces: PowerShell sync command with explicit source map and `-VerifyOnly`

- [ ] **Step 1: Add a failing test-target smoke**

Create a JUCE `UnitTest` named `CorvusEffectsBaselineTest` that includes `PluginProcessor.h`, renders a deterministic stereo impulse through `ProfessionalDistortion`, `EnhancedChorus`, `EnhancedDelay`, `UpgradedReverb`, and `MasterOutputStage`, and asserts every sample is finite. Add a second assertion against a fixture hash constant initialized to an intentionally wrong value.

```cpp
class CorvusEffectsBaselineTest final : public juce::UnitTest
{
public:
    CorvusEffectsBaselineTest() : juce::UnitTest("Corvus effects baseline") {}
    void runTest() override
    {
        beginTest("deterministic fixture remains finite");
        const auto output = renderEffectsFixture();
        for (const auto sample : output)
            expect(std::isfinite(sample));
        beginTest("fixture fingerprint");
        expectEquals(fingerprint(output), uint64_t{0});
    }
};
```

- [ ] **Step 2: Add the console test target**

Add `juce_add_console_app(CorvusDSPTests PRODUCT_NAME "Corvus DSP Tests")`, `juce_generate_juce_header(CorvusDSPTests)`, the test source, include directories, and links to `juce::juce_audio_utils`, `juce::juce_dsp`, and recommended config flags. The test `main()` runs all registered tests and returns nonzero when any result fails.

- [ ] **Step 3: Write the explicit sync script**

The script accepts `-VerifyOnly`, validates the source and destination roots, uses an explicit relative-path array, creates only required destination directories, copies with `Copy-Item -LiteralPath`, and compares SHA-256 after copying. It must not delete or mirror entire directories.

- [ ] **Step 4: Configure and run the test to verify the fingerprint failure**

Run:

```powershell
.\scripts\sync_corvus_source.ps1
& 'C:\Program Files\Microsoft Visual Studio\18\Community\Common7\IDE\CommonExtensions\Microsoft\CMake\CMake\bin\cmake.exe' `
  -G 'Visual Studio 18 2026' -A x64 `
  -DJUCE_PATH='C:\Users\ethan\Downloads\juce-8.0.12-windows\JUCE' `
  -S 'C:\Users\ethan\Downloads\DrippyFX_v1.0.0_Complete\DrippyFX' `
  -B 'C:\Users\ethan\Downloads\DrippyFX_v1.0.0_Complete\DrippyFX\build'
& 'C:\Program Files\Microsoft Visual Studio\18\Community\Common7\IDE\CommonExtensions\Microsoft\CMake\CMake\bin\cmake.exe' `
  --build 'C:\Users\ethan\Downloads\DrippyFX_v1.0.0_Complete\DrippyFX\build' `
  --config Release --target CorvusDSPTests
```

Expected: build succeeds; test executable fails only at the intentionally wrong fingerprint.

- [ ] **Step 5: Capture and lock the real baseline fingerprint**

Replace `uint64_t{0}` with the printed deterministic fingerprint, run the test twice, and require both runs to pass with the same value.

- [ ] **Step 6: Commit the baseline harness**

```powershell
git add source/DrippyFX/tests/CorvusDspTests.cpp source/DrippyFX/CMakeLists.txt scripts/sync_corvus_source.ps1 docs/SOURCE_TRACKING_VERIFICATION.md
git commit -m "test(corvus): lock deterministic effects baseline"
```

### Task 2: Extract the shared Corvus effects header without behavior changes

**Files:**
- Create: `source/DrippyFX/dsp/CorvusEffects.h`
- Modify: `source/DrippyFX/PluginProcessor.h`
- Modify: `source/DrippyFX/tests/CorvusDspTests.cpp`
- Modify: `scripts/sync_corvus_source.ps1`

**Interfaces:**
- Produces unchanged global types: `DCBlocker`, `OnePole`, `Oversampling2x`, `ProfessionalDistortion`, `EnhancedChorus`, `EnhancedDelay`, `UpgradedReverb`, `MasterOutputStage`
- Preserves: `hermiteInterp`, `padeTanh`, and `padeSoftClip`

- [ ] **Step 1: Add a compile-time shared-header test**

Change the test include from `PluginProcessor.h` to `dsp/CorvusEffects.h`. Run the test build before creating the header.

Expected: compile failure because `dsp/CorvusEffects.h` does not exist.

- [ ] **Step 2: Mechanically move the DSP section**

Move the utility functions and structs currently occupying `PluginProcessor.h` lines 11-1522 into `dsp/CorvusEffects.h`. Retain the same includes, definitions, order, names, access, constants, and comments. Add `#include "dsp/CorvusEffects.h"` to `PluginProcessor.h`; leave only processor-specific includes and `CorvusFXAudioProcessor` in that file.

- [ ] **Step 3: Update the explicit sync map**

Add `dsp/CorvusEffects.h` to the sync script and run both copy and `-VerifyOnly` modes.

- [ ] **Step 4: Run extraction verification**

Run the console tests and the existing FX release build. Required results: baseline fingerprint unchanged, all samples finite, FX build succeeds, and `git diff --check` reports no whitespace errors.

- [ ] **Step 5: Commit the extraction**

```powershell
git add source/DrippyFX/dsp/CorvusEffects.h source/DrippyFX/PluginProcessor.h source/DrippyFX/tests/CorvusDspTests.cpp scripts/sync_corvus_source.ps1
git commit -m "refactor(dsp): extract shared Corvus effects core"
```

### Task 3: Implement a band-limited factory wavetable oscillator

**Files:**
- Create: `source/DrippyFX/instrument/WavetableOscillator.h`
- Modify: `source/DrippyFX/tests/CorvusDspTests.cpp`
- Modify: `scripts/sync_corvus_source.ps1`

**Interfaces:**
- Produces: `enum class FactoryWave { Sine, Triangle, Saw, Square }`
- Produces: `WavetableOscillator::prepare(double sampleRate)`
- Produces: `WavetableOscillator::setFrequency(float hz)`
- Produces: `WavetableOscillator::setWave(FactoryWave wave)`
- Produces: `WavetableOscillator::reset(float phase = 0.0f)`
- Produces: `WavetableOscillator::process() -> float`

- [ ] **Step 1: Write failing frequency, range, and determinism tests**

Render one second at 48 kHz. Count positive-going zero crossings for A4 and require `440 ± 1`. Require all samples finite and inside `[-1.01, 1.01]`. Reset two oscillators to the same phase and require sample equality within `1.0e-7f`.

- [ ] **Step 2: Build tests and verify compile failure**

Expected: `WavetableOscillator` is undefined.

- [ ] **Step 3: Implement mipmapped factory tables**

Generate power-of-two 2048-sample tables at construction. Build progressively band-limited tables by capping harmonics per octave, select the table from fundamental frequency, and use linear interpolation between adjacent samples. Clamp invalid frequency to zero output and reject non-positive sample rates in `prepare` with `jassertfalse` plus safe silence.

- [ ] **Step 4: Run oscillator tests and a high-note alias sanity test**

The high-note test compares total energy outside the expected harmonic bins against a naive saw fixture and requires the band-limited oscillator to be lower.

- [ ] **Step 5: Commit the oscillator**

```powershell
git add source/DrippyFX/instrument/WavetableOscillator.h source/DrippyFX/tests/CorvusDspTests.cpp scripts/sync_corvus_source.ps1
git commit -m "feat(instrument): add band-limited wavetable oscillator"
```

### Task 4: Implement one voice and sixteen-voice MIDI allocation

**Files:**
- Create: `source/DrippyFX/instrument/CorvusVoice.h`
- Create: `source/DrippyFX/instrument/CorvusSynthEngine.h`
- Modify: `source/DrippyFX/tests/CorvusDspTests.cpp`
- Modify: `scripts/sync_corvus_source.ps1`

**Interfaces:**
- Consumes: `WavetableOscillator`
- Produces: `VoiceParameters { attackSeconds, decaySeconds, sustainLevel, releaseSeconds, wave }`
- Produces: `CorvusVoice::startNote(note, velocity, params, age)`
- Produces: `CorvusVoice::stopNote(allowTailOff)`
- Produces: `CorvusVoice::render(left, right, start, count)`
- Produces: `CorvusSynthEngine::prepare(sampleRate, maxBlockSize)`
- Produces: `CorvusSynthEngine::render(buffer, midi, params)`
- Produces: `CorvusSynthEngine::panic()`

- [ ] **Step 1: Write failing note lifecycle tests**

Test A4 frequency, velocity scaling, release reaching silence, all-notes-off, sustain-pedal release, no stuck notes, and finite stereo output.

- [ ] **Step 2: Write a failing deterministic voice-stealing test**

Start 17 notes without releases. Require the seventeenth note to steal the oldest released voice if one exists; otherwise require it to steal the voice with the smallest age counter.

- [ ] **Step 3: Run tests and verify compile failure**

Expected: voice and engine types are undefined.

- [ ] **Step 4: Implement the voice**

Use `juce::ADSR` for amplitude, MIDI-to-Hz conversion through `juce::MidiMessage::getMidiNoteInHertz`, equal-power stereo pan at center, and a 32-sample de-click ramp when a live voice is stolen.

- [ ] **Step 5: Implement the allocator and MIDI dispatch**

Preallocate exactly 16 voices. Process MIDI events at sample offsets by rendering spans between events. Handle note-on, note-off, sustain controller 64, all-notes-off, all-sound-off, and pitch wheel. `panic()` immediately resets voices and clears sustain state.

- [ ] **Step 6: Run voice and allocator tests**

Expected: all lifecycle, stealing, sustain, panic, and finite-output tests pass.

- [ ] **Step 7: Commit the playable engine**

```powershell
git add source/DrippyFX/instrument/CorvusVoice.h source/DrippyFX/instrument/CorvusSynthEngine.h source/DrippyFX/tests/CorvusDspTests.cpp scripts/sync_corvus_source.ps1
git commit -m "feat(instrument): add polyphonic Corvus voice engine"
```

### Task 5: Add the distinct Corvus Instrument processor and state

**Files:**
- Create: `source/DrippyFX/instrument/CorvusInstrumentProcessor.h`
- Create: `source/DrippyFX/instrument/CorvusInstrumentProcessor.cpp`
- Create: `source/DrippyFX/instrument/CorvusInstrumentEditor.h`
- Create: `source/DrippyFX/instrument/CorvusInstrumentEditor.cpp`
- Modify: `source/DrippyFX/CMakeLists.txt`
- Modify: `source/DrippyFX/tests/CorvusDspTests.cpp`
- Modify: `scripts/sync_corvus_source.ps1`

**Interfaces:**
- Consumes: `CorvusSynthEngine` and shared effects structs
- Produces: `CorvusInstrumentProcessor : juce::AudioProcessor`
- Produces parameter IDs: `osc_wave`, `attack`, `decay`, `sustain`, `release`, `fx_amount`, `flight`, `output`
- Produces state root: `CorvusInstrumentState` with integer `schemaVersion=1`

- [ ] **Step 1: Write failing processor-identity and state tests**

Require stereo output with no input bus, MIDI acceptance, non-MIDI-effect identity, synth behavior, parameter existence, and a state round trip that restores every parameter exactly within APVTS normalization tolerance.

- [ ] **Step 2: Add the new JUCE target**

Configure `CorvusInstrument` with manufacturer code `Crvs`, plugin code `Cvi1`, `IS_SYNTH TRUE`, `NEEDS_MIDI_INPUT TRUE`, `NEEDS_MIDI_OUTPUT FALSE`, `FORMATS VST3 Standalone`, product name `Corvus Instrument`, and VST3 categories `Instrument` and `Synth`. Leave the existing `DrippyFX` target fields unchanged.

- [ ] **Step 3: Implement the processor and generic editor wrapper**

Use an APVTS with the eight vertical-slice parameters. `processBlock` clears unsupported channels, renders the synth into stereo, applies the global effects chain, clamps non-finite samples to silence, and applies a smoothed final output control. `createEditor` returns a stable wrapper around `juce::GenericAudioProcessorEditor`.

- [ ] **Step 4: Implement versioned state**

Serialize the APVTS tree with `schemaVersion=1`. Reject XML or binary data with the wrong root or unsupported version and leave the current state unchanged.

- [ ] **Step 5: Build and run processor tests**

Expected: both `DrippyFX_VST3` and `CorvusInstrument_VST3` build, state tests pass, and the two targets expose different plugin codes.

- [ ] **Step 6: Commit the distinct instrument target**

```powershell
git add source/DrippyFX/instrument source/DrippyFX/CMakeLists.txt source/DrippyFX/tests/CorvusDspTests.cpp scripts/sync_corvus_source.ps1
git commit -m "feat(instrument): add distinct Corvus synth target"
```

### Task 6: Wire the full global Corvus effects chain and Flight control

**Files:**
- Modify: `source/DrippyFX/instrument/CorvusInstrumentProcessor.h`
- Modify: `source/DrippyFX/instrument/CorvusInstrumentProcessor.cpp`
- Modify: `source/DrippyFX/tests/CorvusDspTests.cpp`

**Interfaces:**
- Consumes: shared `ProfessionalDistortion`, `EnhancedChorus`, `EnhancedDelay`, `UpgradedReverb`, `MasterOutputStage`
- Produces: `InstrumentEffectsSettings CorvusInstrumentProcessor::settingsForFlight(float flight) const`
- Produces: one global effects instance per module

- [ ] **Step 1: Write failing dry/wet and safety tests**

At `fx_amount=0`, require instrument output to match the dry synth fixture within `1.0e-6f`. At `fx_amount=1` and `flight=1`, require output to differ materially while remaining finite and below the documented safety clamp. Sweep Flight through 257 values and require no non-finite sample or discontinuity above the de-click threshold.

- [ ] **Step 2: Run tests and verify the wet-path assertions fail**

- [ ] **Step 3: Implement the global chain**

Prepare one instance of every existing effect module. Reuse the FX processor's safe parameter ranges and begin-block ordering. Mix dry and processed output through a smoothed `fx_amount` control.

- [ ] **Step 4: Implement the vertical-slice Flight mapping**

Map Flight monotonically across distortion amount, chorus depth/mix, delay mix/modulation, reverb size/mix/modulation, master width, and master drive. Clamp every derived parameter before passing it to shared DSP. Flight does not alter oscillator pitch or amplitude in this slice.

- [ ] **Step 5: Run all DSP tests and both release builds**

Expected: baseline FX fingerprint unchanged, instrument dry match passes, wet output differs, Flight sweep remains finite, and both plugin targets build.

- [ ] **Step 6: Commit the effects-native signal path**

```powershell
git add source/DrippyFX/instrument/CorvusInstrumentProcessor.h source/DrippyFX/instrument/CorvusInstrumentProcessor.cpp source/DrippyFX/tests/CorvusDspTests.cpp
git commit -m "feat(instrument): route voices through Corvus effects"
```

### Task 7: Add five signature patches and host program behavior

**Files:**
- Create: `source/DrippyFX/instrument/CorvusInstrumentPresets.h`
- Modify: `source/DrippyFX/instrument/CorvusInstrumentProcessor.h`
- Modify: `source/DrippyFX/instrument/CorvusInstrumentProcessor.cpp`
- Modify: `source/DrippyFX/tests/CorvusDspTests.cpp`
- Modify: `scripts/sync_corvus_source.ps1`

**Interfaces:**
- Produces: `InstrumentPreset { name, wave, attack, decay, sustain, release, fxAmount, flight, output }`
- Produces programs: `Dawn Choir`, `Raven Glass`, `Ashen Sky`, `Northern Signal`, `Cathedral Drift`

- [ ] **Step 1: Write failing program and level tests**

Require exactly five programs, stable names and indices, deterministic recall, state round trip after recall, non-silent A3 chord output, finite samples, and peak output at or below the safety target.

- [ ] **Step 2: Run tests and verify program-count failure**

- [ ] **Step 3: Implement the five presets**

Author distinct envelope, waveform, FX amount, Flight, and output settings for the five named patches. Normalize perceived level by measured peak and RMS rather than by arbitrary gain copying.

- [ ] **Step 4: Render dry and wet fixtures for every patch**

Require every wet fixture to differ from its dry source and every pair of wet presets to differ by more than the deterministic similarity threshold.

- [ ] **Step 5: Commit the signature bank**

```powershell
git add source/DrippyFX/instrument/CorvusInstrumentPresets.h source/DrippyFX/instrument/CorvusInstrumentProcessor.h source/DrippyFX/instrument/CorvusInstrumentProcessor.cpp source/DrippyFX/tests/CorvusDspTests.cpp scripts/sync_corvus_source.ps1
git commit -m "feat(instrument): add five Corvus signature patches"
```

### Task 8: Release-build, deploy, and real host smoke

**Files:**
- Modify: `docs/SOURCE_TRACKING_VERIFICATION.md`
- Modify: `README.md`
- Create: `docs/reports/2026-08-08-corvus-instrument-vertical-slice.md`

**Interfaces:**
- Produces: release VST3 and Standalone artifacts for Corvus Instrument
- Preserves: existing `DrippyMk1.vst3` artifact and hash unless the behavior-preserving refactor rebuild intentionally changes binary layout

- [ ] **Step 1: Run the full source and test gate**

```powershell
.\scripts\sync_corvus_source.ps1 -VerifyOnly
& 'C:\Program Files\Microsoft Visual Studio\18\Community\Common7\IDE\CommonExtensions\Microsoft\CMake\CMake\bin\cmake.exe' `
  --build 'C:\Users\ethan\Downloads\DrippyFX_v1.0.0_Complete\DrippyFX\build' `
  --config Release --target CorvusDSPTests DrippyFX_VST3 CorvusInstrument_VST3 CorvusInstrument_Standalone
& 'C:\Users\ethan\Downloads\DrippyFX_v1.0.0_Complete\DrippyFX\build\CorvusDSPTests_artefacts\Release\Corvus DSP Tests.exe'
git diff --check
```

Expected: all builds and tests pass with zero whitespace errors.

- [ ] **Step 2: Verify artifact provenance**

Record SHA-256 for the CMake build output, deployed VST3 copy, Standalone executable, and existing Corvus FX artifact. Confirm the deployed instrument hash equals the build output hash.

- [ ] **Step 3: Run the Standalone smoke**

Launch the real release Standalone executable, confirm the window opens, load all five patches, play MIDI through an available visible input or the JUCE on-screen keyboard, exercise Flight, press panic, and exit cleanly. Record observable results without accessing hidden session data.

- [ ] **Step 4: Run a real DAW VST3 smoke**

Open an available DAW, scan the new VST3, instantiate Corvus Instrument on an instrument track, play and release a chord, save the project, reopen it, and verify patch/state recall. Also instantiate Corvus FX on an audio track to confirm its identity still resolves separately.

- [ ] **Step 5: Write the vertical-slice report**

Record commands, test count, hashes, artifact paths, host identity, state-recall result, patch names, CPU observation, and any remaining beta blockers. Do not claim commercial release readiness.

- [ ] **Step 6: Commit verified vertical-slice documentation**

```powershell
git add README.md docs/SOURCE_TRACKING_VERIFICATION.md docs/reports/2026-08-08-corvus-instrument-vertical-slice.md
git commit -m "docs(instrument): verify Corvus vertical slice"
```
