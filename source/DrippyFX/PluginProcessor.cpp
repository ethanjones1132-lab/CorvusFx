#include "PluginProcessor.h"
#include "PluginEditor.h"
#include <cmath>
#include <algorithm>
#include <cstdint>

namespace
{
// CV-028: marks a multi-parameter recall as one batch. The epoch is bumped when
// the batch opens and closes, so a block-header capture that overlapped the
// writes — including one that starts and finishes entirely inside the capture —
// is rejected by publishParameterGeneration(), and so processBlock can tell that
// its own header reads straddle the recall. The epoch also tells the writer's
// own publish that the batch is complete.
class ParameterGenerationBatch final
{
public:
    explicit ParameterGenerationBatch(std::atomic<std::uint32_t>& sequence) noexcept
        : sequence(sequence)
    {
        sequence.fetch_add(1, std::memory_order_seq_cst);
    }

    // Closes the batch so the completed set can be published before the object
    // leaves scope. Idempotent: the destructor is the early-return/throw path.
    void close() noexcept
    {
        if (! closed)
        {
            closed = true;
            sequence.fetch_add(1, std::memory_order_seq_cst);
        }
    }

    ~ParameterGenerationBatch() { close(); }

private:
    std::atomic<std::uint32_t>& sequence;
    bool closed = false;
};
}

CorvusFXAudioProcessor::CorvusFXAudioProcessor()
#ifndef JucePlugin_PreferredChannelConfigurations
    : AudioProcessor(BusesProperties()
#if ! JucePlugin_IsMidiEffect
#if ! JucePlugin_IsSynth
        .withInput("Input", juce::AudioChannelSet::stereo(), true)
#endif
        .withOutput("Output", juce::AudioChannelSet::stereo(), true)
#endif
    ),
#else
    :
#endif
apvts(*this, &undoManager, "Parameters", createParameterLayout())
{
    apvts.addParameterListener("preset", this);

    // CV-017 / CV-027: the audio-thread MIDI-map view and the host-notify
    // roster are fixed-size arrays reserved here, off the audio thread, so the
    // callback's try-read and CC apply never allocate.
    for (auto& slot : publishedMidiCcSlots)
        slot.store(-1, std::memory_order_relaxed);
    midiMapView.fill(-1);
    midiMapScratch.fill(-1);

    // CV-029: build the CC → host-notification roster once, off the audio
    // thread. One slot per automatable parameter; the program parameter
    // ("preset") is deliberately excluded (a CC must never fan out into a
    // whole preset change), so a stale or restored CC→preset mapping can never
    // reach the host from the apply path and no preset slot can ever be
    // staged. CV-027 uses the same roster as the published MIDI-map slot
    // table, so each slot also carries its parameter id for the
    // message-thread publication path.
    auto* programParam = apvts.getParameter("preset");
    for (auto* param : getParameters())
    {
        auto* ranged = dynamic_cast<juce::RangedAudioParameter*>(param);
        if (ranged == nullptr || ranged == programParam)
            continue;
        if (numMidiHostNotifySlots >= MAX_MIDI_HOST_NOTIFY_PARAMS)
            break;
        auto& slot = midiHostNotifySlots[(size_t) numMidiHostNotifySlots];
        slot.param = ranged;
        slot.id = ranged->getParameterID();
        ++numMidiHostNotifySlots;
    }

    // CV-027: publish the (empty) initial map so the first audio block already
    // has a coherent view instead of waiting for the first message-thread edit.
    publishMidiMap();

    // CV-028: commit the initial parameter set and seed the block header's
    // last-good generation before the first render, so a block that lands while
    // a recall is already in flight still has a coherent set to fall back on.
    publishParameterGeneration();
    lastGoodGeneration = readParameterGeneration(lastGoodGeneration);

    // CV-029: the message-thread drain runs from the processor's own timer so a
    // mapped CC reaches the host whether or not the editor window is open.
    startTimerHz(30);
}

CorvusFXAudioProcessor::~CorvusFXAudioProcessor()
{
    // Stop the drain timer before any member it touches is torn down.
    stopTimer();
    apvts.removeParameterListener("preset", this);
}

void CorvusFXAudioProcessor::parameterChanged(const juce::String& parameterID, float newValue)
{
    if (parameterID == "preset")
    {
        // CV-041: "preset" is registered non-automatable, so a plain host
        // automation write can no longer reach this branch. Recall still
        // arrives from the editor combo, a host program change
        // (setCurrentProgram) and state restore, which must keep working.
        if (restoringPresetState.load())
            return;
        // ComboBoxAttachment maps the parameter value to combo box item ID.
        // The combo has 42 items (IDs 1-42) with 6 disabled separators (IDs 1,8,15,22,29,36).
        // We convert the item ID to a preset index via a lookup table.
        static const int idToPreset[43] = {
            -1, -1, 0, 1, 2, 3, 4, 5,   // IDs 0-7  (0=unused, 1=separator, 2-7=CLEAN presets 0-5)
            -1, 6, 7, 8, 9,10,11,       // IDs 8-14 (8=separator, 9-14=WARM presets 6-11)
            -1,12,13,14,15,16,17,        // IDs 15-21 (15=separator, 16-21=CREATIVE presets 12-17)
            -1,18,19,20,21,22,23,        // IDs 22-28 (22=separator, 23-28=EXTREME presets 18-23)
            -1,24,25,26,27,28,29,        // IDs 29-35 (29=separator, 30-35=SIGNATURE presets 24-29)
            -1,30,31,32,33,34,35         // IDs 36-41 (36=separator, 37-41=DREAM presets 30-35)
        };
        int id = static_cast<int>(newValue + 0.5f);
        if (id >= 2 && id <= 42 && idToPreset[id] >= 0)
            loadPreset(idToPreset[id]);
    }
}

void CorvusFXAudioProcessor::loadPreset(int index)
{
    // index is the preset array index (0-35), mapped from combo item ID
    // via idToPreset[] in parameterChanged(), or directly from DAW host
    // via setCurrentProgram's presetToId[] lookup.
    // Combo order: CLEAN [0-5], WARM [6-11], CREATIVE [12-17], EXTREME [18-23], SIGNATURE [24-29], DREAM [30-35]
    if (index < 0 || index >= 36) return;
    undoManager.beginNewTransaction("Load Preset");

    // CV-028: the writes below are one recall. The batch epoch keeps a block
    // header that overlaps them from rendering a mix of the old preset and the
    // new one; the completed set is published as one generation at the end.
    ParameterGenerationBatch batch(presetBatchSequence);

    //                    fat  cD   cR    cM   dT   dFb  dM   dDmp dMod rS   rDmp rM   rMod  mDrv mWid mMid mSide dByp cByp dByp rByp mByp
    struct P { float fat, cD, cR, cM, dT, dFb, dM, dDmp, dMod, rS, rDmp, rM, rMod, mDrv, mWid, mMid, mSide, distByp, chorusByp, delayByp, reverbByp, masterByp, oTrim; };
    static const P presets[36] = {
        // ── CLEAN (pos 0-5): transparent enhancement, pristine highs ──────
        // 0: Clean Sparkle — subtle widening, pristine highs
        {  8, 25, 1.2f, 35,   0,  0,  0,  0,  0,  20, 55, 10, 20,   0, 100,   0,   0, 0, 0, 0, 0, 0, 100 },
        // 1: Crystal Shimmer — chorus-forward, bright and airy
        {  5, 60, 3.0f, 70, 130, 15, 15, 25, 40,  50, 25, 20, 75,   0, 100,   0,   0, 0, 0, 0, 0, 0, 100 },
        // 2: Silk Thread — ultra-smooth chorus, no drive, gentle space
        {  0, 40, 0.5f, 60,   0,  0,  0,  0,  0,  35, 50, 12, 40,   0, 100,   0,   0, 0, 0, 0, 0, 0, 100 },
        // 3: Subtle Glue — bus cohesion, barely-there enhancement
        { 28,  8, 1.2f, 18,  80, 12,  8, 45, 10,  25, 60,  8, 12,   0, 100,   0,   0, 0, 0, 0, 0, 0, 100 },
        // 4: Glass Canon — pristine stereo widening, shimmering highs, zero drive
        {  0, 35, 2.8f, 40, 110,  8, 15, 15, 45,  45, 40, 22, 65,   0, 120,   0,   0, 0, 0, 0, 0, 0, 100 },
        // 5: Air Lift — gentle HF excitation, subtle chorus, airy top end
        { 12, 30, 4.0f, 35,   0,  0,  0,  0,  0,  20, 30,  8, 55,   0, 100,   0,   0, 0, 0, 0, 0, 0, 100 },

        // ── WARM (pos 6-11): analog-style saturation, musical thickening ───
        // 6: Warm Glow — medium drive, gentle chorus thickening
        { 40, 18, 1.8f, 30, 180, 20, 12, 55, 25,  35, 65, 15, 25,  20, 100,  10,   5, 0, 0, 0, 0, 0, 100 },
        // 7: Vintage Vibe — lo-fi warmth, rolled-off highs
        { 55, 30, 0.7f, 40, 280, 32, 22, 80, 20,  55, 75, 18, 15,  30, 100,  15,  10, 0, 0, 0, 0, 0, 100 },
        // 8: Thick Sauce — heavy saturation, chorus thickening
        { 72, 35, 2.2f, 45, 200, 28, 18, 50, 35,  40, 55, 18, 30,  40, 100,  20,  15, 0, 0, 0, 0, 0, 100 },
        // 9: Tight Punch — controlled, punchy, no excess
        { 45, 12, 2.0f, 22, 100, 18, 10, 55, 15,  28, 65,  8, 18,  15, 100,   5,   5, 0, 0, 0, 0, 0, 100 },
        // 10: Cozy Hiss — cassette deck warmth, gentle wow, lo-fi magic
        { 35, 15, 0.9f, 28, 220, 35, 20, 85, 55,  30, 70, 12, 40,  25, 100,  10,  10, 0, 0, 0, 0, 0, 100 },
        // 11: Tube Glow — mild tube drive, rich harmonics, subtle room verb
        { 50, 10, 1.5f, 20,   0,  0,  0,  0,  0,  25, 50, 12, 25,  20, 100,  10,   0, 0, 0, 0, 0, 0, 100 },

        // ── CREATIVE (pos 12-17): modulation-forward, sound design ─────────
        // 12: Dreamy Space — low drive, deep chorus, big reverb
        { 12, 50, 0.8f, 55, 420, 35, 25, 40, 30,  85, 30, 55, 65,  10, 110,   5,  15, 0, 0, 0, 0, 0, 100 },
        // 13: Cosmic Wide — maximum stereo width, deep modulation
        { 22, 75, 3.5f, 65, 160, 25, 28, 30, 60,  80, 25, 45, 85,   0, 130,   0,  20, 0, 0, 0, 0, 0, 100 },
        // 14: Molten Core — heavy saturation into drenched chorus
        { 78, 55, 1.5f, 70, 150, 22, 20, 45, 30,  25, 45, 12, 35,  50, 100,  25,  20, 0, 0, 0, 0, 0, 100 },
        // 15: Sunspot — fast bright chorus + short slapback delay
        {  0, 45, 4.5f, 55,  65, 10, 25, 20, 35,  15, 40,  5, 50,   0, 100,   0,   0, 0, 0, 0, 0, 0, 100 },
        // 16: Nebula Drift — slow evolving chorus + long pre-delay reverb
        { 20, 65, 0.3f, 55, 300, 40, 18, 50, 40,  88, 35, 55, 80,   5, 115,   0,  10, 0, 0, 0, 0, 0, 100 },
        // 17: Shimmerfall — cascading delay into shimmer reverb, ethereal wash
        {  5, 40, 2.0f, 45, 350, 50, 40, 35, 45,  80, 15, 60, 90,  10, 120,   5,  15, 0, 0, 0, 0, 0, 100 },

        // ── EXTREME (pos 18-23): aggressive, heavy processing ──────────────
        // 18: Deep Echo — tape delay focus, dark repeats
        { 18, 12, 1.5f, 20, 520, 58, 55, 75, 50,  45, 60, 15, 25,  15, 100,  10,  10, 0, 0, 0, 0, 0, 100 },
        // 19: Aggressive Drive — in-your-face distortion character
        { 88, 15, 2.0f, 25, 200, 25, 15, 60, 25,  30, 55, 10, 20,  70, 100,  30,  20, 0, 0, 0, 0, 0, 100 },
        // 20: Lush Pad — massive reverb wash for sustained sounds
        { 15, 45, 1.0f, 50, 380, 30, 15, 35, 30,  92, 20, 65, 70,   5, 120,   0,  15, 0, 0, 0, 0, 0, 100 },
        // 21: Event Horizon — long delay + heavy feedback into massive reverb
        { 10, 20, 0.6f, 30, 800, 65, 45, 55, 45,  95, 15, 70, 90,  20, 125,  10,  25, 0, 0, 0, 0, 0, 100 },
        // 22: Iron Press — heavy parallel compression via drive + tight verb
        { 65,  5, 1.8f, 15,  60, 15,  8, 70, 20,  18, 80,  6, 10,  40,  90,  20,  10, 0, 0, 0, 0, 0, 100 },
        // 23: Obliterator — maxed drive, deep chorus, long feedback, giant hall
        { 95, 50, 1.2f, 55, 600, 70, 40, 65, 50,  90, 30, 55, 85,  80, 100,  40,  30, 0, 0, 0, 0, 0, 100 },

        // ── SIGNATURE (pos 24-29): curated artist-style sounds, distinct character ──
        // 24: Velvet Morning — warm tape saturation, gentle chorus, silk reverb
        { 32, 22, 0.7f, 28, 120, 18, 12, 35, 15,  30, 55, 18, 35,  15, 100,   8,   5, 0, 0, 0, 0, 0, 100 },
        // 25: Neon Dusk — bright chorus, crisp delay, crystalline highs
        {  8, 55, 3.2f, 45, 280, 22, 18, 15, 40,  60, 25, 35, 70,  10, 115,   0,  12, 0, 0, 0, 0, 0, 100 },
        // 26: Basement Sessions — gritty drive, dark delay, underground vibe
        { 62, 18, 1.1f, 20, 450, 45, 35, 65, 30,  40, 65, 12, 20,  45,  95,  18,  15, 0, 0, 0, 0, 0, 100 },
        // 27: Cathedral Drift — massive reverb, slow chorus, spiritual space
        {  0, 48, 0.25f, 60, 900, 55, 30, 25, 50,  95, 20, 70, 85,   0, 130,   0,  20, 0, 0, 0, 0, 0, 100 },
        // 28: Circuit Bent — experimental modulation, glitchy texture
        { 45, 70, 4.8f, 65,  45, 12, 25, 10, 60,  25, 40, 15, 60,  25, 105,   5,  18, 0, 0, 0, 0, 0, 100 },
        // 29: Midnight Oil — saturated warmth, tape echo, late-night intimacy
        { 58, 15, 0.6f, 30, 320, 40, 28, 80, 45,  35, 70, 18, 25,  35, 100,  12,  10, 0, 0, 0, 0, 0, 100 },

        // ── DREAM (pos 30-35): ambient, ethereal, deep soundscapes ──────
        // 30: Cloud Chamber — vast spatial wash, barely-there modulation, floating ambience
        {  5, 35, 0.15f, 55, 750, 50, 30, 45, 55,  90, 45, 75, 65,   0, 135,   0,  22, 0, 0, 0, 0, 0, 100 },
        // 31: Frozen Lake — crystalline chorus, long shimmer reverb, glassy reflections
        {  0, 55, 2.0f, 60, 400, 35, 45, 25, 50,  88, 25, 70, 85,   0, 125,   0,  18, 0, 0, 0, 0, 0, 100 },
        // 32: Ash & Ember — warm low-end drive, dark tape delay, glowing decay
        { 48, 22, 0.5f, 25, 550, 55, 42, 90, 60,  55, 80, 15, 20,  30,  95,  12,  10, 0, 0, 0, 0, 0, 100 },
        // 33: Stargate Portal — rotating modulation, long feedback, cosmic return
        { 25, 60, 0.9f, 65, 650, 60, 50, 30, 65,  70, 20, 60, 80,  15, 140,   5,  30, 0, 0, 0, 0, 0, 100 },
        // 34: Underwater Cathedral — massive low reverb, slow pitch drift, submerged depth
        { 15, 40, 0.08f, 70, 900, 65, 35, 85, 40,  95, 50, 80, 40,   5, 130,   0,  15, 0, 0, 0, 0, 0, 100 },
        // 35: Solar Flare — bright piercing drive, fast chorus, explosive decay
        { 65, 70, 5.5f, 45, 180, 25, 22, 20, 50,  30, 40, 10, 75,  60, 110,  25,  35, 0, 0, 0, 0, 0, 100 },
    };
    
    const auto& p = presets[index];
    auto set = [this](const juce::String& id, float v) {
        auto* param = apvts.getParameter(id);
        if (param)
        {
            param->beginChangeGesture();
            try
            {
                param->setValueNotifyingHost(param->convertTo0to1(v));
            }
            catch (...)
            {
                param->endChangeGesture();
                throw;
            }
            param->endChangeGesture();
        }
        };
    set("fatness", p.fat); set("chorus_depth", p.cD); set("chorus_rate", p.cR);
    set("chorus_mix", p.cM); set("delay_time", p.dT); set("delay_feedback", p.dFb);
    set("delay_mix", p.dM); set("delay_damping", p.dDmp); set("delay_mod", p.dMod);
    set("reverb_size", p.rS); set("reverb_damping", p.rDmp); set("reverb_mix", p.rM); set("reverb_mod", p.rMod);
    set("master_drive", p.mDrv); set("master_width", p.mWid); set("master_mid_drive", p.mMid); set("master_side_drive", p.mSide);
    set("distortion_bypass", p.distByp);
    set("chorus_bypass", p.chorusByp);
    set("delay_bypass", p.delayByp);
    set("reverb_bypass", p.reverbByp);
    set("master_bypass", p.masterByp);
    set("output_trim", p.oTrim);

    // CV-028: the whole preset is in place now — close the batch and commit it
    // as one generation, so the next block adopts all 23 values together.
    batch.close();
    publishParameterGeneration();
}

