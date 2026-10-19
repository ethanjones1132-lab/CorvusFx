# Corvus Instrument vertical slice — plan vs actual

**Report date:** 2026-10-18
**Status of this report:** documentation only — no build, test, or host run was
performed while writing it.

## Sources

- Plan: [`docs/superpowers/plans/2026-08-08-corvus-instrument-vertical-slice.md`](../superpowers/plans/2026-08-08-corvus-instrument-vertical-slice.md)
- Design: [`docs/superpowers/specs/2026-08-08-corvus-instrument-design.md`](../superpowers/specs/2026-08-08-corvus-instrument-design.md)
- Integration baseline (macOS ARM / AppleClang 14 evidence): [`docs/integration/2026-10-14-clean-baseline.md`](../integration/2026-10-14-clean-baseline.md)
- Release notes draft (states Windows is pending): [`docs/release/v1.0.0-notes.md`](../release/v1.0.0-notes.md)
- Repository files and git history at `HEAD` (`319f1bf`).

**Method:** the plan's deliverables were checked against files actually present
in the working tree and against statements explicitly recorded in the two
documents above. Where nothing in a document records a result, the item is
marked **unverified** rather than assumed. All checkboxes in the plan file are
still `- [ ]` (unchecked); the statuses below come from the repo and docs, not
from ticked boxes. No build, test, pluginval, or DAW/Standalone run was carried
out for this report, and **no Windows result is claimed anywhere**.

## Plan-vs-actual table

| Task | Planned deliverable / interface | Present in repo | Evidence | Status |
|---|---|---|---|---|
| 1. Test target + FX baseline fixture | `source/DrippyFX/tests/CorvusDspTests.cpp`, CMake `CorvusDSPTests` console target, `scripts/sync_corvus_source.ps1` (explicit map + `-VerifyOnly`), update `docs/SOURCE_TRACKING_VERIFICATION.md` | Yes | File exists; `CMakeLists.txt` defines `juce_add_console_app(CorvusDSPTests …)` and `CorvusDSPTestsRun`; sync script lists an explicit `relativePaths` array and hashes SHA-256 after copy; `SOURCE_TRACKING_VERIFICATION.md` has a 2026-08-08 instrument section | Implemented (source). Test execution **unverified** here |
| 2. Extract shared `dsp/CorvusEffects.h` | New `source/DrippyFX/dsp/CorvusEffects.h`; `PluginProcessor.h` keeps only processor-specific code; FX behavior preserved | Yes | `dsp/CorvusEffects.h` tracked; commit `1727ed9` shows `+1521` in the header and `-1525` in `PluginProcessor.h`; `CorvusDspTests.cpp` includes `dsp/CorvusEffects.h` | Implemented |
| 3. Band-limited wavetable oscillator | `instrument/WavetableOscillator.h` with `enum class FactoryWave { Sine, Triangle, Saw, Square }` and `prepare/setFrequency/setWave/reset/process`; 2048-sample band-limited tables | Yes | File tracked; `FactoryWave` enum and all five methods present; `tableSize = 2048`; `createTable(..., harmonicLimit)` | Implemented |
| 4. One voice + 16-voice allocation | `instrument/CorvusVoice.h`, `instrument/CorvusSynthEngine.h`; `VoiceParameters`; note-on/off, sustain, all-notes-off/panic, pitch wheel, voice stealing | Yes | Files tracked; `CorvusSynthEngine.h` has `voiceCount = 16`, `panic()`, sustain handling, `pitchBendSemitones`; tests cover stealing/sustain/panic | Implemented |
| 5. Distinct instrument processor + versioned state | `CorvusInstrumentProcessor.h/.cpp`, `CorvusInstrumentEditor.h/.cpp`; CMake target `CorvusInstrument` (`Crvs`/`Cvi1`, `IS_SYNTH TRUE`, VST3+Standalone); params `osc_wave, attack, decay, sustain, release, fx_amount, flight, output`; state root `CorvusInstrumentState`, `schemaVersion=1` | Yes | `CMakeLists.txt` lines 90–104; processor declares `stateRoot = "CorvusInstrumentState"`, `stateSchemaVersion = 1`, and all eight parameter IDs; editor wraps `juce::GenericAudioProcessorEditor` | Implemented |
| 6. Global effects chain + Flight control | One global instance per effect module; `settingsForFlight(float)` mapping; dry/wet via `fx_amount` | Yes | `CorvusInstrumentProcessor.cpp` `EffectsCore` holds one `ProfessionalDistortion`/`EnhancedChorus`/`EnhancedDelay`/`UpgradedReverb`/`MasterOutputStage`; `settingsForFlight` defined | Implemented |
| 7. Five signature patches | `instrument/CorvusInstrumentPresets.h` with exactly `Dawn Choir`, `Raven Glass`, `Ashen Sky`, `Northern Signal`, `Cathedral Drift` | Yes | `corvusInstrumentPresets` is a `std::array<InstrumentPreset, 5>` with those exact names | Implemented |
| 8. Release build, deploy, host smoke, report | Windows release VST3 + Standalone artifacts, recorded SHA-256, Standalone + DAW smoke, and `docs/reports/2026-08-08-corvus-instrument-vertical-slice.md` | Report is this file. No `CorvusInstrument.vst3` is tracked in-repo; artifacts are `TBD` in the release notes | `git ls-files drippy DrippyMk2` shows only the FX `DrippyMk1.vst3`; release notes list instrument artifact hashes as `TBD` and mark Windows builds/smoke as pending | **Partial / unverified** |

