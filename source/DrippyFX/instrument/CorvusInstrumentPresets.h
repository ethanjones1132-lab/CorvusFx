#pragma once

#include "WavetableOscillator.h"

#include <array>

struct InstrumentPreset
{
    const char* name;
    FactoryWave wave;
    float attack;
    float decay;
    float sustain;
    float release;
    float fxAmount;
    float flight;
    float outputDb;
};

// Output levels are measured against the normalized split-history oversampler.
// Ashen/Cathedral retain their timbres with output-only trims to keep all five
// signature chord fixtures in the existing 0.07–0.13 RMS window.
inline constexpr std::array<InstrumentPreset, 5> corvusInstrumentPresets {{
    { "Dawn Choir", FactoryWave::Triangle, 0.35f, 1.20f, 0.82f, 4.50f,
      0.78f, 0.72f, 0.0f },
    { "Raven Glass", FactoryWave::Square, 0.01f, 0.42f, 0.52f, 1.40f,
      0.64f, 0.48f, -12.0f },
    { "Ashen Sky", FactoryWave::Saw, 0.08f, 1.10f, 0.68f, 3.20f,
      0.84f, 0.86f, -16.0f },
    { "Northern Signal", FactoryWave::Sine, 0.02f, 0.28f, 0.72f, 2.10f,
      0.56f, 0.40f, -12.0f },
    { "Cathedral Drift", FactoryWave::Triangle, 1.20f, 2.20f, 0.90f, 7.00f,
      0.95f, 1.00f, -12.0f }
}};
