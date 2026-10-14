#include <JuceHeader.h>
#include "PluginProcessor.h"
#include <cmath>
#include <iostream>
#include <memory>

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
