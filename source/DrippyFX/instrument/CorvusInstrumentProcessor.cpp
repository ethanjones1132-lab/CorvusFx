#include "CorvusInstrumentProcessor.h"
#include "CorvusInstrumentEditor.h"
#include "CorvusInstrumentPresets.h"
#include "../dsp/CorvusEffects.h"

#include <array>
#include <cmath>
#include <cstdint>
#include <cstring>
#include <memory>
#include <vector>

namespace
{
constexpr auto stateRoot = "CorvusInstrumentState";
constexpr auto stateSchemaVersion = 1;
// CV-023: flight-derived FX settings are refreshed once per fixed sub-chunk
// instead of once per host block. 32 samples is ~0.73 ms at 44.1 kHz, so a
// modulated flight sweep ramps inside the block instead of stepping at the
// block boundary (the smoother itself still moves per sample).
constexpr int fxParameterChunkSize = 32;
// Measured peak emitted activity over the 8,192-sample 0.8-velocity Dawn
// Choir signature window.
constexpr float dawnTriadUnityActivity = 1.17023f;

// CV-087: bit-level finiteness test for the instrument output guard. The
// product targets compile with MSVC /fp:fast, where the compiler may assume
// every float is finite and fold an isfinite() test on a value produced by
// arithmetic to `true` - the guard would then be unreachable in the shipped
// binary while the source still reads as safe. Inspecting the IEEE-754
// exponent bits keeps the guard value-dependent; the answers are exactly
// std::isfinite's (NaN and both infinities false, everything else true), only
// the vehicle changes. Same test the FX processor's CV-082 helper uses.
inline bool isFiniteFloat(float value) noexcept
{
    static_assert(sizeof(float) == sizeof(std::uint32_t), "IEEE-754 float expected");

    std::uint32_t bits = 0;
    std::memcpy(&bits, &value, sizeof(bits));
    return (bits & 0x7f800000u) != 0x7f800000u;
}

// Marks multi-parameter writes so a publisher can discard any snapshot that
// overlaps a preset or state restore, even if the whole batch starts and ends
// while the snapshot is being collected. Odd values mean a batch is active.
class ParameterGenerationBatch final
{
public:
    explicit ParameterGenerationBatch(std::atomic<std::uint32_t>& sequence) noexcept
        : sequence(sequence)
    {
        sequence.fetch_add(1, std::memory_order_seq_cst);
    }

    ~ParameterGenerationBatch()
    {
        sequence.fetch_add(1, std::memory_order_seq_cst);
    }

private:
    std::atomic<std::uint32_t>& sequence;
};
}

struct CorvusInstrumentProcessor::EffectsCore
{
    ProfessionalDistortion distortion;
    EnhancedChorus chorus;
    EnhancedDelay delay;
    UpgradedReverb reverb;
    MasterOutputStage master;
};

CorvusInstrumentProcessor::CorvusInstrumentProcessor()
    : juce::AudioProcessor(BusesProperties()
          .withOutput("Output", juce::AudioChannelSet::stereo(), true)),
      apvts(*this, &undoManager, stateRoot, createParameterLayout()),
      effects(std::make_unique<EffectsCore>())
{
    for (const auto* id : { "osc_wave", "attack", "decay", "sustain", "release",
                            "fx_amount", "flight", "output" })
        apvts.addParameterListener(id, this);
    publishParameterGeneration();
    setCurrentProgram(0);
}

CorvusInstrumentProcessor::~CorvusInstrumentProcessor()
{
    for (const auto* id : { "osc_wave", "attack", "decay", "sustain", "release",
                            "fx_amount", "flight", "output" })
        apvts.removeParameterListener(id, this);
}

int CorvusInstrumentProcessor::getNumPrograms()
{
    return static_cast<int>(corvusInstrumentPresets.size());
}

int CorvusInstrumentProcessor::getCurrentProgram()
{
    return currentProgram.load(std::memory_order_relaxed);
}

