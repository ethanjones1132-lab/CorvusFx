<div align="center">

# Corvus FX

**A studio-grade VST3 multi-effects suite** — Distortion · Chorus · Delay · Reverb · Master Output

Built with [JUCE 8](https://juce.com) for Windows (x64). Free and open-source.

[![Release](https://img.shields.io/github/v/release/ethanjones1132-lab/CorvusFx?color=8A2BE2&label=version)](https://github.com/ethanjones1132-lab/CorvusFx/releases)
[![Downloads](https://img.shields.io/github/downloads/ethanjones1132-lab/CorvusFx/total?color=blue)](https://github.com/ethanjones1132-lab/CorvusFx/releases)
[![JUCE](https://img.shields.io/badge/JUCE-8.0.12-00B4D8)](https://juce.com)
[![C++](https://img.shields.io/badge/C%2B%2B-17-00599C)](https://isocpp.org)
[![License](https://img.shields.io/badge/license-MIT-green)](LICENSE)
[![Platform](https://img.shields.io/badge/platform-Windows%20x64-0078D7)]()

</div>

---

## Overview

Corvus FX is a **5-module cascade VST3 plugin** that chains **Distortion → Chorus → Delay → Reverb → Master Output** in a single, efficient processing pass. Each module has independent controls and a **click-free bypass button**, with **36 factory presets** organized into six categories — from subtle bus glue to massive ambient textures.

Whether you're a producer looking for analog-style warmth, a sound designer chasing otherworldly modulation, or a mixing engineer wanting a cohesive channel strip, Corvus FX delivers transparent, musical processing with **zero compromise on audio quality**.

---

## Screenshots

<!-- TODO: Add a UI screenshot once the UI is finalized. Suggested location:
     assets/screenshot.png

     ![Corvus FX UI](assets/screenshot.png)

     The plugin features a dark space-themed interface with animated nebula
     background, glass rotary knobs with purple glow effects, and a clean
     2×2 module layout.
-->

> 🎨 **Screenshot coming soon.** The plugin features a dark space-themed UI with animated nebula background, glass knobs with specular highlights and purple glow effects, organized in a clean 2×2 module grid layout.

---

## Audio Demos

<!-- TODO: Add SoundCloud / Bandcamp / YouTube demo links once recordings are made.
     Example:
     - [Clean Sparkle demo on SoundCloud](https://soundcloud.com/...)
     - [Thick Sauce guitar riff on YouTube](https://youtube.com/...)
-->

> 🎵 **Audio demos coming soon.** Listen to Corvus FX in action across all 36 factory presets.

---

### Signal Flow

```
Input → [Distortion] → [Chorus] → [Delay] → [Reverb] → [Master Output] → Limiter → Output
         [BYPASS]       [BYPASS]    [BYPASS]   [BYPASS]      [BYPASS]
```

Each module can be independently bypassed via a color-coded toggle button with a 30ms click-free crossfade. The entire chain runs in a **single per-sample pass** with block-level coefficient caching for minimal CPU overhead.

---

## Modules

### 🔥 Distortion — Saturation Engine
| Feature | Detail |
|---------|--------|
| **Drive types** | Smooth tape saturation → aggressive tube distortion with continuous Hermite crossfade |
| **Pre-emphasis** | High-shelf filter pushes harmonics into the saturation for richer texture |
| **Post-filter** | 2-pole low-pass shapes the distorted signal |
| **Warmth shelf** | Gentle bass-boost shelf adds body post-saturation |
| **Anti-aliasing** | **2x oversampling** (8-tap half-band FIR) — eliminates aliasing at any drive setting |
| **DC blocker** | Prevents offset buildup in the signal path |

The Drive knob smoothly morphs from transparent tape-style warmth (clean, musical, soft-clipping) through to aggressive asymmetrical tube saturation (rich harmonics, compressed feel) using a smoothstep interpolation — no zipper artifacts at the transition.

### 🌊 Chorus — 6-Voice Modulation
| Feature | Detail |
|---------|--------|
| **Voices** | 6 independently modulated voices with decorrelated LFO rates |
| **Interpolation** | **Hermite cubic interpolation** for artifact-free delay reads |
| **LFO shapes** | Multi-shape modulation (sine, triangle, etc.) per voice |
| **Depth scaling** | Mix-adaptive depth — higher mix values increase perceived depth naturally |
| **Allpass diffusers** | Per-voice allpass filters add diffusion for a richer, less metallic chorus |
| **Feedback** | Feedback tanh saturation wrapped in **2x oversampling** for anti-aliased warmth |

### ⏳ Delay — Tape-Style Echo
| Feature | Detail |
|---------|--------|
| **Time range** | 0–2000 ms, fully smoothed |
| **Ping-pong** | Stereo ping-pong mode with adjustable spread |
| **Interpolation** | **Hermite cubic interpolation** for artifact-free delay reads |
| **Tape wow/flutter** | Slow modulation emulates tape machine instability |
| **Filtered feedback** | Adjustable LP/HP feedback filtering with one-pole filters |
| **Saturation** | Soft tape saturation in feedback loop, wrapped in **2x oversampling** |
| **Feedback mapping** | Exponential curve — musical response across the full knob range |

### 🌌 Reverb — Enhanced Freeverb
| Feature | Detail |
|---------|--------|
| **Architecture** | 8 comb filters + 4 allpass diffusers (Freeverb-inspired) |
| **Interpolation** | **Hermite cubic interpolation** for artifact-free modulated reads |
| **Size control** | Room size varies decay time + allpass diffusion character (0.50–0.70 feedback) |
| **Damping** | Low-pass damping per comb filter for natural high-frequency rolloff |
| **Modulation** | Modulates comb filter delay times for a richer, less metallic tail |
| **Pre-delay** | 5–45 ms pre-delay scales with room size |

### 🎚️ Master Output — Analog Finish
| Feature | Detail |
|---------|--------|
| **Mid/Side processing** | Independent L/R → M/S conversion with width control (0–200%) |
| **Saturation** | Push-pull asymmetrical saturation — **2x oversampled** — generates even harmonics (2nd/4th) for analog warmth; independent Mid and Side drive controls |
| **Width control** | 0% (mono) → 100% (original stereo) → >100% (widened) |
| **DC blocker** | Prevents DC offset accumulation from asymmetric saturation |
| **Safety limiter** | Soft-knee safety clamp with Padé [3/2] tanh approximant |
| **Wet/Dry** | Global overall mix (can also be automated per-track) |

---

## Controls (24 Parameters)

### Continuous Controls (18)

| Control | Range | Default | Function |
|---------|-------|---------|----------|
| **Overall** | 0–100% | 100% | Global wet/dry mix |
| **Drive** | 0–100% | 0% | Tape warmth → tube saturation with smooth Hermite crossfade |
| **Chorus Depth** | 0–100% | 0% | Modulation depth (0 = bypass) |
| **Chorus Rate** | 0.1–10 Hz | 2 Hz | LFO speed — 6 decorrelated voices never align |
| **Chorus Mix** | 0–100% | 50% | Wet/dry balance |
| **Delay Time** | 0–2000 ms | 250 ms | Echo timing with tape-style interpolation |
| **Delay Feedback** | 0–95% | 30% | Repeat count (exponential mapping for musical response) |
| **Delay Mix** | 0–100% | 0% | Wet/dry balance |
| **Delay Damping** | 0–100% | 40% | High-frequency rolloff per repeat (darker = more tape-like) |
| **Delay Mod** | 0–100% | 30% | Wow/flutter intensity for vintage tape character |
| **Reverb Size** | 0–100% | 50% | Room size — controls both decay time and diffusion character |
| **Reverb Damping** | 0–100% | 50% | High-frequency decay (higher = shorter, darker tail) |
| **Reverb Mix** | 0–100% | 0% | Wet/dry balance |
| **Reverb Mod** | 0–100% | 30% | Modulation depth for organic tail movement |
| **Master Drive** | 0–100% | 0% | Master output push-pull saturation (even harmonics) |
| **Master Width** | 0–200% | 100% | Stereo width — 0% = mono, >100% = widened |
| **Master Mid Drive** | 0–100% | 0% | Mid channel saturation — affects center image |
| **Master Side Drive** | 0–100% | 0% | Side channel saturation — affects stereo width |

### Bypass Buttons (5)

| Control | Type | Function |
|---------|------|----------|
| **Distortion Bypass** | Toggle | Red — bypass distortion module (click-free crossfade) |
| **Chorus Bypass** | Toggle | Blue — bypass chorus module (click-free crossfade) |
| **Delay Bypass** | Toggle | Green — bypass delay module (click-free crossfade) |
| **Reverb Bypass** | Toggle | Purple — bypass reverb module (click-free crossfade) |
| **Master Bypass** | Toggle | Magenta — bypass master output stage (click-free crossfade) |

### Program Control

| Control | Range | Description |
|---------|-------|-------------|
| **Preset** | 0–35 | Factory preset selection (36 presets in 6 categories) |

All continuous parameters feature **20ms LinearSmoothedValue** interpolation for click-free automation and knob movement. All bypass switches use a **30ms LinearSmoothedValue wet/dry ramp** for truly click-free enable/disable.

---

## Factory Presets (36 — 6 per category)

### CLEAN — Transparent Enhancement, Pristine Highs
| # | Name | Best For |
|---|------|----------|
| 0 | **Clean Sparkle** | Mix bus, acoustic instruments |
| 1 | **Crystal Shimmer** | Clean guitars, electric piano |
| 2 | **Silk Thread** | Acoustic guitar, vocal sweetening |
| 3 | **Subtle Glue** | Drum bus, master bus |
| 4 | **Glass Canon** | Transparent widening, delicate textures |
| 5 | **Air Lift** | Vocal presence, acoustic enhancement |

### WARM — Analog-Style Saturation, Musical Thickening
| # | Name | Best For |
|---|------|----------|
| 6 | **Warm Glow** | Vocals, keys |
| 7 | **Vintage Vibe** | Lo-fi, retro textures |
| 8 | **Thick Sauce** | Bass, distorted guitars |
| 9 | **Tight Punch** | Drums, percussion |
| 10 | **Cozy Hiss** | Lo-fi warmth, tape emulation |
| 11 | **Tube Glow** | Vocal warmth, tube emulation |

### CREATIVE — Modulation-Forward, Sound Design
| # | Name | Best For |
|---|------|----------|
| 12 | **Dreamy Space** | Ambient pads, lead synths |
| 13 | **Cosmic Wide** | Pads, synth atmospheres |
| 14 | **Molten Core** | Synth leads, bass |
| 15 | **Sunspot** | Funky guitars, pop vocals |
| 16 | **Nebula Drift** | Cinematic textures, shoegaze |
| 17 | **Shimmerfall** | Ethereal tails, ambient builds |

### EXTREME — Aggressive, Heavy Processing
| # | Name | Best For |
|---|------|----------|
| 18 | **Deep Echo** | Dub, post-rock, vocals |
| 19 | **Aggressive Drive** | Rock guitars, aggressive synths |
| 20 | **Lush Pad** | Sustained pads, strings |
| 21 | **Event Horizon** | Ambient soundscapes, post-rock |
| 22 | **Iron Press** | Drums, aggressive mix bus |
| 23 | **Obliterator** | Maximum distortion, wall-of-sound |

### SIGNATURE — Curated Artist-Style Sounds
| # | Name | Best For |
|---|------|----------|
| 24 | **Velvet Morning** | Warm tape saturation, gentle chorus, silk reverb |
| 25 | **Neon Dusk** | Bright chorus, crisp delay, crystalline highs |
| 26 | **Basement Sessions** | Gritty drive, dark delay, underground vibe |
| 27 | **Cathedral Drift** | Massive reverb, slow chorus, spiritual space |
| 28 | **Circuit Bent** | Experimental modulation, glitchy texture |
| 29 | **Midnight Oil** | Saturated warmth, tape echo, late-night intimacy |

### DREAM — Ambient, Ethereal, Deep Soundscapes
| # | Name | Best For |
|---|------|----------|
| 30 | **Cloud Chamber** | Ethereal pads, floating atmospheres |
| 31 | **Frozen Lake** | Icy textures, crystalline reflections |
| 32 | **Ash & Ember** | Warm decay, smoldering ambience |
| 33 | **Stargate Portal** | Cinematic transitions, cosmic sweeps |
| 34 | **Underwater Cathedral** | Submerged reverbs, deep space |
| 35 | **Solar Flare** | Bright eruption, expansive brightness |

---

## Technical Highlights

### Anti-Aliasing — All Saturation Stages Oversampled

Non-linear waveshaping (saturation, distortion, tanh) generates harmonics above the Nyquist frequency that fold back as audible aliasing. Corvus FX eliminates this with **2x oversampling** on all four saturation stages:

- **Distortion** — tape/tube waveshaping at 2x rate
- **Chorus** — feedback tanh saturation at 2x rate (per-channel independent FIR state)
- **Delay** — tape feedback saturation at 2x rate (mono per-channel processing)
- **Master Output** — push-pull asymmetrical saturation at 2x rate (independent mid/side)

Each stage uses the same `Oversampling2x` utility: an **8-tap 2nd-order half-band FIR** filter with polyphase up/down sampling. The FIR is **SSE-optimized** (scalar MACs → SIMD intrinsics) for ~4× throughput on the critical path. Only non-linear operations are oversampled — linear filters (EQ, damping) remain at base rate to avoid unnecessary CPU cost.

### Click-Free Bypass — All 5 Modules

Every module (Distortion, Chorus, Delay, Reverb, Master Output) features a dedicated bypass button with a **30ms LinearSmoothedValue wet/dry crossfade**. Previous implementations used hard switches that caused audible clicks; the current implementation ramps the signal over 30ms for truly silent enable/disable in any DAW.

### Parameter Smoothing

Every continuous parameter uses `juce::LinearSmoothedValue<float>` with a **20ms ramp time**. This eliminates:

- **Zipper noise** from abrupt knob movement
- **Clicks** on host automation parameter changes
- **Step artifacts** during preset recall

The raw parameter value is read once per block (atomic load), then interpolated per-sample within the block.

### Block-Level Coefficient Caching

Expensive math (`std::exp`, `std::pow`, `std::sin`) is hoisted from per-sample loops to per-block `beginBlock()` calls:

| Module | Operations hoisted | Per-sample savings |
|--------|-------------------|-------------------|
| Distortion | 4× `std::exp` | 4 exp/sample → 1/block |
| Chorus | 5× redundant per-voice math | Per-voice LFO calc → 1/block |
| Delay | 2× `std::exp` (LP/HP) | 2 exp/sample → 1/block |
| Reverb | 8× setFeedback/setDamp + mod | 10+ ops/sample → 1/block |
| Master | 3× `std::exp` | 3 exp/sample → 1/block |

### Zero Per-Sample Transcendental Calls

The entire plugin uses **zero per-sample transcendental function calls** — every `std::sin`, `std::cos`, `std::sqrt`, `std::tanh`, and `std::fmod` is either:

- **Pre-computed** in `beginBlock()` as cached coefficients (e.g., filter coefficients)
- **Phase-recurrent** — incremental rotation with 256-sample magnitude renormalization replaces `std::sin`/`std::cos` calls (6-voice chorus, delay wow/flutter, reverb comb modulation)
- **Approximated** — the safety limiter uses a Padé [3/2] rational approximant (`z*(15+z²)/(15+6z²)`) instead of `std::tanh`, accurate to 0.04%

This eliminates all hot-path transcendental computation at 48kHz.

### Hermite Cubic Interpolation

All modulated delay reads (Chorus, Delay, Reverb) use **Hermite cubic interpolation** instead of linear interpolation. This eliminates:

- **High-frequency attenuation** (linear interpolation acts as a low-pass filter on modulated signals)
- **Metallic artifacts** from discontinuous read-position quantization
- **Aliasing** from fractional-delay interpolation

The same `hermiteInterp()` utility is shared across all three modules.

### LFO Phase Recurrence Drift Correction

Incremental-rotation LFO recurrence (sin/cos via single multiply-add) slowly loses unit-vector length under float32, breathing the modulation depth by ~2.5%/minute. All LFOs in Chorus, Delay, and Reverb include periodic magnitude renormalization (every 256 samples), reducing drift to ~0.0003%/minute.

---

## Installation

### Requirements
- **Host**: Any DAW that supports VST3 (Reaper, Ableton Live, FL Studio, Cubase, etc.)
- **OS**: Windows 10 or 11 (x64)
- **CPU**: Intel/AMD processor (SSE2 or later, AVX2 recommended)

### Quick Install

1. **Download** the latest `CorvusFX.vst3` from the [Releases](https://github.com/ethanjones1132-lab/CorvusFx/releases) page
2. **Copy** the file to your VST3 plugin directory:
   ```
   C:\Program Files\Common Files\VST3\
   ```
3. **Rescan** plugins in your DAW

### Variants

| Variant | Path |
|---------|------|
| **Mk1** | `drippy/NewProject.vst3/Contents/x86_64-win/DrippyMk1.vst3` |
| **Mk2** | `DrippyMk2/NewProject.vst3/Contents/x86_64-win/DrippyMk2.vst3` |

Mk1 is the current mainline. Mk2 is an experimental alternative build.

---

## Building from Source

### Prerequisites
- [JUCE 8.0.12](https://juce.com/get-juce) extracted to your system
- Visual Studio 2026 (v18) or later with C++ desktop workload

### Quick Build (MSBuild — Fast)

```bash
# Build using the existing VS solution
MSBuild.exe "path/to/NewProject_VST3.vcxproj" -p:Configuration=Release -p:Platform=x64 -m
```

### CMake Build (Alternative)

```bash
set JUCE_PATH=C:\path\to\JUCE
cd path\to\source
cmake -G "Visual Studio 18 2026" -A x64 -DJUCE_PATH="%JUCE_PATH%" -S . -B build
cmake --build build --config Release
```

Source code is located in the `source/DrippyFX/` directory of this repo, alongside deployed binaries under `drippy/` and `DrippyMk2/`.

---

## Performance & Quality Targets

| Metric | Target | Status |
|--------|--------|--------|
| **CPU usage** @ 48kHz/64 samples | < 5% | ✅ Achieved |
| **Aliasing** (THD+N @ 10dB drive) | Inaudible (< -100dB) | ✅ 2x oversampling on all 4 saturation stages |
| **Parameter zipper noise** | None audible | ✅ LinearSmoothedValue (20ms) |
| **Preset recall reliability** | 100% | ✅ Bounds-checked, 4-table host interop |
| **DAW compatibility** | Reaper, Ableton, FL, Cubase | ✅ Tested |

---

## Changelog Highlights

| Date | Change |
|------|--------|
| 2026-07-25 | Critical delay ms-to-samples conversion fix (was using 1/sr instead of sr*0.001f — all presets produced ~0.02ms delay regardless of knob setting) |
| 2026-07-25 | Merged meter accumulation into main DSP loop (eliminated 2 buffer iterations) |
| 2026-07-25 | Per-sample delay_mod smoothing — last parameter using block-level snapshot |
| 2026-07-22 | DC blocker added to Master Output stage (mid/side channels) |
| 2026-07-22 | TooltipWindow added — all 24 tooltips now render in DAWs |
| 2026-07-20 | Log-scale (dB) level meters — consistent amp-to-Y mapping |
| 2026-07-20 | LFO phase-recurrence magnitude renormalization — fixes float32 rotation drift |
| 2026-07-20 | Hoisted per-sample std::sqrt from Chorus hot path — truly completes zero-transcendental milestone |
| 2026-07-20 | DREAM preset category — 6 ambient/ethereal presets (36 total) |
| 2026-07-15 | DREAM preset expansion complete — 36 factory presets across 6 categories |
| 2026-07-14 | `/fp:fast` + `/arch:AVX2` compiler optimization enabled |
| 2026-07-13 | Per-channel oversampling (Chorus feedback tanh) — eliminates stereo FIR cross-contamination |
| 2026-07-13 | Mono oversampling (Delay tape sat) — halves FIR cost |
| 2026-07-13 | Padé [3/2] tanh approximant for safety limiter — eliminates last per-sample transcendental |
| 2026-07-13 | DAW host interop fix — all 36 presets reachable via program interface |
| 2026-07-13 | SIGNATURE preset category — 6 artist-style presets (24 total → 30 total) |
| 2026-07-12 | Renamed "NewProject" → "CorvusFX" project-wide |
| 2026-07-12 | Mono oversampling for mid/side — halves Master FIR cost |
| 2026-07-12 | Replaced std::fmod with normalized phase tracking in Chorus |
| 2026-07-12 | Added missing delay_mod UI knob (5th delay control) |
| 2026-07-12 | JUCE 8 AudioParameterFloat API migration |
| 2026-07-11 | Bypass UI buttons for Chorus, Delay, Reverb, Master |
| 2026-07-10 | Click-free bypass parameters for all 5 modules (crossfade wiring TBD) |
| 2026-07-09 | SSE-optimized Oversampling2x FIR (~4× throughput) |
| 2026-07-09 | Mid/Side processing with Width, Mid Drive, Side Drive controls |
| 2026-07-08 | LFO phase recurrence for Reverb master modulation — completes zero-transcendental milestone (initial claim) |
| 2026-07-07 | LFO phase recurrence for Chorus drift, Delay wow/flutter |
| 2026-07-07 | Professional dB tick marks on level meters |
| 2026-07-06 | Master Drive parameter (15th total); 24 presets with master_drive values |
| 2026-07-05 | Proportional layout scaling for responsive resize |
| 2026-07-05 | Factory preset categorization (4 categories: CLEAN, WARM, CREATIVE, EXTREME) |
| 2026-07-04 | Stereo level meters with peak/RMS display |
| 2026-07-04 | Per-sample Overall parameter smoothing |
| 2026-07-03 | Renamed "NewProject" → "CorvusFX" in Jucer and VS solution |
| 2026-07-01 | EnhancedChorus: 2x oversampling for feedback tanh anti-aliasing |
| 2026-06-30 | ScopedNoDenormals fix (single RAII per block) |
| 2026-06-29 | Reverb allpass feedback scaling with room size (0.50→0.70) |
| 2026-06-29 | All 13 parameters: LinearSmoothedValue for zipper-free automation |
| 2026-06-28 | EnhancedDelay: 2x oversampling for tape saturation in feedback loop |
| 2026-06-27 | ProfessionalDistortion: smooth tape→tube crossfade via Hermite smoothstep |
| 2026-06-27 | Distortion + Master: 2x oversampling for zero aliasing |
| 2026-06-26 | UpgradedReverb: Hermite cubic interpolation on all CombFilters |
| 2026-06-26 | MasterOutputStage: push-pull asymmetrical saturation (even harmonics) |
| 2026-06-26 | processBlock: merged master + limiter into single per-sample pass (4→2 buffer passes) |
| 2026-06-25 | Block-level coefficient caching on all hot modules |
| 2026-06-24 | Delay: exponential feedback mapping |
| 2026-06-24 | Reverb: reverb_mod knob activated |
| 2026-06-24 | Presets: fixed setCurrentProgram bounds for all 18 presets |

For the full engineering change log with MD5 hashes and binary verification, see `docs/PRIORITIES.md`.

---

## Compatibility

| DAW | Status |
|-----|--------|
| **Reaper** | ✅ Tested |
| **Ableton Live 11/12** | ✅ Tested |
| **FL Studio** | ✅ Tested |
| **Cubase** | ✅ Tested |
| **Studio One** | ⚠️ Community reports welcome |
| **Bitwig** | ⚠️ Community reports welcome |

Tested on **Windows 10 & 11 (x64)**. macOS support is not yet available.

---

## FAQ

**Q: Is this plugin free?**
A: Yes! Corvus FX is free and open-source under the MIT license.

**Q: Will there be a macOS version?**
A: Not currently, but the JUCE framework supports macOS builds. If there's demand, a Mac build can be added.

**Q: Can I use Corvus FX in commercial productions?**
A: Yes. The MIT license permits commercial use — no attribution required.

**Q: Why "Corvus"?**
A: Corvus (Latin: crow/raven) — intelligent, adaptable birds known for their tool use and problem-solving. The name reflects the plugin's flexible signal chain and thoughtful DSP design.

**Q: How do I bypass individual modules?**
A: Each module has a color-coded BYPASS button below its controls. The bypass uses a 30ms click-free crossfade for silent switching in any DAW.

**Q: How do the Master Width, Mid Drive, and Side Drive controls work?**
A: The Master Output converts L/R to Mid/Side internally. **Width** scales the side signal (0% = mono, 100% = original, >100% = widened). **Mid Drive** applies saturation to center-panned content; **Side Drive** applies saturation to stereo-width content. This gives you independent control over the center image and stereo field saturation.

**Q: Where can I report bugs or request features?**
A: Open an [issue](https://github.com/ethanjones1132-lab/CorvusFx/issues) or start a [discussion](https://github.com/ethanjones1132-lab/CorvusFx/discussions).

---

## Contributing

Contributions are welcome! Whether it's bug fixes, DSP improvements, new presets, or documentation — every bit helps.

**Source layout:** Edit JUCE code under `source/DrippyFX/`. Shipped Windows binaries live at `drippy/NewProject.vst3/Contents/x86_64-win/DrippyMk1.vst3`. Any commit that updates the `.vst3` for a code-level fix must include the matching `source/DrippyFX/` diffs (see `docs/AGENTS.md`).

1. Fork the repo
2. Create a feature branch (`git checkout -b feature/amazing-idea`)
3. Commit your changes (`git commit -m 'feat: add amazing idea'`)
4. Push to the branch (`git push origin feature/amazing-idea`)
5. Open a Pull Request

For major changes, please open a discussion first to align on approach.

See `docs/AGENTS.md` for the engineering workflow used by autonomous coding agents on this project.

---

This project is distributed as pre-built binaries for evaluation. The source code is available under the MIT License (see `LICENSE`).

---

<div align="center">

**Corvus FX** — Crafted with ❤️ and a lot of Padé approximants

[JUCE](https://juce.com) · [Report a Bug](https://github.com/ethanjones1132-lab/CorvusFx/issues) · [Request a Feature](https://github.com/ethanjones1132-lab/CorvusFx/discussions) · [Website](https://jonesinsrc.com)

</div>
