#include "PluginProcessor.h"
#include "PluginEditor.h"

CorvusFXAudioProcessorEditor::CorvusFXAudioProcessorEditor(CorvusFXAudioProcessor& p)
    : AudioProcessorEditor(&p), audioProcessor(p),
    distortionSection("DISTORTION", juce::Colour(0xffff6b35)),
    chorusSection("CHORUS", juce::Colour(0xff4ecdc4)),
    delaySection("DELAY", juce::Colour(0xfff7b731)),
    reverbSection("REVERB", juce::Colour(0xffb366ff))
{
    setLookAndFeel(&corvusLookAndFeel);
    setSize(1200, 700);
    setResizable(true, true);
    setResizeLimits(1000, 600, 1600, 900);

    addAndMakeVisible(animatedBackground);
    animatedBackground.toBack();

    titleLabel.setText("CORVUS FX", juce::dontSendNotification);
    titleLabel.setFont(juce::Font(52.0f, juce::Font::bold));
    titleLabel.setJustificationType(juce::Justification::centred);
    titleLabel.setColour(juce::Label::textColourId, juce::Colour(0xffb366ff));
    addAndMakeVisible(titleLabel);

    presetLabel.setText("PRESET", juce::dontSendNotification);
    presetLabel.setFont(juce::Font(12.0f, juce::Font::bold));
    presetLabel.setJustificationType(juce::Justification::centred);
    presetLabel.setColour(juce::Label::textColourId, juce::Colour(0xff888899));
    addAndMakeVisible(presetLabel);

    static const char* presetNames[] = {
        "Clean Sparkle","Warm Glow","Dreamy Space","Thick Sauce",
        "Crystal Shimmer","Deep Echo","Vintage Vibe","Cosmic Wide",
        "Subtle Glue","Aggressive Drive","Lush Pad","Tight Punch",
        "Silk Thread","Molten Core","Event Horizon","Sunspot",
        "Nebula Drift","Iron Press","Glass Canon","Air Lift",
        "Cozy Hiss","Tube Glow","Shimmerfall","Obliterator"
    };
    
    // Factory preset categorization: grouped by vibe with disabled separator items
    // Category 1: CLEAN — transparent enhancement, pristine highs (6 presets)
    presetSelector.addItem("═══ CLEAN ═══", 1);   presetSelector.setItemEnabled(1, false);
    presetSelector.addItem("Clean Sparkle", 2);
    presetSelector.addItem("Crystal Shimmer", 3);
    presetSelector.addItem("Silk Thread", 4);
    presetSelector.addItem("Subtle Glue", 5);
    presetSelector.addItem("Glass Canon", 6);
    presetSelector.addItem("Air Lift", 7);
    
    // Category 2: WARM — analog-style saturation, musical thickening (6 presets)
    presetSelector.addItem("═══ WARM ═══", 8);    presetSelector.setItemEnabled(8, false);
    presetSelector.addItem("Warm Glow", 9);
    presetSelector.addItem("Vintage Vibe", 10);
    presetSelector.addItem("Thick Sauce", 11);
    presetSelector.addItem("Tight Punch", 12);
    presetSelector.addItem("Cozy Hiss", 13);
    presetSelector.addItem("Tube Glow", 14);
    
    // Category 3: CREATIVE — modulation-forward, sound design (6 presets)
    presetSelector.addItem("═══ CREATIVE ═══", 15); presetSelector.setItemEnabled(15, false);
    presetSelector.addItem("Dreamy Space", 16);
    presetSelector.addItem("Cosmic Wide", 17);
    presetSelector.addItem("Molten Core", 18);
    presetSelector.addItem("Sunspot", 19);
    presetSelector.addItem("Nebula Drift", 20);
    presetSelector.addItem("Shimmerfall", 21);
    
    // Category 4: EXTREME — aggressive, heavy processing (6 presets)
    presetSelector.addItem("═══ EXTREME ═══", 22); presetSelector.setItemEnabled(22, false);
    presetSelector.addItem("Deep Echo", 23);
    presetSelector.addItem("Aggressive Drive", 24);
    presetSelector.addItem("Lush Pad", 25);
    presetSelector.addItem("Event Horizon", 26);
    presetSelector.addItem("Iron Press", 27);
    presetSelector.addItem("Obliterator", 28);
    
    presetSelector.setSelectedId(2); // Default to Clean Sparkle (first actual preset)
    presetSelector.setTooltip("Select factory preset — 24 curated sounds from clean enhancement to extreme sound design");
    addAndMakeVisible(presetSelector);

    auto setupKnob = [this](AnimatedKnob& k, juce::Label& l, const juce::String& txt, const juce::String& tooltip = "") {
        k.setTextBoxStyle(juce::Slider::TextBoxBelow, false, 70, 18);
        k.setColour(juce::Slider::textBoxTextColourId, juce::Colour(0xffc0c0d0));
        k.setColour(juce::Slider::textBoxBackgroundColourId, juce::Colour(0xff0c0c1a));
        k.setColour(juce::Slider::textBoxOutlineColourId, juce::Colour(0xff2a2a50));
        if (tooltip.isNotEmpty())
            k.setTooltip(tooltip);
        addAndMakeVisible(k);
        l.setText(txt, juce::dontSendNotification);
        l.setFont(juce::Font(11.0f, juce::Font::bold));
        l.setJustificationType(juce::Justification::centred);
        l.setColour(juce::Label::textColourId, juce::Colour(0xff999aaa));
        addAndMakeVisible(l);
        };

    setupKnob(overallKnob, overallLabel, "OVERALL", "Global wet/dry mix — blends the full effect chain with the dry signal");
    overallLabel.setFont(juce::Font(14.0f, juce::Font::bold));
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
    distortionBypassButton.setTooltip("Bypass the distortion module entirely — click-free crossfade");

    addAndMakeVisible(chorusBypassButton);
    chorusBypassButton.setButtonText("BYPASS");
    chorusBypassButton.setColour(juce::TextButton::buttonColourId, juce::Colour(0xff182030));
    chorusBypassButton.setColour(juce::TextButton::buttonOnColourId, juce::Colour(0xff223344));
    chorusBypassButton.setColour(juce::TextButton::textColourOffId, juce::Colour(0xff6688aa));
    chorusBypassButton.setColour(juce::TextButton::textColourOnId, juce::Colour(0xff88aacc));
    chorusBypassButton.setTooltip("Bypass the chorus module entirely — click-free crossfade");

    addAndMakeVisible(delayBypassButton);
    delayBypassButton.setButtonText("BYPASS");
    delayBypassButton.setColour(juce::TextButton::buttonColourId, juce::Colour(0xff1a3020));
    delayBypassButton.setColour(juce::TextButton::buttonOnColourId, juce::Colour(0xff224433));
    delayBypassButton.setColour(juce::TextButton::textColourOffId, juce::Colour(0xff66aa88));
    delayBypassButton.setColour(juce::TextButton::textColourOnId, juce::Colour(0xff88ccaa));
    delayBypassButton.setTooltip("Bypass the delay module entirely — click-free crossfade");

    addAndMakeVisible(reverbBypassButton);
    reverbBypassButton.setButtonText("BYPASS");
    reverbBypassButton.setColour(juce::TextButton::buttonColourId, juce::Colour(0xff301a30));
    reverbBypassButton.setColour(juce::TextButton::buttonOnColourId, juce::Colour(0xff442244));
    reverbBypassButton.setColour(juce::TextButton::textColourOffId, juce::Colour(0xffaa66aa));
    reverbBypassButton.setColour(juce::TextButton::textColourOnId, juce::Colour(0xffcc88cc));
    reverbBypassButton.setTooltip("Bypass the reverb module entirely — click-free crossfade");

    addAndMakeVisible(masterBypassButton);
    masterBypassButton.setButtonText("BYPASS");
    masterBypassButton.setColour(juce::TextButton::buttonColourId, juce::Colour(0xff301a20));
    masterBypassButton.setColour(juce::TextButton::buttonOnColourId, juce::Colour(0xff442233));
    masterBypassButton.setColour(juce::TextButton::textColourOffId, juce::Colour(0xffaa6688));
    masterBypassButton.setColour(juce::TextButton::textColourOnId, juce::Colour(0xffcc88aa));
    masterBypassButton.setTooltip("Bypass the master output stage entirely — click-free crossfade");

    setupKnob(fatnessKnob, fatnessLabel, "DRIVE", "Distortion amount — blends tape saturation at low settings into tube warmth at high settings");
    setupKnob(chorusDepthKnob, chorusDepthLabel, "DEPTH", "Chorus modulation depth — controls pitch excursion amount");
    setupKnob(chorusRateKnob, chorusRateLabel, "RATE", "Chorus LFO speed (Hz) — 6 decorrelated voices never align");
    setupKnob(chorusMixKnob, chorusMixLabel, "MIX", "Chorus wet/dry balance — 10% dry anchor keeps pitch stable at full wet");
    setupKnob(delayTimeKnob, delayTimeLabel, "TIME", "Delay time in milliseconds — 0 to 2000ms with tape-style interpolation");
    setupKnob(delayFeedbackKnob, delayFeedbackLabel, "FEEDBACK", "Delay feedback amount — exponential mapping for musical response");
    setupKnob(delayMixKnob, delayMixLabel, "MIX", "Delay wet/dry balance");
    setupKnob(delayDampingKnob, delayDampingLabel, "DAMPING", "Delay feedback tone — high values = darker, more tape-like repeats");
    setupKnob(delayModKnob, delayModLabel, "MOD", "Delay tape modulation depth — wow and flutter intensity for vintage tape character");
    setupKnob(reverbSizeKnob, reverbSizeLabel, "SIZE", "Reverb room size — controls both decay time and diffusion character");
    setupKnob(reverbDampingKnob, reverbDampingLabel, "DAMPING", "Reverb high-frequency absorption — higher = shorter, darker tail");
    setupKnob(reverbMixKnob, reverbMixLabel, "MIX", "Reverb wet/dry balance");
    setupKnob(reverbModKnob, reverbModLabel, "MOD", "Reverb modulation depth — adds organic movement to the reverb tail");
    setupKnob(masterDriveKnob, masterDriveLabel, "MASTER DRIVE", "Master output saturation — push-pull even harmonics for analog warmth");
    setupKnob(masterWidthKnob, masterWidthLabel, "WIDTH", "Stereo width — 0% = mono, 100% = original stereo, >100% = widened");
    setupKnob(masterMidDriveKnob, masterMidDriveLabel, "MID DRIVE", "Mid channel saturation — push-pull even harmonics on center content");
    setupKnob(masterSideDriveKnob, masterSideDriveLabel, "SIDE DRIVE", "Side channel saturation — push-pull even harmonics on stereo width");

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
    presetAtt = std::make_unique<juce::AudioProcessorValueTreeState::ComboBoxAttachment>(audioProcessor.apvts, "preset", presetSelector);

    // Level meter
    addAndMakeVisible(levelMeter);
}