void CorvusInstrumentProcessor::setCurrentProgram(int index)
{
    if (index < 0 || index >= getNumPrograms())
        return;

    const auto& preset = corvusInstrumentPresets[static_cast<std::size_t>(index)];
    auto setPhysicalValue = [this](const juce::String& parameterId, float value)
    {
        auto* parameter = apvts.getParameter(parameterId);
        if (parameter == nullptr)
            return;
        // CV-075: bracket every recalled value in its own begin/end gesture
        // pair, mirroring the FX recall and A/B pattern, so automation lanes
        // and the host's undo capture one coherent edit per parameter instead
        // of a silent jump. Only the recall path opens gestures; real-time
        // writes and per-block smoothing stay untouched.
        parameter->beginChangeGesture();
        try
        {
            parameter->setValueNotifyingHost(parameter->convertTo0to1(value));
        }
        catch (...)
        {
            parameter->endChangeGesture();
            throw;
        }
        parameter->endChangeGesture();
    };

    {
        ParameterGenerationBatch batch(presetBatchSequence);
        setPhysicalValue("osc_wave", static_cast<float>(preset.wave));
        setPhysicalValue("attack", preset.attack);
        setPhysicalValue("decay", preset.decay);
        setPhysicalValue("sustain", preset.sustain);
        setPhysicalValue("release", preset.release);
        setPhysicalValue("fx_amount", preset.fxAmount);
        setPhysicalValue("flight", preset.flight);
        setPhysicalValue("output", preset.outputDb);
        currentProgram.store(index, std::memory_order_relaxed);
    }
    publishParameterGeneration();
}

const juce::String CorvusInstrumentProcessor::getProgramName(int index)
{
    if (index < 0 || index >= getNumPrograms())
        return {};
    return corvusInstrumentPresets[static_cast<std::size_t>(index)].name;
}

void CorvusInstrumentProcessor::prepareToPlay(double sampleRate, int samplesPerBlock)
{
    synthEngine.prepare(sampleRate, samplesPerBlock);
    effects->distortion.prepare(sampleRate);
    effects->chorus.prepare(sampleRate);
    effects->delay.prepare(sampleRate);
    effects->reverb.prepare(sampleRate);
    effects->master.prepare(sampleRate);
    // CV-020: retained as prepare-time storage only. processBlock captures the
    // pristine synth output per sample, so no host block size (the prepared
    // size is only a hint) resizes this buffer inside the audio callback.
    dryBuffer.setSize(2, samplesPerBlock, false, false, true);

    fxAmount.reset(sampleRate, 0.03);
    fxAmount.setCurrentAndTargetValue(
        apvts.getRawParameterValue("fx_amount")->load());
    flightAmount.reset(sampleRate, 0.05);
    flightAmount.setCurrentAndTargetValue(
        apvts.getRawParameterValue("flight")->load());
    outputGain.reset(sampleRate, 0.02);
    const auto outputDb = apvts.getRawParameterValue("output")->load();
    const auto gain = juce::Decibels::decibelsToGain(outputDb);
    outputGain.setCurrentAndTargetValue(gain);
}

void CorvusInstrumentProcessor::releaseResources()
{
    synthEngine.panic();
}

bool CorvusInstrumentProcessor::isBusesLayoutSupported(const BusesLayout& layouts) const
{
    return layouts.getMainInputChannelSet().isDisabled()
        && layouts.getMainOutputChannelSet() == juce::AudioChannelSet::stereo();
}

