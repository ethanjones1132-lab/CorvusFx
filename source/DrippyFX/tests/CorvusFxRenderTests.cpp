#include "CorvusRenderHarness.h"
#include "PluginProcessor.h"
#include <memory>
#include <utility>

juce::AudioProcessor* JUCE_CALLTYPE createPluginFilter();

namespace
{
using namespace corvus::tests;

auto makeFx()
{
    return std::unique_ptr<CorvusFXAudioProcessor>(
        static_cast<CorvusFXAudioProcessor*>(createPluginFilter()));
}

void isolate(CorvusFXAudioProcessor& fx, const char* enabled)
{
    setParameter(fx.apvts, "overall", 100.0f);
    setParameter(fx.apvts, "output_trim", 100.0f);
    for (const auto* id : { "distortion_bypass", "chorus_bypass", "delay_bypass",
                            "reverb_bypass", "master_bypass" })
        setParameter(fx.apvts, id, std::strcmp(id, enabled) == 0 ? 0.0f : 1.0f);
}

struct Setup
{
    double rate;
    int block;

    int ms(double milliseconds) const
    {
        return static_cast<int>(std::lround(rate * milliseconds / 1000.0));
    }

    juce::String label() const
    {
        return " [" + juce::String(static_cast<int>(rate)) + " Hz, "
                    + juce::String(block) + " frames]";
    }
};

void configureDelay(CorvusFXAudioProcessor& fx, float time)
{
    isolate(fx, "delay_bypass");
    setParameter(fx.apvts, "delay_time", time);
    setParameter(fx.apvts, "delay_mix", 100.0f);
    setParameter(fx.apvts, "delay_feedback", 0.0f);
    setParameter(fx.apvts, "delay_mod", 0.0f);
}

class CorvusFxRenderTests final : public juce::UnitTest
{
public:
    CorvusFxRenderTests() : juce::UnitTest("Corvus FX render regressions") {}

    void runTest() override
    {
        for (const auto rate : renderRates)
            for (const auto block : renderBlocks)
            {
                const Setup setup { rate, block };
                cleanSparkle(setup);
                mutedDelay(setup);
                mutedReverb(setup);
                reverbMix(setup);
                delayTime(setup);
                smoothControl(setup, true);
                smoothControl(setup, false);
                chorusBypass(setup);
            }
    }

private:
    void cleanSparkle(Setup setup)
    {
        beginTest("CV-070: fresh insert plays Clean Sparkle" + setup.label());
        auto fresh = makeFx();
        expectEquals(fresh->getCurrentProgram(), 0);
        expect(fresh->getProgramName(0) == "Clean Sparkle");
        // Published row in native units, independent of the code that seeds it.
        const std::pair<const char*, float> values[] = {
            { "fatness", 8 }, { "chorus_depth", 25 }, { "chorus_rate", 1.2f },
            { "chorus_mix", 35 }, { "delay_time", 0 }, { "delay_feedback", 0 },
            { "delay_mix", 0 }, { "delay_damping", 0 }, { "delay_mod", 0 },
            { "reverb_size", 20 }, { "reverb_damping", 55 }, { "reverb_mix", 10 },
            { "reverb_mod", 20 }, { "master_drive", 0 }, { "master_width", 100 },
            { "master_mid_drive", 0 }, { "master_side_drive", 0 },
            { "distortion_bypass", 0 }, { "chorus_bypass", 0 },
            { "delay_bypass", 0 }, { "reverb_bypass", 0 }, { "master_bypass", 0 },
            { "output_trim", 100 }
        };
        for (const auto& [id, expected] : values)
            expectWithinAbsoluteError(fresh->apvts.getRawParameterValue(id)->load(),
                                      expected, 1.0e-4f, id);
        (void) fresh->apvts.copyState(); // flushes pending APVTS tree writes, if any
        expect(!fresh->undoManager.canUndo(), "insertion must not create an undo step");

        auto recalled = makeFx();
        recalled->loadPreset(0);
        Render inserted(*fresh, setup.rate, setup.block);
        Render loaded(*recalled, setup.rate, setup.block);
        const auto impulse = [](int channel, int frame)
        {
            return frame == 0 ? (channel == 0 ? 0.22f : -0.14f) : 0.0f;
        };
        const auto frames = setup.ms(300);
        inserted.append(frames, impulse);
        loaded.append(frames, impulse);
        expect(samplesAreNormal(inserted.output));
        expect(rms(inserted.output[0], setup.ms(2), setup.ms(80)) > 1.0e-5,
               "a fresh impulse must excite the preset's audible wet tail");
        expectWithinAbsoluteError(maxDifference(inserted.output, loaded.output, 0, frames),
                                  0.0f, 1.0e-6f, "fresh and recalled preset must render alike");
    }

