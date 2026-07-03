# AGENTS.md — Corvus VST (DrippyFX) Agent Working Rules

This file gives autonomous AI agents the minimal project-specific context needed to work safely in this repo.

---

## What This Repo Is

**Corvus VST** (brand name for **DrippyFX**) — a JUCE 8.0.12 VST3 audio plugin suite with 4 cascade effect modules + Master Output:

| Module | Type | Key Features |
|--------|------|--------------|
| **Distortion** | Saturation | Tape→tube blend, pre-emphasis, 2-pole post filter, warmth shelf, DC blocker, **2x oversampling** |
| **Chorus** | 6-voice modulation | Hermite interpolation, multi-shape LFO, mix-adaptive depth, per-voice allpass, decorrelated rates |
| **Delay** | Tape-style | Ping-pong, Hermite interp, tape wow/flutter, filtered feedback, soft saturation, exponential feedback mapping |
| **Reverb** | Freeverb-inspired | 8 comb filters + 4 allpasses, modulation (`reverb_mod` knob active), pre-delay, damping, **Hermite interpolation** |
| **Master Output** | Multi-stage | Push-pull asymmetrical saturation (2nd/4th harmonics), multi-band processor, DC blocker, peak limiter, **2x oversampling** |

**18 presets** spanning Clean Sparkle → Warm Glow → Dreamy Space → Thick Sauce → etc.

---

## Source of Truth

**Source code lives OUTSIDE the repo at:**
```
C:\Users\ethan\Downloads\DrippyFX_v1.0.0_Complete\DrippyFX\
```

| File | Purpose |
|------|---------|
| `PluginProcessor.h` | DSP engine — `ProfessionalDistortion`, `EnhancedChorus`, `EnhancedDelay`, `UpgradedReverb`, `MasterOutputStage` |
| `PluginProcessor.cpp` | Audio processor — parameter layout, `processBlock`, preset system, state save/load |
| `PluginEditor.h` | UI — `AnimatedKnob`, `CorvusLookAndFeel`, `AnimatedBackground`, section headers |
| `PluginEditor.cpp` | Editor layout — all knob setup, attachments, 2x2 grid layout |
| `CMakeLists.txt` | CMake build config (VST3 + AU + Standalone) |

**Repo workdir (binaries only):** `C:\Projects\Corvus VST`
- `drippy/NewProject.vst3/Contents/x86_64-win/DrippyMk1.vst3` — deployed VST3 binary
- `.obj`, `.pdb`, `.exp`, `.lib`, `.iobj` — VS build artifacts (DO NOT DELETE)

---

## Absolute Rules for Agents

### 1. Source lives outside the repo — ALWAYS edit files in Downloads, NOT in the repo workdir
```bash
# Correct source path:
C:\Users\ethan\Downloads\DrippyFX_v1.0.0_Complete\DrippyFX\PluginProcessor.cpp

# Wrong (repo only has binaries):
C:\Projects\Corvus VST\...
```

### 2. One improvement per run — pick the highest-impact item and complete it
Don't scatter-gun fixes. Follow the priority order in PRIORITIES.md.

### 3. Follow conventional commit format
```
quality(scope): description

What changed, why, measured impact where possible.
```

### 4. Verify every rebuild — 3-step protocol (MANDATORY)
After ANY binary rebuild:
1. `git diff --stat -- "drippy/.../DrippyMk1.vst3"` — byte count change
2. `md5sum` of build output vs deployed copy — confirms copy succeeded
3. `git show HEAD:<path> | md5sum` vs `md5sum <path>` — confirms binary differs from HEAD

**If binary unchanged (same MD5 as HEAD) → force rebuild:**
```bash
MSBuild ... -t:Rebuild
```

### 5. Always quote paths — space in "Corvus VST" breaks unquoted commands
```bash
# Correct:
"C:/Projects/Corvus VST/drippy/..."
"C:/Users/ethan/Downloads/DrippyFX_v1.0.0_Complete/DrippyFX/..."

# Wrong (fails silently):
C:/Projects/Corvus VST/drippy/...
```

### 6. Preserve binary naming — `DrippyMk1.vst3` / `DrippyMk2.vst3`
DAWs may reference these paths.

### 7. Do NOT delete VS build artifacts — `.obj`, `.pdb`, `.exp`, `.lib`, `.iobj` are expected in repo

---

## Build & Deploy Pipeline

**Preferred: MSBuild (fast, incremental, no juceaide timeout)**
```bash
"C:/Program Files/Microsoft Visual Studio/18/Community/MSBuild/Current/Bin/amd64/MSBuild.exe" ^
  "C:/Users/ethan/Downloads/DrippyFX_v1.0.0_Complete/NewProject/Builds/VisualStudio2026/NewProject_VST3.vcxproj" ^
  -p:Configuration=Release -p:Platform=x64 -m
```
Output binary:
`C:/Users/ethan/Downloads/DrippyFX_v1.0.0_Complete/NewProject/Builds/VisualStudio2026/x64/Release/VST3/NewProject.vst3/Contents/x86_64-win/NewProject.vst3`

