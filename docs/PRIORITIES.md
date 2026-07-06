# Corvus VST (DrippyFX) — Priority Roadmap

Last updated: 2026-07-06 (overnight pass — fixed broken loadPreset selectorToPreset double-mapping bug, rebuild + deploy verified)
Working copy: `C:\\Projects\\Corvus VST`
Source root: `C:\\Users\\ethan\\Downloads\\DrippyFX_v1.0.0_Complete\\DrippyFX\\`

Quick status: **DSP quality — all 4 saturation stages oversampled, all parameters smoothed, hot-paths fully block-cached**

---

## High-Impact Improvements (Ranked)

| Priority | Item | Why it Matters | Status |
|----------|------|----------------|--------|
| **P0** | Create PRIORITIES.md + ROADMAP.md (this file) | No planning docs; cron agents fly blind | ✅ Done (2026-07-02) |
| **P0** | Create AGENTS.md for autonomous agent context | Corvus has no AGENTS.md — agents lack project rules | ✅ Done (2026-07-02) |
| **P1** | Rename "NewProject" → "CorvusFX" in Jucer/solution | Boilerplate names leak into DAW plugin lists, installer paths | ✅ Done (2026-07-03, rebuilt & committed `0e65aa6`) |
| **P1** | Verify 2x oversampling on all saturation stages (Distortion + Master) | Alias-free saturation at any drive — latest major improvement | ✅ Done (2026-06-27, `a66f658`) |
| **P1** | Hermite interpolation on Reverb CombFilter | Modulated delay reads artifact-free — matches Delay/Chorus | ✅ Done (2026-06-26, `7c37e20`) |
| **P1** | 2x oversampling on Delay tape saturation | Eliminates aliasing in feedback loop tail | ✅ Done (2026-06-28, `83b59a0`) |
| **P1** | 2x oversampling on Chorus feedback tanh | Eliminates aliasing in chorus feedback loop | ✅ Done (2026-07-01, `37bc0c2`) |
| **P1** | Block-level coefficient caching on all hot paths | 4–5 exp/sample → 1/block across Distortion, Delay, Reverb, Master | ✅ Done (2026-06-24 to 2026-06-26) |
| **P1** | Merge master output + limiter into single per-sample pass | 4→2 buffer passes in processBlock | ✅ Done (2026-06-26, `b3b4f21`) |
| **P2** | Push-pull asymmetrical saturation (even harmonics) | Musical warmth via 2nd/4th harmonic asymmetry | ✅ Done (2026-06-26, `f7ed642`) |
| **P2** | Exponential feedback mapping on Delay | Musical response across full knob range | ✅ Done (2026-06-24, `bc8e816`) |
| **P2** | Activate Reverb modulation (`reverb_mod` knob) | Knob existed but was dead code | ✅ Done (2026-06-24, `cf33942`) |
| **P2** | Preset system: fix `setCurrentProgram` bounds for all 18 presets | DAWs crashed on program change >17 | ✅ Done (2026-06-24, `b0e960a`) |
| **P2** | Parameter smoothing (LinearSmoothedValue) on all 14 params | Zipper noise eliminated on knob/automation changes | ✅ Done (2026-06-29, `b99b59c`) |
| **P2** | Reverb allpass feedback scaling with room size | Size knob now varies spatial diffusion character | ✅ Done (2026-06-29, `1c3652e`) |
| **P2** | Chorus LFO rate caching (rateToIncrement in beginBlock) | 6 divides/sample → 0; last remaining per-sample /sr | ✅ Done (2026-07-05, `d48eaf0`) |
| **P3** | Factory preset categorization | Group by vibe: Clean, Warm, Creative, Extreme | ✅ Done (2026-07-05) |
| **P3** | New presets beyond current 18 | Expand creative palette | ⬜ Deferred |

---

## Improvement Progress Log (from corvus-cron skill)

