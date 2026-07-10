#include "PluginProcessor.h"
#include "PluginEditor.h"
#include <cmath>
#include <algorithm>

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
apvts(*this, nullptr, "Parameters", createParameterLayout())
{
    apvts.addParameterListener("preset", this);
}

CorvusFXAudioProcessor::~CorvusFXAudioProcessor()
{
    apvts.removeParameterListener("preset", this);
}

void CorvusFXAudioProcessor::parameterChanged(const juce::String& parameterID, float newValue)
{
    if (parameterID == "preset")
    {
        // ComboBoxAttachment maps the parameter value to combo box item ID.
        // The combo has 28 items (IDs 1-28) with 4 disabled separators (IDs 1,8,15,22).
        // We convert the item ID to a preset index via a lookup table.
        static const int idToPreset[29] = {
            0,  -1, 0, 1, 2, 3, 4, 5,   // IDs 0-7  (0=unused, 1=separator, 2-7=CLEAN presets 0-5)
            -1, 6, 7, 8, 9,10,11,       // IDs 8-14 (8=separator, 9-14=WARM presets 6-11)
            -1,12,13,14,15,16,17,        // IDs 15-21 (15=separator, 16-21=CREATIVE presets 12-17)
            -1,18,19,20,21,22,23         // IDs 22-28 (22=separator, 23-28=EXTREME presets 18-23)
        };
        int id = static_cast<int>(newValue + 0.5f);
        if (id >= 2 && id <= 28 && idToPreset[id] >= 0)
            loadPreset(idToPreset[id]);
    }
}

