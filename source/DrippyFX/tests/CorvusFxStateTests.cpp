#include <JuceHeader.h>
#include "PluginProcessor.h"
#include <algorithm>
#include <array>
#include <cmath>
#include <iostream>
#include <limits>
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

//==============================================================================
// REVERB TAIL AUDIO (CV-039)
// The modulated-delay history repair must be audible as a repaired reverb tail,
// not hidden by the final limiter, a clamp or a gain change. These long-running
// regressions render the real CorvusFXAudioProcessor through the public
// programs whose published presets drive the reverb modulation hardest:
// 13 = "Cosmic Wide" (reverb_mod 85%, reverb_size 80%, delay 160 ms) and
// 21 = "Event Horizon" (reverb_mod 90%, reverb_size 95%, delay 800 ms with 65%
// feedback). Both signs of the signed comb/allpass modulation therefore run
// through the longest published tails with continuously non-silent input.
//==============================================================================
class CorvusFxReverbAudioTest final : public juce::UnitTest
{
public:
    CorvusFxReverbAudioTest() : juce::UnitTest("Corvus FX reverb audio") {}

    void runTest() override
    {
        const std::array<int, 2> programs { 13, 21 };
        const std::array<const char*, 2> programNames { "Cosmic Wide", "Event Horizon" };
        // The published reverb modulation / size / delay feedback of programs
        // 13 and 21 (parameter values in their native percent units).
        const std::array<float, 2> expectedReverbMod { 85.0f, 90.0f };
        const std::array<float, 2> expectedReverbSize { 80.0f, 95.0f };
        const std::array<float, 2> expectedDelayFeedback { 25.0f, 65.0f };

        beginTest("deterministic drive input is continuously non-silent and bounded");
        expectInputIsContinuous();

        for (std::size_t index = 0; index < programs.size(); ++index)
        {
            const auto program = programs[index];
            const juce::String name = programNames[index];

            beginTest("program " + juce::String(program) + " (" + name
                      + ") keeps a finite, unrailed, audible tail");

            auto processor = std::make_unique<CorvusFXAudioProcessor>();
            expectEquals(processor->getNumPrograms(), 36);
            processor->setCurrentProgram(program);
            expectEquals(processor->getCurrentProgram(), program);
            expect(processor->getProgramName(program) == name,
                   "public program " + juce::String(program) + " must be \"" + name + "\"");
            // Apply the published preset through its public entry point as well,
            // so the render never depends on the order in which a host-visible
            // program change is fanned out to the parameter listeners.
            processor->loadPreset(program);
            expectWithinAbsoluteError(
                processor->apvts.getRawParameterValue("reverb_mod")->load(),
                expectedReverbMod[index], 1.0e-3f);
            expectWithinAbsoluteError(
                processor->apvts.getRawParameterValue("reverb_size")->load(),
                expectedReverbSize[index], 1.0e-3f);
            expectWithinAbsoluteError(
                processor->apvts.getRawParameterValue("delay_feedback")->load(),
                expectedDelayFeedback[index], 1.0e-3f);
            processor->prepareToPlay(sampleRate, blockSize);

            const auto rendered = renderProgram(*processor);
            expectBoundedLiveOutput(rendered, name);

            // Modulation must still move the tail: the same public program with
            // reverb_mod at 0 has to render a different signal.
            auto unmodulated = std::make_unique<CorvusFXAudioProcessor>();
            unmodulated->setCurrentProgram(program);
            unmodulated->loadPreset(program);
            unmodulated->apvts.getParameter("reverb_mod")->setValueNotifyingHost(0.0f);
            unmodulated->prepareToPlay(sampleRate, blockSize);
            const auto unmodulatedRender = renderProgram(*unmodulated);

            auto differenceEnergy = 0.0;
            for (std::size_t sample = 0; sample < rendered.left.size(); ++sample)
            {
                const auto differenceLeft = static_cast<double>(rendered.left[sample])
                                          - static_cast<double>(unmodulatedRender.left[sample]);
                const auto differenceRight = static_cast<double>(rendered.right[sample])
                                           - static_cast<double>(unmodulatedRender.right[sample]);
                differenceEnergy += differenceLeft * differenceLeft
                                  + differenceRight * differenceRight;
            }
            const auto differenceRms = std::sqrt(
                differenceEnergy / (2.0 * static_cast<double>(rendered.left.size())));
            expect(differenceRms > 1.0e-4,
                   name + ": reverb modulation must still change the tail (difference RMS "
                       + juce::String(differenceRms, 6) + ")");

            // The tail assertions above are only meaningful if this program
            // renders deterministically from the same public state and input.
            auto repeat = std::make_unique<CorvusFXAudioProcessor>();
            repeat->setCurrentProgram(program);
            repeat->loadPreset(program);
            repeat->prepareToPlay(sampleRate, blockSize);
            const auto repeated = renderProgram(*repeat);
            expect(repeated.left == rendered.left && repeated.right == rendered.right,
                   name + ": the same public program and input must render bit-for-bit");
        }
    }

private:
    static constexpr double sampleRate = 48000.0;
    static constexpr int blockSize = 512;
    static constexpr int toneSamples = 6 * 48000;     // 6 s of continuous drive
    static constexpr int silenceSamples = 2 * 48000;  // 2 s of released tail