    void mutedDelay(Setup setup)
    {
        for (const bool bypass : { false, true })
        {
            beginTest(juce::String(bypass ? "CV-073: delay history under bypass"
                                         : "CV-073: delay history at zero Mix") + setup.label());
            const auto render = [&](bool mute)
            {
                auto processor = makeFx();
                configureDelay(*processor, 800.0f);
                auto& params = processor->apvts;
                Render audio(*processor, setup.rate, setup.block);
                audio.append(setup.ms(40), silence);
                if (mute)
                    setParameter(params, bypass ? "delay_bypass" : "delay_mix",
                                 bypass ? 1.0f : 0.0f);
                audio.append(setup.ms(40), silence);
                setParameter(params, "delay_time", 120.0f, true);
                audio.append(setup.ms(55), silence);
                const int marker = setup.ms(40) * 2 + setup.ms(55);
                audio.append(setup.ms(25), [marker](int, int frame)
                {
                    return frame == marker ? 0.20f : 0.0f;
                });
                if (mute)
                    setParameter(params, bypass ? "delay_bypass" : "delay_mix",
                                 bypass ? 0.0f : 100.0f);
                audio.append(setup.ms(140), silence);
                return std::move(audio.output);
            };
            const auto reference = render(false);
            const auto resumed = render(true);
            const int marker = setup.ms(40) * 2 + setup.ms(55);
            const int returned = marker + setup.ms(120);
            expect(samplesAreNormal(resumed));
            expectWithinAbsoluteError(resumed[0][static_cast<std::size_t>(marker)], 0.20f, 1.0e-6f,
                                      "muted delay must pass dry without stopping its history");
            expectWithinAbsoluteError(reference[0][static_cast<std::size_t>(returned)], 0.20f, 1.0e-6f);
            expectWithinAbsoluteError(maxDifference(reference, resumed, marker + setup.ms(65),
                                                     setup.ms(85)), 0.0f, 1.0e-6f,
                                      "the marker written while muted must arrive at the new time");
        }
    }

    void mutedReverb(Setup setup)
    {
        for (const bool bypass : { false, true })
        {
            beginTest(juce::String(bypass ? "CV-073: reverb history under bypass"
                                         : "CV-073: reverb history at zero Mix") + setup.label());
            const auto render = [&](bool mute)
            {
                auto processor = makeFx();
                isolate(*processor, "reverb_bypass");
                auto& params = processor->apvts;
                setParameter(params, "reverb_size", 80.0f);
                setParameter(params, "reverb_mod", 0.0f);
                setParameter(params, "reverb_mix", 100.0f);
                Render audio(*processor, setup.rate, setup.block);
                audio.append(setup.ms(70), silence);
                if (mute)
                    setParameter(params, bypass ? "reverb_bypass" : "reverb_mix",
                                 bypass ? 1.0f : 0.0f);
                audio.append(setup.ms(70), silence);
                audio.append(setup.ms(85), [](int channel, int frame)
                {
                    return 0.25f * noise(channel, frame);
                });
                if (mute)
                    setParameter(params, bypass ? "reverb_bypass" : "reverb_mix",
                                 bypass ? 0.0f : 100.0f);
                audio.append(setup.ms(160), silence);
                return std::move(audio.output);
            };
            const auto reference = render(false);
            const auto resumed = render(true);
            const int analysis = setup.ms(70) * 2 + setup.ms(85) + setup.ms(85);
            const int count = setup.ms(50);
            expect(samplesAreNormal(resumed));
            expect(rms(reference[0], analysis, count) > 1.0e-4,
                   "the reference tail must still have measurable energy");
            expectWithinAbsoluteError(maxDifference(reference, resumed, analysis, count),
                                      0.0f, 1.0e-6f, "the tank must keep time at zero output blend");
        }
    }

