#include "PluginProcessor.h"
#include "PluginEditor.h"

#include <initializer_list>
#include <utility>

CorvusFXAudioProcessorEditor::CorvusFXAudioProcessorEditor(CorvusFXAudioProcessor& p)
    : AudioProcessorEditor(&p), audioProcessor(p),
    distortionSection("DISTORTION", juce::Colour(0xffff6b35)),
    chorusSection("CHORUS", juce::Colour(0xff4ecdc4)),
    delaySection("DELAY", juce::Colour(0xfff7b731)),
    reverbSection("REVERB", juce::Colour(0xffb366ff))
{
    setLookAndFeel(&corvusLookAndFeel);
    {
        juce::PropertiesFile::Options opts;
        opts.applicationName = "CorvusFX";
        opts.filenameSuffix = ".settings";
        opts.osxLibrarySubFolder = "Application Support";
        opts.commonToAllUsers = false;
        themeProperties = std::make_unique<juce::PropertiesFile>(opts);
        if (themeProperties)
            themeDark = themeProperties->getBoolValue("themeDark", true);
        corvusLookAndFeel.setDarkTheme(themeDark);
    }
    setSize(1200, 700);
    setResizable(true, true);
    setResizeLimits(1000, 600, 1600, 900);
    setWantsKeyboardFocus(true);

    addAndMakeVisible(animatedBackground);
    animatedBackground.toBack();
    animatedBackground.setDarkTheme(themeDark);
    distortionSection.setDarkTheme(themeDark);
    chorusSection.setDarkTheme(themeDark);
    delaySection.setDarkTheme(themeDark);
    reverbSection.setDarkTheme(themeDark);

    titleLabel.setText("CORVUS FX", juce::dontSendNotification);
    titleLabel.setFont(juce::Font(juce::FontOptions(52.0f, juce::Font::bold)));
    titleLabel.setJustificationType(juce::Justification::centred);
    titleLabel.setColour(juce::Label::textColourId, juce::Colour(0xffb366ff));
    addAndMakeVisible(titleLabel);

    presetLabel.setText("PRESET", juce::dontSendNotification);
    presetLabel.setFont(juce::Font(juce::FontOptions(12.0f, juce::Font::bold)));
    presetLabel.setJustificationType(juce::Justification::centred);
    presetLabel.setColour(juce::Label::textColourId, juce::Colour(0xff888899));
    addAndMakeVisible(presetLabel);

    // Factory preset categorization: grouped by vibe with disabled separator items
    // Category 1: CLEAN ÃƒÆ’Ã†â€™Ãƒâ€ Ã¢â‚¬â„¢ÃƒÆ’Ã¢â‚¬Å¡Ãƒâ€šÃ‚Â¢ÃƒÆ’Ã†â€™Ãƒâ€šÃ‚Â¢ÃƒÆ’Ã‚Â¢ÃƒÂ¢Ã¢â‚¬Å¡Ã‚Â¬Ãƒâ€¦Ã‚Â¡ÃƒÆ’Ã¢â‚¬Å¡Ãƒâ€šÃ‚Â¬ÃƒÆ’Ã†â€™Ãƒâ€šÃ‚Â¢ÃƒÆ’Ã‚Â¢ÃƒÂ¢Ã¢â€šÂ¬Ã…Â¡Ãƒâ€šÃ‚Â¬ÃƒÆ’Ã¢â‚¬Å¡Ãƒâ€šÃ‚Â transparent enhancement, pristine highs (6 presets)
    presetSelector.addItem("--- CLEAN ---", 1);   presetSelector.setItemEnabled(1, false);
    presetSelector.addItem("Clean Sparkle", 2);
    presetSelector.addItem("Crystal Shimmer", 3);
    presetSelector.addItem("Silk Thread", 4);
    presetSelector.addItem("Subtle Glue", 5);
    presetSelector.addItem("Glass Canon", 6);
    presetSelector.addItem("Air Lift", 7);
    
    // Category 2: WARM ÃƒÆ’Ã†â€™Ãƒâ€ Ã¢â‚¬â„¢ÃƒÆ’Ã¢â‚¬Å¡Ãƒâ€šÃ‚Â¢ÃƒÆ’Ã†â€™Ãƒâ€šÃ‚Â¢ÃƒÆ’Ã‚Â¢ÃƒÂ¢Ã¢â‚¬Å¡Ã‚Â¬Ãƒâ€¦Ã‚Â¡ÃƒÆ’Ã¢â‚¬Å¡Ãƒâ€šÃ‚Â¬ÃƒÆ’Ã†â€™Ãƒâ€šÃ‚Â¢ÃƒÆ’Ã‚Â¢ÃƒÂ¢Ã¢â€šÂ¬Ã…Â¡Ãƒâ€šÃ‚Â¬ÃƒÆ’Ã¢â‚¬Å¡Ãƒâ€šÃ‚Â analog-style saturation, musical thickening (6 presets)
    presetSelector.addItem("--- WARM ---", 8);    presetSelector.setItemEnabled(8, false);
    presetSelector.addItem("Warm Glow", 9);
    presetSelector.addItem("Vintage Vibe", 10);
    presetSelector.addItem("Thick Sauce", 11);
    presetSelector.addItem("Tight Punch", 12);
    presetSelector.addItem("Cozy Hiss", 13);
    presetSelector.addItem("Tube Glow", 14);
    
    // Category 3: CREATIVE ÃƒÆ’Ã†â€™Ãƒâ€ Ã¢â‚¬â„¢ÃƒÆ’Ã¢â‚¬Å¡Ãƒâ€šÃ‚Â¢ÃƒÆ’Ã†â€™Ãƒâ€šÃ‚Â¢ÃƒÆ’Ã‚Â¢ÃƒÂ¢Ã¢â‚¬Å¡Ã‚Â¬Ãƒâ€¦Ã‚Â¡ÃƒÆ’Ã¢â‚¬Å¡Ãƒâ€šÃ‚Â¬ÃƒÆ’Ã†â€™Ãƒâ€šÃ‚Â¢ÃƒÆ’Ã‚Â¢ÃƒÂ¢Ã¢â€šÂ¬Ã…Â¡Ãƒâ€šÃ‚Â¬ÃƒÆ’Ã¢â‚¬Å¡Ãƒâ€šÃ‚Â modulation-forward, sound design (6 presets)
    presetSelector.addItem("--- CREATIVE ---", 15); presetSelector.setItemEnabled(15, false);
    presetSelector.addItem("Dreamy Space", 16);
    presetSelector.addItem("Cosmic Wide", 17);
    presetSelector.addItem("Molten Core", 18);
    presetSelector.addItem("Sunspot", 19);
    presetSelector.addItem("Nebula Drift", 20);
    presetSelector.addItem("Shimmerfall", 21);
    
    // Category 4: EXTREME ÃƒÆ’Ã†â€™Ãƒâ€ Ã¢â‚¬â„¢ÃƒÆ’Ã¢â‚¬Å¡Ãƒâ€šÃ‚Â¢ÃƒÆ’Ã†â€™Ãƒâ€šÃ‚Â¢ÃƒÆ’Ã‚Â¢ÃƒÂ¢Ã¢â‚¬Å¡Ã‚Â¬Ãƒâ€¦Ã‚Â¡ÃƒÆ’Ã¢â‚¬Å¡Ãƒâ€šÃ‚Â¬ÃƒÆ’Ã†â€™Ãƒâ€šÃ‚Â¢ÃƒÆ’Ã‚Â¢ÃƒÂ¢Ã¢â€šÂ¬Ã…Â¡Ãƒâ€šÃ‚Â¬ÃƒÆ’Ã¢â‚¬Å¡Ãƒâ€šÃ‚Â aggressive, heavy processing (6 presets)
    presetSelector.addItem("--- EXTREME ---", 22); presetSelector.setItemEnabled(22, false);
    presetSelector.addItem("Deep Echo", 23);
    presetSelector.addItem("Aggressive Drive", 24);
    presetSelector.addItem("Lush Pad", 25);
    presetSelector.addItem("Event Horizon", 26);
    presetSelector.addItem("Iron Press", 27);
    presetSelector.addItem("Obliterator", 28);
    
    // Category 5: SIGNATURE ÃƒÆ’Ã†â€™Ãƒâ€ Ã¢â‚¬â„¢ÃƒÆ’Ã¢â‚¬Å¡Ãƒâ€šÃ‚Â¢ÃƒÆ’Ã†â€™Ãƒâ€šÃ‚Â¢ÃƒÆ’Ã‚Â¢ÃƒÂ¢Ã¢â‚¬Å¡Ã‚Â¬Ãƒâ€¦Ã‚Â¡ÃƒÆ’Ã¢â‚¬Å¡Ãƒâ€šÃ‚Â¬ÃƒÆ’Ã†â€™Ãƒâ€šÃ‚Â¢ÃƒÆ’Ã‚Â¢ÃƒÂ¢Ã¢â€šÂ¬Ã…Â¡Ãƒâ€šÃ‚Â¬ÃƒÆ’Ã¢â‚¬Å¡Ãƒâ€šÃ‚Â curated artist-style sounds, distinct character (6 presets)
    presetSelector.addItem("--- SIGNATURE ---", 29); presetSelector.setItemEnabled(29, false);
    presetSelector.addItem("Velvet Morning", 30);
    presetSelector.addItem("Neon Dusk", 31);
    presetSelector.addItem("Basement Sessions", 32);
    presetSelector.addItem("Cathedral Drift", 33);
    presetSelector.addItem("Circuit Bent", 34);
    presetSelector.addItem("Midnight Oil", 35);
    
    // Category 6: DREAM ÃƒÆ’Ã†â€™Ãƒâ€ Ã¢â‚¬â„¢ÃƒÆ’Ã¢â‚¬Å¡Ãƒâ€šÃ‚Â¢ÃƒÆ’Ã†â€™Ãƒâ€šÃ‚Â¢ÃƒÆ’Ã‚Â¢ÃƒÂ¢Ã¢â‚¬Å¡Ã‚Â¬Ãƒâ€¦Ã‚Â¡ÃƒÆ’Ã¢â‚¬Å¡Ãƒâ€šÃ‚Â¬ÃƒÆ’Ã†â€™Ãƒâ€šÃ‚Â¢ÃƒÆ’Ã‚Â¢ÃƒÂ¢Ã¢â€šÂ¬Ã…Â¡Ãƒâ€šÃ‚Â¬ÃƒÆ’Ã¢â‚¬Å¡Ãƒâ€šÃ‚Â ambient, ethereal, deep soundscapes (6 presets)
    presetSelector.addItem("--- DREAM ---", 36); presetSelector.setItemEnabled(36, false);
    presetSelector.addItem("Cloud Chamber", 37);
    presetSelector.addItem("Frozen Lake", 38);
    presetSelector.addItem("Ash & Ember", 39);
    presetSelector.addItem("Stargate Portal", 40);
    presetSelector.addItem("Underwater Cathedral", 41);
    presetSelector.addItem("Solar Flare", 42);
    
    presetSelector.setSelectedId(2); // Default to Clean Sparkle (first actual preset)
    presetSelector.setTooltip("Select factory preset ÃƒÆ’Ã†â€™Ãƒâ€ Ã¢â‚¬â„¢ÃƒÆ’Ã¢â‚¬Å¡Ãƒâ€šÃ‚Â¢ÃƒÆ’Ã†â€™Ãƒâ€šÃ‚Â¢ÃƒÆ’Ã‚Â¢ÃƒÂ¢Ã¢â‚¬Å¡Ã‚Â¬Ãƒâ€¦Ã‚Â¡ÃƒÆ’Ã¢â‚¬Å¡Ãƒâ€šÃ‚Â¬ÃƒÆ’Ã†â€™Ãƒâ€šÃ‚Â¢ÃƒÆ’Ã‚Â¢ÃƒÂ¢Ã¢â€šÂ¬Ã…Â¡Ãƒâ€šÃ‚Â¬ÃƒÆ’Ã¢â‚¬Å¡Ãƒâ€šÃ‚Â 36 curated sounds from clean enhancement to deep ambient soundscapes");
    addAndMakeVisible(presetSelector);

    auto setupKnob = [this](AnimatedKnob& k, juce::Label& l, const juce::String& txt, const juce::String& paramID, const juce::String& tooltip = "") {
        k.setTextBoxStyle(juce::Slider::TextBoxBelow, false, 70, 18);
        k.setColour(juce::Slider::textBoxTextColourId, juce::Colour(0xffc0c0d0));
        k.setColour(juce::Slider::textBoxBackgroundColourId, juce::Colour(0xff0c0c1a));
        k.setColour(juce::Slider::textBoxOutlineColourId, juce::Colour(0xff2a2a50));
        if (tooltip.isNotEmpty())
            k.setTooltip(tooltip);
        addAndMakeVisible(k);
        l.setText(txt, juce::dontSendNotification);
        l.setFont(juce::Font(juce::FontOptions(11.0f, juce::Font::bold)));
        l.setJustificationType(juce::Justification::centred);
        l.setColour(juce::Label::textColourId, juce::Colour(0xff999aaa));
        addAndMakeVisible(l);
        k.linkedParamID = paramID;
        k.onGestureStart = [this]() {
            audioProcessor.undoManager.beginNewTransaction();
        };
        // The menu is shown asynchronously, so every callback below must be
        // able to outlive this knob (and the editor). Capture only the
        // parameter id by value and guard all component/processor access with
        // SafePointer; raw `[&k]`/`[&proc]` captures can fire after teardown.
        k.onRightClick = [this, paramID = k.linkedParamID,
                          safeKnob = juce::Component::SafePointer<AnimatedKnob>(&k)]
                         (const juce::MouseEvent&)
        {
            juce::Component::SafePointer<CorvusFXAudioProcessorEditor> safeEditor(this);
            juce::PopupMenu menu;
            // Armed-learn affordance: offer cancellation while a learn is
            // pending (otherwise the next CC silently consumes the armed
            // state with no escape hatch except capturing or editor close).
            if (audioProcessor.isMidiLearnActive())
                menu.addItem("Cancel MIDI Learn", [safeEditor]() {
                    if (auto* editor = safeEditor.getComponent())
                        if (auto* proc = static_cast<CorvusFXAudioProcessor*>(
                                editor->getAudioProcessor()))
                            proc->stopMidiLearn();
                });
            menu.addItem("MIDI Learn", [safeEditor, paramID]() {
                if (auto* editor = safeEditor.getComponent())
                    if (auto* proc = static_cast<CorvusFXAudioProcessor*>(
                            editor->getAudioProcessor()))
                        proc->startMidiLearn(paramID);
            });
            if (audioProcessor.hasMidiMapping(paramID))
                menu.addItem("Forget MIDI Mapping", [safeEditor, paramID]() {
                    if (auto* editor = safeEditor.getComponent())
                        if (auto* proc = static_cast<CorvusFXAudioProcessor*>(
                                editor->getAudioProcessor()))
                            proc->clearMidiMapping(paramID);
                });
            menu.addSeparator();
            if (audioProcessor.isParameterLocked(paramID))
                menu.addItem("Unlock Parameter", [safeEditor, safeKnob, paramID]() {
                    if (auto* editor = safeEditor.getComponent())
                        if (auto* proc = static_cast<CorvusFXAudioProcessor*>(
                                editor->getAudioProcessor()))
                            proc->setParameterLocked(paramID, false);
                    if (auto* knob = safeKnob.getComponent())
                        knob->setColour(juce::Slider::textBoxTextColourId,
                                        juce::Colour(0xffc0c0d0));
                });
            else
                menu.addItem("Lock Parameter", [safeEditor, safeKnob, paramID]() {
                    if (auto* editor = safeEditor.getComponent())
                        if (auto* proc = static_cast<CorvusFXAudioProcessor*>(
                                editor->getAudioProcessor()))
                            proc->setParameterLocked(paramID, true);
                    if (auto* knob = safeKnob.getComponent())
                        knob->setColour(juce::Slider::textBoxTextColourId,
                                        juce::Colour(0xff666666));
                });
            menu.addSeparator();
            menu.addItem("Clear All MIDI Maps", [safeEditor]() {
                if (auto* editor = safeEditor.getComponent())
                    if (auto* proc = static_cast<CorvusFXAudioProcessor*>(
                            editor->getAudioProcessor()))
                        proc->clearAllMidiMappings();
            });
            menu.showMenuAsync(juce::PopupMenu::Options());
        };
        };

    setupKnob(overallKnob, overallLabel, "OVERALL", "overall", "Global wet/dry mix ÃƒÆ’Ã†â€™Ãƒâ€ Ã¢â‚¬â„¢ÃƒÆ’Ã¢â‚¬Å¡Ãƒâ€šÃ‚Â¢ÃƒÆ’Ã†â€™Ãƒâ€šÃ‚Â¢ÃƒÆ’Ã‚Â¢ÃƒÂ¢Ã¢â‚¬Å¡Ã‚Â¬Ãƒâ€¦Ã‚Â¡ÃƒÆ’Ã¢â‚¬Å¡Ãƒâ€šÃ‚Â¬ÃƒÆ’Ã†â€™Ãƒâ€šÃ‚Â¢ÃƒÆ’Ã‚Â¢ÃƒÂ¢Ã¢â€šÂ¬Ã…Â¡Ãƒâ€šÃ‚Â¬ÃƒÆ’Ã¢â‚¬Å¡Ãƒâ€šÃ‚Â blends the full effect chain with the dry signal");
    overallLabel.setFont(juce::Font(juce::FontOptions(14.0f, juce::Font::bold)));
    overallLabel.setColour(juce::Label::textColourId, juce::Colour(0xffb0b0c8));

    addAndMakeVisible(distortionSection);
    addAndMakeVisible(chorusSection);
    addAndMakeVisible(delaySection);
    addAndMakeVisible(reverbSection);
    addAndMakeVisible(distortionBypassButton);
    distortionBypassButton.setButtonText("BYPASS");
    distortionBypassButton.setColour(juce::TextButton::buttonColourId, juce::Colour(0xff3a1a20));
    distortionBypassButton.setColour(juce::TextButton::buttonOnColourId, juce::Colour(0xff552233));
    distortionBypassButton.setColour(juce::TextButton::textColourOffId, juce::Colour(0xff886666));
    distortionBypassButton.setColour(juce::TextButton::textColourOnId, juce::Colour(0xffcc8888));
    distortionBypassButton.setTooltip("Bypass the distortion module entirely ÃƒÆ’Ã†â€™Ãƒâ€ Ã¢â‚¬â„¢ÃƒÆ’Ã¢â‚¬Å¡Ãƒâ€šÃ‚Â¢ÃƒÆ’Ã†â€™Ãƒâ€šÃ‚Â¢ÃƒÆ’Ã‚Â¢ÃƒÂ¢Ã¢â‚¬Å¡Ã‚Â¬Ãƒâ€¦Ã‚Â¡ÃƒÆ’Ã¢â‚¬Å¡Ãƒâ€šÃ‚Â¬ÃƒÆ’Ã†â€™Ãƒâ€šÃ‚Â¢ÃƒÆ’Ã‚Â¢ÃƒÂ¢Ã¢â€šÂ¬Ã…Â¡Ãƒâ€šÃ‚Â¬ÃƒÆ’Ã¢â‚¬Å¡Ãƒâ€šÃ‚Â click-free crossfade");

    addAndMakeVisible(chorusBypassButton);
    chorusBypassButton.setButtonText("BYPASS");
    chorusBypassButton.setColour(juce::TextButton::buttonColourId, juce::Colour(0xff182030));
    chorusBypassButton.setColour(juce::TextButton::buttonOnColourId, juce::Colour(0xff223344));
    chorusBypassButton.setColour(juce::TextButton::textColourOffId, juce::Colour(0xff6688aa));
    chorusBypassButton.setColour(juce::TextButton::textColourOnId, juce::Colour(0xff88aacc));
    chorusBypassButton.setTooltip("Bypass the chorus module entirely ÃƒÆ’Ã†â€™Ãƒâ€ Ã¢â‚¬â„¢ÃƒÆ’Ã¢â‚¬Å¡Ãƒâ€šÃ‚Â¢ÃƒÆ’Ã†â€™Ãƒâ€šÃ‚Â¢ÃƒÆ’Ã‚Â¢ÃƒÂ¢Ã¢â‚¬Å¡Ã‚Â¬Ãƒâ€¦Ã‚Â¡ÃƒÆ’Ã¢â‚¬Å¡Ãƒâ€šÃ‚Â¬ÃƒÆ’Ã†â€™Ãƒâ€šÃ‚Â¢ÃƒÆ’Ã‚Â¢ÃƒÂ¢Ã¢â€šÂ¬Ã…Â¡Ãƒâ€šÃ‚Â¬ÃƒÆ’Ã¢â‚¬Å¡Ãƒâ€šÃ‚Â click-free crossfade");

    addAndMakeVisible(delayBypassButton);
    delayBypassButton.setButtonText("BYPASS");
    delayBypassButton.setColour(juce::TextButton::buttonColourId, juce::Colour(0xff1a3020));
    delayBypassButton.setColour(juce::TextButton::buttonOnColourId, juce::Colour(0xff224433));
    delayBypassButton.setColour(juce::TextButton::textColourOffId, juce::Colour(0xff66aa88));
    delayBypassButton.setColour(juce::TextButton::textColourOnId, juce::Colour(0xff88ccaa));
    delayBypassButton.setTooltip("Bypass the delay module entirely ÃƒÆ’Ã†â€™Ãƒâ€ Ã¢â‚¬â„¢ÃƒÆ’Ã¢â‚¬Å¡Ãƒâ€šÃ‚Â¢ÃƒÆ’Ã†â€™Ãƒâ€šÃ‚Â¢ÃƒÆ’Ã‚Â¢ÃƒÂ¢Ã¢â‚¬Å¡Ã‚Â¬Ãƒâ€¦Ã‚Â¡ÃƒÆ’Ã¢â‚¬Å¡Ãƒâ€šÃ‚Â¬ÃƒÆ’Ã†â€™Ãƒâ€šÃ‚Â¢ÃƒÆ’Ã‚Â¢ÃƒÂ¢Ã¢â€šÂ¬Ã…Â¡Ãƒâ€šÃ‚Â¬ÃƒÆ’Ã¢â‚¬Å¡Ãƒâ€šÃ‚Â click-free crossfade");

    addAndMakeVisible(reverbBypassButton);
    reverbBypassButton.setButtonText("BYPASS");
    reverbBypassButton.setColour(juce::TextButton::buttonColourId, juce::Colour(0xff301a30));
    reverbBypassButton.setColour(juce::TextButton::buttonOnColourId, juce::Colour(0xff442244));
    reverbBypassButton.setColour(juce::TextButton::textColourOffId, juce::Colour(0xffaa66aa));
    reverbBypassButton.setColour(juce::TextButton::textColourOnId, juce::Colour(0xffcc88cc));
    reverbBypassButton.setTooltip("Bypass the reverb module entirely ÃƒÆ’Ã†â€™Ãƒâ€ Ã¢â‚¬â„¢ÃƒÆ’Ã¢â‚¬Å¡Ãƒâ€šÃ‚Â¢ÃƒÆ’Ã†â€™Ãƒâ€šÃ‚Â¢ÃƒÆ’Ã‚Â¢ÃƒÂ¢Ã¢â‚¬Å¡Ã‚Â¬Ãƒâ€¦Ã‚Â¡ÃƒÆ’Ã¢â‚¬Å¡Ãƒâ€šÃ‚Â¬ÃƒÆ’Ã†â€™Ãƒâ€šÃ‚Â¢ÃƒÆ’Ã‚Â¢ÃƒÂ¢Ã¢â€šÂ¬Ã…Â¡Ãƒâ€šÃ‚Â¬ÃƒÆ’Ã¢â‚¬Å¡Ãƒâ€šÃ‚Â click-free crossfade");

    addAndMakeVisible(masterBypassButton);
    masterBypassButton.setButtonText("BYPASS");
    masterBypassButton.setColour(juce::TextButton::buttonColourId, juce::Colour(0xff301a20));
    masterBypassButton.setColour(juce::TextButton::buttonOnColourId, juce::Colour(0xff442233));
    masterBypassButton.setColour(juce::TextButton::textColourOffId, juce::Colour(0xffaa6688));
    masterBypassButton.setColour(juce::TextButton::textColourOnId, juce::Colour(0xffcc88aa));
    masterBypassButton.setTooltip("Bypass the master output stage entirely ÃƒÆ’Ã†â€™Ãƒâ€ Ã¢â‚¬â„¢ÃƒÆ’Ã¢â‚¬Å¡Ãƒâ€šÃ‚Â¢ÃƒÆ’Ã†â€™Ãƒâ€šÃ‚Â¢ÃƒÆ’Ã‚Â¢ÃƒÂ¢Ã¢â‚¬Å¡Ã‚Â¬Ãƒâ€¦Ã‚Â¡ÃƒÆ’Ã¢â‚¬Å¡Ãƒâ€šÃ‚Â¬ÃƒÆ’Ã†â€™Ãƒâ€šÃ‚Â¢ÃƒÆ’Ã‚Â¢ÃƒÂ¢Ã¢â€šÂ¬Ã…Â¡Ãƒâ€šÃ‚Â¬ÃƒÆ’Ã¢â‚¬Å¡Ãƒâ€šÃ‚Â click-free crossfade");

    setupKnob(fatnessKnob, fatnessLabel, "DRIVE", "fatness", "Distortion amount ÃƒÆ’Ã†â€™Ãƒâ€ Ã¢â‚¬â„¢ÃƒÆ’Ã¢â‚¬Å¡Ãƒâ€šÃ‚Â¢ÃƒÆ’Ã†â€™Ãƒâ€šÃ‚Â¢ÃƒÆ’Ã‚Â¢ÃƒÂ¢Ã¢â‚¬Å¡Ã‚Â¬Ãƒâ€¦Ã‚Â¡ÃƒÆ’Ã¢â‚¬Å¡Ãƒâ€šÃ‚Â¬ÃƒÆ’Ã†â€™Ãƒâ€šÃ‚Â¢ÃƒÆ’Ã‚Â¢ÃƒÂ¢Ã¢â€šÂ¬Ã…Â¡Ãƒâ€šÃ‚Â¬ÃƒÆ’Ã¢â‚¬Å¡Ãƒâ€šÃ‚Â blends tape saturation at low settings into tube warmth at high settings");
    setupKnob(chorusDepthKnob, chorusDepthLabel, "DEPTH", "chorus_depth", "Chorus modulation depth ÃƒÆ’Ã†â€™Ãƒâ€ Ã¢â‚¬â„¢ÃƒÆ’Ã¢â‚¬Å¡Ãƒâ€šÃ‚Â¢ÃƒÆ’Ã†â€™Ãƒâ€šÃ‚Â¢ÃƒÆ’Ã‚Â¢ÃƒÂ¢Ã¢â‚¬Å¡Ã‚Â¬Ãƒâ€¦Ã‚Â¡ÃƒÆ’Ã¢â‚¬Å¡Ãƒâ€šÃ‚Â¬ÃƒÆ’Ã†â€™Ãƒâ€šÃ‚Â¢ÃƒÆ’Ã‚Â¢ÃƒÂ¢Ã¢â€šÂ¬Ã…Â¡Ãƒâ€šÃ‚Â¬ÃƒÆ’Ã¢â‚¬Å¡Ãƒâ€šÃ‚Â controls pitch excursion amount");
    setupKnob(chorusRateKnob, chorusRateLabel, "RATE", "chorus_rate", "Chorus LFO speed (Hz) ÃƒÆ’Ã†â€™Ãƒâ€ Ã¢â‚¬â„¢ÃƒÆ’Ã¢â‚¬Å¡Ãƒâ€šÃ‚Â¢ÃƒÆ’Ã†â€™Ãƒâ€šÃ‚Â¢ÃƒÆ’Ã‚Â¢ÃƒÂ¢Ã¢â‚¬Å¡Ã‚Â¬Ãƒâ€¦Ã‚Â¡ÃƒÆ’Ã¢â‚¬Å¡Ãƒâ€šÃ‚Â¬ÃƒÆ’Ã†â€™Ãƒâ€šÃ‚Â¢ÃƒÆ’Ã‚Â¢ÃƒÂ¢Ã¢â€šÂ¬Ã…Â¡Ãƒâ€šÃ‚Â¬ÃƒÆ’Ã¢â‚¬Å¡Ãƒâ€šÃ‚Â 6 decorrelated voices never align");
    setupKnob(chorusMixKnob, chorusMixLabel, "MIX", "chorus_mix", "Chorus wet/dry balance ÃƒÆ’Ã†â€™Ãƒâ€ Ã¢â‚¬â„¢ÃƒÆ’Ã¢â‚¬Å¡Ãƒâ€šÃ‚Â¢ÃƒÆ’Ã†â€™Ãƒâ€šÃ‚Â¢ÃƒÆ’Ã‚Â¢ÃƒÂ¢Ã¢â‚¬Å¡Ã‚Â¬Ãƒâ€¦Ã‚Â¡ÃƒÆ’Ã¢â‚¬Å¡Ãƒâ€šÃ‚Â¬ÃƒÆ’Ã†â€™Ãƒâ€šÃ‚Â¢ÃƒÆ’Ã‚Â¢ÃƒÂ¢Ã¢â€šÂ¬Ã…Â¡Ãƒâ€šÃ‚Â¬ÃƒÆ’Ã¢â‚¬Å¡Ãƒâ€šÃ‚Â 10% dry anchor keeps pitch stable at full wet");
    setupKnob(delayTimeKnob, delayTimeLabel, "TIME", "delay_time", "Delay time in milliseconds ÃƒÆ’Ã†â€™Ãƒâ€ Ã¢â‚¬â„¢ÃƒÆ’Ã¢â‚¬Å¡Ãƒâ€šÃ‚Â¢ÃƒÆ’Ã†â€™Ãƒâ€šÃ‚Â¢ÃƒÆ’Ã‚Â¢ÃƒÂ¢Ã¢â‚¬Å¡Ã‚Â¬Ãƒâ€¦Ã‚Â¡ÃƒÆ’Ã¢â‚¬Å¡Ãƒâ€šÃ‚Â¬ÃƒÆ’Ã†â€™Ãƒâ€šÃ‚Â¢ÃƒÆ’Ã‚Â¢ÃƒÂ¢Ã¢â€šÂ¬Ã…Â¡Ãƒâ€šÃ‚Â¬ÃƒÆ’Ã¢â‚¬Å¡Ãƒâ€šÃ‚Â 0 to 2000ms with tape-style interpolation");
    setupKnob(delayFeedbackKnob, delayFeedbackLabel, "FEEDBACK", "delay_feedback", "Delay feedback amount ÃƒÆ’Ã†â€™Ãƒâ€ Ã¢â‚¬â„¢ÃƒÆ’Ã¢â‚¬Å¡Ãƒâ€šÃ‚Â¢ÃƒÆ’Ã†â€™Ãƒâ€šÃ‚Â¢ÃƒÆ’Ã‚Â¢ÃƒÂ¢Ã¢â‚¬Å¡Ã‚Â¬Ãƒâ€¦Ã‚Â¡ÃƒÆ’Ã¢â‚¬Å¡Ãƒâ€šÃ‚Â¬ÃƒÆ’Ã†â€™Ãƒâ€šÃ‚Â¢ÃƒÆ’Ã‚Â¢ÃƒÂ¢Ã¢â€šÂ¬Ã…Â¡Ãƒâ€šÃ‚Â¬ÃƒÆ’Ã¢â‚¬Å¡Ãƒâ€šÃ‚Â exponential mapping for musical response");
    setupKnob(delayMixKnob, delayMixLabel, "MIX", "delay_mix", "Delay wet/dry balance");
    setupKnob(delayDampingKnob, delayDampingLabel, "DAMPING", "delay_damping", "Delay feedback tone ÃƒÆ’Ã†â€™Ãƒâ€ Ã¢â‚¬â„¢ÃƒÆ’Ã¢â‚¬Å¡Ãƒâ€šÃ‚Â¢ÃƒÆ’Ã†â€™Ãƒâ€šÃ‚Â¢ÃƒÆ’Ã‚Â¢ÃƒÂ¢Ã¢â‚¬Å¡Ã‚Â¬Ãƒâ€¦Ã‚Â¡ÃƒÆ’Ã¢â‚¬Å¡Ãƒâ€šÃ‚Â¬ÃƒÆ’Ã†â€™Ãƒâ€šÃ‚Â¢ÃƒÆ’Ã‚Â¢ÃƒÂ¢Ã¢â€šÂ¬Ã…Â¡Ãƒâ€šÃ‚Â¬ÃƒÆ’Ã¢â‚¬Å¡Ãƒâ€šÃ‚Â high values = darker, more tape-like repeats");
    setupKnob(delayModKnob, delayModLabel, "MOD", "delay_mod", "Delay tape modulation depth ÃƒÆ’Ã†â€™Ãƒâ€ Ã¢â‚¬â„¢ÃƒÆ’Ã¢â‚¬Å¡Ãƒâ€šÃ‚Â¢ÃƒÆ’Ã†â€™Ãƒâ€šÃ‚Â¢ÃƒÆ’Ã‚Â¢ÃƒÂ¢Ã¢â‚¬Å¡Ã‚Â¬Ãƒâ€¦Ã‚Â¡ÃƒÆ’Ã¢â‚¬Å¡Ãƒâ€šÃ‚Â¬ÃƒÆ’Ã†â€™Ãƒâ€šÃ‚Â¢ÃƒÆ’Ã‚Â¢ÃƒÂ¢Ã¢â€šÂ¬Ã…Â¡Ãƒâ€šÃ‚Â¬ÃƒÆ’Ã¢â‚¬Å¡Ãƒâ€šÃ‚Â wow and flutter intensity for vintage tape character");
    setupKnob(reverbSizeKnob, reverbSizeLabel, "SIZE", "reverb_size", "Reverb room size ÃƒÆ’Ã†â€™Ãƒâ€ Ã¢â‚¬â„¢ÃƒÆ’Ã¢â‚¬Å¡Ãƒâ€šÃ‚Â¢ÃƒÆ’Ã†â€™Ãƒâ€šÃ‚Â¢ÃƒÆ’Ã‚Â¢ÃƒÂ¢Ã¢â‚¬Å¡Ã‚Â¬Ãƒâ€¦Ã‚Â¡ÃƒÆ’Ã¢â‚¬Å¡Ãƒâ€šÃ‚Â¬ÃƒÆ’Ã†â€™Ãƒâ€šÃ‚Â¢ÃƒÆ’Ã‚Â¢ÃƒÂ¢Ã¢â€šÂ¬Ã…Â¡Ãƒâ€šÃ‚Â¬ÃƒÆ’Ã¢â‚¬Å¡Ãƒâ€šÃ‚Â controls both decay time and diffusion character");
    setupKnob(reverbDampingKnob, reverbDampingLabel, "DAMPING", "reverb_damping", "Reverb high-frequency absorption ÃƒÆ’Ã†â€™Ãƒâ€ Ã¢â‚¬â„¢ÃƒÆ’Ã¢â‚¬Å¡Ãƒâ€šÃ‚Â¢ÃƒÆ’Ã†â€™Ãƒâ€šÃ‚Â¢ÃƒÆ’Ã‚Â¢ÃƒÂ¢Ã¢â‚¬Å¡Ã‚Â¬Ãƒâ€¦Ã‚Â¡ÃƒÆ’Ã¢â‚¬Å¡Ãƒâ€šÃ‚Â¬ÃƒÆ’Ã†â€™Ãƒâ€šÃ‚Â¢ÃƒÆ’Ã‚Â¢ÃƒÂ¢Ã¢â€šÂ¬Ã…Â¡Ãƒâ€šÃ‚Â¬ÃƒÆ’Ã¢â‚¬Å¡Ãƒâ€šÃ‚Â higher = shorter, darker tail");
    setupKnob(reverbMixKnob, reverbMixLabel, "MIX", "reverb_mix", "Reverb wet/dry balance");
    setupKnob(reverbModKnob, reverbModLabel, "MOD", "reverb_mod", "Reverb modulation depth ÃƒÆ’Ã†â€™Ãƒâ€ Ã¢â‚¬â„¢ÃƒÆ’Ã¢â‚¬Å¡Ãƒâ€šÃ‚Â¢ÃƒÆ’Ã†â€™Ãƒâ€šÃ‚Â¢ÃƒÆ’Ã‚Â¢ÃƒÂ¢Ã¢â‚¬Å¡Ã‚Â¬Ãƒâ€¦Ã‚Â¡ÃƒÆ’Ã¢â‚¬Å¡Ãƒâ€šÃ‚Â¬ÃƒÆ’Ã†â€™Ãƒâ€šÃ‚Â¢ÃƒÆ’Ã‚Â¢ÃƒÂ¢Ã¢â€šÂ¬Ã…Â¡Ãƒâ€šÃ‚Â¬ÃƒÆ’Ã¢â‚¬Å¡Ãƒâ€šÃ‚Â adds organic movement to the reverb tail");
    setupKnob(masterDriveKnob, masterDriveLabel, "MASTER DRIVE", "master_drive", "Master output saturation ÃƒÆ’Ã†â€™Ãƒâ€ Ã¢â‚¬â„¢ÃƒÆ’Ã¢â‚¬Å¡Ãƒâ€šÃ‚Â¢ÃƒÆ’Ã†â€™Ãƒâ€šÃ‚Â¢ÃƒÆ’Ã‚Â¢ÃƒÂ¢Ã¢â‚¬Å¡Ã‚Â¬Ãƒâ€¦Ã‚Â¡ÃƒÆ’Ã¢â‚¬Å¡Ãƒâ€šÃ‚Â¬ÃƒÆ’Ã†â€™Ãƒâ€šÃ‚Â¢ÃƒÆ’Ã‚Â¢ÃƒÂ¢Ã¢â€šÂ¬Ã…Â¡Ãƒâ€šÃ‚Â¬ÃƒÆ’Ã¢â‚¬Å¡Ãƒâ€šÃ‚Â push-pull even harmonics for analog warmth");
    setupKnob(masterWidthKnob, masterWidthLabel, "WIDTH", "master_width", "Stereo width ÃƒÆ’Ã†â€™Ãƒâ€ Ã¢â‚¬â„¢ÃƒÆ’Ã¢â‚¬Å¡Ãƒâ€šÃ‚Â¢ÃƒÆ’Ã†â€™Ãƒâ€šÃ‚Â¢ÃƒÆ’Ã‚Â¢ÃƒÂ¢Ã¢â‚¬Å¡Ã‚Â¬Ãƒâ€¦Ã‚Â¡ÃƒÆ’Ã¢â‚¬Å¡Ãƒâ€šÃ‚Â¬ÃƒÆ’Ã†â€™Ãƒâ€šÃ‚Â¢ÃƒÆ’Ã‚Â¢ÃƒÂ¢Ã¢â€šÂ¬Ã…Â¡Ãƒâ€šÃ‚Â¬ÃƒÆ’Ã¢â‚¬Å¡Ãƒâ€šÃ‚Â 0% = mono, 100% = original stereo, >100% = widened");
    setupKnob(masterMidDriveKnob, masterMidDriveLabel, "MID DRIVE", "master_mid_drive", "Mid channel saturation ÃƒÆ’Ã†â€™Ãƒâ€ Ã¢â‚¬â„¢ÃƒÆ’Ã¢â‚¬Å¡Ãƒâ€šÃ‚Â¢ÃƒÆ’Ã†â€™Ãƒâ€šÃ‚Â¢ÃƒÆ’Ã‚Â¢ÃƒÂ¢Ã¢â‚¬Å¡Ã‚Â¬Ãƒâ€¦Ã‚Â¡ÃƒÆ’Ã¢â‚¬Å¡Ãƒâ€šÃ‚Â¬ÃƒÆ’Ã†â€™Ãƒâ€šÃ‚Â¢ÃƒÆ’Ã‚Â¢ÃƒÂ¢Ã¢â€šÂ¬Ã…Â¡Ãƒâ€šÃ‚Â¬ÃƒÆ’Ã¢â‚¬Å¡Ãƒâ€šÃ‚Â push-pull even harmonics on center content");
    setupKnob(masterSideDriveKnob, masterSideDriveLabel, "SIDE DRIVE", "master_side_drive", "Side channel saturation ÃƒÆ’Ã†â€™Ãƒâ€ Ã¢â‚¬â„¢ÃƒÆ’Ã¢â‚¬Å¡Ãƒâ€šÃ‚Â¢ÃƒÆ’Ã†â€™Ãƒâ€šÃ‚Â¢ÃƒÆ’Ã‚Â¢ÃƒÂ¢Ã¢â‚¬Å¡Ã‚Â¬Ãƒâ€¦Ã‚Â¡ÃƒÆ’Ã¢â‚¬Å¡Ãƒâ€šÃ‚Â¬ÃƒÆ’Ã†â€™Ãƒâ€šÃ‚Â¢ÃƒÆ’Ã‚Â¢ÃƒÂ¢Ã¢â€šÂ¬Ã…Â¡Ãƒâ€šÃ‚Â¬ÃƒÆ’Ã¢â‚¬Å¡Ãƒâ€šÃ‚Â push-pull even harmonics on stereo width");
    setupKnob(outputTrimKnob, outputTrimLabel, "TRIM", "output_trim", "Output level trim ÃƒÆ’Ã†â€™Ãƒâ€ Ã¢â‚¬â„¢ÃƒÆ’Ã¢â‚¬Å¡Ãƒâ€šÃ‚Â¢ÃƒÆ’Ã†â€™Ãƒâ€šÃ‚Â¢ÃƒÆ’Ã‚Â¢ÃƒÂ¢Ã¢â‚¬Å¡Ã‚Â¬Ãƒâ€¦Ã‚Â¡ÃƒÆ’Ã¢â‚¬Å¡Ãƒâ€šÃ‚Â¬ÃƒÆ’Ã†â€™Ãƒâ€šÃ‚Â¢ÃƒÆ’Ã‚Â¢ÃƒÂ¢Ã¢â€šÂ¬Ã…Â¡Ãƒâ€šÃ‚Â¬ÃƒÆ’Ã¢â‚¬Å¡Ãƒâ€šÃ‚Â 0% = silent, 100% = unity gain, 200% = +6dB boost");

    auto applyLockColor = [this](AnimatedKnob& knob)
    {
        knob.setColour(juce::Slider::textBoxTextColourId,
                       audioProcessor.isParameterLocked(knob.linkedParamID)
                           ? juce::Colour(0xff666666)
                           : juce::Colour(0xffc0c0d0));
    };
    applyLockColor(overallKnob);
    applyLockColor(fatnessKnob);
    applyLockColor(chorusDepthKnob);
    applyLockColor(chorusRateKnob);
    applyLockColor(chorusMixKnob);
    applyLockColor(delayTimeKnob);
    applyLockColor(delayFeedbackKnob);
    applyLockColor(delayMixKnob);
    applyLockColor(delayDampingKnob);
    applyLockColor(delayModKnob);
    applyLockColor(reverbSizeKnob);
    applyLockColor(reverbDampingKnob);
    applyLockColor(reverbMixKnob);
    applyLockColor(reverbModKnob);
    applyLockColor(masterDriveKnob);
    applyLockColor(masterWidthKnob);
    applyLockColor(masterMidDriveKnob);
    applyLockColor(masterSideDriveKnob);
    applyLockColor(outputTrimKnob);

    // Attachments
    overallAtt = std::make_unique<juce::AudioProcessorValueTreeState::SliderAttachment>(audioProcessor.apvts, "overall", overallKnob);
    fatnessAtt = std::make_unique<juce::AudioProcessorValueTreeState::SliderAttachment>(audioProcessor.apvts, "fatness", fatnessKnob);
    distortionBypassAtt = std::make_unique<juce::AudioProcessorValueTreeState::ButtonAttachment>(audioProcessor.apvts, "distortion_bypass", distortionBypassButton);
    chorusBypassAtt = std::make_unique<juce::AudioProcessorValueTreeState::ButtonAttachment>(audioProcessor.apvts, "chorus_bypass", chorusBypassButton);
    delayBypassAtt = std::make_unique<juce::AudioProcessorValueTreeState::ButtonAttachment>(audioProcessor.apvts, "delay_bypass", delayBypassButton);
    reverbBypassAtt = std::make_unique<juce::AudioProcessorValueTreeState::ButtonAttachment>(audioProcessor.apvts, "reverb_bypass", reverbBypassButton);
    masterBypassAtt = std::make_unique<juce::AudioProcessorValueTreeState::ButtonAttachment>(audioProcessor.apvts, "master_bypass", masterBypassButton);
    cDepAtt = std::make_unique<juce::AudioProcessorValueTreeState::SliderAttachment>(audioProcessor.apvts, "chorus_depth", chorusDepthKnob);
    cRateAtt = std::make_unique<juce::AudioProcessorValueTreeState::SliderAttachment>(audioProcessor.apvts, "chorus_rate", chorusRateKnob);
    cMixAtt = std::make_unique<juce::AudioProcessorValueTreeState::SliderAttachment>(audioProcessor.apvts, "chorus_mix", chorusMixKnob);
    dTimeAtt = std::make_unique<juce::AudioProcessorValueTreeState::SliderAttachment>(audioProcessor.apvts, "delay_time", delayTimeKnob);
    dFbAtt = std::make_unique<juce::AudioProcessorValueTreeState::SliderAttachment>(audioProcessor.apvts, "delay_feedback", delayFeedbackKnob);
    dMixAtt = std::make_unique<juce::AudioProcessorValueTreeState::SliderAttachment>(audioProcessor.apvts, "delay_mix", delayMixKnob);
    dDampAtt = std::make_unique<juce::AudioProcessorValueTreeState::SliderAttachment>(audioProcessor.apvts, "delay_damping", delayDampingKnob);
    dModAtt = std::make_unique<juce::AudioProcessorValueTreeState::SliderAttachment>(audioProcessor.apvts, "delay_mod", delayModKnob);
    rSizeAtt = std::make_unique<juce::AudioProcessorValueTreeState::SliderAttachment>(audioProcessor.apvts, "reverb_size", reverbSizeKnob);
    rDampAtt = std::make_unique<juce::AudioProcessorValueTreeState::SliderAttachment>(audioProcessor.apvts, "reverb_damping", reverbDampingKnob);
    rMixAtt = std::make_unique<juce::AudioProcessorValueTreeState::SliderAttachment>(audioProcessor.apvts, "reverb_mix", reverbMixKnob);
    rModAtt = std::make_unique<juce::AudioProcessorValueTreeState::SliderAttachment>(audioProcessor.apvts, "reverb_mod", reverbModKnob);
    masterDriveAtt = std::make_unique<juce::AudioProcessorValueTreeState::SliderAttachment>(audioProcessor.apvts, "master_drive", masterDriveKnob);
    masterWidthAtt = std::make_unique<juce::AudioProcessorValueTreeState::SliderAttachment>(audioProcessor.apvts, "master_width", masterWidthKnob);
    masterMidDriveAtt = std::make_unique<juce::AudioProcessorValueTreeState::SliderAttachment>(audioProcessor.apvts, "master_mid_drive", masterMidDriveKnob);
    masterSideDriveAtt = std::make_unique<juce::AudioProcessorValueTreeState::SliderAttachment>(audioProcessor.apvts, "master_side_drive", masterSideDriveKnob);
    outputTrimAtt = std::make_unique<juce::AudioProcessorValueTreeState::SliderAttachment>(audioProcessor.apvts, "output_trim", outputTrimKnob);
    presetAtt = std::make_unique<PresetComboAttachment>(*audioProcessor.apvts.getParameter("preset"), presetSelector, &audioProcessor.undoManager);

    // Preset A/B Compare buttons
    btnSlotA.setButtonText("A");
    btnSlotA.setColour(juce::TextButton::buttonColourId, juce::Colour(0xff2a2a50));
    btnSlotA.setColour(juce::TextButton::buttonOnColourId, juce::Colour(0xffb366ff));
    btnSlotA.setColour(juce::TextButton::textColourOffId, juce::Colour(0xff8888aa));
    btnSlotA.setColour(juce::TextButton::textColourOnId, juce::Colour(0xffffffff));
    btnSlotA.setClickingTogglesState(false);
    btnSlotA.setRadioGroupId(1001);
    btnSlotA.setTooltip("Load preset snapshot A");
    btnSlotA.onClick = [this] { audioProcessor.loadSlotA(); btnSlotA.setToggleState(true, juce::dontSendNotification); btnSlotB.setToggleState(false, juce::dontSendNotification); };
    addAndMakeVisible(btnSlotA);
    btnSlotA.setTooltip("Active slot A / recall slot A (spacebar)");

    btnSlotB.setButtonText("B");
    btnSlotB.setColour(juce::TextButton::buttonColourId, juce::Colour(0xff2a2a50));
    btnSlotB.setColour(juce::TextButton::buttonOnColourId, juce::Colour(0xffb366ff));
    btnSlotB.setColour(juce::TextButton::textColourOffId, juce::Colour(0xff8888aa));
    btnSlotB.setColour(juce::TextButton::textColourOnId, juce::Colour(0xffffffff));
    btnSlotB.setClickingTogglesState(false);
    btnSlotB.setRadioGroupId(1001);
    btnSlotB.setTooltip("Load preset snapshot B");
    btnSlotB.onClick = [this] { audioProcessor.loadSlotB(); btnSlotB.setToggleState(true, juce::dontSendNotification); btnSlotA.setToggleState(false, juce::dontSendNotification); };
    addAndMakeVisible(btnSlotB);
    btnSlotB.setTooltip("Active slot B / recall slot B");

    btnSaveAB.setButtonText("SAVE");
    btnSaveAB.setColour(juce::TextButton::buttonColourId, juce::Colour(0xff1a1a30));
    btnSaveAB.setColour(juce::TextButton::textColourOffId, juce::Colour(0xff8888aa));
    btnSaveAB.setTooltip("Save current knob positions to the active slot (A or B)");
    btnSaveAB.onClick = [this] { if (audioProcessor.isSlotA()) audioProcessor.saveSlotA(); else audioProcessor.saveSlotB(); };
    addAndMakeVisible(btnSaveAB);

    // Randomize Preset button ÃƒÆ’Ã†â€™Ãƒâ€ Ã¢â‚¬â„¢ÃƒÆ’Ã¢â‚¬Å¡Ãƒâ€šÃ‚Â¢ÃƒÆ’Ã†â€™Ãƒâ€šÃ‚Â¢ÃƒÆ’Ã‚Â¢ÃƒÂ¢Ã¢â‚¬Å¡Ã‚Â¬Ãƒâ€¦Ã‚Â¡ÃƒÆ’Ã¢â‚¬Å¡Ãƒâ€šÃ‚Â¬ÃƒÆ’Ã†â€™Ãƒâ€šÃ‚Â¢ÃƒÆ’Ã‚Â¢ÃƒÂ¢Ã¢â€šÂ¬Ã…Â¡Ãƒâ€šÃ‚Â¬ÃƒÆ’Ã¢â‚¬Å¡Ãƒâ€šÃ‚Â one-click creative inspiration
    randomizeButton.setButtonText("RND");
    randomizeButton.setColour(juce::TextButton::buttonColourId, juce::Colour(0xff3a2a50));
    randomizeButton.setColour(juce::TextButton::textColourOffId, juce::Colour(0xffb366ff));
    randomizeButton.setTooltip("Randomize all unlocked parameters (Alt+R)");
    randomizeButton.onClick = [this] { audioProcessor.randomizePreset(); };
    addAndMakeVisible(randomizeButton);

    // Theme toggle button
    themeToggleButton.setButtonText(themeDark ? "DARK" : "LIGHT");
    themeToggleButton.setColour(juce::TextButton::buttonColourId, juce::Colour(0xff24244a));
    themeToggleButton.setColour(juce::TextButton::textColourOffId, juce::Colour(0xffb0b0cf));
    themeToggleButton.setTooltip("Toggle dark/light theme palette (Ctrl+T)");
    themeToggleButton.onClick = [this] { themeDark = !themeDark; toggleTheme(); };
    addAndMakeVisible(themeToggleButton);

    // Default: A is active -- snapshot both slots with the restored init
    // state, but ONLY when the processor didn't have saved snapshots
    // restored by setStateInformation: state with an "abSlots" child
    // already carries a saved A/B compare, and the blind reseed would
    // overwrite both slots with the current (identical) live values.
    if (!audioProcessor.hasPersistedABSnapshots())
    {
        btnSlotA.setToggleState(true, juce::dontSendNotification);
        audioProcessor.saveSlotA();
        audioProcessor.saveSlotB();
    }

    // Reflect the recalled active slot even when the persisted pair skips reseeding.
    btnSlotA.setToggleState(audioProcessor.isSlotA(), juce::dontSendNotification);
    btnSlotB.setToggleState(!audioProcessor.isSlotA(), juce::dontSendNotification);

    // Level meter
    addAndMakeVisible(levelMeter);
    startTimerHz(30); // drives timerCallback -> meters read + decay order
}