InstrumentEffectsSettings
CorvusInstrumentProcessor::settingsForFlight(float flight) const noexcept
{
    const auto amount = juce::jlimit(0.0f, 1.0f, flight);
    InstrumentEffectsSettings settings;
    settings.distortionAmount = juce::jlimit(0.0f, 0.70f, 0.08f + amount * 0.42f);
    settings.chorusDepth = juce::jlimit(0.0f, 1.0f, 0.12f + amount * 0.48f);
    settings.chorusMix = juce::jlimit(0.0f, 1.0f, 0.10f + amount * 0.38f);
    settings.chorusRate = juce::jlimit(0.1f, 10.0f, 0.25f + amount * 1.10f);
    settings.delayTimeMs = juce::jlimit(1.0f, 900.0f, 90.0f + amount * 410.0f);
    settings.delayFeedback = juce::jlimit(0.0f, 0.75f, 0.12f + amount * 0.36f);
    settings.delayMix = juce::jlimit(0.0f, 0.65f, 0.06f + amount * 0.30f);
    settings.delayDamping = juce::jlimit(0.0f, 1.0f, 0.30f + amount * 0.25f);
    settings.delayModulation = juce::jlimit(0.0f, 1.0f, 0.04f + amount * 0.38f);
    settings.reverbSize = juce::jlimit(0.0f, 1.0f, 0.30f + amount * 0.62f);
    settings.reverbDamping = juce::jlimit(0.0f, 1.0f, 0.28f + amount * 0.30f);
    settings.reverbMix = juce::jlimit(0.0f, 0.80f, 0.10f + amount * 0.58f);
    settings.reverbModulation = juce::jlimit(0.0f, 1.0f, 0.05f + amount * 0.70f);
    settings.masterMidDrive = juce::jlimit(0.0f, 1.8f, 0.18f + amount * 0.92f);
    settings.masterSideDrive = juce::jlimit(0.0f, 1.8f, 0.12f + amount * 0.78f);
    settings.masterWidth = juce::jlimit(0.5f, 2.0f, 1.0f + amount * 0.50f);
    return settings;
}

void CorvusInstrumentProcessor::parameterChanged(const juce::String& parameterID,
                                                  float newValue)
{
    juce::ignoreUnused(parameterID, newValue);
    if ((presetBatchSequence.load(std::memory_order_seq_cst) & 1u) != 0)
    {
        generationDirty.store(true, std::memory_order_release);
        return;
    }
    publishParameterGeneration();
}

void CorvusInstrumentProcessor::publishParameterGeneration() noexcept
{
    // Audio-thread callbacks never wait for another writer. If a writer is
    // active, leave dirty set; processBlock retries before its next snapshot.
    if (generationWriter.test_and_set(std::memory_order_acquire))
    {
        generationDirty.store(true, std::memory_order_release);
        return;
    }

    // Consume an earlier notification only after owning the writer flag. Any
    // later contender leaves dirty set; never clear it after unlocking, where
    // doing so could steal a notification from the next writer.
    generationDirty.exchange(false, std::memory_order_acq_rel);
    const auto batchBefore = presetBatchSequence.load(std::memory_order_seq_cst);
    if ((batchBefore & 1u) != 0)
    {
        generationDirty.store(true, std::memory_order_release);
        generationWriter.clear(std::memory_order_release);
        return;
    }

    ParameterGeneration candidate;
    candidate.wave = apvts.getRawParameterValue("osc_wave")->load();
    candidate.attack = apvts.getRawParameterValue("attack")->load();
    candidate.decay = apvts.getRawParameterValue("decay")->load();
    candidate.sustain = apvts.getRawParameterValue("sustain")->load();
    candidate.release = apvts.getRawParameterValue("release")->load();
    candidate.fxAmount = apvts.getRawParameterValue("fx_amount")->load();
    candidate.flight = apvts.getRawParameterValue("flight")->load();
    candidate.output = apvts.getRawParameterValue("output")->load();
    candidate.programIndex = currentProgram.load(std::memory_order_relaxed);

    // A batch may have begun and ended during the reads, so checking only its
    // active/odd state is insufficient. Publish only if the even epoch matches.
    const auto batchAfter = presetBatchSequence.load(std::memory_order_seq_cst);
    if (batchBefore != batchAfter || (batchAfter & 1u) != 0)
    {
        generationDirty.store(true, std::memory_order_release);
        generationWriter.clear(std::memory_order_release);
        return;
    }

    // All payload atomics and sequence markers are sequentially consistent so
    // a reader that observes payload from this write cannot accept the old even
    // sequence on either side of it.
    generationSequence.fetch_add(1, std::memory_order_seq_cst); // odd: write in progress
    generationWave.store(candidate.wave, std::memory_order_seq_cst);
    generationAttack.store(candidate.attack, std::memory_order_seq_cst);
    generationDecay.store(candidate.decay, std::memory_order_seq_cst);
    generationSustain.store(candidate.sustain, std::memory_order_seq_cst);
    generationRelease.store(candidate.release, std::memory_order_seq_cst);
    generationFxAmount.store(candidate.fxAmount, std::memory_order_seq_cst);
    generationFlight.store(candidate.flight, std::memory_order_seq_cst);
    generationOutput.store(candidate.output, std::memory_order_seq_cst);
    generationProgramIndex.store(candidate.programIndex, std::memory_order_seq_cst);
    generationSequence.fetch_add(1, std::memory_order_seq_cst); // even: published
    generationWriter.clear(std::memory_order_release);
}

