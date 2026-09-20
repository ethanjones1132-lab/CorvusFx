#pragma once

#include <JuceHeader.h>

#include <algorithm>
#include <array>
#include <cmath>
#include <cstddef>

enum class FactoryWave
{
    Sine,
    Triangle,
    Saw,
    Square
};

class WavetableOscillator
{
public:
    void prepare(double newSampleRate)
    {
        if (!std::isfinite(newSampleRate) || newSampleRate <= 0.0)
        {
            jassertfalse;
            sampleRate = 0.0;
            frequencyHz = 0.0f;
            phaseIncrement = 0.0;
            return;
        }

        sampleRate = newSampleRate;
        setFrequency(frequencyHz);
    }

    void setFrequency(float newFrequencyHz)
    {
        if (!std::isfinite(newFrequencyHz)
            || newFrequencyHz <= 0.0f
            || sampleRate <= 0.0
            || newFrequencyHz > static_cast<float>(sampleRate * 0.5))
        {
            frequencyHz = 0.0f;
            phaseIncrement = 0.0;
            return;
        }

        frequencyHz = newFrequencyHz;
        phaseIncrement = static_cast<double>(frequencyHz) / sampleRate;
    }

    void setWave(FactoryWave newWave) noexcept
    {
        wave = newWave;
    }

    void reset(float newPhase = 0.0f) noexcept
    {
        if (!std::isfinite(newPhase))
        {
            phase = 0.0;
            return;
        }

        phase = static_cast<double>(newPhase) - std::floor(static_cast<double>(newPhase));
    }

    float process() noexcept
    {
        if (phaseIncrement <= 0.0 || sampleRate <= 0.0)
            return 0.0f;

        const auto waveIndex = juce::jlimit<std::size_t>(
            0, waveCount - 1, static_cast<std::size_t>(wave));
        const auto& table = tables()[waveIndex][selectMipLevel()];
        const auto tablePosition = phase * static_cast<double>(tableSize);
        const auto index = static_cast<std::size_t>(tablePosition) & tableMask;
        const auto nextIndex = (index + 1) & tableMask;
        const auto fraction = static_cast<float>(
            tablePosition - static_cast<double>(static_cast<std::size_t>(tablePosition)));
        const auto output = table[index] + (table[nextIndex] - table[index]) * fraction;

        phase += phaseIncrement;
        phase -= std::floor(phase);
        return output;
    }

private:
    static constexpr auto tableSize = std::size_t { 2048 };
    static constexpr auto tableMask = tableSize - 1;
    static constexpr auto mipLevelCount = std::size_t { 11 };
    static constexpr auto waveCount = std::size_t { 4 };
    static_assert((tableSize & tableMask) == 0, "wavetable size must be a power of two");

    using Table = std::array<float, tableSize>;
    using MipTables = std::array<Table, mipLevelCount>;
    using TableBank = std::array<MipTables, waveCount>;

    static bool harmonicIsPresent(FactoryWave factoryWave, int harmonic) noexcept
    {
        if (factoryWave == FactoryWave::Sine)
            return harmonic == 1;
        if (factoryWave == FactoryWave::Triangle || factoryWave == FactoryWave::Square)
            return (harmonic & 1) != 0;
        return true;
    }

    static double harmonicAmplitude(FactoryWave factoryWave, int harmonic) noexcept
    {
        if (factoryWave == FactoryWave::Triangle)
        {
            const auto alternatingSign = ((harmonic - 1) / 2) % 2 == 0 ? 1.0 : -1.0;
            return alternatingSign / static_cast<double>(harmonic * harmonic);
        }
        if (factoryWave == FactoryWave::Saw)
            return -1.0 / static_cast<double>(harmonic);
        if (factoryWave == FactoryWave::Square)
            return 1.0 / static_cast<double>(harmonic);
        return harmonic == 1 ? 1.0 : 0.0;
    }

    static Table createTable(FactoryWave factoryWave, int harmonicLimit)
    {
        Table table {};
        const auto limitedHarmonics = factoryWave == FactoryWave::Sine
            ? 1
            : juce::jlimit(1, static_cast<int>(tableSize / 2 - 1), harmonicLimit);

        auto maximumMagnitude = 0.0;
        for (std::size_t sample = 0; sample < tableSize; ++sample)
        {
            const auto phaseRadians = juce::MathConstants<double>::twoPi
                * static_cast<double>(sample) / static_cast<double>(tableSize);
            auto value = 0.0;
            for (auto harmonic = 1; harmonic <= limitedHarmonics; ++harmonic)
            {
                if (harmonicIsPresent(factoryWave, harmonic))
                    value += harmonicAmplitude(factoryWave, harmonic)
                        * std::sin(phaseRadians * static_cast<double>(harmonic));
            }
            table[sample] = static_cast<float>(value);
            maximumMagnitude = std::max(maximumMagnitude, std::abs(value));
        }

        if (maximumMagnitude > 0.0)
        {
            const auto normalise = static_cast<float>(1.0 / maximumMagnitude);
            for (auto& sample : table)
                sample *= normalise;
        }

        return table;
    }

    static TableBank createTableBank()
    {
        TableBank bank {};
        for (std::size_t waveIndex = 0; waveIndex < waveCount; ++waveIndex)
        {
            const auto factoryWave = static_cast<FactoryWave>(waveIndex);
            for (std::size_t mipLevel = 0; mipLevel < mipLevelCount; ++mipLevel)
            {
                const auto harmonicLimit = 1 << static_cast<int>(mipLevel);
                bank[waveIndex][mipLevel] = createTable(factoryWave, harmonicLimit);
            }
        }
        return bank;
    }

    static const TableBank& tables()
    {
        static const auto bank = createTableBank();
        return bank;
    }

    std::size_t selectMipLevel() const noexcept
    {
        const auto maximumHarmonic = static_cast<int>(
            std::floor((sampleRate * 0.5) / static_cast<double>(frequencyHz)));
        auto selectedLevel = std::size_t { 0 };
        while (selectedLevel + 1 < mipLevelCount
               && (1 << static_cast<int>(selectedLevel + 1)) <= maximumHarmonic)
            ++selectedLevel;
        return selectedLevel;
    }

    double sampleRate = 0.0;
    double phase = 0.0;
    double phaseIncrement = 0.0;
    float frequencyHz = 0.0f;
    FactoryWave wave = FactoryWave::Sine;
};