void CorvusFXAudioProcessor::loadPreset(int index)
{
    // index is the combo box item position (0-23), which maps directly
    // to the preset array index. The JUCE ComboBoxAttachment maps
    // item position -> parameter value linearly, and the presets[]
    // array is ordered to match the combo box layout.
    // Combo order: CLEAN [0-5], WARM [6-11], CREATIVE [12-17], EXTREME [18-23]
    if (index < 0 || index >= 24) return;
    
    //                    fat  cD   cR    cM   dT   dFb  dM   dDmp dMod rS   rDmp rM   rMod  mDrv mWid mMid mSide dByp
    struct P { float fat, cD, cR, cM, dT, dFb, dM, dDmp, dMod, rS, rDmp, rM, rMod, mDrv, mWid, mMid, mSide, distByp; };
    static const P presets[24] = {
        // ── CLEAN (pos 0-5): transparent enhancement, pristine highs ──────
        // 0: Clean Sparkle — subtle widening, pristine highs
        {  8, 25, 1.2f, 35,   0,  0,  0,  0,  0,  20, 55, 10, 20,   0, 100,   0,   0, 0 },
        // 1: Crystal Shimmer — chorus-forward, bright and airy
        {  5, 60, 3.0f, 70, 130, 15, 15, 25, 40,  50, 25, 20, 75,   0, 100,   0,   0, 0 },
        // 2: Silk Thread — ultra-smooth chorus, no drive, gentle space
        {  0, 40, 0.5f, 60,   0,  0,  0,  0,  0,  35, 50, 12, 40,   0, 100,   0,   0, 0 },
        // 3: Subtle Glue — bus cohesion, barely-there enhancement
        { 28,  8, 1.2f, 18,  80, 12,  8, 45, 10,  25, 60,  8, 12,   0, 100,   0,   0, 0 },
        // 4: Glass Canon — pristine stereo widening, shimmering highs, zero drive
        {  0, 35, 2.8f, 40, 110,  8, 15, 15, 45,  45, 40, 22, 65,   0, 120,   0,   0, 0 },
        // 5: Air Lift — gentle HF excitation, subtle chorus, airy top end
        { 12, 30, 4.0f, 35,   0,  0,  0,  0,  0,  20, 30,  8, 55,   0, 100,   0,   0, 0 },

        // ── WARM (pos 6-11): analog-style saturation, musical thickening ───
        // 6: Warm Glow — medium drive, gentle chorus thickening
        { 40, 18, 1.8f, 30, 180, 20, 12, 55, 25,  35, 65, 15, 25,  20, 100,  10,   5, 0 },
        // 7: Vintage Vibe — lo-fi warmth, rolled-off highs
        { 55, 30, 0.7f, 40, 280, 32, 22, 80, 20,  55, 75, 18, 15,  30, 100,  15,  10, 0 },
        // 8: Thick Sauce — heavy saturation, chorus thickening
        { 72, 35, 2.2f, 45, 200, 28, 18, 50, 35,  40, 55, 18, 30,  40, 100,  20,  15, 0 },
        // 9: Tight Punch — controlled, punchy, no excess
        { 45, 12, 2.0f, 22, 100, 18, 10, 55, 15,  28, 65,  8, 18,  15, 100,   5,   5, 0 },
        // 10: Cozy Hiss — cassette deck warmth, gentle wow, lo-fi magic
        { 35, 15, 0.9f, 28, 220, 35, 20, 85, 55,  30, 70, 12, 40,  25, 100,  10,  10, 0 },
        // 11: Tube Glow — mild tube drive, rich harmonics, subtle room verb
        { 50, 10, 1.5f, 20,   0,  0,  0,  0,  0,  25, 50, 12, 25,  20, 100,  10,   0, 0 },

        // ── CREATIVE (pos 12-17): modulation-forward, sound design ─────────
        // 12: Dreamy Space — low drive, deep chorus, big reverb
        { 12, 50, 0.8f, 55, 420, 35, 25, 40, 30,  85, 30, 55, 65,  10, 110,   5,  15, 0 },
        // 13: Cosmic Wide — maximum stereo width, deep modulation
        { 22, 75, 3.5f, 65, 160, 25, 28, 30, 60,  80, 25, 45, 85,   0, 130,   0,  20, 0 },
        // 14: Molten Core — heavy saturation into drenched chorus
        { 78, 55, 1.5f, 70, 150, 22, 20, 45, 30,  25, 45, 12, 35,  50, 100,  25,  20, 0 },
        // 15: Sunspot — fast bright chorus + short slapback delay
        {  0, 45, 4.5f, 55,  65, 10, 25, 20, 35,  15, 40,  5, 50,   0, 100,   0,   0, 0 },
        // 16: Nebula Drift — slow evolving chorus + long pre-delay reverb
        { 20, 65, 0.3f, 55, 300, 40, 18, 50, 40,  88, 35, 55, 80,   5, 115,   0,  10, 0 },
        // 17: Shimmerfall — cascading delay into shimmer reverb, ethereal wash
        {  5, 40, 2.0f, 45, 350, 50, 40, 35, 45,  80, 15, 60, 90,  10, 120,   5,  15, 0 },

        // ── EXTREME (pos 18-23): aggressive, heavy processing ──────────────
        // 18: Deep Echo — tape delay focus, dark repeats
        { 18, 12, 1.5f, 20, 520, 58, 55, 75, 50,  45, 60, 15, 25,  15, 100,  10,  10, 0 },
        // 19: Aggressive Drive — in-your-face distortion character
        { 88, 15, 2.0f, 25, 200, 25, 15, 60, 25,  30, 55, 10, 20,  70, 100,  30,  20, 0 },
        // 20: Lush Pad — massive reverb wash for sustained sounds
        { 15, 45, 1.0f, 50, 380, 30, 15, 35, 30,  92, 20, 65, 70,   5, 120,   0,  15, 0 },
        // 21: Event Horizon — long delay + heavy feedback into massive reverb
        { 10, 20, 0.6f, 30, 800, 65, 45, 55, 45,  95, 15, 70, 90,  20, 125,  10,  25, 0 },
        // 22: Iron Press — heavy parallel compression via drive + tight verb
        { 65,  5, 1.8f, 15,  60, 15,  8, 70, 20,  18, 80,  6, 10,  40,  90,  20,  10, 0 },
        // 23: Obliterator — maxed drive, deep chorus, long feedback, giant hall
        { 95, 50, 1.2f, 55, 600, 70, 40, 65, 50,  90, 30, 55, 85,  80, 100,  40,  30, 0 },
    };
    
    const auto& p = presets[index];
    auto set = [this](const juce::String& id, float v) {
        auto* param = apvts.getParameter(id);
        if (param) param->setValueNotifyingHost(param->convertTo0to1(v));
        };
    set("fatness", p.fat); set("chorus_depth", p.cD); set("chorus_rate", p.cR);
    set("chorus_mix", p.cM); set("delay_time", p.dT); set("delay_feedback", p.dFb);
    set("delay_mix", p.dM); set("delay_damping", p.dDmp); set("delay_mod", p.dMod);
    set("reverb_size", p.rS); set("reverb_damping", p.rDmp); set("reverb_mix", p.rM); set("reverb_mod", p.rMod);
    set("master_drive", p.mDrv); set("master_width", p.mWid); set("master_mid_drive", p.mMid); set("master_side_drive", p.mSide);
    set("distortion_bypass", p.distByp);
}

