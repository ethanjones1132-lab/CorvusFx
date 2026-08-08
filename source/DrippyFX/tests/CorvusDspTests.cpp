#include <JuceHeader.h>

#include "dsp/CorvusEffects.h"
#include "instrument/WavetableOscillator.h"

#include <array>
#include <cmath>
#include <cstdint>
#include <cstring>
#include <iostream>
#include <memory>
#include <vector>

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

class CorvusWavetableOscillatorTest final : public juce::UnitTest
{
public:
    CorvusWavetableOscillatorTest()
        : juce::UnitTest("Corvus wavetable oscillator")
    {
    }

    void runTest() override
    {
        constexpr auto sampleRate = 48000.0;

        beginTest("A4 frequency is accurate");
        WavetableOscillator sine;
        sine.prepare(sampleRate);
        sine.setWave(FactoryWave::Sine);
        sine.setFrequency(440.0f);
        sine.reset();

        auto crossings = 0;
        auto previous = sine.process();
        for (auto sample = 1; sample < static_cast<int>(sampleRate); ++sample)
        {
            const auto current = sine.process();
            if (previous <= 0.0f && current > 0.0f)
                ++crossings;
            previous = current;
        }
        expectWithinAbsoluteError(static_cast<float>(crossings), 440.0f, 1.0f);

        beginTest("factory waves remain finite and bounded");
        for (const auto wave : { FactoryWave::Sine, FactoryWave::Triangle,
                                 FactoryWave::Saw, FactoryWave::Square })
        {
            WavetableOscillator oscillator;
            oscillator.prepare(sampleRate);
            oscillator.setWave(wave);
            oscillator.setFrequency(997.0f);
            oscillator.reset(0.123f);
            for (auto sample = 0; sample < 8192; ++sample)
            {
                const auto value = oscillator.process();
                expect(std::isfinite(value));
                expect(value >= -1.01f && value <= 1.01f);
            }
        }

        beginTest("reset phase is deterministic");
        WavetableOscillator first;
        WavetableOscillator second;
        for (auto* oscillator : { &first, &second })
        {
            oscillator->prepare(sampleRate);
            oscillator->setWave(FactoryWave::Saw);
            oscillator->setFrequency(731.0f);
            oscillator->reset(0.375f);
        }
        for (auto sample = 0; sample < 4096; ++sample)
            expectWithinAbsoluteError(first.process(), second.process(), 1.0e-7f);

        beginTest("invalid frequency fails to silence");
        first.setFrequency(-1.0f);
        expectEquals(first.process(), 0.0f);
        first.setFrequency(24001.0f);
        expectEquals(first.process(), 0.0f);

        beginTest("high saw suppresses out-of-band aliases");
        constexpr auto fftOrder = 12;
        constexpr auto fftSize = 1 << fftOrder;
        constexpr auto fundamentalBin = 389;
        constexpr auto frequency = static_cast<float>(fundamentalBin * sampleRate / fftSize);

        WavetableOscillator bandLimited;
        bandLimited.prepare(sampleRate);
        bandLimited.setWave(FactoryWave::Saw);
        bandLimited.setFrequency(frequency);
        bandLimited.reset();

        std::array<float, fftSize * 2> bandLimitedSpectrum {};
        std::array<float, fftSize * 2> naiveSpectrum {};
        auto naivePhase = 0.0f;
        const auto phaseIncrement = frequency / static_cast<float>(sampleRate);
        for (auto sample = 0; sample < fftSize; ++sample)
        {
            bandLimitedSpectrum[static_cast<std::size_t>(sample)] = bandLimited.process();
            naiveSpectrum[static_cast<std::size_t>(sample)] = naivePhase * 2.0f - 1.0f;
            naivePhase += phaseIncrement;
            naivePhase -= std::floor(naivePhase);
        }

        juce::dsp::FFT fft(fftOrder);
        fft.performFrequencyOnlyForwardTransform(bandLimitedSpectrum.data(), true);
        fft.performFrequencyOnlyForwardTransform(naiveSpectrum.data(), true);

        auto outOfBandEnergy = [=](const auto& spectrum)
        {
            auto energy = 0.0;
            for (auto bin = 1; bin < fftSize / 2; ++bin)
            {
                auto expectedHarmonic = false;
                for (auto harmonic = 1; harmonic * fundamentalBin < fftSize / 2; ++harmonic)
                    expectedHarmonic = expectedHarmonic || bin == harmonic * fundamentalBin;
                if (!expectedHarmonic)
                {
                    const auto magnitude = static_cast<double>(spectrum[static_cast<std::size_t>(bin)]);
                    energy += magnitude * magnitude;
                }
            }
            return energy;
        };

        const auto bandLimitedAliasEnergy = outOfBandEnergy(bandLimitedSpectrum);
        const auto naiveAliasEnergy = outOfBandEnergy(naiveSpectrum);
        expect(bandLimitedAliasEnergy < naiveAliasEnergy * 0.20,
               "band-limited alias energy must be less than 20% of the naive saw");
    }
};

CorvusEffectsBaselineTest corvusEffectsBaselineTest;
CorvusWavetableOscillatorTest corvusWavetableOscillatorTest;
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
