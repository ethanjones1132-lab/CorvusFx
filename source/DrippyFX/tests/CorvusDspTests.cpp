#include <JuceHeader.h>

#include "dsp/CorvusEffects.h"
#include "instrument/CorvusSynthEngine.h"
#include "instrument/CorvusInstrumentProcessor.h"
#include "instrument/CorvusVoice.h"
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

class CorvusOversamplingTest final : public juce::UnitTest
{
public:
    CorvusOversamplingTest() : juce::UnitTest("Corvus oversampler unity") {}
    void runTest() override
    {
        for (const auto frequency : { 0.0, 40.0, 440.0, 5000.0 })
        {
            beginTest("identity preserves DC/passband level and mono/stereo agreement at " + juce::String(frequency));
            Oversampling2x mono, stereo;
            mono.prepare(48000.0);
            stereo.prepare(48000.0);
            double inputEnergy = 0.0, outputEnergy = 0.0;
            float maximumDifference = 0.0f;
            for (auto sample = 0; sample < 48000; ++sample)
            {
                const auto input = frequency == 0.0 ? 0.1f
                    : 0.1f * static_cast<float>(std::sin(sample * frequency * juce::MathConstants<double>::twoPi / 48000.0));
                float output = 0.0f, left = 0.0f, right = 0.0f;
                mono.processSampleMono(input, output, [](float value, float& result) { result = value; });
                stereo.processSample(input, input * 0.5f, left, right,
                    [](float l, float r, float& ol, float& or_) { ol = l; or_ = r; });
                if (sample >= 12000)
                {
                    inputEnergy += static_cast<double>(input) * input;
                    outputEnergy += static_cast<double>(output) * output;
                    maximumDifference = std::max(maximumDifference,
                        std::abs(left - output) + std::abs(right - output * 0.5f));
                }
            }
            const auto gain = std::sqrt(outputEnergy / inputEnergy);
            expectWithinAbsoluteError(gain, 1.0, frequency >= 5000.0 ? 0.2 : 0.01);
            expect(maximumDifference < 0.000001f);
            mono.reset();
            float resetOutput = 1.0f;
            mono.processSampleMono(0.0f, resetOutput, [](float value, float& result) { result = value; });
            expectEquals(resetOutput, 0.0f);
        }
    }
};

//==============================================================================
// DELAY CHANNEL ISOLATION
// The delay's tape-saturation oversampler must keep one FIR history per
// channel. A shared Oversampling2x instance makes the left and right feedback
// paths reuse the same up/down history and the same read index, so the right
// channel's saturation tail bleeds into the left (and back again).
//==============================================================================
class CorvusDelayChannelIsolationTest final : public juce::UnitTest
{
public:
    CorvusDelayChannelIsolationTest() : juce::UnitTest("Corvus delay channel isolation") {}

