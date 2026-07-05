# Corvus VST (DrippyFX) — Roadmap

**Project:** Corvus VST / DrippyFX — JUCE 8.0.12 VST3 audio plugin suite  
**Source:** `C:\\Users\\ethan\\Downloads\\DrippyFX_v1.0.0_Complete\\DrippyFX\\`  
**Repo (binaries):** `C:\\Projects\\Corvus VST`  
**Last updated:** 2026-07-05 (Chorus LFO rate caching — hot-loop optimization complete)

---

## Vision

A studio-grade, aliasing-free VST3 multi-FX suite (Distortion → Chorus → Delay → Reverb → Master) with musical parameter response, professional UI, and zero-compromise DSP. Competitive with commercial $50–100 plugins.

---

## Phase 0 — Foundation (Week 1) ✅ *Complete*

- [x] Create PRIORITIES.md (this cycle)
- [x] Create AGENTS.md (this cycle)
- [x] Create ROADMAP.md (this file)
- [x] Rename "NewProject" → "CorvusFX" in Jucer, regenerate solution

---

## Phase 1 — DSP Excellence (Weeks 1–3) ✅ *Substantially Complete*

| Item | Target | Status |
|------|--------|--------|
| 2x oversampling on all saturation (Distortion + Master) | Zero aliasing at any drive | ✅ Done (`a66f658`) |
| Hermite interpolation on Reverb CombFilter | Artifact-free modulated reads | ✅ Done (`7c37e20`) |
| Block-level coefficient caching all hot paths | 4–5 exp/sample → 1/block | ✅ Done (6 commits) |
| Merge master output + limiter into single pass | 4→2 buffer passes | ✅ Done (`b3b4f21`) |
| Push-pull asymmetrical saturation (even harmonics) | Musical warmth via 2nd/4th harmonic | ✅ Done (`f7ed642`) |
| Exponential feedback mapping (Delay) | Musical response across full range | ✅ Done (`bc8e816`) |
| Activate Reverb modulation (`reverb_mod` knob) | Dead knob → working control | ✅ Done (`cf33942`) |
| Fix preset system bounds (18 presets) | DAW program change crash fix | ✅ Done (`b0e960a`) |
| 2x oversampling on Delay tape saturation | Alias-free feedback loop | ✅ Done (`83b59a0`) |
| 2x oversampling on Chorus feedback tanh | Alias-free chorus feedback | ✅ Done (`37bc0c2`) |
| Parameter smoothing (LinearSmoothedValue) all 14 params | Zipper noise elimination | ✅ Done (`b99b59c`) |
| Reverb allpass feedback scaling with room size | Musical diffusion | ✅ Done (`1c3652e`) |
| Chorus LFO rate caching in beginBlock() | 6 divides/sample → 0 | ✅ Done (`d48eaf0`) |

**Remaining P1:**
- [ ] SIMD (SSE/AVX) for hot inner loops — profile first
- [ ] Profile-guided optimization (PGO) build

---

## Phase 2 — Polish & Professionalization (Weeks 3–4)

| Item | Target | Effort |
|------|--------|--------|
| ~~Rename "NewProject" → "CorvusFX" everywhere~~ | Jucer, solution, binary names, DAW metadata | ~~M~~ ✅ Done (`0e65aa6`) |
| ~~Stereo level meters (peak/RMS)~~ | Professional metering with In/Out L/R | ~~M~~ ✅ Done (`57c04aa`) |
| UI responsiveness pass | Resize handling, knob feel, visual feedback | M |
| ~~Parameter smoothing audit (Overall knob)~~ | No zipper noise, musical taper on all knobs | ~~S~~ ✅ Done (`0b1c4d8`) |
| Preset refinement | Adjust 18 preset values by ear; add 6 more | M |
| Tooltip / parameter info system | Hover help for every control | S |
| Factory preset categorization | Group by vibe: Clean, Warm, Creative, Extreme | S |

---

## Phase 3 — Advanced DSP (Month 2)

| Item | Target | Effort |
|------|--------|--------|
| Antiderivative antialiasing (Distortion alt) | Compare vs oversampling; choose best | L |
| Convolution reverb IR mode | "Real space" option alongside algorithmic | L |
| Mid/side processing on Master | Width control, independent M/S saturation | M |
| Per-module bypass with crossfade | Click-free enable/disable | S |
| Oversampling quality modes | 2x / 4x / 8x selectable | M |

---

## Phase 4 — Distribution & Growth (Month 2+)

| Item | Target | Effort |
|------|--------|--------|
| AU / AAX builds | Mac AU, AAX (Windows) | L |
| Installer (Windows) | NSIS/Inno with VST3 path detection | M |
| License / trial system | 14-day trial, machine-bound license | M |
| Website / docs | Product page, manual, changelog | M |
| Preset sharing platform | Community preset exchange | L |

---

## Quality Gates (Every Commit)

From corvus-cron skill — **mandatory verification protocol:**

1. `git diff --stat -- "drippy/.../DrippyMk1.vst3"` — byte count change
2. `md5sum` build output vs deployed copy — copy integrity
3. `git show HEAD:<path> | md5sum` vs `md5sum <path>` — binary differs from HEAD
4. If unchanged → `MSBuild ... -t:Rebuild` (2.5 min)
5. Source grep: verify new function names compiled in
6. `cargo test` equivalent — JUCE test suite if exists

---

## Success Metrics

| Metric | Baseline | Target |
|--------|----------|--------|
| CPU @ 48kHz/64 samples | ~8% (estimated) | <5% |
| Aliasing (THD+N @ 10dB drive) | Audible | Inaudible (<-100dB) |
| Parameter zipper noise | Present on some knobs | None audible |
| Preset recall reliability | Crashed >17 | 100% |
| Binary stale-ship incidents | 2 known | 0 |
| DAW compatibility | Untested broadly | Reaper, Ableton, FL, Logic, Cubase |

---

## Dependencies & Risks

- **JUCE 8.0.12** — pinned; upgrading may break DSP
- **VS 2026 (v18)** — only supported generator; VS 2022 fails
- **Source outside repo** — must edit in Downloads, deploy to repo
- **Space in path** — "Corvus VST" breaks unquoted commands
- **No CI** — local verification only; verify.sh pattern critical
- **Single maintainer** — serial execution

---

## Quick Links

- PRIORITIES.md (this cycle, detailed status)
- AGENTS.md (agent rules)
- corvus-cron skill (automation workflow)
- references/dsp-optimization-patterns.md
- references/verification-pattern.md
- references/oversampling-pattern.md