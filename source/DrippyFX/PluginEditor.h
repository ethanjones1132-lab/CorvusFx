#pragma once
#include <JuceHeader.h>
#include "PluginProcessor.h"

// â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•
// ANIMATED KNOB â€” smooth hover glow
// â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•
class AnimatedKnob : public juce::Slider, public juce::Timer
{
public:
    AnimatedKnob() { setSliderStyle(juce::Slider::RotaryHorizontalVerticalDrag); setTextBoxStyle(juce::Slider::TextBoxBelow, false, 70, 18); startTimer(30); }
    void mouseEnter(const juce::MouseEvent& e) override { juce::Slider::mouseEnter(e); hov = true; }
    void mouseExit(const juce::MouseEvent& e) override { juce::Slider::mouseExit(e);  hov = false; }
    void mouseDown(const juce::MouseEvent& e) override
    {
        if (e.mods.isRightButtonDown())
        {
            if (onRightClick) onRightClick(e);
            return;
        }
        if (onGestureStart) onGestureStart();  // begin undo transaction before first knob move
        juce::Slider::mouseDown(e);  prs = true;
    }
    void mouseUp(const juce::MouseEvent& e) override { juce::Slider::mouseUp(e);    prs = false; }
    void timerCallback() override { float t = prs ? 1.4f : (hov ? 1.0f : 0.0f); glow += (t - glow) * 0.12f; if (std::abs(t - glow) > 0.005f) repaint(); }
    float getGlowAmount() const { return glow; }
    juce::String linkedParamID;
    std::function<void(const juce::MouseEvent&)> onRightClick;
    std::function<void()> onGestureStart;

private:
    bool hov = false, prs = false; float glow = 0.0f;
};

// â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•
// PREMIUM LOOK AND FEEL â€” glass knobs with depth and specular
// â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•
class CorvusLookAndFeel : public juce::LookAndFeel_V4
{
public:
    CorvusLookAndFeel(bool darkTheme = true) : darkTheme_(darkTheme) { applyTheme(); }

    void setDarkTheme(bool darkTheme)
    {
        if (darkTheme_ == darkTheme)
            return;
        darkTheme_ = darkTheme;
        applyTheme();
    }

    bool isDarkTheme() const { return darkTheme_; }

private:
    bool darkTheme_ = true;

    void applyTheme()
    {
        setColour(juce::ResizableWindow::backgroundColourId, darkTheme_ ? juce::Colour(0xff050510) : juce::Colour(0xffeef0f8));
        setColour(juce::Slider::textBoxTextColourId, darkTheme_ ? juce::Colour(0xffc0c0d0) : juce::Colour(0xff303048));
        setColour(juce::Slider::textBoxBackgroundColourId, darkTheme_ ? juce::Colour(0xff0c0c1a) : juce::Colour(0xffdfe2ef));
        setColour(juce::Slider::textBoxOutlineColourId, darkTheme_ ? juce::Colour(0xff2a2a50) : juce::Colour(0xffb7bed8));
        setColour(juce::ComboBox::backgroundColourId, darkTheme_ ? juce::Colour(0xff12122a) : juce::Colour(0xffffffff));
        setColour(juce::ComboBox::outlineColourId, darkTheme_ ? juce::Colour(0xff3a3a6a) : juce::Colour(0xffb7bed8));
        setColour(juce::ComboBox::arrowColourId, darkTheme_ ? juce::Colour(0xffb366ff) : juce::Colour(0xff51239f));
        setColour(juce::ComboBox::textColourId, darkTheme_ ? juce::Colour(0xffd0d0e0) : juce::Colour(0xff222238));
        setColour(juce::PopupMenu::backgroundColourId, darkTheme_ ? juce::Colour(0xff12122a) : juce::Colour(0xffffffff));
        setColour(juce::PopupMenu::textColourId, darkTheme_ ? juce::Colour(0xffd0d0e0) : juce::Colour(0xff222238));
        setColour(juce::PopupMenu::highlightedBackgroundColourId, darkTheme_ ? juce::Colour(0xff3a2a6a) : juce::Colour(0xffd6d8ef));
        setColour(juce::Label::textColourId, darkTheme_ ? juce::Colour(0xffd0d0e0) : juce::Colour(0xff222238));
    }

public:
    void drawRotarySlider(juce::Graphics& g, int x, int y, int width, int height,
        float sliderPos, float rotaryStartAngle, float rotaryEndAngle,
        juce::Slider& slider) override
    {
        auto knob = dynamic_cast<AnimatedKnob*>(&slider);
        float glow = knob ? knob->getGlowAmount() : 0.0f;
        auto r = juce::jmin(width / 2, height / 2) - 14.0f;
        auto cx = x + width * 0.5f, cy = y + height * 0.5f;
        auto rx = cx - r, ry = cy - r, rw = r * 2.0f;
        auto angle = rotaryStartAngle + sliderPos * (rotaryEndAngle - rotaryStartAngle);

        // Outer glow
        if (glow > 0.01f) {
            juce::ColourGradient gg(juce::Colour(0xffb366ff).withAlpha(glow * 0.25f), cx, cy, juce::Colours::transparentBlack, cx, cy - r - 20, true);
            g.setGradientFill(gg); g.fillEllipse(rx - 16, ry - 16, rw + 32, rw + 32);
        }
        // Shadow
        g.setColour(juce::Colour(0xff000008).withAlpha(0.6f));
        g.fillEllipse(rx + 2, ry + 3, rw, rw);
        // Bezel
        juce::ColourGradient bz(juce::Colour(0xff1a1a30), cx, cy - r, juce::Colour(0xff080818), cx, cy + r, false);
        g.setGradientFill(bz); g.fillEllipse(rx, ry, rw, rw);
        // Face
        float ir = r - 5;
        juce::ColourGradient fc(juce::Colour(0xff1e1e38), cx - ir * 0.3f, cy - ir * 0.5f, juce::Colour(0xff0a0a1a), cx + ir * 0.3f, cy + ir * 0.5f, false);
        g.setGradientFill(fc); g.fillEllipse(cx - ir, cy - ir, ir * 2, ir * 2);
        // Specular
        juce::ColourGradient sp(juce::Colour(0x18ffffff), cx - ir * 0.2f, cy - ir * 0.7f, juce::Colours::transparentWhite, cx, cy, true);
        g.setGradientFill(sp); g.fillEllipse(cx - ir * 0.6f, cy - ir * 0.85f, ir * 1.2f, ir * 0.7f);
        // Track bg
        juce::Path trk; trk.addCentredArc(cx, cy, r - 8, r - 8, 0, rotaryStartAngle, rotaryEndAngle, true);
        g.setColour(juce::Colour(0xff1a1a30)); g.strokePath(trk, juce::PathStrokeType(3.5f));
        // Value arc
        if (sliderPos > 0.005f) {
            juce::Path va; va.addCentredArc(cx, cy, r - 8, r - 8, 0, rotaryStartAngle, angle, true);
            juce::ColourGradient ag(juce::Colour(0xff5522bb), cx, cy - r, juce::Colour(0xffcc77ff), cx, cy + r, false);
            g.setGradientFill(ag); g.strokePath(va, juce::PathStrokeType(3.5f, juce::PathStrokeType::curved));
            g.setColour(juce::Colour(0xffb366ff).withAlpha(0.15f + glow * 0.1f));
            g.strokePath(va, juce::PathStrokeType(8.0f));
        }
        // Pointer
        juce::Path ptr; ptr.addRoundedRectangle(-1.8f, -r + 10, 3.6f, r * 0.5f, 1.8f);
        ptr.applyTransform(juce::AffineTransform::rotation(angle).translated(cx, cy));
        g.setColour(juce::Colour(0xffd099ff).withAlpha(0.7f + glow * 0.3f)); g.fillPath(ptr);
        // Center jewel
        juce::ColourGradient jw(juce::Colour(0xff8855cc), cx - 3, cy - 3, juce::Colour(0xff4422aa), cx + 3, cy + 3, true);
        g.setGradientFill(jw); g.fillEllipse(cx - 4.5f, cy - 4.5f, 9, 9);
        g.setColour(juce::Colour(0x30ffffff)); g.fillEllipse(cx - 2.5f, cy - 3.5f, 4, 3);
    }
};