    void runTest() override
    {
        const auto leftTone = makeTone(testFrames, 0.40f, 220.0f);
        const auto rightTone = makeTone(testFrames, 0.40f, 220.0f);
        const auto silence = std::vector<float>(testFrames, 0.0f);

        beginTest("left-only input leaves the right channel bit-exactly silent");
        {
            auto delay = std::make_unique<EnhancedDelay>();
            delay->prepare(testSampleRate);
            delay->beginBlock(0.40f);
            const auto rendered = renderDelay(*delay, leftTone, silence,
                                              10.0f, 0.60f, 0.50f, 0.0f, 0.0f);

            auto leakedSamples = 0;
            auto worstLeak = 0.0f;
            auto drivenEnergy = 0.0;
            for (std::size_t frame = 0; frame < testFrames; ++frame)
            {
                if (rendered.right[frame] != 0.0f)
                {
                    ++leakedSamples;
                    worstLeak = std::max(worstLeak, std::abs(rendered.right[frame]));
                }
                drivenEnergy += static_cast<double>(rendered.left[frame])
                              * static_cast<double>(rendered.left[frame]);
            }
            expect(leakedSamples == 0,
                   "the undriven channel must stay bit-exactly silent -- the delay's "
                   "tape-saturation oversampler must not share FIR history between channels");
            expect(drivenEnergy > 1.0e-3, "the driven channel must still produce signal");
            logMessage(juce::String("Delay bleed (left driven): leaked samples = ")
                       + juce::String(leakedSamples)
                       + ", worst leak = " + juce::String(worstLeak, 8));
        }

        beginTest("right-only input leaves the left channel bit-exactly silent");
        {
            auto delay = std::make_unique<EnhancedDelay>();
            delay->prepare(testSampleRate);
            delay->beginBlock(0.40f);
            const auto rendered = renderDelay(*delay, silence, rightTone,
                                              10.0f, 0.60f, 0.50f, 0.0f, 0.0f);

            auto leakedSamples = 0;
            auto worstLeak = 0.0f;
            auto drivenEnergy = 0.0;
            for (std::size_t frame = 0; frame < testFrames; ++frame)
            {
                if (rendered.left[frame] != 0.0f)
                {
                    ++leakedSamples;
                    worstLeak = std::max(worstLeak, std::abs(rendered.left[frame]));
                }
                drivenEnergy += static_cast<double>(rendered.right[frame])
                              * static_cast<double>(rendered.right[frame]);
            }
            expect(leakedSamples == 0,
                   "the undriven channel must stay bit-exactly silent -- the delay's "
                   "tape-saturation oversampler must not share FIR history between channels");
            expect(drivenEnergy > 1.0e-3, "the driven channel must still produce signal");
            logMessage(juce::String("Delay bleed (right driven): leaked samples = ")
                       + juce::String(leakedSamples)
                       + ", worst leak = " + juce::String(worstLeak, 8));
        }

        beginTest("ping-pong cross-feed still routes the echo into the opposite channel");
        {
            auto delay = std::make_unique<EnhancedDelay>();
            delay->prepare(testSampleRate);
            delay->beginBlock(0.40f);
            const auto rendered = renderDelay(*delay, leftTone, silence,
                                              10.0f, 0.60f, 0.50f, 1.0f, 0.0f);

            auto crossFeedPeak = 0.0f;
            for (std::size_t frame = 0; frame < testFrames; ++frame)
                crossFeedPeak = std::max(crossFeedPeak, std::abs(rendered.right[frame]));
            expect(crossFeedPeak > 0.05f,
                   "ping-pong must cross-feed the left echo into the right channel");
        }

        beginTest("feedback stays clamped to the 0.92 ceiling");
        {
            auto clamped = std::make_unique<EnhancedDelay>();
            auto overdriven = std::make_unique<EnhancedDelay>();
            clamped->prepare(testSampleRate);
            clamped->beginBlock(0.40f);
            overdriven->prepare(testSampleRate);
            overdriven->beginBlock(0.40f);

            const auto clampedRender = renderDelay(*clamped, leftTone, rightTone,
                                                   10.0f, 0.92f, 0.50f, 0.50f, 0.05f);
            const auto overdrivenRender = renderDelay(*overdriven, leftTone, rightTone,
                                                      10.0f, 5.0f, 0.50f, 0.50f, 0.05f);

            auto mismatches = 0;
            for (std::size_t frame = 0; frame < testFrames; ++frame)
                if (clampedRender.left[frame] != overdrivenRender.left[frame]
                    || clampedRender.right[frame] != overdrivenRender.right[frame])
                    ++mismatches;
            expect(mismatches == 0,
                   "feedback above the 0.92 ceiling must be clamped to the same signal");
        }

        beginTest("reset and re-prepare restore the exact starting state");
        {
            auto delay = std::make_unique<EnhancedDelay>();
            delay->prepare(testSampleRate);
            delay->beginBlock(0.40f);
            const auto first = renderDelay(*delay, leftTone, rightTone,
                                           10.0f, 0.60f, 0.50f, 0.50f, 0.05f);

            delay->reset();
            delay->beginBlock(0.40f);
            const auto afterReset = renderDelay(*delay, leftTone, rightTone,
                                                10.0f, 0.60f, 0.50f, 0.50f, 0.05f);
            expectIdentical(afterReset, first, "reset()");

            delay->prepare(testSampleRate);
            delay->beginBlock(0.40f);
            const auto afterPrepare = renderDelay(*delay, leftTone, rightTone,
                                                  10.0f, 0.60f, 0.50f, 0.50f, 0.05f);
            expectIdentical(afterPrepare, first, "prepare()");

            auto fresh = std::make_unique<EnhancedDelay>();
            fresh->prepare(testSampleRate);
            fresh->beginBlock(0.40f);
            const auto freshRender = renderDelay(*fresh, leftTone, rightTone,
                                                 10.0f, 0.60f, 0.50f, 0.50f, 0.05f);
            expectIdentical(freshRender, first, "a freshly prepared delay");
        }
    }

private:
    static constexpr double testSampleRate = 48000.0;
    static constexpr std::size_t testFrames = 4096;

    struct DelayRender
    {
        std::vector<float> left;
        std::vector<float> right;
    };

    static std::vector<float> makeTone(std::size_t frames, float amplitude, float frequency)
    {
        std::vector<float> samples(frames, 0.0f);
        for (std::size_t frame = 0; frame < frames; ++frame)
        {
            const auto phase = juce::MathConstants<double>::twoPi
                             * static_cast<double>(frequency)
                             * static_cast<double>(frame) / testSampleRate;
            samples[frame] = amplitude * static_cast<float>(std::sin(phase));
        }
        return samples;
    }

