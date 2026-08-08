#pragma once

#include <JuceHeader.h>

#include <memory>

class CorvusInstrumentProcessor;

class CorvusInstrumentEditor final : public juce::AudioProcessorEditor
{
public:
    explicit CorvusInstrumentEditor(CorvusInstrumentProcessor& processor);
    ~CorvusInstrumentEditor() override = default;

    void resized() override;

private:
    std::unique_ptr<juce::GenericAudioProcessorEditor> genericEditor;

    JUCE_DECLARE_NON_COPYABLE_WITH_LEAK_DETECTOR(CorvusInstrumentEditor)
};
