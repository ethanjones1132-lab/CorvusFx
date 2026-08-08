#include "CorvusInstrumentEditor.h"
#include "CorvusInstrumentProcessor.h"

CorvusInstrumentEditor::CorvusInstrumentEditor(CorvusInstrumentProcessor& processor)
    : juce::AudioProcessorEditor(&processor),
      genericEditor(std::make_unique<juce::GenericAudioProcessorEditor>(processor))
{
    addAndMakeVisible(*genericEditor);
    setResizable(true, true);
    setSize(520, 520);
}

void CorvusInstrumentEditor::resized()
{
    genericEditor->setBounds(getLocalBounds());
}