CorvusInstrumentProcessor::ParameterGeneration
CorvusInstrumentProcessor::readParameterGeneration(ParameterGeneration lastGood) const noexcept
{
    // Three attempts cap audio-thread work. Atomic payload fields avoid the C++
    // data race inherent in a plain-struct seqlock; sequence checks reject tears.
    for (int attempt = 0; attempt < 3; ++attempt)
    {
        const auto before = generationSequence.load(std::memory_order_seq_cst);
        if ((before & 1u) != 0)
            continue;
        ParameterGeneration candidate;
        candidate.wave = generationWave.load(std::memory_order_seq_cst);
        candidate.attack = generationAttack.load(std::memory_order_seq_cst);
        candidate.decay = generationDecay.load(std::memory_order_seq_cst);
        candidate.sustain = generationSustain.load(std::memory_order_seq_cst);
        candidate.release = generationRelease.load(std::memory_order_seq_cst);
        candidate.fxAmount = generationFxAmount.load(std::memory_order_seq_cst);
        candidate.flight = generationFlight.load(std::memory_order_seq_cst);
        candidate.output = generationOutput.load(std::memory_order_seq_cst);
        candidate.programIndex = generationProgramIndex.load(std::memory_order_seq_cst);
        const auto after = generationSequence.load(std::memory_order_seq_cst);
        if (before == after && (after & 1u) == 0)
            return candidate;
    }
    return lastGood;
}

VoiceParameters CorvusInstrumentProcessor::voiceParametersFor(
    const ParameterGeneration& generation) const noexcept
{
    VoiceParameters parameters;
    const auto waveIndex = juce::jlimit(0, 3, static_cast<int>(std::lround(generation.wave)));
    parameters.wave = static_cast<FactoryWave>(waveIndex);
    parameters.attackSeconds = generation.attack;
    parameters.decaySeconds = generation.decay;
    parameters.sustainLevel = generation.sustain;
    parameters.releaseSeconds = generation.release;
    return parameters;
}

