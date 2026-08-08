#include <JuceHeader.h>

#include "dsp/CorvusEffects.h"

#include <array>
#include <cmath>
#include <cstdint>
#include <cstring>
#include <iostream>
#include <memory>

namespace
{
constexpr auto fixtureFrames = std::size_t { 256 };
using EffectsFixture = std::array<float, fixtureFrames * 2>;

EffectsFixture renderEffectsFixture()
{
    constexpr auto sampleRate = 48000.0;

    auto distortion = std::make_unique<ProfessionalDistortion>();
    auto chorus = std::make_unique<EnhancedChorus>();
    auto delay = std::make_unique<EnhancedDelay>();
    auto reverb = std::make_unique<UpgradedReverb>();
    auto master = std::make_unique<MasterOutputStage>();

    distortion->prepare(sampleRate);
    chorus->prepare(sampleRate);
    delay->prepare(sampleRate);
    reverb->prepare(sampleRate);
    master->prepare(sampleRate);

    distortion->beginBlock(0.42f);
    chorus->beginBlock(0.36f, 0.32f, 0.55f);
    delay->beginBlock(0.40f);
    reverb->beginBlock(0.58f, 0.35f, 0.25f, 0.18f, 1.15f, 0.0f);
    master->beginBlock();

    EffectsFixture output {};

    for (std::size_t frame = 0; frame < fixtureFrames; ++frame)
    {
        float left = frame == 0 ? 0.75f : 0.0f;
        float right = frame == 0 ? -0.35f : 0.0f;

        float processedLeft = 0.0f;
        float processedRight = 0.0f;
        distortion->process(left, right, processedLeft, processedRight);
        left = processedLeft;
        right = processedRight;

        left = chorus->process(left, 0, 0.55f, 0.36f, 0.09f);
        right = chorus->process(right, 1, 0.55f, 0.36f, 0.09f);
        chorus->advanceWritePos();

        delay->processSample(left, right, processedLeft, processedRight,
                             1.0f, 0.28f, 0.22f, 0.35f, 0.10f);
        left = processedLeft;
        right = processedRight;

        reverb->processSample(left, right, processedLeft, processedRight);
        left = processedLeft;
        right = processedRight;

        master->process(left, right, 1.10f, 0.90f, 1.20f);

        output[frame * 2] = left;
        output[frame * 2 + 1] = right;
    }

    return output;
}

std::uint64_t fingerprint(const EffectsFixture& samples)
{
    constexpr auto offsetBasis = std::uint64_t { 14695981039346656037ull };
    constexpr auto prime = std::uint64_t { 1099511628211ull };
    auto hash = offsetBasis;

    for (const auto sample : samples)
    {
        std::uint32_t bits = 0;
        static_assert(sizeof(bits) == sizeof(sample));
        std::memcpy(&bits, &sample, sizeof(bits));

        for (auto shift = 0u; shift < 32u; shift += 8u)
        {
            hash ^= static_cast<std::uint8_t>((bits >> shift) & 0xffu);
            hash *= prime;
        }
    }

    return hash;
}

class CorvusEffectsBaselineTest final : public juce::UnitTest
{
public:
    CorvusEffectsBaselineTest()
        : juce::UnitTest("Corvus effects baseline")
    {
    }

    void runTest() override
    {
        const auto output = renderEffectsFixture();

        beginTest("deterministic fixture remains finite");
        for (const auto sample : output)
            expect(std::isfinite(sample));

        beginTest("fixture fingerprint");
        constexpr auto expected = std::uint64_t { 0x144377379d3ea850ull };
        const auto actual = fingerprint(output);
        std::cout << "Corvus effects fingerprint: 0x" << std::hex << actual << std::dec << '\n';
        expect(actual == expected,
               "actual fingerprint: 0x"
                   + juce::String::toHexString(static_cast<juce::int64>(actual)));
    }
};

CorvusEffectsBaselineTest corvusEffectsBaselineTest;
} // namespace

int main()
{
    juce::UnitTestRunner runner;
    runner.setAssertOnFailure(false);
    runner.setPassesAreLogged(true);
    runner.runAllTests(0xC0FFEE);

    auto failures = 0;
    for (auto index = 0; index < runner.getNumResults(); ++index)
        if (const auto* result = runner.getResult(index))
            failures += result->failures;

    std::cout << "Corvus DSP tests: " << failures << " failure(s)\n";
    return failures == 0 ? 0 : 1;
}