### Notes and deviations

- **Tolerance wording.** The plan's global constraint called for an
  "exact fingerprint" match within `1.0e-6f` after extraction. The integration
  document records that the fingerprint is toolchain-dependent and enforces the
  raw digest only on the measured macOS ARM / AppleClang 14 toolchain
  (`e8dffa927c566497`); all toolchains are said to enforce exact repeated-render
  equality, finite samples, and waveform level bounds. The historical Windows
  digest `0x144377379d3ea850` is retained as historical evidence only. This is a
  documented deviation from the plan's single-fingerprint wording.
- **Plan checkboxes.** The plan still shows every step unchecked, so it does not
  itself assert completion. Statuses above rest on the tracked files, commit
  `1727ed9`, and the integration/release documents.
- **Baseline docs state.** `SOURCE_TRACKING_VERIFICATION.md` still carries the
  older `0x144377379d3ea850` fingerprint text; the current test constant is
  `0xe8dffa927c566497`.
- **Windows release path.** README/PRIORITIES/release notes all describe the
  Windows build, pluginval, DAW smoke, and artifact hashes as still pending.

## Unverified list

Everything below was **not** reproduced while writing this report. Items marked
"documented" have a recorded result in `docs/integration/2026-10-14-clean-baseline.md`
(macOS ARM / AppleClang 14 only), but were not re-run:

- Windows CMake Release build of the four targets (`CorvusDSPTests`,
  `DrippyFX_VST3`, `CorvusInstrument_VST3`, `CorvusInstrument_Standalone`) — **unverified**.
- `CorvusDSPTests` execution and the deterministic fingerprint — **unverified**
  here (documented: two identical runs at `e8dffa927c566497`, macOS ARM).
- `CorvusFXStateTests` execution — **unverified** here (documented: passes,
  macOS ARM).
- Portable source gate `bash scripts/verify_corvus_source.sh` — **unverified**
  here (documented: 75 checkers pass incl. negative probes, macOS).
- pluginval strictness 5 on the Windows VST3 bundles — **unverified** for
  Windows (documented: both bundles pass with GUI tests skipped, macOS).
- DAW VST3 load / play / save / reopen smoke (both FX and Instrument) — **unverified**.
- Standalone launch and MIDI/Flight/panic smoke — **unverified**.
- Artifact provenance: SHA-256/MD5 of a built or deployed `CorvusInstrument.vst3`
  and the Standalone `.exe` — **unverified**; release notes keep them `TBD`.
- CPU / performance gates from the design ("48 kHz, 64-sample buffer, 16 active
  notes, no dropouts") — **unverified**; no measurement is recorded.
- Full GUI interaction checks — **unverified** (integration document states they
  were not performed).
- macOS support as a shipped product — not claimed (release notes: macOS not part
  of this release).
- Modulation/macro scope beyond the vertical slice (second oscillator, sub/noise,
  filter, LFOs, modulation matrix, ~24 beta presets) — **out of scope** for this
  slice; not implemented and not claimed.

## Bottom line

The Phase 2 "playable vertical slice" described by the plan is present in source:
the shared DSP core, band-limited oscillator, 16-voice engine, distinct
`CorvusInstrument` target with versioned state, global Corvus effects chain,
Flight control, and five signature patches. Its correctness is supported only by
documented macOS evidence. The Task 8 release/deploy/host-smoke items — a real
Windows build, deployed instrument artifacts with hashes, pluginval, and
DAW/Standalone smoke — remain unverified, consistent with the release notes and
`PRIORITIES.md`, which still lists this report as the pending CV-003 item.