    struct ProgramRender
    {
        std::vector<float> left;
        std::vector<float> right;
    };

    // Deterministic, always-on, bounded stereo drive: three incommensurate
    // partials per channel, peak 0.30, so every block carries signal.
    static float testInput(int channel, juce::int64 position)
    {
        const auto twoPi = juce::MathConstants<double>::twoPi;
        const auto t = static_cast<double>(position) / sampleRate;
        if (channel == 0)
            return 0.18f * static_cast<float>(std::sin(twoPi * 173.0 * t))
                 + 0.083f * static_cast<float>(std::sin(twoPi * 311.7 * t + 0.7))
                 + 0.038f * static_cast<float>(std::sin(twoPi * 47.3 * t + 1.9));
        return 0.165f * static_cast<float>(std::sin(twoPi * 181.3 * t + 0.4))
             + 0.090f * static_cast<float>(std::sin(twoPi * 293.1 * t + 1.1))
             + 0.045f * static_cast<float>(std::sin(twoPi * 53.9 * t + 2.6));
    }

    static ProgramRender renderProgram(CorvusFXAudioProcessor& processor)
    {
        ProgramRender rendered;
        const auto total = toneSamples + silenceSamples;
        rendered.left.assign(static_cast<std::size_t>(total), 0.0f);
        rendered.right.assign(static_cast<std::size_t>(total), 0.0f);

        juce::AudioBuffer<float> buffer(2, blockSize);
        juce::MidiBuffer midi;
        for (int start = 0; start < total; start += blockSize)
        {
            const auto samples = std::min(blockSize, total - start);
            buffer.setSize(2, samples, false, false, true);
            for (int i = 0; i < samples; ++i)
            {
                const auto position = start + i;
                const auto live = position < toneSamples;
                buffer.setSample(0, i, live ? testInput(0, position) : 0.0f);
                buffer.setSample(1, i, live ? testInput(1, position) : 0.0f);
            }
            processor.processBlock(buffer, midi);
            for (int i = 0; i < samples; ++i)
            {
                rendered.left[static_cast<std::size_t>(start + i)] =
                    buffer.getSample(0, i);
                rendered.right[static_cast<std::size_t>(start + i)] =
                    buffer.getSample(1, i);
            }
        }
        return rendered;
    }

    void expectInputIsContinuous()
    {
        auto peak = 0.0f;
        auto quietestBlockRms = std::numeric_limits<double>::max();
        for (int start = 0; start < toneSamples; start += blockSize)
        {
            auto energy = 0.0;
            for (int i = 0; i < blockSize; ++i)
            {
                const auto left = testInput(0, start + i);
                const auto right = testInput(1, start + i);
                energy += static_cast<double>(left) * static_cast<double>(left)
                        + static_cast<double>(right) * static_cast<double>(right);
                peak = std::max(peak, std::max(std::abs(left), std::abs(right)));
            }
            quietestBlockRms = std::min(quietestBlockRms,
                                        std::sqrt(energy / (2.0 * blockSize)));
        }
        expect(quietestBlockRms > 0.02,
               "every drive block must carry signal (quietest RMS "
                   + juce::String(quietestBlockRms, 6) + ")");
        expect(peak > 0.1f && peak <= 0.35f,
               "the drive must stay bounded below full scale (peak "
                   + juce::String(peak, 6) + ")");
    }