void CorvusFXAudioProcessor::randomizePreset()
{
    // Iterate all parameters and set random values for instant creative exploration.
    // Skips the preset parameter (factory preset index stays unchanged).
    // Bypass buttons have ~15% chance of being active; continuous params get full-range random.
    juce::Random rng;
    undoManager.beginNewTransaction("Randomize");
    auto& params = getParameters();
    for (auto* param : params)
    {
        auto* ranged = dynamic_cast<juce::RangedAudioParameter*>(param);
        if (!ranged) continue;
        if (ranged->getParameterID() == "preset")
            continue;

        {
            const juce::ScopedLock lock(lockedParamsLock);
            if (lockedParams.count(ranged->getParameterID()) != 0)
                continue;
        }

        bool isBool = dynamic_cast<juce::AudioParameterBool*>(ranged) != nullptr;
        ranged->beginChangeGesture();
        try
        {
        if (isBool)
            ranged->setValueNotifyingHost(rng.nextFloat() < 0.15f ? 1.0f : 0.0f);
        else
            ranged->setValueNotifyingHost(rng.nextFloat());
        }
        catch (...)
        {
            ranged->endChangeGesture();
            throw;
        }
        ranged->endChangeGesture();
    }
}

void CorvusFXAudioProcessor::setParameterLocked(const juce::String& paramID, bool locked)
{
    const juce::ScopedLock lock(lockedParamsLock);
    if (locked)
        lockedParams.insert(paramID);
    else
        lockedParams.erase(paramID);
}

bool CorvusFXAudioProcessor::isParameterLocked(const juce::String& paramID) const
{
    const juce::ScopedLock lock(lockedParamsLock);
    return lockedParams.count(paramID) != 0;
}

juce::AudioProcessorValueTreeState::ParameterLayout CorvusFXAudioProcessor::createParameterLayout()
{
    std::vector<std::unique_ptr<juce::RangedAudioParameter>> params;

    // Helper lambda for percentage parameters with proper formatting
    auto pctParam = [](const juce::String& id, const juce::String& name, float def) {
        auto range = juce::NormalisableRange<float>(0, 100, 0.1f);
        return std::make_unique<juce::AudioParameterFloat>(
            id, name, range, def,
            juce::AudioParameterFloatAttributes()
                .withLabel("%")
                .withStringFromValueFunction([range](float value, int) { return juce::String(value, 1) + " %"; })
                .withValueFromStringFunction([range](const juce::String& text) { return text.replace("%", "").getFloatValue(); }));
    };

    // Helper for Hz parameters
    auto hzParam = [](const juce::String& id, const juce::String& name, float min, float max, float def) {
        auto range = juce::NormalisableRange<float>(min, max, 0.1f);
        return std::make_unique<juce::AudioParameterFloat>(
            id, name, range, def,
            juce::AudioParameterFloatAttributes()
                .withLabel("Hz")
                .withStringFromValueFunction([range](float value, int) { return juce::String(value, 1) + " Hz"; })
                .withValueFromStringFunction([range](const juce::String& text) { return text.replace("Hz", "").replace("hz", "").getFloatValue(); }));
    };

    // Helper for ms parameters
    auto msParam = [](const juce::String& id, const juce::String& name, float min, float max, float def) {
        auto range = juce::NormalisableRange<float>(min, max, 1.0f);
        return std::make_unique<juce::AudioParameterFloat>(
            id, name, range, def,
            juce::AudioParameterFloatAttributes()
                .withLabel("ms")
                .withStringFromValueFunction([range](float value, int) { return juce::String((int)value) + " ms"; })
                .withValueFromStringFunction([range](const juce::String& text) { return text.replace("ms", "").getFloatValue(); }));
    };

    params.push_back(pctParam("overall", "Overall", 100));
    // CV-056: the host-visible name is "Drive" - the name the editor row
    // prints and the README parameter table lists. The parameter ID stays
    // "fatness" byte-for-byte so saved sessions, factory presets, MIDI maps
    // and state round-trips keep their identity.
    params.push_back(pctParam("fatness", "Drive", 0));
    params.push_back(std::make_unique<juce::AudioParameterBool>("distortion_bypass", "Distortion Bypass", false));
    params.push_back(pctParam("chorus_depth", "Chorus Depth", 0));
    params.push_back(hzParam("chorus_rate", "Chorus Rate", 0.1f, 10, 2));
    params.push_back(pctParam("chorus_mix", "Chorus Mix", 50));
    params.push_back(std::make_unique<juce::AudioParameterBool>("chorus_bypass", "Chorus Bypass", false));
    params.push_back(msParam("delay_time", "Delay Time", 0, 2000, 250));
    params.push_back(pctParam("delay_feedback", "Delay Feedback", 30));
    params.push_back(pctParam("delay_mix", "Delay Mix", 0));
    params.push_back(pctParam("delay_damping", "Delay Damping", 40));
    params.push_back(pctParam("delay_mod", "Delay Mod", 30));
    params.push_back(std::make_unique<juce::AudioParameterBool>("delay_bypass", "Delay Bypass", false));
    params.push_back(pctParam("reverb_size", "Reverb Size", 50));
    params.push_back(pctParam("reverb_damping", "Reverb Damping", 50));
    params.push_back(pctParam("reverb_mix", "Reverb Mix", 0));
    params.push_back(pctParam("reverb_mod", "Reverb Mod", 30));
    params.push_back(std::make_unique<juce::AudioParameterBool>("reverb_bypass", "Reverb Bypass", false));
    params.push_back(pctParam("master_drive", "Master Drive", 0));
    // CV-036: master_width owns a 0..200% range so the stored preset widths
    // through 140% are not clamped to 100%. Every other percentage knob keeps
    // the shared pctParam helper's 0..100 range and formatting.
    params.push_back(std::make_unique<juce::AudioParameterFloat>(
        "master_width", "Master Width",
        juce::NormalisableRange<float>(0.0f, 200.0f, 0.1f), 100.0f,
        juce::AudioParameterFloatAttributes()
            .withLabel("%")
            .withStringFromValueFunction([](float value, int) { return juce::String(value, 1) + " %"; })
            .withValueFromStringFunction([](const juce::String& text) { return text.replace("%", "").getFloatValue(); })));
    params.push_back(pctParam("master_mid_drive", "Master Mid Drive", 0));
    params.push_back(pctParam("master_side_drive", "Master Side Drive", 0));
    params.push_back(std::make_unique<juce::AudioParameterBool>("master_bypass", "Master Bypass", false));
    params.push_back(pctParam("output_trim", "Output Trim", 100));
    // CV-041: "preset" is a recall trigger, not a mix parameter. Registering it
    // non-automatable keeps hosts from exposing/recording an automation lane
    // for it, so a plain automation write can no longer reach parameterChanged()
    // -> loadPreset() and stamp the whole parameter set mid-playback. ID, name,
    // range [0,42] and default 2 stay byte-for-byte so saved sessions and host
    // parameter identity survive; the value still round-trips through
    // get/setStateInformation, the editor's PresetComboAttachment and
    // setCurrentProgram().
    params.push_back(std::make_unique<juce::AudioParameterInt>(
        "preset", "Preset", 0, 42, 2,
        juce::AudioParameterIntAttributes().withAutomatable(false)));
    return { params.begin(), params.end() };
}