| Date | Commit | Module | Improvement |
|------|--------|--------|-------------|
| 2026-06-24 | `b0e960a` | Presets | Fix `setCurrentProgram` bounds for all 18 presets |
| 2026-06-24 | `cf33942` | Reverb | Activate comb filter modulation (`reverb_mod` knob now works) |
| 2026-06-24 | `bc8e816` | Delay | Exponential feedback mapping for musical response |
| 2026-06-24 | `4db06cc` | Distortion | Block-level coefficient cache (4 exp/sample → 1/block) |
| 2026-06-25 | `6bf1278` | Master + Chorus | Block-level coefficient cache (5 exp/sample → 1/block) |
| 2026-06-25 | `61c197f` | EnhancedDelay | Block-level coefficient cache for feedback LP/HP (2 exp/sample → 1/block) |
| 2026-06-25 | `60f3dc1` | UpgradedReverb | Block-level coefficient cache: hoisted 8× setFeedback/setDamp + mod calc |
| 2026-06-26 | `b3b4f21` | processBlock | Merge master output + safety limiter into main loop (4→2 buffer passes) |
| 2026-06-26 | `f7ed642` | MasterOutputStage | Push-pull asymmetrical saturation: even-harmonic warmth, drive=1.8x, safety clamp |
| 2026-06-26 | `7c37e20` | UpgradedReverb | Hermite cubic interpolation for modulated reads (replaces linear) |
| 2026-06-27 | `a66f658` | Distortion + Master | **2x oversampling** for zero aliasing: Oversampling2x (2nd-order half-band FIR, 8 taps) |
| 2026-06-28 | `83b59a0` | EnhancedDelay | **2x oversampling** for tape saturation in feedback loop — eliminates aliasing in delay tail |
| 2026-06-29 | `b99b59c` | processBlock | **Parameter smoothing (LinearSmoothedValue)** on all 13 audio parameters — 20ms smoothing eliminates zipper noise from knob movement and host automation. Previously, raw atomic reads jumped instantly between blocks. |
| 2026-06-29 | `1c3652e` | UpgradedReverb | **Allpass feedback scales with room size** (0.50→0.70) — Size knob now varies diffusion character. Also hoisted comb setFeedback/setDamp loop from per-sample to per-block in beginBlock(). |
| 2026-06-30 | `3936329` | processBlock | **ScopedNoDenormals fix** — moved from outer function scope into per-sample loop, fixing redundant reconstruction on every iteration. Single RAII object per block eliminates per-sample stack object creation/destruction overhead. |
| 2026-07-01 | `37bc0c2` | EnhancedChorus | **2x oversampling for feedback tanh anti-aliasing** — wrapped the tanh feedback saturation in Oversampling2x (8-tap half-band FIR). Eliminates aliasing artifacts from the non-linear feedback loop that compound with each iteration. Now all 4 saturation stages (Distortion, Chorus, Delay, Master) run at 2x sample rate. |
| 2026-07-03 | `0e65aa6` | Jucer/Build | **Renamed "NewProject" → "CorvusFX" in Jucer project and VS solution** — updated project name, target name, JucePlugin_Name, JucePlugin_Desc definitions. Full rebuild confirms new branding in VST3 manifest. Binary MD5 changed `a96d1356` → `fa8c8d77`. |
| 2026-07-04 | `57c04aa` | UI/PluginEditor | **Stereo level meters with peak/RMS display** — 4 vertical bars (In L/R, Out L/R), professional metering with cyan input / magenta output colors, 0dB reference line, peak hold with exponential decay, 30fps update via timerCallback reading relaxed atomics |
| 2026-07-04 | `0b1c4d8` | processBlock | **Per-sample Overall parameter smoothing** — moved Overall wet/dry from block-level `getCurrentValue()` into per-sample loop using `smoothOverall.getNextValue()`. All 14 audio parameters now have 20ms LinearSmoothedValue smoothing. Eliminates zipper noise on global wet/dry knob during automation/knob movement. |
| 2026-07-05 | `d48eaf0` | EnhancedChorus | **Cache LFO rate→increment in beginBlock()** — precompute `twoPi/sr` once per block, replacing 6 per-sample divides with cached multiplies in the hot inner loop. Same behavior, fewer arithmetic ops per voice. |
| 2026-07-05 | `0c36943` | UpgradedReverb | **Cache modPhase increment in beginBlock()** — precompute `0.37f/sr` once per block, replacing 1 per-sample divide with cached multiply. Last remaining per-sample `/sr` in the entire plugin — all hot-path sample-rate divides are now cached at block level. |
| 2026-07-05 | `2897782` | UI/PluginEditor | **Proportional layout scaling for responsive resize** — all hardcoded pixel values in resized() now scale via `min(width/1200, height/700)` factor with minimum size guards. Full 1000-1600w × 600-900h range supported with uniform aspect-ratio preservation, 60fps animated background maintained. |
| 2026-07-05 | `4e43c77` | UI/PluginEditor | **Factory preset categorization** — group 18 presets into 4 vibe categories (CLEAN, WARM, CREATIVE, EXTREME) with disabled separator items in preset selector; adds selector-to-preset mapping in loadPreset(). |
| 2026-07-06 | `252d2ff` | Presets | **Reorder presets[] to match categorized combo box layout** — removed broken ID-based selectorToPreset table; instead reordered presets[] + getProgramName() to match CLEAN[0-3]/WARM[4-7]/CREATIVE[8-12]/EXTREME[13-17] layout. All three paths (combo attachment, DAW host interface, program names) now use identity mapping with no translation table. Binary MD5: c872564e → b7a435c7. |