    void expectBoundedLiveOutput(const ProgramRender& rendered, const juce::String& name)
    {
        auto peak = 0.0f;
        auto railSamples = 0;
        auto fullScaleSamples = 0;
        auto nonFinite = 0;
        auto longestSilence = 0;
        auto silentRun = 0;
        for (std::size_t sample = 0; sample < rendered.left.size(); ++sample)
        {
            const auto left = rendered.left[sample];
            const auto right = rendered.right[sample];
            if (!std::isfinite(left) || !std::isfinite(right))
                ++nonFinite;
            peak = std::max(peak, std::max(std::abs(left), std::abs(right)));
            if (std::abs(left) >= 0.99f || std::abs(right) >= 0.99f)
                ++railSamples;
            if (std::abs(left) >= 1.0f || std::abs(right) >= 1.0f)
                ++fullScaleSamples;
            // A silent latch only counts while the drive is present; a released
            // tail is allowed to decay to exact zero at the end of the run.
            if (sample < static_cast<std::size_t>(toneSamples)
                && std::abs(left) < 1.0e-6f && std::abs(right) < 1.0e-6f)
            {
                ++silentRun;
                longestSilence = std::max(longestSilence, silentRun);
            }
            else
                silentRun = 0;
        }
        expect(nonFinite == 0, name + ": output must stay finite");
        expect(peak > 0.02f, name + ": the chain must produce audible output (peak "
                                + juce::String(peak, 6) + ")");
        // Product soft clip starts at 1.0 and the hard clamp is ±1.5
        // (padeSoftClip threshold, then jlimit). Unity output trim does not
        // pull a legal over back under 1. Sol's latch was peak 1.181579 and
        // 699855/720000 samples above full scale, plus a silence latch on
        // program 21. A hot preset may kiss full scale; it may not sit there.
        // 5% of this render is 19200 samples. Measured 2026-11-02 Windows
        // x64 Release: Cosmic Wide 47/384000, Event Horizon 2268/384000.
        const auto fullScaleLimit = static_cast<int>(rendered.left.size() / 20);
        expect(peak < 1.05f, name + ": output must not latch onto the limiter rail (peak "
                                 + juce::String(peak, 6)
                                 + " ge0.99=" + juce::String(railSamples)
                                 + " ge1=" + juce::String(fullScaleSamples)
                                 + "/" + juce::String(static_cast<int>(rendered.left.size())) + ")");
        expect(fullScaleSamples < fullScaleLimit,
               name + ": full-scale samples must stay rare (ge1="
                   + juce::String(fullScaleSamples) + " limit="
                   + juce::String(fullScaleLimit) + ")");
        expect(longestSilence < 2048,
               name + ": output must not silently latch (longest silent run "
                   + juce::String(longestSilence) + ")");

        const auto lastSecondStart = static_cast<std::size_t>(toneSamples - 48000);
        auto toneEnergy = 0.0;
        for (auto sample = lastSecondStart;
             sample < static_cast<std::size_t>(toneSamples); ++sample)
        {
            toneEnergy += static_cast<double>(rendered.left[sample])
                        * static_cast<double>(rendered.left[sample]);
            toneEnergy += static_cast<double>(rendered.right[sample])
                        * static_cast<double>(rendered.right[sample]);
        }
        const auto toneRms = std::sqrt(toneEnergy / (2.0 * 48000.0));
        expect(toneRms > 0.01 && toneRms < 0.5,
               name + ": the last second of drive must stay at a sensible level (RMS "
                   + juce::String(toneRms, 6) + ")");

        auto tailEnergy = 0.0;
        for (auto sample = static_cast<std::size_t>(toneSamples);
             sample < rendered.left.size(); ++sample)
        {
            tailEnergy += static_cast<double>(rendered.left[sample])
                        * static_cast<double>(rendered.left[sample]);
            tailEnergy += static_cast<double>(rendered.right[sample])
                        * static_cast<double>(rendered.right[sample]);
        }
        const auto tailRms = std::sqrt(tailEnergy / (2.0 * silenceSamples));
        expect(tailRms > 0.001,
               name + ": the released tail must stay audible after the input stops (RMS "
                   + juce::String(tailRms, 6) + ")");
    }
};

CorvusFxStateTest corvusFxStateTest;
CorvusFxReverbAudioTest corvusFxReverbAudioTest;
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
        {
            failures += result->failures;
            // The GUI logger swallows UnitTestRunner::logMessage on Windows,
            // so a console run would otherwise print only this total.
            for (const auto& message : result->messages)
                std::cout << message << '\n';
        }
    std::cout << "Corvus FX state tests: " << failures << " failure(s)\n";
    return failures == 0 ? 0 : 1;
}