    static DelayRender renderDelay(EnhancedDelay& delay,
                                   const std::vector<float>& inputLeft,
                                   const std::vector<float>& inputRight,
                                   float delayTimeMs, float feedback, float mix,
                                   float pingPong, float modAmount)
    {
        DelayRender rendered;
        rendered.left.assign(inputLeft.size(), 0.0f);
        rendered.right.assign(inputLeft.size(), 0.0f);
        for (std::size_t frame = 0; frame < inputLeft.size(); ++frame)
        {
            float left = 0.0f, right = 0.0f;
            delay.processSample(inputLeft[frame], inputRight[frame], left, right,
                                delayTimeMs, feedback, mix, pingPong, modAmount);
            rendered.left[frame] = left;
            rendered.right[frame] = right;
        }
        return rendered;
    }

    void expectIdentical(const DelayRender& actual, const DelayRender& expected,
                         const juce::String& what)
    {
        auto mismatches = 0;
        for (std::size_t frame = 0; frame < expected.left.size(); ++frame)
            if (actual.left[frame] != expected.left[frame]
                || actual.right[frame] != expected.right[frame])
                ++mismatches;
        expect(mismatches == 0, what + " must reproduce the delay output bit-for-bit");
    }
};

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
        const auto actual = fingerprint(output);
        const auto repeated = renderEffectsFixture();
        expect(actual == fingerprint(repeated), "fixture must repeat bit-for-bit on this host");

        // September's split oversampler histories (9b2c3e7), chorus drift
        // radians (751a3d2), and moving reverb diffusion (0cd68e2) intentionally
        // change the waveform. The integration also repairs zero-stuffing,
        // both decimation phases, and SSE lane order while retaining split
        // histories: identity gain is 1 at DC and 0.999658 at 440 Hz.
        // CV-018 (2026-10-21) gives the delay's tape-saturation oversampler one
        // Oversampling2x instance per channel, which removes the left/right
        // feedback bleed a shared instance caused. That bleed was part of this
        // fixture's waveform, so removing it intentionally changes the fixture
        // again: the locked reference below and the measured level window have
        // to be re-measured on the pinned toolchain (native build acceptance).
        // The previous Windows digest was
        // 0x144377379d3ea850; it is historical, not a reference for this DSP.
        // Raw float hashes depend on compiler/architecture. This reference
        // was measured twice on macOS ARM64, AppleClang 14 Release; other
        // toolchains still enforce exact local repetition and level bounds.
#if JUCE_MAC && JUCE_ARM && defined(__clang__) && __clang_major__ == 14
        constexpr auto expected = std::uint64_t { 0xe8dffa927c566497ull };
        expect(actual == expected,
               "actual fingerprint: 0x"
                   + juce::String::toHexString(static_cast<juce::int64>(actual)));
#else
        logMessage("No locked raw-float reference for this toolchain; checking exact local repetition and waveform levels.");
#endif
        std::cout << "Corvus effects fingerprint: 0x" << std::hex << actual << std::dec << '\n';

        beginTest("corrected shared-DSP fixture keeps its measured waveform levels");
        auto peak = 0.0f;
        auto energy = 0.0;
        for (const auto sample : output)
        {
            peak = std::max(peak, std::abs(sample));
            energy += static_cast<double>(sample) * static_cast<double>(sample);
        }
        const auto rms = std::sqrt(energy / output.size());
        expect(peak > 0.30f && peak < 0.36f);
        expect(rms > 0.020 && rms < 0.026);
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

class CorvusVoiceAndEngineTest final : public juce::UnitTest
{
public:
    CorvusVoiceAndEngineTest()
        : juce::UnitTest("Corvus voice and engine")
    {
    }

