#include "CorvusInstrumentProcessor.h"
#include "CorvusInstrumentEditor.h"

#include <array>
#include <cmath>
#include <memory>
#include <vector>

namespace
{
constexpr auto stateRoot = "CorvusInstrumentState";
constexpr auto stateSchemaVersion = 1;
}

CorvusInstrumentProcessor::CorvusInstrumentProcessor()
    : juce::AudioProcessor(BusesProperties()
          .withOutput("Output", juce::AudioChannelSet::stereo(), true)),
      apvts(*this, &undoManager, stateRoot, createParameterLayout())
{
}

void CorvusInstrumentProcessor::prepareToPlay(double sampleRate, int samplesPerBlock)
{
    synthEngine.prepare(sampleRate, samplesPerBlock);
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

    apvts.replaceState(candidate);
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