void CorvusInstrumentProcessor::processBlock(juce::AudioBuffer<float>& buffer,
                                             juce::MidiBuffer& midi)
{
    juce::ScopedNoDenormals noDenormals;
    lastPreClampPeak = 0.0f;
    if (buffer.getNumChannels() < 2)
    {
        buffer.clear();
        return;
    }

    if (generationDirty.load(std::memory_order_acquire))
        publishParameterGeneration();
    lastGoodGeneration = readParameterGeneration(lastGoodGeneration);
    const auto& generation = lastGoodGeneration;
    const auto voiceParameters = voiceParametersFor(generation);
    if (generation.programIndex == 0)
        synthEngine.renderWithDawnActivityGain(
            buffer, midi, voiceParameters, dawnTriadUnityActivity);
    else
        synthEngine.render(buffer, midi, voiceParameters);
    for (auto channel = 2; channel < buffer.getNumChannels(); ++channel)
        buffer.clear(channel, 0, buffer.getNumSamples());

    fxAmount.setTargetValue(generation.fxAmount);
    flightAmount.setTargetValue(generation.flight);

    // CV-023: refresh the flight-derived FX settings once per fixed sub-chunk
    // (~0.73 ms at 44.1 kHz) instead of once per host block, so a modulated
    // flight sweep ramps inside the block rather than stepping at the block
    // boundary. `fxChunkRemaining` counts down to the next chunk head, so the
    // chunk lengths sum to exactly the block length and `flightAmount` is
    // advanced by exactly `buffer.getNumSamples()` per callback. Nothing else
    // about the loop changed: no allocation, no per-sample parameter read.
    auto fxChunkRemaining = 0;
    InstrumentEffectsSettings settings {};

    for (auto sample = 0; sample < buffer.getNumSamples(); ++sample)
    {
        // CV-020: capture the pristine synth-rendered channels once per sample,
        // before any effect or overwrite touches `buffer`. A scalar capture is
        // block-length independent, so a host block larger than the
        // prepareToPlay hint never resizes (allocates) a dry scratch buffer on
        // the audio thread. Both the DSP inputs and the dry/wet blend read
        // these same captures.
        const float dryLeft = buffer.getSample(0, sample);
        const float dryRight = buffer.getSample(1, sample);
        auto processedLeft = dryLeft;
        auto processedRight = dryRight;
        float nextLeft = 0.0f;
        float nextRight = 0.0f;

        if (fxChunkRemaining == 0)
        {
            fxChunkRemaining = juce::jmin(
                fxParameterChunkSize, buffer.getNumSamples() - sample);
            settings = settingsForFlight(flightAmount.getCurrentValue());
            flightAmount.skip(fxChunkRemaining);

            effects->distortion.beginBlock(settings.distortionAmount);
            effects->chorus.beginBlock(
                settings.chorusDepth, settings.chorusMix, settings.chorusRate);
            effects->delay.beginBlock(settings.delayDamping);
            effects->reverb.beginBlock(
                settings.reverbSize, settings.reverbDamping, settings.reverbMix,
                settings.reverbModulation, 1.0f, 5.0f + settings.reverbSize * 40.0f);
            effects->master.beginBlock();
        }
        --fxChunkRemaining;

        effects->distortion.process(
            processedLeft, processedRight, nextLeft, nextRight);
        processedLeft = nextLeft;
        processedRight = nextRight;

        processedLeft = effects->chorus.process(
            processedLeft, 0, settings.chorusRate, settings.chorusDepth,
            settings.chorusDepth * 0.25f);
        processedRight = effects->chorus.process(
            processedRight, 1, settings.chorusRate, settings.chorusDepth,
            settings.chorusDepth * 0.25f);
        effects->chorus.advanceWritePos();

        effects->delay.processSample(
            processedLeft, processedRight, nextLeft, nextRight,
            settings.delayTimeMs, settings.delayFeedback, settings.delayMix,
            0.35f, settings.delayModulation);
        processedLeft = nextLeft;
        processedRight = nextRight;

        effects->reverb.processSample(
            processedLeft, processedRight, nextLeft, nextRight);
        processedLeft = nextLeft;
        processedRight = nextRight;

        effects->master.process(
            processedLeft, processedRight, settings.masterMidDrive,
            settings.masterSideDrive, settings.masterWidth);

        const auto wet = fxAmount.getNextValue();
        const auto dry = 1.0f - wet;
        buffer.setSample(0, sample, dryLeft * dry + processedLeft * wet);
        buffer.setSample(1, sample, dryRight * dry + processedRight * wet);
    }

    outputGain.setTargetValue(juce::Decibels::decibelsToGain(generation.output));
    for (auto sample = 0; sample < buffer.getNumSamples(); ++sample)
    {
        const auto gain = outputGain.getNextValue();
        for (auto channel = 0; channel < 2; ++channel)
        {
            auto value = buffer.getSample(channel, sample) * gain;
            // CV-087: a non-finite sample must be contained before it reaches
            // the host, and the guard must be a bit test: /fp:fast folds
            // isfinite() on a value produced by arithmetic to `true`, which
            // leaves this containment unreachable in the shipped binary.
            if (!isFiniteFloat(value))
                value = 0.0f;
            lastPreClampPeak = juce::jmax(lastPreClampPeak, std::abs(value));
            buffer.setSample(channel, sample, juce::jlimit(-1.0f, 1.0f, value));
        }
    }
}

