#pragma once

#include "CorvusSynthEngine.h"

#include <JuceHeader.h>

#include <atomic>
#include <cstdint>
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

class CorvusInstrumentProcessor final : public juce::AudioProcessor,
                                        private juce::AudioProcessorValueTreeState::Listener
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
    // CV-074: the offline-render tail, derived from the worst configured
    // settings by scripts/check_cv074_offline_tail.py: the 10.0 s maximum
    // release envelope, then the Flight=1 effects chain (500 ms delay at 0.48
    // feedback = 4.71 s to -60 dB, Size 0.92 reverb RT60 = 4.78 s, 41.8 ms
    // pre-delay) which is serial after it = 19.53 s required. A bare constant:
    // the override reads nothing, so realtime processing is untouched.
    double getTailLengthSeconds() const override { return 20.0; }

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
    void parameterChanged(const juce::String& parameterID, float newValue) override;
    InstrumentEffectsSettings settingsForFlight(float flight) const noexcept;

    juce::UndoManager undoManager;
    juce::AudioProcessorValueTreeState apvts;
    float getLastPreClampPeak() const noexcept { return lastPreClampPeak; }

private:
    struct EffectsCore;

    static juce::AudioProcessorValueTreeState::ParameterLayout createParameterLayout();
    struct ParameterGeneration
    {
        float wave = 2.0f, attack = 0.05f, decay = 0.35f, sustain = 0.75f;
        float release = 1.5f, fxAmount = 0.65f, flight = 0.5f, output = -6.0f;
        int programIndex = 0;
    };
    void publishParameterGeneration() noexcept;
    ParameterGeneration readParameterGeneration(ParameterGeneration lastGood) const noexcept;
    VoiceParameters voiceParametersFor(const ParameterGeneration& generation) const noexcept;

    CorvusSynthEngine synthEngine;
    std::unique_ptr<EffectsCore> effects;
    juce::AudioBuffer<float> dryBuffer;
    juce::LinearSmoothedValue<float> fxAmount;
    juce::LinearSmoothedValue<float> flightAmount;
    juce::LinearSmoothedValue<float> outputGain;
    float lastPreClampPeak = 0.0f;
    std::atomic<int> currentProgram { 0 };
    std::atomic_flag generationWriter = ATOMIC_FLAG_INIT;
    std::atomic<bool> generationDirty { false };
    std::atomic<std::uint32_t> presetBatchSequence { 0 };
    std::atomic<std::uint32_t> generationSequence { 0 };
    std::atomic<float> generationWave { 2.0f }, generationAttack { 0.05f };
    std::atomic<float> generationDecay { 0.35f }, generationSustain { 0.75f };
    std::atomic<float> generationRelease { 1.5f }, generationFxAmount { 0.65f };
    std::atomic<float> generationFlight { 0.5f }, generationOutput { -6.0f };
    std::atomic<int> generationProgramIndex { 0 };
    ParameterGeneration lastGoodGeneration;

    JUCE_DECLARE_NON_COPYABLE_WITH_LEAK_DETECTOR(CorvusInstrumentProcessor)
};
