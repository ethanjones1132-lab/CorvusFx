#pragma once

#include "CorvusSynthEngine.h"

#include <JuceHeader.h>

#include <memory>

struct InstrumentEffectsSettings
{
    float distortionAmount = 0.0f;
    float chorusDepth = 0.0f;
    float chorusMix = 0.0f;
    float chorusRate = 0.0f;
    float delayTimeMs = 0.0f;
    float delayFeedback = 0.0f;
    float delayMix = 0.0f;
    float delayDamping = 0.0f;
    float delayModulation = 0.0f;
    float reverbSize = 0.0f;
    float reverbDamping = 0.0f;
    float reverbMix = 0.0f;
    float reverbModulation = 0.0f;
    float masterMidDrive = 0.0f;
    float masterSideDrive = 0.0f;
    float masterWidth = 1.0f;
};

class CorvusInstrumentProcessor final : public juce::AudioProcessor
{
public:
    CorvusInstrumentProcessor();
    ~CorvusInstrumentProcessor() override;

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

    int getNumPrograms() override;
    int getCurrentProgram() override;
    void setCurrentProgram(int index) override;
    const juce::String getProgramName(int index) override;
    void changeProgramName(int index, const juce::String& name) override
    {
        juce::ignoreUnused(index, name);
    }

    void getStateInformation(juce::MemoryBlock& destination) override;
    void setStateInformation(const void* data, int sizeInBytes) override;
    InstrumentEffectsSettings settingsForFlight(float flight) const noexcept;

    juce::UndoManager undoManager;
    juce::AudioProcessorValueTreeState apvts;

private:
    struct EffectsCore;

    static juce::AudioProcessorValueTreeState::ParameterLayout createParameterLayout();
    VoiceParameters currentVoiceParameters() const;

    CorvusSynthEngine synthEngine;
    std::unique_ptr<EffectsCore> effects;
    juce::AudioBuffer<float> dryBuffer;
    juce::LinearSmoothedValue<float> fxAmount;
    juce::LinearSmoothedValue<float> flightAmount;
    juce::LinearSmoothedValue<float> outputGain;
    int currentProgram = 0;

    JUCE_DECLARE_NON_COPYABLE_WITH_LEAK_DETECTOR(CorvusInstrumentProcessor)
};