juce::AudioProcessorEditor* CorvusInstrumentProcessor::createEditor()
{
    return new CorvusInstrumentEditor(*this);
}

void CorvusInstrumentProcessor::getStateInformation(juce::MemoryBlock& destination)
{
    auto state = apvts.copyState();
    state.setProperty("schemaVersion", stateSchemaVersion, nullptr);
    state.setProperty("currentProgram",
                      currentProgram.load(std::memory_order_relaxed), nullptr);
    juce::MemoryOutputStream stream(destination, false);
    state.writeToStream(stream);
}

void CorvusInstrumentProcessor::setStateInformation(const void* data, int sizeInBytes)
{
    if (data == nullptr || sizeInBytes <= 0)
        return;

    const auto candidate = juce::ValueTree::readFromData(
        data, static_cast<std::size_t>(sizeInBytes));
    if (!candidate.isValid()
        || !candidate.hasType(stateRoot)
        || static_cast<int>(candidate.getProperty("schemaVersion", 0))
            != stateSchemaVersion)
        return;

    {
        ParameterGenerationBatch batch(presetBatchSequence);
        apvts.replaceState(candidate);

        // CV-023: a stale or corrupt program index must not discard a valid
        // parameter tree. Restore the index without loading a factory preset.
        const auto restoredProgram = static_cast<int>(candidate.getProperty("currentProgram", 0));
        if (restoredProgram >= 0 && restoredProgram < getNumPrograms())
            currentProgram.store(restoredProgram, std::memory_order_relaxed);
        else
            currentProgram.store(0, std::memory_order_relaxed);
    }
    publishParameterGeneration();
}

juce::AudioProcessorValueTreeState::ParameterLayout
CorvusInstrumentProcessor::createParameterLayout()
{
    std::vector<std::unique_ptr<juce::RangedAudioParameter>> parameters;
    parameters.push_back(std::make_unique<juce::AudioParameterChoice>(
        "osc_wave", "Oscillator Wave",
        juce::StringArray { "Sine", "Triangle", "Saw", "Square" }, 2));
    parameters.push_back(std::make_unique<juce::AudioParameterFloat>(
        "attack", "Attack", juce::NormalisableRange<float>(0.0f, 5.0f, 0.001f, 0.4f),
        0.05f));
    parameters.push_back(std::make_unique<juce::AudioParameterFloat>(
        "decay", "Decay", juce::NormalisableRange<float>(0.0f, 5.0f, 0.001f, 0.4f),
        0.35f));
    parameters.push_back(std::make_unique<juce::AudioParameterFloat>(
        "sustain", "Sustain", juce::NormalisableRange<float>(0.0f, 1.0f, 0.001f),
        0.75f));
    parameters.push_back(std::make_unique<juce::AudioParameterFloat>(
        "release", "Release", juce::NormalisableRange<float>(0.01f, 10.0f, 0.001f, 0.4f),
        1.5f));
    parameters.push_back(std::make_unique<juce::AudioParameterFloat>(
        "fx_amount", "FX Amount", juce::NormalisableRange<float>(0.0f, 1.0f, 0.001f),
        0.65f));
    parameters.push_back(std::make_unique<juce::AudioParameterFloat>(
        "flight", "Flight", juce::NormalisableRange<float>(0.0f, 1.0f, 0.001f),
        0.50f));
    parameters.push_back(std::make_unique<juce::AudioParameterFloat>(
        "output", "Output", juce::NormalisableRange<float>(-24.0f, 0.0f, 0.1f),
        -6.0f));
    return { parameters.begin(), parameters.end() };
}

juce::AudioProcessor* JUCE_CALLTYPE createPluginFilter()
{
    return new CorvusInstrumentProcessor();
}