juce::AudioProcessorValueTreeState::ParameterLayout CorvusFXAudioProcessor::createParameterLayout()
{
    std::vector<std::unique_ptr<juce::RangedAudioParameter>> params;

    // Helper lambda for percentage parameters with proper formatting
    auto pctParam = [](const juce::String& id, const juce::String& name, float def) {
        auto range = juce::NormalisableRange<float>(0, 100, 0.1f);
        return std::make_unique<juce::AudioParameterFloat>(
            id, name, range, def, "%",
            juce::AudioParameterFloatAttributes().withLabel("%"),
            [range](float value, int) { return juce::String(value, 1) + " %"; },
            [range](const juce::String& text) { return text.replace("%", "").getFloatValue(); });
    };

    // Helper for Hz parameters
    auto hzParam = [](const juce::String& id, const juce::String& name, float min, float max, float def) {
        auto range = juce::NormalisableRange<float>(min, max, 0.1f);
        return std::make_unique<juce::AudioParameterFloat>(
            id, name, range, def, "Hz",
            juce::AudioParameterFloatAttributes().withLabel("Hz"),
            [range](float value, int) { return juce::String(value, 1) + " Hz"; },
            [range](const juce::String& text) { return text.replace("Hz", "").replace("hz", "").getFloatValue(); });
    };

    // Helper for ms parameters
    auto msParam = [](const juce::String& id, const juce::String& name, float min, float max, float def) {
        auto range = juce::NormalisableRange<float>(min, max, 1.0f);
        return std::make_unique<juce::AudioParameterFloat>(
            id, name, range, def, "ms",
            juce::AudioParameterFloatAttributes().withLabel("ms"),
            [range](float value, int) { return juce::String((int)value) + " ms"; },
            [range](const juce::String& text) { return text.replace("ms", "").getFloatValue(); });
    };

    params.push_back(pctParam("overall", "Overall", 100));
    params.push_back(pctParam("fatness", "Fatness", 0));
    params.push_back(std::make_unique<juce::AudioParameterBool>("distortion_bypass", "Distortion Bypass", false));
    params.push_back(pctParam("chorus_depth", "Chorus Depth", 0));
    params.push_back(hzParam("chorus_rate", "Chorus Rate", 0.1f, 10, 2));
    params.push_back(pctParam("chorus_mix", "Chorus Mix", 50));
    params.push_back(msParam("delay_time", "Delay Time", 0, 2000, 250));
    params.push_back(pctParam("delay_feedback", "Delay Feedback", 30));
    params.push_back(pctParam("delay_mix", "Delay Mix", 0));
    params.push_back(pctParam("delay_damping", "Delay Damping", 40));
    params.push_back(pctParam("delay_mod", "Delay Mod", 30));
    params.push_back(pctParam("reverb_size", "Reverb Size", 50));
    params.push_back(pctParam("reverb_damping", "Reverb Damping", 50));
    params.push_back(pctParam("reverb_mix", "Reverb Mix", 0));
    params.push_back(pctParam("reverb_mod", "Reverb Mod", 30));
    params.push_back(pctParam("master_drive", "Master Drive", 0));
    params.push_back(pctParam("master_width", "Master Width", 100));
    params.push_back(pctParam("master_mid_drive", "Master Mid Drive", 0));
    params.push_back(pctParam("master_side_drive", "Master Side Drive", 0));
    params.push_back(std::make_unique<juce::AudioParameterBool>("chorus_bypass", "Chorus Bypass", false));
    params.push_back(std::make_unique<juce::AudioParameterBool>("delay_bypass", "Delay Bypass", false));
    params.push_back(std::make_unique<juce::AudioParameterBool>("reverb_bypass", "Reverb Bypass", false));
    params.push_back(std::make_unique<juce::AudioParameterBool>("master_bypass", "Master Bypass", false));
    params.push_back(std::make_unique<juce::AudioParameterInt>("preset", "Preset", 0, 23, 0));
    return { params.begin(), params.end() };
}

