#pragma once

#include <JuceHeader.h>

#include "dsp/CorvusEffects.h"

#include <array>
#include <atomic>
#include <cstdint>
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
    //
    // CV-027: arming resolves the target to a fixed roster slot, so the audio
    // thread never reads the juce::String parameter ID and never allocates.
    // CV-029: "preset" is not a legal MIDI-learn target. A CC bound to the
    // program parameter has no knob-level meaning and would fan a raw CC out
    // into loadPreset() (an undo transaction plus a full parameter rewrite), so
    // arming is refused here, in the learn fold, and at state restore; the
    // roster itself also excludes the program parameter, so no published slot
    // can ever resolve to it.
    void startMidiLearn(const juce::String& paramID)
    {
        if (paramID == "preset")
            return;
        const int slot = findMidiMapParamSlot(paramID);
        if (slot < 0)
            return;
        // Publish the roster slot BEFORE arming: the audio thread only ever
        // reads this atomic and never the juce::String parameter id.
        midiLearnParamSlot.store(slot, std::memory_order_relaxed);
        midiLearnActive = true;
    }
    bool isMidiLearnActive() const { return midiLearnActive.load(); }
    void stopMidiLearn() { midiLearnActive = false; }
    bool hasMidiMapping(const juce::String& paramID) const;
    void clearMidiMapping(const juce::String& paramID);
    void clearAllMidiMappings();
    // Returns a snapshot copy taken under midiMapLock. Never return a
    // reference to the live map: it is mutated by the message-thread fold
    // (learn), clear and restore paths, and CV-027 keeps the audio thread out
    // of it entirely (the callback reads the published CC→slot table instead),
    // but the copy keeps any future caller from aliasing message-thread state.
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


    // ── CV-028 / CV-048: one coherent parameter generation ──
    // A preset, A/B or session recall rewrites the whole parameter set with one
    // notification per id. Read one parameter at a time, a block can pick up the
    // new chorus depth next to the old reverb mix and render a hybrid of two
    // presets, so the recall has to land as ONE generation. Every recall path is
    // bracketed by ParameterGenerationBatch; publishParameterGeneration()
    // commits the 24 block parameters only when that batch epoch is even and
    // unchanged across the capture; and the block header re-seeds its targets
    // from lastGoodGeneration whenever the epoch moved while it read. The writer
    // flag, batch epoch, sequentially consistent payload and last-good fallback
    // are the contract the instrument processor already uses.
    //
    // The FX block header is this publisher's only consumer, so it captures once
    // per block instead of chasing per-parameter notifications. That keeps every
    // knob and automation edit live (the capture still reads the raw parameters
    // every block) and keeps lastGoodGeneration a current, coherent pre-recall
    // set rather than a set that can only be as fresh as the last notification.
    struct ParameterGeneration
    {
        float overall = 100.0f, fatness = 0.0f, chorusDepth = 0.0f;
        float chorusRate = 2.0f, chorusMix = 50.0f, delayTime = 250.0f;
        float delayFeedback = 30.0f, delayMix = 0.0f, delayDamping = 40.0f;
        float delayMod = 30.0f, reverbSize = 50.0f, reverbDamping = 50.0f;
        float reverbMix = 0.0f, reverbMod = 30.0f, masterDrive = 0.0f;
        float masterWidth = 100.0f, masterMidDrive = 0.0f;
        float masterSideDrive = 0.0f, outputTrim = 100.0f;
        bool distortionBypass = false, chorusBypass = false, delayBypass = false;
        bool reverbBypass = false, masterBypass = false;
    };
    void publishParameterGeneration() noexcept;
    ParameterGeneration readParameterGeneration(ParameterGeneration lastGood) const noexcept;
    void applyParameterGeneration(const ParameterGeneration& generation) noexcept;

    std::atomic_flag generationWriter = ATOMIC_FLAG_INIT; // one publisher at a time
    std::atomic<std::uint32_t> presetBatchSequence { 0 }; // odd = recall in flight
    std::atomic<std::uint32_t> generationSequence { 0 };  // odd = payload write
    std::atomic<float> generationOverall { 100.0f }, generationFatness { 0.0f };
    std::atomic<float> generationChorusDepth { 0.0f }, generationChorusRate { 2.0f };
    std::atomic<float> generationChorusMix { 50.0f }, generationDelayTime { 250.0f };
    std::atomic<float> generationDelayFeedback { 30.0f };
    std::atomic<float> generationDelayMix { 0.0f };
    std::atomic<float> generationDelayDamping { 40.0f };
    std::atomic<float> generationDelayMod { 30.0f };
    std::atomic<float> generationReverbSize { 50.0f };
    std::atomic<float> generationReverbDamping { 50.0f };
    std::atomic<float> generationReverbMix { 0.0f };
    std::atomic<float> generationReverbMod { 30.0f };
    std::atomic<float> generationMasterDrive { 0.0f };
    std::atomic<float> generationMasterWidth { 100.0f };
    std::atomic<float> generationMasterMidDrive { 0.0f };
    std::atomic<float> generationMasterSideDrive { 0.0f };
    std::atomic<float> generationOutputTrim { 100.0f };
    std::atomic<bool> generationDistortionBypass { false };
    std::atomic<bool> generationChorusBypass { false };
    std::atomic<bool> generationDelayBypass { false };
    std::atomic<bool> generationReverbBypass { false };
    std::atomic<bool> generationMasterBypass { false };
    ParameterGeneration lastGoodGeneration;


    // ── CV-027: lock-free MIDI-map publication ──
    // The authoritative map and its lock are message-thread only. To make a
    // change visible to processBlock without the audio thread taking that
    // lock, publishMidiMap() flattens midiMap into one parameter-roster slot
    // index per legal CC and publishes the table behind a sequence counter
    // (odd = publication in progress). processBlock try-reads the table into
    // preallocated arrays; if a publication overlaps the read it keeps its
    // last coherent view and retries on the next block. The callback therefore
    // never locks, never touches a juce::String and never allocates — including
    // on the first learn event, which only stores two ints in pendingLearnCc /
    // pendingLearnSlot for the message-thread fold.
    std::map<int, juce::String> midiMap;
    juce::CriticalSection midiMapLock;

    static constexpr int MAX_MIDI_CCS = 128;   // legal MIDI CC domain 0..127
    std::array<std::atomic<int>, MAX_MIDI_CCS> publishedMidiCcSlots {};
    std::atomic<unsigned> midiMapSequence { 0 };     // even = stable, odd = busy
    std::array<int, MAX_MIDI_CCS> midiMapView {};    // audio thread: last good
    std::array<int, MAX_MIDI_CCS> midiMapScratch {}; // audio thread: try-read
    unsigned midiMapViewSequence = 0;

    // Armed learn target (message thread writes; audio thread reads the slot).
    std::atomic<int> midiLearnParamSlot { -1 };
    // Audio-thread capture hand-off, applied by foldPendingMidiLearn().
    std::atomic<int> pendingLearnCc { -1 };
    std::atomic<int> pendingLearnSlot { -1 };

    int findMidiMapParamSlot(const juce::String& paramID) const;
    void publishMidiMap();
    void foldPendingMidiLearn();
    void refreshMidiMapView() noexcept;

    // ── CV-029: audio-thread → message-thread host-notification mailbox ──
    // One slot per automatable parameter, populated ONCE in the constructor
    // from the fixed parameter layout, so the audio thread only ever performs
    // a pointer match. CV-027 reuses the same roster as the MIDI-map slot
    // table: a published CC row stores a slot index, so the apply path resolves
    // the parameter pointer and its id without any juce::String work. The
    // "preset" program parameter is deliberately absent: a CC can never fan
    // out into a whole preset change. processBlock stores value + pending
    // (relaxed/release atomics only — no lock, no allocation, no host call, no
    // APVTS listener work); the message thread drains the mailbox from the
    // processor timer and is the only place a MIDI CC reaches
    // setValueNotifyingHost. 64 slots comfortably cover the 24-parameter
    // layout plus any future addition.
    static constexpr int MAX_MIDI_HOST_NOTIFY_PARAMS = 64;
    struct MidiHostNotifySlot
    {
        juce::RangedAudioParameter* param = nullptr; // fixed off the audio thread
        juce::String id;                             // message thread only
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
    // CV-067: the slots belong to the processor. The constructor seeds both
    // from the live parameter values once and marks them persisted, and
    // setStateInformation seeds them for a state that carried no complete
    // "abSlots" pair, so no session and no editor open/close ever leaves a
    // slot unseeded (an all-zero mix).
    void seedABSnapshotsFromLiveParameters();
    // abSnapshotsPersisted: true when both slots were seeded or restored.
    // The constructor sets it after seeding; setStateInformation sets it only
    // when the host state carried a complete "abSlots" pair, and leaves it
    // false when it derived the slots from the restored parameters instead.
    // No code path gates behaviour on it any more (the editor never reseeds);
    // it reports where the slots came from.
    bool abSnapshotsPersisted = false;
    std::atomic<bool> restoringPresetState{false};
    // CV-066: a freshly inserted FX must start on the factory default preset
    // (0, "Clean Sparkle") without opening an undo transaction, a change
    // gesture or a host notification. presetLoadSilent marks that
    // construction-time load; hostProgramRecall carries the program index a
    // setCurrentProgram() call is about to echo back through the "preset"
    // parameter listener, so loadPreset() can skip loading the same preset
    // twice (and -1 means "no program change in flight").
    std::atomic<bool> presetLoadSilent{false};
    std::atomic<int> hostProgramRecall{-1};
    // MIDI Learn State (accessed across audio/message threads)
    // CV-027: only the atomic arm flag is shared; the armed target lives in the
    // atomic roster slot above, so the audio thread never reads a juce::String.
    std::atomic<bool> midiLearnActive{false};
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
