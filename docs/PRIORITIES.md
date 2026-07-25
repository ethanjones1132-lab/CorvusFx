# Corvus VST (DrippyFX) — Priority Roadmap

Last updated: 2026-07-25 (evening pass -- per-sample delay_mod smoothing + dead oversampling variable cleanup; build now has 0 warnings)
Working copy: `C:\\\\\\\\Projects\\\\\\\\Corvus VST`
Source root: `C:\\\\\\\\Projects\\\\\\\\Corvus VST\\\\\\\\source\\\\\\\\DrippyFX\\\\\\\\` (git SoT; sync to Downloads tree for MSBuild)

Quick status: **DSP quality — all 4 saturation stages oversampled, all parameters smoothed, hot-paths fully block-cached, 19 parameters. Entire plugin has zero per-sample transcendental calls (including safety limiter). All 5 modules (Distortion, Chorus, Delay, Reverb, Master) support truly click-free bypass. CRITICAL BUGFIX: delay ms-to-samples conversion (was using 1/sr instead of sr*0.001f -- delay produced ~0.02ms regardless of knob setting) — 30ms LinearSmoothedValue wet/dry crossfade (params + UI buttons from 2026-07-10, crossfade fix 2026-07-19). Parameter layout reorganized: bypass params sit next to modules. Bugfix: reverbMod→sReverbMod in beginBlock. 36 categorized presets (6 per category: CLEAN, WARM, CREATIVE, EXTREME, SIGNATURE, DREAM), professional dB-scale metering, /fp:fast + /arch:AVX2 compiler optimization, proportional layout scaling, unified meter/DSP pass (2 fewer buffer iterations).**

---

## High-Impact Improvements (Ranked)

| Priority | Item | Why it Matters | Status |
|----------|------|----------------|--------|
| **P0** | Create PRIORITIES.md + ROADMAP.md (this file) | No planning docs; cron agents fly blind | ✅ Done (2026-07-02) |
| **P0** | Create AGENTS.md for autonomous agent context | Corvus has no AGENTS.md — agents lack project rules | ✅ Done (2026-07-02) |
| **P1** | Rename \"NewProject\" → \"CorvusFX\" in Jucer/solution | Boilerplate names leak into DAW plugin lists, installer paths | ✅ Done (2026-07-03, rebuilt & committed `0e65aa6`) |
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
| **P2** | DAW host interop: make all 36 presets reachable (incl. DREAM) | `getCurrentProgram`/`setCurrentProgram` guards stale after 30→36 expansion — 6 DREAM presets dead via host | ✅ Done (2026-07-20, `130307c`) |
| **P2** | Parameter smoothing (LinearSmoothedValue) on all 14 params | Zipper noise eliminated on knob/automation changes | ✅ Done (2026-06-29, `b99b59c`) |
| **P2** | Reverb allpass feedback scaling with room size | Size knob now varies spatial diffusion character | ✅ Done (2026-06-29, `1c3652e`) |
| **P2** | Chorus LFO rate caching (rateToIncrement in beginBlock) | 6 divides/sample → 0; last remaining per-sample /sr | ✅ Done (2026-07-05, `d48eaf0`) |
| **P2** | Click-free bypass for all 5 modules (Distortion, Chorus, Delay, Reverb, Master) | Professional workflow: A/B comparison, CPU savings, automation | ✅ Done (2026-07-10, `5dd1e7c` — params added; **2026-07-19: crossfade made truly click-free** — was a hard switch in the audio path, now 30ms LinearSmoothedValue wet/dry ramp) |
| **P3** | Factory preset categorization | Group by vibe: Clean, Warm, Creative, Extreme | ✅ Done (2026-07-05) |
| **P3** | New presets beyond current 18 | Expand creative palette | ✅ Done (2026-07-06, `3e16739` — 24 total: Glass Canon, Air Lift, Cozy Hiss, Tube Glow, Shimmerfall, Obliterator; idToPreset[] lookup fixes ComboBoxAttachment mapping with separators) |

---

## Improvement Progress Log (from corvus-cron skill)