    void runTest() override
    {
        constexpr auto sampleRate = 48000.0;
        VoiceParameters voiceParameters;
        voiceParameters.attackSeconds = 0.0f;
        voiceParameters.decaySeconds = 0.0f;
        voiceParameters.sustainLevel = 1.0f;
        voiceParameters.releaseSeconds = 0.01f;
        voiceParameters.wave = FactoryWave::Sine;

        beginTest("voice renders A4 and releases to silence");
        CorvusVoice voice;
        voice.prepare(sampleRate);
        voice.startNote(69, 1.0f, voiceParameters, 1);
        std::vector<float> left(static_cast<std::size_t>(sampleRate), 0.0f);
        std::vector<float> right(static_cast<std::size_t>(sampleRate), 0.0f);
        voice.render(left.data(), right.data(), 0, static_cast<int>(left.size()));

        auto crossings = 0;
        for (std::size_t sample = 1; sample < left.size(); ++sample)
        {
            if (left[sample - 1] <= 0.0f && left[sample] > 0.0f)
                ++crossings;
            expect(std::isfinite(left[sample]));
            expectWithinAbsoluteError(left[sample], right[sample], 1.0e-7f);
        }
        expectWithinAbsoluteError(static_cast<float>(crossings), 440.0f, 1.0f);

        voice.stopNote(true);
        std::array<float, 2048> releaseLeft {};
        std::array<float, 2048> releaseRight {};
        voice.render(releaseLeft.data(), releaseRight.data(), 0,
                     static_cast<int>(releaseLeft.size()));
        expect(!voice.isActive());
        expectWithinAbsoluteError(releaseLeft.back(), 0.0f, 1.0e-7f);

        beginTest("velocity scales voice amplitude");
        CorvusVoice quietVoice;
        CorvusVoice loudVoice;
        quietVoice.prepare(sampleRate);
        loudVoice.prepare(sampleRate);
        quietVoice.startNote(69, 0.25f, voiceParameters, 1);
        loudVoice.startNote(69, 1.0f, voiceParameters, 1);
        std::array<float, 512> quietLeft {};
        std::array<float, 512> quietRight {};
        std::array<float, 512> loudLeft {};
        std::array<float, 512> loudRight {};
        quietVoice.render(quietLeft.data(), quietRight.data(), 0, 512);
        loudVoice.render(loudLeft.data(), loudRight.data(), 0, 512);
        const auto quietPeak = *std::max_element(
            quietLeft.begin(), quietLeft.end(),
            [](float firstValue, float secondValue)
            {
                return std::abs(firstValue) < std::abs(secondValue);
            });
        const auto loudPeak = *std::max_element(
            loudLeft.begin(), loudLeft.end(),
            [](float firstValue, float secondValue)
            {
                return std::abs(firstValue) < std::abs(secondValue);
            });
        expectWithinAbsoluteError(std::abs(quietPeak / loudPeak), 0.25f, 0.02f);

        beginTest("pitch wheel bends all active voices by two semitones");
        CorvusSynthEngine bendEngine;
        bendEngine.prepare(sampleRate, static_cast<int>(sampleRate));
        juce::AudioBuffer<float> bendBuffer(2, static_cast<int>(sampleRate));
        juce::MidiBuffer bendMidi;
        bendMidi.addEvent(juce::MidiMessage::noteOn(1, 69, 1.0f), 0);
        bendMidi.addEvent(juce::MidiMessage::pitchWheel(1, 16383), 0);
        bendEngine.render(bendBuffer, bendMidi, voiceParameters);
        auto bentCrossings = 0;
        for (auto sample = 1; sample < bendBuffer.getNumSamples(); ++sample)
            if (bendBuffer.getSample(0, sample - 1) <= 0.0f
                && bendBuffer.getSample(0, sample) > 0.0f)
                ++bentCrossings;
        expectWithinAbsoluteError(static_cast<float>(bentCrossings), 494.0f, 1.0f);

        beginTest("sustain defers release and panic is immediate");
        CorvusSynthEngine engine;
        engine.prepare(sampleRate, 512);
        juce::AudioBuffer<float> buffer(2, 512);
        juce::MidiBuffer sustainedMidi;
        sustainedMidi.addEvent(juce::MidiMessage::noteOn(1, 60, 1.0f), 0);
        sustainedMidi.addEvent(juce::MidiMessage::controllerEvent(1, 64, 127), 64);
        sustainedMidi.addEvent(juce::MidiMessage::noteOff(1, 60), 128);
        engine.render(buffer, sustainedMidi, voiceParameters);
        expect(engine.isNoteActive(60));
        for (auto channel = 0; channel < buffer.getNumChannels(); ++channel)
            for (auto sample = 0; sample < buffer.getNumSamples(); ++sample)
                expect(std::isfinite(buffer.getSample(channel, sample)));

        juce::MidiBuffer releasePedal;
        releasePedal.addEvent(juce::MidiMessage::controllerEvent(1, 64, 0), 0);
        engine.render(buffer, releasePedal, voiceParameters);
        juce::MidiBuffer noMidi;
        for (auto block = 0; block < 4; ++block)
            engine.render(buffer, noMidi, voiceParameters);
        expect(!engine.isNoteActive(60));

        juce::MidiBuffer oneNote;
        oneNote.addEvent(juce::MidiMessage::noteOn(1, 72, 1.0f), 0);
        engine.render(buffer, oneNote, voiceParameters);
        expect(engine.activeVoiceCount() == 1);
        engine.panic();
        expect(engine.activeVoiceCount() == 0);

        beginTest("all notes off and all sound off leave no stuck notes");
        juce::MidiBuffer controllerMidi;
        controllerMidi.addEvent(juce::MidiMessage::noteOn(1, 60, 1.0f), 0);
        controllerMidi.addEvent(juce::MidiMessage::noteOn(1, 64, 1.0f), 1);
        controllerMidi.addEvent(juce::MidiMessage::controllerEvent(1, 123, 0), 64);
        engine.render(buffer, controllerMidi, voiceParameters);
        for (auto block = 0; block < 4; ++block)
            engine.render(buffer, noMidi, voiceParameters);
        expect(engine.activeVoiceCount() == 0);

        controllerMidi.clear();
        controllerMidi.addEvent(juce::MidiMessage::noteOn(1, 67, 1.0f), 0);
        controllerMidi.addEvent(juce::MidiMessage::controllerEvent(1, 120, 0), 32);
        engine.render(buffer, controllerMidi, voiceParameters);
        expect(engine.activeVoiceCount() == 0);

        beginTest("seventeenth note steals the oldest released voice first");
        VoiceParameters longRelease = voiceParameters;
        longRelease.releaseSeconds = 10.0f;
        CorvusSynthEngine releasedStealEngine;
        releasedStealEngine.prepare(sampleRate, 64);
        juce::AudioBuffer<float> smallBuffer(2, 64);
        juce::MidiBuffer sixteenNotes;
        for (auto index = 0; index < 16; ++index)
            sixteenNotes.addEvent(juce::MidiMessage::noteOn(1, 20 + index, 0.8f), 0);
        releasedStealEngine.render(smallBuffer, sixteenNotes, longRelease);
        expect(releasedStealEngine.activeVoiceCount() == 16);

        juce::MidiBuffer releaseOne;
        releaseOne.addEvent(juce::MidiMessage::noteOff(1, 25), 0);
        releasedStealEngine.render(smallBuffer, releaseOne, longRelease);
        expect(releasedStealEngine.isNoteActive(25));

        juce::MidiBuffer seventeenthNote;
        seventeenthNote.addEvent(juce::MidiMessage::noteOn(1, 80, 0.8f), 0);
        releasedStealEngine.render(smallBuffer, seventeenthNote, longRelease);
        expect(!releasedStealEngine.isNoteActive(25));
        expect(releasedStealEngine.isNoteActive(20));
        expect(releasedStealEngine.isNoteActive(80));

        beginTest("without a released voice the oldest active voice is stolen");
        CorvusSynthEngine oldestStealEngine;
        oldestStealEngine.prepare(sampleRate, 64);
        oldestStealEngine.render(smallBuffer, sixteenNotes, longRelease);
        oldestStealEngine.render(smallBuffer, seventeenthNote, longRelease);
        expect(!oldestStealEngine.isNoteActive(20));
        expect(oldestStealEngine.isNoteActive(21));
        expect(oldestStealEngine.isNoteActive(80));
        expect(oldestStealEngine.activeVoiceCount() == 16);
    }
};