CorvusFXAudioProcessorEditor::~CorvusFXAudioProcessorEditor()
{
    // An armed MIDI-Learn is editor-lifetime UI state: kill it when the
    // editor closes so a stray CC can't hijack a knob in a later session.
    audioProcessor.stopMidiLearn();
    setLookAndFeel(nullptr);
}

void CorvusFXAudioProcessorEditor::timerCallback()
{
    // Update level meter from processor (audio thread -> message thread via atomics).
    // Decay the processor-side atomics FIRST so the copies below are the
    // authoritative displayed values (a stale peak can't resurrect after silence).
    auto& meters = audioProcessor.levelMeters;
    meters.decayPeaks(0.96f);
    levelMeter.setInputPeakL(meters.inPeakL.load(std::memory_order_relaxed));
    levelMeter.setInputPeakR(meters.inPeakR.load(std::memory_order_relaxed));
    levelMeter.setInputRmsL(meters.inRmsL.load(std::memory_order_relaxed));
    levelMeter.setInputRmsR(meters.inRmsR.load(std::memory_order_relaxed));
    levelMeter.setOutputPeakL(meters.outPeakL.load(std::memory_order_relaxed));
    levelMeter.setOutputPeakR(meters.outPeakR.load(std::memory_order_relaxed));
    levelMeter.setOutputRmsL(meters.outRmsL.load(std::memory_order_relaxed));
    levelMeter.setOutputRmsR(meters.outRmsR.load(std::memory_order_relaxed));
}