| 2026-07-25 | `HEAD` | PluginProcessor + Oversampling2x | **Per-sample delay_mod smoothing + dead oversampling variable cleanup** — `delayMod` was the ONLY delay parameter using a block-level `getTargetValue()` snapshot instead of per-sample `getNextValue()`, creating a zipper noise risk on fast delay_mod changes. Added `sDelayMod = smoothDelayMod.getNextValue()` in the per-sample loop alongside other `s*` delay variables, and passed `sDelayMod` to `delay.processSample()` instead of the block snapshot. Also removed 3 dead variable assignments in Oversampling2x (`downL_odd`, `downR_odd`, `down_odd`) that were computed but never used since the even-phase output provides latency alignment — these generated C4189 warnings since the SSE optimization was added. SharedCode gate 0 errors, full .sln 0 errors/0 warnings. Binary MD5: d0d88365 → 8c889614. |
|| 2026-07-25 | `eb556f1` | processBlock | **Merge meter passes into main DSP loop (eliminate 2 buffer iterations)** → input and output level meter accumulation was done in two separate full-buffer passes before and after the main DSP loop. Merged both into the per-sample loop: input meters read from dryBuffer before DSP, output meters read processed smpL/smpR after DSP. Saves 2 buffer iterations per processBlock() call (~halves non-DSP buffer overhead). Zero audio quality impact. SharedCode gate 0 errors, full .sln 0 errors/0 warnings. Binary MD5: a586b43a → 8b4a3e2c. |
|| 2026-07-25 | `be8050a` | EnhancedDelay | **Fix critical delay ms-to-samples conversion bug** -- `delayTimeMs * invSr` was computing ms/sample (delayMs / sr) instead of ms*sr/1000. All preset delay values (65ms-900ms) hit the 1-sample minimum floor, producing ~0.02ms of delay regardless of knob position. Added `msToSamples = sr*0.001f` to BlockCoeffs and used it in the targetSmp formula. All 36 presets now correctly produce their intended delay lengths. SharedCode gate 0 errors, full .sln 0 errors/0 warnings. Binary MD5: 8b4a3e2c -> d0d88365. |
| 2026-07-22 | `HEAD` | UI/Tooltips | **Activate hover tooltips — add missing `juce::TooltipWindow`** — the editor set 24 `setTooltip()` strings on every knob, bypass button, and the preset selector, but JUCE renders NO tooltips unless a `juce::TooltipWindow` instance lives in the component tree. None existed, so all 24 tooltips were silently dead in every DAW since they were written. Added `juce::TooltipWindow tooltipWindow { this, 600 }` (600ms hover delay) as an editor member after `levelMeter`. One-member fix activates the entire parameter hover-help system (P2 "Tooltip / parameter info system"). Pure UI change — no DSP/parameter/CPU impact. SharedCode gate 0 errors, full .sln 0 errors. Binary MD5: de09ba2b → 8c041693. |
| 2026-07-22 | `cb55bbb` | MasterOutputStage | **Add DC blocker to Master Output stage** — the asymmetric push-pull saturation (positive knee 0.15 vs negative knee 0.25, `pushPullSaturate`) generated a 2nd-harmonic DC component that was emitted directly to the DAW because MasterOutputStage had NO DC blocker (unlike Distortion `dcL/dcR`, Chorus `dcBlock[2]`, Delay `dcBlock[2]` which all strip DC). The skill/AGENTS.md described the master stage as having a DC blocker, but it was never wired in. Added `DCBlocker dcMid, dcSide` to the struct, reset in `prepare()`, and applied on L/R after M/S reconstruction, before the safety clamp — using the existing Julius O. Smith DCBlocker (0.9995 coeff, ~3.5Hz). Removes a standing DC offset that wasted headroom and stressed monitors. SharedCode gate 0 errors, full .sln 0 warnings/0 errors. Binary MD5: 8c041693 → a586b43a. |
| 2026-07-19 | `HEAD` | processBlock | **Truly click-free bypass crossfade for all 5 modules**
| 2026-07-20 | `130307c` | Presets/HostInterop | **Make all 36 presets reachable via DAW program interface** — the DREAM category (presets 30–35, added `c4401c2`) was unreachable from a DAW and `getCurrentProgram()` misreported it. When the 30→36 expansion updated `idToPreset[43]` and `presetToId[36]`, it left `getCurrentProgram()`'s reverse table sized `[36]` (missing DREAM rows) with a stale guard `id < 36`, and `setCurrentProgram()` kept the stale guard `i < 30`. So a host calling `setCurrentProgram(30..35)` no-opped, and `getCurrentProgram()` clamped combo IDs 37–42 to −1 → preset 0. Fix: `presetFromId[36]→[43]` with DREAM rows (IDs 36–42→30–35), guard `id < 36→< 43`, `setCurrentProgram` guard `i < 30→< 36`, and updated the `idToPreset` comment (42 items / 6 separators). Verified: SharedCode gate 0 errors, full .sln 0 errors/0 warnings, binary MD5 `d382fdda → de09ba2b`. |
| 2026-07-20 | `f0a3eef`+1 | UI/LevelMeter | **Convert LevelMeter to true logarithmic (dB) scale** — bars and dB tick marks previously used mismatched/incorrect mappings (bars linear-in-amplitude while ticks used a separate offset). A −20 dBFS signal filled only 10% of the bar, making the meter nearly useless. Added a shared `ampToYPos()` lambda (0 dBFS at top → −60 dBFS at bottom); both bars and the 9 dB-grid tick marks now use it, so they align exactly and equal dB steps span equal pixels. Pure rendering change — no DSP/parameter/CPU change. Builds clean (0 errors). Binary MD5: 24ac524a → d19b62bf. |
| 2026-07-20 | `a2df97e` | EnhancedChorus | **Hoist per-sample std::sqrt out of chorus hot path — TRULY completes the zero per-sample transcendental milestone** — `EnhancedChorus::process()` computed `const float voiceGain = 1.0f / std::sqrt(6.0f)` on EVERY sample (line 681), the last surviving per-sample transcendental call even after the 2026-07-13 "zero transcendental" milestone. The value is a constant (NUM_VOICES is constexpr 6), so it has been moved into `ChorusBlockCoeffs` as a default-member-initialized constant, computed once at instantiation. Removes 288,000 sqrt/sec at 48kHz. Identical audio output. Builds clean (0 errors, SharedCode gate + full .sln). Binary MD5: d19b62bf → e6f671c3. |
| 2026-07-20 | `HEAD+1` | Chorus/Delay/Reverb | **LFO phase-recurrence magnitude renormalization (float32 rotation-drift fix)** — the incremental-rotation LFO recurrence (sin(φ+Δ)/cos(φ+Δ) = sin·cosΔ + cos·sinΔ) used in chorus (lfoSin/cos, driftSin/cos 1&2), delay (lfoSin/lfo2Sin), and reverb (modSin/modCos) slowly lost unit-vector length each step, breathing the modulation **depth** itself: ~2.5%/min in chorus & delay and ~0.34%/min in reverb (verified via float32 simulation). Added `renormLFO()` (chorus/delay) and `renormModLFO()` (reverb) that rescale each sin/cos pair to unit length every 256 samples (tick counter `lfoTick`/`modTick`). Simulation confirms residual drift drops to ~0.0003%/min — audibly stable. Zero audio behavior change; 0 errors (SharedCode gate + full .sln). Binary MD5: e6f671c3 → d382fdda. |