class CorvusInstrumentProcessorTest final : public juce::UnitTest
{
public:
    CorvusInstrumentProcessorTest()
        : juce::UnitTest("Corvus instrument processor")
    {
    }

    void runTest() override
    {
        CorvusInstrumentProcessor processor;

        beginTest("instrument identity and buses are distinct");
        expectEquals(processor.getName(), juce::String("Corvus Instrument"));
        expectEquals(processor.getTotalNumInputChannels(), 0);
        expectEquals(processor.getTotalNumOutputChannels(), 2);
        expect(processor.acceptsMidi());
        expect(!processor.producesMidi());
        expect(!processor.isMidiEffect());

        beginTest("vertical-slice parameter contract is complete");
        const std::array<juce::String, 8> parameterIds {
            "osc_wave", "attack", "decay", "sustain", "release",
            "fx_amount", "flight", "output"
        };
        for (const auto& parameterId : parameterIds)
            expect(processor.apvts.getParameter(parameterId) != nullptr,
                   "missing parameter: " + parameterId);

        beginTest("state round trip restores every parameter");
        std::array<float, parameterIds.size()> expectedValues {};
        for (std::size_t index = 0; index < parameterIds.size(); ++index)
        {
            auto* parameter = processor.apvts.getParameter(parameterIds[index]);
            const auto value = static_cast<float>(index + 1) / 10.0f;
            parameter->setValueNotifyingHost(value);
            expectedValues[index] = parameter->getValue();
        }

        juce::MemoryBlock state;
        processor.getStateInformation(state);
        const auto stateTree = juce::ValueTree::readFromData(state.getData(), state.getSize());
        expect(stateTree.hasType("CorvusInstrumentState"));
        expectEquals(static_cast<int>(stateTree.getProperty("schemaVersion", 0)), 1);

        for (const auto& parameterId : parameterIds)
            processor.apvts.getParameter(parameterId)->setValueNotifyingHost(0.0f);
        processor.setStateInformation(state.getData(), static_cast<int>(state.getSize()));
        for (std::size_t index = 0; index < parameterIds.size(); ++index)
            expectWithinAbsoluteError(
                processor.apvts.getParameter(parameterIds[index])->getValue(),
                expectedValues[index], 1.0e-6f);

        beginTest("invalid state leaves current parameters unchanged");
        auto* flight = processor.apvts.getParameter("flight");
        const auto flightBeforeInvalidState = flight->getValue();
        juce::ValueTree wrongRoot("NotCorvusInstrumentState");
        wrongRoot.setProperty("schemaVersion", 1, nullptr);
        juce::MemoryOutputStream wrongRootData;
        wrongRoot.writeToStream(wrongRootData);
        processor.setStateInformation(wrongRootData.getData(),
                                      static_cast<int>(wrongRootData.getDataSize()));
        expectWithinAbsoluteError(flight->getValue(), flightBeforeInvalidState, 1.0e-7f);

        auto unsupportedState = stateTree.createCopy();
        unsupportedState.setProperty("schemaVersion", 99, nullptr);
        juce::MemoryOutputStream unsupportedData;
        unsupportedState.writeToStream(unsupportedData);
        processor.setStateInformation(unsupportedData.getData(),
                                      static_cast<int>(unsupportedData.getDataSize()));
        expectWithinAbsoluteError(flight->getValue(), flightBeforeInvalidState, 1.0e-7f);

        beginTest("MIDI renders finite stereo output without an input bus");
        processor.prepareToPlay(48000.0, 512);
        juce::AudioBuffer<float> output(2, 512);
        output.clear();
        juce::MidiBuffer midi;
        midi.addEvent(juce::MidiMessage::noteOn(1, 60, 1.0f), 0);
        processor.processBlock(output, midi);
        auto peak = 0.0f;
        for (auto channel = 0; channel < output.getNumChannels(); ++channel)
        {
            for (auto sample = 0; sample < output.getNumSamples(); ++sample)
            {
                const auto value = output.getSample(channel, sample);
                expect(std::isfinite(value));
                peak = std::max(peak, std::abs(value));
            }
        }
        expect(peak > 1.0e-4f);

        auto setPhysicalValue = [](CorvusInstrumentProcessor& target,
                                   const juce::String& parameterId, float value)
        {
            auto* parameter = target.apvts.getParameter(parameterId);
            parameter->setValueNotifyingHost(parameter->convertTo0to1(value));
        };
        auto configureDeterministicVoice = [&](CorvusInstrumentProcessor& target,
                                               float fxAmount, float flight)
        {
            setPhysicalValue(target, "osc_wave", 0.0f);
            setPhysicalValue(target, "attack", 0.0f);
            setPhysicalValue(target, "decay", 0.0f);
            setPhysicalValue(target, "sustain", 1.0f);
            setPhysicalValue(target, "release", 1.0f);
            setPhysicalValue(target, "fx_amount", fxAmount);
            setPhysicalValue(target, "flight", flight);
            setPhysicalValue(target, "output", 0.0f);
        };

        beginTest("zero FX amount exactly matches the dry synth engine");
        CorvusInstrumentProcessor dryProcessor;
        configureDeterministicVoice(dryProcessor, 0.0f, 1.0f);
        dryProcessor.prepareToPlay(48000.0, 512);
        juce::AudioBuffer<float> dryProcessorOutput(2, 512);
        juce::MidiBuffer dryProcessorMidi;
        dryProcessorMidi.addEvent(juce::MidiMessage::noteOn(1, 60, 1.0f), 0);
        dryProcessor.processBlock(dryProcessorOutput, dryProcessorMidi);

        CorvusSynthEngine dryEngine;
        dryEngine.prepare(48000.0, 512);
        VoiceParameters dryParameters;
        dryParameters.attackSeconds = 0.0f;
        dryParameters.decaySeconds = 0.0f;
        dryParameters.sustainLevel = 1.0f;
        dryParameters.releaseSeconds = 1.0f;
        dryParameters.wave = FactoryWave::Sine;
        juce::AudioBuffer<float> directDryOutput(2, 512);
        juce::MidiBuffer directDryMidi;
        directDryMidi.addEvent(juce::MidiMessage::noteOn(1, 60, 1.0f), 0);
        dryEngine.render(directDryOutput, directDryMidi, dryParameters);
        for (auto channel = 0; channel < 2; ++channel)
            for (auto sample = 0; sample < 512; ++sample)
                expectWithinAbsoluteError(dryProcessorOutput.getSample(channel, sample),
                                          directDryOutput.getSample(channel, sample),
                                          1.0e-6f);

        beginTest("full FX and Flight materially change output within the safety clamp");
        CorvusInstrumentProcessor wetProcessor;
        configureDeterministicVoice(wetProcessor, 1.0f, 1.0f);
        wetProcessor.prepareToPlay(48000.0, 512);
        juce::AudioBuffer<float> wetOutput(2, 512);
        juce::MidiBuffer wetMidi;
        wetMidi.addEvent(juce::MidiMessage::noteOn(1, 60, 1.0f), 0);
        wetProcessor.processBlock(wetOutput, wetMidi);

        auto differenceEnergy = 0.0;
        for (auto channel = 0; channel < 2; ++channel)
        {
            for (auto sample = 0; sample < 512; ++sample)
            {
                const auto wet = wetOutput.getSample(channel, sample);
                const auto dry = directDryOutput.getSample(channel, sample);
                expect(std::isfinite(wet));
                expect(std::abs(wet) <= 1.0f);
                const auto difference = static_cast<double>(wet - dry);
                differenceEnergy += difference * difference;
            }
        }
        expect(differenceEnergy > 1.0e-3,
               "full Corvus effects must differ materially from the dry synth");

        beginTest("Flight mapping is monotonic and clamped");
        auto previousSettings = wetProcessor.settingsForFlight(0.0f);
        for (auto step = 1; step <= 256; ++step)
        {
            const auto settings = wetProcessor.settingsForFlight(
                static_cast<float>(step) / 256.0f);
            expect(settings.distortionAmount >= previousSettings.distortionAmount);
            expect(settings.chorusDepth >= previousSettings.chorusDepth);
            expect(settings.chorusMix >= previousSettings.chorusMix);
            expect(settings.delayMix >= previousSettings.delayMix);
            expect(settings.delayModulation >= previousSettings.delayModulation);
            expect(settings.reverbSize >= previousSettings.reverbSize);
            expect(settings.reverbMix >= previousSettings.reverbMix);
            expect(settings.reverbModulation >= previousSettings.reverbModulation);
            expect(settings.masterWidth >= previousSettings.masterWidth);
            expect(settings.masterMidDrive >= previousSettings.masterMidDrive);
            expect(settings.masterSideDrive >= previousSettings.masterSideDrive);
            previousSettings = settings;
        }

        beginTest("Flight sweep remains finite, bounded, and de-clicked");
        CorvusInstrumentProcessor sweepProcessor;
        configureDeterministicVoice(sweepProcessor, 1.0f, 0.0f);
        setPhysicalValue(sweepProcessor, "output", -6.0f);
        sweepProcessor.prepareToPlay(48000.0, 128);
        juce::AudioBuffer<float> sweepBuffer(2, 128);
        std::array<float, 2> previousLastSample {};
        auto hasPreviousBlock = false;
        for (auto step = 0; step <= 256; ++step)
        {
            setPhysicalValue(sweepProcessor, "flight",
                             static_cast<float>(step) / 256.0f);
            juce::MidiBuffer sweepMidi;
            if (step == 0)
                sweepMidi.addEvent(juce::MidiMessage::noteOn(1, 60, 0.8f), 0);
            sweepProcessor.processBlock(sweepBuffer, sweepMidi);
            for (auto channel = 0; channel < 2; ++channel)
            {
                if (hasPreviousBlock)
                    expect(std::abs(sweepBuffer.getSample(channel, 0)
                                    - previousLastSample[static_cast<std::size_t>(channel)])
                           < 0.75f);
                for (auto sample = 0; sample < sweepBuffer.getNumSamples(); ++sample)
                {
                    const auto value = sweepBuffer.getSample(channel, sample);
                    expect(std::isfinite(value));
                    expect(std::abs(value) <= 1.0f);
                }
                previousLastSample[static_cast<std::size_t>(channel)]
                    = sweepBuffer.getSample(channel, sweepBuffer.getNumSamples() - 1);
            }
            hasPreviousBlock = true;
        }

        beginTest("five signature programs expose stable host names");
        CorvusInstrumentProcessor presetProcessor;
        const std::array<juce::String, 5> expectedProgramNames {
            "Dawn Choir", "Raven Glass", "Ashen Sky",
            "Northern Signal", "Cathedral Drift"
        };
        expectEquals(presetProcessor.getNumPrograms(),
                     static_cast<int>(expectedProgramNames.size()));
        for (std::size_t index = 0; index < expectedProgramNames.size(); ++index)
        {
            presetProcessor.setCurrentProgram(static_cast<int>(index));
            expectEquals(presetProcessor.getCurrentProgram(), static_cast<int>(index));
            expectEquals(presetProcessor.getProgramName(static_cast<int>(index)),
                         expectedProgramNames[index]);
        }

        beginTest("program recall survives versioned state round trip");
        presetProcessor.setCurrentProgram(3);
        std::array<float, parameterIds.size()> recalledValues {};
        for (std::size_t index = 0; index < parameterIds.size(); ++index)
            recalledValues[index]
                = presetProcessor.apvts.getParameter(parameterIds[index])->getValue();
        juce::MemoryBlock recalledState;
        presetProcessor.getStateInformation(recalledState);
        presetProcessor.setCurrentProgram(0);
        presetProcessor.setStateInformation(
            recalledState.getData(), static_cast<int>(recalledState.getSize()));
        expectEquals(presetProcessor.getCurrentProgram(), 3);
        for (std::size_t index = 0; index < parameterIds.size(); ++index)
            expectWithinAbsoluteError(
                presetProcessor.apvts.getParameter(parameterIds[index])->getValue(),
                recalledValues[index], 1.0e-6f);

        auto renderProgram = [&](int program, bool forceDry)
        {
            CorvusInstrumentProcessor renderedProcessor;
            renderedProcessor.setCurrentProgram(program);
            if (forceDry)
                setPhysicalValue(renderedProcessor, "fx_amount", 0.0f);
            renderedProcessor.prepareToPlay(48000.0, 512);
            std::vector<float> fixture(8192, 0.0f);
            juce::AudioBuffer<float> blockBuffer(2, 512);
            for (auto block = 0; block < 16; ++block)
            {
                juce::MidiBuffer chordMidi;
                if (block == 0)
                {
                    chordMidi.addEvent(juce::MidiMessage::noteOn(1, 57, 0.75f), 0);
                    chordMidi.addEvent(juce::MidiMessage::noteOn(1, 60, 0.68f), 0);
                    chordMidi.addEvent(juce::MidiMessage::noteOn(1, 64, 0.62f), 0);
                }
                renderedProcessor.processBlock(blockBuffer, chordMidi);
                for (auto sample = 0; sample < blockBuffer.getNumSamples(); ++sample)
                    fixture[static_cast<std::size_t>(block * 512 + sample)]
                        = blockBuffer.getSample(0, sample);
            }
            return fixture;
        };

        beginTest("every signature patch is finite, non-silent, and effects-native");
        std::array<std::vector<float>, 5> wetFixtures;
        for (auto program = 0; program < 5; ++program)
        {
            wetFixtures[static_cast<std::size_t>(program)]
                = renderProgram(program, false);
            const auto dryFixture = renderProgram(program, true);
            auto wetEnergy = 0.0;
            auto programDifferenceEnergy = 0.0;
            auto programPeak = 0.0f;
            for (std::size_t sample = 0; sample < dryFixture.size(); ++sample)
            {
                const auto wet = wetFixtures[static_cast<std::size_t>(program)][sample];
                expect(std::isfinite(wet));
                programPeak = std::max(programPeak, std::abs(wet));
                wetEnergy += static_cast<double>(wet) * static_cast<double>(wet);
                const auto difference = static_cast<double>(wet - dryFixture[sample]);
                programDifferenceEnergy += difference * difference;
            }
            expect(programPeak <= 1.0f);
            expect(wetEnergy > 1.0e-4);
            expect(programDifferenceEnergy > 1.0e-3);
            const auto programRms = std::sqrt(wetEnergy / dryFixture.size());
            expect(programRms >= 0.07 && programRms <= 0.13,
                   "signature patch RMS must stay inside the measured level window");
            std::cout << "Corvus patch metric: "
                      << expectedProgramNames[static_cast<std::size_t>(program)]
                      << " peak=" << programPeak
                      << " rms=" << programRms << '\n';
        }

        beginTest("signature patches render distinct deterministic fixtures");
        const auto dawnChoirAgain = renderProgram(0, false);
        for (std::size_t sample = 0; sample < dawnChoirAgain.size(); ++sample)
            expectWithinAbsoluteError(dawnChoirAgain[sample], wetFixtures[0][sample],
                                      1.0e-7f);
        for (std::size_t firstProgram = 0; firstProgram < wetFixtures.size(); ++firstProgram)
        {
            for (std::size_t secondProgram = firstProgram + 1;
                 secondProgram < wetFixtures.size(); ++secondProgram)
            {
                auto pairDifferenceEnergy = 0.0;
                for (std::size_t sample = 0; sample < wetFixtures[firstProgram].size(); ++sample)
                {
                    const auto difference = static_cast<double>(
                        wetFixtures[firstProgram][sample]
                        - wetFixtures[secondProgram][sample]);
                    pairDifferenceEnergy += difference * difference;
                }
                expect(pairDifferenceEnergy > 1.0e-3);
            }
        }
    }
};

CorvusOversamplingTest corvusOversamplingTest;
CorvusDelayChannelIsolationTest corvusDelayChannelIsolationTest;
CorvusEffectsBaselineTest corvusEffectsBaselineTest;
CorvusWavetableOscillatorTest corvusWavetableOscillatorTest;
CorvusVoiceAndEngineTest corvusVoiceAndEngineTest;
CorvusInstrumentProcessorTest corvusInstrumentProcessorTest;
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