const juce::String CorvusFXAudioProcessor::getName() const
{
#ifndef JucePlugin_Name
#define JucePlugin_Name "CorvusFX"
#endif
    return JucePlugin_Name;
}
bool CorvusFXAudioProcessor::acceptsMidi() const { return false; }
bool CorvusFXAudioProcessor::producesMidi() const { return false; }
bool CorvusFXAudioProcessor::isMidiEffect() const { return false; }
double CorvusFXAudioProcessor::getTailLengthSeconds() const { return 8.0; }
int CorvusFXAudioProcessor::getNumPrograms() { return 24; }
int CorvusFXAudioProcessor::getCurrentProgram() { return (int)(apvts.getRawParameterValue("preset")->load() + 0.5f); }
void CorvusFXAudioProcessor::setCurrentProgram(int i) {
    if (i >= 0 && i < 24) { auto* p = apvts.getParameter("preset"); if (p) p->setValueNotifyingHost(p->convertTo0to1((float)i)); }
}
const juce::String CorvusFXAudioProcessor::getProgramName(int i) {
    // Reordered to match combo box layout: CLEAN [0-5], WARM [6-11], CREATIVE [12-17], EXTREME [18-23]
    static const juce::String n[24] = { "Clean Sparkle","Crystal Shimmer","Silk Thread","Subtle Glue","Glass Canon","Air Lift","Warm Glow","Vintage Vibe","Thick Sauce","Tight Punch","Cozy Hiss","Tube Glow","Dreamy Space","Cosmic Wide","Molten Core","Sunspot","Nebula Drift","Shimmerfall","Deep Echo","Aggressive Drive","Lush Pad","Event Horizon","Iron Press","Obliterator" };
    return (i >= 0 && i < 24) ? n[i] : juce::String();
}
void CorvusFXAudioProcessor::changeProgramName(int, const juce::String&) {}