bool CorvusFXAudioProcessorEditor::keyPressed(const juce::KeyPress& key)
{
    auto& um = audioProcessor.undoManager;
    if (key.getModifiers().isCommandDown() && key.getKeyCode() == 'Z')
    {
        if (key.getModifiers().isShiftDown())
            um.redo();
        else
            um.undo();
        return true;
    }
    if (key.getModifiers().isCommandDown() && key.getKeyCode() == 'Y')
    {
        um.redo();
        return true;
    }
    if (key.getModifiers().isCommandDown() && key.getKeyCode() == 'T')
    {
        themeDark = !themeDark;
        toggleTheme();
        return true;
    }
    if (key.getModifiers().isAltDown() && key.getKeyCode() == 'R')
    {
        audioProcessor.randomizePreset();
        return true;
    }
    return false;
}

void CorvusFXAudioProcessorEditor::toggleTheme()
{
    themeToggleButton.setButtonText(themeDark ? "DARK" : "LIGHT");
    animatedBackground.setDarkTheme(themeDark);
    distortionSection.setDarkTheme(themeDark);
    chorusSection.setDarkTheme(themeDark);
    delaySection.setDarkTheme(themeDark);
    reverbSection.setDarkTheme(themeDark);
    corvusLookAndFeel.setDarkTheme(themeDark);
    if (themeProperties)
    {
        themeProperties->setValue("themeDark", themeDark);
        themeProperties->saveIfNeeded();
    }
    repaint();
}