// â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•
// LEVEL METER â€” Vertical stereo peak/RMS bars with dB scale
// Smooth exponential decay for professional metering feel
// ═══════════════════════════════════════════════════════════════
class LevelMeter : public juce::Component
{
public:
    LevelMeter() { setInterceptsMouseClicks(false, false); }

    void setInputPeakL(float v)  { inPeakL  = juce::jlimit(0.0f, 1.0f, v); repaint(); }
    void setInputPeakR(float v)  { inPeakR  = juce::jlimit(0.0f, 1.0f, v); repaint(); }
    void setInputRmsL(float v)   { inRmsL   = juce::jlimit(0.0f, 1.0f, v); }
    void setInputRmsR(float v)   { inRmsR   = juce::jlimit(0.0f, 1.0f, v); }
    void setOutputPeakL(float v) { outPeakL = juce::jlimit(0.0f, 1.0f, v); repaint(); }
    void setOutputPeakR(float v) { outPeakR = juce::jlimit(0.0f, 1.0f, v); repaint(); }
    void setOutputRmsL(float v)  { outRmsL  = juce::jlimit(0.0f, 1.0f, v); }
    void setOutputRmsR(float v)  { outRmsR  = juce::jlimit(0.0f, 1.0f, v); }

    void paint(juce::Graphics& g) override
    {
        auto bounds = getLocalBounds().toFloat();
        int w = (int)bounds.getWidth();
        int h = (int)bounds.getHeight();
        if (w < 10 || h < 20) return;

        // Meter layout: 4 vertical bars [InL][InR]  gap  [OutL][OutR]
        // Each bar gets equal width
        int barW = (w - 8) / 4;
        int gap = 8;
        int xInL = 2;
        int xInR = xInL + barW;
        int xOutL = xInR + barW + gap;
        int xOutR = xOutL + barW;

        // â”€â”€ dB scale (left side of meter area) â”€â”€
        // Professional metering: standard dB markings at -6, -12, -18, -24, -30, -40, -50, -60
        // dB = 20 * log10(amplitude), where 0dB = 1.0 (top), -60dB = 0.001 (near bottom)
        auto drawDbScale = [&](float xStart, float scaleW)
        {
            g.setColour(juce::Colour(0xff555577));
            g.setFont(juce::Font(juce::FontOptions(7.0f)));
            
            struct DbMark { float db; const char* label; };
            static const DbMark marks[] = {
                { 0.0f, "0"   },
                { -6.0f, "-6"  },
                { -12.0f, "-12" },
                { -18.0f, "-18" },
                { -24.0f, "-24" },
                { -30.0f, "-30" },
                { -40.0f, "-40" },
                { -50.0f, "-50" },
                { -60.0f, "-60" },
            };
            
            float scaleLeft = xStart + scaleW + 2;
            for (const auto& m : marks)
            {
            int y = (int)(bounds.getY() + (std::abs(m.db) / 60.0f) * h);
                // Tick mark
                g.setColour(juce::Colour(0xff444466));
                g.drawLine(scaleLeft - 6, (float)y, scaleLeft, (float)y, 1.0f);
                // Label
                g.setColour(juce::Colour(0xff666688));
                g.drawText(m.label, (int)(scaleLeft - 28), y - 5, 24, 10, juce::Justification::centredRight);
            }
        };
        
        // Draw dB scale on the left of the input meters
        drawDbScale(0, (float)xInL + barW * 2 + gap);

        // Logarithmic amplitude->position mapping shared by bars and dB ticks
        // (0 dBFS at top of meter -> -60 dBFS at bottom). Equal dB steps = equal pixels.
        auto ampToYPos = [&](float amp)
        {
            float db = 20.0f * std::log10(juce::jmax(amp, 1e-6f));  // <= 0
            float negDb = juce::jlimit(0.0f, 60.0f, -db);
            return negDb / 60.0f;
        };

        auto drawBar = [&](int x, float peak, float rms, juce::Colour peakCol, juce::Colour rmsCol)
        {
            float peakY = bounds.getY() + ampToYPos(peak) * h;
            float rmsY  = bounds.getY() + ampToYPos(rms)  * h;

            // Background track
            g.setColour(juce::Colour(0xff0a0a1a));
            g.fillRect((float)(x + 2), bounds.getY() + 2.0f, (float)(barW - 4), h - 4.0f);

            // RMS bar (sustained level)
            if (rms > 0.001f)
            {
                g.setColour(rmsCol);
                g.fillRect((float)(x + 2), rmsY, (float)(barW - 4), bounds.getBottom() - rmsY);
            }

            // Peak marker (single pixel line at top)
            if (peak > 0.001f)
            {
                g.setColour(peakCol);
                g.fillRect((float)(x + 1), peakY, (float)(barW - 2), 2.0f);
            }

            // 0dBFS reference line (top of meter = 0dB; bottom = -60dB)
            float zeroDbY = bounds.getY();
            g.setColour(juce::Colour(0xff444466));
            g.fillRect((float)(x + 2), zeroDbY, (float)(barW - 4), 1.0f);
        };

        // Input meters (cool cyan/blue)
        drawBar(xInL, inPeakL, inRmsL, juce::Colour(0xff00ffff), juce::Colour(0xff0088cc));
        drawBar(xInR, inPeakR, inRmsR, juce::Colour(0xff00ffff), juce::Colour(0xff0088cc));

        // Output meters (magenta/purple - Corvus brand)
        drawBar(xOutL, outPeakL, outRmsL, juce::Colour(0xffb366ff), juce::Colour(0xff8844cc));
        drawBar(xOutR, outPeakR, outRmsR, juce::Colour(0xffb366ff), juce::Colour(0xff8844cc));

        // Labels
        g.setColour(juce::Colour(0xff555577));
        g.setFont(juce::Font(juce::FontOptions(8.0f)));
        g.drawText("IN", xInL, (int)(bounds.getBottom() - 14), barW * 2, 12, juce::Justification::centred);
        g.drawText("OUT", xOutL, (int)(bounds.getBottom() - 14), barW * 2, 12, juce::Justification::centred);

        // Peak hold decay - handled externally by timer callback
    }

