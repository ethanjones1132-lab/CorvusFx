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

        if (replacingLiveVoice)
        {
            // CV-065: a stolen voice must fade the outgoing note instead of
            // cutting it. The running oscillator phase and envelope are left
            // untouched and rendered for one declick window with a decaying
            // gain; the reset and the replacement note's own declick fade-in
            // are deferred until that tail has been rendered. The new note
            // owns the voice immediately, so note ownership and the bounded
            // 16-voice allocation are unchanged - this still allocates
            // nothing on the audio thread.
            pendingParameters = parameters;
            pendingNoteNumber = juce::jlimit(0, 127, newNoteNumber);
            pendingVelocity = juce::jlimit(0.0f, 1.0f, newVelocity);
            pendingAge = newAge;
            pendingReleaseOnStart = false;
            pendingDeferOnStart = false;
            // Continue from the level the outgoing note is already at, so a
            // second steal inside the same window cannot jump back up.
            stealFromVelocity = stealFadeSamplesRemaining > 0
                ? stealFromVelocity * stealFadeScale()
                : velocity;
            stealFadeSamplesRemaining = declickLength;

            noteNumber = pendingNoteNumber;
            age = pendingAge;
            keyDown = true;
            pitchBendSemitones = 0.0f;
            return;
        }

        noteNumber = juce::jlimit(0, 127, newNoteNumber);
        velocity = juce::jlimit(0.0f, 1.0f, newVelocity);
        age = newAge;
        keyDown = true;
        active = true;
        pitchBendSemitones = 0.0f;
        beginNote(parameters);
        declickSamplesRemaining = 0;
    }

    void stopNote(bool allowTailOff)
    {
        keyDown = false;
        if (!active)
            return;

        if (!allowTailOff)
        {
            resetImmediately();
            return;
        }

        if (stealFadeSamplesRemaining > 0)
        {
            // The envelope still belongs to the outgoing note; release the
            // replacement as soon as its own start has been applied.
            pendingReleaseOnStart = true;
            pendingDeferOnStart = false;
            return;
        }

        envelope.noteOff();
    }

    void deferNoteOff() noexcept
    {
        keyDown = false;
        if (stealFadeSamplesRemaining > 0)
        {
            // Sustain holds the replacement off; the pedal release will ask
            // for the note-off once the deferred start has run.
            pendingDeferOnStart = true;
            pendingReleaseOnStart = false;
        }
    }

    void releaseDeferredNote()
    {
        if (!active || keyDown)
            return;

        if (stealFadeSamplesRemaining > 0)
        {
            pendingReleaseOnStart = true;
            pendingDeferOnStart = false;
            return;
        }

        envelope.noteOff();
    }

    void setPitchBendSemitones(float semitones)
    {
        pitchBendSemitones = juce::jlimit(-2.0f, 2.0f, semitones);
        updateFrequency();
    }

    float renderSample(float& emittedEnvelopeLevel)
    {
        if (!active)
            return 0.0f;

        auto gain = 0.0f;
        const auto sample = renderNextSample(gain);
        emittedEnvelopeLevel += gain;
        return sample;
    }

    void finishRenderSpan() noexcept
    {
        if (stealFadeSamplesRemaining > 0)
            return;

        if (active && !envelope.isActive())
            resetImmediately();
    }

    void render(float* left, float* right, int start, int count)
    {
        if (!active || left == nullptr || right == nullptr || count <= 0)
            return;

        auto gain = 0.0f;
        for (auto offset = 0; offset < count; ++offset)
        {
            const auto sample = renderNextSample(gain);
            left[start + offset] += sample;
            right[start + offset] += sample;
        }

        // A steal fade may still be running (or may just have handed over to
        // the replacement note); only retire the voice once no tail is owed.
        if (stealFadeSamplesRemaining <= 0 && !envelope.isActive())
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
        pendingNoteNumber = -1;
        pendingVelocity = 0.0f;
        pendingAge = 0;
        pendingReleaseOnStart = false;
        pendingDeferOnStart = false;
        stealFromVelocity = 0.0f;
        stealFadeSamplesRemaining = 0;
    }

    bool isActive() const noexcept { return active; }
    bool isReleased() const noexcept { return active && !keyDown; }
    bool isKeyDown() const noexcept { return active && keyDown; }
    int getNoteNumber() const noexcept { return noteNumber; }
    std::uint64_t getAge() const noexcept { return age; }