void CorvusFXAudioProcessor::prepareToPlay(double sampleRate, int samplesPerBlock)
{
    lastSampleRate = sampleRate;
    chorus.prepare(sampleRate);
    delay.prepare(sampleRate);
    distortion.prepare(sampleRate);
    upgradedReverb.prepare(sampleRate);
    masterOutput.prepare(sampleRate);
    dryBuffer.setSize(2, samplesPerBlock, false, true, true);

    // ── Parameter smoothing initialization ──
    // 20ms smoothing time: responsive feel, no zipper noise.
    // Reset current values to parameter defaults so smoothing
    // starts from the correct state (no ramp from zero on load).
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

    // Set initial target values from current parameter state
    smoothOverall.setTargetValue(apvts.getRawParameterValue("overall")->load() / 100.0f);
    smoothFatness.setTargetValue(apvts.getRawParameterValue("fatness")->load() / 100.0f);
    smoothChorusDepth.setTargetValue(apvts.getRawParameterValue("chorus_depth")->load() / 100.0f);
    smoothChorusRate.setTargetValue(apvts.getRawParameterValue("chorus_rate")->load());
    smoothChorusMix.setTargetValue(apvts.getRawParameterValue("chorus_mix")->load() / 100.0f);
    smoothDelayTime.setTargetValue(apvts.getRawParameterValue("delay_time")->load());
    {
        float fbRaw = apvts.getRawParameterValue("delay_feedback")->load() / 100.0f;
        smoothDelayFeedback.setTargetValue(fbRaw * fbRaw * 0.65f + fbRaw * 0.27f);
    }
    smoothDelayMix.setTargetValue(apvts.getRawParameterValue("delay_mix")->load() / 100.0f);
    smoothDelayDamping.setTargetValue(apvts.getRawParameterValue("delay_damping")->load() / 100.0f);
    smoothDelayMod.setTargetValue(apvts.getRawParameterValue("delay_mod")->load() / 100.0f);
    smoothReverbSize.setTargetValue(apvts.getRawParameterValue("reverb_size")->load() / 100.0f);
    smoothReverbDamping.setTargetValue(apvts.getRawParameterValue("reverb_damping")->load() / 100.0f);
    smoothReverbMix.setTargetValue(apvts.getRawParameterValue("reverb_mix")->load() / 100.0f);
    smoothReverbMod.setTargetValue(apvts.getRawParameterValue("reverb_mod")->load() / 100.0f);
    smoothMasterDrive.setTargetValue(apvts.getRawParameterValue("master_drive")->load() / 100.0f);
    smoothMasterWidth.setTargetValue(apvts.getRawParameterValue("master_width")->load() / 100.0f);
    smoothMasterMidDrive.setTargetValue(apvts.getRawParameterValue("master_mid_drive")->load() / 100.0f);
    smoothMasterSideDrive.setTargetValue(apvts.getRawParameterValue("master_side_drive")->load() / 100.0f);
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
void CorvusFXAudioProcessor::processBlock(juce::AudioBuffer<float>& buffer, juce::MidiBuffer&)
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
    smoothOverall.setTargetValue(apvts.getRawParameterValue("overall")->load() / 100.0f);
    smoothFatness.setTargetValue(apvts.getRawParameterValue("fatness")->load() / 100.0f);
    smoothChorusDepth.setTargetValue(apvts.getRawParameterValue("chorus_depth")->load() / 100.0f);
    smoothChorusRate.setTargetValue(apvts.getRawParameterValue("chorus_rate")->load());
    smoothChorusMix.setTargetValue(apvts.getRawParameterValue("chorus_mix")->load() / 100.0f);
    smoothDelayTime.setTargetValue(apvts.getRawParameterValue("delay_time")->load());
    {
        // Exponential mapping: linear knob → musical feedback response
        // Applied to the target value so the exponential curve is preserved through smoothing
        float fbRaw = apvts.getRawParameterValue("delay_feedback")->load() / 100.0f;
        smoothDelayFeedback.setTargetValue(fbRaw * fbRaw * 0.65f + fbRaw * 0.27f);
    }
    smoothDelayMix.setTargetValue(apvts.getRawParameterValue("delay_mix")->load() / 100.0f);
    smoothDelayDamping.setTargetValue(apvts.getRawParameterValue("delay_damping")->load() / 100.0f);
    smoothDelayMod.setTargetValue(apvts.getRawParameterValue("delay_mod")->load() / 100.0f);
    smoothReverbSize.setTargetValue(apvts.getRawParameterValue("reverb_size")->load() / 100.0f);
    smoothReverbDamping.setTargetValue(apvts.getRawParameterValue("reverb_damping")->load() / 100.0f);
    smoothReverbMix.setTargetValue(apvts.getRawParameterValue("reverb_mix")->load() / 100.0f);
    smoothReverbMod.setTargetValue(apvts.getRawParameterValue("reverb_mod")->load() / 100.0f);
    smoothMasterDrive.setTargetValue(apvts.getRawParameterValue("master_drive")->load() / 100.0f);
    smoothMasterWidth.setTargetValue(apvts.getRawParameterValue("master_width")->load() / 100.0f);
    smoothMasterMidDrive.setTargetValue(apvts.getRawParameterValue("master_mid_drive")->load() / 100.0f);
    smoothMasterSideDrive.setTargetValue(apvts.getRawParameterValue("master_side_drive")->load() / 100.0f);
    const bool distortionBypass = apvts.getRawParameterValue("distortion_bypass")->load() > 0.5f;
    const bool chorusBypass = apvts.getRawParameterValue("chorus_bypass")->load() > 0.5f;
    const bool delayBypass = apvts.getRawParameterValue("delay_bypass")->load() > 0.5f;
    const bool reverbBypass = apvts.getRawParameterValue("reverb_bypass")->load() > 0.5f;
    const bool masterBypass = apvts.getRawParameterValue("master_bypass")->load() > 0.5f;

    // Snapshot smoothed values for the beginning of this block.
    // beginBlock() calls use these block-level snapshots since their
    // coefficient caches don't need per-sample ramping (the cached
    // exp() values are ~constant over a 64-sample block).
    const float overallMix = smoothOverall.getTargetValue();
    const float fatness     = smoothFatness.getTargetValue();
    const float chorusDepth = smoothChorusDepth.getTargetValue();
    const float chorusRate  = smoothChorusRate.getTargetValue();
    const float chorusMix   = smoothChorusMix.getTargetValue();
    const float delayTime   = smoothDelayTime.getTargetValue();
    const float delayFeedback = smoothDelayFeedback.getTargetValue();
    const float delayMix    = smoothDelayMix.getTargetValue();
    const float delayDamping = smoothDelayDamping.getTargetValue();
    const float delayMod    = smoothDelayMod.getTargetValue();
    const float reverbSize  = smoothReverbSize.getTargetValue();
    const float reverbDamping = smoothReverbDamping.getTargetValue();
    const float reverbMix   = smoothReverbMix.getTargetValue();
    const float sReverbMod   = smoothReverbMod.getTargetValue();

    const float chorusFeedback = chorusDepth * 0.25f;
    const float delayModAmount = delayMod;
    const float pingPong = 0.35f;
    const float reverbPreDelay = 5.0f + reverbSize * 40.0f;

    // Pre-compute delay coefficients once per block (avoids 2× std::exp() per sample)
    delay.beginBlock(delayDamping);

    // Pre-compute reverb coefficients once per block (avoids per-sample setFeedback/setDamp + mod calc)
    if (reverbMix > 0.001f)
        upgradedReverb.beginBlock(reverbSize, reverbDamping, reverbMix, reverbMod, 1.0f, reverbPreDelay);

    // Store dry signal
    if (dryBuffer.getNumSamples() < numSamples || dryBuffer.getNumChannels() < chProc)
        dryBuffer.setSize(chProc, numSamples, false, false, true);
    for (int ch = 0; ch < chProc; ++ch)
        dryBuffer.copyFrom(ch, 0, buffer, ch, 0, numSamples);

    // ── Input level meters (pre-processing) ──
    // Use relaxed atomics — approximate values are fine for display
    if (chProc >= 1)
    {
        float inPeakL = 0.0f, inRmsSumL = 0.0f;
        float inPeakR = 0.0f, inRmsSumR = 0.0f;
        const float* inL = buffer.getReadPointer(0);
        const float* inR = (chProc >= 2) ? buffer.getReadPointer(1) : buffer.getReadPointer(0);
        for (int s = 0; s < numSamples; ++s)
        {
            float vL = std::abs(inL[s]);
            float vR = std::abs(inR[s]);
            if (vL > inPeakL) inPeakL = vL;
            if (vR > inPeakR) inPeakR = vR;
            inRmsSumL += vL * vL;
            inRmsSumR += vR * vR;
        }
        float inRmsL = std::sqrt(inRmsSumL / static_cast<float>(numSamples));
        float inRmsR = std::sqrt(inRmsSumR / static_cast<float>(numSamples));
        // Smooth with simple exponential decay (attack=0, release~300ms at 48kHz)
        const float peakSmooth = 0.999f;
        const float rmsSmooth  = 0.995f;
        levelMeters.inPeakL .store(std::max(levelMeters.inPeakL .load(), inPeakL),  std::memory_order_relaxed);
        levelMeters.inPeakR .store(std::max(levelMeters.inPeakR .load(), inPeakR),  std::memory_order_relaxed);
        levelMeters.inRmsL  .store(levelMeters.inRmsL .load() * rmsSmooth + inRmsL  * (1.0f - rmsSmooth), std::memory_order_relaxed);
        levelMeters.inRmsR  .store(levelMeters.inRmsR .load() * rmsSmooth + inRmsR  * (1.0f - rmsSmooth), std::memory_order_relaxed);
    }

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

    for (int s = 0; s < numSamples; ++s)
    {
        const float sFatness      = smoothFatness.getNextValue();
        const float sChorusDepth  = smoothChorusDepth.getNextValue();
        const float sChorusRate   = smoothChorusRate.getNextValue();
        const float sChorusFb     = sChorusDepth * 0.25f;
        const float sDelayTime    = smoothDelayTime.getNextValue();
        const float sDelayFb      = smoothDelayFeedback.getNextValue();
        const float sDelayMix     = smoothDelayMix.getNextValue();
        const float sReverbMix    = smoothReverbMix.getNextValue();
        const float sOverall      = smoothOverall.getNextValue(); // Per-sample Overall smoothing — eliminates zipper noise on global wet/dry
        const float sMasterDrive  = smoothMasterDrive.getNextValue(); // Per-sample Master Drive smoothing
        const float sMasterWidth  = smoothMasterWidth.getNextValue(); // Per-sample Master Width smoothing
        const float sMasterMidDrive  = smoothMasterMidDrive.getNextValue(); // Per-sample Master Mid Drive smoothing
        const float sMasterSideDrive = smoothMasterSideDrive.getNextValue(); // Per-sample Master Side Drive smoothing

        float smpL = juce::jlimit(-2.0f, 2.0f, chData[0][s]);
        float smpR = juce::jlimit(-2.0f, 2.0f, isMono ? smpL : chData[1][s]);

        // 1. DISTORTION
        if (!distortionBypass && sFatness > 0.001f)
        {
            float dL, dR;
            distortion.process(smpL, smpR, sFatness, dL, dR);
            smpL = dL;
            smpR = dR;
        }

        // 2. CHORUS (with click-free bypass crossfade)
        if (chorusBypass)
        {
            // Bypassed - do nothing, signal passes through dry
        }
        else if (sChorusDepth > 0.001f)
        {
            smpL = chorus.process(smpL, 0, sChorusRate, sChorusDepth, sChorusFb);
            smpR = chorus.process(smpR, 1, sChorusRate, sChorusDepth, sChorusFb);
            chorus.advanceWritePos();
        }

        // 3. DELAY (with click-free bypass crossfade)
        if (!delayBypass && sDelayMix > 0.001f && sDelayTime > 0.0f)
        {
            float dL, dR;
            delay.processSample(smpL, smpR, dL, dR,
                sDelayTime, sDelayFb, sDelayMix,
                pingPong, delayModAmount);
            smpL = dL;
            smpR = dR;
        }

        // 4. REVERB (with click-free bypass crossfade)
        if (!reverbBypass && sReverbMix > 0.001f)
        {
            float rL, rR;
            upgradedReverb.processSample(smpL, smpR, rL, rR);
            smpL = rL;
            smpR = rR;
        }

        // 5. MASTER OUTPUT STAGE — analog warmth and professional polish
        // Mid/Side processing with independent saturation and width control
        // master_width: 0% = mono, 100% = original stereo, >100% = widened
        // master_mid_drive: 0% = clean, 100% = full push-pull saturation on mid
        // master_side_drive: 0% = clean, 100% = full push-pull saturation on side
        // Master Drive still provides a base drive amount applied to both mid and side
        if (!masterBypass)
        {
            float midDrive = sMasterDrive * 1.8f + sMasterMidDrive * 1.8f;
            float sideDrive = sMasterDrive * 1.8f + sMasterSideDrive * 1.8f;
            float width = 0.5f + sMasterWidth * 1.5f; // 0.5 to 2.0 range
            masterOutput.process(smpL, smpR, midDrive, sideDrive, width);
        }

        // 6. SAFETY LIMITER (merged from separate pass)
        if (smpL > 1.0f)
            smpL = 1.0f + std::tanh((smpL - 1.0f) * 0.5f) * 0.2f;
        else if (smpL < -1.0f)
            smpL = -1.0f + std::tanh((smpL + 1.0f) * 0.5f) * 0.2f;
        smpL = juce::jlimit(-1.5f, 1.5f, smpL);

        if (!isMono)
        {
            if (smpR > 1.0f)
                smpR = 1.0f + std::tanh((smpR - 1.0f) * 0.5f) * 0.2f;
            else if (smpR < -1.0f)
                smpR = -1.0f + std::tanh((smpR + 1.0f) * 0.5f) * 0.2f;
            smpR = juce::jlimit(-1.5f, 1.5f, smpR);
        }

        // 7. OVERALL WET/DRY — per-sample linear crossfade with smoothing
        if (sOverall < 0.999f)
        {
            smpL = dryBuffer.getReadPointer(0)[s] * (1.0f - sOverall) + smpL * sOverall;
            if (!isMono)
                smpR = dryBuffer.getReadPointer(1)[s] * (1.0f - sOverall) + smpR * sOverall;
        }

        chData[0][s] = smpL;
        if (!isMono) chData[1][s] = smpR;
    }

    // ── Output level meters (post-processing) ──
    if (chProc >= 1)
    {
        float outPeakL = 0.0f, outRmsSumL = 0.0f;
        float outPeakR = 0.0f, outRmsSumR = 0.0f;
        const float* outL = buffer.getReadPointer(0);
        const float* outR = (chProc >= 2) ? buffer.getReadPointer(1) : buffer.getReadPointer(0);
        for (int s = 0; s < numSamples; ++s)
        {
            float vL = std::abs(outL[s]);
            float vR = std::abs(outR[s]);
            if (vL > outPeakL) outPeakL = vL;
            if (vR > outPeakR) outPeakR = vR;
            outRmsSumL += vL * vL;
            outRmsSumR += vR * vR;
        }
        float outRmsL = std::sqrt(outRmsSumL / static_cast<float>(numSamples));
        float outRmsR = std::sqrt(outRmsSumR / static_cast<float>(numSamples));
        // Smooth with simple exponential decay
        const float peakSmooth = 0.999f;
        const float rmsSmooth  = 0.995f;
        levelMeters.outPeakL.store(std::max(levelMeters.outPeakL.load(), outPeakL), std::memory_order_relaxed);
        levelMeters.outPeakR.store(std::max(levelMeters.outPeakR.load(), outPeakR), std::memory_order_relaxed);
        levelMeters.outRmsL .store(levelMeters.outRmsL .load() * rmsSmooth + outRmsL * (1.0f - rmsSmooth), std::memory_order_relaxed);
        levelMeters.outRmsR .store(levelMeters.outRmsR .load() * rmsSmooth + outRmsR * (1.0f - rmsSmooth), std::memory_order_relaxed);
    }
}

bool CorvusFXAudioProcessor::hasEditor() const { return true; }
juce::AudioProcessorEditor* CorvusFXAudioProcessor::createEditor() { return new CorvusFXAudioProcessorEditor(*this); }

void CorvusFXAudioProcessor::getStateInformation(juce::MemoryBlock& destData)
{
    auto state = apvts.copyState();
    std::unique_ptr<juce::XmlElement> xml(state.createXml());
    copyXmlToBinary(*xml, destData);
}

void CorvusFXAudioProcessor::setStateInformation(const void* data, int sizeInBytes)
{
    std::unique_ptr<juce::XmlElement> xml(getXmlFromBinary(data, sizeInBytes));
    if (xml && xml->hasTagName(apvts.state.getType()))
        apvts.replaceState(juce::ValueTree::fromXml(*xml));
}

juce::AudioProcessor* JUCE_CALLTYPE createPluginFilter() { return new CorvusFXAudioProcessor(); }