        // Peak hold decay lives on the processor's LevelMeters, applied by the
        // editor's timer before copying there — one timer, no local decay.

    private:
    float inPeakL = 0.0f, inPeakR = 0.0f;
    float inRmsL = 0.0f, inRmsR = 0.0f;
    float outPeakL = 0.0f, outPeakR = 0.0f;
    float outRmsL = 0.0f, outRmsR = 0.0f;
};

// â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•
// PHOTOREALISTIC DEEP SPACE BACKGROUND
// Static layers cached to images â†’ only animate overlay = 60fps
// â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•
class AnimatedBackground : public juce::Component, public juce::Timer
{
public:
    AnimatedBackground() { setInterceptsMouseClicks(false, false); startTimer(33); }
    void resized() override { nebulaCache = juce::Image(); starCache = juce::Image(); cW = cH = 0; }
    void setDarkTheme(bool isDark) { themeDark = isDark; resized(); repaint(); }
    void paint(juce::Graphics& g) override
    {
        int w = getWidth(), h = getHeight();
        if (w < 1 || h < 1) return;

        // Ensure the backdrop fill matches the active theme.
        g.fillAll(themeDark ? juce::Colour(0xff050510) : juce::Colour(0xfff4f4fa));

        if (!themeDark) {
            juce::ColourGradient soft(
                juce::Colour(0xfff8f9ff), getWidth() / 2.0f, getHeight() / 2.0f,
                juce::Colour(0xffdfe2f2), 0.0f, 0.0f, true);
            g.setGradientFill(soft);
            g.fillRect(getLocalBounds());
            return;
        }


        // Cache static layers on resize
        if (cW != w || cH != h) { renderNebula(w, h); renderStars(w, h); cW = w; cH = h; }

        g.drawImageAt(nebulaCache, 0, 0);

        // Animated nebula pulse â€” 3 breathing zones for organic feel
        float pulse1 = std::sin(phase * 0.12f) * 0.025f;
        float pulse2 = std::sin(phase * 0.17f + 1.2f) * 0.02f;
        float pulse3 = std::sin(phase * 0.09f + 3.5f) * 0.015f;
        // Primary cloud breathes
        {
            float nx = w * 0.32f + std::sin(phase * 0.018f) * w * 0.015f;
            float ny = h * 0.35f + std::cos(phase * 0.013f) * h * 0.012f;
            juce::ColourGradient gp(juce::Colour(0xff6633aa).withAlpha(0.035f + pulse1), nx, ny,
                juce::Colours::transparentBlack, nx + w * 0.25f, ny + h * 0.22f, true);
            g.setGradientFill(gp); g.fillRect(getLocalBounds());
        }
        // Secondary cloud breathes (slightly offset timing)
        {
            float nx = w * 0.72f + std::cos(phase * 0.015f) * w * 0.01f;
            float ny = h * 0.54f + std::sin(phase * 0.02f) * h * 0.008f;
            juce::ColourGradient gs(juce::Colour(0xff334488).withAlpha(0.025f + pulse2), nx, ny,
                juce::Colours::transparentBlack, nx + w * 0.2f, ny, true);
            g.setGradientFill(gs); g.fillRect(getLocalBounds());
        }
        // Magenta accent breathes (slowest)
        {
            float nx = w * 0.46f + std::sin(phase * 0.022f) * w * 0.012f;
            float ny = h * 0.67f + std::cos(phase * 0.016f) * h * 0.01f;
            juce::ColourGradient gm(juce::Colour(0xff882266).withAlpha(0.018f + pulse3), nx, ny,
                juce::Colours::transparentBlack, nx + w * 0.15f, ny + h * 0.12f, true);
            g.setGradientFill(gm); g.fillRect(getLocalBounds());
        }

        g.drawImageAt(starCache, 0, 0);

        // Animated hero star twinkle â€” deeply organic, never repetitive
        for (int i = 0; i < NUM_HERO_STARS; ++i)
        {
            auto& s = heroStars[i];

            // â”€â”€ 4-oscillator composite with irregular bursting â”€â”€
            // Primary: main rhythm
            float w1 = std::sin(phase * s.spd1 + s.ph);
            // Secondary: detuned against primary â†’ beating pattern
            float w2 = std::sin(phase * s.spd2 + s.ph * 1.73f);
            // Tertiary: slow envelope that gates the star on/off
            float w3 = std::sin(phase * s.spd3 + s.ph * 0.61f);
            // Ultra-slow drift: prevents exact repetition for ~3 minutes
            float w4 = std::sin(phase * 0.031f + s.ph * 2.37f);

            // Envelope: slow oscillators gate the fast ones
            // Power curve creates long dim periods with brief bright bursts
            float env = (w3 + 1.0f) * 0.5f;          // 0-1
            float drift = (w4 + 1.0f) * 0.5f;         // 0-1
            env = env * env * env;                      // cubic = long rests, sharp peaks
            env *= 0.5f + drift * 0.5f;                // drift modulates overall activity

            // Fast flicker: beating between two close frequencies
            float beat = w1 * 0.55f + w2 * 0.45f;
            // Occasional sharp spike: when both fast waves align
            float spike = std::max(0.0f, w1 * w2);     // only positive when both positive
            float flicker = beat * 0.7f + spike * 0.3f;

            // Final brightness
            float tw = flicker * env;
            float al = 0.05f + std::max(0.0f, tw) * 0.95f;
            if (al < 0.03f) continue;

            float sx = s.x * w, sy = s.y * h;
            float sz = s.sz;
            float dynSize = sz * (0.6f + al * 0.6f);

            // â”€â”€ Color temperature shift during twinkle â”€â”€
            // Stars shimmer between their base color and white-hot
            juce::Colour baseCol(s.col);
            // At peak brightness, shift toward white; at dim, shift toward blue
            float warmShift = al * al; // nonlinear: only goes white at peak
            juce::Colour sc = baseCol.interpolatedWith(
                juce::Colours::white, warmShift * 0.4f);
            juce::Colour coolSc = baseCol.interpolatedWith(
                juce::Colour(0xffaabbff), (1.0f - al) * 0.3f);

            // â”€â”€ Outer atmospheric halo (very faint, very large) â”€â”€
            float haloR = dynSize * 7.0f;
            g.setColour(coolSc.withAlpha(al * 0.04f));
            g.fillEllipse(sx - haloR, sy - haloR, haloR * 2, haloR * 2);

            // â”€â”€ Diffraction spikes with subtle rotation â”€â”€
            // Slight rotation over time gives organic shimmer
            float spikeRot = std::sin(phase * 0.07f + s.ph * 3.1f) * 0.08f;
            float spikeLen = dynSize * (3.5f + al * 4.0f);
            float spikeAlpha = al * 0.35f;

            float cosR = std::cos(spikeRot), sinR = std::sin(spikeRot);

            // Primary cross spikes (rotated)
            g.setColour(sc.withAlpha(spikeAlpha * 0.6f));
            g.drawLine(sx - spikeLen * cosR, sy - spikeLen * sinR,
                sx + spikeLen * cosR, sy + spikeLen * sinR, 0.9f);
            g.drawLine(sx + spikeLen * sinR, sy - spikeLen * cosR,
                sx - spikeLen * sinR, sy + spikeLen * cosR, 0.9f);

            // Thin bright inner spikes
            g.setColour(juce::Colours::white.withAlpha(spikeAlpha * 0.45f));
            g.drawLine(sx - spikeLen * 0.65f * cosR, sy - spikeLen * 0.65f * sinR,
                sx + spikeLen * 0.65f * cosR, sy + spikeLen * 0.65f * sinR, 0.4f);
            g.drawLine(sx + spikeLen * 0.65f * sinR, sy - spikeLen * 0.65f * cosR,
                sx - spikeLen * 0.65f * sinR, sy + spikeLen * 0.65f * cosR, 0.4f);

            // 45-degree secondary spikes (shorter, different rotation)
            float diagLen = spikeLen * 0.4f;
            float dRot = spikeRot + 0.785f; // offset by 45 degrees
            float dCos = std::cos(dRot), dSin = std::sin(dRot);
            g.setColour(sc.withAlpha(spikeAlpha * 0.22f));
            g.drawLine(sx - diagLen * dCos, sy - diagLen * dSin,
                sx + diagLen * dCos, sy + diagLen * dSin, 0.5f);
            g.drawLine(sx + diagLen * dSin, sy - diagLen * dCos,
                sx - diagLen * dSin, sy + diagLen * dCos, 0.5f);

            // â”€â”€ 5-layer bloom with color gradient â”€â”€
            g.setColour(coolSc.withAlpha(al * 0.035f));
            g.fillEllipse(sx - dynSize * 6, sy - dynSize * 6, dynSize * 12, dynSize * 12);
            g.setColour(coolSc.withAlpha(al * 0.06f));
            g.fillEllipse(sx - dynSize * 4.5f, sy - dynSize * 4.5f, dynSize * 9, dynSize * 9);
            g.setColour(sc.withAlpha(al * 0.12f));
            g.fillEllipse(sx - dynSize * 3, sy - dynSize * 3, dynSize * 6, dynSize * 6);
            g.setColour(sc.withAlpha(al * 0.3f));
            g.fillEllipse(sx - dynSize * 1.5f, sy - dynSize * 1.5f, dynSize * 3, dynSize * 3);
            // Hot white core â€” slightly non-circular for realism
            float coreW = dynSize * 0.55f, coreH = dynSize * 0.45f;
            g.setColour(juce::Colours::white.withAlpha(al * 0.95f));
            g.fillEllipse(sx - coreW * 0.5f, sy - coreH * 0.5f, coreW, coreH);
        }

        // Shooting star
        if (meteorActive)
        {
            float t = meteorProg;
            float et = t < 0.4f ? (t / 0.4f) * (t / 0.4f) : 1.0f;
            float fo = t > 0.7f ? 1.0f - (t - 0.7f) / 0.3f : 1.0f;
            float al = et * fo;
            float mx = mSX + mDX * t * w, my = mSY + mDY * t * h;
            for (int j = 0; j < 40; ++j) {
                float tp = (float)j / 40.0f, tt = t - tp * 0.18f;
                if (tt < 0) continue;
                float tx = mSX + mDX * tt * w, ty = mSY + mDY * tt * h;
                float ta = (1 - tp) * al, tw2 = (1 - tp) * 3.0f + 0.3f;
                juce::Colour tc = tp < 0.15f ? juce::Colours::white : tp < 0.4f ? juce::Colour(0xffddddff) : tp < 0.7f ? juce::Colour(0xffbbaaee) : juce::Colour(0xff8866cc);
                g.setColour(tc.withAlpha(ta));
                g.fillEllipse(tx - tw2 * 0.5f, ty - tw2 * 0.5f, tw2, tw2);
            }
            g.setColour(juce::Colour(0xff9977dd).withAlpha(al * 0.15f));
            g.fillEllipse(mx - 16, my - 16, 32, 32);
            g.setColour(juce::Colour(0xffccbbff).withAlpha(al * 0.4f));
            g.fillEllipse(mx - 6, my - 6, 12, 12);
            g.setColour(juce::Colours::white.withAlpha(al * 0.95f));
            g.fillEllipse(mx - 2.5f, my - 2.5f, 5, 5);
        }

        // Dust particles
        for (int i = 0; i < 20; ++i) {
            float dx = std::fmod(dustP[i].x + phase * dustP[i].spd * 0.001f, 1.2f) - 0.1f;
            float dy = dustP[i].y + std::sin(phase * 0.05f + dustP[i].ph) * 0.005f;
            float da = dustP[i].al * (0.7f + std::sin(phase * 0.3f + dustP[i].ph) * 0.3f);
            g.setColour(juce::Colour(dustP[i].col).withAlpha(da));
            g.fillEllipse(dx * w - dustP[i].sz * 0.5f, dy * h - dustP[i].sz * 0.5f, dustP[i].sz, dustP[i].sz);
        }
    }

