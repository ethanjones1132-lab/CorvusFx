#pragma once

#include "CorvusSynthEngine.h"

#include <JuceHeader.h>

class CorvusInstrumentProcessor final : public juce::AudioProcessor
{
public:
    CorvusInstrumentProcessor();
    ~CorvusInstrumentProcessor() override = default;

    void prepareToPlay(double sampleRate, int samplesPerBlock) override;
    void releaseResources() override;
    bool isBusesLayoutSupported(const BusesLayout& layouts) const override;
    void processBlock(juce::AudioBuffer<float>& buffer, juce::MidiBuffer& midi) override;

    juce::AudioProcessorEditor* createEditor() override;
    bool hasEditor() const override { return true; }

    const juce::String getName() const override { return "Corvus Instrument"; }
    bool acceptsMidi() const override { return true; }
    bool producesMidi() const override { return false; }
    bool isMidiEffect() const override { return false; }
    double getTailLengthSeconds() const override { return 10.0; }

    int getNumPrograms() override { return 1; }
    int getCurrentProgram() override { return 0; }
    void setCurrentProgram(int index) override { juce::ignoreUnused(index); }
    const juce::String getProgramName(int index) override
    {
        return index == 0 ? juce::String("Initial") : juce::String();
    }
    void changeProgramName(int index, const juce::String& name) override
    {
        juce::ignoreUnused(index, name);
    }

    void getStateInformation(juce::MemoryBlock& destination) override;
    void setStateInformation(const void* data, int sizeInBytes) override;

    juce::UndoManager undoManager;
    juce::AudioProcessorValueTreeState apvts;

private:
    static juce::AudioProcessorValueTreeState::ParameterLayout createParameterLayout();
    VoiceParameters currentVoiceParameters() const;

    CorvusSynthEngine synthEngine;
    juce::LinearSmoothedValue<float> outputGain;

    JUCE_DECLARE_NON_COPYABLE_WITH_LEAK_DETECTOR(CorvusInstrumentProcessor)
};
