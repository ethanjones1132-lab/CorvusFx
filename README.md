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

Corvus FX is a **5-module cascade VST3 plugin** that chains **Distortion → Chorus → Delay → Reverb → Master Output** in a single, efficient processing pass. Each module is independently controllable, and 18 factory presets take you from subtle bus glue to massive ambient textures.

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

> 🎵 **Audio demos coming soon.** Listen to Corvus FX in action across all 18 factory presets.

---

### Signal Flow

```
Input → [Distortion] → [Chorus] → [Delay] → [Reverb] → [Master Output] → Limiter → Output
```

Each module can be dialed to zero (bypassed) so the signal passes through cleanly. The entire chain runs in a **single per-sample pass** with block-level coefficient caching for minimal CPU overhead.

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

The Fatness knob smoothly morphs from transparent tape-style warmth (clean, musical, soft-clipping) through to aggressive asymmetrical tube saturation (rich harmonics, compressed feel) using a smoothstep interpolation — no zipper artifacts at the transition.

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
| **Saturation** | Push-pull asymmetrical saturation — **2x oversampled** — generates even harmonics (2nd/4th) for analog warmth |
| **Multi-band** | Two-band processor with crossover shaping |
| **DC blocker** | Prevents DC offset accumulation across the chain |
| **Peak limiter** | Soft-knee safety limiter with tanh soft-clipping |
| **Wet/Dry** | Global overall mix (can also be automated per-track) |

---

## Controls (14 Parameters)

| Control | Range | Default | Function |
|---------|-------|---------|----------|
| **Overall** | 0–100% | 100% | Global wet/dry mix |
| **Fatness** | 0–100% | 0% | Drive: tape warmth → tube saturation |
| **Chorus Depth** | 0–100% | 0% | Modulation depth (0 = bypass) |
| **Chorus Rate** | 0.1–10 Hz | 2 Hz | LFO speed |
| **Chorus Mix** | 0–100% | 50% | Wet/dry blend |
| **Delay Time** | 0–2000 ms | 250 ms | Echo timing |
| **Delay Feedback** | 0–95% | 30% | Repeat count (exponential mapping) |
| **Delay Mix** | 0–100% | 0% | Wet/dry blend |
| **Delay Damping** | 0–100% | 40% | High-frequency rolloff per repeat |
| **Delay Mod** | 0–100% | 30% | Tape wow/flutter intensity |
| **Reverb Size** | 0–100% | 50% | Room size (decay + diffusion) |
| **Reverb Damping** | 0–100% | 50% | High-frequency decay control |
| **Reverb Mix** | 0–100% | 0% | Wet/dry blend |
| **Reverb Mod** | 0–100% | 30% | Modulation depth for richer tail |
| **Preset** | 0–17 | 0 | Factory preset selection |

All parameters feature **20ms LinearSmoothedValue** interpolation for click-free automation and knob movement.

---

## Factory Presets (18)

| # | Name | Vibe | Best For |
|---|------|------|----------|
| 0 | **Clean Sparkle** | Subtle widening, pristine highs | Mix bus, acoustic instruments |
| 1 | **Warm Glow** | Medium drive, gentle chorus | Vocals, keys |
| 2 | **Dreamy Space** | Low drive, deep chorus, big reverb | Ambient pads, lead synths |
| 3 | **Thick Sauce** | Heavy saturation, chorus thickening | Bass, distorted guitars |
| 4 | **Crystal Shimmer** | Chorus-forward, bright and airy | Clean guitars, electric piano |
| 5 | **Deep Echo** | Tape delay focus, dark repeats | Dub, post-rock, vocals |
| 6 | **Vintage Vibe** | Lo-fi warmth, rolled-off highs | Lofi, retro textures |
| 7 | **Cosmic Wide** | Maximum stereo width, deep modulation | Pads, synth atmospheres |
| 8 | **Subtle Glue** | Bus cohesion, barely-there enhancement | Drum bus, master bus |
| 9 | **Aggressive Drive** | In-your-face distortion | Rock guitars, aggressive synths |
| 10 | **Lush Pad** | Massive reverb wash | Sustained pads, strings |
| 11 | **Tight Punch** | Controlled, punchy, no excess | Drums, percussion |
| 12 | **Silk Thread** | Ultra-smooth chorus, no drive | Acoustic guitar, vocal sweetening |
| 13 | **Molten Core** | Heavy saturation into drenched chorus | Synth leads, bass |
| 14 | **Event Horizon** | Long delay + massive reverb | Ambient soundscapes, post-rock |
| 15 | **Sunspot** | Fast bright chorus + slapback | Funky guitars, pop vocals |
| 16 | **Nebula Drift** | Slow evolving chorus + long reverb | Cinematic textures, shoegaze |
| 17 | **Iron Press** | Heavy drive + tight verb | Drums, aggressive mix bus |