    void timerCallback() override
    {
        phase += 0.05f;
        if (meteorActive) { meteorProg += 0.012f; if (meteorProg > 1) { meteorActive = false; meteorCD = 120 + (int)(std::sin(phase * 0.37f) * 80 + 80); } }
        else { meteorCD--; if (meteorCD <= 0) { meteorActive = true; meteorProg = 0; float s = std::sin(phase * 1.37f); mSX = (0.3f + s * 0.4f) * getWidth(); mSY = -10; mDX = 0.4f + std::abs(std::sin(phase * 2.1f)) * 0.3f; mDY = 0.3f + std::abs(std::cos(phase * 1.7f)) * 0.4f; if (std::sin(phase * 0.77f) > 0) mDX = -mDX; } }
        repaint();
    }

private:
    float phase = 0; juce::Image nebulaCache, starCache; int cW = 0, cH = 0; bool themeDark = true;
    // Hero stars: 3 independent oscillator speeds per star for organic feel
    // spd1 = primary pulse, spd2 = secondary (detuned), spd3 = slow envelope
    static constexpr int NUM_HERO_STARS = 22;
    struct HS { float x, y, sz, spd1, spd2, spd3, ph; juce::uint32 col; };
    HS heroStars[NUM_HERO_STARS] = {
        //  x      y     sz   spd1  spd2   spd3   phase   colour
        // GROUP A: Very slow breathers (flash every 5-10 sec)
        { .12f, .08f, 3.2f,  0.7f,  1.9f,  0.06f, 0.0f,  0xffeeddff },
        { .45f, .05f, 3.4f,  0.5f,  1.4f,  0.04f, 2.3f,  0xffffffff },
        { .05f, .22f, 3.0f,  0.6f,  2.1f,  0.05f, 3.4f,  0xffddccee },
        { .75f, .68f, 2.8f,  0.8f,  1.6f,  0.07f, 5.2f,  0xffeedddd },
        // GROUP B: Medium pulsers (flash every 2-4 sec)
        { .85f, .15f, 2.5f,  1.8f,  3.7f,  0.14f, 1.1f,  0xffddccff },
        { .92f, .58f, 2.6f,  1.5f,  4.2f,  0.18f, 5.0f,  0xffddbbff },
        { .55f, .82f, 2.9f,  2.0f,  3.0f,  0.12f, 1.5f,  0xffffeeff },
        { .65f, .72f, 2.5f,  1.6f,  3.5f,  0.20f, 2.7f,  0xffddddff },
        { .33f, .12f, 2.7f,  1.4f,  4.0f,  0.11f, 1.9f,  0xffeeeeff },
        { .42f, .92f, 2.8f,  1.9f,  2.8f,  0.16f, 2.0f,  0xffddddff },
        // GROUP C: Fast twinklers (rapid shimmer)
        { .72f, .42f, 2.3f,  3.5f,  6.8f,  0.28f, 0.7f,  0xffccddff },
        { .28f, .67f, 2.1f,  4.5f,  7.2f,  0.22f, 3.8f,  0xffeeeeff },
        { .08f, .45f, 2.2f,  5.0f,  8.1f,  0.35f, 4.2f,  0xffccccff },
        { .38f, .32f, 2.0f,  6.0f,  3.5f,  0.10f, 0.3f,  0xffeeddee },
        { .78f, .25f, 2.1f,  4.8f,  6.5f,  0.15f, 4.6f,  0xffffffff },
        // GROUP D: Erratic blinkers (mix of fast/slow)
        { .50f, .50f, 2.0f,  3.2f,  0.9f,  0.40f, 5.5f,  0xffddddee },
        { .88f, .85f, 2.4f,  2.6f,  5.3f,  0.08f, 0.8f,  0xffccbbee },
        { .62f, .08f, 2.5f,  0.9f,  7.0f,  0.30f, 4.0f,  0xffeeeeff },
        { .15f, .38f, 2.2f,  4.8f,  1.2f,  0.38f, 1.3f,  0xffccddee },
        { .58f, .28f, 2.3f,  1.1f,  5.5f,  0.25f, 3.6f,  0xffddeeff },
        { .82f, .48f, 2.1f,  2.8f,  0.7f,  0.09f, 4.8f,  0xffffddff },
        { .18f, .88f, 2.7f,  0.4f,  3.2f,  0.03f, 3.1f,  0xffeeccff },
    };
    struct DP { float x, y, sz, spd, al, ph; juce::uint32 col; };
    DP dustP[20] = {
        {.1f,.2f,1.2f,.3f,.06f,0,0xffbbaadd},{.3f,.5f,1.5f,.2f,.05f,1,0xffaa99cc},
        {.5f,.1f,1.0f,.4f,.07f,2,0xffccbbee},{.7f,.7f,1.3f,.25f,.04f,3,0xff9988bb},
        {.9f,.3f,1.1f,.35f,.06f,4,0xffbbaacc},{.2f,.8f,1.4f,.15f,.05f,5,0xffaa88cc},
        {.4f,.4f,1.0f,.3f,.04f,.5f,0xffccaadd},{.6f,.6f,1.6f,.2f,.06f,1.5f,0xff9977bb},
        {.8f,.1f,1.2f,.4f,.05f,2.5f,0xffbbbbdd},{.15f,.55f,1.3f,.28f,.07f,3.5f,0xffaa99dd},
        {.35f,.85f,1.1f,.32f,.04f,4.5f,0xffbb99cc},{.55f,.25f,1.5f,.22f,.06f,5.5f,0xffccaaee},
        {.75f,.45f,1.0f,.38f,.05f,.3f,0xff8877aa},{.95f,.65f,1.4f,.18f,.04f,1.3f,0xffaa88bb},
        {.25f,.35f,1.2f,.33f,.07f,2.3f,0xffbbaacc},{.05f,.75f,1.3f,.27f,.05f,3.3f,0xffcc99dd},
        {.45f,.15f,1.1f,.36f,.06f,4.3f,0xff9988cc},{.65f,.95f,1.5f,.21f,.04f,5.3f,0xffaaaadd},
        {.85f,.5f,1.0f,.39f,.05f,.7f,0xffbb88cc},{.22f,.62f,1.4f,.24f,.07f,1.7f,0xffccbbdd},
    };
    bool meteorActive = false; float meteorProg = 0, mSX = 0, mSY = 0, mDX = .5f, mDY = .3f; int meteorCD = 80;

