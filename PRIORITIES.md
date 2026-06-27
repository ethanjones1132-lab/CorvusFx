# Corvus VST (DrippyFX) — Priority Roadmap

Last updated: 2026-06-27 (Guardian Agent morning report)
Working copy: `C:\Projects\Corvus VST`
Source root: `C:\Users\ethan\Downloads\DrippyFX_v1.0.0_Complete\DrippyFX\`

Quick status: **No planning docs existed — creating baseline from corvus-cron skill improvement log**

---

## High-Impact Improvements (Ranked)

| Priority | Item | Why it Matters | Status |
|----------|------|----------------|--------|
| **P0** | Create PRIORITIES.md + ROADMAP.md (this file) | No planning docs; cron agents fly blind | ⬜ Pending |
| **P0** | Create AGENTS.md for autonomous agent context | Corvus has no AGENTS.md — agents lack project rules | ⬜ Pending |
| **P1** | Rename "NewProject" → "CorvusFX" in Jucer/solution | Boilerplate names leak into DAW plugin lists, installer paths | ⬜ Pending |
| **P1** | Verify 2x oversampling on all saturation stages (Distortion + Master) | Alias-free saturation at any drive — latest major improvement | ✅ Done (2026-06-27, `a66f658`) |
| **P1** | Hermite interpolation on Reverb CombFilter | Modulated delay reads artifact-free — matches Delay/Chorus | ✅ Done (2026-06-26, `7c37e20`) |
| **P1** | Block-level coefficient caching on all hot paths | 4–5 exp/sample → 1/block across Distortion, Delay, Reverb, Master | ✅ Done (2026-06-24 to 2026-06-26) |
| **P1** | Merge master output + limiter into single per-sample pass | 4→2 buffer passes in processBlock | ✅ Done (2026-06-26, `b3b4f21`) |
| **P2** | Push-pull asymmetrical saturation (even harmonics) | Musical warmth via 2nd/4th harmonic asymmetry | ✅ Done (2026-06-26, `f7ed642`) |
| **P2** | Exponential feedback mapping on Delay | Musical response across full knob range | ✅ Done (2026-06-24, `bc8e816`) |
| **P2** | Activate Reverb modulation (`reverb_mod` knob) | Knob existed but was dead code | ✅ Done (2026-06-24, `cf33942`) |
| **P2** | Preset system: fix `setCurrentProgram` bounds for all 18 presets | DAWs crashed on program change >17 | ✅ Done (2026-06-24, `b0e960a`) |
| **P3** | SIMD (SSE/AVX) for hot inner loops | Further CPU reduction if profiling warrants | ⬜ Deferred |
| **P3** | UI polish: responsive resize, knob feel, visual feedback | Professional aesthetics parity | ⬜ Deferred |
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

---

## Suggested Next Target: P0 — Planning Docs

1. **Create AGENTS.md** (project rules for autonomous agents — see corvus-cron skill for template)
2. **Finalize this PRIORITIES.md** as living roadmap
3. **Create ROADMAP.md** (consolidated view for humans)
4. **Rename "NewProject" → "CorvusFX"** in `.jucer`, regenerate solution — cleans DAW metadata

---

## Environment Notes

- JUCE 8.0.12 at `C:\Users\ethan\Downloads\juce-8.0.12-windows\JUCE`
- VS 2026 (v18) — generator must be `"Visual Studio 18 2026"`
- Jucer: `C:\Users\ethan\Downloads\DrippyFX_v1.0.0_Complete\NewProject\NewProject.jucer`
- Solution: `...NewProject\Builds\VisualStudio2026\NewProject.sln`
- CMake: `C:/Program Files/Microsoft Visual Studio/18/Community/Common7/IDE/CommonExtensions/Microsoft/CMake/CMake/bin/cmake.exe`
- Repo workdir: `C:\Projects\Corvus VST` (binaries only — source lives in Downloads)
- Cron: `corvus-cron` skill runs 3×/day (9:45am, 1:45pm, 5:45pm) + overnight (6:30am)
- Model: `opencode-go/xiaomi/mimo-v2.5-pro`
- **Always quote paths** — space in "Corvus VST" breaks unquoted commands
- `.obj/.pdb/.exp/.lib/.iobj` in repo are expected VS artifacts — do NOT clean