const juce::String CorvusFXAudioProcessor::getName() const
{
#ifndef JucePlugin_Name
#define JucePlugin_Name "CorvusFX"
#endif
    return JucePlugin_Name;
}
bool CorvusFXAudioProcessor::acceptsMidi() const { return true; }
bool CorvusFXAudioProcessor::producesMidi() const { return false; }
bool CorvusFXAudioProcessor::isMidiEffect() const { return false; }
double CorvusFXAudioProcessor::getTailLengthSeconds() const { return 8.0; }
int CorvusFXAudioProcessor::getNumPrograms() { return 36; }
int CorvusFXAudioProcessor::getCurrentProgram() {
    // Convert combo box item ID (0-35) to preset index (0-29) via reverse lookup.
    // DAW hosts expect program indices in [0, getNumPrograms()-1], not combo item IDs.
    int id = (int)(apvts.getRawParameterValue("preset")->load() + 0.5f);
    // Reverse of idToPreset: combo IDs 2-7->0-5, 9-14->6-11, 16-21->12-17, 23-28->18-23, 30-35->24-29, 37-42->30-35
    static const int presetFromId[43] = {
        -1, -1, 0, 1, 2, 3, 4, 5,   // IDs 0-7
        -1, 6, 7, 8, 9,10,11,       // IDs 8-14
        -1,12,13,14,15,16,17,        // IDs 15-21
        -1,18,19,20,21,22,23,        // IDs 22-28
        -1,24,25,26,27,28,29,        // IDs 29-35
        -1,30,31,32,33,34,35         // IDs 36-42 (36=separator, 37-42=DREAM presets 30-35)
    };
    if (id >= 0 && id < 43) {
        int idx = presetFromId[id];
        if (idx >= 0) return idx;
    }
    return 0;
}
void CorvusFXAudioProcessor::setCurrentProgram(int i) {
    // Convert preset index (0-35) to combo box item ID (2-42) for the ComboBoxAttachment.
    // The host calls setCurrentProgram(i) with i in [0, getNumPrograms()-1].
    static const int presetToId[36] = {
        2, 3, 4, 5, 6, 7,              // CLEAN [0-5]
        9,10,11,12,13,14,               // WARM [6-11]
       16,17,18,19,20,21,               // CREATIVE [12-17]
       23,24,25,26,27,28,               // EXTREME [18-23]
       30,31,32,33,34,35,               // SIGNATURE [24-29]
       37,38,39,40,41,42                // DREAM [30-35]
    };
    if (i >= 0 && i < 36) {
        auto* p = apvts.getParameter("preset");
        if (p) p->beginChangeGesture();
        try
        {
            if (p) p->setValueNotifyingHost(p->convertTo0to1((float)presetToId[i]));
        }
        catch (...)
        {
            if (p) p->endChangeGesture();
            throw;
        }
        if (p) p->endChangeGesture();
    }
}
const juce::String CorvusFXAudioProcessor::getProgramName(int i) {
    // Reordered to match combo box layout: CLEAN [0-5], WARM [6-11], CREATIVE [12-17], EXTREME [18-23], SIGNATURE [24-29], DREAM [30-35]
    static const juce::String n[36] = { "Clean Sparkle","Crystal Shimmer","Silk Thread","Subtle Glue","Glass Canon","Air Lift","Warm Glow","Vintage Vibe","Thick Sauce","Tight Punch","Cozy Hiss","Tube Glow","Dreamy Space","Cosmic Wide","Molten Core","Sunspot","Nebula Drift","Shimmerfall","Deep Echo","Aggressive Drive","Lush Pad","Event Horizon","Iron Press","Obliterator","Velvet Morning","Neon Dusk","Basement Sessions","Cathedral Drift","Circuit Bent","Midnight Oil","Cloud Chamber","Frozen Lake","Ash & Ember","Stargate Portal","Underwater Cathedral","Solar Flare" };
    return (i >= 0 && i < 36) ? n[i] : juce::String();
}
void CorvusFXAudioProcessor::changeProgramName(int, const juce::String&) {}


// MIDI Learn: map management
bool CorvusFXAudioProcessor::hasMidiMapping(const juce::String& paramID) const
{
    // CV-027: the authoritative map is message-thread only — the audio thread
    // reads the published CC→slot table instead — but the lock keeps this
    // reader safe against every message-thread mutation (fold/clear/restore).
    juce::CriticalSection& mapLock =
        const_cast<juce::CriticalSection&>(midiMapLock);
    const juce::ScopedLock lock(mapLock);
    for (const auto& [cc, pid] : midiMap)
        if (pid == paramID) return true;
    return false;
}

void CorvusFXAudioProcessor::clearMidiMapping(const juce::String& paramID)
{
    {
        const juce::ScopedLock lock(midiMapLock);
        for (auto it = midiMap.begin(); it != midiMap.end(); )
        {
            if (it->second == paramID)
                it = midiMap.erase(it);
            else
                ++it;
        }
    }
    // CV-027: republish so the audio-thread view drops the mapping without the
    // callback ever taking midiMapLock.
    publishMidiMap();
}

void CorvusFXAudioProcessor::clearAllMidiMappings()
{
    {
        const juce::ScopedLock lock(midiMapLock);
        midiMap.clear();
    }
    // A learn captured before the clear must not resurrect a mapping from the
    // message-thread fold.
    pendingLearnCc.store(-1, std::memory_order_relaxed);
    pendingLearnSlot.store(-1, std::memory_order_relaxed);
    publishMidiMap();
}

// ── CV-029: audio-thread → message-thread host-notification mailbox ──
void CorvusFXAudioProcessor::stageMidiHostNotify(juce::RangedAudioParameter* param,
                                                 float normValue)
{
    // Audio thread (processBlock). Pointer match against the constructor-built
    // roster only: no lock, no allocation, no juce::String work, no host call.
    // The value store happens-before the release store of `pending`, and the
    // drain's acquire exchange peers with it, so the message thread always
    // observes a value written before the flag it consumed.
    if (param == nullptr)
        return;
    for (int i = 0; i < numMidiHostNotifySlots; ++i)
    {
        auto& slot = midiHostNotifySlots[(size_t) i];
        if (slot.param != param)
            continue;
        // Newest request wins: an older pending value is simply overwritten.
        slot.value.store(normValue, std::memory_order_relaxed);
        slot.pending.store(true, std::memory_order_release);
        return;
    }
}

// ── CV-027: message-thread MIDI-map publication + learn fold ──
int CorvusFXAudioProcessor::findMidiMapParamSlot(const juce::String& paramID) const
{
    // Message thread only. Returns the fixed roster slot for `paramID`, or -1
    // when the id is unknown or not learnable ("preset" is absent from the
    // roster by construction). The audio thread never calls this.
    for (int i = 0; i < numMidiHostNotifySlots; ++i)
        if (midiHostNotifySlots[(size_t) i].id == paramID)
            return i;
    return -1;
}

void CorvusFXAudioProcessor::publishMidiMap()
{
    // Message thread only. Seqlock-style publication: mark the table unstable
    // (odd sequence), flatten midiMap into one roster-slot index per legal CC,
    // then mark it stable. The audio thread never waits here: a callback block
    // that overlaps this write keeps its previous coherent view.
    midiMapSequence.fetch_add(1, std::memory_order_acq_rel);
    {
        const juce::ScopedLock lock(midiMapLock);
        for (int cc = 0; cc < MAX_MIDI_CCS; ++cc)
        {
            int slot = -1;
            const auto it = midiMap.find(cc);
            if (it != midiMap.end())
                slot = findMidiMapParamSlot(it->second);
            publishedMidiCcSlots[(size_t) cc].store(slot,
                                                    std::memory_order_relaxed);
        }
    }
    midiMapSequence.fetch_add(1, std::memory_order_release);
}

void CorvusFXAudioProcessor::foldPendingMidiLearn()
{
    // Message thread only. The audio thread recorded the captured CC and the
    // armed roster slot in plain atomics, so this is where the map node and the
    // juce::String assignment happen — never in the callback.
    const int slot = pendingLearnSlot.exchange(-1, std::memory_order_acq_rel);
    if (slot < 0 || slot >= numMidiHostNotifySlots)
    {
        pendingLearnCc.store(-1, std::memory_order_relaxed);
        return;
    }
    const int cc = pendingLearnCc.exchange(-1, std::memory_order_relaxed);
    if (cc < 0 || cc >= MAX_MIDI_CCS)
        return;

    bool changed = false;
    {
        const juce::ScopedLock lock(midiMapLock);
        const juce::String& paramID = midiHostNotifySlots[(size_t) slot].id;
        // CV-029: "preset" can never be a roster id, but the refusal stays
        // explicit so a future roster change cannot restore a preset fan-out.
        if (paramID.isEmpty() || paramID == "preset")
            return;
        const auto existing = midiMap.find(cc);
        // Refuse to steal: the audio thread already checked its published
        // view, this re-check protects against a concurrent message-thread
        // change between capture and fold.
        if (existing != midiMap.end() && existing->second != paramID)
            return;
        if (existing == midiMap.end())
        {
            midiMap[cc] = paramID;
            changed = true;
        }
    }
    if (changed)
        publishMidiMap();
}

void CorvusFXAudioProcessor::refreshMidiMapView() noexcept
{
    // Audio thread. Try-read of the published CC→slot table: copy into the
    // preallocated scratch array, then verify the sequence did not move. Only a
    // coherent read is adopted; an in-flight publication leaves the previous
    // view untouched so the callback always has a last good map.
    const unsigned sequence = midiMapSequence.load(std::memory_order_acquire);
    if (sequence == midiMapViewSequence || (sequence & 1u) != 0u)
        return;
    for (int cc = 0; cc < MAX_MIDI_CCS; ++cc)
        midiMapScratch[(size_t) cc] =
            publishedMidiCcSlots[(size_t) cc].load(std::memory_order_relaxed);
    if (midiMapSequence.load(std::memory_order_acquire) != sequence)
        return;
    midiMapView = midiMapScratch;
    midiMapViewSequence = sequence;
}

void CorvusFXAudioProcessor::timerCallback()
{
    drainPendingMidiHostNotifications();
}

int CorvusFXAudioProcessor::drainPendingMidiHostNotifications()
{
    // Message thread only (processor timer). This is the single place a MIDI CC
    // reachable from processBlock notifies the host, so the render callback
    // never calls setValueNotifyingHost, a gesture or an undo transaction.
    // Each parameter is drained at most once per tick: the exchange consumes
    // the newest staged value and nothing re-notifies until the audio thread
    // stages again.
    //
    // CV-027: also folds a learn captured by the audio thread, so the map edit
    // and its republication stay on the message thread.
    foldPendingMidiLearn();
    int notified = 0;
    for (int i = 0; i < numMidiHostNotifySlots; ++i)
    {
        auto& slot = midiHostNotifySlots[(size_t) i];
        if (! slot.pending.exchange(false, std::memory_order_acquire))
            continue;
        if (slot.param == nullptr)
            continue;
        slot.param->beginChangeGesture();
        try
        {
            slot.param->setValueNotifyingHost(slot.value.load(std::memory_order_relaxed));
        }
        catch (...)
        {
            slot.param->endChangeGesture();
            throw;
        }
        slot.param->endChangeGesture();
        ++notified;
    }
    return notified;
}

// Preset A/B Compare
// Snapshot/restore all 23 non-preset parameters from normalized 0-1 values.
static constexpr const char* abParamIds[24] = {
    "overall","fatness","chorus_depth","chorus_rate","chorus_mix",
    "delay_time","delay_feedback","delay_mix","delay_damping","delay_mod",
    "reverb_size","reverb_damping","reverb_mix","reverb_mod",
    "master_drive","master_width","master_mid_drive","master_side_drive",
    "distortion_bypass","chorus_bypass","delay_bypass","reverb_bypass","master_bypass",
    "output_trim"
};

void CorvusFXAudioProcessor::saveSlotA()
{
    undoManager.beginNewTransaction("A/B Compare");
    for (int i = 0; i < NUM_AB_PARAMS; ++i)
    {
        auto* p = apvts.getParameter(abParamIds[i]);
        if (p) snapshotA[i] = p->getValue();
    }
    abSlotIsA = true;
}

void CorvusFXAudioProcessor::saveSlotB()
{
    undoManager.beginNewTransaction("A/B Compare");
    for (int i = 0; i < NUM_AB_PARAMS; ++i)
    {
        auto* p = apvts.getParameter(abParamIds[i]);
        if (p) snapshotB[i] = p->getValue();
    }
    abSlotIsA = false;
}