    void renderNebula(int w, int h)
    {
        nebulaCache = juce::Image(juce::Image::ARGB, w, h, true);
        juce::Graphics g(nebulaCache);

        // Deep space base gradient
        juce::ColourGradient bg(juce::Colour(0xff060614), w * .3f, 0,
            juce::Colour(0xff030308), w * .7f, (float)h, false);
        bg.addColour(0.35, juce::Colour(0xff080820));
        bg.addColour(0.65, juce::Colour(0xff050512));
        g.setGradientFill(bg);
        g.fillRect(0, 0, w, h);

        // Helper to paint a radial cloud blob
        struct CL { float cx, cy, rx, ry; juce::uint32 c; };
        auto paintClouds = [&](CL* layers, int count) {
            for (int i = 0; i < count; ++i)
            {
                auto& cl = layers[i];
                float cx = cl.cx * w, cy = cl.cy * h;
                float rx = cl.rx * w, ry = cl.ry * h;
                // Elliptical radial gradient for organic shape
                juce::ColourGradient cg(
                    juce::Colour(cl.c), cx, cy,
                    juce::Colours::transparentBlack, cx + rx, cy + ry, true);
                g.setGradientFill(cg);
                g.fillRect(0, 0, w, h);
            }
            };

        // â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•
        // PRIMARY NEBULA (upper-left, purple/violet)
        // Core + mid-density + wispy edges
        // â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•
        CL primaryCore[] = {
            { .30f, .33f, .38f, .32f, 0x0c5522aa },  // large base
            { .33f, .36f, .28f, .24f, 0x0e7733bb },  // mid layer
            { .28f, .30f, .20f, .18f, 0x108844cc },  // bright inner
            { .32f, .34f, .14f, .12f, 0x14aa55dd },  // hot core
            { .35f, .38f, .08f, .07f, 0x0acc66ee },  // bright nucleus
        };
        paintClouds(primaryCore, 5);

        // Primary wispy tendrils extending outward
        CL primaryWisps[] = {
            { .22f, .25f, .18f, .08f, 0x087733aa },  // upper-left tendril
            { .42f, .28f, .15f, .10f, 0x066622aa },  // upper-right arm
            { .25f, .45f, .10f, .20f, 0x088833bb },  // downward stream
            { .38f, .48f, .12f, .15f, 0x065522aa },  // lower arm
            { .18f, .35f, .22f, .06f, 0x077744aa },  // horizontal wisp left
            { .44f, .32f, .16f, .05f, 0x066633aa },  // horizontal wisp right
        };
        paintClouds(primaryWisps, 6);

        // â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•
        // SECONDARY NEBULA (right side, blue/teal)
        // â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•
        CL secondaryCore[] = {
            { .72f, .55f, .28f, .24f, 0x0a3344aa },
            { .70f, .52f, .20f, .18f, 0x0c4455bb },
            { .74f, .57f, .14f, .12f, 0x0e5566cc },
            { .71f, .54f, .08f, .07f, 0x086677dd },
        };
        paintClouds(secondaryCore, 4);

        CL secondaryWisps[] = {
            { .64f, .48f, .14f, .06f, 0x073355aa },  // upper tendril
            { .80f, .60f, .10f, .16f, 0x064466aa },  // lower reach
            { .68f, .62f, .18f, .05f, 0x063344aa },  // horizontal wisp
            { .76f, .46f, .08f, .12f, 0x054455aa },  // small upper
        };
        paintClouds(secondaryWisps, 4);

        // â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•
        // CONNECTING BRIDGE (between the two main clouds)
        // Faint material linking the two nebulae
        // â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•
        CL bridge[] = {
            { .50f, .45f, .30f, .08f, 0x053333aa },  // wide faint horizontal
            { .48f, .42f, .20f, .06f, 0x064444aa },  // narrower overlay
            { .55f, .48f, .15f, .05f, 0x043355aa },  // slight offset
        };
        paintClouds(bridge, 3);

        // â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•
        // MAGENTA / WARM ACCENT WISPS
        // â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•
        CL magentaCore[] = {
            { .45f, .65f, .22f, .16f, 0x08882266 },
            { .50f, .70f, .14f, .10f, 0x0aaa3377 },
            { .42f, .62f, .10f, .08f, 0x08993388 },
        };
        paintClouds(magentaCore, 3);

        CL magentaWisps[] = {
            { .38f, .72f, .16f, .04f, 0x06772255 },
            { .52f, .60f, .08f, .14f, 0x05882266 },
            { .48f, .78f, .12f, .05f, 0x04662244 },
        };
        paintClouds(magentaWisps, 3);

        // â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•
        // FAINT OUTER HAZE (very subtle, very large)
        // Creates the impression of gas extending everywhere
        // â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•
        CL outerHaze[] = {
            { .20f, .20f, .50f, .45f, 0x04332255 },
            { .80f, .75f, .45f, .40f, 0x03223355 },
            { .50f, .50f, .60f, .50f, 0x02221133 },
            { .15f, .70f, .30f, .25f, 0x03442244 },
            { .85f, .30f, .25f, .30f, 0x02334455 },
        };
        paintClouds(outerHaze, 5);

        // â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•
        // DARK DUST LANES (subtractive â€” like real nebulae)
        // These cut through the bright areas
        // â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•
        CL darkLanes[] = {
            { .50f, .42f, .20f, .08f, 0x22000005 },
            { .38f, .55f, .15f, .06f, 0x1a000008 },
            { .60f, .35f, .12f, .10f, 0x18000005 },
            { .30f, .42f, .10f, .14f, 0x14000006 },
            { .55f, .52f, .08f, .06f, 0x10000004 },
            { .42f, .38f, .18f, .04f, 0x12000005 },  // horizontal lane
        };
        paintClouds(darkLanes, 6);

        // â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•
        // EDGE GLOW (subtle bright rim on cloud edges)
        // â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•
        CL edgeGlow[] = {
            { .24f, .28f, .06f, .04f, 0x08bb88ee },
            { .40f, .36f, .04f, .06f, 0x06aa77dd },
            { .66f, .50f, .05f, .04f, 0x067788cc },
            { .76f, .60f, .04f, .05f, 0x056688bb },
        };
        paintClouds(edgeGlow, 4);

        // â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•
        // FILAMENTARY STRUCTURE (thin elongated wisps)
        // These are very elongated elliptical gradients
        // that create the fine threadlike texture of real nebulae
        // â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•
        CL filaments[] = {
            // Primary cloud filaments
            { .26f, .30f, .25f, .02f, 0x066633aa },   // long horizontal strand
            { .34f, .38f, .03f, .22f, 0x055522aa },   // vertical filament
            { .29f, .40f, .18f, .025f, 0x057744aa },  // diagonal strand
            { .36f, .32f, .02f, .16f, 0x044433aa },   // thin vertical
            { .22f, .36f, .20f, .015f, 0x048844aa },  // very thin horizontal
            // Secondary cloud filaments
            { .70f, .52f, .20f, .018f, 0x054466aa },  // blue horizontal
            { .74f, .54f, .025f, .18f, 0x044455aa },  // blue vertical
            { .68f, .58f, .15f, .02f, 0x043355aa },   // thin thread
            // Cross-cloud filaments
            { .48f, .44f, .28f, .012f, 0x033344aa },  // very long thin bridge strand
            { .52f, .46f, .22f, .015f, 0x032233aa },  // parallel bridge strand
        };
        paintClouds(filaments, 10);

        // â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•
        // SOFT OVERLAPPING CLOUD LAYERS
        // Multiple semi-transparent ellipses that overlap
        // to create depth and billowing cloud texture
        // â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•
        CL cloudOverlaps[] = {
            // Primary region: stacked ovals at slight offsets
            { .28f, .34f, .16f, .14f, 0x066633aa },
            { .32f, .37f, .14f, .12f, 0x077744bb },
            { .26f, .31f, .12f, .16f, 0x055522aa },
            { .34f, .40f, .10f, .10f, 0x088855cc },
            { .30f, .28f, .13f, .11f, 0x066633aa },
            // Secondary region: billowing ovals
            { .70f, .53f, .12f, .14f, 0x054455aa },
            { .73f, .56f, .10f, .12f, 0x065566bb },
            { .68f, .51f, .14f, .10f, 0x044455aa },
            // Magenta region: soft billows
            { .44f, .66f, .10f, .08f, 0x06772255 },
            { .47f, .69f, .08f, .12f, 0x07883366 },
            { .50f, .64f, .12f, .06f, 0x05661144 },
        };
        paintClouds(cloudOverlaps, 11);

        // â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•
        // LUMINOUS RIM HIGHLIGHTS
        // Bright thin edges where cloud density transitions
        // Simulates backlit gas illumination
        // â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•
        CL rimLight[] = {
            { .24f, .27f, .04f, .02f, 0x0addaaff },  // primary upper rim
            { .38f, .42f, .03f, .02f, 0x08cc99ee },  // primary lower rim
            { .20f, .34f, .02f, .08f, 0x07bb88dd },  // primary left rim
            { .66f, .49f, .03f, .02f, 0x088899dd },  // secondary upper rim
            { .78f, .62f, .02f, .03f, 0x067788cc },  // secondary lower rim
            { .44f, .62f, .03f, .02f, 0x07994477 },  // magenta rim
        };
        paintClouds(rimLight, 6);

        // â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•
        // FILM GRAIN (photorealistic texture)
        // â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•
        juce::Random gr(42);
        for (int i = 0; i < w * h / 60; ++i)
        {
            float ga = gr.nextFloat() * 0.035f;
            g.setColour(juce::Colours::white.withAlpha(ga));
            g.fillRect(gr.nextInt(w), gr.nextInt(h), 1, 1);
        }
    }