    void delayTime(Setup setup)
    {
        beginTest("CV-076: an audible time edit preserves repeat pitch" + setup.label());
        auto processor = makeFx();
        configureDelay(*processor, 40.0f);
        Render audio(*processor, setup.rate, setup.block);
        // Both taps are an integer number of 500 Hz periods from the input.
        // A crossfade should preserve that line, unlike an intermediate head
        // sweeping the history (including backwards on this length increase).
        const auto tone = [setup](int, int frame) { return sine(frame, setup.rate, 500.0, 0.10f, 0.6); };
        const int move = setup.ms(240);
        const int transition = setup.ms(40);
        audio.append(move, tone);
        setParameter(processor->apvts, "delay_time", 200.0f, true);
        audio.append(transition, tone);
        const auto& left = audio.output[0];
        expect(samplesAreNormal(audio.output));
        expectWithinAbsoluteError(toneAmplitude(left, move, transition, setup.rate, 500.0),
                                  0.10, 0.002);
        expectWithinAbsoluteError(rms(left, move, transition), 0.10 / std::sqrt(2.0), 0.002);
        for (const auto& channel : audio.output)
            expect(maxStep(channel, move, transition) < 0.015f, "smooth repeats must not click");

        // The spectrum check alone would pass if the time control did nothing.
        audio.append(setup.ms(230), silence);
        const int marker = move + transition + setup.ms(230);
        audio.append(setup.ms(210), [marker](int, int frame) { return frame == marker ? 0.20f : 0.0f; });
        expectWithinAbsoluteError(left[static_cast<std::size_t>(marker + setup.ms(40))], 0.0f, 1.0e-6f);
        expectWithinAbsoluteError(left[static_cast<std::size_t>(marker + setup.ms(200))], 0.20f, 1.0e-6f);
    }

    void reverbMix(Setup setup)
    {
        beginTest("CV-073: a reverb Mix fade persists across callbacks" + setup.label());
        const auto render = [&](int block)
        {
            auto processor = makeFx();
            isolate(*processor, "reverb_bypass");
            setParameter(processor->apvts, "reverb_mix", 0.0f);
            const auto tone = [setup](int, int frame)
            {
                return sine(frame, setup.rate, 220.0, 0.20f, 0.5);
            };
            Render audio(*processor, setup.rate, block);
            audio.append(setup.ms(100), tone);
            setParameter(processor->apvts, "reverb_mix", 100.0f, true);
            audio.append(setup.ms(40), tone);
            return std::move(audio.output);
        };
        const auto actual = render(setup.block);
        const auto reference = render(setup.block == 64 ? 512 : 64);
        const int move = setup.ms(100);
        expect(samplesAreNormal(actual));
        expectWithinAbsoluteError(maxDifference(actual, reference, move, setup.ms(40)),
                                  0.0f, 1.0e-5f, "repeating a target must not truncate its fade");
        expect(maxStep(actual[0], move, setup.ms(40)) < 0.025f);
    }