void CorvusFXAudioProcessor::loadSlotA()
{
    undoManager.beginNewTransaction("A/B Compare");
    // CV-028: an A/B recall rewrites all 24 snapshot parameters; bracket it as
    // one batch so no block can render half of slot A and half of slot B.
    ParameterGenerationBatch batch(presetBatchSequence);
    for (int i = 0; i < NUM_AB_PARAMS; ++i)
    {
        auto* p = apvts.getParameter(abParamIds[i]);
        if (p) p->beginChangeGesture();
        try
        {
            if (p) p->setValueNotifyingHost(snapshotA[i]);
        }
        catch (...)
        {
            if (p) p->endChangeGesture();
            throw;
        }
        if (p) p->endChangeGesture();
    }
    batch.close();
    publishParameterGeneration();
    // A/B preset choice INTENTIONALLY STALE: loadSlotA restores the 24
    // knob-level snapshot values only. Writing the "preset" id too would
    // fire parameterChanged -> loadPreset, whose set() writes stomp every
    // non-preset parameter (the post-preset tweaks this snapshot captured)
    // back to the factory recipe, so the snapshot the user just restored is
    // destroyed before it is audible. A/B compare is a knob-level restore,
    // not a program change; the preset ComboBox may honestly follow the
    // last-touched preset instead.
    abSlotIsA = true;
}

void CorvusFXAudioProcessor::loadSlotB()
{
    undoManager.beginNewTransaction("A/B Compare");
    // CV-028: see loadSlotA — one batch, one published generation.
    ParameterGenerationBatch batch(presetBatchSequence);
    for (int i = 0; i < NUM_AB_PARAMS; ++i)
    {
        auto* p = apvts.getParameter(abParamIds[i]);
        if (p) p->beginChangeGesture();
        try
        {
            if (p) p->setValueNotifyingHost(snapshotB[i]);
        }
        catch (...)
        {
            if (p) p->endChangeGesture();
            throw;
        }
        if (p) p->endChangeGesture();
    }
    batch.close();
    publishParameterGeneration();
    // A/B preset choice INTENTIONALLY STALE: loadSlotB restores the 24
    // knob-level snapshot values only. Writing the "preset" id too would
    // fire parameterChanged -> loadPreset, whose set() writes stomp every
    // non-preset parameter (the post-preset tweaks this snapshot captured)
    // back to the factory recipe, so the snapshot the user just restored is
    // destroyed. A/B compare is a knob-level restore, not a program change;
    // the preset ComboBox may honestly follow the last-touched preset
    // instead.
    abSlotIsA = false;
}

namespace
{
// CV-023: a NaN, an infinity, or an overflowed parameter mapping must never
// become a smoothing target. `mapped` is the raw read carried through its
// target units; a non-finite mapping falls back to the caller's declared
// default, and a doubly-invalid pair lands on 0 rather than poisoning the
// smoother (for delay_feedback that smoother also feeds the feedback curve).
inline float finiteSmoothingTarget(float mapped, float fallback)
{
    if (std::isfinite(mapped))   return mapped;
    if (std::isfinite(fallback)) return fallback;
    return 0.0f;
}

// CV-038: one NaN or infinity in the host input must not latch the input meter
// or survive in the dry path. Folded once before the per-sample loop captures
// its dry tap; finite samples are left untouched.
inline void foldNonFiniteSamples(float* samples, int numSamples) noexcept
{
    for (int i = 0; i < numSamples; ++i)
        if (!std::isfinite(samples[i]))
            samples[i] = 0.0f;
}

// Declared default of an APVTS parameter in the parameter's own units (0..100
// for the percentage knobs, 0..200 for master_width, Hz / ms for the native
// ones). Read-only: no APVTS write, no lock, no allocation.
inline float declaredTarget(juce::AudioProcessorValueTreeState& state, const char* paramId)
{
    auto* param = state.getParameter(paramId);
    return param != nullptr ? param->convertFrom0to1(param->getDefaultValue()) : 0.0f;
}

// Declared default of a percentage knob, in smoothing-target units (0..1).
inline float declaredPercentTarget(juce::AudioProcessorValueTreeState& state, const char* paramId)
{
    return declaredTarget(state, paramId) / 100.0f;
}

// Delay-feedback target curve. The coefficients are the same numbers as the
// inline feedback curve at both call sites, applied here to the declared
// default so a re-prepare fallback lands on the same curve as a live read.
inline float feedbackTarget(float linearAmount)
{
    return linearAmount * linearAmount * 0.65f + linearAmount * 0.27f;
}

// CV-028: the single restore path for a generated target. The live block header
// writes its 19 smoother targets and 5 bypass-gain targets inline (those lines
// are pinned by check_cv023_parameter_targets.py / check_bypass_gain_glue.py),
// so a restore goes through this one guarded seed instead of a second copy of
// the pinned lines. Every restored value passes the same CV-023 guard the live
// path uses, so a corrupt generation can never seed a non-finite target.
inline void seedRestoredTarget(juce::LinearSmoothedValue<float>& smoother,
                               float mapped, float fallback) noexcept
{
    smoother.setTargetValue(finiteSmoothingTarget(mapped, fallback));
}
}


// ── CV-028 / CV-048: one coherent parameter generation ──
void CorvusFXAudioProcessor::publishParameterGeneration() noexcept
{
    // Never wait: a publisher that loses the writer flag leaves the previously
    // committed generation in place and the next audio block tries again.
    if (generationWriter.test_and_set(std::memory_order_acquire))
        return;

    const auto batchBefore = presetBatchSequence.load(std::memory_order_seq_cst);
    if ((batchBefore & 1u) != 0)
    {
        // A recall is mid-batch, so the live parameters are a mix of two
        // presets. Commit nothing; the batch's own publish (or the next block)
        // captures the completed set.
        generationWriter.clear(std::memory_order_release);
        return;
    }

    ParameterGeneration candidate;
    candidate.overall = apvts.getRawParameterValue("overall")->load();
    candidate.fatness = apvts.getRawParameterValue("fatness")->load();
    candidate.chorusDepth = apvts.getRawParameterValue("chorus_depth")->load();
    candidate.chorusRate = apvts.getRawParameterValue("chorus_rate")->load();
    candidate.chorusMix = apvts.getRawParameterValue("chorus_mix")->load();
    candidate.delayTime = apvts.getRawParameterValue("delay_time")->load();
    candidate.delayFeedback = apvts.getRawParameterValue("delay_feedback")->load();
    candidate.delayMix = apvts.getRawParameterValue("delay_mix")->load();
    candidate.delayDamping = apvts.getRawParameterValue("delay_damping")->load();
    candidate.delayMod = apvts.getRawParameterValue("delay_mod")->load();
    candidate.reverbSize = apvts.getRawParameterValue("reverb_size")->load();
    candidate.reverbDamping = apvts.getRawParameterValue("reverb_damping")->load();
    candidate.reverbMix = apvts.getRawParameterValue("reverb_mix")->load();
    candidate.reverbMod = apvts.getRawParameterValue("reverb_mod")->load();
    candidate.masterDrive = apvts.getRawParameterValue("master_drive")->load();
    candidate.masterWidth = apvts.getRawParameterValue("master_width")->load();
    candidate.masterMidDrive = apvts.getRawParameterValue("master_mid_drive")->load();
    candidate.masterSideDrive = apvts.getRawParameterValue("master_side_drive")->load();
    candidate.distortionBypass = apvts.getRawParameterValue("distortion_bypass")->load() > 0.5f;
    candidate.chorusBypass = apvts.getRawParameterValue("chorus_bypass")->load() > 0.5f;
    candidate.delayBypass = apvts.getRawParameterValue("delay_bypass")->load() > 0.5f;
    candidate.reverbBypass = apvts.getRawParameterValue("reverb_bypass")->load() > 0.5f;
    candidate.masterBypass = apvts.getRawParameterValue("master_bypass")->load() > 0.5f;
    candidate.outputTrim = apvts.getRawParameterValue("output_trim")->load();

    // A batch can start and finish entirely inside the capture above, so the
    // odd/even test at the top is not enough: commit only when the even epoch
    // the capture straddles is the same on both sides.
    const auto batchAfter = presetBatchSequence.load(std::memory_order_seq_cst);
    if (batchBefore != batchAfter || (batchAfter & 1u) != 0)
    {
        generationWriter.clear(std::memory_order_release);
        return;
    }

    // Sequentially consistent payload and markers: a reader that observes any
    // payload field from this commit can never accept the previous even
    // sequence on both sides of it, so it sees this generation whole or not at
    // all.
    generationSequence.fetch_add(1, std::memory_order_seq_cst); // odd: write in progress
    generationOverall.store(candidate.overall, std::memory_order_seq_cst);
    generationFatness.store(candidate.fatness, std::memory_order_seq_cst);
    generationChorusDepth.store(candidate.chorusDepth, std::memory_order_seq_cst);
    generationChorusRate.store(candidate.chorusRate, std::memory_order_seq_cst);
    generationChorusMix.store(candidate.chorusMix, std::memory_order_seq_cst);
    generationDelayTime.store(candidate.delayTime, std::memory_order_seq_cst);
    generationDelayFeedback.store(candidate.delayFeedback, std::memory_order_seq_cst);
    generationDelayMix.store(candidate.delayMix, std::memory_order_seq_cst);
    generationDelayDamping.store(candidate.delayDamping, std::memory_order_seq_cst);
    generationDelayMod.store(candidate.delayMod, std::memory_order_seq_cst);
    generationReverbSize.store(candidate.reverbSize, std::memory_order_seq_cst);
    generationReverbDamping.store(candidate.reverbDamping, std::memory_order_seq_cst);
    generationReverbMix.store(candidate.reverbMix, std::memory_order_seq_cst);
    generationReverbMod.store(candidate.reverbMod, std::memory_order_seq_cst);
    generationMasterDrive.store(candidate.masterDrive, std::memory_order_seq_cst);
    generationMasterWidth.store(candidate.masterWidth, std::memory_order_seq_cst);
    generationMasterMidDrive.store(candidate.masterMidDrive, std::memory_order_seq_cst);
    generationMasterSideDrive.store(candidate.masterSideDrive, std::memory_order_seq_cst);
    generationOutputTrim.store(candidate.outputTrim, std::memory_order_seq_cst);
    generationDistortionBypass.store(candidate.distortionBypass, std::memory_order_seq_cst);
    generationChorusBypass.store(candidate.chorusBypass, std::memory_order_seq_cst);
    generationDelayBypass.store(candidate.delayBypass, std::memory_order_seq_cst);
    generationReverbBypass.store(candidate.reverbBypass, std::memory_order_seq_cst);
    generationMasterBypass.store(candidate.masterBypass, std::memory_order_seq_cst);
    generationSequence.fetch_add(1, std::memory_order_seq_cst); // even: committed

    generationWriter.clear(std::memory_order_release);
}

CorvusFXAudioProcessor::ParameterGeneration
CorvusFXAudioProcessor::readParameterGeneration(ParameterGeneration lastGood) const noexcept
{
    // Bounded seqlock read. The payload fields are individually atomic, so an
    // overlapped write can only hand back a stale mix, never an undefined
    // value; the sequence markers reject that mix, and a busy publisher keeps
    // the caller's last good generation.
    for (int attempt = 0; attempt < 3; ++attempt)
    {
        const auto before = generationSequence.load(std::memory_order_seq_cst);
        if ((before & 1u) != 0)
            continue;

        ParameterGeneration candidate;
        candidate.overall = generationOverall.load(std::memory_order_seq_cst);
        candidate.fatness = generationFatness.load(std::memory_order_seq_cst);
        candidate.chorusDepth = generationChorusDepth.load(std::memory_order_seq_cst);
        candidate.chorusRate = generationChorusRate.load(std::memory_order_seq_cst);
        candidate.chorusMix = generationChorusMix.load(std::memory_order_seq_cst);
        candidate.delayTime = generationDelayTime.load(std::memory_order_seq_cst);
        candidate.delayFeedback = generationDelayFeedback.load(std::memory_order_seq_cst);
        candidate.delayMix = generationDelayMix.load(std::memory_order_seq_cst);
        candidate.delayDamping = generationDelayDamping.load(std::memory_order_seq_cst);
        candidate.delayMod = generationDelayMod.load(std::memory_order_seq_cst);
        candidate.reverbSize = generationReverbSize.load(std::memory_order_seq_cst);
        candidate.reverbDamping = generationReverbDamping.load(std::memory_order_seq_cst);
        candidate.reverbMix = generationReverbMix.load(std::memory_order_seq_cst);
        candidate.reverbMod = generationReverbMod.load(std::memory_order_seq_cst);
        candidate.masterDrive = generationMasterDrive.load(std::memory_order_seq_cst);
        candidate.masterWidth = generationMasterWidth.load(std::memory_order_seq_cst);
        candidate.masterMidDrive = generationMasterMidDrive.load(std::memory_order_seq_cst);
        candidate.masterSideDrive = generationMasterSideDrive.load(std::memory_order_seq_cst);
        candidate.outputTrim = generationOutputTrim.load(std::memory_order_seq_cst);
        candidate.distortionBypass = generationDistortionBypass.load(std::memory_order_seq_cst);
        candidate.chorusBypass = generationChorusBypass.load(std::memory_order_seq_cst);
        candidate.delayBypass = generationDelayBypass.load(std::memory_order_seq_cst);
        candidate.reverbBypass = generationReverbBypass.load(std::memory_order_seq_cst);
        candidate.masterBypass = generationMasterBypass.load(std::memory_order_seq_cst);

        const auto after = generationSequence.load(std::memory_order_seq_cst);
        if (before == after && (after & 1u) == 0)
            return candidate;
    }
    return lastGood;
}