    void renderStars(int w, int h)
    {
        starCache = juce::Image(juce::Image::ARGB, w, h, true);
        juce::Graphics g(starCache);
        juce::Random rng(12345);
        // Distant
        for (int i = 0; i < 200; ++i) {
            float sx = rng.nextFloat() * w, sy = rng.nextFloat() * h, sa = .15f + rng.nextFloat() * .2f, ss = .5f + rng.nextFloat() * .5f;
            g.setColour(juce::Colour(220, 220, (juce::uint8)(200 + rng.nextFloat() * 55)).withAlpha(sa)); g.fillEllipse(sx, sy, ss, ss);
        }
        // Medium
        for (int i = 0; i < 80; ++i) {
            float sx = rng.nextFloat() * w, sy = rng.nextFloat() * h, sa = .3f + rng.nextFloat() * .4f, ss = 1 + rng.nextFloat();
            auto c = juce::Colour((juce::uint8)(200 + rng.nextFloat() * 55), 215, (juce::uint8)(210 + rng.nextFloat() * 45));
            g.setColour(c.withAlpha(sa)); g.fillEllipse(sx - ss * .5f, sy - ss * .5f, ss, ss);
            g.setColour(c.withAlpha(sa * .15f)); g.fillEllipse(sx - ss, sy - ss, ss * 2, ss * 2);
        }
        // Bright
        for (int i = 0; i < 25; ++i) {
            float sx = rng.nextFloat() * w, sy = rng.nextFloat() * h, sa = .6f + rng.nextFloat() * .4f, ss = 1.5f + rng.nextFloat() * 1.5f;
            g.setColour(juce::Colour(0xffddccff).withAlpha(sa * .08f)); g.fillEllipse(sx - ss * 4, sy - ss * 4, ss * 8, ss * 8);
            g.setColour(juce::Colour(0xffddddff).withAlpha(sa * .2f)); g.fillEllipse(sx - ss * 2, sy - ss * 2, ss * 4, ss * 4);
            g.setColour(juce::Colours::white.withAlpha(sa)); g.fillEllipse(sx - ss * .5f, sy - ss * .5f, ss, ss);
        }
    }
};