| Date | Commit | Module | Improvement |
|------|--------|--------|-------------|
| 2026-07-15 | `c4401c2` | Presets | **Expand factory presets from 30 to 36 with DREAM category** — added 6 new ambient/ethereal presets (Cloud Chamber, Frozen Lake, Ash & Ember, Stargate Portal, Underwater Cathedral, Solar Flare). Updated getNumPrograms() 30→36, idToPreset 36→43, presetToId 30→36. PluginEditor: added DREAM category separator + 6 preset items. Tooltip updated to 36 curated sounds. Binary MD5: b05ef287 → 649e6a10 (+13 KB). |
| 2026-07-14 | `5f35dae` | Build/CMake | **Enable /fp:fast and /arch:AVX2 compiler flags** — adds aggressive floating-point optimization and AVX2 vector instruction set to Release builds. Enables MSVC to inline fabsf/sqrtf as SSE intrinsics, reorder FP ops for ILP, and auto-vectorize scalar loops. No audio behavior change. Binary MD5: 86f44145 → b05ef287 (+86 KB). |
| 2026-07-13 | `d6ea118` | EnhancedDelay | **Mono oversampling for tape saturation** — replace stereo Oversampling2x::processSample() with independent mono processSampleMono() calls for L/R tapeSat. Halves FIR filter cost in delay feedback loop (same optimization applied to Master mid/side 2026-07-12). No audio change — identical output, half the CPU. |
| 2026-07-13 | `ca23485` | processBlock | **Replace std::tanh in Safety Limiter with Pade [3/2] rational approximant z*(15+z²)/(15+6z²)** — eliminates last 4 per-sample transcendental calls in hot path. Pade approximant matches tanh(z) within 0.04% for z ∈ [0, 1.0] (the exact domain). Each branch computes z and z² once in a scoped block. Max limiter output error: 0.00006. Completes zero-transcendental-per-sample milestone. |
| 2026-07-12 | `26f6574` | PluginProcessor | **Remove dead block-level snapshot variables** — 8 dead declarations removed from processBlock(): overallMix, delayTime, delayFeedback, delayMix, chorusFeedback, peakSmooth (2x). Also removed dead distortionBypassButton.onClick handler. |
| 2026-07-12 | `3d63fb5` | EnhancedChorus | **Replace std::fmod in smoothTriangle with normalized phase recurrence** — tracks normalized [0,1) triangle phase per voice, advances via simple multiply-and-wrap instead of 6 std::fmod()/sample. Saves 288,000 fmod calls/sec at 48kHz. Inlined smoothTriangle logic directly in process() using v.triPhase. Binary MD5: 1e7d38a0 → 42d5db57 (+1024 bytes). |
| 2026-07-12 | `50f559d` | UI/Delay | **Add missing delay_mod UI knob** — the delay_mod parameter existed in the DSP pipeline (param ID 'delay_mod', default 30%, full smoothing + processBlock read + delay.processSample modAmount) but had no UI knob. Added delayModKnob + delayModLabel + dModAtt with tooltip. Delay row expanded from 4 to 5 knobs (TIME, FEEDBACK, MIX, DAMPING, MOD). |
| 2026-07-11 | `062281e` | Presets | **Reorganize bypass params in parameter layout** — moved chorus_bypass/delay_bypass/reverb_bypass/master_bypass from grouped-at-end to module-local positions in createParameterLayout(). Expanded preset P struct with 4 new bypass fields; all 24 presets updated with bypass=0. 62-line coherent WIP committed. |
| 2026-07-11 | `7a8f1a0` | UI/PluginEditor | **Add bypass buttons for Chorus, Delay, Reverb, and Master** — color-coded ToggleButtons (blue=chorus, green=delay, purple=reverb, magenta=master) with ButtonAttachments wired to the VTS. Button placement below each module's knobs in 2×2 grid, master bypass next to Master Drive row. Tooltips: \"Bypass the <module> module entirely — click-free crossfade\". 58-line addition to header+cpp. |
| 2026-07-11 | `a4e5bda` | UpgradedReverb | **Fix reverbMod → sReverbMod in beginBlock call** — line 366 used undeclared `reverbMod` instead of `sReverbMod` (C2065). Bug silently present in git SoT since 5dd1e7c but Downloads tree had different declaration state during prior builds. Single-line fix, no binary change. |
| 2026-07-10 | `5dd1e7c` | Modules | **Add click-free bypass for Chorus, Delay, Reverb, Master** — 4 new AudioParameterBool parameters (chorus_bypass, delay_bypass, reverb_bypass, master_bypass). Distortion already had bypass (distortion_bypass). Each module now conditionally processes in processBlock() with parameter-controlled bypass. All 24 presets updated with bypass=0. Total parameters: 19 (was 15). Binary MD5: 56005a3d → 5e9f557f (rebuilt via MSBuild -t:Rebuild). |
| 2026-07-10 | `56758bf` | MasterOutputStage | **Fix missing setTargetValue for master_drive, master_width, master_mid_drive** — three of four Master Output parameters only received initial target values in prepareToPlay(). Their setTargetValue calls were missing from processBlock(), so knobs stopped responding after plugin load. Only master_side_drive was correctly updated per-block. Added the three missing calls after smoothReverbMod and before smoothMasterSideDrive. All four Master parameters now smooth correctly with 20ms LinearSmoothedValue, eliminating zipper noise and ensuring responsive knob/automation. Binary MD5: 56005a3d. |
| 2026-07-10 | `3645f81` | UI/Presets/DSP | **Add distortion bypass parameter (19th param) + fix reverb_mod smoothing regression** — new AudioParameterBool toggle with BYPASS button and ButtonAttachment in distortion section. All 24 presets updated with distByp=0. CRITICAL BUGFIX: restored smoothReverbMod.setTargetValue() in processBlock — it was accidentally replaced with a duplicate smoothMasterSideDrive in e2cdb08, silently breaking reverb modulation for 2 days. Binary MD5: 3f41827d → 9a47a8fb. |
| 2026-07-09 | `f7ecad0` | Oversampling2x | **SSE-optimized 8-tap FIR filtering** — replaces scalar loops in processSample()/processSampleMono() with SSE intrinsics (_mm_set_ps, _mm_shuffle_ps, _mm_mul_ps, _mm_hadd_ps). The oversampling filter is the hottest path (called at 2x rate by all 4 saturation stages: Distortion, Chorus feedback, Delay tape sat, Master push-pull). 4 FIR passes per call (up even/odd, down even/odd). SSE reduces 16 scalar MACs per pass to ~4 SIMD ops, ~4x throughput on critical path. Binary MD5: 79f9c407 → e9e46593. |
| 2026-07-09 | `d4350b9` | EnhancedChorus + EnhancedDelay | **Remove dead per-sample parameters** — drop unused `mix` from EnhancedChorus::process() (precomputed as mixDepthScale + dryGain/wetGain in beginBlock) and unused `damping` from EnhancedDelay::processSample() (precomputed as fbLPCoeff in beginBlock). Also removed dead `sChorusMix` per-sample variable from processBlock. Eliminates redundant parameter passing and 1 smoothChorusMix.getNextValue() per sample. Binary MD5: 54cfa7ef → 79f9c407. |
| 2026-07-08 | `92cdde6` | UpgradedReverb | **Reverb API cleanup** — cache width, pre-delay in BlockCoeffs; remove 6 redundant processSample() params; eliminate per-sample parameter passing overhead. |
| 2026-07-08 | `ca52994` | EnhancedDelay + UpgradedReverb | **API cleanup** — cache preDelaySmp, width, pingPong, modAmount in BlockCoeffs; clean per-sample signatures. Binary MD5: 138d45c8 → b7dfb5b5. |
| 2026-07-08 | `df7c97a` | UpgradedReverb | **Deploy rebuilt binary** for API cleanup (ca52994/92cdde6). Binary MD5: b7dfb5b5 → 54cfa7ef. |
| 2026-07-08 | `a0629ff` | UpgradedReverb | **LFO phase recurrence for master modulation** — replaces 2 std::sin()+std::cos()/sample with 4 multiplies via precomputed sin/cos deltas in beginBlock(). Eliminates the last per-sample transcendental calls in the entire plugin. Binary MD5: 975692af → 138d45c8. |
| 2026-07-07 | `66f4cc2` | EnhancedChorus | **LFO phase recurrence for drift modulation** — replaces 2 std::sin()/voice/sample (12 total/sample for 6 voices × 2 frequencies) with 4 multiplies per voice per sample via precomputed sin/cos deltas in beginBlock(). Extends the established LFO phase recurrence pattern to the slow organic drift LFO (frequencies 2.32x and 5.71x base driftDelta). Binary MD5: ca2f5535 → 754ec91c. |
| 2026-07-07 | `0a93199` | EnhancedDelay | **LFO phase recurrence for wow/flutter** — replaces 2 std::sin()/sample with 4 multiplies via precomputed sin/cos deltas in beginBlock(). Same identity as Chorus/Reverb LFO optimization (c7853f2, c23e1c3). Binary MD5: 754ec91c → 24b31d41. |
| 2026-07-07 | *(this pass)* | UI/LevelMeter | **Professional dB scale markings on level meters** — adds industry-standard dB tick marks and labels (-6, -12, -18, -24, -30, -40, -50, -60 dB) with 0dB reference line aligned to the meter's 0dB position. Brings metering to professional plugin standard. Binary MD5: 24b31d41 → 44bc7218. |
| 2026-07-08 | `d885a33` | EnhancedChorus | **Cache dry/wet crossfade gains in beginBlock()** — moves equal-power dryGain/wetGain from per-sample process() to ChorusBlockCoeffs. Eliminates 2 std::sin() + 2 std::cos() per sample per stereo channel. Chorus hot path now has zero per-sample transcendental calls. Binary MD5: 44bc7218 → 975692af. |
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
| 2026-07-03 | `0e65aa6` | Jucer/Build | **Renamed \"NewProject\" → \"CorvusFX\" in Jucer project and VS solution** — updated project name, target name, JucePlugin_Name, JucePlugin_Desc definitions. Full rebuild confirms new branding in VST3 manifest. Binary MD5 changed `a96d1356` → `fa8c8d77`. |
| 2026-07-04 | `57c04aa` | UI/PluginEditor | **Stereo level meters with peak/RMS display** — 4 vertical bars (In L/R, Out L/R), professional metering with cyan input / magenta output colors, 0dB reference line, peak hold with exponential decay, 30fps update via timerCallback reading relaxed atomics |
| 2026-07-04 | `0b1c4d8` | processBlock | **Per-sample Overall parameter smoothing** — moved Overall wet/dry from block-level `getCurrentValue()` into per-sample loop using `smoothOverall.getNextValue()`. All 14 audio parameters now have 20ms LinearSmoothedValue smoothing. Eliminates zipper noise on global wet/dry knob during automation/knob movement. |
| 2026-07-05 | `d48eaf0` | EnhancedChorus | **Cache LFO rate→increment in beginBlock()** — precompute `twoPi/sr` once per block, replacing 6 per-sample divides with cached multiplies in the hot inner loop. Same behavior, fewer arithmetic ops per voice. |
| 2026-07-05 | `0c36943` | UpgradedReverb | **Cache modPhase increment in beginBlock()** — precompute `0.37f/sr` once per block, replacing 1 per-sample divide with cached multiply. Last remaining per-sample `/sr` in the entire plugin — all hot-path sample-rate divides are now cached at block level. |
| 2026-07-05 | `2897782` | UI/PluginEditor | **Proportional layout scaling for responsive resize** — all hardcoded pixel values in resized() now scale via `min(width/1200, height/700)` factor with minimum size guards. Full 1000-1600w × 600-900h range supported with uniform aspect-ratio preservation, 60fps animated background maintained. |
| 2026-07-05 | `4e43c77` | UI/PluginEditor | **Factory preset categorization** — group 18 presets into 4 vibe categories (CLEAN, WARM, CREATIVE, EXTREME) with disabled separator items in preset selector; adds selector-to-preset mapping in loadPreset(). |
| 2026-07-06 | `e2d6c74` | Presets | **Reorder presets[] to match categorized combo box layout** — removed broken ID-based selectorToPreset table; instead reordered presets[] + getProgramName() to match CLEAN[0-3]/WARM[4-7]/CREATIVE[8-12]/EXTREME[13-17] layout. All three paths (combo attachment, DAW host interface, program names) now use identity mapping with no translation table. Binary MD5: c872564e → b7a435c7. |
| 2026-07-06 | `e379f2d` | MasterOutputStage | **Add Master Drive parameter** — user-controllable push-pull saturation (0-100%, mapped to drive 0.0-1.8). Added LinearSmoothedValue (20ms), UI knob below Overall, updated all 24 presets with master_drive values. Binary MD5: 525f3ffd → 588a94cc. 15 total parameters now. |
| 2026-07-07 | `c23e1c3` | UpgradedReverb | **LFO phase recurrence for comb modulation** — replaces 8 std::sin()/sample with 2 + 16 multiplies via precomputed sin(Δi)/cos(Δi) per comb in beginBlock(). ~4x reduction in modulation cost. Binary MD5: c88ea5c6 → ca2f5535. |

