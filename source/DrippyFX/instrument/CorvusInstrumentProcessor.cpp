#include "CorvusInstrumentProcessor.h"
#include "CorvusInstrumentEditor.h"
#include "CorvusInstrumentPresets.h"
#include "../dsp/CorvusEffects.h"

#include <array>
#include <cmath>
#include <memory>
#include <vector>

namespace
{
constexpr auto stateRoot = "CorvusInstrumentState";
constexpr auto stateSchemaVersion = 1;
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
    setCurrentProgram(0);
}

CorvusInstrumentProcessor::~CorvusInstrumentProcessor() = default;

int CorvusInstrumentProcessor::getNumPrograms()
{
    return static_cast<int>(corvusInstrumentPresets.size());
}

int CorvusInstrumentProcessor::getCurrentProgram()
{
    return currentProgram;
}

void CorvusInstrumentProcessor::setCurrentProgram(int index)
{
    if (index < 0 || index >= getNumPrograms())
        return;

    const auto& preset = corvusInstrumentPresets[static_cast<std::size_t>(index)];
    auto setPhysicalValue = [this](const juce::String& parameterId, float value)
    {
        if (auto* parameter = apvts.getParameter(parameterId))
            parameter->setValueNotifyingHost(parameter->convertTo0to1(value));
    };

    setPhysicalValue("osc_wave", static_cast<float>(preset.wave));
    setPhysicalValue("attack", preset.attack);
    setPhysicalValue("decay", preset.decay);
    setPhysicalValue("sustain", preset.sustain);
    setPhysicalValue("release", preset.release);
    setPhysicalValue("fx_amount", preset.fxAmount);
    setPhysicalValue("flight", preset.flight);
    setPhysicalValue("output", preset.outputDb);
    currentProgram = index;
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

VoiceParameters CorvusInstrumentProcessor::currentVoiceParameters() const
{
    VoiceParameters parameters;
    const auto waveIndex = juce::jlimit(
        0, 3, static_cast<int>(std::lround(apvts.getRawParameterValue("osc_wave")->load())));
    parameters.wave = static_cast<FactoryWave>(waveIndex);
    parameters.attackSeconds = apvts.getRawParameterValue("attack")->load();
    parameters.decaySeconds = apvts.getRawParameterValue("decay")->load();
    parameters.sustainLevel = apvts.getRawParameterValue("sustain")->load();
    parameters.releaseSeconds = apvts.getRawParameterValue("release")->load();
    return parameters;
}

void CorvusInstrumentProcessor::processBlock(juce::AudioBuffer<float>& buffer,
                                             juce::MidiBuffer& midi)
{
    juce::ScopedNoDenormals noDenormals;
    if (buffer.getNumChannels() < 2)
    {
        buffer.clear();
        return;
    }

    synthEngine.render(buffer, midi, currentVoiceParameters());
    for (auto channel = 2; channel < buffer.getNumChannels(); ++channel)
        buffer.clear(channel, 0, buffer.getNumSamples());

    if (dryBuffer.getNumSamples() < buffer.getNumSamples())
        dryBuffer.setSize(2, buffer.getNumSamples(), false, false, true);
    for (auto channel = 0; channel < 2; ++channel)
        dryBuffer.copyFrom(channel, 0, buffer, channel, 0, buffer.getNumSamples());

    fxAmount.setTargetValue(apvts.getRawParameterValue("fx_amount")->load());
    flightAmount.setTargetValue(apvts.getRawParameterValue("flight")->load());
    const auto settings = settingsForFlight(flightAmount.getCurrentValue());
    flightAmount.skip(buffer.getNumSamples());

    effects->distortion.beginBlock(settings.distortionAmount);
    effects->chorus.beginBlock(
        settings.chorusDepth, settings.chorusMix, settings.chorusRate);
    effects->delay.beginBlock(settings.delayDamping);
    effects->reverb.beginBlock(
        settings.reverbSize, settings.reverbDamping, settings.reverbMix,
        settings.reverbModulation, 1.0f, 5.0f + settings.reverbSize * 40.0f);
    effects->master.beginBlock();

    for (auto sample = 0; sample < buffer.getNumSamples(); ++sample)
    {
        auto processedLeft = dryBuffer.getSample(0, sample);
        auto processedRight = dryBuffer.getSample(1, sample);
        float nextLeft = 0.0f;
        float nextRight = 0.0f;

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
        buffer.setSample(0, sample,
                         dryBuffer.getSample(0, sample) * dry + processedLeft * wet);
        buffer.setSample(1, sample,
                         dryBuffer.getSample(1, sample) * dry + processedRight * wet);
    }

    outputGain.setTargetValue(juce::Decibels::decibelsToGain(
        apvts.getRawParameterValue("output")->load()));
    for (auto sample = 0; sample < buffer.getNumSamples(); ++sample)
    {
        const auto gain = outputGain.getNextValue();
        for (auto channel = 0; channel < 2; ++channel)
        {
            auto value = buffer.getSample(channel, sample) * gain;
            if (!std::isfinite(value))
                value = 0.0f;
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
    state.setProperty("currentProgram", currentProgram, nullptr);
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

    const auto restoredProgram = static_cast<int>(candidate.getProperty("currentProgram", 0));
    if (restoredProgram < 0 || restoredProgram >= getNumPrograms())
        return;

    apvts.replaceState(candidate);
    currentProgram = restoredProgram;
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
