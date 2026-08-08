#pragma once

#include <JuceHeader.h>

#include "dsp/CorvusEffects.h"

#include <array>
#include <atomic>
#include <map>

//==============================================================================
class CorvusFXAudioProcessor : public juce::AudioProcessor,
    public juce::AudioProcessorValueTreeState::Listener
{
public:
    CorvusFXAudioProcessor();
    ~CorvusFXAudioProcessor() override;

    void prepareToPlay(double sampleRate, int samplesPerBlock) override;
    void releaseResources() override;
#ifndef JucePlugin_PreferredChannelConfigurations
    bool isBusesLayoutSupported(const BusesLayout& layouts) const override;
#endif
    void processBlock(juce::AudioBuffer<float>&, juce::MidiBuffer&) override;
    juce::AudioProcessorEditor* createEditor() override;
    bool hasEditor() const override;
    const juce::String getName() const override;
    bool acceptsMidi() const override;
    bool producesMidi() const override;
    bool isMidiEffect() const override;
    double getTailLengthSeconds() const override;
    int getNumPrograms() override;
    int getCurrentProgram() override;
    void setCurrentProgram(int index) override;
    const juce::String getProgramName(int index) override;
    void changeProgramName(int index, const juce::String& newName) override;
    void getStateInformation(juce::MemoryBlock& destData) override;
    void setStateInformation(const void* data, int sizeInBytes) override;
    juce::AudioProcessorValueTreeState::ParameterLayout createParameterLayout();
    juce::AudioProcessorValueTreeState apvts;
    juce::UndoManager undoManager;
    void parameterChanged(const juce::String& parameterID, float newValue) override;
    void loadPreset(int index);
    void randomizePreset();

    // Preset A/B Compare
    void saveSlotA();
    void saveSlotB();
    void loadSlotA();
    void loadSlotB();
    bool isSlotA() const { return abSlotIsA; }

    // MIDI Learn
    void startMidiLearn(const juce::String& paramID) { midiLearnParamID = paramID; midiLearnActive = true; }
    void stopMidiLearn() { midiLearnActive = false; }
    bool hasMidiMapping(const juce::String& paramID) const;
    void clearMidiMapping(const juce::String& paramID);
    void clearAllMidiMappings();
    const std::map<int, juce::String>& getMidiMappings() const { return midiMap; }


private:
    EnhancedChorus chorus;
    EnhancedDelay delay;
    ProfessionalDistortion distortion;
    UpgradedReverb upgradedReverb;
    MasterOutputStage masterOutput;
    juce::AudioBuffer<float> dryBuffer;
    double lastSampleRate = 44100.0;

    // ── Parameter smoothing ──
    // Smoothed parameter values eliminate zipper noise from knob movement
    // and host automation. Without smoothing, atomic parameter reads
    // jump instantly between blocks, creating audible clicks/clicks.
    // 20ms smoothing time: fast enough to feel responsive, slow enough
    // to remove all artifacts. Standard for professional VST3 plugins.
    //
    // Usage: setTargetValue() in processBlock header, then getNextValue()
    // per sample for smooth interpolation across the block.
    juce::LinearSmoothedValue<float> smoothOverall;
    juce::LinearSmoothedValue<float> smoothFatness;
    juce::LinearSmoothedValue<float> smoothChorusDepth;
    juce::LinearSmoothedValue<float> smoothChorusRate;
    juce::LinearSmoothedValue<float> smoothChorusMix;
    juce::LinearSmoothedValue<float> smoothDelayTime;
    juce::LinearSmoothedValue<float> smoothDelayFeedback;
    juce::LinearSmoothedValue<float> smoothDelayMix;
    juce::LinearSmoothedValue<float> smoothDelayDamping;
    juce::LinearSmoothedValue<float> smoothDelayMod;
    juce::LinearSmoothedValue<float> smoothReverbSize;
    juce::LinearSmoothedValue<float> smoothReverbDamping;
    juce::LinearSmoothedValue<float> smoothReverbMix;
    juce::LinearSmoothedValue<float> smoothReverbMod;
    juce::LinearSmoothedValue<float> smoothMasterDrive;
    juce::LinearSmoothedValue<float> smoothMasterWidth;
    juce::LinearSmoothedValue<float> smoothMasterMidDrive;
    juce::LinearSmoothedValue<float> smoothMasterSideDrive;
    juce::LinearSmoothedValue<float> smoothOutputTrim;

    // Bypass crossfade gains -- when a module bypass is toggled, the wet/dry
    // mix ramps over ~30ms via LinearSmoothedValue instead of a hard switch,
    // eliminating the click/step discontinuity (audible on Delay/Reverb tails).
    juce::LinearSmoothedValue<float> bypassGainDist;
    juce::LinearSmoothedValue<float> bypassGainChorus;
    juce::LinearSmoothedValue<float> bypassGainDelay;
    juce::LinearSmoothedValue<float> bypassGainReverb;
    juce::LinearSmoothedValue<float> bypassGainMaster;


    // MIDI Learn - maps MIDI CC numbers to parameter IDs
    std::map<int, juce::String> midiMap;
    juce::CriticalSection midiMapLock;


    // Preset A/B Snapshot Storage
    static constexpr int NUM_AB_PARAMS = 24;
    std::array<float, NUM_AB_PARAMS> snapshotA = {};
    std::array<float, NUM_AB_PARAMS> snapshotB = {};
    bool abSlotIsA = true;
    // MIDI Learn State (accessed across audio/message threads)
    std::atomic<bool> midiLearnActive{false};
    juce::String midiLearnParamID;
    // ── Level Meter State ──
    // Smoothed peak/RMS meters for input and output.
    // Updated in processBlock (audio thread), read by editor (message thread)
    // via atomic floats. No locks needed — relaxed atomics are sufficient
    // for meter display (approximate values are fine).
public:
    struct LevelMeters
    {
        std::atomic<float> inPeakL  { 0.0f }, inPeakR  { 0.0f };
        std::atomic<float> inRmsL   { 0.0f }, inRmsR   { 0.0f };
        std::atomic<float> outPeakL { 0.0f }, outPeakR { 0.0f };
        std::atomic<float> outRmsL  { 0.0f }, outRmsR  { 0.0f };
    } levelMeters;

    JUCE_DECLARE_NON_COPYABLE_WITH_LEAK_DETECTOR(CorvusFXAudioProcessor)
};

using DrippyFXAudioProcessor = CorvusFXAudioProcessor;
