#pragma once

#include "CorvusVoice.h"

#include <JuceHeader.h>

#include <array>
#include <cstddef>
#include <cstdint>

class CorvusSynthEngine
{
public:
    static constexpr auto voiceCount = std::size_t { 16 };

    void prepare(double sampleRate, int maxBlockSize)
    {
        juce::ignoreUnused(maxBlockSize);
        for (auto& voice : voices)
            voice.prepare(sampleRate);
        nextAge = 1;
        sustainDown = false;
        pitchBendSemitones = 0.0f;
    }

    void render(juce::AudioBuffer<float>& buffer, const juce::MidiBuffer& midi,
                const VoiceParameters& parameters)
    {
        buffer.clear();
        if (buffer.getNumChannels() < 2 || buffer.getNumSamples() <= 0)
            return;

        auto renderedUntil = 0;
        for (const auto metadata : midi)
        {
            const auto eventPosition = juce::jlimit(
                renderedUntil, buffer.getNumSamples(), metadata.samplePosition);
            renderSpan(buffer, renderedUntil, eventPosition - renderedUntil);
            handleMidiMessage(metadata.getMessage(), parameters);
            renderedUntil = eventPosition;
        }

        renderSpan(buffer, renderedUntil, buffer.getNumSamples() - renderedUntil);
    }

    void panic() noexcept
    {
        for (auto& voice : voices)
            voice.resetImmediately();
        sustainDown = false;
        pitchBendSemitones = 0.0f;
    }

    std::size_t activeVoiceCount() const noexcept
    {
        auto count = std::size_t { 0 };
        for (const auto& voice : voices)
            if (voice.isActive())
                ++count;
        return count;
    }

    bool isNoteActive(int noteNumber) const noexcept
    {
        for (const auto& voice : voices)
            if (voice.isActive() && voice.getNoteNumber() == noteNumber)
                return true;
        return false;
    }

private:
    CorvusVoice& chooseVoice()
    {
        for (auto& voice : voices)
            if (!voice.isActive())
                return voice;

        CorvusVoice* oldestReleased = nullptr;
        for (auto& voice : voices)
        {
            if (voice.isReleased()
                && (oldestReleased == nullptr || voice.getAge() < oldestReleased->getAge()))
                oldestReleased = &voice;
        }
        if (oldestReleased != nullptr)
            return *oldestReleased;

        auto* oldest = &voices.front();
        for (auto& voice : voices)
            if (voice.getAge() < oldest->getAge())
                oldest = &voice;
        return *oldest;
    }

    void startNote(int noteNumber, float velocity, const VoiceParameters& parameters)
    {
        auto& voice = chooseVoice();
        voice.startNote(noteNumber, velocity, parameters, nextAge++);
        voice.setPitchBendSemitones(pitchBendSemitones);
    }

    void releaseNote(int noteNumber)
    {
        for (auto& voice : voices)
        {
            if (!voice.isActive() || !voice.isKeyDown()
                || voice.getNoteNumber() != noteNumber)
                continue;

            if (sustainDown)
                voice.deferNoteOff();
            else
                voice.stopNote(true);
        }
    }

    void setSustain(bool shouldHold)
    {
        if (sustainDown == shouldHold)
            return;

        sustainDown = shouldHold;
        if (!sustainDown)
            for (auto& voice : voices)
                voice.releaseDeferredNote();
    }

    void allNotesOff(bool allowTailOff)
    {
        sustainDown = false;
        for (auto& voice : voices)
            if (voice.isActive())
                voice.stopNote(allowTailOff);
    }

    void setPitchWheel(int wheelValue)
    {
        const auto centred = wheelValue - 8192;
        const auto normalised = centred >= 0
            ? static_cast<float>(centred) / 8191.0f
            : static_cast<float>(centred) / 8192.0f;
        pitchBendSemitones = normalised * 2.0f;
        for (auto& voice : voices)
            if (voice.isActive())
                voice.setPitchBendSemitones(pitchBendSemitones);
    }

    void handleMidiMessage(const juce::MidiMessage& message,
                           const VoiceParameters& parameters)
    {
        if (message.isNoteOn())
        {
            startNote(message.getNoteNumber(), message.getFloatVelocity(), parameters);
            return;
        }
        if (message.isNoteOff())
        {
            releaseNote(message.getNoteNumber());
            return;
        }
        if (message.isPitchWheel())
        {
            setPitchWheel(message.getPitchWheelValue());
            return;
        }
        if (!message.isController())
            return;

        const auto controller = message.getControllerNumber();
        if (controller == 64)
            setSustain(message.getControllerValue() >= 64);
        else if (controller == 120)
            panic();
        else if (controller == 123)
            allNotesOff(true);
    }

    void renderSpan(juce::AudioBuffer<float>& buffer, int start, int count)
    {
        if (count <= 0)
            return;

        auto* left = buffer.getWritePointer(0);
        auto* right = buffer.getWritePointer(1);
        for (auto& voice : voices)
            voice.render(left, right, start, count);
    }

    std::array<CorvusVoice, voiceCount> voices;
    std::uint64_t nextAge = 1;
    float pitchBendSemitones = 0.0f;
    bool sustainDown = false;
};