// â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•
// GLASS-MORPHISM EFFECT SECTION
// â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•
class EffectSection : public juce::Component
{
public:
    EffectSection(const juce::String& t, const juce::Colour& a) : title(t), accent(a) {}
    void setDarkTheme(bool isDark) { themeDark = isDark; repaint(); }
    void paint(juce::Graphics& g) override
    {
        auto b = getLocalBounds().toFloat();
        g.setColour(themeDark ? juce::Colour(0x20101020) : juce::Colour(0x30ffffff)); g.fillRoundedRectangle(b, 10);
        g.setColour(themeDark ? juce::Colour(0x15ffffff) : juce::Colour(0x1e000000)); g.fillRoundedRectangle(b.reduced(1), 9);
        auto hl = b.removeFromTop(b.getHeight() * .4f);
        juce::ColourGradient hg(juce::Colour(0x08ffffff), hl.getCentreX(), hl.getY(), juce::Colours::transparentWhite, hl.getCentreX(), hl.getBottom(), false);
        g.setGradientFill(hg); g.fillRoundedRectangle(hl.reduced(1), 9);
        g.setColour(accent.withAlpha(0.25f)); g.drawRoundedRectangle(getLocalBounds().toFloat(), 10, 1.5f);
        auto ta = getLocalBounds().toFloat().removeFromTop(32);
        juce::ColourGradient tb(accent.withAlpha(.12f), ta.getX(), ta.getY(), accent.withAlpha(.03f), ta.getRight(), ta.getBottom(), false);
        g.setGradientFill(tb); g.fillRoundedRectangle(ta.reduced(2, 2), 8);
        g.setColour(accent.withAlpha(.9f)); g.setFont(juce::Font(juce::FontOptions(14.0f, juce::Font::bold))); g.drawText(title, ta, juce::Justification::centred);
    }
private:
    juce::String title; juce::Colour accent;
    bool themeDark = true;
};