void CorvusFXAudioProcessor::applyParameterGeneration(const ParameterGeneration& generation) noexcept
{
    // Re-seeds every block-header target from one coherent generation. The
    // mapping mirrors the render refresh in processBlock (percent knobs through
    // /100, delay feedback through the quadratic curve, bypasses through the
    // 0.5 gate) and a non-finite mapping falls back to the declared default
    // exactly as the CV-023 guards do, so a restore never seeds a smoother with
    // a value the live path would have rejected.
    seedRestoredTarget(smoothOverall, generation.overall / 100.0f, declaredPercentTarget(apvts, "overall"));
    seedRestoredTarget(smoothFatness, generation.fatness / 100.0f, declaredPercentTarget(apvts, "fatness"));
    seedRestoredTarget(smoothChorusDepth, generation.chorusDepth / 100.0f, declaredPercentTarget(apvts, "chorus_depth"));
    seedRestoredTarget(smoothChorusRate, generation.chorusRate, declaredTarget(apvts, "chorus_rate"));
    seedRestoredTarget(smoothChorusMix, generation.chorusMix / 100.0f, declaredPercentTarget(apvts, "chorus_mix"));
    seedRestoredTarget(smoothDelayTime, generation.delayTime, declaredTarget(apvts, "delay_time"));
    {
        const float fbRaw = generation.delayFeedback / 100.0f;
        seedRestoredTarget(smoothDelayFeedback,
            feedbackTarget(fbRaw),
            feedbackTarget(declaredPercentTarget(apvts, "delay_feedback")));
    }
    seedRestoredTarget(smoothDelayMix, generation.delayMix / 100.0f, declaredPercentTarget(apvts, "delay_mix"));
    seedRestoredTarget(smoothDelayDamping, generation.delayDamping / 100.0f, declaredPercentTarget(apvts, "delay_damping"));
    seedRestoredTarget(smoothDelayMod, generation.delayMod / 100.0f, declaredPercentTarget(apvts, "delay_mod"));
    seedRestoredTarget(smoothReverbSize, generation.reverbSize / 100.0f, declaredPercentTarget(apvts, "reverb_size"));
    seedRestoredTarget(smoothReverbDamping, generation.reverbDamping / 100.0f, declaredPercentTarget(apvts, "reverb_damping"));
    seedRestoredTarget(smoothReverbMix, generation.reverbMix / 100.0f, declaredPercentTarget(apvts, "reverb_mix"));
    seedRestoredTarget(smoothReverbMod, generation.reverbMod / 100.0f, declaredPercentTarget(apvts, "reverb_mod"));
    seedRestoredTarget(smoothMasterDrive, generation.masterDrive / 100.0f, declaredPercentTarget(apvts, "master_drive"));
    seedRestoredTarget(smoothMasterWidth, generation.masterWidth / 100.0f, declaredPercentTarget(apvts, "master_width"));
    seedRestoredTarget(smoothMasterMidDrive, generation.masterMidDrive / 100.0f, declaredPercentTarget(apvts, "master_mid_drive"));
    seedRestoredTarget(smoothMasterSideDrive, generation.masterSideDrive / 100.0f, declaredPercentTarget(apvts, "master_side_drive"));
    seedRestoredTarget(smoothOutputTrim, generation.outputTrim / 100.0f, declaredPercentTarget(apvts, "output_trim"));
    // Inverted literal, same as the live header: bypassed -> 0.0f, active ->
    // 1.0f. The bool is finite, so the fallback is unreachable.
    seedRestoredTarget(bypassGainDist, generation.distortionBypass ? 0.0f : 1.0f, 1.0f);
    seedRestoredTarget(bypassGainChorus, generation.chorusBypass ? 0.0f : 1.0f, 1.0f);
    seedRestoredTarget(bypassGainDelay, generation.delayBypass ? 0.0f : 1.0f, 1.0f);
    seedRestoredTarget(bypassGainReverb, generation.reverbBypass ? 0.0f : 1.0f, 1.0f);
    seedRestoredTarget(bypassGainMaster, generation.masterBypass ? 0.0f : 1.0f, 1.0f);
}


void CorvusFXAudioProcessor::prepareToPlay(double sampleRate, int samplesPerBlock)
{
    lastSampleRate = sampleRate;
    chorus.prepare(sampleRate);
    delay.prepare(sampleRate);
    distortion.prepare(sampleRate);
    upgradedReverb.prepare(sampleRate);
    masterOutput.prepare(sampleRate);
    // Kept as a prepared resource only: processBlock's dry feed is a scalar
    // per-sample capture, so a host block larger than this hint never resizes
    // it (and never allocates) on the audio thread.
    dryBuffer.setSize(2, samplesPerBlock, false, true, true);

    // CV-027: the MIDI-map view, scratch table and published CC→slot table are
    // fixed-size std::array members initialised in the constructor, so there is
    // no capacity to re-assert here and no audio-thread allocation to guard.

    // ── Parameter smoothing initialization ──
    // 20ms smoothing time: responsive feel, no zipper noise.
    // reset() only sets the ramp length and zeroes the current value; the
    // current value is seeded from the live parameter state further down so
    // smoothing never starts from zero.
    const double smoothTime = 0.02; // 20ms
    smoothOverall.reset(sampleRate, smoothTime);
    smoothFatness.reset(sampleRate, smoothTime);
    smoothChorusDepth.reset(sampleRate, smoothTime);
    smoothChorusRate.reset(sampleRate, smoothTime);
    smoothChorusMix.reset(sampleRate, smoothTime);
    smoothDelayTime.reset(sampleRate, smoothTime);
    smoothDelayFeedback.reset(sampleRate, smoothTime);
    smoothDelayMix.reset(sampleRate, smoothTime);
    smoothDelayDamping.reset(sampleRate, smoothTime);
    smoothDelayMod.reset(sampleRate, smoothTime);
    smoothReverbSize.reset(sampleRate, smoothTime);
    smoothReverbDamping.reset(sampleRate, smoothTime);
    smoothReverbMix.reset(sampleRate, smoothTime);
    smoothReverbMod.reset(sampleRate, smoothTime);
    smoothMasterDrive.reset(sampleRate, smoothTime);
    smoothMasterWidth.reset(sampleRate, smoothTime);
    smoothMasterMidDrive.reset(sampleRate, smoothTime);
    smoothMasterSideDrive.reset(sampleRate, smoothTime);
    smoothOutputTrim.reset(sampleRate, smoothTime);

    // Seed BOTH current and target values from the current parameter state.
    // CV-023: `reset(sampleRate, smoothTime)` alone zeroes the smoother's
    // current value, so a plain setTargetValue() makes the first getNextValue()
    // after prepare ramp from 0 for the whole 20ms smoothing time — audible as
    // a sweep on output gain and delay time at every host block-size change and
    // at the start of an offline render. setCurrentAndTargetValue() starts the
    // ramp already at the value it would otherwise travel toward.
    // Each fallback is the parameter's declared default carried through the
    // same units and mapping as the target — never the previous target and
    // never a blanket zero. Every target is then routed through
    // finiteSmoothingTarget, so a NaN, an infinity, or an overflowed mapping
    // cannot seed a smoother (or the delay-feedback curve) at re-prepare time.
    const float fallbackOverall = declaredPercentTarget(apvts, "overall");
    const float fallbackFatness = declaredPercentTarget(apvts, "fatness");
    const float fallbackChorusDepth = declaredPercentTarget(apvts, "chorus_depth");
    const float fallbackChorusRate = declaredTarget(apvts, "chorus_rate");
    const float fallbackChorusMix = declaredPercentTarget(apvts, "chorus_mix");
    const float fallbackDelayTime = declaredTarget(apvts, "delay_time");
    const float fallbackDelayFeedback = feedbackTarget(declaredPercentTarget(apvts, "delay_feedback"));
    const float fallbackDelayMix = declaredPercentTarget(apvts, "delay_mix");
    const float fallbackDelayDamping = declaredPercentTarget(apvts, "delay_damping");
    const float fallbackDelayMod = declaredPercentTarget(apvts, "delay_mod");
    const float fallbackReverbSize = declaredPercentTarget(apvts, "reverb_size");
    const float fallbackReverbDamping = declaredPercentTarget(apvts, "reverb_damping");
    const float fallbackReverbMix = declaredPercentTarget(apvts, "reverb_mix");
    const float fallbackReverbMod = declaredPercentTarget(apvts, "reverb_mod");
    const float fallbackMasterDrive = declaredPercentTarget(apvts, "master_drive");
    const float fallbackMasterWidth = declaredPercentTarget(apvts, "master_width");
    const float fallbackMasterMidDrive = declaredPercentTarget(apvts, "master_mid_drive");
    const float fallbackMasterSideDrive = declaredPercentTarget(apvts, "master_side_drive");
    const float fallbackOutputTrim = declaredPercentTarget(apvts, "output_trim");

    smoothOverall.setCurrentAndTargetValue(finiteSmoothingTarget(apvts.getRawParameterValue("overall")->load() / 100.0f, fallbackOverall));
    smoothFatness.setCurrentAndTargetValue(finiteSmoothingTarget(apvts.getRawParameterValue("fatness")->load() / 100.0f, fallbackFatness));
    smoothChorusDepth.setCurrentAndTargetValue(finiteSmoothingTarget(apvts.getRawParameterValue("chorus_depth")->load() / 100.0f, fallbackChorusDepth));
    smoothChorusRate.setCurrentAndTargetValue(finiteSmoothingTarget(apvts.getRawParameterValue("chorus_rate")->load(), fallbackChorusRate));
    smoothChorusMix.setCurrentAndTargetValue(finiteSmoothingTarget(apvts.getRawParameterValue("chorus_mix")->load() / 100.0f, fallbackChorusMix));
    smoothDelayTime.setCurrentAndTargetValue(finiteSmoothingTarget(apvts.getRawParameterValue("delay_time")->load(), fallbackDelayTime));
    {
        float fbRaw = apvts.getRawParameterValue("delay_feedback")->load() / 100.0f;
        smoothDelayFeedback.setCurrentAndTargetValue(finiteSmoothingTarget(fbRaw * fbRaw * 0.65f + fbRaw * 0.27f, fallbackDelayFeedback));
    }
    smoothDelayMix.setCurrentAndTargetValue(finiteSmoothingTarget(apvts.getRawParameterValue("delay_mix")->load() / 100.0f, fallbackDelayMix));
    smoothDelayDamping.setCurrentAndTargetValue(finiteSmoothingTarget(apvts.getRawParameterValue("delay_damping")->load() / 100.0f, fallbackDelayDamping));
    smoothDelayMod.setCurrentAndTargetValue(finiteSmoothingTarget(apvts.getRawParameterValue("delay_mod")->load() / 100.0f, fallbackDelayMod));
    smoothReverbSize.setCurrentAndTargetValue(finiteSmoothingTarget(apvts.getRawParameterValue("reverb_size")->load() / 100.0f, fallbackReverbSize));
    smoothReverbDamping.setCurrentAndTargetValue(finiteSmoothingTarget(apvts.getRawParameterValue("reverb_damping")->load() / 100.0f, fallbackReverbDamping));
    smoothReverbMix.setCurrentAndTargetValue(finiteSmoothingTarget(apvts.getRawParameterValue("reverb_mix")->load() / 100.0f, fallbackReverbMix));
    smoothReverbMod.setCurrentAndTargetValue(finiteSmoothingTarget(apvts.getRawParameterValue("reverb_mod")->load() / 100.0f, fallbackReverbMod));
    smoothMasterDrive.setCurrentAndTargetValue(finiteSmoothingTarget(apvts.getRawParameterValue("master_drive")->load() / 100.0f, fallbackMasterDrive));
    smoothMasterWidth.setCurrentAndTargetValue(finiteSmoothingTarget(apvts.getRawParameterValue("master_width")->load() / 100.0f, fallbackMasterWidth));
    smoothMasterMidDrive.setCurrentAndTargetValue(finiteSmoothingTarget(apvts.getRawParameterValue("master_mid_drive")->load() / 100.0f, fallbackMasterMidDrive));
    smoothMasterSideDrive.setCurrentAndTargetValue(finiteSmoothingTarget(apvts.getRawParameterValue("master_side_drive")->load() / 100.0f, fallbackMasterSideDrive));
    smoothOutputTrim.setCurrentAndTargetValue(finiteSmoothingTarget(apvts.getRawParameterValue("output_trim")->load() / 100.0f, fallbackOutputTrim));

    // Bypass crossfade gain init (click-free): 1.0 active, 0.0 dry pass-through.
    // Seeded with current == target for the same reason as the parameter
    // smoothers: after reset() the current value is 0, so a bare
    // setTargetValue() would fade an active module in from silence over the
    // 30ms ramp on every prepare.
    const float bDist  = apvts.getRawParameterValue("distortion_bypass")->load() > 0.5f ? 0.0f : 1.0f;
    const float bChor  = apvts.getRawParameterValue("chorus_bypass")->load() > 0.5f ? 0.0f : 1.0f;
    const float bDel   = apvts.getRawParameterValue("delay_bypass")->load() > 0.5f ? 0.0f : 1.0f;
    const float bRev   = apvts.getRawParameterValue("reverb_bypass")->load() > 0.5f ? 0.0f : 1.0f;
    const float bMast  = apvts.getRawParameterValue("master_bypass")->load() > 0.5f ? 0.0f : 1.0f;
    const double bypassTime = 0.03; // 30ms gentle dip, slower than param smoothing
    bypassGainDist.reset(sampleRate, bypassTime);   bypassGainDist.setCurrentAndTargetValue(bDist);
    bypassGainChorus.reset(sampleRate, bypassTime); bypassGainChorus.setCurrentAndTargetValue(bChor);
    bypassGainDelay.reset(sampleRate, bypassTime);  bypassGainDelay.setCurrentAndTargetValue(bDel);
    bypassGainReverb.reset(sampleRate, bypassTime); bypassGainReverb.setCurrentAndTargetValue(bRev);
    bypassGainMaster.reset(sampleRate, bypassTime); bypassGainMaster.setCurrentAndTargetValue(bMast);
}