    void smoothControl(Setup setup, bool drive)
    {
        beginTest(juce::String(drive ? "CV-078: Drive level follows the ramp inside a block"
                                     : "CV-079: Chorus Mix follows the ramp inside a block") + setup.label());
        const auto tone = [setup, drive](int channel, int frame)
        {
            return sine(frame, setup.rate, drive ? 500.0 : 173.0, drive ? 0.025f : 0.12f,
                        channel == 0 ? 0.6 : 1.1);
        };
        const auto render = [&](int block)
        {
            auto processor = makeFx();
            isolate(*processor, drive ? "distortion_bypass" : "chorus_bypass");
            auto& params = processor->apvts;
            const auto* id = drive ? "fatness" : "chorus_mix";
            setParameter(params, "chorus_depth", 60.0f);
            setParameter(params, "chorus_rate", 1.3f);
            setParameter(params, id, drive ? 10.0f : 0.0f);
            Render audio(*processor, setup.rate, block);
            audio.append(setup.ms(100), tone);
            setParameter(params, id, drive ? 85.0f : 100.0f, true);
            audio.append(setup.ms(100), tone);
            return std::move(audio.output);
        };
        const auto actual = render(setup.block);
        const auto reference = render(setup.block == 64 ? 512 : 64);
        const int move = setup.ms(100);
        expect(samplesAreNormal(actual));
        expectWithinAbsoluteError(maxDifference(actual, reference, move, setup.ms(40)),
                                  0.0f, 1.0e-5f, "same automation sample, different host partition");
        expect(maxStep(actual[0], move, setup.ms(40)) < 0.04f, "the move must not click");
        if (drive)
        {
            const auto count = setup.ms(40);
            const auto before = move - count;
            const auto after = move + setup.ms(60);
            const auto low = rms(actual[0], before, count);
            const auto high = rms(actual[0], after, count);
            expect(low > 0.01 && high > low * 1.5 && high < 0.35,
                   "the Drive ramp must end at a materially different, unrailed level");
            expect(toneAmplitude(actual[0], after, count, setup.rate, 500.0)
                   > 1.5 * toneAmplitude(actual[0], before, count, setup.rate, 500.0),
                   "the change in level must include the fundamental, not just new harmonics");
        }
        else
        {
            float wetDifference = 0.0f;
            for (int i = move + setup.ms(60); i < move + setup.ms(100); ++i)
                wetDifference = std::max(wetDifference,
                    std::abs(actual[0][static_cast<std::size_t>(i)] - tone(0, i)));
            expect(wetDifference > 0.02f, "the wet end must not just pass the dry tone");
        }
    }

    void chorusBypass(Setup setup)
    {
        for (const bool dropDepth : { false, true })
        {
            beginTest(juce::String(dropDepth ? "CV-080: Depth can disengage while bypassed"
                                             : "CV-080: bypass does not pause chorus history")
                      + setup.label());
            auto processor = makeFx();
            isolate(*processor, "chorus_bypass");
            auto& params = processor->apvts;
            setParameter(params, "chorus_depth", 65.0f);
            setParameter(params, "chorus_mix", 100.0f);
            Render audio(*processor, setup.rate, setup.block);
            const auto tone = [setup](int, int frame) { return sine(frame, setup.rate, 173.0, 0.25f); };
            const int prime = setup.ms(150);
            const int fade = setup.ms(40);
            const int muted = setup.ms(500);
            audio.append(prime, tone);
            setParameter(params, "chorus_bypass", 1.0f);
            audio.append(fade, tone); // leave nonzero samples in the old frozen ring
            if (dropDepth)
                setParameter(params, "chorus_depth", 0.0f, true);
            audio.append(muted, silence);
            setParameter(params, "chorus_bypass", 0.0f);
            const int resumed = prime + fade + muted;
            const int quiet = setup.ms(dropDepth ? 2 : 15);
            audio.append(quiet, silence);
            for (const auto& channel : audio.output)
                expect(rms(channel, resumed, quiet) < 2.0e-5,
                       "enabling on silence must not replay the pre-bypass tone");
            if (dropDepth)
            {
                const int toneStart = resumed + quiet;
                const auto newTone = [setup, toneStart](int, int frame)
                {
                    return sine(frame - toneStart, setup.rate, 173.0, 0.25f);
                };
                audio.append(fade - quiet, newTone);
                float dryError = 0.0f;
                for (int i = toneStart; i < resumed + fade; ++i)
                    dryError = std::max(dryError,
                        std::abs(audio.output[0][static_cast<std::size_t>(i)] - newTone(0, i)));
                expectWithinAbsoluteError(dryError, 0.0f, 1.0e-6f,
                                          "Depth already reached dry while bypassed");
            }
            expect(samplesAreNormal(audio.output));
        }
    }
};

CorvusFxRenderTests corvusFxRenderTests;
}