// â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•
// MAIN EDITOR
// â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•
class CorvusFXAudioProcessorEditor : public juce::AudioProcessorEditor, public juce::Timer
{
public:
    CorvusFXAudioProcessorEditor(CorvusFXAudioProcessor&);
    ~CorvusFXAudioProcessorEditor() override;
    void paint(juce::Graphics&) override;
    void resized() override;
    void timerCallback() override;
    bool keyPressed(const juce::KeyPress& key) override;
    void toggleTheme();
private:
    CorvusFXAudioProcessor& audioProcessor;
    CorvusLookAndFeel corvusLookAndFeel;
    AnimatedBackground animatedBackground;
    juce::Label titleLabel; juce::ComboBox presetSelector; juce::Label presetLabel;
    AnimatedKnob overallKnob; juce::Label overallLabel;
    EffectSection distortionSection, chorusSection, delaySection, reverbSection;
    AnimatedKnob fatnessKnob; juce::Label fatnessLabel;
    juce::ToggleButton distortionBypassButton;
    juce::ToggleButton chorusBypassButton;
    juce::ToggleButton delayBypassButton;
    juce::ToggleButton reverbBypassButton;
    juce::ToggleButton masterBypassButton;
    AnimatedKnob chorusDepthKnob, chorusRateKnob, chorusMixKnob;
    juce::Label chorusDepthLabel, chorusRateLabel, chorusMixLabel;
    AnimatedKnob delayTimeKnob, delayFeedbackKnob, delayMixKnob, delayDampingKnob, delayModKnob;
    juce::Label delayTimeLabel, delayFeedbackLabel, delayMixLabel, delayDampingLabel, delayModLabel;
    AnimatedKnob reverbSizeKnob, reverbDampingKnob, reverbMixKnob, reverbModKnob;
    juce::Label reverbSizeLabel, reverbDampingLabel, reverbMixLabel, reverbModLabel;
    AnimatedKnob masterDriveKnob; juce::Label masterDriveLabel;
    AnimatedKnob masterWidthKnob; juce::Label masterWidthLabel;
    AnimatedKnob masterMidDriveKnob; juce::Label masterMidDriveLabel;
    AnimatedKnob masterSideDriveKnob; juce::Label masterSideDriveLabel;
    AnimatedKnob outputTrimKnob; juce::Label outputTrimLabel;
    std::unique_ptr<juce::AudioProcessorValueTreeState::SliderAttachment> overallAtt, fatnessAtt;
    std::unique_ptr<juce::AudioProcessorValueTreeState::ButtonAttachment> distortionBypassAtt;
    std::unique_ptr<juce::AudioProcessorValueTreeState::ButtonAttachment> chorusBypassAtt;
    std::unique_ptr<juce::AudioProcessorValueTreeState::ButtonAttachment> delayBypassAtt;
    std::unique_ptr<juce::AudioProcessorValueTreeState::ButtonAttachment> reverbBypassAtt;
    std::unique_ptr<juce::AudioProcessorValueTreeState::ButtonAttachment> masterBypassAtt;
    std::unique_ptr<juce::AudioProcessorValueTreeState::SliderAttachment> cDepAtt, cRateAtt, cMixAtt;
    std::unique_ptr<juce::AudioProcessorValueTreeState::SliderAttachment> dTimeAtt, dFbAtt, dMixAtt, dDampAtt, dModAtt;
    std::unique_ptr<juce::AudioProcessorValueTreeState::SliderAttachment> rSizeAtt, rDampAtt, rMixAtt, rModAtt;
    std::unique_ptr<juce::AudioProcessorValueTreeState::SliderAttachment> masterDriveAtt;
    std::unique_ptr<juce::AudioProcessorValueTreeState::SliderAttachment> masterWidthAtt;
    std::unique_ptr<juce::AudioProcessorValueTreeState::SliderAttachment> masterMidDriveAtt;
    std::unique_ptr<juce::AudioProcessorValueTreeState::SliderAttachment> masterSideDriveAtt;
    std::unique_ptr<juce::AudioProcessorValueTreeState::SliderAttachment> outputTrimAtt;
    std::unique_ptr<juce::AudioProcessorValueTreeState::ComboBoxAttachment> presetAtt;
    LevelMeter levelMeter;
    // Activates hover tooltips for all knobs/buttons (JUCE renders no
    // tooltips without a TooltipWindow instance in the component tree).
    juce::TooltipWindow tooltipWindow { this, 400 };

    // Preset A/B compare buttons
    juce::TextButton btnSlotA, btnSlotB, btnSaveAB;
    // Randomize preset button
    juce::TextButton randomizeButton;
    // Theme toggle button (also available via Ctrl+T)
    juce::TextButton themeToggleButton;
    // Theme state (plumbed in this slice; palette lands later)
    std::unique_ptr<juce::PropertiesFile> themeProperties;
    bool themeDark = true;
    JUCE_DECLARE_NON_COPYABLE_WITH_LEAK_DETECTOR(CorvusFXAudioProcessorEditor)
};
