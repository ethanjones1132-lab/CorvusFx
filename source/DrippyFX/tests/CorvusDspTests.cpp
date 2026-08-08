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
    }
};

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
