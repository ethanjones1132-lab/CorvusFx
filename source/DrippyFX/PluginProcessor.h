#pragma once

#include <JuceHeader.h>

#include "dsp/CorvusEffects.h"

#include <array>
#include <atomic>
#include <map>
#include <set>
#include <utility>
#include <vector>

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

    // Parameter locking for randomize preservation
    void setParameterLocked(const juce::String& paramID, bool locked);
    bool isParameterLocked(const juce::String& paramID) const;

    // Preset A/B Compare
    void saveSlotA();
    void saveSlotB();
    void loadSlotA();
    void loadSlotB();
    bool isSlotA() const { return abSlotIsA; }
    bool hasPersistedABSnapshots() const { return abSnapshotsPersisted; }

    // MIDI Learn
    void startMidiLearn(const juce::String& paramID)
    {
        // Armed-learn state is read by the audio thread under midiMapLock;
        // write under the same lock so the capture branch can never see a
        // torn juce::String parameter ID.
        const juce::ScopedLock lock(midiMapLock);
        midiLearnParamID = paramID;
        midiLearnActive = true;
    }
    bool isMidiLearnActive() const { return midiLearnActive.load(); }
    void stopMidiLearn() { midiLearnActive = false; }
    bool hasMidiMapping(const juce::String& paramID) const;
    void clearMidiMapping(const juce::String& paramID);
    void clearAllMidiMappings();
    // Returns a snapshot copy taken under midiMapLock. Never return a
    // reference to the live map: it is mutated on the audio thread (learn
    // capture) and the message thread (clear/restore) under midiMapLock, so
    // any caller iterating it unsynchronized would race the insert/erase.
    std::map<int, juce::String> getMidiMappings() const
    {
        juce::CriticalSection& mapLock =
            const_cast<juce::CriticalSection&>(midiMapLock);
        const juce::ScopedLock lock(mapLock);
        return midiMap;
    }


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

    // CV-017: reusable, pre-reserved storage for the audio-thread CC apply
    // snapshot. Replaces the per-block std::map local that heap-allocated
    // (and freed) map nodes on every MIDI block: processBlock now only
    // clear-and-refills this member under midiMapLock. Clearing keeps the
    // reserved capacity and the refill appends plain copies (a juce::String
    // copy is a ref-count bump), so the refill never allocates. Capacity is
    // reserved off the audio thread in the constructor and re-asserted in
    // prepareToPlay; MIDI CC numbers are 0..127, so a full legal mapping
    // table is at most 128 entries — capping the refill at that width makes
    // growth impossible. Only the audio thread touches this member.
    std::vector<std::pair<int, juce::String>> mapSnapshot;

    std::set<juce::String> lockedParams;
    juce::CriticalSection lockedParamsLock;


    // Preset A/B Snapshot Storage
    static constexpr int NUM_AB_PARAMS = 24;
    std::array<float, NUM_AB_PARAMS> snapshotA = {};
    std::array<float, NUM_AB_PARAMS> snapshotB = {};
    bool abSlotIsA = true;
    // abSnapshotsPersisted: set true by setStateInformation when the host
    // state carried an "abSlots" child, so the editor constructor can skip
    // the blind reseed that would otherwise overwrite the restored
    // snapshots with identical live values.
    bool abSnapshotsPersisted = false;
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

        // Display-side peak decay, run on the message thread from the editor
        // timer (relaxed load/store is fine for approximate meter display).
        // Processor-side so decayed values are authoritative and a refresh
        // never resurrects a stale bar from a non-decaying atomic.
        void decayPeaks(float factor = 0.96f)
        {
            auto mul = [&](std::atomic<float>& a)
            {
                a.store(a.load(std::memory_order_relaxed) * factor,
                        std::memory_order_relaxed);
            };
            mul(inPeakL);  mul(inPeakR);
            mul(inRmsL);   mul(inRmsR);
            mul(outPeakL); mul(outPeakR);
            mul(outRmsL);  mul(outRmsR);
        }
    } levelMeters;

    JUCE_DECLARE_NON_COPYABLE_WITH_LEAK_DETECTOR(CorvusFXAudioProcessor)
};

using DrippyFXAudioProcessor = CorvusFXAudioProcessor;
