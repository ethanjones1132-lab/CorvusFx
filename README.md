# Aphelion FXs

**Professional audio plugins engineered with precision and warmth.**

Aphelion FXs is a boutique audio plugin studio building studio-grade effects for music producers, engineers, and sound designers. Every plugin is crafted with obsessive attention to both the science and the art of audio processing.

> *"Sound is energy. We shape it with intention."*

Named after the point in a planet's orbit farthest from the sun, Aphelion FXs represents perspective — the vantage point where you can see the whole picture. Based in the mountains of Appalachia, built for studios everywhere.

---

## Website

This repository hosts the **Aphelion FXs** marketing and product website, deployed via GitHub Pages.

| Page | Description |
|---|---|
| [`index.html`](index.html) | Main Aphelion FXs brand landing page — company story, product catalog, philosophy |
| [`corvus-fx.html`](corvus-fx.html) | Dedicated product page for **Corvus FX** |

The site auto-deploys to GitHub Pages on every push to `main`.

---

## Corvus FX

**Corvus FX** is the flagship VST3 plugin from Aphelion FXs — a professional multi-effect suite in a single plugin, built on the [JUCE](https://juce.com/) framework.

### Pricing

| License | Price |
|---|---|
| Full License (lifetime) | **$15** one-time — no subscriptions, ever |

Free updates for life. No iLok, no dongle, no machine limits (covers all computers you personally own).

---

### Features

Four studio-grade effects in series, each engineered to complement the next:

#### 🔥 Analog-Modeled Distortion
Tape saturation at low drive, tube-style asymmetric harmonics at high drive. Pre-emphasis, adaptive makeup gain, and Julius O. Smith DC blocking for clean, warm overdrive at any setting.

#### 🌊 6-Voice Lush Chorus
Six independent voices with organic drift modulation and Hermite cubic interpolation. Zero crackling, wide stereo spread, and feedback control — from subtle shimmer to massive walls of sound.

#### ⏱️ Tape-Style Delay
Hermite-interpolated delay with wow and flutter, stereo ping-pong, and damped feedback with tape saturation. Repeats darken naturally like real analog tape machines.

#### ✨ Algorithmic Reverb
Freeverb-inspired architecture: 8 comb filters, 4 allpass diffusers, and 8-tap early reflections. Independent room size, damping, width, and pre-delay. Stable at every parameter value.

#### 🎨 Deep Space Interface
Photorealistic animated nebula with cached-layer rendering at 60fps. Glass-morphism panels, premium knobs with specular highlights, and an organic star field with diffraction spikes.

#### ⚡ Optimized Performance
Per-sample processing with low CPU overhead across all four effects simultaneously. Rock-solid stability in every major DAW.

---

### Signal Chain

```
Input → Distortion → Chorus → Delay → Reverb → Output (Soft Limiter)
(Stereo/Mono)  (Tape→Tube)  (6 Voices)  (Tape Style)  (8-Comb FDN)  (tanh)
```

---

### Technical Specifications

#### Plugin

| Spec | Value |
|---|---|
| Format | VST3 |
| Platform | Windows & macOS |
| Framework | JUCE (Professional) |
| Controls | 13 Parameters + Preset Selector |
| Window | 1200 × 700 (resizable) |
| Sample Rates | 44.1 kHz — 192 kHz |
| Latency | 0 samples (real-time, no lookahead) |

#### DSP Engine

| Module | Implementation |
|---|---|
| Distortion | Tape + Tube Waveshaping |
| Chorus | 6-Voice, Hermite Cubic Interpolation |
| Delay | Tape-Style, Ping-Pong |
| Reverb | 8-Comb + 4-Allpass FDN (Freeverb-inspired) |
| Interpolation | Hermite Cubic (4-point) |
| DC Blocking | Julius O. Smith Topology |
| Output Limiter | Soft-knee tanh Saturation |

---

### Included Presets (12)

| Preset | Character |
|---|---|
| Clean Sparkle | Subtle enhancement |
| Warm Glow | Saturated warmth |
| Dreamy Space | Ethereal & wide |
| Thick Sauce | Heavy saturation |
| Crystal Shimmer | Bright, chorus-heavy |
| Deep Echo | Dark tape repeats |
| Vintage Vibe | Lo-fi analog warmth |
| Cosmic Wide | Massive stereo spread |
| Subtle Glue | Mix bus cohesion |
| Aggressive Drive | In-your-face grit |
| Lush Pad | Massive reverb wash |
| Tight Punch | Controlled & punchy |

---

### DAW Compatibility

Any DAW that supports the **VST3** format, including:

- FL Studio
- Ableton Live
- Logic Pro
- Cubase
- Studio One
- Reaper
- Bitwig Studio

---

### Installation

1. Purchase Corvus FX and download the VST3 file.
2. Copy it to your VST3 folder:
   - **Windows:** `C:\Program Files\Common Files\VST3`
   - **macOS:** `~/Library/Audio/Plug-Ins/VST3`
3. Rescan plugins in your DAW.

---

### Support & Policies

- **Refund policy:** 14-day refund for unresolvable technical issues.
- **Support:** [support@corvusfx.com](mailto:support@corvusfx.com)
- **License:** Covers all computers you personally own — no activation servers.

---

## Upcoming Plugins

| Plugin | Description | Status |
|---|---|---|
| **Perihelion** | Dedicated saturation & harmonic exciter with parallel processing, envelope following, and multi-band warmth | Coming Soon |
| **Solstice** | Modulation powerhouse — phaser, flanger, rotary, and tremolo with tempo sync, stereo expansion, and analog-modeled LFOs | Coming Soon |

All future plugins follow the same philosophy: one fair price, lifetime license, free updates forever.

---

## Philosophy

**I — Precision Engineering**
No shortcuts. Every DSP algorithm is built from scratch with clean mathematics — Hermite interpolation, Julius O. Smith DC blocking, proper anti-aliasing.

**II — Musical Character**
Technical perfection means nothing without soul. Effects are tuned by ear to feel alive — tape warmth, analog drift, organic modulation.

**III — Honest Value**
No subscriptions. No upsells. No locked features. One fair price, lifetime license, free updates forever.

---

## Repository Structure

```
AphelionFx/
├── index.html              # Aphelion FXs brand/company landing page
├── corvus-fx.html          # Corvus FX product page
├── AphelionFx-0.1.0/       # v0.1.0 release snapshot
│   ├── index.html
│   └── corvus-fx.html
├── .github/
│   └── workflows/
│       ├── deploy-pages.yml  # GitHub Pages deployment
│       └── static.yml        # Static site deployment
├── .nojekyll               # Disables Jekyll on GitHub Pages
└── README.md
```

---

## Deployment

The site is a static HTML/CSS/JS project with no build step. It is automatically deployed to **GitHub Pages** on every push to the `main` branch via the workflow in `.github/workflows/deploy-pages.yml`.

---

## Contact

- **General / support:** [support@aphelionfxs.com](mailto:support@aphelionfxs.com)
- **Corvus FX support:** [support@corvusfx.com](mailto:support@corvusfx.com)

© 2026 Aphelion FXs LLC. All rights reserved.
