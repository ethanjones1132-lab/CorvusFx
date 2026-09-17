/*
    CorvusDspTests — Corvus Instrument vertical slice, Plan Task 1 Step 1.

    Plan source of truth (read before every change here):
    docs/superpowers/plans/2026-08-08-corvus-instrument-vertical-slice.md
    Task 1 "Add a deterministic JUCE test target and baseline FX fixture"

    CorvusEffectsBaselineTest includes the DSP section of PluginProcessor.h and
    renders a deterministic stereo impulse through the five shared effect structs
    in chain order — ProfessionalDistortion, EnhancedChorus, EnhancedDelay,
    UpgradedReverb, MasterOutputStage — then asserts:
      1. every sample of the 512-sample stereo fixture is finite (std::isfinite)
      2. a fingerprint of the fixture equals a locked constant, seeded to
         uint64_t{0} so the first Windows run FAILS intentionally (Plan Task 1
         Step 4 "Expected: ... test executable fails only at the intentionally
         wrong fingerprint"); Windows Step 5 prints the actual value and locks
         it here in place of the zero.

    This file compiles as part of the Windows CorvusDSPTests console target
    (Plan Task 1 Step 2) and must stay buildable with only PluginProcessor.h on
    the include path. The macOS headless gate pins this file's shape via
    scripts/check_baseline_fixture_test.py; no plugin code is expected to
    change for this task (behavior-preserving harness only).
*/

#include <JuceHeader.h>

#include <array>
#include <cmath>
#include <cstdint>
#include <cstring>
#include <algorithm>

// The five shared effect structs live in the DSP section of PluginProcessor.h.
#include "../../source/DrippyFX/PluginProcessor.h"

namespace CorvusDsp
{
static constexpr int fixtureNumSamples = 512;
static constexpr double fixtureSampleRate = 48000.0;

// Fingerprint constant the test asserts against. Deliberately zero for the
// first run (Plan Task 1 Step 1); after Windows Step 4/5 prints the real
// deterministic value, replace 0 with that value and both consecutive runs
// must pass unchanged.
static constexpr uint64_t expectedFingerprint = uint64_t { 0 };

static uint64_t fingerprint(const float* samples, int count)
{
    // FNV-1a over the raw float32 bits — deterministic across runs/machines
    // with the same build; good enough to catch unintended DSP edits.
    uint64_t h = 1469598103934665603ull;
    for (int i = 0; i < count; ++i)
    {
        uint32_t bits;
        static_assert(sizeof(float) == sizeof(uint32_t), "32-bit float required");
        std::memcpy(&bits, &samples[i], sizeof(bits));
        h ^= (uint64_t) bits;
        h *= 1099511628211ull;
    }
    return h;
}

// Deterministic stereo impulse + step fixture through the full Corvus FX
// chain, at the documented safe defaults, at 48 kHz.
static std::array<float, fixtureNumSamples> renderEffectsFixture()
{
    const double sr = fixtureSampleRate;

    ProfessionalDistortion distortion;
    EnhancedChorus      chorus;
    EnhancedDelay       delay;
    UpgradedReverb      reverb;
    MasterOutputStage   master;

    distortion.prepare(sr);
    chorus.prepare(sr);
    delay.prepare(sr);
    reverb.prepare(sr);
    master.prepare(sr);

    // One block of cached coefficients at default knob equivalents.
    distortion.beginBlock(0.35f);
    chorus.beginBlock(0.5f, 0.4f, 0.8f);
    delay.beginBlock(0.3f);
    reverb.beginBlock(0.5f, 0.3f, 0.35f, 0.2f, 1.0f, 10.0f);
    master.beginBlock();

    std::array<float, fixtureNumSamples> out {};

    for (int n = 0; n < fixtureNumSamples; ++n)
    {
        // Deterministic excitation: impulse at 0, decaying tone after.
        float inL = (n == 0) ? 1.0f
                             : 0.25f * std::sin((float) n * 0.0931f)
                                   / std::max (1.0f, (float) n * 0.01f);
        float inR = (n == 0) ? 0.8f
                             : 0.25f * std::cos((float) n * 0.0713f)
                                   / std::max (1.0f, (float) n * 0.01f);

        float dl = 0.0f, dr = 0.0f;
        distortion.process(inL, inR, dl, dr);

        float cl = chorus.process(dl, 0, 0.8f, 0.5f, 0.3f);
        float cr = chorus.process(dr, 1, 0.8f, 0.5f, 0.3f);
        chorus.advanceWritePos();

        float yl = 0.0f, yr = 0.0f;
        delay.processSample(cl, cr, yl, yr, 250.0f, 0.35f, 0.3f, 0.3f, 0.2f);

        float rl = 0.0f, rr = 0.0f;
        reverb.processSample(yl, yr, rl, rr);

        master.process(rl, rr, 0.3f, 0.3f, 1.0f);

        out[(size_t) n] = 0.5f * (rl + rr); // sum to a mono fingerprint stream
    }

    return out;
}
} // namespace CorvusDsp

class CorvusEffectsBaselineTest final : public juce::UnitTest
{
public:
    CorvusEffectsBaselineTest() : juce::UnitTest ("Corvus effects baseline") {}

    void runTest() override
    {
        using namespace CorvusDsp;

        beginTest ("deterministic fixture remains finite");
        const auto output = renderEffectsFixture();
        for (const auto sample : output)
            expect (std::isfinite (sample), "non-finite sample in baseline fixture");

        beginTest ("fixture fingerprint");
        const auto fp = fingerprint (output.data(), (int) output.size());
        expectEquals (fp, expectedFingerprint);
    }
};

static CorvusEffectsBaselineTest corvusEffectsBaselineTest;
