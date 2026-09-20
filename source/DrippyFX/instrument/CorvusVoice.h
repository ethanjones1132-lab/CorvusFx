#pragma once

#include "WavetableOscillator.h"

#include <JuceHeader.h>

#include <algorithm>
#include <cmath>
#include <cstdint>

struct VoiceParameters
{
    float attackSeconds = 0.01f;
    float decaySeconds = 0.20f;
    float sustainLevel = 0.75f;
    float releaseSeconds = 0.50f;
    FactoryWave wave = FactoryWave::Saw;
};

class CorvusVoice
{
public:
    void prepare(double newSampleRate)
    {
        sampleRate = newSampleRate;
        oscillator.prepare(newSampleRate);
        envelope.setSampleRate(newSampleRate);
        resetImmediately();
    }

    void startNote(int newNoteNumber, float newVelocity,
                   const VoiceParameters& parameters, std::uint64_t newAge)
    {
        const auto replacingLiveVoice = active;
        noteNumber = juce::jlimit(0, 127, newNoteNumber);
        velocity = juce::jlimit(0.0f, 1.0f, newVelocity);
        age = newAge;
        keyDown = true;
        active = true;
        pitchBendSemitones = 0.0f;

        oscillator.setWave(parameters.wave);
        oscillator.reset();
        updateFrequency();

        juce::ADSR::Parameters envelopeParameters;
        envelopeParameters.attack = std::max(0.0f, parameters.attackSeconds);
        envelopeParameters.decay = std::max(0.0f, parameters.decaySeconds);
        envelopeParameters.sustain = juce::jlimit(0.0f, 1.0f, parameters.sustainLevel);
        envelopeParameters.release = std::max(0.0f, parameters.releaseSeconds);
        envelope.setParameters(envelopeParameters);
        envelope.reset();
        envelope.noteOn();

        declickSamplesRemaining = replacingLiveVoice ? declickLength : 0;
    }

    void stopNote(bool allowTailOff)
    {
        keyDown = false;
        if (!active)
            return;

        if (allowTailOff)
            envelope.noteOff();
        else
            resetImmediately();
    }

    void deferNoteOff() noexcept
    {
        keyDown = false;
    }

    void releaseDeferredNote()
    {
        if (active && !keyDown)
            envelope.noteOff();
    }

    void setPitchBendSemitones(float semitones)
    {
        pitchBendSemitones = juce::jlimit(-2.0f, 2.0f, semitones);
        updateFrequency();
    }

    void render(float* left, float* right, int start, int count)
    {
        if (!active || left == nullptr || right == nullptr || count <= 0)
            return;

        constexpr auto centrePanGain = 0.7071067811865475f;
        for (auto offset = 0; offset < count; ++offset)
        {
            const auto envelopeValue = envelope.getNextSample();
            auto gain = envelopeValue * velocity;
            if (declickSamplesRemaining > 0)
            {
                gain *= static_cast<float>(declickLength - declickSamplesRemaining)
                    / static_cast<float>(declickLength);
                --declickSamplesRemaining;
            }

            const auto sample = oscillator.process() * gain * centrePanGain;
            left[start + offset] += sample;
            right[start + offset] += sample;
        }

        if (!envelope.isActive())
            resetImmediately();
    }

    void resetImmediately() noexcept
    {
        envelope.reset();
        oscillator.reset();
        active = false;
        keyDown = false;
        noteNumber = -1;
        velocity = 0.0f;
        pitchBendSemitones = 0.0f;
        declickSamplesRemaining = 0;
    }

    bool isActive() const noexcept { return active; }
    bool isReleased() const noexcept { return active && !keyDown; }
    bool isKeyDown() const noexcept { return active && keyDown; }
    int getNoteNumber() const noexcept { return noteNumber; }
    std::uint64_t getAge() const noexcept { return age; }

private:
    void updateFrequency()
    {
        if (sampleRate <= 0.0 || noteNumber < 0)
        {
            oscillator.setFrequency(0.0f);
            return;
        }

        const auto bentNote = static_cast<double>(noteNumber)
            + static_cast<double>(pitchBendSemitones);
        const auto frequency = 440.0 * std::pow(2.0, (bentNote - 69.0) / 12.0);
        oscillator.setFrequency(static_cast<float>(frequency));
    }

    static constexpr auto declickLength = 32;

    WavetableOscillator oscillator;
    juce::ADSR envelope;
    double sampleRate = 0.0;
    std::uint64_t age = 0;
    int noteNumber = -1;
    int declickSamplesRemaining = 0;
    float velocity = 0.0f;
    float pitchBendSemitones = 0.0f;
    bool active = false;
    bool keyDown = false;
};