void CorvusFXAudioProcessor::releaseResources() {}

#ifndef JucePlugin_PreferredChannelConfigurations
bool CorvusFXAudioProcessor::isBusesLayoutSupported(const BusesLayout& layouts) const
{
    if (layouts.getMainOutputChannelSet() != juce::AudioChannelSet::mono()
        && layouts.getMainOutputChannelSet() != juce::AudioChannelSet::stereo())
        return false;
#if ! JucePlugin_IsSynth
    if (layouts.getMainOutputChannelSet() != layouts.getMainInputChannelSet())
        return false;
#endif
    return true;
}
#endif

//==============================================================================
void CorvusFXAudioProcessor::processBlock(juce::AudioBuffer<float>& buffer, juce::MidiBuffer& midiMessages)
{
    juce::ScopedNoDenormals noDenormals;
    const int numChannels = buffer.getNumChannels();
    const int numSamples = buffer.getNumSamples();
    if (numChannels == 0 || numSamples == 0) return;
    const int chProc = std::min(numChannels, 2);

    for (int ch = chProc; ch < numChannels; ++ch)
        buffer.clear(ch, 0, numSamples);

    // ── Update smoothed parameter targets ──
    // Raw parameter reads happen once per block (atomic load, thread-safe).
    // LinearSmoothedValue then interpolates across samples within the block,
    // eliminating zipper noise from knob movement and host automation.
    //
    // ── CV-028 / CV-048: one coherent parameter generation ──
    // Commit the live set as one generation and adopt the newest committed one.
    // `lastGoodGeneration` is what this block falls back to if a preset, A/B or
    // session recall moves the batch epoch while the header below reads its
    // parameters: the header must never smooth a mix of the old and new values.
    // Publishing every block (not on a dirty notification) is what keeps every
    // knob and automation edit live here, and it costs one capture of the same
    // 24 raw reads the header performs anyway.
    publishParameterGeneration();
    lastGoodGeneration = readParameterGeneration(lastGoodGeneration);
    const auto generationBatchBefore = presetBatchSequence.load(std::memory_order_seq_cst);

    // CV-023: the render fallback is the smoother's current target when that is
    // finite, otherwise the same declared default the prepare path uses. The
    // ternary is lazy, so the declared-default lookup runs only on a bad read;
    // valid finite mappings pass through finiteSmoothingTarget unchanged.
    const float fallbackOverall = std::isfinite(smoothOverall.getTargetValue())
        ? smoothOverall.getTargetValue() : declaredPercentTarget(apvts, "overall");
    const float fallbackFatness = std::isfinite(smoothFatness.getTargetValue())
        ? smoothFatness.getTargetValue() : declaredPercentTarget(apvts, "fatness");
    const float fallbackChorusDepth = std::isfinite(smoothChorusDepth.getTargetValue())
        ? smoothChorusDepth.getTargetValue() : declaredPercentTarget(apvts, "chorus_depth");
    const float fallbackChorusRate = std::isfinite(smoothChorusRate.getTargetValue())
        ? smoothChorusRate.getTargetValue() : declaredTarget(apvts, "chorus_rate");
    const float fallbackChorusMix = std::isfinite(smoothChorusMix.getTargetValue())
        ? smoothChorusMix.getTargetValue() : declaredPercentTarget(apvts, "chorus_mix");
    const float fallbackDelayTime = std::isfinite(smoothDelayTime.getTargetValue())
        ? smoothDelayTime.getTargetValue() : declaredTarget(apvts, "delay_time");
    const float fallbackDelayFeedback = std::isfinite(smoothDelayFeedback.getTargetValue())
        ? smoothDelayFeedback.getTargetValue() : feedbackTarget(declaredPercentTarget(apvts, "delay_feedback"));
    const float fallbackDelayMix = std::isfinite(smoothDelayMix.getTargetValue())
        ? smoothDelayMix.getTargetValue() : declaredPercentTarget(apvts, "delay_mix");
    const float fallbackDelayDamping = std::isfinite(smoothDelayDamping.getTargetValue())
        ? smoothDelayDamping.getTargetValue() : declaredPercentTarget(apvts, "delay_damping");
    const float fallbackDelayMod = std::isfinite(smoothDelayMod.getTargetValue())
        ? smoothDelayMod.getTargetValue() : declaredPercentTarget(apvts, "delay_mod");
    const float fallbackReverbSize = std::isfinite(smoothReverbSize.getTargetValue())
        ? smoothReverbSize.getTargetValue() : declaredPercentTarget(apvts, "reverb_size");
    const float fallbackReverbDamping = std::isfinite(smoothReverbDamping.getTargetValue())
        ? smoothReverbDamping.getTargetValue() : declaredPercentTarget(apvts, "reverb_damping");
    const float fallbackReverbMix = std::isfinite(smoothReverbMix.getTargetValue())
        ? smoothReverbMix.getTargetValue() : declaredPercentTarget(apvts, "reverb_mix");
    const float fallbackReverbMod = std::isfinite(smoothReverbMod.getTargetValue())
        ? smoothReverbMod.getTargetValue() : declaredPercentTarget(apvts, "reverb_mod");
    const float fallbackMasterDrive = std::isfinite(smoothMasterDrive.getTargetValue())
        ? smoothMasterDrive.getTargetValue() : declaredPercentTarget(apvts, "master_drive");
    const float fallbackMasterWidth = std::isfinite(smoothMasterWidth.getTargetValue())
        ? smoothMasterWidth.getTargetValue() : declaredPercentTarget(apvts, "master_width");
    const float fallbackMasterMidDrive = std::isfinite(smoothMasterMidDrive.getTargetValue())
        ? smoothMasterMidDrive.getTargetValue() : declaredPercentTarget(apvts, "master_mid_drive");
    const float fallbackMasterSideDrive = std::isfinite(smoothMasterSideDrive.getTargetValue())
        ? smoothMasterSideDrive.getTargetValue() : declaredPercentTarget(apvts, "master_side_drive");
    const float fallbackOutputTrim = std::isfinite(smoothOutputTrim.getTargetValue())
        ? smoothOutputTrim.getTargetValue() : declaredPercentTarget(apvts, "output_trim");

    smoothOverall.setTargetValue(finiteSmoothingTarget(apvts.getRawParameterValue("overall")->load() / 100.0f, fallbackOverall));
    smoothFatness.setTargetValue(finiteSmoothingTarget(apvts.getRawParameterValue("fatness")->load() / 100.0f, fallbackFatness));
    smoothChorusDepth.setTargetValue(finiteSmoothingTarget(apvts.getRawParameterValue("chorus_depth")->load() / 100.0f, fallbackChorusDepth));
    smoothChorusRate.setTargetValue(finiteSmoothingTarget(apvts.getRawParameterValue("chorus_rate")->load(), fallbackChorusRate));
    smoothChorusMix.setTargetValue(finiteSmoothingTarget(apvts.getRawParameterValue("chorus_mix")->load() / 100.0f, fallbackChorusMix));
    smoothDelayTime.setTargetValue(finiteSmoothingTarget(apvts.getRawParameterValue("delay_time")->load(), fallbackDelayTime));
    {
        // Exponential mapping: linear knob → musical feedback response
        // Applied to the target value so the exponential curve is preserved through smoothing
        float fbRaw = apvts.getRawParameterValue("delay_feedback")->load() / 100.0f;
        smoothDelayFeedback.setTargetValue(finiteSmoothingTarget(fbRaw * fbRaw * 0.65f + fbRaw * 0.27f, fallbackDelayFeedback));
    }
    smoothDelayMix.setTargetValue(finiteSmoothingTarget(apvts.getRawParameterValue("delay_mix")->load() / 100.0f, fallbackDelayMix));
    smoothDelayDamping.setTargetValue(finiteSmoothingTarget(apvts.getRawParameterValue("delay_damping")->load() / 100.0f, fallbackDelayDamping));
    smoothDelayMod.setTargetValue(finiteSmoothingTarget(apvts.getRawParameterValue("delay_mod")->load() / 100.0f, fallbackDelayMod));
    smoothReverbSize.setTargetValue(finiteSmoothingTarget(apvts.getRawParameterValue("reverb_size")->load() / 100.0f, fallbackReverbSize));
    smoothReverbDamping.setTargetValue(finiteSmoothingTarget(apvts.getRawParameterValue("reverb_damping")->load() / 100.0f, fallbackReverbDamping));
    smoothReverbMix.setTargetValue(finiteSmoothingTarget(apvts.getRawParameterValue("reverb_mix")->load() / 100.0f, fallbackReverbMix));
    smoothReverbMod.setTargetValue(finiteSmoothingTarget(apvts.getRawParameterValue("reverb_mod")->load() / 100.0f, fallbackReverbMod));
    smoothMasterDrive.setTargetValue(finiteSmoothingTarget(apvts.getRawParameterValue("master_drive")->load() / 100.0f, fallbackMasterDrive));
    smoothMasterWidth.setTargetValue(finiteSmoothingTarget(apvts.getRawParameterValue("master_width")->load() / 100.0f, fallbackMasterWidth));
    smoothMasterMidDrive.setTargetValue(finiteSmoothingTarget(apvts.getRawParameterValue("master_mid_drive")->load() / 100.0f, fallbackMasterMidDrive));
    smoothMasterSideDrive.setTargetValue(finiteSmoothingTarget(apvts.getRawParameterValue("master_side_drive")->load() / 100.0f, fallbackMasterSideDrive));
    smoothOutputTrim.setTargetValue(finiteSmoothingTarget(apvts.getRawParameterValue("output_trim")->load() / 100.0f, fallbackOutputTrim));
    const bool distortionBypass = apvts.getRawParameterValue("distortion_bypass")->load() > 0.5f;
    const bool chorusBypass = apvts.getRawParameterValue("chorus_bypass")->load() > 0.5f;
    const bool delayBypass = apvts.getRawParameterValue("delay_bypass")->load() > 0.5f;
    const bool reverbBypass = apvts.getRawParameterValue("reverb_bypass")->load() > 0.5f;
    const bool masterBypass = apvts.getRawParameterValue("master_bypass")->load() > 0.5f;

    // Click-free bypass: ramp each module wet/dry over 30ms instead of hard switching
    bypassGainDist.setTargetValue(distortionBypass ? 0.0f : 1.0f);
    bypassGainChorus.setTargetValue(chorusBypass ? 0.0f : 1.0f);
    bypassGainDelay.setTargetValue(delayBypass ? 0.0f : 1.0f);
    bypassGainReverb.setTargetValue(reverbBypass ? 0.0f : 1.0f);
    bypassGainMaster.setTargetValue(masterBypass ? 0.0f : 1.0f);

    // CV-028: if a recall batch was open, started, or finished anywhere across
    // the parameter reads above, the targets just set are a hybrid of two
    // presets. Re-seed every one of them from the last coherent generation; the
    // per-sample loop below then ramps from what the previous block actually
    // rendered, never from a mix. A stable epoch means the targets above are
    // already one generation, so nothing is re-applied.
    const auto generationBatchAfter = presetBatchSequence.load(std::memory_order_seq_cst);
    if (generationBatchBefore != generationBatchAfter
        || (generationBatchAfter & 1u) != 0)
        applyParameterGeneration(lastGoodGeneration);

    // MIDI Learn: apply CC to parameter mappings from MIDI input
    // When midiLearnActive is true, the next CC message captures that CC
    // for the target parameter (triggered by right-click in the UI).
    if (!midiMessages.isEmpty())
    {
        // CV-027: adopt the newest published CC→parameter table. This is a
        // try-read, not a lock: if the message thread is mid-publication the
        // callback keeps its last good view and retries on the next block. All
        // buffers involved are fixed-size members, so nothing allocates here.
        refreshMidiMapView();

        // CV-027: learn capture never mutates the authoritative map on this
        // thread. It records the first unclaimed CC and the armed parameter
        // slot in preallocated atomics; foldPendingMidiLearn() applies them on
        // the message thread, so the first learn event cannot allocate a map
        // node inside the callback. The armed slot is always a roster slot and
        // the roster excludes "preset" (and startMidiLearn refuses it), so a
        // CC can never fan out into loadPreset(). Refuse to steal: a CC already
        // mapped to a DIFFERENT parameter is left alone and the learn stays
        // armed. The full buffer keeps getting scanned (no loop exit),
        // mirroring the skip-only-this-CC semantics.
        int capturedCc = -1;
        if (midiLearnActive)
        {
            const int armedSlot =
                midiLearnParamSlot.load(std::memory_order_relaxed);
            for (const auto& metadata : midiMessages)
            {
                auto msg = metadata.getMessage();
                if (msg.isController() && capturedCc == -1)
                {
                    const int cc = msg.getControllerNumber();
                    if (cc < 0 || cc >= MAX_MIDI_CCS)
                        continue;
                    if (armedSlot < 0
                        || (midiMapView[(size_t) cc] >= 0
                            && midiMapView[(size_t) cc] != armedSlot))
                        continue;
                    capturedCc = cc;
                    pendingLearnCc.store(cc, std::memory_order_relaxed);
                    // Release store publishes the CC recorded above; the fold
                    // consumes this slot with an acquire exchange.
                    pendingLearnSlot.store(armedSlot, std::memory_order_release);
                    midiLearnActive = false;
                }
            }
        }

        // Apply mappings from the published view. The captured CC skips its own
        // mapping step (skip-only-this-CC semantics).
        //
        // CV-029: the audio thread NEVER notifies the host. A mapped CC only
        // stages the newest normalised value (the raw cc/127, unchanged, so
        // the parameter's own rounding is exactly what it is today) in that
        // parameter's pending slot. drainPendingMidiHostNotifications() runs
        // on the message-thread timer and performs the single
        // setValueNotifyingHost per parameter per tick, so no mapped knob can
        // run host-facing work, an undo transaction or APVTS listener work
        // inside this render callback.
        //
        // CV-027: the view stores roster slot indices, not parameter-id
        // strings, so this path does no juce::String work and performs no
        // APVTS lookup. A row that is not a live slot (removed parameter, or
        // anything that could never be rostered such as "preset") is -1 and is
        // dropped here.
        for (const auto& metadata : midiMessages)
        {
            auto msg = metadata.getMessage();
            if (!msg.isController())
                continue;
            int cc = msg.getControllerNumber();
            if (cc < 0 || cc >= MAX_MIDI_CCS)
                continue;
            if (cc == capturedCc)
                continue;
            float normValue = msg.getControllerValue() / 127.0f;
            const int slot = midiMapView[(size_t) cc];
            if (slot < 0 || slot >= numMidiHostNotifySlots)
                continue;
            auto* p = midiHostNotifySlots[(size_t) slot].param;
            if (p != nullptr)
                stageMidiHostNotify(p, normValue);
        }
    }
// Snapshot smoothed values for the beginning of this block.
    // beginBlock() calls use these block-level snapshots since their
    // coefficient caches don't need per-sample ramping (the cached
    // exp() values are ~constant over a 64-sample block).
    //
    // CV-030: read getCurrentValue() — the value the smoother has actually
    // reached, i.e. what the previous block rendered — not
    // getTargetValue(), which reports the far end of an in-flight ramp a
    // block early: a block that begins mid-ramp would then seed its
    // coefficient cache with a value the audio path has not reached yet,
    // and percussive material jumps when the next block lands on the real
    // value. getCurrentValue() is a pure read and does NOT advance the ramp
    // — it must never be getNextValue() here, which would consume one ramp
    // step per block and desync the per-sample getNextValue() loop below.
    const float fatness     = smoothFatness.getCurrentValue();
    const float chorusDepth = smoothChorusDepth.getCurrentValue();
    const float chorusRate  = smoothChorusRate.getCurrentValue();
    const float chorusMix   = smoothChorusMix.getCurrentValue();
    const float delayDamping = smoothDelayDamping.getCurrentValue();
    const float reverbSize  = smoothReverbSize.getCurrentValue();
    const float reverbDamping = smoothReverbDamping.getCurrentValue();
    const float reverbMix   = smoothReverbMix.getCurrentValue();
    const float sReverbMod   = smoothReverbMod.getCurrentValue();

    const float pingPong = 0.35f;
    const float reverbPreDelay = 5.0f + reverbSize * 40.0f;

    // Pre-compute delay coefficients once per block (avoids 2× std::exp() per sample)
    delay.beginBlock(delayDamping);

    // Pre-compute reverb coefficients once per block (avoids per-sample setFeedback/setDamp + mod calc)
    if (reverbMix > 0.001f)
        upgradedReverb.beginBlock(reverbSize, reverbDamping, reverbMix, sReverbMod, 1.0f, reverbPreDelay);

    // ── Level meter accumulation (merged into main loop) ──
    // Accumulates peak/RMS in the same pass as DSP processing,
    // eliminating two full buffer iterations per processBlock call.
    float inPeakL_ = 0.0f, inRmsSumL_ = 0.0f;
    float inPeakR_ = 0.0f, inRmsSumR_ = 0.0f;
    float outPeakL_ = 0.0f, outRmsSumL_ = 0.0f;
    float outPeakR_ = 0.0f, outRmsSumR_ = 0.0f;

    float* chData[2] = { nullptr, nullptr };
    for (int ch = 0; ch < chProc; ++ch)
        chData[ch] = buffer.getWritePointer(ch);
    bool isMono = (chProc == 1);

    // ══════════════════════════════════════════════════════════════
    // PER-SAMPLE PROCESSING (single pass)
    // Chain: Distortion → Chorus → Delay → Reverb → Master → Limiter
    // ══════════════════════════════════════════════════════════════

    // Pre-compute distortion coefficients once per block (avoids 4× std::exp() per sample)
    distortion.beginBlock(fatness);

    // Pre-compute chorus coefficients once per block (avoids redundant per-voice math)
    if (chorusDepth > 0.001f)
        chorus.beginBlock(chorusDepth, chorusMix, chorusRate);

    // Pre-compute master output coefficients once per block (avoids 3× std::exp() per sample)
    // Master output always runs, so call unconditionally
    masterOutput.beginBlock();

    // These smoothers feed only block-level coefficient caches, so advance
    // their ramps once for the samples this block will render.
    smoothChorusMix.skip(numSamples);
    smoothDelayDamping.skip(numSamples);
    smoothReverbSize.skip(numSamples);
    smoothReverbDamping.skip(numSamples);
    smoothReverbMod.skip(numSamples);

    foldNonFiniteSamples(chData[0], numSamples);
    if (!isMono)
        foldNonFiniteSamples(chData[1], numSamples);

    for (int s = 0; s < numSamples; ++s)
    {
        // Capture the pristine channel input once per sample, before any DSP
        // writes back into chData. This scalar dry feed is block-length
        // independent, so hosts that hand us a block larger than the prepared
        // size never trigger a scratch-buffer setSize allocation in the audio
        // callback. The R capture keeps the mono duplicate, exactly like the
        // former dryBuffer feed.
        const float dryL = chData[0][s];
        const float dryR = isMono ? dryL : chData[1][s];

        const float sFatness      = smoothFatness.getNextValue();
        const float sChorusDepth  = smoothChorusDepth.getNextValue();
        const float sChorusRate   = smoothChorusRate.getNextValue();
        const float sChorusFb     = sChorusDepth * 0.25f;
        const float sDelayTime    = smoothDelayTime.getNextValue();
        const float sDelayFb      = smoothDelayFeedback.getNextValue();
        const float sDelayMix     = smoothDelayMix.getNextValue();
        const float sReverbMix    = smoothReverbMix.getNextValue();
        const float sDelayMod    = smoothDelayMod.getNextValue();
        const float sOverall      = smoothOverall.getNextValue(); // Per-sample Overall smoothing — eliminates zipper noise on global wet/dry
        const float sMasterDrive  = smoothMasterDrive.getNextValue(); // Per-sample Master Drive smoothing
        const float sMasterWidth  = smoothMasterWidth.getNextValue(); // Per-sample Master Width smoothing
        const float sMasterMidDrive  = smoothMasterMidDrive.getNextValue(); // Per-sample Master Mid Drive smoothing
        const float sMasterSideDrive = smoothMasterSideDrive.getNextValue(); // Per-sample Master Side Drive smoothing
        const float sOutputTrim = smoothOutputTrim.getNextValue(); // Per-sample Output Trim smoothing

        // ── Input level meter (read dry signal before DSP) ──
        {
            float inV_ = std::abs(dryL);
            if (inV_ > inPeakL_) inPeakL_ = inV_;
            inRmsSumL_ += inV_ * inV_;
            if (!isMono)
            {
                float inVR_ = std::abs(dryR);
                if (inVR_ > inPeakR_) inPeakR_ = inVR_;
                inRmsSumR_ += inVR_ * inVR_;
            }
        }

        // Click-free bypass crossfade gains (ramp per sample)
        const float gDist    = bypassGainDist.getNextValue();
        const float gChorus  = bypassGainChorus.getNextValue();
        const float gDelay   = bypassGainDelay.getNextValue();
        const float gReverb  = bypassGainReverb.getNextValue();
        const float gMaster  = bypassGainMaster.getNextValue();

        float smpL = juce::jlimit(-2.0f, 2.0f, chData[0][s]);
        float smpR = juce::jlimit(-2.0f, 2.0f, isMono ? smpL : chData[1][s]);

        // CV-023 input sanitiser: jlimit is comparison-based and maps neither
        // NaN nor infinity to a bound, so a single non-finite sample would
        // otherwise pass straight into delay.processSample()/reverb writes and
        // be stored in their feedback state, repeating for the rest of the
        // session. Fold the chain input to 0 before any DSP sees it (the mono
        // duplicate in smpR folds together with smpL), keeping the existing
        // output guard below as the last line of defence.
        smpL = std::isfinite(smpL) ? smpL : 0.0f;
        smpR = std::isfinite(smpR) ? smpR : 0.0f;

        // 1. DISTORTION (click-free bypass crossfade)
        if (gDist > 0.001f && sFatness > 0.001f)
        {
            float dL, dR;
            distortion.process(smpL, smpR, dL, dR);
            smpL = smpL * (1.0f - gDist) + dL * gDist;
            smpR = smpR * (1.0f - gDist) + dR * gDist;
        }

        // 2. CHORUS (click-free bypass crossfade)
        if (gChorus > 0.001f && sChorusDepth > 0.001f)
        {
            float cl = chorus.process(smpL, 0, sChorusRate, sChorusDepth, sChorusFb);
            float cr = chorus.process(smpR, 1, sChorusRate, sChorusDepth, sChorusFb);
            smpL = smpL * (1.0f - gChorus) + cl * gChorus;
            smpR = smpR * (1.0f - gChorus) + cr * gChorus;
            chorus.advanceWritePos();
        }

        // 3. DELAY (click-free bypass crossfade)
        if (gDelay > 0.001f && sDelayMix > 0.001f && sDelayTime > 0.0f)
        {
            float dL, dR;
            delay.processSample(smpL, smpR, dL, dR,
                sDelayTime, sDelayFb, sDelayMix,
                pingPong, sDelayMod);
            smpL = smpL * (1.0f - gDelay) + dL * gDelay;
            smpR = smpR * (1.0f - gDelay) + dR * gDelay;
        }

        // 4. REVERB (click-free bypass crossfade)
        if (gReverb > 0.001f && sReverbMix > 0.001f)
        {
            float rL, rR;
            upgradedReverb.processSample(smpL, smpR, rL, rR);
            smpL = smpL * (1.0f - gReverb) + rL * gReverb;
            smpR = smpR * (1.0f - gReverb) + rR * gReverb;
        }

        // 5. MASTER OUTPUT STAGE — analog warmth and professional polish
        // Mid/Side processing with independent saturation and width control
        // master_width: 0% = mono, 100% = original stereo, >100% = widened
        // master_mid_drive: 0% = clean, 100% = full push-pull saturation on mid
        // master_side_drive: 0% = clean, 100% = full push-pull saturation on side
        // Master Drive still provides a base drive amount applied to both mid and side
        if (gMaster > 0.001f)
        {
            float midDrive = sMasterDrive * 1.8f + sMasterMidDrive * 1.8f;
            float sideDrive = sMasterDrive * 1.8f + sMasterSideDrive * 1.8f;
            float width = sMasterWidth; // identity: 0% = mono, 100% = original stereo, >100% = widened
            float ml = smpL, mr = smpR;
            masterOutput.process(ml, mr, midDrive, sideDrive, width);
            smpL = smpL * (1.0f - gMaster) + ml * gMaster;
            smpR = smpR * (1.0f - gMaster) + mr * gMaster;
        }

        // 6. SAFETY LIMITER - Pade [3/2] rational approximant (eliminates last per-sample transcendental)
        smpL = padeSoftClip(smpL);
        smpL = juce::jlimit(-1.5f, 1.5f, smpL);

        if (!isMono)
        {
            smpR = padeSoftClip(smpR);
            smpR = juce::jlimit(-1.5f, 1.5f, smpR);
        }

        // 8. OUTPUT TRIM — per-sample final gain adjustment (0-200%)
        smpL *= sOutputTrim;
        if (!isMono) smpR *= sOutputTrim;

        // 9. OVERALL WET/DRY — per-sample linear crossfade with smoothing
        if (sOverall < 0.999f)
        {
            smpL = dryL * (1.0f - sOverall) + smpL * sOverall;
            if (!isMono)
                smpR = dryR * (1.0f - sOverall) + smpR * sOverall;
        }

        chData[0][s] = std::isfinite(smpL) ? smpL : 0.0f;
        if (!isMono) chData[1][s] = std::isfinite(smpR) ? smpR : 0.0f;

        // ── Output level meter (read processed samples) ──
        {
            float outV_ = std::abs(smpL);
            if (outV_ > outPeakL_) outPeakL_ = outV_;
            outRmsSumL_ += outV_ * outV_;
            if (!isMono)
            {
                float outVR_ = std::abs(smpR);
                if (outVR_ > outPeakR_) outPeakR_ = outVR_;
                outRmsSumR_ += outVR_ * outVR_;
            }
        }
    }

    // ── Store accumulated meter values in atomics ──
    if (chProc >= 1)
    {
        const float rmsSmooth = 0.995f;
        float inRmsL_ = std::sqrt(inRmsSumL_ / static_cast<float>(numSamples));
        float inRmsR_ = (chProc >= 2) ? std::sqrt(inRmsSumR_ / static_cast<float>(numSamples)) : inRmsL_;
        float outRmsL_ = std::sqrt(outRmsSumL_ / static_cast<float>(numSamples));
        float outRmsR_ = (chProc >= 2) ? std::sqrt(outRmsSumR_ / static_cast<float>(numSamples)) : outRmsL_;
        levelMeters.inPeakL .store(std::max(levelMeters.inPeakL .load(), inPeakL_),  std::memory_order_relaxed);
        levelMeters.inPeakR .store(std::max(levelMeters.inPeakR .load(), inPeakR_),  std::memory_order_relaxed);
        levelMeters.inRmsL  .store(levelMeters.inRmsL .load() * rmsSmooth + inRmsL_ * (1.0f - rmsSmooth), std::memory_order_relaxed);
        levelMeters.inRmsR  .store(levelMeters.inRmsR .load() * rmsSmooth + inRmsR_ * (1.0f - rmsSmooth), std::memory_order_relaxed);
        levelMeters.outPeakL.store(std::max(levelMeters.outPeakL.load(), outPeakL_), std::memory_order_relaxed);
        levelMeters.outPeakR.store(std::max(levelMeters.outPeakR.load(), outPeakR_), std::memory_order_relaxed);
        levelMeters.outRmsL .store(levelMeters.outRmsL .load() * rmsSmooth + outRmsL_ * (1.0f - rmsSmooth), std::memory_order_relaxed);
        levelMeters.outRmsR .store(levelMeters.outRmsR .load() * rmsSmooth + outRmsR_ * (1.0f - rmsSmooth), std::memory_order_relaxed);
    }
}

