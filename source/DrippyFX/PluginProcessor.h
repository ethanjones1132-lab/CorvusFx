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
    public juce::AudioProcessorValueTreeState::Listener,
    private juce::Timer
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
        // CV-029: "preset" is not a legal MIDI-learn target. A CC bound to the
        // program parameter has no knob-level meaning and would fan a raw CC
        // out into loadPreset() (an undo transaction plus a full parameter
        // rewrite), so arming is refused here as well as in the audio-thread
        // capture branch and the apply path.
        if (paramID == "preset")
            return;
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

    // CV-029: message-thread drain for the audio-thread CC mailbox.
    //
    // processBlock never notifies the host for a MIDI CC. It only records the
    // newest requested normalised value in that parameter's pending slot
    // (relaxed atomics, no lock, no allocation, no host call). This drain runs
    // on the editor timer (message thread) and performs the single
    // setValueNotifyingHost per parameter per tick, so a mapped knob can never
    // run host-facing work, an undo transaction or APVTS listener work inside
    // a render callback. Returns the number of parameters notified.
    int drainPendingMidiHostNotifications();

    // Message-thread driver for the drain (CV-029 review fix). The editor only
    // exists while its window is open, and a DAW plays with it closed, so the
    // drain cannot depend on it: the processor ticks its own timer.
    void timerCallback() override;


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

    // ── CV-029: audio-thread → message-thread host-notification mailbox ──
    // One slot per automatable parameter, populated ONCE in the constructor
    // from the fixed parameter layout, so the audio thread only ever performs
    // a pointer match. The "preset" program parameter is deliberately absent:
    // a CC can never fan out into a whole preset change. processBlock stores
    // value + pending (relaxed/release atomics only — no lock, no allocation,
    // no host call, no APVTS listener work); the message thread drains the
    // mailbox from the editor timer and is the only place a MIDI CC reaches
    // setValueNotifyingHost. 64 slots comfortably cover the 24-parameter
    // layout plus any future addition.
    static constexpr int MAX_MIDI_HOST_NOTIFY_PARAMS = 64;
    struct MidiHostNotifySlot
    {
        juce::RangedAudioParameter* param = nullptr; // fixed off the audio thread
        std::atomic<float> value { 0.0f };           // newest requested value
        std::atomic<bool> pending { false };         // set by the audio thread
    };
    std::array<MidiHostNotifySlot, MAX_MIDI_HOST_NOTIFY_PARAMS> midiHostNotifySlots;
    int numMidiHostNotifySlots = 0;

    // Audio thread: record the newest requested normalised value for `param`
    // (CC value / 127, unchanged, so the parameter's own rounding is exactly
    // what it is today). Unknown parameters are dropped, never queued.
    void stageMidiHostNotify(juce::RangedAudioParameter* param, float normValue);

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
    std::atomic<bool> restoringPresetState{false};
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