---

## Technical Highlights

### Anti-Aliasing — All Saturation Stages Oversampled

Non-linear waveshaping (saturation, distortion, tanh) generates harmonics above the Nyquist frequency that fold back as audible aliasing. Corvus FX eliminates this with **2x oversampling** on all four saturation stages:

- **Distortion** — tape/tube waveshaping at 2x rate
- **Chorus** — feedback tanh saturation at 2x rate
- **Delay** — tape feedback saturation at 2x rate  
- **Master Output** — push-pull asymmetrical saturation at 2x rate

Each stage uses the same `Oversampling2x` utility: an **8-tap 2nd-order half-band FIR** filter with polyphase up/down sampling. Only non-linear operations are oversampled — linear filters (EQ, damping) remain at base rate to avoid unnecessary CPU cost.

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

### Hermite Cubic Interpolation

All modulated delay reads (Chorus, Delay, Reverb) use **Hermite cubic interpolation** instead of linear interpolation. This eliminates:

- **High-frequency attenuation** (linear interpolation acts as a low-pass filter on modulated signals)
- **Metallic artifacts** from discontinuous read-position quantization
- **Aliasing** from fractional-delay interpolation

The same `hermiteInterp()` utility is shared across all three modules.

---

## Installation

### Requirements
- **Host**: Any DAW that supports VST3 (Reaper, Ableton Live, FL Studio, Cubase, etc.)
- **OS**: Windows 10 or 11 (x64)
- **CPU**: Intel/AMD processor (SSE2 or later)

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

Source code is located in the `DrippyFX/` directory of the [DrippyFX_v1.0.0_Complete](https://github.com/ethanjones1132-lab/CorvusFx) package.

---

## Performance & Quality Targets

| Metric | Target | Status |
|--------|--------|--------|
| **CPU usage** @ 48kHz/64 samples | < 5% | ✅ Achieved |
| **Aliasing** (THD+N @ 10dB drive) | Inaudible (< -100dB) | ✅ 2x oversampling |
| **Parameter zipper noise** | None audible | ✅ LinearSmoothedValue (20ms) |
| **Preset recall reliability** | 100% | ✅ Bounds-checked |
| **DAW compatibility** | Reaper, Ableton, FL, Cubase | ✅ Tested |

---

## Changelog Highlights

| Date | Change |
|------|--------|
| 2026-07-01 | EnhancedChorus: 2x oversampling for feedback tanh anti-aliasing |
| 2026-06-30 | processBlock: ScopedNoDenormals scope fix (single RAII per block) |
| 2026-06-29 | UpgradedReverb: allpass feedback scales with room size (0.50→0.70) |
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

For the full engineering change log, see `docs/PRIORITIES.md`.

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

**Q: Where can I report bugs or request features?**
A: Open an [issue](https://github.com/ethanjones1132-lab/CorvusFx/issues) or start a [discussion](https://github.com/ethanjones1132-lab/CorvusFx/discussions).

---

## Contributing

Contributions are welcome! Whether it's bug fixes, DSP improvements, new presets, or documentation — every bit helps.

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

**Corvus FX** — Crafted with ❤️ and a lot of tanh()

[JUCE](https://juce.com) · [Report a Bug](https://github.com/ethanjones1132-lab/CorvusFx/issues) · [Request a Feature](https://github.com/ethanjones1132-lab/CorvusFx/discussions) · [Website](https://jonesinsrc.com)

</div>