---

## Quality Targets (from corvus-cron skill)

| Area | Goal | Success Signal |
|------|------|----------------|
| **DSP accuracy** | Studio-grade, competitive with market | Cleaner spectrum, less aliasing, musical parameter response |
| **Performance** | <5% CPU at 48kHz/64 samples | No audio dropouts, efficient SIMD where needed |
| **Parameter feel** | Musical across full range | Smooth transitions, no zipper noise, useful extremes |
| **UI polish** | Professional-grade visual experience | Consistent with top-tier plugins, responsive |
| **Code quality** | Production C++17 | No "NewProject" boilerplate, const-correct, clean includes |

---

## Build & Deploy Pipeline

**Preferred: MSBuild (fast, incremental)**

```bash
"C:/Program Files/Microsoft Visual Studio/18/Community/MSBuild/Current/Bin/amd64/MSBuild.exe" \
  "C:/Users/ethan/Downloads/DrippyFX_v1.0.0_Complete/NewProject/Builds/VisualStudio2026/NewProject_VST3.vcxproj" \
  -p:Configuration=Release -p:Platform=x64 -m
```
Output: `.../x64/Release/VST3/NewProject.vst3/Contents/x86_64-win/NewProject.vst3`

**Deploy:**
```bash
cp ".../NewProject.vst3" "C:/Projects/Corvus VST/drippy/NewProject.vst3/Contents/x86_64-win/DrippyMk1.vst3"
```

**Verification Protocol (mandatory after every rebuild):**
1. `git diff --stat -- "drippy/.../DrippyMk1.vst3"` — byte count change
2. `md5sum` of build output vs deployed copy — confirms copy succeeded
3. `git show HEAD:<path> | md5sum` vs `md5sum <path>` — confirms binary differs from HEAD
4. If unchanged → force rebuild: `MSBuild ... -t:Rebuild` (~2.5 min)

---

## Remaining Optimization Opportunities (from dsp-optimization-patterns.md)

- All modules: SIMD (SSE/AVX) for hot inner loops if profiling shows need
- All modules: Profile-guided optimization (PGO) build
- Distortion: Antiderivative antialiasing as alternative to oversampling
- Reverb: Convolution reverb IR option for "real space" mode
- Presets: Add 6+ new presets beyond the current 18

---

## Suggested Next Target: P2 — Polish & Professionalization

1. **Preset refinement** — Adjust 18 preset values by ear; add 6 more
2. **Tooltip / parameter info system** — Hover help for every control
| **P3** | Factory preset categorization | Group by vibe: Clean, Warm, Creative, Extreme | ✅ Done (2026-07-05) |
| **P3** | New presets beyond current 18 | Expand creative palette | ⬜ Deferred |

Phase 0 (Foundation) is now complete. The project has all three core planning docs and a clean "CorvusFX" brand identity in the Jucer/build system.

---

## Environment Notes

- JUCE 8.0.12 at `C:\\Users\\ethan\\Downloads\\juce-8.0.12-windows\\JUCE`
- VS 2026 (v18) — generator must be `"Visual Studio 18 2026"`
- Jucer: `C:\\Users\\ethan\\Downloads\\DrippyFX_v1.0.0_Complete\\NewProject\\NewProject.jucer`
- Solution: `...NewProject\\Builds\\VisualStudio2026\\NewProject.sln`
- CMake: `C:/Program Files/Microsoft Visual Studio/18/Community/Common7/IDE/CommonExtensions/Microsoft/CMake/CMake/bin/cmake.exe`
- Repo workdir: `C:\\Projects\\Corvus VST` (binaries only — source lives in Downloads)
- Cron: `corvus-cron` skill runs 3×/day (9:45am, 1:45pm, 5:45pm) + overnight (6:30am)
- Model: `opencode-go/xiaomi/mimo-v2.5-pro`
- **Always quote paths** — space in "Corvus VST" breaks unquoted commands
- `.obj/.pdb/.exp/.lib/.iobj` in repo are expected VS artifacts — do NOT clean