**Deploy:**
```bash
cp "C:/Users/ethan/Downloads/DrippyFX_v1.0.0_Complete/NewProject/Builds/VisualStudio2026/x64/Release/VST3/NewProject.vst3/Contents/x86_64-win/NewProject.vst3" ^
   "C:/Projects/Corvus VST/drippy/NewProject.vst3/Contents/x86_64-win/DrippyMk1.vst3"
```

**Alternative: CMake (slower — juceaide bootstrap 2-5 min)**
```bash
export JUCE_PATH="C:/Users/ethan/Downloads/juce-8.0.12-windows/JUCE"
cd "C:/Users/ethan/Downloads/DrippyFX_v1.0.0_Complete/DrippyFX"
"C:/Program Files/Microsoft Visual Studio/18/Community/Common7/IDE/CommonExtensions/Microsoft/CMake/CMake/bin/cmake.exe" ^
  -G "Visual Studio 18 2026" -A x64 -DJUCE_PATH="$JUCE_PATH" -S . -B build
"C:/Program Files/Microsoft Visual Studio/18/Community/Common7/IDE/CommonExtensions/Microsoft/CMake/CMake/bin/cmake.exe" ^
  --build build --config Release
```

---

## Quality Improvement Workflow (Per Cron Run)

### 1. Source Analysis
Review `C:\Users\ethan\Downloads\DrippyFX_v1.0.0_Complete\DrippyFX\` for:
- **DSP quality**: Algorithm improvements (saturation curves, filter topologies, delay interpolation)
- **Unused parameters**: `/*unused*/`, commented-out params, received-but-never-referenced — these are dead UI controls
- **Parameter mapping**: Knob ranges musically useful? Log/exp scaling needed?
- **Host interop**: `getNumPrograms()`, `setCurrentProgram()`, `getProgramName()`, `getCurrentProgram()` — all agree on count/index?
- **Performance**: Hot loops (per-sample) → SIMD, pre-computation, block processing? See `references/dsp-optimization-patterns.md`
- **Cleanup**: Debug `DBG()` calls, unused code paths, stale comments
- **Presets**: 18 presets need refinement or additions?
- **Naming**: "NewProject" boilerplate → "CorvusFX"?
- **UI polish**: Layout, responsiveness, visual improvements

### 2. Prioritize & Implement
Pick **single highest-impact** improvement:
1. DSP quality (smoother filters, better modulation, anti-aliasing, oversampling)
2. Parameter improvements (ranges, smoothing, tooltips)
3. Performance (SIMD, pre-compute, block processing)
4. Code quality (rename artifacts, dead code, structure)
5. Preset refinement (values, new presets)
6. UI/UX improvements

### 3. Rebuild → Verify → Commit

---

## Completed Improvements (Progress Log)

| Date | Commit | Module | Improvement |
|------|--------|--------|-------------|
| 2026-06-24 | `b0e960a` | Presets | Fix `setCurrentProgram` bounds for all 18 presets |
| 2026-06-24 | `cf33942` | Reverb | Activate comb filter modulation (`reverb_mod` knob now works) |
| 2026-06-24 | `bc8e816` | Delay | Exponential feedback mapping for musical response |
| 2026-06-24 | `4db06cc` | Distortion | Block-level coefficient cache (4 exp/sample → 1/block) |
| 2026-06-25 | `6bf1278` | Master + Chorus | Block-level coefficient cache (5 exp/sample → 1/block) |
| 2026-06-25 | `61c197f` | EnhancedDelay | Block-level coefficient cache for feedback LP/HP (2 exp/sample → 1/block) |
| 2026-06-25 | `60f3dc1` | UpgradedReverb | Block-level cache: hoisted 8× setFeedback/setDamp + mod calc |
| 2026-06-26 | `b3b4f21` | processBlock | Merge master output + safety limiter into main loop (4→2 buffer passes) |
| 2026-06-26 | `f7ed642` | MasterOutputStage | Push-pull asymmetrical saturation: even-harmonic warmth, drive=1.8x |
| 2026-06-26 | `7c37e20` | UpgradedReverb | Hermite cubic interpolation for modulated reads |
| 2026-06-27 | `a66f658` | Distortion + Master | **2x oversampling** for zero aliasing (Oversampling2x, 2nd-order half-band FIR, 8 taps) |
| 2026-06-28 | `83b59a0` | EnhancedDelay | **2x oversampling** for tape saturation in feedback loop — eliminates aliasing in delay tail |
| 2026-06-29 | `b99b59c` | processBlock | **Parameter smoothing (LinearSmoothedValue)** on all 13 audio parameters — 20ms smoothing eliminates zipper noise from knob movement and host automation. Previously, raw atomic reads jumped instantly between blocks. |
| 2026-06-29 | `1c3652e` | UpgradedReverb | **Allpass feedback scales with room size** (0.50→0.70) — Size knob now varies diffusion character. Also hoisted comb setFeedback/setDamp loop from per-sample to per-block in beginBlock(). |
| 2026-06-30 | `3936329` | processBlock | **ScopedNoDenormals fix** — moved from outer function scope into per-sample loop, fixing redundant reconstruction on every iteration. Single RAII object per block eliminates per-sample stack object creation/destruction overhead. |
| 2026-07-01 | `37bc0c2` | EnhancedChorus | **2x oversampling for feedback tanh anti-aliasing** — wrapped the tanh feedback saturation in Oversampling2x (8-tap half-band FIR). Eliminates aliasing artifacts from the non-linear feedback loop that compound with each iteration. Now all 4 saturation stages (Distortion, Chorus, Delay, Master) run at 2x sample rate. |
|| 2026-07-03 | `0e65aa6` | Jucer/Build | **Renamed "NewProject" → "CorvusFX" in Jucer project and VS solution** — updated project name, target name, JucePlugin_Name, JucePlugin_Desc definitions. Full rebuild confirms new branding in VST3 manifest. Binary MD5 changed `a96d1356` → `fa8c8d77`. |

---

## Remaining Optimization Opportunities

- All modules: SIMD (SSE/AVX) for hot inner loops if profiling shows need
- All modules: Profile-guided optimization (PGO) build
- Distortion: Antiderivative antialiasing as alternative to oversampling
- Reverb: Convolution reverb IR option for "real space" mode

---

## Quality Targets

| Area | Goal | Success Signal |
|------|------|----------------|
| **DSP accuracy** | Studio-grade, competitive | Cleaner spectrum, less aliasing, musical parameter response |
| **Performance** | <5% CPU at 48kHz/64 samples | No audio dropouts, efficient SIMD where needed |
| **Parameter feel** | Musical across full range | Smooth transitions, no zipper noise, useful extremes |
| **UI polish** | Professional-grade visual | Consistent with top-tier plugins, responsive resizing |
| **Code quality** | Production C++17 | No "NewProject" boilerplate, const-correct, clean includes |

---

## Known Pitfalls

1. **MSBuild incremental misses header changes** — after modifying `.h` files, incremental build may succeed in <1s with **identical binary**. Always run 3-step verification.
2. **CMake generator must be "Visual Studio 18 2026"** — machine has VS2026 (v18), NOT VS2022 (v17). Wrong generator → MSB8020.
3. **CMake juceaide timeout** — first configure builds juceaide from scratch (2-5+ min). 120s terminal timeout insufficient. Prefer MSBuild.
4. **MSBuild property syntax in git-bash/MSYS** — use `-p:Configuration=Release` NOT `/p:` (MSYS converts `/p:` to filesystem path).
5. **JUCE_PATH must be set** — required by CMakeLists.txt and build scripts.
6. **Space in "Corvus VST"** — always quote paths.
7. **Plugin code name mismatch** — `.jucer` says "NewProject" but processor class is `CorvusFXAudioProcessor`, DSP files in `DrippyFX/`. Fix by updating `.jucer` and regenerating.

---

## Environment

- **JUCE SDK:** `C:\Users\ethan\Downloads\juce-8.0.12-windows\JUCE`
- **VS 2026 (v18):** `C:/Program Files/Microsoft Visual Studio/18/Community/`
- **Jucer project:** `C:\Users\ethan\Downloads\DrippyFX_v1.0.0_Complete\NewProject\NewProject.jucer`
- **VS Solution:** `...NewProject\Builds\VisualStudio2026\NewProject.sln`
- **CMake:** `C:/Program Files/Microsoft Visual Studio/18/Community/Common7/IDE/CommonExtensions/Microsoft/CMake/CMake/bin/cmake.exe`
- **Repo workdir:** `C:\Projects\Corvus VST` (binaries only)
- **Branch:** master
- **Cron:** `corvus-cron` skill (3×/day 9:45am/1:45pm/5:45pm + overnight 6:30am)
- **Model:** `opencode-go/xiaomi/mimo-v2.5-pro`
- **Toolsets:** terminal, file, coding

---

## Support Files (in corvus-cron skill)

- `references/dsp-optimization-patterns.md` — Block-level coefficient pre-computation pattern
- `references/oversampling-pattern.md` — 2x oversampling implementation details
- `references/verification-pattern.md` — Ad-hoc verification script template & checklist