bool CorvusFXAudioProcessor::hasEditor() const { return true; }
juce::AudioProcessorEditor* CorvusFXAudioProcessor::createEditor() { return new CorvusFXAudioProcessorEditor(*this); }

void CorvusFXAudioProcessor::getStateInformation(juce::MemoryBlock& destData)
{
    // CV-027: a learn captured in the last audio block may still be waiting for
    // the message-thread fold; apply it before serializing so a save never
    // drops the mapping the user just learned.
    foldPendingMidiLearn();

    auto state = apvts.copyState();
    std::unique_ptr<juce::XmlElement> xml(state.createXml());

    // createXml() returns nullptr on a corrupt/cyclic copyState tree; skip
    // serialization rather than dereferencing a null root element (mirrors
    // the setStateInformation guard).
    if (! xml)
        return;

    // Version tag keeps session loading forward-compatible.
    xml->setAttribute("schemaVersion", 1);
    // Save the A/B-compare snapshots with the state (abSlots child below).
    // Without this the two float[24] snapshots and the active slot live only
    // in memory, so reloading a project silently loses both saved snapshots.

    // Save MIDI Learn mappings as a child element
    auto* mapsXml = xml->createNewChildElement("midiMaps");
    if (mapsXml)
    {
        const juce::ScopedLock lock(midiMapLock);
        for (const auto& [cc, paramID] : midiMap)
        {
            auto* mapXml = mapsXml->createNewChildElement("map");
            mapXml->setAttribute("cc", cc);
            mapXml->setAttribute("param", paramID);
        }
    }

    // Save locked parameters as a child element
    auto* locksXml = xml->createNewChildElement("paramLocks");
    if (locksXml)
    {
        const juce::ScopedLock lock(lockedParamsLock);
        for (const auto& id : lockedParams)
        {
            auto* lockXml = locksXml->createNewChildElement("lock");
            if (lockXml)
                lockXml->setAttribute("id", id);
        }
    }

    // abSlots child: snapshotA/snapshotB as base64 binary floats,
    // active slot as an int attribute.
    if (auto* abXml = xml->createNewChildElement("abSlots"))
    {
        abXml->setAttribute("slot", abSlotIsA ? 1 : 0);
        abXml->createNewChildElement("snapshotA")->addTextElement(
            juce::Base64::toBase64(snapshotA.data(),
                static_cast<size_t>(NUM_AB_PARAMS) * sizeof(float)));
        abXml->createNewChildElement("snapshotB")->addTextElement(
            juce::Base64::toBase64(snapshotB.data(),
                static_cast<size_t>(NUM_AB_PARAMS) * sizeof(float)));
    }

    copyXmlToBinary(*xml, destData);
}

