#include <JuceHeader.h>
#include "PluginProcessor.h"
#include <algorithm>
#include <cmath>
#include <iostream>
#include <memory>
#include <vector>

namespace
{
class CorvusFxStateTest final : public juce::UnitTest
{
public:
    CorvusFxStateTest() : juce::UnitTest("Corvus FX session state") {}

    void runTest() override
    {
        const auto setFatness = [](CorvusFXAudioProcessor& processor, float value)
        {
            processor.apvts.getParameter("fatness")->setValueNotifyingHost(value);
        };
        const auto getFatness = [](CorvusFXAudioProcessor& processor)
        {
            return processor.apvts.getParameter("fatness")->getValue();
        };

        beginTest("overall dry and all-module bypass preserve steady-state input");
        for (const auto moduleBypass : { false, true })
        {
            auto processor = std::make_unique<CorvusFXAudioProcessor>();
            processor->apvts.getParameter("overall")->setValueNotifyingHost(moduleBypass ? 1.0f : 0.0f);
            for (const auto* id : { "distortion_bypass", "chorus_bypass", "delay_bypass", "reverb_bypass", "master_bypass" })
                processor->apvts.getParameter(id)->setValueNotifyingHost(moduleBypass ? 1.0f : 0.0f);
            processor->prepareToPlay(48000.0, 128);
            juce::AudioBuffer<float> tone(2, 128);
            juce::MidiBuffer noMidi;
            for (auto block = 0; block < 16; ++block)
            {
                for (auto sample = 0; sample < 128; ++sample)
                {
                    const auto input = 0.1f * std::sin(static_cast<float>(block * 128 + sample) * 0.0576f);
                    tone.setSample(0, sample, input);
                    tone.setSample(1, sample, input * 0.5f);
                }
                processor->processBlock(tone, noMidi);
            }
            for (auto sample = 0; sample < 128; ++sample)
            {
                const auto input = 0.1f * std::sin(static_cast<float>(15 * 128 + sample) * 0.0576f);
                expectWithinAbsoluteError(tone.getSample(0, sample), input, 0.000001f);
                expectWithinAbsoluteError(tone.getSample(1, sample), input * 0.5f, 0.000001f);
            }
        }

        {
            beginTest("dry feed and wet output stay block-size invariant after a 128-sample prepare");

            // 8193 is larger than the 128-sample prepare hint: the removed
            // dryBuffer guard used to resize (allocate) on exactly this path.
            const auto blockSizes = { 1, 17, 64, 128, 129, 1024, 8193 };
            const auto testInput = [](int channel, int sample)
            {
                const auto phase = static_cast<float>(sample);
                const auto left = 0.35f * std::sin(phase * 0.037f)
                                + 0.15f * std::sin(phase * 0.113f);
                if (channel == 0)
                    return left;
                return 0.45f * std::sin(phase * 0.071f + 0.4f)
                     + 0.05f * std::cos(phase * 0.019f);
            };
            const auto render = [&testInput](CorvusFXAudioProcessor& processor,
                                             int channels, int blockSize,
                                             int totalSamples)
            {
                std::vector<float> output(
                    static_cast<size_t>(channels * totalSamples), 0.0f);
                juce::AudioBuffer<float> buffer(channels, blockSize);
                juce::MidiBuffer noMidi;
                for (int start = 0; start < totalSamples; start += blockSize)
                {
                    const auto samples = std::min(blockSize, totalSamples - start);
                    buffer.setSize(channels, samples, false, false, true);
                    for (int ch = 0; ch < channels; ++ch)
                        for (int i = 0; i < samples; ++i)
                            buffer.setSample(ch, i, testInput(ch, start + i));
                    processor.processBlock(buffer, noMidi);
                    for (int ch = 0; ch < channels; ++ch)
                        for (int i = 0; i < samples; ++i)
                            output[static_cast<size_t>(ch * totalSamples + start + i)] =
                                buffer.getSample(ch, i);
                }
                return output;
            };
            const auto configureWet = [](CorvusFXAudioProcessor& processor)
            {
                const auto set = [&processor](const char* id, float value)
                {
                    processor.apvts.getParameter(id)->setValueNotifyingHost(value);
                };
                set("overall", 1.0f);
                set("fatness", 0.45f);
                set("chorus_depth", 0.6f);
                set("chorus_rate", 0.4f);
                set("chorus_mix", 0.5f);
                set("delay_time", 0.3f);
                set("delay_feedback", 0.35f);
                set("delay_mix", 0.4f);
                set("delay_damping", 0.5f);
                set("delay_mod", 0.3f);
                set("reverb_size", 0.5f);
                set("reverb_damping", 0.4f);
                set("reverb_mix", 0.3f);
                set("reverb_mod", 0.2f);
                set("master_drive", 0.4f);
                set("master_width", 0.6f);
                set("master_mid_drive", 0.3f);
                set("master_side_drive", 0.2f);
                set("output_trim", 0.8f);
                processor.prepareToPlay(48000.0, 128);
            };

            const int totalSamples = 16384;
            const auto expectedPeak = [&testInput](int channel, int count)
            {
                float peak = 0.0f;
                for (int i = 0; i < count; ++i)
                    peak = std::max(peak, std::abs(testInput(channel, i)));
                return peak;
            };
            const float inputPeakL = expectedPeak(0, totalSamples);
            const float inputPeakR = expectedPeak(1, totalSamples);
            for (const auto channels : { 1, 2 })
            {
                // overall=0 dry, then all-module bypass with overall=1: both
                // must reproduce the untouched input at any host block size.
                // The bypass path still passes the safety limiter (identity
                // below 1.0 for this input) and the output-trim ramp, which
                // settles after the 20 ms parameter-smoothing window (960
                // samples at 48 kHz); skip a 2048-sample margin so the test
                // asserts pristine-bypass preservation, not the startup ramp.
                constexpr int bypassSettleSamples = 2048;
                for (const auto allBypass : { false, true })
                {
                    for (const auto blockSize : blockSizes)
                    {
                        auto processor = std::make_unique<CorvusFXAudioProcessor>();
                        processor->apvts.getParameter("overall")->setValueNotifyingHost(
                            allBypass ? 1.0f : 0.0f);
                        for (const auto* id : { "distortion_bypass", "chorus_bypass",
                                                "delay_bypass", "reverb_bypass",
                                                "master_bypass" })
                            processor->apvts.getParameter(id)->setValueNotifyingHost(
                                allBypass ? 1.0f : 0.0f);
                        processor->prepareToPlay(48000.0, 128);
                        const auto actual = render(*processor, channels, blockSize,
                                                   totalSamples);
                        expectWithinAbsoluteError(
                            processor->levelMeters.inPeakL.load(), inputPeakL,
                            0.000001f);
                        if (channels == 2)
                            expectWithinAbsoluteError(
                                processor->levelMeters.inPeakR.load(), inputPeakR,
                                0.000001f);
                        const int compareFrom = allBypass ? bypassSettleSamples : 0;
                        for (int ch = 0; ch < channels; ++ch)
                        {
                            float maxDifference = 0.0f;
                            for (int i = compareFrom; i < totalSamples; ++i)
                                maxDifference = std::max(
                                    maxDifference,
                                    std::abs(actual[static_cast<size_t>(
                                                 ch * totalSamples + i)]
                                             - testInput(ch, i)));
                            expectWithinAbsoluteError(maxDifference, 0.0f, 0.000001f);
                        }
                    }
                }

                // Same continuous input through a fully wet chain must match
                // the 128-sample rendering regardless of block boundaries.
                auto referenceProcessor = std::make_unique<CorvusFXAudioProcessor>();
                configureWet(*referenceProcessor);
                const auto reference = render(*referenceProcessor, channels, 128,
                                              totalSamples);
                for (const auto blockSize : blockSizes)
                {
                    auto processor = std::make_unique<CorvusFXAudioProcessor>();
                    configureWet(*processor);
                    const auto actual = render(*processor, channels, blockSize,
                                               totalSamples);
                    expectWithinAbsoluteError(
                        processor->levelMeters.inPeakL.load(), inputPeakL,
                        0.000001f);
                    if (channels == 2)
                        expectWithinAbsoluteError(
                            processor->levelMeters.inPeakR.load(), inputPeakR,
                            0.000001f);
                    for (int ch = 0; ch < channels; ++ch)
                    {
                        float maxDifference = 0.0f;
                        for (int i = 0; i < totalSamples; ++i)
                        {
                            const auto index = static_cast<size_t>(
                                ch * totalSamples + i);
                            maxDifference = std::max(
                                maxDifference, std::abs(actual[index] - reference[index]));
                        }
                        expectWithinAbsoluteError(maxDifference, 0.0f, 0.000001f);
                    }
                }
            }
        }

        beginTest("distinct A/B slots and active slot survive binary session recall");
        auto original = std::make_unique<CorvusFXAudioProcessor>();
        setFatness(*original, 0.2f);
        original->saveSlotA();
        setFatness(*original, 0.8f);
        original->saveSlotB();
        original->loadSlotB();
        original->setParameterLocked("fatness", true);
        original->startMidiLearn("chorus_depth");
        original->prepareToPlay(48000.0, 128);
        juce::AudioBuffer<float> buffer(2, 128);
        buffer.clear();
        juce::MidiBuffer midi;
        midi.addEvent(juce::MidiMessage::controllerEvent(1, 21, 64), 0);
        original->processBlock(buffer, midi);
        juce::MemoryBlock saved;
        original->getStateInformation(saved);
        expect(saved.getSize() > 0);

        auto restored = std::make_unique<CorvusFXAudioProcessor>();
        restored->setStateInformation(saved.getData(), static_cast<int>(saved.getSize()));
        expect(restored->hasPersistedABSnapshots());
        expect(!restored->isSlotA());
        expect(restored->isParameterLocked("fatness"));
        expect(restored->hasMidiMapping("chorus_depth"));
        restored->loadSlotA();
        expectWithinAbsoluteError(getFatness(*restored), 0.2f, 0.0001f);
        restored->loadSlotB();
        expectWithinAbsoluteError(getFatness(*restored), 0.8f, 0.0001f);

        beginTest("editor reflects a recalled B slot without reseeding snapshots");
        {
            std::unique_ptr<juce::AudioProcessorEditor> editor(restored->createEditor());
            bool foundA = false, foundB = false;
            for (auto* child : editor->getChildren())
                if (auto* button = dynamic_cast<juce::TextButton*>(child))
                {
                    if (button->getButtonText() == "A") { foundA = true; expect(!button->getToggleState()); }
                    if (button->getButtonText() == "B") { foundB = true; expect(button->getToggleState()); }
                }
            expect(foundA && foundB);
        }
        restored->loadSlotA();
        expectWithinAbsoluteError(getFatness(*restored), 0.2f, 0.0001f);
        restored->loadSlotB();
        expectWithinAbsoluteError(getFatness(*restored), 0.8f, 0.0001f);

        beginTest("save-recall-edit-save-recall restores latest slots, maps, and locks");
        setFatness(*restored, 0.4f);
        restored->saveSlotA();
        setFatness(*restored, 0.6f);
        restored->saveSlotB();
        restored->loadSlotA();
        restored->setParameterLocked("fatness", false);
        restored->clearAllMidiMappings();
        restored->startMidiLearn("delay_mix");
        restored->prepareToPlay(48000.0, 128);
        buffer.clear();
        midi.clear();
        midi.addEvent(juce::MidiMessage::controllerEvent(1, 22, 64), 0);
        restored->processBlock(buffer, midi);
        juce::MemoryBlock secondSave;
        restored->getStateInformation(secondSave);
        auto latest = std::make_unique<CorvusFXAudioProcessor>();
        latest->setStateInformation(secondSave.getData(), static_cast<int>(secondSave.getSize()));
        expect(latest->hasPersistedABSnapshots());
        expect(latest->isSlotA());
        expect(!latest->isParameterLocked("fatness"));
        expect(!latest->hasMidiMapping("chorus_depth"));
        expect(latest->hasMidiMapping("delay_mix"));
        latest->loadSlotA();
        expectWithinAbsoluteError(getFatness(*latest), 0.4f, 0.0001f);
        latest->loadSlotB();
        expectWithinAbsoluteError(getFatness(*latest), 0.6f, 0.0001f);
        for (const auto* tag : { "abSlots", "midiMaps", "paramLocks" })
            expect(!latest->apvts.state.getChildWithName(tag).isValid(),
                   "transport metadata must not enter the parameter ValueTree");

        beginTest("malformed or partial snapshots cannot enable a persisted pair");
        auto xml = juce::AudioProcessor::getXmlFromBinary(saved.getData(), static_cast<int>(saved.getSize()));
        expect(xml != nullptr);
        if (!xml) return;
        auto* slots = xml->getChildByName("abSlots");
        expect(slots != nullptr);
        if (!slots) return;
        auto* snapshotB = slots->getChildByName("snapshotB");
        expect(snapshotB != nullptr);
        if (!snapshotB) return;
        slots->removeChildElement(snapshotB, true);
        juce::MemoryBlock partial;
        juce::AudioProcessor::copyXmlToBinary(*xml, partial);
        restored->setStateInformation(partial.getData(), static_cast<int>(partial.getSize()));
        expect(!restored->hasPersistedABSnapshots());

        beginTest("legacy sessions clear stale MIDI mappings and retain schema compatibility");
        xml->removeChildElement(slots, true);
        if (auto* maps = xml->getChildByName("midiMaps"))
            xml->removeChildElement(maps, true);
        xml->removeAttribute("schemaVersion");
        juce::MemoryBlock legacy;
        juce::AudioProcessor::copyXmlToBinary(*xml, legacy);
        restored->setStateInformation(legacy.getData(), static_cast<int>(legacy.getSize()));
        expect(!restored->hasPersistedABSnapshots());
        expect(restored->getMidiMappings().empty());

        beginTest("unsupported schema leaves current parameters unchanged");
        setFatness(*restored, 0.35f);
        xml->setAttribute("schemaVersion", 999);
        juce::MemoryBlock unsupported;
        juce::AudioProcessor::copyXmlToBinary(*xml, unsupported);
        restored->setStateInformation(unsupported.getData(), static_cast<int>(unsupported.getSize()));
        expectWithinAbsoluteError(getFatness(*restored), 0.35f, 0.0001f);
    }
};
CorvusFxStateTest corvusFxStateTest;
}

int main()
{
    juce::ScopedJuceInitialiser_GUI initialiseJuce;
    juce::UnitTestRunner runner;
    runner.setAssertOnFailure(false);
    runner.runAllTests(0xC0FFEE);
    auto failures = 0;
    for (auto index = 0; index < runner.getNumResults(); ++index)
        if (const auto* result = runner.getResult(index))
            failures += result->failures;
    std::cout << "Corvus FX state tests: " << failures << " failure(s)\n";
    return failures == 0 ? 0 : 1;
}