CorvusFXAudioProcessorEditor::~CorvusFXAudioProcessorEditor()
{
    setLookAndFeel(nullptr);
}

void CorvusFXAudioProcessorEditor::timerCallback()
{
    // Update level meter from processor (audio thread -> message thread via atomics)
    auto& meters = audioProcessor.levelMeters;
    levelMeter.setInputPeakL(meters.inPeakL.load(std::memory_order_relaxed));
    levelMeter.setInputPeakR(meters.inPeakR.load(std::memory_order_relaxed));
    levelMeter.setInputRmsL(meters.inRmsL.load(std::memory_order_relaxed));
    levelMeter.setInputRmsR(meters.inRmsR.load(std::memory_order_relaxed));
    levelMeter.setOutputPeakL(meters.outPeakL.load(std::memory_order_relaxed));
    levelMeter.setOutputPeakR(meters.outPeakR.load(std::memory_order_relaxed));
    levelMeter.setOutputRmsL(meters.outRmsL.load(std::memory_order_relaxed));
    levelMeter.setOutputRmsR(meters.outRmsR.load(std::memory_order_relaxed));
}

void CorvusFXAudioProcessorEditor::paint(juce::Graphics& g)
{
    // Vignette
    juce::ColourGradient vig(
        juce::Colours::transparentBlack, getWidth() / 2.0f, getHeight() / 2.0f,
        juce::Colours::black.withAlpha(0.3f), 0, 0, true);
    g.setGradientFill(vig);
    g.fillRect(getLocalBounds());

    // Version text
    g.setColour(juce::Colour(0xff444466));
    g.setFont(juce::Font(9.0f));
    g.drawText("CorvusFX v1.0 | Professional Multi-FX Suite",
        getLocalBounds().removeFromBottom(15), juce::Justification::centred, true);
}