private:
    static constexpr auto declickLength = 32;
    static constexpr auto centrePanGain = 0.7071067811865475f;

    // One rendered sample of the note currently owned by this voice. `gainOut`
    // reports the envelope gain applied to it (the activity meter consumes a
    // sum of those gains), so both the block and the per-sample render paths
    // share one fade/declick implementation.
    float renderNextSample(float& gainOut)
    {
        const auto envelopeValue = envelope.getNextSample();

        if (stealFadeSamplesRemaining > 0)
        {
            // CV-065: keep the outgoing oscillator and envelope running and
            // fade them out across the declick window. The reset only happens
            // after this last tail sample has been produced, so the samples
            // stay continuous instead of being cut to zero at the steal.
            gainOut = envelopeValue * stealFromVelocity * stealFadeScale();
            const auto sample = oscillator.process() * gainOut * centrePanGain;
            if (--stealFadeSamplesRemaining == 0)
                applyPendingStart();
            return sample;
        }

        auto gain = envelopeValue * velocity;
        if (declickSamplesRemaining > 0)
        {
            gain *= static_cast<float>(declickLength - declickSamplesRemaining)
                / static_cast<float>(declickLength);
            --declickSamplesRemaining;
        }

        gainOut = gain;
        return oscillator.process() * gain * centrePanGain;
    }

    // 1.0 at the first fade sample, then a straight ramp towards zero: the
    // outgoing note starts at its old level (no discontinuity) and decays
    // over exactly one declick window.
    float stealFadeScale() const noexcept
    {
        if (stealFadeSamplesRemaining <= 0)
            return 1.0f;

        return static_cast<float>(stealFadeSamplesRemaining)
            / static_cast<float>(declickLength);
    }

    void beginNote(const VoiceParameters& parameters)
    {
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
    }

    // Reset/reuse of a stolen voice, run only after the outgoing tail has been
    // rendered. The replacement keeps its own declick fade-in.
    void applyPendingStart()
    {
        stealFadeSamplesRemaining = 0;
        stealFromVelocity = 0.0f;

        noteNumber = pendingNoteNumber;
        velocity = pendingVelocity;
        age = pendingAge;
        keyDown = true;
        active = true;

        beginNote(pendingParameters);
        declickSamplesRemaining = declickLength;

        if (pendingReleaseOnStart)
        {
            pendingReleaseOnStart = false;
            pendingDeferOnStart = false;
            keyDown = false;
            envelope.noteOff();
        }
        else if (pendingDeferOnStart)
        {
            // Held by the sustain pedal: the voice stays released from the key
            // so releaseDeferredNote() can end it when the pedal lifts.
            pendingDeferOnStart = false;
            keyDown = false;
        }
    }

    void updateFrequency()
    {
        // A steal fade still belongs to the outgoing note: keep its pitch until
        // the deferred start applies the stored bend to the replacement.
        if (stealFadeSamplesRemaining > 0)
            return;

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

    WavetableOscillator oscillator;
    juce::ADSR envelope;
    VoiceParameters pendingParameters;
    double sampleRate = 0.0;
    std::uint64_t age = 0;
    std::uint64_t pendingAge = 0;
    int noteNumber = -1;
    int pendingNoteNumber = -1;
    int declickSamplesRemaining = 0;
    int stealFadeSamplesRemaining = 0;
    float velocity = 0.0f;
    float pendingVelocity = 0.0f;
    float stealFromVelocity = 0.0f;
    float pitchBendSemitones = 0.0f;
    bool active = false;
    bool keyDown = false;
    bool pendingReleaseOnStart = false;
    bool pendingDeferOnStart = false;
};
