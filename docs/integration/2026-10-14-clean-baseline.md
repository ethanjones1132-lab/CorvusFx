# Corvus integrated baseline — 2026-10-14

Integrated remote master `4e60b61` with the complete local September sprint
`8138bc6` (88 unpublished commits), retaining both histories as merge parents.
The former unrelated website branches were deleted remotely and are not part
of the audio application baseline. Original local checkout and backups remain
separate from this integration checkout.

## Conflict decisions

- Retained master's shared `dsp/CorvusEffects.h`, complete Instrument, CMake
  targets, and full DSP/instrument tests. Transferred sprint DSP changes into
  the shared header, so FX and Instrument receive the same fixes. The sprint's
  earlier zero-fingerprint scaffold is superseded by the completed fixture;
  its checker now follows that implementation and preserves mutation probes.
- Combined master's themes, parameter locks, schema tag, and non-finite-output
  safety with sprint undo gestures, meter timer/decay, MIDI locking/lifecycle,
  preset lookup correction, output-trim refresh, and A/B snapshot persistence.
- Replaced invalid sprint JUCE calls with `XmlElement::addTextElement`,
  `getAllSubText`, and `Base64::convertFromBase64` into `MemoryOutputStream`.
  Decode success, exact byte sizes, and both-slot guards must all pass.
  The editor reads persistence through a const accessor and reflects the
  recalled active slot without overwriting saved snapshots. Custom slots/maps/locks
  are decoded from the incoming XML and stripped from the parameter ValueTree
  to prevent stale duplicate metadata across repeated save/recall cycles.
- Included the unpublished `check_ab_base64_roundtrip.py`, adapting its
  payload and decode guards to actual JUCE APIs. Adapted DSP checks to shared
  header paths; instrument parameter checks include the implementation;
  sync checks recognize Windows separators and the real explicit path array.
- Added a portable source gate and actual FX session regressions. Updated the
  explicit Windows sync map for the new regression file and the working
  instructions to remove dependency on ignored local sprint tooling.

## Oversampling and waveform evidence

A naive transfer of sprint `9b2c3e7` (split FIR histories) failed normalization.
Both up/down histories retained the former shared-index schedule, leaving
unwritten up phases and overwriting down phases. Identity gain fell to 0.290867
at DC and 0.289071 at 440 Hz; this was rejected, not accepted as lower output.

The integration retains the separate histories but explicitly zero-stuffs and
scales interpolation by 2, advances/stores both decimation phases, and pairs
SSE lanes with the correct coefficient order. The coefficient sum is 1; no
arbitrary output compensation was added to the oversampler. Regression tests
failed on the naive transfer, then passed on this correction:

| Identity frequency | Original master gain | Naive split gain | Corrected gain |
| --- | ---: | ---: | ---: |
| DC | 1.000000 | 0.290867 | 1.000000 |
| 40 Hz | 0.999956 | 0.290853 | 0.999997 |
| 440 Hz | 0.994680 | 0.289071 | 0.999658 |
| 5 kHz | 0.464279 | 0.104762 | 0.955647 |

Mono/stereo maximum difference is zero and reset removes all history. The FX
processor's overall-dry and all-module-bypass paths reproduce steady-state
input within 1e-6. Filtering and nonlinear timbre change as intended; this is
not a byte-identical audio baseline.

Controlled identical-toolchain experiments show raw float hashes are affected
by both the split histories and sprint chorus/reverb changes (`751a3d2`,
`0cd68e2`, `f87e5e8`). All values below use AppleClang 14, ARM64, Release:

| DSP variant | Fixture fingerprint | Peak | RMS |
| --- | --- | ---: | ---: |
| Original master | `7e1cc9a9e30432ae` | 0.152018 | 0.0143852 |
| Naive sprint split plus all DSP fixes | `13bb4e13b41f3e3b` | 0.0147774 | 0.00139128 |
| Sprint DSP with original oversampler only | `be25262d6e14c5f8` | 0.152171 | 0.0144085 |
| Original DSP with naive split only | `4755b138cbfb55eb` | 0.0147558 | 0.00138946 |
| Final normalized integration | `e8dffa927c566497` | 0.329923 | 0.0229678 |

The former Windows digest `144377379d3ea850` is preserved as historical evidence,
not applied to a changed waveform or falsely claimed as validated. The final
raw digest is enforced only for the measured macOS ARM/AppleClang 14 toolchain;
all toolchains enforce exact repeated-render equality, finite samples, and
waveform level bounds. Windows build and reference capture remain unverified.

Restored passband gain made Ashen Sky and Cathedral Drift louder than the
original 0.07–0.13 RMS musical-level window. Following the instrument plan's
explicit measured-level normalization requirement, only their existing output
trims changed: -8.5 to -16 dB and -2 to -12 dB respectively. Waveforms,
envelopes, FX amount, and Flight values remain unchanged. Final fixture levels:

| Patch | Peak | RMS |
| --- | ---: | ---: |
| Dawn Choir | 0.356684 | 0.100796 |
| Raven Glass | 0.221076 | 0.105065 |
| Ashen Sky | 0.268547 | 0.0984241 |
| Northern Signal | 0.218501 | 0.0886116 |
| Cathedral Drift | 0.301212 | 0.0955909 |

The original RMS window remains enforced alongside non-silence, finite output,
peak bound, pairwise distinctness, and wet-vs-dry difference assertions.

## Verification and limits

- Portable source gate: all 75 checkers pass, including negative probes.
- Historical sprint harness: 34/34 grade-queue and 22/22 refill tests pass.
- CMake Release build: DSP tests, FX state tests, and both VST3 targets pass,
  using existing JUCE and ARM SSE compatibility headers outside the checkout.
- DSP/instrument tests: two consecutive runs pass with identical fingerprint
  `e8dffa927c566497` and identical patch metrics.
- Actual FX state tests: A/B slots, active slot, MIDI maps, parameter locks,
  partial/legacy session state, schema rejection, dry/bypass, and recovered-B
  editor indicators all pass. A repeated save/recall/edit/save/recall regression
  failed nine assertions before transport metadata was stripped from APVTS,
  then passed after the correction.
  An isolated build reintroducing the old XML `setText` save bug fails four
  round-trip assertions; the final source passes unchanged.
- Both generated VST3 bundles pass pluginval strictness 5 with GUI tests skipped.
  macOS-generated bundle xattrs needed removal before ad-hoc signing; cleanup
  was confined to today's generated build bundles. Plugin copy/install remains
  disabled. Windows builds and full GUI interaction checks were not performed.
