#pragma once

#include <JuceHeader.h>
#include <algorithm>
#include <array>
#include <cmath>
#include <cstddef>
#include <cstdint>
#include <cstring>
#include <vector>

namespace corvus::tests
{
constexpr std::array<double, 3> renderRates { 44100.0, 48000.0, 96000.0 };
constexpr std::array<int, 3> renderBlocks { 64, 512, 1024 };

// The VST wrapper and UI both work with normalised values at the parameter
// boundary. Deliver a value-change listener event even without a UI gesture.
inline void setParameter(juce::AudioProcessorValueTreeState& state,
                         const char* id, float units, bool gesture = false)
{
    auto& parameter = *state.getParameter(id);
    if (gesture)
        parameter.beginChangeGesture();
    parameter.setValueNotifyingHost(parameter.convertTo0to1(units));
    if (gesture)
        parameter.endChangeGesture();
}

using Stereo = std::array<std::vector<float>, 2>;

inline float silence(int, int) { return 0.0f; }
inline void noMidi(juce::MidiBuffer&, int, int) {}

inline float sine(int frame, double rate, double hz, float amplitude, double phase = 0.0)
{
    return amplitude * static_cast<float>(
        std::sin(juce::MathConstants<double>::twoPi * hz * frame / rate + phase));
}

inline float noise(int channel, int frame)
{
    // Stateless seeded noise: changing block partitions cannot change input.
    auto bits = static_cast<std::uint32_t>(frame) * 2u
              + static_cast<std::uint32_t>(channel) + 0x2395b961u;
    bits = (bits ^ (bits >> 16u)) * 0x7feb352du;
    bits = (bits ^ (bits >> 15u)) * 0x846ca68bu;
    bits ^= bits >> 16u;
    return static_cast<float>(bits >> 8u) / 8388608.0f - 1.0f;
}

class Render
{
public:
    Render(juce::AudioProcessor& processorIn, double rate, int block)
        : processor(processorIn), blockSize(block), buffer(2, blockSize)
    {
        processor.setRateAndBufferSizeDetails(rate, blockSize);
        processor.prepareToPlay(rate, blockSize);
    }

    ~Render() { processor.releaseResources(); }

    // Call at automation boundaries, write parameters, then append again.
    // A short block before an event is legal and keeps its sample time exact.
    template <typename Input, typename Midi = decltype(&noMidi)>
    void append(int frames, Input input, Midi events = noMidi)
    {
        const int end = position + frames;
        while (position < end)
        {
            const int count = std::min(blockSize, end - position);
            buffer.setSize(2, count, false, false, true);
            for (int ch = 0; ch < 2; ++ch)
                for (int i = 0; i < count; ++i)
                    buffer.setSample(ch, i, input(ch, position + i));
            midi.clear();
            events(midi, position, count);
            processor.processBlock(buffer, midi);
            for (int ch = 0; ch < 2; ++ch)
            {
                const auto* start = buffer.getReadPointer(ch);
                output[static_cast<std::size_t>(ch)].insert(
                    output[static_cast<std::size_t>(ch)].end(), start, start + count);
            }
            position += count;
        }
    }

    Stereo output;

private:
    juce::AudioProcessor& processor;
    int blockSize;
    juce::AudioBuffer<float> buffer;
    juce::MidiBuffer midi;
    int position = 0;
};

inline bool isNormalOrZero(float sample)
{
    // Bit classification also works under /fp:fast and with FTZ/DAZ enabled.
    static_assert(sizeof(float) == sizeof(std::uint32_t));
    std::uint32_t bits = 0;
    std::memcpy(&bits, &sample, sizeof(bits));
    const auto exponent = bits & 0x7f800000u;
    return exponent != 0x7f800000u
        && (exponent != 0 || (bits & 0x007fffffu) == 0);
}

inline bool samplesAreNormal(const Stereo& output)
{
    for (const auto& channel : output)
        if (!std::all_of(channel.begin(), channel.end(), isNormalOrZero))
            return false;
    return true;
}

inline double rms(const std::vector<float>& samples, int start, int count)
{
    double energy = 0.0;
    for (int i = start; i < start + count; ++i)
    {
        const double value = samples[static_cast<std::size_t>(i)];
        energy += value * value;
    }
    return std::sqrt(energy / count);
}

inline float maxStep(const std::vector<float>& samples, int start, int count)
{
    float peak = 0.0f;
    for (int i = start; i < start + count; ++i)
        peak = std::max(peak, std::abs(samples[static_cast<std::size_t>(i)]
                                    - samples[static_cast<std::size_t>(i - 1)]));
    return peak;
}

inline float maxDifference(const Stereo& a, const Stereo& b, int start, int count)
{
    float peak = 0.0f;
    for (std::size_t ch = 0; ch < a.size(); ++ch)
        for (int i = start; i < start + count; ++i)
            peak = std::max(peak, std::abs(a[ch][static_cast<std::size_t>(i)]
                                        - b[ch][static_cast<std::size_t>(i)]));
    return peak;
}

// Least overhead for a single spectral bin. Use a whole number of periods
// for leakage-free level comparisons with the RMS of the same window.
inline double toneAmplitude(const std::vector<float>& samples, int start, int count,
                            double rate, double hz)
{
    double iSum = 0.0, qSum = 0.0;
    for (int i = 0; i < count; ++i)
    {
        const double phase = juce::MathConstants<double>::twoPi * hz * i / rate;
        const double value = samples[static_cast<std::size_t>(start + i)];
        iSum += value * std::cos(phase);
        qSum += value * std::sin(phase);
    }
    return 2.0 * std::hypot(iSum, qSum) / count;
}
}