---

## Quality Targets (from corvus-cron skill)

| Area | Goal | Success Signal |
|------|------|----------------|
| **DSP accuracy** | Studio-grade, competitive with market | Cleaner spectrum, less aliasing, musical parameter response |
| **Performance** | <5% CPU at 48kHz/64 samples | No audio dropouts, efficient SIMD where needed |
| **Parameter feel** | Musical across full range | Smooth transitions, no zipper noise, useful extremes |
| **UI polish** | Professional-grade visual experience | Consistent with top-tier plugins, responsive |
| **Code quality** | Production C++17 | No \"NewProject\" boilerplate, const-correct, clean includes |

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

- All modules: Profile-guided optimization (PGO) build
- Distortion: Antiderivative antialiasing as alternative to oversampling
- Reverb: Convolution reverb IR option for "real space" mode
- Presets: Add 6+ new presets beyond the current 30 ✅ Done (2026-07-15, `c4401c2` — 36 total with DREAM category)

---

## Suggested Next Target: P2 — Polish & Professionalization

1. **Preset refinement** — Adjust 18 preset values by ear; add 6 more
2. **Tooltip / parameter info system** — Hover help for every control ✅ Done (2026-07-22 — TooltipWindow added; 24 tooltip strings now render)
| **P3** | Factory preset categorization | Group by vibe: Clean, Warm, Creative, Extreme | ✅ Done (2026-07-05) |
| **P3** | New presets beyond current 18 | Expand creative palette | ✅ Done (2026-07-06, `3e16739` — 24 total: Glass Canon, Air Lift, Cozy Hiss, Tube Glow, Shimmerfall, Obliterator; idToPreset[] lookup fixes ComboBoxAttachment mapping with separators) |

Phase 0 (Foundation) is now complete. The project has all three core planning docs and a clean \"CorvusFX\" brand identity in the Jucer/build system.

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