void CorvusFXAudioProcessor::setStateInformation(const void* data, int sizeInBytes)
{
    std::unique_ptr<juce::XmlElement> xml(getXmlFromBinary(data, sizeInBytes));
    if (xml && xml->hasTagName(apvts.state.getType()))
    {
        if (xml->hasAttribute("schemaVersion") && xml->getIntAttribute("schemaVersion") != 1)
            return;

        // Transport metadata is decoded below from the original XML. Keep
        // it out of the parameter ValueTree: XML text children are discarded
        // by ValueTree::fromXml, and retaining their wrappers would serialize
        // stale duplicate slots/maps/locks on the next save.
        juce::XmlElement parameterState(*xml);
        parameterState.deleteAllChildElementsWithTagName("abSlots");
        parameterState.deleteAllChildElementsWithTagName("midiMaps");
        parameterState.deleteAllChildElementsWithTagName("paramLocks");
        // CV-028: replaceState rewrites the whole parameter tree, so the
        // restore is one recall. While the batch is open, a block header that
        // reads parameters here cannot commit — and if it already read, it
        // restores its last coherent generation instead of a half-restored
        // session.
        ParameterGenerationBatch batch(presetBatchSequence);
        restoringPresetState.store(true);
        apvts.replaceState(juce::ValueTree::fromXml(parameterState));
        restoringPresetState.store(false);

        // Clear A/B-compare snapshots unconditionally so an absent or partial
        // pair in the restored state cannot inherit the previous session.
        {
            snapshotA.fill(0.0f);
            snapshotB.fill(0.0f);
            abSlotIsA = true;
            abSnapshotsPersisted = false;
        }

        // Restore A/B-compare snapshots only when the state carries them.
        // Older states (no "abSlots" child) leave abSnapshotsPersisted
        // false so the editor constructor reseed keeps its legacy role:
        // initialising both slots with the recall's parameter values.
        // Restored slots reopen a saved A/B compare instead of leaving both
        // slots in a state where a mere editor reopen destroys them.
        if (auto* abXml = xml->getChildByName("abSlots"))
        {
            juce::MemoryOutputStream aMB;
            bool restoredA = false;
            bool restoredB = false;
            if (auto* aXml = abXml->getChildByName("snapshotA"))
            {
                restoredA = juce::Base64::convertFromBase64(aMB, aXml->getAllSubText())
                    && aMB.getDataSize() == static_cast<size_t>(NUM_AB_PARAMS) * sizeof(float);
            }
            juce::MemoryOutputStream bMB;
            if (auto* bXml = abXml->getChildByName("snapshotB"))
            {
                restoredB = juce::Base64::convertFromBase64(bMB, bXml->getAllSubText())
                    && bMB.getDataSize() == static_cast<size_t>(NUM_AB_PARAMS) * sizeof(float);
            }
            if (restoredA && restoredB)
            {
                std::memcpy(snapshotA.data(), aMB.getData(), aMB.getDataSize());
                std::memcpy(snapshotB.data(), bMB.getData(), bMB.getDataSize());
                abSlotIsA = abXml->getIntAttribute("slot", 0) != 0;
                abSnapshotsPersisted = true;
            }
        }

        // Clear MIDI Learn mappings unconditionally: a saved state from an
        // older build (without a "midiMaps" child) must not silently keep the
        // previous session's CC mappings armed.
        {
            const juce::ScopedLock lock(midiMapLock);
            midiMap.clear();
        }

        // Restore MIDI Learn mappings (only when the state carries them)
        if (auto* mapsXml = xml->getChildByName("midiMaps"))
        {
            const juce::ScopedLock lock(midiMapLock);
            for (auto* mapXml : mapsXml->getChildWithTagNameIterator("map"))
            {
                int cc = mapXml->getIntAttribute("cc");
                juce::String paramID = mapXml->getStringAttribute("param");
                // CV-029: never restore a CC→preset mapping. Mapping creation
                // (startMidiLearn / learn capture) and the audio-thread apply
                // path reject "preset" too, so a saved or hand-edited state
                // can never re-arm a CC that fans out into a whole preset
                // change (undo transaction + full parameter rewrite).
                if (paramID != "preset" && paramID.isNotEmpty()
                    && apvts.getParameter(paramID) != nullptr)
                    midiMap[cc] = paramID;
            }
        }

        // CV-027: a restored session starts from the saved map only. Drop any
        // learn captured by the previous session's audio thread and republish
        // the rebuilt table so the next processBlock adopts it without a lock.
        pendingLearnCc.store(-1, std::memory_order_relaxed);
        pendingLearnSlot.store(-1, std::memory_order_relaxed);
        publishMidiMap();

        // Clear locked parameters unconditionally: a saved state from an
        // older build (without a "paramLocks" child) must not silently keep
        // the previous session's locks armed.
        {
            const juce::ScopedLock lock(lockedParamsLock);
            lockedParams.clear();
        }

        // Restore locked parameter list (only when the state carries them)
        if (auto* restoredLocksXml = xml->getChildByName("paramLocks"))
        {
            const juce::ScopedLock lock(lockedParamsLock);
            for (auto* lockXml : restoredLocksXml->getChildWithTagNameIterator("lock"))
            {
                const juce::String id = lockXml->getStringAttribute("id");
                // isEmpty, not isNotEmpty: the CV-043 empty-id probe removes
                // only the insert guard, and a second isNotEmpty() would hide that.
                if (!id.isEmpty() && apvts.getParameter(id) == nullptr)
                    continue;
                if (id.isNotEmpty())
                    lockedParams.insert(id);
            }
        }

        // CV-028: the restored parameter set is complete and every companion
        // child (abSlots, midiMaps, paramLocks) is in place — commit it as one
        // generation so the next block adopts the session whole.
        batch.close();
        publishParameterGeneration();
}

}

juce::AudioProcessor* JUCE_CALLTYPE createPluginFilter() { return new CorvusFXAudioProcessor(); }