void CorvusFXAudioProcessorEditor::resized()
{
    auto area = getLocalBounds();
    animatedBackground.setBounds(area);

    // ── Calculate proportional scaling factor based on reference size 1200x700 ──
    // This ensures all layout elements scale smoothly between min (1000x600) and max (1600x900)
    const float refW = 1200.0f;
    const float refH = 700.0f;
    const float scaleW = area.getWidth() / refW;
    const float scaleH = area.getHeight() / refH;
    const float scale = juce::jmin(scaleW, scaleH); // Uniform scaling preserves aspect ratios
    auto sc = [scale](int px) { return juce::roundToInt(px * scale); };

    // ── Top: title + preset ──
    auto topSection = area.removeFromTop(sc(100));
    titleLabel.setBounds(topSection.removeFromTop(sc(60)).reduced(sc(20), sc(5)));
    auto presetArea = topSection.reduced(sc(250), sc(5));
    presetLabel.setBounds(presetArea.removeFromTop(sc(15)));
    presetSelector.setBounds(presetArea);

    // ── Level Meter (between title/preset and overall knob) ──
    auto meterArea = area.removeFromTop(sc(60)).reduced(area.getWidth() / 4, 0);
    levelMeter.setBounds(meterArea);

    area.removeFromBottom(sc(20)); // version text space
    area.reduce(sc(20), sc(10));

    // ── Overall knob (centered hero) ──
    auto overallRow = area.removeFromTop(sc(180));
    int oSize = sc(150);
    auto oArea = overallRow.withSizeKeepingCentre(oSize, oSize + sc(30));
    overallKnob.setBounds(oArea.removeFromTop(oSize));
    overallLabel.setBounds(oArea);

    // ── Master Drive knob (below Overall) ──
    auto masterDriveRow = area.removeFromTop(sc(100));
    int mSize = sc(100);
    auto mArea = masterDriveRow.withSizeKeepingCentre(mSize, mSize + sc(25));
    masterDriveKnob.setBounds(mArea.removeFromTop(mSize));
    masterDriveLabel.setBounds(mArea);

    // Master bypass button — right-aligned in the same row
    auto mdrRow = masterDriveRow.reduced(sc(40), 0);
    auto mbBypassArea = mdrRow.removeFromRight(sc(100));
    masterBypassButton.setBounds(mbBypassArea.removeFromTop(sc(25)).withTrimmedLeft(0));

    area.removeFromTop(sc(10));

    // ── Master Width / Mid Drive / Side Drive knobs (below Master Drive) ──
    auto masterMSSRow = area.removeFromTop(sc(100));
    int msSize = sc(80);
    int msGap = sc(20);
    int msTotalW = msSize * 3 + msGap * 2;
    auto msStart = masterMSSRow.withSizeKeepingCentre(msTotalW, msSize + sc(25));
    
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

    area.removeFromTop(sc(10));

    // ── 2x2 grid of effect sections ──
    int totalW = area.getWidth();
    int totalH = area.getHeight();
    int gap = sc(15);
    int secW = (totalW - gap) / 2;
    int secH = (totalH - gap) / 2;
    int bottomY = area.getY() + secH + gap;

    // === TOP ROW ===
    auto topFxRow = area.removeFromTop(secH);

    // Distortion (top-left)
    auto distArea = topFxRow.removeFromLeft(secW);
    distortionSection.setBounds(distArea);
    {
        auto c = distArea.reduced(sc(15), sc(45));
        int ks = juce::jmin(juce::jmin(c.getWidth(), c.getHeight()) - sc(20), sc(120));
        ks = juce::jmax(ks, 60); // Minimum readable size
        auto ka = c.withSizeKeepingCentre(ks, ks + sc(25));
        fatnessKnob.setBounds(ka.removeFromTop(ks));
        fatnessLabel.setBounds(ka);
        // Bypass button below the knob
        auto bypassArea = c.removeFromTop(sc(30)).withTrimmedTop(sc(10));
        distortionBypassButton.setBounds(bypassArea.withSizeKeepingCentre(juce::jmin(bypassArea.getWidth(), sc(80)), sc(22)));
    }

    topFxRow.removeFromLeft(gap);

    // Chorus (top-right) - 3 knobs horizontal
    auto chorArea = topFxRow;
    chorusSection.setBounds(chorArea);
    {
        auto c = chorArea.reduced(sc(15), sc(45));
        int ks = juce::jmin(sc(80), c.getHeight() - sc(30));
        ks = juce::jmax(ks, 50); // Minimum readable size
        int sp = juce::jmax(sc(5), (c.getWidth() - ks * 3) / 4);

        c.removeFromLeft(sp);
        auto a1 = c.removeFromLeft(ks);
        chorusDepthKnob.setBounds(a1.removeFromTop(ks));
        chorusDepthLabel.setBounds(a1.removeFromTop(sc(25)));

        c.removeFromLeft(sp);
        auto a2 = c.removeFromLeft(ks);
        chorusRateKnob.setBounds(a2.removeFromTop(ks));
        chorusRateLabel.setBounds(a2.removeFromTop(sc(25)));

        c.removeFromLeft(sp);
        auto a3 = c.removeFromLeft(ks);
        chorusMixKnob.setBounds(a3.removeFromTop(ks));
        chorusMixLabel.setBounds(a3.removeFromTop(sc(25)));
        c.removeFromTop(sc(5));
        auto chBypArea = c.removeFromTop(sc(30));
        chorusBypassButton.setBounds(chBypArea.withSizeKeepingCentre(juce::jmin(chBypArea.getWidth(), sc(80)), sc(22)));
    }

    // === BOTTOM ROW ===
    auto botRow = getLocalBounds();
    botRow.removeFromTop(bottomY);
    botRow.removeFromBottom(sc(20));
    botRow.reduce(sc(20), 0);

    // Delay (bottom-left) - 4 knobs horizontal
    auto delArea = botRow.removeFromLeft(secW);
    delaySection.setBounds(delArea);
    {
        auto c = delArea.reduced(sc(12), sc(45));
        int ks = juce::jmin(sc(70), c.getHeight() - sc(30));
        ks = juce::jmax(ks, 50); // Minimum readable size
        int sp = juce::jmax(sc(4), (c.getWidth() - ks * 5) / 6);

        c.removeFromLeft(sp);
        auto a1 = c.removeFromLeft(ks);
        delayTimeKnob.setBounds(a1.removeFromTop(ks));
        delayTimeLabel.setBounds(a1.removeFromTop(sc(25)));

        c.removeFromLeft(sp);
        auto a2 = c.removeFromLeft(ks);
        delayFeedbackKnob.setBounds(a2.removeFromTop(ks));
        delayFeedbackLabel.setBounds(a2.removeFromTop(sc(25)));

        c.removeFromLeft(sp);
        auto a3 = c.removeFromLeft(ks);
        delayMixKnob.setBounds(a3.removeFromTop(ks));
        delayMixLabel.setBounds(a3.removeFromTop(sc(25)));

        c.removeFromLeft(sp);
        auto a4 = c.removeFromLeft(ks);
        delayDampingKnob.setBounds(a4.removeFromTop(ks));
        delayDampingLabel.setBounds(a4.removeFromTop(sc(25)));

        c.removeFromLeft(sp);
        auto a5 = c.removeFromLeft(ks);
        delayModKnob.setBounds(a5.removeFromTop(ks));
        delayModLabel.setBounds(a5.removeFromTop(sc(25)));
        c.removeFromTop(sc(5));
        auto dlBypArea = c.removeFromTop(sc(30));
        delayBypassButton.setBounds(dlBypArea.withSizeKeepingCentre(juce::jmin(dlBypArea.getWidth(), sc(80)), sc(22)));
    }

    botRow.removeFromLeft(gap);

    // Reverb (bottom-right) - 4 knobs horizontal
    auto revArea = botRow;
    reverbSection.setBounds(revArea);
    {
        auto c = revArea.reduced(sc(12), sc(45));
        int ks = juce::jmin(sc(70), c.getHeight() - sc(30));
        ks = juce::jmax(ks, 50); // Minimum readable size
        int sp = juce::jmax(sc(4), (c.getWidth() - ks * 4) / 5);

        c.removeFromLeft(sp);
        auto a1 = c.removeFromLeft(ks);
        reverbSizeKnob.setBounds(a1.removeFromTop(ks));
        reverbSizeLabel.setBounds(a1.removeFromTop(sc(25)));

        c.removeFromLeft(sp);
        auto a2 = c.removeFromLeft(ks);
        reverbDampingKnob.setBounds(a2.removeFromTop(ks));
        reverbDampingLabel.setBounds(a2.removeFromTop(sc(25)));

        c.removeFromLeft(sp);
        auto a3 = c.removeFromLeft(ks);
        reverbMixKnob.setBounds(a3.removeFromTop(ks));
        reverbMixLabel.setBounds(a3.removeFromTop(sc(25)));

        c.removeFromLeft(sp);
        auto a4 = c.removeFromLeft(ks);
        reverbModKnob.setBounds(a4.removeFromTop(ks));
        reverbModLabel.setBounds(a4.removeFromTop(sc(25)));
        c.removeFromTop(sc(5));
        auto rvBypArea = c.removeFromTop(sc(30));
        reverbBypassButton.setBounds(rvBypArea.withSizeKeepingCentre(juce::jmin(rvBypArea.getWidth(), sc(80)), sc(22)));
    }
}