void CorvusFXAudioProcessorEditor::paint(juce::Graphics& g)
{
    const bool dark = themeDark;

    // Background
    g.fillAll(dark ? juce::Colour(0xff050510) : juce::Colour(0xfff4f4fa));

    // Vignette
    juce::ColourGradient vig(
        juce::Colours::transparentBlack, getWidth() / 2.0f, getHeight() / 2.0f,
        juce::Colours::black.withAlpha(dark ? 0.3f : 0.08f), 0, 0, true);
    g.setGradientFill(vig);
    g.fillRect(getLocalBounds());

    // Version text
    g.setColour(dark ? juce::Colour(0xff444466) : juce::Colour(0xff999aa8));
    g.setFont(juce::Font(juce::FontOptions(9.0f)));
    g.drawText("CorvusFX v1.0 | Professional Multi-FX Suite",
        getLocalBounds().removeFromBottom(15), juce::Justification::centred, true);
}

void CorvusFXAudioProcessorEditor::resized()
{
    auto area = getLocalBounds();
    animatedBackground.setBounds(area);

    // ÃƒÆ’Ã†â€™Ãƒâ€ Ã¢â‚¬â„¢ÃƒÆ’Ã¢â‚¬Å¡Ãƒâ€šÃ‚Â¢ÃƒÆ’Ã†â€™Ãƒâ€šÃ‚Â¢ÃƒÆ’Ã‚Â¢ÃƒÂ¢Ã¢â€šÂ¬Ã…Â¡Ãƒâ€šÃ‚Â¬ÃƒÆ’Ã¢â‚¬Å¡Ãƒâ€šÃ‚ÂÃƒÆ’Ã†â€™Ãƒâ€šÃ‚Â¢ÃƒÆ’Ã‚Â¢ÃƒÂ¢Ã¢â‚¬Å¡Ã‚Â¬Ãƒâ€¦Ã‚Â¡ÃƒÆ’Ã¢â‚¬Å¡Ãƒâ€šÃ‚Â¬ÃƒÆ’Ã†â€™Ãƒâ€ Ã¢â‚¬â„¢ÃƒÆ’Ã¢â‚¬Å¡Ãƒâ€šÃ‚Â¢ÃƒÆ’Ã†â€™Ãƒâ€šÃ‚Â¢ÃƒÆ’Ã‚Â¢ÃƒÂ¢Ã¢â€šÂ¬Ã…Â¡Ãƒâ€šÃ‚Â¬ÃƒÆ’Ã¢â‚¬Å¡Ãƒâ€šÃ‚ÂÃƒÆ’Ã†â€™Ãƒâ€šÃ‚Â¢ÃƒÆ’Ã‚Â¢ÃƒÂ¢Ã¢â‚¬Å¡Ã‚Â¬Ãƒâ€¦Ã‚Â¡ÃƒÆ’Ã¢â‚¬Å¡Ãƒâ€šÃ‚Â¬ Calculate proportional scaling factor based on reference size 1200x700 ÃƒÆ’Ã†â€™Ãƒâ€ Ã¢â‚¬â„¢ÃƒÆ’Ã¢â‚¬Å¡Ãƒâ€šÃ‚Â¢ÃƒÆ’Ã†â€™Ãƒâ€šÃ‚Â¢ÃƒÆ’Ã‚Â¢ÃƒÂ¢Ã¢â€šÂ¬Ã…Â¡Ãƒâ€šÃ‚Â¬ÃƒÆ’Ã¢â‚¬Å¡Ãƒâ€šÃ‚ÂÃƒÆ’Ã†â€™Ãƒâ€šÃ‚Â¢ÃƒÆ’Ã‚Â¢ÃƒÂ¢Ã¢â‚¬Å¡Ã‚Â¬Ãƒâ€¦Ã‚Â¡ÃƒÆ’Ã¢â‚¬Å¡Ãƒâ€šÃ‚Â¬ÃƒÆ’Ã†â€™Ãƒâ€ Ã¢â‚¬â„¢ÃƒÆ’Ã¢â‚¬Å¡Ãƒâ€šÃ‚Â¢ÃƒÆ’Ã†â€™Ãƒâ€šÃ‚Â¢ÃƒÆ’Ã‚Â¢ÃƒÂ¢Ã¢â€šÂ¬Ã…Â¡Ãƒâ€šÃ‚Â¬ÃƒÆ’Ã¢â‚¬Å¡Ãƒâ€šÃ‚ÂÃƒÆ’Ã†â€™Ãƒâ€šÃ‚Â¢ÃƒÆ’Ã‚Â¢ÃƒÂ¢Ã¢â‚¬Å¡Ã‚Â¬Ãƒâ€¦Ã‚Â¡ÃƒÆ’Ã¢â‚¬Å¡Ãƒâ€šÃ‚Â¬
    // This ensures all layout elements scale smoothly between min (1000x600) and max (1600x900)
    const float refW = 1200.0f;
    const float refH = 700.0f;
    const float scaleW = area.getWidth() / refW;
    const float scaleH = area.getHeight() / refH;
    const float scale = juce::jmin(scaleW, scaleH); // Uniform scaling preserves aspect ratios
    auto sc = [scale](int px) { return juce::roundToInt(px * scale); };

    // Reference-pixel layout constants. scripts/check_editor_layout_async.py
    // parses these names so the rendered geometry stays verifiable at both
    // supported minimum and default sizes; keep the names stable.
    const int kTopSectionRef = 100;
    const int kTitleRef = 60;
    const int kPresetInsetXRef = 160;
    const int kPresetInsetYRef = 5;
    const int kPresetLabelRef = 15;
    const int kPresetButtonRailRef = 290;
    const int kPresetButtonHeightRef = 22;
    const int kPresetButtonMinHeightRef = 16;
    const int kMeterRef = 60;
    const int kFooterRef = 20;
    const int kContentInsetXRef = 20;
    const int kContentInsetYRef = 10;
    const int kRailGapRef = 16;
    const int kRailMinRef = 230;
    const int kRailMaxRef = 300;
    const int kOverallRowRef = 180;
    const int kOverallKnobRef = 150;
    const int kOverallLabelRef = 30;
    const int kMasterDriveRowRef = 100;
    const int kMasterDriveKnobRef = 100;
    const int kMasterDriveLabelRef = 25;
    const int kMasterBypassWidthRef = 100;
    const int kMasterBypassHeightRef = 25;
    const int kMasterSideRowRef = 100;
    const int kMasterSideKnobRef = 80;
    const int kMasterSideGapRef = 20;
    const int kMasterSideLabelRef = 25;
    const int kOutputTrimKnobRef = 70;
    const int kOutputTrimLabelRef = 25;
    const int kRailKnobInsetRef = 40;
    const int kGridGapRef = 15;
    const int kGridRowsRef = 2;
    const float kDelayColumnShare = 0.58f;
    const int kSectionPadXRef = 14;
    const int kSectionPadYRef = 45;
    const int kSectionLabelRef = 22;
    const int kSectionBypassRef = 20;
    const int kSectionBypassGapRef = 8;
    const int kSectionBypassWidthRef = 80;
    const int kSectionMinGapRef = 4;
    const int kSectionMaxGapRef = 14;
    const int kSectionMinKnobRef = 40;
    const int kDistortionMaxKnobRef = 120;
    const int kChorusMaxKnobRef = 80;
    const int kDelayMaxKnobRef = 70;
    const int kReverbMaxKnobRef = 70;

    // ÃƒÆ’Ã†â€™Ãƒâ€ Ã¢â‚¬â„¢ÃƒÆ’Ã¢â‚¬Å¡Ãƒâ€šÃ‚Â¢ÃƒÆ’Ã†â€™Ãƒâ€šÃ‚Â¢ÃƒÆ’Ã‚Â¢ÃƒÂ¢Ã¢â€šÂ¬Ã…Â¡Ãƒâ€šÃ‚Â¬ÃƒÆ’Ã¢â‚¬Å¡Ãƒâ€šÃ‚ÂÃƒÆ’Ã†â€™Ãƒâ€šÃ‚Â¢ÃƒÆ’Ã‚Â¢ÃƒÂ¢Ã¢â‚¬Å¡Ã‚Â¬Ãƒâ€¦Ã‚Â¡ÃƒÆ’Ã¢â‚¬Å¡Ãƒâ€šÃ‚Â¬ÃƒÆ’Ã†â€™Ãƒâ€ Ã¢â‚¬â„¢ÃƒÆ’Ã¢â‚¬Å¡Ãƒâ€šÃ‚Â¢ÃƒÆ’Ã†â€™Ãƒâ€šÃ‚Â¢ÃƒÆ’Ã‚Â¢ÃƒÂ¢Ã¢â€šÂ¬Ã…Â¡Ãƒâ€šÃ‚Â¬ÃƒÆ’Ã¢â‚¬Å¡Ãƒâ€šÃ‚ÂÃƒÆ’Ã†â€™Ãƒâ€šÃ‚Â¢ÃƒÆ’Ã‚Â¢ÃƒÂ¢Ã¢â‚¬Å¡Ã‚Â¬Ãƒâ€¦Ã‚Â¡ÃƒÆ’Ã¢â‚¬Å¡Ãƒâ€šÃ‚Â¬ Top: title + preset ÃƒÆ’Ã†â€™Ãƒâ€ Ã¢â‚¬â„¢ÃƒÆ’Ã¢â‚¬Å¡Ãƒâ€šÃ‚Â¢ÃƒÆ’Ã†â€™Ãƒâ€šÃ‚Â¢ÃƒÆ’Ã‚Â¢ÃƒÂ¢Ã¢â€šÂ¬Ã…Â¡Ãƒâ€šÃ‚Â¬ÃƒÆ’Ã¢â‚¬Å¡Ãƒâ€šÃ‚ÂÃƒÆ’Ã†â€™Ãƒâ€šÃ‚Â¢ÃƒÆ’Ã‚Â¢ÃƒÂ¢Ã¢â‚¬Å¡Ã‚Â¬Ãƒâ€¦Ã‚Â¡ÃƒÆ’Ã¢â‚¬Å¡Ãƒâ€šÃ‚Â¬ÃƒÆ’Ã†â€™Ãƒâ€ Ã¢â‚¬â„¢ÃƒÆ’Ã¢â‚¬Å¡Ãƒâ€šÃ‚Â¢ÃƒÆ’Ã†â€™Ãƒâ€šÃ‚Â¢ÃƒÆ’Ã‚Â¢ÃƒÂ¢Ã¢â€šÂ¬Ã…Â¡Ãƒâ€šÃ‚Â¬ÃƒÆ’Ã¢â‚¬Å¡Ãƒâ€šÃ‚ÂÃƒÆ’Ã†â€™Ãƒâ€šÃ‚Â¢ÃƒÆ’Ã‚Â¢ÃƒÂ¢Ã¢â‚¬Å¡Ã‚Â¬Ãƒâ€¦Ã‚Â¡ÃƒÆ’Ã¢â‚¬Å¡Ãƒâ€šÃ‚Â¬
    auto topSection = area.removeFromTop(sc(kTopSectionRef));
    titleLabel.setBounds(topSection.removeFromTop(sc(kTitleRef)).reduced(sc(20), sc(5)));
    auto presetArea = topSection.reduced(sc(kPresetInsetXRef), sc(kPresetInsetYRef));
    presetLabel.setBounds(presetArea.removeFromTop(sc(kPresetLabelRef)));
    auto presetRow = presetArea;
    // A/B compare buttons -- right of preset selector
    auto abBtnArea = presetRow.removeFromRight(sc(kPresetButtonRailRef));
    int abH = juce::jlimit(sc(kPresetButtonMinHeightRef), sc(kPresetButtonHeightRef),
                           topSection.getBottom() - presetRow.getY());
    int abW = sc(32);
    int topOff = 0;
    btnSlotA.setBounds(abBtnArea.removeFromLeft(abW).withHeight(abH).withTrimmedTop(topOff));
    abBtnArea.removeFromLeft(sc(4));
    btnSlotB.setBounds(abBtnArea.removeFromLeft(abW).withHeight(abH).withTrimmedTop(topOff));
    abBtnArea.removeFromLeft(sc(6));
    btnSaveAB.setBounds(abBtnArea.removeFromLeft(sc(60)).withHeight(abH).withTrimmedTop(topOff));
    abBtnArea.removeFromLeft(sc(8));
    randomizeButton.setBounds(abBtnArea.removeFromLeft(sc(40)).withHeight(abH).withTrimmedTop(topOff));
    abBtnArea.removeFromLeft(sc(4));
    themeToggleButton.setBounds(abBtnArea.removeFromLeft(sc(62)).withHeight(abH).withTrimmedTop(topOff));
    presetSelector.setBounds(presetRow);

    // ÃƒÆ’Ã†â€™Ãƒâ€ Ã¢â‚¬â„¢ÃƒÆ’Ã¢â‚¬Å¡Ãƒâ€šÃ‚Â¢ÃƒÆ’Ã†â€™Ãƒâ€šÃ‚Â¢ÃƒÆ’Ã‚Â¢ÃƒÂ¢Ã¢â€šÂ¬Ã…Â¡Ãƒâ€šÃ‚Â¬ÃƒÆ’Ã¢â‚¬Å¡Ãƒâ€šÃ‚ÂÃƒÆ’Ã†â€™Ãƒâ€šÃ‚Â¢ÃƒÆ’Ã‚Â¢ÃƒÂ¢Ã¢â‚¬Å¡Ã‚Â¬Ãƒâ€¦Ã‚Â¡ÃƒÆ’Ã¢â‚¬Å¡Ãƒâ€šÃ‚Â¬ÃƒÆ’Ã†â€™Ãƒâ€ Ã¢â‚¬â„¢ÃƒÆ’Ã¢â‚¬Å¡Ãƒâ€šÃ‚Â¢ÃƒÆ’Ã†â€™Ãƒâ€šÃ‚Â¢ÃƒÆ’Ã‚Â¢ÃƒÂ¢Ã¢â€šÂ¬Ã…Â¡Ãƒâ€šÃ‚Â¬ÃƒÆ’Ã¢â‚¬Å¡Ãƒâ€šÃ‚ÂÃƒÆ’Ã†â€™Ãƒâ€šÃ‚Â¢ÃƒÆ’Ã‚Â¢ÃƒÂ¢Ã¢â‚¬Å¡Ã‚Â¬Ãƒâ€¦Ã‚Â¡ÃƒÆ’Ã¢â‚¬Å¡Ãƒâ€šÃ‚Â¬ Level Meter (between title/preset and overall knob) ÃƒÆ’Ã†â€™Ãƒâ€ Ã¢â‚¬â„¢ÃƒÆ’Ã¢â‚¬Å¡Ãƒâ€šÃ‚Â¢ÃƒÆ’Ã†â€™Ãƒâ€šÃ‚Â¢ÃƒÆ’Ã‚Â¢ÃƒÂ¢Ã¢â€šÂ¬Ã…Â¡Ãƒâ€šÃ‚Â¬ÃƒÆ’Ã¢â‚¬Å¡Ãƒâ€šÃ‚ÂÃƒÆ’Ã†â€™Ãƒâ€šÃ‚Â¢ÃƒÆ’Ã‚Â¢ÃƒÂ¢Ã¢â‚¬Å¡Ã‚Â¬Ãƒâ€¦Ã‚Â¡ÃƒÆ’Ã¢â‚¬Å¡Ãƒâ€šÃ‚Â¬ÃƒÆ’Ã†â€™Ãƒâ€ Ã¢â‚¬â„¢ÃƒÆ’Ã¢â‚¬Å¡Ãƒâ€šÃ‚Â¢ÃƒÆ’Ã†â€™Ãƒâ€šÃ‚Â¢ÃƒÆ’Ã‚Â¢ÃƒÂ¢Ã¢â€šÂ¬Ã…Â¡Ãƒâ€šÃ‚Â¬ÃƒÆ’Ã¢â‚¬Å¡Ãƒâ€šÃ‚ÂÃƒÆ’Ã†â€™Ãƒâ€šÃ‚Â¢ÃƒÆ’Ã‚Â¢ÃƒÂ¢Ã¢â‚¬Å¡Ã‚Â¬Ãƒâ€¦Ã‚Â¡ÃƒÆ’Ã¢â‚¬Å¡Ãƒâ€šÃ‚Â¬
    auto meterArea = area.removeFromTop(sc(kMeterRef)).reduced(area.getWidth() / 4, 0);
    levelMeter.setBounds(meterArea);

    area.removeFromBottom(sc(kFooterRef)); // version text space
    area.reduce(sc(kContentInsetXRef), sc(kContentInsetYRef));

    // Carve the FX grid out of the right-hand side FIRST, then let the
    // master controls stack in the remaining left rail. This is what keeps
    // the 2x2 grid at its full available height instead of inheriting
    // whatever is left after the master rows (the old 20px collapse).
    const int railGap = sc(kRailGapRef);
    const int railW = juce::jlimit(sc(kRailMinRef), area.getWidth() / 3,
                                   sc(kRailMaxRef));
    const int gridW = juce::jmax(1, area.getWidth() - railW - railGap);
    auto gridArea = area.removeFromRight(gridW);
    area.removeFromRight(railGap);

    // ÃƒÆ’Ã†â€™Ãƒâ€ Ã¢â‚¬â„¢ÃƒÆ’Ã¢â‚¬Å¡Ãƒâ€šÃ‚Â¢ÃƒÆ’Ã†â€™Ãƒâ€šÃ‚Â¢ÃƒÆ’Ã‚Â¢ÃƒÂ¢Ã¢â€šÂ¬Ã…Â¡Ãƒâ€šÃ‚Â¬ÃƒÆ’Ã¢â‚¬Å¡Ãƒâ€šÃ‚ÂÃƒÆ’Ã†â€™Ãƒâ€šÃ‚Â¢ÃƒÆ’Ã‚Â¢ÃƒÂ¢Ã¢â‚¬Å¡Ã‚Â¬Ãƒâ€¦Ã‚Â¡ÃƒÆ’Ã¢â‚¬Å¡Ãƒâ€šÃ‚Â¬ÃƒÆ’Ã†â€™Ãƒâ€ Ã¢â‚¬â„¢ÃƒÆ’Ã¢â‚¬Å¡Ãƒâ€šÃ‚Â¢ÃƒÆ’Ã†â€™Ãƒâ€šÃ‚Â¢ÃƒÆ’Ã‚Â¢ÃƒÂ¢Ã¢â€šÂ¬Ã…Â¡Ãƒâ€šÃ‚Â¬ÃƒÆ’Ã¢â‚¬Å¡Ãƒâ€šÃ‚ÂÃƒÆ’Ã†â€™Ãƒâ€šÃ‚Â¢ÃƒÆ’Ã‚Â¢ÃƒÂ¢Ã¢â‚¬Å¡Ã‚Â¬Ãƒâ€¦Ã‚Â¡ÃƒÆ’Ã¢â‚¬Å¡Ãƒâ€šÃ‚Â¬ Overall knob (centered hero) ÃƒÆ’Ã†â€™Ãƒâ€ Ã¢â‚¬â„¢ÃƒÆ’Ã¢â‚¬Å¡Ãƒâ€šÃ‚Â¢ÃƒÆ’Ã†â€™Ãƒâ€šÃ‚Â¢ÃƒÆ’Ã‚Â¢ÃƒÂ¢Ã¢â€šÂ¬Ã…Â¡Ãƒâ€šÃ‚Â¬ÃƒÆ’Ã¢â‚¬Å¡Ãƒâ€šÃ‚ÂÃƒÆ’Ã†â€™Ãƒâ€šÃ‚Â¢ÃƒÆ’Ã‚Â¢ÃƒÂ¢Ã¢â‚¬Å¡Ã‚Â¬Ãƒâ€¦Ã‚Â¡ÃƒÆ’Ã¢â‚¬Å¡Ãƒâ€šÃ‚Â¬ÃƒÆ’Ã†â€™Ãƒâ€ Ã¢â‚¬â„¢ÃƒÆ’Ã¢â‚¬Å¡Ãƒâ€šÃ‚Â¢ÃƒÆ’Ã†â€™Ãƒâ€šÃ‚Â¢ÃƒÆ’Ã‚Â¢ÃƒÂ¢Ã¢â€šÂ¬Ã…Â¡Ãƒâ€šÃ‚Â¬ÃƒÆ’Ã¢â‚¬Å¡Ãƒâ€šÃ‚ÂÃƒÆ’Ã†â€™Ãƒâ€šÃ‚Â¢ÃƒÆ’Ã‚Â¢ÃƒÂ¢Ã¢â‚¬Å¡Ã‚Â¬Ãƒâ€¦Ã‚Â¡ÃƒÆ’Ã¢â‚¬Å¡Ãƒâ€šÃ‚Â¬
    auto overallRow = area.removeFromTop(sc(kOverallRowRef));
    int oSize = juce::jmin(sc(kOverallKnobRef), area.getWidth() - sc(kRailKnobInsetRef));
    oSize = juce::jmin(oSize, overallRow.getHeight() - sc(kOverallLabelRef));
    oSize = juce::jmax(1, oSize);
    auto oArea = overallRow.withSizeKeepingCentre(oSize, oSize + sc(kOverallLabelRef));
    overallKnob.setBounds(oArea.removeFromTop(oSize));
    overallLabel.setBounds(oArea);

    // ÃƒÆ’Ã†â€™Ãƒâ€ Ã¢â‚¬â„¢ÃƒÆ’Ã¢â‚¬Å¡Ãƒâ€šÃ‚Â¢ÃƒÆ’Ã†â€™Ãƒâ€šÃ‚Â¢ÃƒÆ’Ã‚Â¢ÃƒÂ¢Ã¢â€šÂ¬Ã…Â¡Ãƒâ€šÃ‚Â¬ÃƒÆ’Ã¢â‚¬Å¡Ãƒâ€šÃ‚ÂÃƒÆ’Ã†â€™Ãƒâ€šÃ‚Â¢ÃƒÆ’Ã‚Â¢ÃƒÂ¢Ã¢â‚¬Å¡Ã‚Â¬Ãƒâ€¦Ã‚Â¡ÃƒÆ’Ã¢â‚¬Å¡Ãƒâ€šÃ‚Â¬ÃƒÆ’Ã†â€™Ãƒâ€ Ã¢â‚¬â„¢ÃƒÆ’Ã¢â‚¬Å¡Ãƒâ€šÃ‚Â¢ÃƒÆ’Ã†â€™Ãƒâ€šÃ‚Â¢ÃƒÆ’Ã‚Â¢ÃƒÂ¢Ã¢â€šÂ¬Ã…Â¡Ãƒâ€šÃ‚Â¬ÃƒÆ’Ã¢â‚¬Å¡Ãƒâ€šÃ‚ÂÃƒÆ’Ã†â€™Ãƒâ€šÃ‚Â¢ÃƒÆ’Ã‚Â¢ÃƒÂ¢Ã¢â‚¬Å¡Ã‚Â¬Ãƒâ€¦Ã‚Â¡ÃƒÆ’Ã¢â‚¬Å¡Ãƒâ€šÃ‚Â¬ Master Drive knob (below Overall) ÃƒÆ’Ã†â€™Ãƒâ€ Ã¢â‚¬â„¢ÃƒÆ’Ã¢â‚¬Å¡Ãƒâ€šÃ‚Â¢ÃƒÆ’Ã†â€™Ãƒâ€šÃ‚Â¢ÃƒÆ’Ã‚Â¢ÃƒÂ¢Ã¢â€šÂ¬Ã…Â¡Ãƒâ€šÃ‚Â¬ÃƒÆ’Ã¢â‚¬Å¡Ãƒâ€šÃ‚ÂÃƒÆ’Ã†â€™Ãƒâ€šÃ‚Â¢ÃƒÆ’Ã‚Â¢ÃƒÂ¢Ã¢â‚¬Å¡Ã‚Â¬Ãƒâ€¦Ã‚Â¡ÃƒÆ’Ã¢â‚¬Å¡Ãƒâ€šÃ‚Â¬ÃƒÆ’Ã†â€™Ãƒâ€ Ã¢â‚¬â„¢ÃƒÆ’Ã¢â‚¬Å¡Ãƒâ€šÃ‚Â¢ÃƒÆ’Ã†â€™Ãƒâ€šÃ‚Â¢ÃƒÆ’Ã‚Â¢ÃƒÂ¢Ã¢â€šÂ¬Ã…Â¡Ãƒâ€šÃ‚Â¬ÃƒÆ’Ã¢â‚¬Å¡Ãƒâ€šÃ‚ÂÃƒÆ’Ã†â€™Ãƒâ€šÃ‚Â¢ÃƒÆ’Ã‚Â¢ÃƒÂ¢Ã¢â‚¬Å¡Ã‚Â¬Ãƒâ€¦Ã‚Â¡ÃƒÆ’Ã¢â‚¬Å¡Ãƒâ€šÃ‚Â¬
    auto masterDriveRow = area.removeFromTop(sc(kMasterDriveRowRef));
    auto mdrRow = masterDriveRow.reduced(sc(kRailKnobInsetRef), 0);
    auto mbBypassArea = mdrRow.removeFromRight(
        juce::jmin(sc(kMasterBypassWidthRef), mdrRow.getWidth() / 2));
    int mSize = juce::jmin(sc(kMasterDriveKnobRef),
                           masterDriveRow.getHeight() - sc(kMasterDriveLabelRef));
    mSize = juce::jmin(mSize, mdrRow.getWidth() - sc(10));
    mSize = juce::jmax(1, mSize);
    auto mArea = mdrRow.withSizeKeepingCentre(mSize,
                                              mSize + sc(kMasterDriveLabelRef));
    masterDriveKnob.setBounds(mArea.removeFromTop(mSize));
    masterDriveLabel.setBounds(mArea);

    // Master bypass button ÃƒÆ’Ã†â€™Ãƒâ€ Ã¢â‚¬â„¢ÃƒÆ’Ã¢â‚¬Å¡Ãƒâ€šÃ‚Â¢ÃƒÆ’Ã†â€™Ãƒâ€šÃ‚Â¢ÃƒÆ’Ã‚Â¢ÃƒÂ¢Ã¢â‚¬Å¡Ã‚Â¬Ãƒâ€¦Ã‚Â¡ÃƒÆ’Ã¢â‚¬Å¡Ãƒâ€šÃ‚Â¬ÃƒÆ’Ã†â€™Ãƒâ€šÃ‚Â¢ÃƒÆ’Ã‚Â¢ÃƒÂ¢Ã¢â€šÂ¬Ã…Â¡Ãƒâ€šÃ‚Â¬ÃƒÆ’Ã¢â‚¬Å¡Ãƒâ€šÃ‚Â right-aligned in the same row
    masterBypassButton.setBounds(mbBypassArea.removeFromTop(
        juce::jmin(sc(kMasterBypassHeightRef), mbBypassArea.getHeight())));

    area.removeFromTop(sc(10));

    // ÃƒÆ’Ã†â€™Ãƒâ€ Ã¢â‚¬â„¢ÃƒÆ’Ã¢â‚¬Å¡Ãƒâ€šÃ‚Â¢ÃƒÆ’Ã†â€™Ãƒâ€šÃ‚Â¢ÃƒÆ’Ã‚Â¢ÃƒÂ¢Ã¢â€šÂ¬Ã…Â¡Ãƒâ€šÃ‚Â¬ÃƒÆ’Ã¢â‚¬Å¡Ãƒâ€šÃ‚ÂÃƒÆ’Ã†â€™Ãƒâ€šÃ‚Â¢ÃƒÆ’Ã‚Â¢ÃƒÂ¢Ã¢â‚¬Å¡Ã‚Â¬Ãƒâ€¦Ã‚Â¡ÃƒÆ’Ã¢â‚¬Å¡Ãƒâ€šÃ‚Â¬ÃƒÆ’Ã†â€™Ãƒâ€ Ã¢â‚¬â„¢ÃƒÆ’Ã¢â‚¬Å¡Ãƒâ€šÃ‚Â¢ÃƒÆ’Ã†â€™Ãƒâ€šÃ‚Â¢ÃƒÆ’Ã‚Â¢ÃƒÂ¢Ã¢â€šÂ¬Ã…Â¡Ãƒâ€šÃ‚Â¬ÃƒÆ’Ã¢â‚¬Å¡Ãƒâ€šÃ‚ÂÃƒÆ’Ã†â€™Ãƒâ€šÃ‚Â¢ÃƒÆ’Ã‚Â¢ÃƒÂ¢Ã¢â‚¬Å¡Ã‚Â¬Ãƒâ€¦Ã‚Â¡ÃƒÆ’Ã¢â‚¬Å¡Ãƒâ€šÃ‚Â¬ Master Width / Mid Drive / Side Drive knobs (below Master Drive) ÃƒÆ’Ã†â€™Ãƒâ€ Ã¢â‚¬â„¢ÃƒÆ’Ã¢â‚¬Å¡Ãƒâ€šÃ‚Â¢ÃƒÆ’Ã†â€™Ãƒâ€šÃ‚Â¢ÃƒÆ’Ã‚Â¢ÃƒÂ¢Ã¢â€šÂ¬Ã…Â¡Ãƒâ€šÃ‚Â¬ÃƒÆ’Ã¢â‚¬Å¡Ãƒâ€šÃ‚ÂÃƒÆ’Ã†â€™Ãƒâ€šÃ‚Â¢ÃƒÆ’Ã‚Â¢ÃƒÂ¢Ã¢â‚¬Å¡Ã‚Â¬Ãƒâ€¦Ã‚Â¡ÃƒÆ’Ã¢â‚¬Å¡Ãƒâ€šÃ‚Â¬ÃƒÆ’Ã†â€™Ãƒâ€ Ã¢â‚¬â„¢ÃƒÆ’Ã¢â‚¬Å¡Ãƒâ€šÃ‚Â¢ÃƒÆ’Ã†â€™Ãƒâ€šÃ‚Â¢ÃƒÆ’Ã‚Â¢ÃƒÂ¢Ã¢â€šÂ¬Ã…Â¡Ãƒâ€šÃ‚Â¬ÃƒÆ’Ã¢â‚¬Å¡Ãƒâ€šÃ‚ÂÃƒÆ’Ã†â€™Ãƒâ€šÃ‚Â¢ÃƒÆ’Ã‚Â¢ÃƒÂ¢Ã¢â‚¬Å¡Ã‚Â¬Ãƒâ€¦Ã‚Â¡ÃƒÆ’Ã¢â‚¬Å¡Ãƒâ€šÃ‚Â¬
    auto masterMSSRow = area.removeFromTop(sc(kMasterSideRowRef));
    int msGap = sc(kMasterSideGapRef);
    int msSize = juce::jmin(sc(kMasterSideKnobRef),
                            (masterMSSRow.getWidth() - msGap * 2) / 3);
    msSize = juce::jmin(msSize, masterMSSRow.getHeight() - sc(kMasterSideLabelRef));
    msSize = juce::jmax(1, msSize);
    int msTotalW = msSize * 3 + msGap * 2;
    auto msStart = masterMSSRow.withSizeKeepingCentre(msTotalW,
                                                      msSize + sc(kMasterSideLabelRef));
    
    // Width knob
    auto msWidthArea = msStart.removeFromLeft(msSize);
    masterWidthKnob.setBounds(msWidthArea.removeFromTop(msSize));
    masterWidthLabel.setBounds(msWidthArea);
    
    msStart.removeFromLeft(msGap);
    
    // Mid Drive knob
    auto msMidArea = msStart.removeFromLeft(msSize);
    masterMidDriveKnob.setBounds(msMidArea.removeFromTop(msSize));
    masterMidDriveLabel.setBounds(msMidArea);
    
    msStart.removeFromLeft(msGap);
    
    // Side Drive knob
    auto msSideArea = msStart.removeFromLeft(msSize);
    masterSideDriveKnob.setBounds(msSideArea.removeFromTop(msSize));
    masterSideDriveLabel.setBounds(msSideArea);

    // ÃƒÆ’Ã†â€™Ãƒâ€ Ã¢â‚¬â„¢ÃƒÆ’Ã¢â‚¬Å¡Ãƒâ€šÃ‚Â¢ÃƒÆ’Ã†â€™Ãƒâ€šÃ‚Â¢ÃƒÆ’Ã‚Â¢ÃƒÂ¢Ã¢â€šÂ¬Ã…Â¡Ãƒâ€šÃ‚Â¬ÃƒÆ’Ã¢â‚¬Å¡Ãƒâ€šÃ‚ÂÃƒÆ’Ã†â€™Ãƒâ€šÃ‚Â¢ÃƒÆ’Ã‚Â¢ÃƒÂ¢Ã¢â‚¬Å¡Ã‚Â¬Ãƒâ€¦Ã‚Â¡ÃƒÆ’Ã¢â‚¬Å¡Ãƒâ€šÃ‚Â¬ÃƒÆ’Ã†â€™Ãƒâ€ Ã¢â‚¬â„¢ÃƒÆ’Ã¢â‚¬Å¡Ãƒâ€šÃ‚Â¢ÃƒÆ’Ã†â€™Ãƒâ€šÃ‚Â¢ÃƒÆ’Ã‚Â¢ÃƒÂ¢Ã¢â€šÂ¬Ã…Â¡Ãƒâ€šÃ‚Â¬ÃƒÆ’Ã¢â‚¬Å¡Ãƒâ€šÃ‚ÂÃƒÆ’Ã†â€™Ãƒâ€šÃ‚Â¢ÃƒÆ’Ã‚Â¢ÃƒÂ¢Ã¢â‚¬Å¡Ã‚Â¬Ãƒâ€¦Ã‚Â¡ÃƒÆ’Ã¢â‚¬Å¡Ãƒâ€šÃ‚Â¬ Output Trim knob (below Width/Mid/Side, centered)
    auto trimRow = area;
    int trimSize = juce::jmin(sc(kOutputTrimKnobRef),
                              trimRow.getWidth() - sc(kRailKnobInsetRef));
    trimSize = juce::jmin(trimSize, trimRow.getHeight() - sc(kOutputTrimLabelRef));
    trimSize = juce::jmax(1, trimSize);
    auto trimArea = trimRow.withSizeKeepingCentre(trimSize,
                                                  trimSize + sc(kOutputTrimLabelRef));
    outputTrimKnob.setBounds(trimArea.removeFromTop(trimSize));
    outputTrimLabel.setBounds(trimArea);

    // ÃƒÆ’Ã†â€™Ãƒâ€ Ã¢â‚¬â„¢ÃƒÆ’Ã¢â‚¬Å¡Ãƒâ€šÃ‚Â¢ÃƒÆ’Ã†â€™Ãƒâ€šÃ‚Â¢ÃƒÆ’Ã‚Â¢ÃƒÂ¢Ã¢â€šÂ¬Ã…Â¡Ãƒâ€šÃ‚Â¬ÃƒÆ’Ã¢â‚¬Å¡Ãƒâ€šÃ‚ÂÃƒÆ’Ã†â€™Ãƒâ€šÃ‚Â¢ÃƒÆ’Ã‚Â¢ÃƒÂ¢Ã¢â‚¬Å¡Ã‚Â¬Ãƒâ€¦Ã‚Â¡ÃƒÆ’Ã¢â‚¬Å¡Ãƒâ€šÃ‚Â¬ÃƒÆ’Ã†â€™Ãƒâ€ Ã¢â‚¬â„¢ÃƒÆ’Ã¢â‚¬Å¡Ãƒâ€šÃ‚Â¢ÃƒÆ’Ã†â€™Ãƒâ€šÃ‚Â¢ÃƒÆ’Ã‚Â¢ÃƒÂ¢Ã¢â€šÂ¬Ã…Â¡Ãƒâ€šÃ‚Â¬ÃƒÆ’Ã¢â‚¬Å¡Ãƒâ€šÃ‚ÂÃƒÆ’Ã†â€™Ãƒâ€šÃ‚Â¢ÃƒÆ’Ã‚Â¢ÃƒÂ¢Ã¢â‚¬Å¡Ã‚Â¬Ãƒâ€¦Ã‚Â¡ÃƒÆ’Ã¢â‚¬Å¡Ãƒâ€šÃ‚Â¬ 2x2 grid of effect sections ÃƒÆ’Ã†â€™Ãƒâ€ Ã¢â‚¬â„¢ÃƒÆ’Ã¢â‚¬Å¡Ãƒâ€šÃ‚Â¢ÃƒÆ’Ã†â€™Ãƒâ€šÃ‚Â¢ÃƒÆ’Ã‚Â¢ÃƒÂ¢Ã¢â€šÂ¬Ã…Â¡Ãƒâ€šÃ‚Â¬ÃƒÆ’Ã¢â‚¬Å¡Ãƒâ€šÃ‚ÂÃƒÆ’Ã†â€™Ãƒâ€šÃ‚Â¢ÃƒÆ’Ã‚Â¢ÃƒÂ¢Ã¢â‚¬Å¡Ã‚Â¬Ãƒâ€¦Ã‚Â¡ÃƒÆ’Ã¢â‚¬Å¡Ãƒâ€šÃ‚Â¬ÃƒÆ’Ã†â€™Ãƒâ€ Ã¢â‚¬â„¢ÃƒÆ’Ã¢â‚¬Å¡Ãƒâ€šÃ‚Â¢ÃƒÆ’Ã†â€™Ãƒâ€šÃ‚Â¢ÃƒÆ’Ã‚Â¢ÃƒÂ¢Ã¢â€šÂ¬Ã…Â¡Ãƒâ€šÃ‚Â¬ÃƒÆ’Ã¢â‚¬Å¡Ãƒâ€šÃ‚ÂÃƒÆ’Ã†â€™Ãƒâ€šÃ‚Â¢ÃƒÆ’Ã‚Â¢ÃƒÂ¢Ã¢â‚¬Å¡Ã‚Â¬Ãƒâ€¦Ã‚Â¡ÃƒÆ’Ã¢â‚¬Å¡Ãƒâ€šÃ‚Â¬
    // The FX grid owns the full height of the right-hand area. Section
    // rectangles are derived from that area, never from a fixed claim.
    const int gap = juce::jmax(1, sc(kGridGapRef));
    const int secH = juce::jmax(1, (gridArea.getHeight() - gap) / kGridRowsRef);
    auto topFxRow = gridArea.removeFromTop(secH);
    const int topW = juce::jmax(1, (topFxRow.getWidth() - gap) / 2);

    // Explicit per-section layout: reserve the bypass strip first, then
    // divide the remaining width/height among the knob columns. Knob sizes
    // are clamped by the available rectangle so labels and bypass always
    // retain positive, usable bounds.
    auto reserveBypass = [&](juce::Rectangle<int> content,
                             juce::Component& button)
    {
        const int bypH = juce::jmax(sc(kSectionBypassRef), 16);
        auto byRow = content.removeFromBottom(bypH);
        content.removeFromBottom(sc(kSectionBypassGapRef));
        button.setBounds(byRow.withSizeKeepingCentre(
            juce::jmin(byRow.getWidth(), sc(kSectionBypassWidthRef)), bypH));
        return content;
    };

    auto layoutSection = [&](
        juce::Rectangle<int> section, int maxKnob,
        std::initializer_list<std::pair<AnimatedKnob*, juce::Label*>> columns,
        juce::Component& bypass)
    {
        auto content = section.reduced(sc(kSectionPadXRef), sc(kSectionPadYRef));
        content = reserveBypass(content, bypass);
        const int labelH = juce::jmax(sc(kSectionLabelRef), 14);
        const int n = static_cast<int>(columns.size());
        int gapX = juce::jlimit(sc(kSectionMinGapRef), sc(kSectionMaxGapRef),
            (content.getWidth() - n * sc(kSectionMinKnobRef))
                / juce::jmax(1, n + 1));
        int knobSize = juce::jmin(maxKnob,
            (content.getWidth() - gapX * (n + 1)) / juce::jmax(1, n));
        knobSize = juce::jmin(knobSize,
            juce::jmax(1, content.getHeight() - labelH));
        knobSize = juce::jmax(1, knobSize);
        const int totalW = knobSize * n + gapX * (n + 1);
        auto row = content.withSizeKeepingCentre(totalW, knobSize + labelH);
        row.removeFromLeft(gapX);
        for (auto& entry : columns)
        {
            auto col = row.removeFromLeft(knobSize);
            entry.first->setBounds(col.removeFromTop(knobSize));
            entry.second->setBounds(col.removeFromTop(labelH));
            row.removeFromLeft(gapX);
        }
    };

    // Distortion (top-left)
    auto distArea = topFxRow.removeFromLeft(topW);
    distortionSection.setBounds(distArea);
    layoutSection(distArea, sc(kDistortionMaxKnobRef),
                  { { &fatnessKnob, &fatnessLabel } },
                  distortionBypassButton);

    topFxRow.removeFromLeft(gap);

    // Chorus (top-right) - 3 knobs horizontal
    auto chorArea = topFxRow;
    chorusSection.setBounds(chorArea);
    layoutSection(chorArea, sc(kChorusMaxKnobRef),
                  { { &chorusDepthKnob, &chorusDepthLabel },
                    { &chorusRateKnob, &chorusRateLabel },
                    { &chorusMixKnob, &chorusMixLabel } },
                  chorusBypassButton);

    // === BOTTOM ROW ===
    auto botRow = gridArea;
    botRow.removeFromTop(gap);

    // Delay (bottom-left) - 5 knobs horizontal. The bottom row gives delay
    // more width than reverb because delay carries five columns plus its
    // bypass strip.
    const int delayW = juce::roundToInt(
        (botRow.getWidth() - gap) * kDelayColumnShare);
    auto delArea = botRow.removeFromLeft(delayW);
    delaySection.setBounds(delArea);
    layoutSection(delArea, sc(kDelayMaxKnobRef),
                  { { &delayTimeKnob, &delayTimeLabel },
                    { &delayFeedbackKnob, &delayFeedbackLabel },
                    { &delayMixKnob, &delayMixLabel },
                    { &delayDampingKnob, &delayDampingLabel },
                    { &delayModKnob, &delayModLabel } },
                  delayBypassButton);

    botRow.removeFromLeft(gap);

    // Reverb (bottom-right) - 4 knobs horizontal
    auto revArea = botRow;
    reverbSection.setBounds(revArea);
    layoutSection(revArea, sc(kReverbMaxKnobRef),
                  { { &reverbSizeKnob, &reverbSizeLabel },
                    { &reverbDampingKnob, &reverbDampingLabel },
                    { &reverbMixKnob, &reverbMixLabel },
                    { &reverbModKnob, &reverbModLabel } },
                  reverbBypassButton);
}
