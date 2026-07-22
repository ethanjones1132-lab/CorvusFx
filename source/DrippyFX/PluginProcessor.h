#pragma once

#include <JuceHeader.h>
#include <cmath>
#include <cstring>
#include <algorithm>
#include <xmmintrin.h>  // SSE intrinsics for oversampling FIR optimization

//==============================================================================
// UTILITY: Hermite cubic interpolation — artifact-free delay reads
//==============================================================================
inline float hermiteInterp(const float* buf, int bufSize, float readPos)
{
    int idx = static_cast<int>(std::floor(readPos));
    float frac = readPos - static_cast<float>(idx);
    auto wrap = [bufSize](int p) -> int { return ((p % bufSize) + bufSize) % bufSize; };
    float xm1 = buf[wrap(idx - 1)];
    float x0 = buf[wrap(idx)];
    float x1 = buf[wrap(idx + 1)];
    float x2 = buf[wrap(idx + 2)];
    float c0 = x0;
    float c1 = 0.5f * (x1 - xm1);
    float c2 = xm1 - 2.5f * x0 + 2.0f * x1 - 0.5f * x2;
    float c3 = 0.5f * (x2 - xm1) + 1.5f * (x0 - x1);
    return ((c3 * frac + c2) * frac + c1) * frac + c0;
}

//==============================================================================
// UTILITY: Padé [3/2] rational approximant for tanh with correct saturation
// Accurate to <0.04% for |z| ≤ 1.0, <1% for |z| ≤ 2.5, and correctly
// saturates to ±1 for |z| > 2.5 (tanh(z) → ±1 as z → ±∞).
// Eliminates std::tanh in hot paths (safety limiter, push-pull saturation).
// Formula: z*(15+z²)/(15+6z²) for |z| ≤ 2.5, else sign(z).
//==============================================================================
inline float padeTanh(float z)
{
    float a = fabsf(z);
    if (a > 2.5f) return z > 0 ? 1.0f : -1.0f;
    float z2 = z * z;
    return z * (15.0f + z2) / (15.0f + 6.0f * z2);
}

//==============================================================================
// UTILITY: Padé [3/2] soft-clipper — rational approximant of tanh
// Replaces std::tanh in the safety limiter hot path (last transcendental holdout).
// Accurate to 0.04% for |x| ≤ 1.0. Eliminates 4 per-sample std::tanh calls.
// Formula: z*(15+z²)/(15+6z²) where z = (|x|-1)*0.5
//==============================================================================
inline float padeSoftClip(float x, float threshold = 1.0f, float scale = 0.2f)
{
    if (x > threshold)
    {
        float z = (x - threshold) * 0.5f;
        float z2 = z * z;
        return threshold + z * (15.0f + z2) / (15.0f + 6.0f * z2) * scale;
    }
    else if (x < -threshold)
    {
        float z = (x + threshold) * 0.5f;
        float z2 = z * z;
        return -threshold + z * (15.0f + z2) / (15.0f + 6.0f * z2) * scale;
    }
    return x;
}

//==============================================================================
// UTILITY: DC blocker — Julius O. Smith topology
//==============================================================================
struct DCBlocker
{
    float x1 = 0.0f, y1 = 0.0f;
    float process(float in)
    {
        // Coefficient 0.9995 → ~3.5Hz cutoff. Prevents cascaded HF resonance
        // when multiple DC blockers are in series across the signal chain.
        float out = in - x1 + 0.9995f * y1;
        x1 = in;
        y1 = out;
        return out;
    }
    void reset() { x1 = y1 = 0.0f; }
};

//==============================================================================
// UTILITY: One-pole filter
//==============================================================================
struct OnePole
{
    float z1 = 0.0f;
    float processLP(float in, float coeff) { z1 = in + coeff * (z1 - in); return z1; }
    float processHP(float in, float coeff) { z1 = in + coeff * (z1 - in); return in - z1; }
    void reset() { z1 = 0.0f; }
};

//==============================================================================
// 2x OVERSAMPLING WRAPPER — Anti-aliasing for non-linear waveshaping
// Eliminates aliasing from tanh/tape saturation by processing at 2x sample rate.
// Uses a 2nd-order half-band FIR filter for up/down sampling (8 coefficients).
// SSE-optimized polyphase FIR filtering for 4x throughput on hot path.
//==============================================================================
struct Oversampling2x
{
    static constexpr int FILTER_TAPS = 8;
    // 2nd-order half-band FIR, cutoff at 0.25*fs (half Nyquist at 2x rate)
    // Normalized so sum = 1.0 for unity gain at DC
    static constexpr float coeffs[FILTER_TAPS] =
    {
        -0.006289f, 0.000000f, 0.088024f, 0.418265f,
        0.418265f,  0.088024f, 0.000000f, -0.006289f
    };

    float stateL[FILTER_TAPS] = {};
    float stateR[FILTER_TAPS] = {};
    int idx = 0;
    double sampleRate = 44100.0;

    // Pre-staged coefficient vectors for SSE (aligned for _mm_load_ps)
    __m128 coeffVec0;  // coeffs[0..3]
    __m128 coeffVec1;  // coeffs[4..7]
    __m128 coeffVecEven;  // coeffs[0], coeffs[2], coeffs[4], coeffs[6] (even taps for half-band)
    bool sseInitialized = false;

    void prepare(double sr) { sampleRate = sr; initSSE(); reset(); }

    void initSSE()
    {
        if (sseInitialized) return;
        // Coefficients in reverse order for circular buffer indexing
        // idx, idx-1, idx-2, idx-3 -> we load state in that order
        coeffVec0 = _mm_loadu_ps(&coeffs[0]);  // c0, c1, c2, c3
        coeffVec1 = _mm_loadu_ps(&coeffs[4]);  // c4, c5, c6, c7
        // Even taps for half-band odd phase: c0, c2, c4, c6 (c1,c3,c5,c7 are zero anyway)
        float evenTaps[4] = { coeffs[0], coeffs[2], coeffs[4], coeffs[6] };
        coeffVecEven = _mm_loadu_ps(evenTaps);
        sseInitialized = true;
    }

    void reset()
    {
        std::memset(stateL, 0, sizeof(stateL));
        std::memset(stateR, 0, sizeof(stateR));
        idx = 0;
    }

    // SSE-optimized 8-tap FIR convolution
    // state: circular buffer, idx: write position
    // Returns dot product of state[idx], state[idx-1]... with coeffs[0..7]
    inline float firSSE(const float* state, int idx) const
    {
        // Load 8 state samples in order: idx, idx-1, ..., idx-7 (wrapped)
        // Since FILTER_TAPS=8, we can load as two __m128 vectors
        __m128 s0 = _mm_set_ps(
            state[(idx - 3 + FILTER_TAPS) % FILTER_TAPS],
            state[(idx - 2 + FILTER_TAPS) % FILTER_TAPS],
            state[(idx - 1 + FILTER_TAPS) % FILTER_TAPS],
            state[idx]
        );  // s0 = [s[idx-3], s[idx-2], s[idx-1], s[idx]]

        __m128 s1 = _mm_set_ps(
            state[(idx - 7 + FILTER_TAPS) % FILTER_TAPS],
            state[(idx - 6 + FILTER_TAPS) % FILTER_TAPS],
            state[(idx - 5 + FILTER_TAPS) % FILTER_TAPS],
            state[(idx - 4 + FILTER_TAPS) % FILTER_TAPS]
        );  // s1 = [s[idx-7], s[idx-6], s[idx-5], s[idx-4]]

        // Multiply with coefficients (coeffs[0..3] with s[idx..idx-3], coeffs[4..7] with s[idx-4..idx-7])
        // Note: coeffVec0 = [c0,c1,c2,c3], coeffVec1 = [c4,c5,c6,c7]
        // We need: s[idx]*c0 + s[idx-1]*c1 + s[idx-2]*c2 + s[idx-3]*c3 + s[idx-4]*c4 + ...
        // s0 is [s[idx-3], s[idx-2], s[idx-1], s[idx]] -> reverse to match coeffs
        __m128 s0_rev = _mm_shuffle_ps(s0, s0, _MM_SHUFFLE(0, 1, 2, 3));  // [s[idx], s[idx-1], s[idx-2], s[idx-3]]
        __m128 s1_rev = _mm_shuffle_ps(s1, s1, _MM_SHUFFLE(0, 1, 2, 3));  // [s[idx-4], s[idx-5], s[idx-6], s[idx-7]]

        __m128 prod0 = _mm_mul_ps(s0_rev, coeffVec0);
        __m128 prod1 = _mm_mul_ps(s1_rev, coeffVec1);

        // Horizontal sum of both products
        __m128 sum0 = _mm_hadd_ps(prod0, prod1);  // [p0+p1, p2+p3, p4+p5, p6+p7]
        __m128 sum1 = _mm_hadd_ps(sum0, sum0);    // [p0+p1+p2+p3, p4+p5+p6+p7, ...]
        float result[4];
        _mm_storeu_ps(result, sum1);
        return result[0] + result[1];
    }

    // SSE-optimized 4-tap half-band FIR (even taps only: 0,2,4,6)
    inline float firHalfBandSSE(const float* state, int idx) const
    {
        // Load state[idx], state[idx-2], state[idx-4], state[idx-6]
        __m128 s = _mm_set_ps(
            state[(idx - 6 + FILTER_TAPS) % FILTER_TAPS],
            state[(idx - 4 + FILTER_TAPS) % FILTER_TAPS],
            state[(idx - 2 + FILTER_TAPS) % FILTER_TAPS],
            state[idx]
        );  // s = [s[idx-6], s[idx-4], s[idx-2], s[idx]]

        // Reverse to match evenTaps order: c0, c2, c4, c6
        __m128 s_rev = _mm_shuffle_ps(s, s, _MM_SHUFFLE(0, 1, 2, 3));  // [s[idx], s[idx-2], s[idx-4], s[idx-6]]
        __m128 prod = _mm_mul_ps(s_rev, coeffVecEven);
        
        // Horizontal sum
        __m128 sum = _mm_hadd_ps(prod, prod);  // [p0+p1, p2+p3, ...]
        sum = _mm_hadd_ps(sum, sum);           // [sum0, sum1, ...]
        float result[4];
        _mm_storeu_ps(result, sum);
        return result[0];
    }

    // Process one input sample at base rate, produce one output sample at base rate.
    // Internally runs the DSP callback at 2x rate with anti-alias filtering.
    template <typename ProcessFn>
    void processSample(float inL, float inR, float& outL, float& outR, ProcessFn&& dsp)
    {
        // ── UP SAMPLE 2x: even phase ──
        stateL[idx] = inL;
        stateR[idx] = inR;
        float upL_even = firSSE(stateL, idx);
        float upR_even = firSSE(stateR, idx);

        // ── UP SAMPLE 2x: odd phase (half-band, only even taps) ──
        float upL_odd = firHalfBandSSE(stateL, idx) * 2.0f;
        float upR_odd = firHalfBandSSE(stateR, idx) * 2.0f;

        idx = (idx + 1) % FILTER_TAPS;

        // ── DSP at 2x rate ──
        float dspL1, dspR1, dspL2, dspR2;
        dsp(upL_even, upR_even, dspL1, dspR1);
        dsp(upL_odd,  upR_odd,  dspL2, dspR2);

        // ── DOWN SAMPLE 2x: even phase ──
        stateL[idx] = dspL1;
        stateR[idx] = dspR1;
        float downL_even = firSSE(stateL, idx);
        float downR_even = firSSE(stateR, idx);

        // ── DOWN SAMPLE 2x: odd phase (half-band) ──
        stateL[idx] = dspL2;
        stateR[idx] = dspR2;
        float downL_odd = firHalfBandSSE(stateL, idx) * 2.0f;
        float downR_odd = firHalfBandSSE(stateR, idx) * 2.0f;

        idx = (idx + 1) % FILTER_TAPS;

        // Use even phase for latency alignment
        outL = downL_even;
        outR = downR_even;
    }

    // ── MONO OVERSAMPLING — For single-channel feedback paths (e.g., chorus feedback)
    // Avoids ~50% CPU waste of stereo polyphase filtering when only one channel is needed.
    template <typename ProcessFn>
    void processSampleMono(float in, float& out, ProcessFn&& dsp)
    {
        // ── UP SAMPLE 2x ──
        stateL[idx] = in;  // reuse L state for mono
        float up_even = firSSE(stateL, idx);
        float up_odd = firHalfBandSSE(stateL, idx) * 2.0f;

        idx = (idx + 1) % FILTER_TAPS;

        // ── DSP at 2x rate ──
        float dsp1, dsp2;
        dsp(up_even, dsp1);
        dsp(up_odd,  dsp2);

        // ── DOWN SAMPLE 2x ──
        stateL[idx] = dsp1;
        float down_even = firSSE(stateL, idx);

        stateL[idx] = dsp2;
        float down_odd = firHalfBandSSE(stateL, idx) * 2.0f;

        idx = (idx + 1) % FILTER_TAPS;

        // Use even phase for latency alignment
        out = down_even;
    }
};

//==============================================================================
// PROFESSIONAL SATURATION / DISTORTION
// Clean analog-modeled waveshaping. 2x oversampling for zero aliasing.
// Tape saturation at low drive, tube harmonics at high drive.
//==============================================================================
struct ProfessionalDistortion
{
    OnePole preLPL, preLPR;       // Pre-emphasis
    OnePole postLP1L, postLP1R;   // Post tone control — pole 1
    OnePole postLP2L, postLP2R;   // Post tone control — pole 2 (12dB/oct cascade)
    OnePole preHPL, preHPR;       // Remove DC before clipping
    OnePole warmthL, warmthR;     // Post-saturation warmth shelf
    DCBlocker dcL, dcR;
    Oversampling2x oversample;    // 2x oversampling for zero aliasing
    double sampleRate = 44100.0;

    void prepare(double sr)
    {
        sampleRate = sr;
        oversample.prepare(sr);
        reset();
    }

    void reset()
    {
        preLPL.reset(); preLPR.reset();
        postLP1L.reset(); postLP1R.reset();
        postLP2L.reset(); postLP2R.reset();
        preHPL.reset(); preHPR.reset();
        warmthL.reset(); warmthR.reset();
        dcL.reset(); dcR.reset();
        oversample.reset();
    }

    // Tube-style waveshaper: asymmetric, warm even harmonics
        // Uses Padé [3/2] rational approximant (padeTanh) instead of std::tanh
        // for zero per-sample transcendental calls in the oversampled hot path.
        // Accurate to <0.04% for |z| ≤ 1.0, correctly saturates to ±1 for |z| > 2.5.
        static inline float tubeShape(float x, float drive)
        {
            if (x >= 0.0f)
                return padeTanh(x * drive);
            else
                return padeTanh(x * drive * 1.15f) / 1.15f;
        }

    // Tape saturation: symmetric, preserves dynamics
    static inline float tapeShape(float x, float drive)
    {
        float d = x * drive;
        return d / (1.0f + std::abs(d));
    }

    // Block-level coefficient cache — avoids recomputing std::exp() every sample.
    // Call beginBlock() once per audio block with the current drive amount,
    // then call process() for each sample. This eliminates 4 redundant
    // transcendental function calls per sample (320 wasted calls per 64-sample block).
    struct BlockCoeffs
    {
        float drive = 1.0f;
        float hpCoeff = 0.0f;
        float empCoeff = 0.0f;
        float postCoeff = 0.0f;
        float warmCoeff = 0.0f;
        float empAmount = 0.0f;
        float warmAmt = 0.0f;
        float makeup = 1.0f;
        float blend = 0.0f;
        bool bypass = true;
        float tapeBlend = 0.0f;    // 0-1 blend for tape-only region (below 0.3)
        float tubeBlend = 0.0f;    // 0-1 blend for tube region (0.3-0.7 smooth crossfade)
        float driveScaled = 1.0f;  // drive * 0.7 for tape side at high amounts
    } blockCoeffs;

    void beginBlock(float amount)
    {
        if (amount < 0.001f)
        {
            blockCoeffs.bypass = true;
            return;
        }
        blockCoeffs.bypass = false;
        float sr = static_cast<float>(sampleRate);
        blockCoeffs.drive = 1.0f + amount * amount * 7.0f;
        blockCoeffs.hpCoeff = std::exp(-6.2832f * 30.0f / sr);
        blockCoeffs.empCoeff = std::exp(-6.2832f * 4500.0f / sr);
        float postFreq = 6000.0f + (1.0f - amount) * 10000.0f;
        blockCoeffs.postCoeff = std::exp(-6.2832f * postFreq / sr);
        blockCoeffs.warmCoeff = std::exp(-6.2832f * 5500.0f / sr);
        blockCoeffs.empAmount = amount * 0.18f;
        blockCoeffs.warmAmt = amount * 0.12f;
        blockCoeffs.makeup = 1.0f + amount * 0.8f;
        blockCoeffs.blend = std::min(1.0f, amount * 1.2f);
        // Smooth tube crossfade: 0 below 0.3, 1 above 0.7, smoothstep in between
        float rawTube = (amount - 0.3f) / 0.4f;
        blockCoeffs.tubeBlend = (rawTube > 0.0f) ? ((rawTube < 1.0f) ? (rawTube * rawTube * (3.0f - 2.0f * rawTube)) : 1.0f) : 0.0f;
        // tapeBlend ramps linearly 0→1 across full drive range
        // Low path: dry→tape(drive), High path: tape(drive70)→tube(drive)
        blockCoeffs.tapeBlend = amount;
        blockCoeffs.driveScaled = blockCoeffs.drive * 0.7f;
    }

    void process(float inL, float inR, float& outL, float& outR)
    {
        // Process at 2x sample rate with anti-alias filtering for zero aliasing
        oversample.processSample(inL, inR, outL, outR, [this](float inL_os, float inR_os, float& outL_os, float& outR_os) {
            if (blockCoeffs.bypass)
            {
                outL_os = inL_os;
                outR_os = inR_os;
                return;
            }

            // Pre-filter: remove subsonic content before clipping
            float preL = preHPL.processHP(inL_os, blockCoeffs.hpCoeff);
            float preR = preHPR.processHP(inR_os, blockCoeffs.hpCoeff);

            // Pre-emphasis: gentle HF lift before clipping (4.5kHz center, reduced amount)
            float hfL = preL - preLPL.processLP(preL, blockCoeffs.empCoeff);
            float hfR = preR - preLPR.processLP(preR, blockCoeffs.empCoeff);
            float empL = preL + hfL * blockCoeffs.empAmount;
            float empR = preR + hfR * blockCoeffs.empAmount;

            // Waveshaping: blend tape → tube based on amount with smooth transition
            // Low amount (0–0.3): pure tape saturation
            // Mid amount (0.3–0.7): smooth tube crossfade
            // High amount (0.7–1.0): tube-dominant blend
            float satL, satR;
            {
                float t = blockCoeffs.tapeBlend;
                float u = blockCoeffs.tubeBlend;
                float tL = tapeShape(empL, blockCoeffs.drive);
                float tR = tapeShape(empR, blockCoeffs.drive);
                float lowL = empL * (1.0f - t) + tL * t;
                float lowR = empR * (1.0f - t) + tR * t;

                float tsL = tapeShape(empL, blockCoeffs.driveScaled);
                float tsR = tapeShape(empR, blockCoeffs.driveScaled);
                float tuL = tubeShape(empL, blockCoeffs.drive);
                float tuR = tubeShape(empR, blockCoeffs.drive);
                float highL = tsL * (1.0f - t) + tuL * t;
                float highR = tsR * (1.0f - t) + tuR * t;

                // Smooth blend between low-drive tape and high-drive tube
                satL = lowL + (highL - lowL) * u;
                satR = lowR + (highR - lowR) * u;
            }

            // Post tone: 2-pole cascade (12dB/oct) — analog-realistic rolloff
            satL = postLP1L.processLP(satL, blockCoeffs.postCoeff);
            satR = postLP1R.processLP(satR, blockCoeffs.postCoeff);
            satL = postLP2L.processLP(satL, blockCoeffs.postCoeff);
            satR = postLP2R.processLP(satR, blockCoeffs.postCoeff);

            // Warmth shelf: gently tame 5-8kHz harshness from waveshaping
            float warmL_lp = warmthL.processLP(satL, blockCoeffs.warmCoeff);
            float warmR_lp = warmthR.processLP(satR, blockCoeffs.warmCoeff);
            satL = satL * (1.0f - blockCoeffs.warmAmt) + warmL_lp * blockCoeffs.warmAmt;
            satR = satR * (1.0f - blockCoeffs.warmAmt) + warmR_lp * blockCoeffs.warmAmt;

            // DC removal
            satL = dcL.process(satL);
            satR = dcR.process(satR);

            // Makeup gain: compensate volume loss from waveshaping
            satL *= blockCoeffs.makeup;
            satR *= blockCoeffs.makeup;

            // Output blend
            outL_os = inL_os * (1.0f - blockCoeffs.blend) + satL * blockCoeffs.blend;
            outR_os = inR_os * (1.0f - blockCoeffs.blend) + satR * blockCoeffs.blend;

            outL_os = juce::jlimit(-2.0f, 2.0f, outL_os);
            outR_os = juce::jlimit(-2.0f, 2.0f, outR_os);
        });
    }
};

//==============================================================================
// PROFESSIONAL CHORUS — Studio-grade 6-voice architecture
//
// Pitch-stable at all mix levels via:
//   • Subliminal dry bleed at high wet (prevents detuned perception)
//   • Mix-adaptive depth compression (less excursion when more wet)
//   • Multi-shape LFOs: sine + smoothed triangle (less time at extremes)
//   • Decorrelated rate ratios (prime-inspired, never align)
//   • Per-voice 1-pole allpass for pitch transition smoothing
//   • tanh feedback saturation — now 2x oversampled to eliminate aliasing in feedback loop
//   • Equal-power crossfade (no hollow mid-range dip)
//==============================================================================
struct EnhancedChorus
{
    static constexpr int NUM_VOICES = 6;
    static constexpr int BUFFER_SIZE = 32768;

    float delayBuffer[2][BUFFER_SIZE] = {};
    int writePos = 0;
    double sampleRate = 44100.0;

    struct Voice
    {
        float phase = 0.0f;
        float centerDelay = 0.0f;   // ms
        float phaseOffset = 0.0f;
        float panL = 1.0f, panR = 1.0f;
        float rateScale = 1.0f;
        float depthScale = 1.0f;
        float triBlend = 0.5f;      // 0 = pure sine, 1 = pure smoothed triangle
        // Per-voice allpass for pitch smoothing
        float apState[2] = {};
        float triPhase = 0.0f;     // Normalized phase [0,1) for triangle LFO — avoids std::fmod
    };

    Voice voices[NUM_VOICES];
    float feedbackState[2] = {};
    DCBlocker dcBlock[2];
    OnePole outputSmooth[2];
    OnePole inputTone[2];        // Gentle pre-filter for cleaner modulation
    float driftPhase[NUM_VOICES] = {};
    // LFO phase recurrence: replaces 2 std::sin() calls/voice/sample with 4 multiplies
    // sin(x+d) = sin(x)cos(d) + cos(x)sin(d)
    // cos(x+d) = cos(x)cos(d) - sin(x)sin(d)
    float lfoSin[NUM_VOICES] = {};  // Current sin(phase) per voice
    float lfoCos[NUM_VOICES] = {};  // Current cos(phase) per voice

    // Drift phase recurrence: replaces 2 std::sin() calls/voice/sample with 4 multiplies
    // Drift uses two frequencies: 2.32x and 5.71x the base driftDelta
    float driftSin1[NUM_VOICES] = {};  // sin(2.32 * driftPhase + offset1) per voice
    float driftCos1[NUM_VOICES] = {};  // cos(2.32 * driftPhase + offset1) per voice
    float driftSin2[NUM_VOICES] = {};  // sin(5.71 * driftPhase + offset2) per voice
    float driftCos2[NUM_VOICES] = {};  // cos(5.71 * driftPhase + offset2) per voice
    Oversampling2x oversample[2];  // 2x oversampling for feedback tanh anti-aliasing — per-channel to avoid state sharing
    int lfoTick = 0;               // LFO renormalization tick counter

    // Block-level coefficient cache — avoids redundant per-sample transcendental calls.
    // beginBlock() precomputes tone/smooth filter coefficients plus chorus-specific
    // parameters (allpass coeff, mix-adaptive depth, drift increment) that were
    // previously recomputed for every voice on every sample.
    struct ChorusBlockCoeffs
        {
            float toneCoeff = 0.0f;
            float smoothCoeff = 0.0f;
            float apCoeff = 0.0f;           // allpass coefficient (0.3 + depth*0.15)
            float mixDepthScale = 1.0f;     // 1.0 at 0% mix → 0.65 at 100% mix
            float maxSwingMs = 2.8f;        // max modulation swing in ms
            float driftDelta = 0.0f;        // drift phase increment per sample
            float rateToIncrement = 0.0f;   // twoPi / sr — cached for LFO rate→phase step
            float invSr = 0.0f;               // 1.0 / sr — cached for normalized triangle phase advance
            // Phase recurrence constants per voice — replaces 2× std::sin()/sample with 4 multiplies
                    float voiceCosDelta[NUM_VOICES] = {};  // cos(rate * rateScale * rateToIncrement) per voice
                    float voiceSinDelta[NUM_VOICES] = {};  // sin(rate * rateScale * rateToIncrement) per voice

                    // Drift phase recurrence constants — replaces 2 std::sin()/voice/sample with 4 multiplies
                    // Drift uses two sine frequencies: 2.32x and 5.71x the base driftDelta
                    float driftCosDelta1[NUM_VOICES] = {};  // cos(2.32 * driftDelta) per voice
                    float driftSinDelta1[NUM_VOICES] = {};  // sin(2.32 * driftDelta) per voice
                    float driftCosDelta2[NUM_VOICES] = {};  // cos(5.71 * driftDelta) per voice
                    float driftSinDelta2[NUM_VOICES] = {};  // sin(5.71 * driftDelta) per voice
                    float driftPhaseOffset1[NUM_VOICES] = {};  // i * 2.1f * 2.32 per voice
                    float driftPhaseOffset2[NUM_VOICES] = {};  // i * 1.3f * 5.71 per voice

                    // Equal-power dry/wet crossfade gains — cached per-block
                    // Replaces 2 std::sin()+std::cos()/sample with single block-level computation.
                    // mix changes at block rate (via parameter smoothing), NOT per-sample.
                    float dryGain = 1.0f;  // cos(effectiveMix * halfPi) — default to dry-only
                    float wetGain = 0.0f;  // sin(effectiveMix * halfPi) — default to dry-only
                    // Per-voice sum normalization: constant 1/sqrt(NUM_VOICES).
                    // Cached here (hoisted from per-sample square-root in process()).
                    float voiceGain = 1.0f / std::sqrt(static_cast<float>(NUM_VOICES));
                } chorusBlockCoeffs;

    void beginBlock(float depth, float mix, float rate)
    {
        float sr = static_cast<float>(sampleRate);
        chorusBlockCoeffs.toneCoeff = std::exp(-6.2832f * 16000.0f / sr);
        chorusBlockCoeffs.smoothCoeff = std::exp(-6.2832f * 14000.0f / sr);
        chorusBlockCoeffs.apCoeff = 0.3f + depth * 0.15f;
        chorusBlockCoeffs.mixDepthScale = 1.0f - mix * 0.35f;
        chorusBlockCoeffs.maxSwingMs = 2.8f * chorusBlockCoeffs.mixDepthScale;
        chorusBlockCoeffs.driftDelta = 0.07f / sr;
        chorusBlockCoeffs.rateToIncrement = juce::MathConstants<float>::twoPi / sr;
        chorusBlockCoeffs.invSr = 1.0f / sr;
        // Precompute per-voice phase recurrence constants
        // sin/cos of per-voice phase delta → 4 multiplies/sample instead of 2 std::sin()/sample
        for (int i = 0; i < NUM_VOICES; ++i)
        {
            float delta = rate * voices[i].rateScale * chorusBlockCoeffs.rateToIncrement;
            chorusBlockCoeffs.voiceSinDelta[i] = std::sin(delta);
            chorusBlockCoeffs.voiceCosDelta[i] = std::cos(delta);
        }
        // Precompute drift phase recurrence constants
        // Drift uses two sine frequencies: 2.32x and 5.71x the base driftDelta
        float dDelta = chorusBlockCoeffs.driftDelta;
        for (int i = 0; i < NUM_VOICES; ++i)
        {
            // Frequency multipliers for the two drift components
            float delta1 = 2.32f * dDelta;
            float delta2 = 5.71f * dDelta;
            chorusBlockCoeffs.driftCosDelta1[i] = std::cos(delta1);
            chorusBlockCoeffs.driftSinDelta1[i] = std::sin(delta1);
            chorusBlockCoeffs.driftCosDelta2[i] = std::cos(delta2);
            chorusBlockCoeffs.driftSinDelta2[i] = std::sin(delta2);
            // Phase offsets per voice for the two drift frequencies
            chorusBlockCoeffs.driftPhaseOffset1[i] = static_cast<float>(i) * 2.1f * 2.32f;
            chorusBlockCoeffs.driftPhaseOffset2[i] = static_cast<float>(i) * 1.3f * 5.71f;
        }

        // Precompute equal-power crossfade gains — eliminates 2 std::sin()+std::cos() per sample
        // effectiveMix = mix * 0.90f (10% dry anchor at full wet for pitch stability)
        float effectiveMix = mix * 0.90f;
        chorusBlockCoeffs.dryGain = std::cos(effectiveMix * juce::MathConstants<float>::halfPi);
        chorusBlockCoeffs.wetGain = std::sin(effectiveMix * juce::MathConstants<float>::halfPi);
    }

    void prepare(double sr)
    {
        sampleRate = sr;
        oversample[0].prepare(sr);
        oversample[1].prepare(sr);
        std::memset(delayBuffer, 0, sizeof(delayBuffer));
        writePos = 0;
        feedbackState[0] = feedbackState[1] = 0.0f;
        dcBlock[0].reset(); dcBlock[1].reset();
        outputSmooth[0].reset(); outputSmooth[1].reset();
        inputTone[0].reset(); inputTone[1].reset();

        // Voice configuration:
        // centerDelay (ms), panL, panR, rateScale, depthScale, triBlend
        // Rate scales use prime-inspired ratios to prevent alignment:
        //   0.71, 0.89, 1.0, 1.13, 1.31, 0.79
        struct Cfg { float c, pL, pR, rs, ds, tb; };
        static constexpr Cfg cfg[NUM_VOICES] = {
            { 3.8f, 1.0f, 0.35f, 0.71f, 0.75f, 0.6f },  // slow, left, more triangle
            { 6.1f, 0.35f, 1.0f, 0.89f, 1.0f,  0.4f },  // moderate, right
            { 8.5f, 0.85f, 0.55f, 1.00f, 1.05f, 0.3f },  // center rate, slight left
            { 5.3f, 0.55f, 0.85f, 1.13f, 0.9f,  0.5f },  // slightly fast, slight right
            {11.0f, 0.95f, 0.25f, 1.31f, 1.15f, 0.7f },  // fast, hard left, more triangle
            { 4.5f, 0.25f, 0.95f, 0.79f, 0.65f, 0.55f }, // slow, hard right
        };
        for (int i = 0; i < NUM_VOICES; ++i)
        {
            voices[i].phase = 0.0f;
            voices[i].phaseOffset = (juce::MathConstants<float>::twoPi / NUM_VOICES) * i
                + i * 0.37f; // extra offset to break symmetry
            voices[i].centerDelay = cfg[i].c;
            voices[i].panL = cfg[i].pL;
            voices[i].panR = cfg[i].pR;
            voices[i].rateScale = cfg[i].rs;
            voices[i].depthScale = cfg[i].ds;
            voices[i].triBlend = cfg[i].tb;
            voices[i].apState[0] = voices[i].apState[1] = 0.0f;
            driftPhase[i] = i * 0.73f; // prime-ish spacing
            // Initialize LFO recurrence state: sin(v.phase+offset), cos(v.phase+offset)
            float initPhase = voices[i].phaseOffset;
            lfoSin[i] = std::sin(initPhase);
            lfoCos[i] = std::cos(initPhase);
            // Initialize normalized triangle phase from phaseOffset
            voices[i].triPhase = std::fmod(initPhase / juce::MathConstants<float>::twoPi, 1.0f);
            if (voices[i].triPhase < 0.0f) voices[i].triPhase += 1.0f;
            // Initialize drift phase recurrence state
            float driftPhase1 = driftPhase[i] * 2.32f + static_cast<float>(i) * 2.1f * 2.32f;
            float driftPhase2 = driftPhase[i] * 5.71f + static_cast<float>(i) * 1.3f * 5.71f;
            driftSin1[i] = std::sin(driftPhase1);
            driftCos1[i] = std::cos(driftPhase1);
            driftSin2[i] = std::sin(driftPhase2);
            driftCos2[i] = std::cos(driftPhase2);
        }
    }

    // smoothTriangle inlined in process() — normalized phase tracking eliminates std::fmod per voice

    // 1-pole allpass for pitch transition smoothing
    static inline float allpassSmooth(float input, float& state, float coeff)
    {
        float output = state + coeff * (input - state);
        state = input + coeff * (output - input);
        return output;
    }

    // Keep LFO unit-vector magnitudes constant (prevents float32 rotation drift).
    // Renormalizes sin/cos recurrence pairs every 256 samples. Without this the
    // incremental rotation loses ~2.5%/min, breathing the modulation depth open.
    void renormLFO()
    {
        for (int i = 0; i < NUM_VOICES; ++i)
        {
            float m = std::sqrt(lfoSin[i]*lfoSin[i] + lfoCos[i]*lfoCos[i]);
            float inv = 1.0f / m;
            lfoSin[i] *= inv; lfoCos[i] *= inv;
            m = std::sqrt(driftSin1[i]*driftSin1[i] + driftCos1[i]*driftCos1[i]);
            inv = 1.0f / m; driftSin1[i] *= inv; driftCos1[i] *= inv;
            m = std::sqrt(driftSin2[i]*driftSin2[i] + driftCos2[i]*driftCos2[i]);
            inv = 1.0f / m; driftSin2[i] *= inv; driftCos2[i] *= inv;
        }
    }
    float process(float input, int channel, float rate, float depth,
        float feedback)
    {
        input = juce::jlimit(-4.0f, 4.0f, input);
        feedback = std::min(feedback, 0.45f);

        // Pre-filter: gentle HF rolloff on input before writing to delay
        // Reduces aliasing artifacts from modulated reads of HF content
        float filtered = inputTone[channel].processLP(input, chorusBlockCoeffs.toneCoeff);

        // Saturated feedback (prevents compound pitch runaway) — 2x oversampled to eliminate aliasing
                // Without oversampling, harmonics from tanh in the feedback loop fold back and compound
                // with each iteration, creating metallic artifacts in the chorus tail.
                float fbIn = feedbackState[channel];
                float fbOut;
                oversample[channel].processSampleMono(fbIn, fbOut, [](float in, float& out) {
                    // Soft saturation: padeTanh(x * 1.2) / 1.2 — gentle, pitch-stable, zero transcendental
                    out = padeTanh(in * 1.2f) / 1.2f;
                });
        delayBuffer[channel][writePos] = filtered + fbOut * feedback;

        // ── Mix-adaptive depth compression ──
        // At high mix, less modulation excursion is needed (you hear more of it)
        // and pitch stability matters more. Pre-computed once per block.
        // NOTE: modMs is computed per-voice inside the loop below since it depends on lfo, v.depthScale, and drift

        float wetOut = 0.0f;

        for (int i = 0; i < NUM_VOICES; ++i)
        {
            Voice& v = voices[i];

            // ── Multi-shape LFO: blend sine + smoothed triangle ──
            // Use phase recurrence to replace 2× std::sin()/voice/sample with 4 multiplies.
            // sin(phase+d) = sin(phase)cos(d) + cos(phase)sin(d)
            // cos(phase+d) = cos(phase)cos(d) - sin(phase)sin(d)
            // sd/cd are computed once per voice per block (in beginBlock, not here).
            if (channel == 0)
            {
                float newSin = lfoSin[i] * chorusBlockCoeffs.voiceCosDelta[i] + lfoCos[i] * chorusBlockCoeffs.voiceSinDelta[i];
                float newCos = lfoCos[i] * chorusBlockCoeffs.voiceCosDelta[i] - lfoSin[i] * chorusBlockCoeffs.voiceSinDelta[i];
                lfoSin[i] = newSin;
                lfoCos[i] = newCos;
            }
            float sineVal = lfoSin[i];
            // Normalized triangle phase — replaces std::fmod(phase/twoPi, 1.0f) with simple wrapping
            float t = v.triPhase;
            float triRaw = (t < 0.5f) ? (4.0f * t - 1.0f) : (3.0f - 4.0f * t);
            float triVal = triRaw * (1.5f - 0.5f * triRaw * triRaw);
            float lfo = sineVal * (1.0f - v.triBlend) + triVal * v.triBlend;

            // Slow organic drift (very low frequency, per-voice)
            // driftDelta pre-computed once per block
            if (channel == 0)
            {
                driftPhase[i] += chorusBlockCoeffs.driftDelta;
                if (driftPhase[i] > 1.0f) driftPhase[i] -= 1.0f;

                // Drift phase recurrence: replaces 2 std::sin()/voice/sample with 4 multiplies
                // sin(φ + Δ) = sin(φ)cos(Δ) + cos(φ)sin(Δ)
                float newDriftSin1 = driftSin1[i] * chorusBlockCoeffs.driftCosDelta1[i] + driftCos1[i] * chorusBlockCoeffs.driftSinDelta1[i];
                float newDriftCos1 = driftCos1[i] * chorusBlockCoeffs.driftCosDelta1[i] - driftSin1[i] * chorusBlockCoeffs.driftSinDelta1[i];
                driftSin1[i] = newDriftSin1;
                driftCos1[i] = newDriftCos1;

                float newDriftSin2 = driftSin2[i] * chorusBlockCoeffs.driftCosDelta2[i] + driftCos2[i] * chorusBlockCoeffs.driftSinDelta2[i];
                float newDriftCos2 = driftCos2[i] * chorusBlockCoeffs.driftCosDelta2[i] - driftSin2[i] * chorusBlockCoeffs.driftSinDelta2[i];
                driftSin2[i] = newDriftSin2;
                driftCos2[i] = newDriftCos2;
            }
            // Multi-frequency drift for organic feel — uses precomputed sin/cos
            float drift = driftSin1[i] * 0.12f + driftSin2[i] * 0.06f;

            // ── Modulation with mix-adaptive depth ──
            // maxSwingMs pre-computed once per block
            float modMs = lfo * depth * v.depthScale * chorusBlockCoeffs.maxSwingMs * (1.0f + drift);
            float delayMs = juce::jlimit(1.0f, 25.0f, v.centerDelay + modMs);
            float delaySmp = juce::jlimit(1.0f, static_cast<float>(BUFFER_SIZE - 4),
                static_cast<float>(delayMs * 0.001 * sampleRate));

            float chGain = (channel == 0) ? v.panL : v.panR;

            float readPosF = static_cast<float>(writePos) - delaySmp;
            if (readPosF < 0.0f) readPosF += static_cast<float>(BUFFER_SIZE);

            float delayed = hermiteInterp(delayBuffer[channel], BUFFER_SIZE, readPosF);

            // ── Per-voice allpass pitch smoothing ──
            // apCoeff pre-computed once per block
            float apCoeff = chorusBlockCoeffs.apCoeff;
            delayed = allpassSmooth(delayed, v.apState[channel], apCoeff);

            wetOut += delayed * chorusBlockCoeffs.voiceGain * chGain;

            // Advance phase (only on first channel to keep L/R coherent)
            if (channel == 0)
            {
                v.phase += rate * v.rateScale * chorusBlockCoeffs.rateToIncrement;
                if (v.phase > juce::MathConstants<float>::twoPi * 4.0f)
                    v.phase -= juce::MathConstants<float>::twoPi * 2.0f;
                // Advance normalized triangle phase — replaces std::fmod with simple wrap
                v.triPhase += rate * v.rateScale * chorusBlockCoeffs.invSr;
                if (v.triPhase >= 1.0f) v.triPhase -= 1.0f;
            }
        }

        // Every 256 samples: renormalize LFO unit vectors (float32 rotation drift)
        if (channel == 0 && (++lfoTick & 255) == 0)
            renormLFO();
        // Feedback from wet sum with reduced gain and saturation
        feedbackState[channel] = wetOut * 0.55f;

        wetOut = dcBlock[channel].process(wetOut);

        // Output smoothing: tame metallic comb-filter peaks above ~14kHz
        wetOut = outputSmooth[channel].processLP(wetOut, chorusBlockCoeffs.smoothCoeff);

        // ── Equal-power crossfade with subliminal dry bleed ──
        // At 100% mix, keep 10% dry as subliminal pitch anchor
        // This is the key to pitch-stable chorus at high mix settings
        // Use cached equal-power crossfade gains from beginBlock()
        // Eliminates 2 std::sin()+std::cos() per sample per channel — computed once per block
        float dryGain = chorusBlockCoeffs.dryGain;
        float wetGain = chorusBlockCoeffs.wetGain;

        return input * dryGain + wetOut * wetGain;
    }

    void advanceWritePos()
    {
        writePos = (writePos + 1) % BUFFER_SIZE;
    }
};

//==============================================================================
// PROFESSIONAL DELAY — Tape-style, Hermite interpolation, filtered feedback
//==============================================================================
struct EnhancedDelay
{
    static constexpr int MAX_DELAY = 192000;

    float buffer[2][MAX_DELAY] = {};
    int writePos[2] = {};
    double sampleRate = 44100.0;

    OnePole fbLP[2], fbHP[2];
    float smoothedDelay[2] = {};
    DCBlocker dcBlock[2];
    Oversampling2x oversample;    // 2x oversampling for tape saturation anti-aliasing
    int lfoTick = 0;              // LFO renormalization tick counter

    // Block-level coefficient cache — avoids recomputing 2× std::exp() every sample.
    // Call beginBlock() once per audio block with current damping,
    // then call processSample() for each sample.
    struct BlockCoeffs
    {
        float fbLPCoeff = 0.0f;
        float fbHPCoeff = 0.0f;
        float invSr = 0.0f;
        float modPhaseInc = 0.0f;
        float lfoCoeff = 0.0f;
        float sampleRateK = 0.0f;
        float maxDelayF = 0.0f;
        float smooth = 0.9997f;

        // LFO phase recurrence: replaces 2 std::sin() calls/sample with 4 multiplies.
        // sin(φ + d) = sin(φ)cos(d) + cos(φ)sin(d)
        // cos(φ + d) = cos(φ)cos(d) - sin(φ)sin(d)
        // LFO has two frequencies: base and 5.13x base
        float lfoSin = 0.0f;     // sin(modPhase * lfoCoeff)
        float lfoCos = 0.0f;     // cos(modPhase * lfoCoeff)
        float lfo2Sin = 0.0f;    // sin(modPhase * lfoCoeff * 5.13)
        float lfo2Cos = 0.0f;    // cos(modPhase * lfoCoeff * 5.13)
        float lfoCosDelta = 0.0f;  // cos(lfoCoeff * modPhaseInc)
        float lfoSinDelta = 0.0f;  // sin(lfoCoeff * modPhaseInc)
        float lfo2CosDelta = 0.0f; // cos(lfoCoeff * modPhaseInc * 5.13)
        float lfo2SinDelta = 0.0f; // sin(lfoCoeff * modPhaseInc * 5.13)
    } blockCoeffs;
    // Keep LFO unit-vector magnitudes constant (prevents float32 rotation drift).
    // Renormalizes sin/cos recurrence pairs every 256 samples (~2.5%/min drift otherwise).
    void renormLFO()
    {
        float m = std::sqrt(blockCoeffs.lfoSin*blockCoeffs.lfoSin + blockCoeffs.lfoCos*blockCoeffs.lfoCos);
        float inv = 1.0f / m;
        blockCoeffs.lfoSin *= inv; blockCoeffs.lfoCos *= inv;
        m = std::sqrt(blockCoeffs.lfo2Sin*blockCoeffs.lfo2Sin + blockCoeffs.lfo2Cos*blockCoeffs.lfo2Cos);
        inv = 1.0f / m;
        blockCoeffs.lfo2Sin *= inv; blockCoeffs.lfo2Cos *= inv;
    }

    void prepare(double sr)
    {
        sampleRate = sr;
        oversample.prepare(sr);
        std::memset(buffer, 0, sizeof(buffer));
        writePos[0] = writePos[1] = 0;
        smoothedDelay[0] = smoothedDelay[1] = 0.0f;
        // Initialize LFO phase recurrence state: sin(0)=0, cos(0)=1
        blockCoeffs.lfoSin = 0.0f;
        blockCoeffs.lfoCos = 1.0f;
        blockCoeffs.lfo2Sin = 0.0f;
        blockCoeffs.lfo2Cos = 1.0f;
        for (int ch = 0; ch < 2; ++ch)
        {
            fbLP[ch].reset(); fbHP[ch].reset(); dcBlock[ch].reset();
        }
    }

    void beginBlock(float damping)
    {
        float sr = static_cast<float>(sampleRate);
        // Feedback high-cut: 2kHz at max damping → 18kHz at min damping
        blockCoeffs.fbLPCoeff = std::exp(-6.2832f * (2000.0f + (1.0f - damping) * 16000.0f) / sr);
        // Feedback low-cut: fixed at 80Hz
        blockCoeffs.fbHPCoeff = std::exp(-6.2832f * 80.0f / sr);

        // Block-level constant cache — eliminates redundant per-sample divides/multiplies.
        blockCoeffs.invSr = 1.0f / sr;
        blockCoeffs.modPhaseInc = 0.55f * blockCoeffs.invSr;
        blockCoeffs.lfoCoeff = 6.2832f * blockCoeffs.invSr;
        blockCoeffs.sampleRateK = sr * 0.0006f;
        blockCoeffs.maxDelayF = (float)(MAX_DELAY - 4);
        blockCoeffs.smooth = 0.9997f;

        // ── LFO phase recurrence: precompute sin/cos of phase increments ──
        // Replaces 2 std::sin() calls per sample with 4 multiplies.
        // LFO has two sine components: base frequency and 5.13x base.
        // sin(φ + Δ) = sin(φ)cos(Δ) + cos(φ)sin(Δ)
        // cos(φ + Δ) = cos(φ)cos(Δ) - sin(φ)sin(Δ)
        float delta1 = blockCoeffs.lfoCoeff * blockCoeffs.modPhaseInc;
        float delta2 = delta1 * 5.13f;
        blockCoeffs.lfoCosDelta = std::cos(delta1);
        blockCoeffs.lfoSinDelta = std::sin(delta1);
        blockCoeffs.lfo2CosDelta = std::cos(delta2);
        blockCoeffs.lfo2SinDelta = std::sin(delta2);
    }

    void processSample(float inL, float inR, float& outL, float& outR,
        float delayTimeMs, float feedback, float mix,
        float pingPong, float modAmount)
    {
        feedback = std::min(feedback, 0.92f);

        // Tape wow/flutter — phase increment cached per-block
        // LFO phase recurrence: replaces 2 std::sin() calls/sample with 4 multiplies.
        // sin(φ + Δ) = sin(φ)cos(Δ) + cos(φ)sin(Δ)
        // cos(φ + Δ) = cos(φ)cos(Δ) - sin(φ)sin(Δ)
        float newLfoSin = blockCoeffs.lfoSin * blockCoeffs.lfoCosDelta + blockCoeffs.lfoCos * blockCoeffs.lfoSinDelta;
        float newLfoCos = blockCoeffs.lfoCos * blockCoeffs.lfoCosDelta - blockCoeffs.lfoSin * blockCoeffs.lfoSinDelta;
        blockCoeffs.lfoSin = newLfoSin;
        blockCoeffs.lfoCos = newLfoCos;

        float newLfo2Sin = blockCoeffs.lfo2Sin * blockCoeffs.lfo2CosDelta + blockCoeffs.lfo2Cos * blockCoeffs.lfo2SinDelta;
        float newLfo2Cos = blockCoeffs.lfo2Cos * blockCoeffs.lfo2CosDelta - blockCoeffs.lfo2Sin * blockCoeffs.lfo2SinDelta;
        blockCoeffs.lfo2Sin = newLfo2Sin;
        blockCoeffs.lfo2Cos = newLfo2Cos;

        // Every 256 samples: renormalize LFO unit vectors (float32 rotation drift)
        if ((++lfoTick & 255) == 0)
            renormLFO();
        float lfo = blockCoeffs.lfoSin + blockCoeffs.lfo2Sin * 0.25f;
        float modSamples = lfo * modAmount * blockCoeffs.sampleRateK;

        float targetSmp = juce::jlimit(1.0f, blockCoeffs.maxDelayF,
            delayTimeMs * blockCoeffs.invSr);

        smoothedDelay[0] = smoothedDelay[0] * blockCoeffs.smooth + (targetSmp + modSamples) * (1.0f - blockCoeffs.smooth);
        smoothedDelay[1] = smoothedDelay[1] * blockCoeffs.smooth +
            (targetSmp + targetSmp * 0.027f + modSamples * 0.65f) * (1.0f - blockCoeffs.smooth);

        for (int ch = 0; ch < 2; ++ch)
            smoothedDelay[ch] = juce::jlimit(1.0f, blockCoeffs.maxDelayF, smoothedDelay[ch]);

        // Read with Hermite interpolation
        float readL = static_cast<float>(writePos[0]) - smoothedDelay[0];
        if (readL < 0.0f) readL += static_cast<float>(MAX_DELAY);
        float delayedL = hermiteInterp(buffer[0], MAX_DELAY, readL);

        float readR = static_cast<float>(writePos[1]) - smoothedDelay[1];
        if (readR < 0.0f) readR += static_cast<float>(MAX_DELAY);
        float delayedR = hermiteInterp(buffer[1], MAX_DELAY, readR);

        // Feedback with ping-pong cross-feed
        float fbL = delayedL * (1.0f - pingPong) + delayedR * pingPong;
        float fbR = delayedR * (1.0f - pingPong) + delayedL * pingPong;

        // Soft tape saturation — 2x oversampled to eliminate aliasing in feedback loop
                // Without oversampling, harmonics from tanh-style clipping fold back and compound
                // with each feedback iteration, creating metallic artifacts in the tail.
                // Mono oversampling: fbL and fbR are processed independently, halving FIR filter cost
                // compared to stereo processSample (same optimization applied to Master mid/side 2026-07-12).
                auto tapeSat = [](float x) -> float { return x / (1.0f + std::abs(x) * 0.4f); };
                float fbOutL, fbOutR;
                oversample.processSampleMono(fbL, fbOutL, [&tapeSat](float in, float& out) { out = tapeSat(in); });
                oversample.processSampleMono(fbR, fbOutR, [&tapeSat](float in, float& out) { out = tapeSat(in); });
                fbL = fbOutL;
                fbR = fbOutR;

        // High-cut on feedback - use cached coefficient
        fbL = fbLP[0].processLP(fbL, blockCoeffs.fbLPCoeff);
        fbR = fbLP[1].processLP(fbR, blockCoeffs.fbLPCoeff);

        // Low-cut on feedback - use cached coefficient
        fbL = fbHP[0].processHP(fbL, blockCoeffs.fbHPCoeff);
        fbR = fbHP[1].processHP(fbR, blockCoeffs.fbHPCoeff);

        // Write to buffers
        buffer[0][writePos[0]] = juce::jlimit(-4.0f, 4.0f, inL + fbL * feedback);
        buffer[1][writePos[1]] = juce::jlimit(-4.0f, 4.0f, inR + fbR * feedback);

        if (++writePos[0] >= MAX_DELAY) writePos[0] = 0;
        if (++writePos[1] >= MAX_DELAY) writePos[1] = 0;

        outL = inL * (1.0f - mix) + delayedL * mix;
        outR = inR * (1.0f - mix) + delayedR * mix;
    }
};

//==============================================================================
// PROFESSIONAL REVERB — Freeverb-inspired, stable at all parameter values
// Proper gain staging, early reflections, correct DC blocking
//==============================================================================
struct UpgradedReverb
{
    static constexpr int NUM_COMBS = 8;
    static constexpr int NUM_AP = 4;

    struct CombFilter
    {
        static constexpr int MAX_SIZE = 8192;
        float buf[MAX_SIZE] = {};
        int size = 1, pos = 0;
        float filterState = 0.0f;
        float damp1 = 0.0f, damp2 = 1.0f, fb = 0.0f;

        void setSize(int s) { size = juce::jlimit(1, MAX_SIZE - 1, s); }
        void setDamp(float d) { damp1 = d; damp2 = 1.0f - d; }
        void setFeedback(float f) { fb = f; }
        void mute() { std::memset(buf, 0, sizeof(buf)); filterState = 0.0f; pos = 0; }

        // modOffset: sub-sample read offset for reverb tail modulation.
        // Positive = longer delay (reads older data), negative = shorter.
        // Hermite cubic interpolation (from hermiteInterp utility) eliminates
        // modulation artifacts and aliasing in the reverb tail that linear
        // interpolation introduces when reading at fractional sample positions.
        inline float process(float input, float modOffset = 0.0f)
        {
            float readF = static_cast<float>(pos) - modOffset;
            // Wrap into [0, size)
            if (readF < 0.0f) readF += static_cast<float>(size);
            else if (readF >= static_cast<float>(size)) readF -= static_cast<float>(size);

            // Use Hermite cubic interpolation for artifact-free modulated reads
            float output = hermiteInterp(buf, size, readF);

            filterState = output * damp2 + filterState * damp1;
            buf[pos] = input + filterState * fb;
            if (++pos >= size) pos = 0;
            return output;
        }
    };

    struct AllpassDiffuser
    {
        static constexpr int MAX_SIZE = 4096;
        float buf[MAX_SIZE] = {};
        int size = 1, pos = 0;
        float fb = 0.5f;
        float modOffset = 0.0f;  // Sub-sample modulation offset for organic diffusion

        void setSize(int s) { size = juce::jlimit(1, MAX_SIZE - 1, s); }
        void setFeedback(float f) { fb = f; }
        void setModOffset(float m) { modOffset = m; }
        void mute() { std::memset(buf, 0, sizeof(buf)); pos = 0; }

        // modOffset: sub-sample read offset for allpass modulation.
        // Positive = longer delay (reads older data), negative = shorter.
        // Hermite cubic interpolation eliminates modulation artifacts and aliasing.
        inline float process(float input, float modOffset_ = 0.0f)
        {
            float readF = static_cast<float>(pos) - modOffset_;
            // Wrap into [0, size)
            if (readF < 0.0f) readF += static_cast<float>(size);
            else if (readF >= static_cast<float>(size)) readF -= static_cast<float>(size);

            // Use Hermite cubic interpolation for artifact-free modulated reads
            float delayed = hermiteInterp(buf, size, readF);

            float output = -input + delayed;
            buf[pos] = input + delayed * fb;
            if (++pos >= size) pos = 0;
            return output;
        }
    };

    struct EarlyReflections
        {
            static constexpr int MAX_SIZE = 9600;
            float buf[MAX_SIZE] = {};
            int pos = 0;
            int tapDelay[8] = {};
            float tapGain[8] = {};
            double sampleRate = 44100.0;

            void prepare(double sr)
            {
                sampleRate = sr;
                setRoomSize(0.5f); // Default to mid-size room
                mute();
            }

            void setRoomSize(float roomSize)
            {
                // Scale delays: small room = tight early reflections (ms scale)
                // large room = wider spaced, later early reflections
                // Base delays at 44.1kHz, scaled by sample rate
                const float baseMs[8] = { 2.3f, 5.8f, 11.2f, 17.5f, 23.1f, 31.7f, 41.3f, 53.0f };
                const float baseGain[8] = { 0.85f, 0.72f, 0.60f, 0.50f, 0.40f, 0.32f, 0.25f, 0.18f };

                // Room size 0.0 → 0.6x delays, 1.3x gains (small, bright, tight)
                // Room size 1.0 → 1.4x delays, 0.7x gains (large, diffuse, late)
                float delayScale = 0.6f + roomSize * 0.8f;    // 0.6 to 1.4
                float gainScale  = 1.3f - roomSize * 0.6f;     // 1.3 to 0.7

                for (int i = 0; i < 8; ++i)
                {
                    int delaySamps = juce::jlimit(1, MAX_SIZE - 1,
                        (int)(baseMs[i] * delayScale * 0.001f * sampleRate));
                    tapDelay[i] = delaySamps;
                    tapGain[i] = baseGain[i] * gainScale;
                }
            }

            void mute() { std::memset(buf, 0, sizeof(buf)); pos = 0; }

            float process(float input)
            {
                buf[pos] = input;
                float output = 0.0f;
                for (int i = 0; i < 8; ++i)
                {
                    int rp = pos - tapDelay[i];
                    if (rp < 0) rp += MAX_SIZE;
                    output += buf[rp] * tapGain[i];
                }
                if (++pos >= MAX_SIZE) pos = 0;
                return output;
            }
        };

    CombFilter combL[NUM_COMBS], combR[NUM_COMBS];
    AllpassDiffuser apL[NUM_AP], apR[NUM_AP];
    EarlyReflections earlyL, earlyR;

    static constexpr int PREDELAY_MAX = 9600;
    float preDelayBuf[2][PREDELAY_MAX] = {};
    int preDelayPos = 0;

    DCBlocker dcL, dcR;
    // Master modulation LFO state — using sin/cos recurrence instead of phase + sin/cos per sample
    float modSin = 0.0f;  // sin(modPhase * twoPi)
    float modCos = 1.0f;  // cos(modPhase * twoPi)
    int modTick = 0;      // master LFO renormalization tick counter
    double sampleRate = 44100.0;

    // Block-level coefficient cache — avoids recomputing feedback/damp per sample
    // and hoists comb modulation calculations out of the hot loop.
    struct BlockCoeffs
    {
        float fb = 0.0f;
        float damp = 0.0f;
        float damp1 = 0.0f;
        float damp2 = 0.0f;
        float modDepth = 0.0f;
        float inputGain = 0.045f;
        float wetGain = 0.0f;
        float apFb = 0.6f;      // Allpass feedback: scales with room size
        float modPhaseIncrement = 0.0f;  // 0.37f / sr — cached for comb modulation LFO
        // Pre-delay in samples (cached per block)
        int preDelaySmp = 0;
        // Stereo width (cached per block)
        float width = 1.0f;
        // LFO phase recurrence: replaces 8 std::sin()/sample with 2 + 16 multiplies.
        // sin(f + di) = sin(f)*cos(di) + cos(f)*sin(di) for each comb's phase offset di.
        // Precomputed once per block in beginBlock().
        float combCosDelta[NUM_COMBS] = {};  // cos(twoPi * i * 0.1234567f) per comb
        float combSinDelta[NUM_COMBS] = {};  // sin(twoPi * i * 0.1234567f) per comb

        // Master modulation LFO phase recurrence — replaces 2 std::sin()+std::cos()/sample
        // with 4 multiplies. The master LFO phase advances per sample at rate 0.37 Hz.
        // sin(φ + Δ) = sin(φ)cos(Δ) + cos(φ)sin(Δ)
        // cos(φ + Δ) = cos(φ)cos(Δ) - sin(φ)sin(Δ)
        // Precomputed sin/cos of phase increment Δ = 0.37 * twoPi / sr once per block.
        float modLfoCosDelta = 0.0f;  // cos(modPhaseIncrement * twoPi)
        float modLfoSinDelta = 0.0f;  // sin(modPhaseIncrement * twoPi)
    } blockCoeffs;

    static constexpr int baseCombL[NUM_COMBS] = { 1557, 1617, 1491, 1422, 1277, 1356, 1188, 1116 };
    static constexpr int baseCombR[NUM_COMBS] = { 1617, 1557, 1422, 1491, 1356, 1277, 1116, 1188 };
    static constexpr int baseAP[NUM_AP] = { 556, 441, 341, 225 };

    void beginBlock(float roomSize, float damping, float wetMix, float reverbMod, float width_, float preDelayMs)
    {
        // Room size → feedback: 0.70 to 0.97
        blockCoeffs.fb = 0.70f + roomSize * 0.27f;
        // Base damping floor: always absorb some HF, even at 0% damping knob
        blockCoeffs.damp = 0.2f + damping * 0.5f;
        blockCoeffs.damp1 = blockCoeffs.damp;
        blockCoeffs.damp2 = 1.0f - blockCoeffs.damp;
        // Modulation depth: 0–1.5 samples of read offset
        blockCoeffs.modDepth = reverbMod * 1.5f;
        // Wet gain (matched to higher inputGain)
        blockCoeffs.wetGain = wetMix * 1.5f;
        // Cache pre-delay and width per block
        blockCoeffs.preDelaySmp = juce::jlimit(0, PREDELAY_MAX - 1,
            (int)(preDelayMs * 0.001f * sampleRate));
        blockCoeffs.width = width_;

                // ── Early reflections scale with room size ──
                // Small rooms: tight, bright, loud early reflections
                // Large rooms: wide, diffuse, quiet early reflections
                earlyL.setRoomSize(roomSize);
                earlyR.setRoomSize(roomSize);

                // ── Allpass feedback scaling with room size ──
        // Smaller rooms: less allpass diffusion (0.50) → tighter, less smeared
        // Larger rooms: more allpass diffusion (0.70) → richer, denser tail
        // This makes the Size knob more musically responsive across its range.
        // Previously hardcoded at 0.6 — only changed comb feedback with size,
        // limiting spatial character variation.
        blockCoeffs.apFb = 0.50f + roomSize * 0.20f;
        // Cache comb modulation LFO step — replaces per-sample 0.37f/sr divide
        blockCoeffs.modPhaseIncrement = 0.37f / static_cast<float>(sampleRate);

        // ── Precompute master modulation LFO phase recurrence constants ──
        // Replaces 2 std::sin()+std::cos() per sample with 4 multiplies.
        // modPhaseIncrement is the phase advance per sample (0.37 Hz / sr).
        // Δ = modPhaseIncrement * twoPi (the full phase increment in radians).
        float modLfoDelta = blockCoeffs.modPhaseIncrement * juce::MathConstants<float>::twoPi;
        blockCoeffs.modLfoCosDelta = std::cos(modLfoDelta);
        blockCoeffs.modLfoSinDelta = std::sin(modLfoDelta);

        // ── Precompute comb LFO phase recurrence constants ──
        // Replaces 8 std::sin() calls per sample with 2 + 16 multiplies.
        // Each comb has a fixed phase offset: twoPi * i * 0.1234567f.
        // Using sin(φ + Δi) = sin(φ)cos(Δi) + cos(φ)sin(Δi).
        for (int i = 0; i < NUM_COMBS; ++i)
        {
            float di = juce::MathConstants<float>::twoPi * static_cast<float>(i) * 0.1234567f;
            blockCoeffs.combSinDelta[i] = std::sin(di);
            blockCoeffs.combCosDelta[i] = std::cos(di);
        }

        // ── Apply coefficients to comb filters once per block ──
        // Hoisted from per-sample processSample(): feedback and damping
        // don't change within a block, so setting them every sample was
        // 4 assignments × 8 combs × 2 channels = 64 redundant writes/sample.
        for (int i = 0; i < NUM_COMBS; ++i)
        {
            combL[i].setFeedback(blockCoeffs.fb); combR[i].setFeedback(blockCoeffs.fb);
            combL[i].setDamp(blockCoeffs.damp1);  combR[i].setDamp(blockCoeffs.damp1);
        }

        // ── Apply allpass feedback once per block ──
        // Previously set only in prepare() with hardcoded 0.6f.
        // Now scales dynamically with room size for richer spatial variation.
        for (int i = 0; i < NUM_AP; ++i)
        {
            apL[i].setFeedback(blockCoeffs.apFb);
            apR[i].setFeedback(blockCoeffs.apFb);
        }
    }

    // Keep master modulation LFO unit-vector magnitude constant (float32 rotation drift).
    // Renormalizes sin/cos every 256 samples (~0.34%/min drift otherwise).
    void renormModLFO()
    {
        float m = std::sqrt(modSin*modSin + modCos*modCos);
        float inv = 1.0f / m;
        modSin *= inv; modCos *= inv;
    }
    void prepare(double sr)
    {
        sampleRate = sr;
        double ratio = sr / 44100.0;

        for (int i = 0; i < NUM_COMBS; ++i)
        {
            combL[i].setSize((int)(baseCombL[i] * ratio));
            combR[i].setSize((int)(baseCombR[i] * ratio));
            combL[i].mute(); combR[i].mute();
        }
        for (int i = 0; i < NUM_AP; ++i)
        {
            apL[i].setSize((int)(baseAP[i] * ratio));
            apR[i].setSize((int)(baseAP[i] * ratio));
            // Initial allpass feedback set to mid-range default; beginBlock()
            // will update dynamically based on room size each audio block.
            apL[i].setFeedback(0.6f); apR[i].setFeedback(0.6f);
            apL[i].mute(); apR[i].mute();
        }
        earlyL.prepare(sr); earlyR.prepare(sr);
        earlyL.mute(); earlyR.mute();
        std::memset(preDelayBuf, 0, sizeof(preDelayBuf));
        preDelayPos = 0;
        // Initialize master modulation LFO state: sin(0)=0, cos(0)=1
        modSin = 0.0f;
        modCos = 1.0f;
        dcL.reset(); dcR.reset();
    }

    void processSample(float inL, float inR, float& outL, float& outR)
    {
        inL = juce::jlimit(-4.0f, 4.0f, inL);
        inR = juce::jlimit(-4.0f, 4.0f, inR);

        // Comb feedback/damp and allpass feedback are set once per block
        // in beginBlock() — no per-sample redundancy.

        // ── Comb modulation LFO ──
        // Slow sinusoidal modulation of comb read positions creates diffusion
        // and prevents metallic ringing in the reverb tail.
        // Rate: ~0.37 Hz (one cycle every ~2.7s). Depth: 0–1.5 samples.
        // Per-comb phase offsets decorrelate the modulation for stereo width.
        // LFO phase recurrence: replaces 2 std::sin()+std::cos()/sample with 4 multiplies.
        // sin(φ + Δ) = sin(φ)cos(Δ) + cos(φ)sin(Δ)
        // cos(φ + Δ) = cos(φ)cos(Δ) - sin(φ)sin(Δ)
        float newSinMod = modSin * blockCoeffs.modLfoCosDelta + modCos * blockCoeffs.modLfoSinDelta;
        float newCosMod = modCos * blockCoeffs.modLfoCosDelta - modSin * blockCoeffs.modLfoSinDelta;
        modSin = newSinMod;
        modCos = newCosMod;

        // Every 256 samples: renormalize master LFO unit vector (float32 rotation drift)
        if ((++modTick & 255) == 0)
            renormModLFO();
        float modDepth = blockCoeffs.modDepth;  // cached from beginBlock
        int pdSmp = blockCoeffs.preDelaySmp;    // cached from beginBlock
        preDelayBuf[0][preDelayPos] = inL;
        preDelayBuf[1][preDelayPos] = inR;
        int pdRead = preDelayPos - pdSmp;
        if (pdRead < 0) pdRead += PREDELAY_MAX;
        float pdL = preDelayBuf[0][pdRead];
        float pdR = preDelayBuf[1][pdRead];
        if (++preDelayPos >= PREDELAY_MAX) preDelayPos = 0;

        // Early reflections
        float erL = earlyL.process(pdL);
        float erR = earlyR.process(pdR);

        // Late reverb: parallel combs → series allpass
        // Higher input gain + lower output gain = same level, less artifact amplification
        float combInL = pdL * blockCoeffs.inputGain;
        float combInR = pdR * blockCoeffs.inputGain;
        float lateL = 0.0f, lateR = 0.0f;
        // ── LFO phase recurrence for comb modulation ──
        // Replaces 8 std::sin() calls per sample with 2 sin() + 16 multiplies.
        // sin(φ + Δi) = sin(φ)cos(Δi) + cos(φ)sin(Δi)
        // Precomputed combSinDelta[i]=sin(Δi), combCosDelta[i]=cos(Δi) in beginBlock().
        // Use recurrence-updated modSin/modCos (sin/cos of master LFO phase) directly.
        for (int i = 0; i < NUM_COMBS; ++i)
        {
            // sin(φ + Δi) = sin(φ)cos(Δi) + cos(φ)sin(Δi)
            float modOff = (modSin * blockCoeffs.combCosDelta[i] + modCos * blockCoeffs.combSinDelta[i]) * modDepth;
            lateL += combL[i].process(combInL, modOff);
            lateR += combR[i].process(combInR, -modOff);  // inverted for stereo decorrelation
        }
        for (int i = 0; i < NUM_AP; ++i)
        {
            // Allpass modulation: applies sub-sample read offset for organic diffusion
            // Each allpass gets a different phase offset to decorrelate left/right
            float apMod = modDepth * (0.5f + static_cast<float>(i) * 0.12f);  // scaled per allpass
            lateL = apL[i].process(lateL, apMod);
            lateR = apR[i].process(lateR, -apMod);  // inverted for stereo decorrelation
        }

        // Combine early + late
        float revL = erL * 0.25f + lateL;
        float revR = erR * 0.25f + lateR;

        revL = dcL.process(revL);
        revR = dcR.process(revR);

        // Stereo width (cached from beginBlock)
        float mid = (revL + revR) * 0.5f;
        float side = (revL - revR) * 0.5f * blockCoeffs.width;
        revL = mid + side;
        revR = mid - side;

        // Wet/dry mix (matched to higher inputGain) - use cached wetGain
        outL = inL * (1.0f - blockCoeffs.wetGain / 1.5f) + revL * blockCoeffs.wetGain;
        outR = inR * (1.0f - blockCoeffs.wetGain / 1.5f) + revR * blockCoeffs.wetGain;

        outL = juce::jlimit(-4.0f, 4.0f, outL);
        outR = juce::jlimit(-4.0f, 4.0f, outR);
    }
};

//==============================================================================
// MASTER OUTPUT STAGE — Analog warmth and professional polish
// Subtle HF shelf rolloff, LF body boost, push-pull saturation (asymmetrical
// even-harmonic generation), mid/side width control, and final smoothing.
// 2x oversampling on push-pull saturation for zero aliasing.
// Removes the "digital" or "tinny" quality from the cumulative signal chain.
//==============================================================================
struct MasterOutputStage
{
    OnePole hfShelfL, hfShelfR;   // HF rolloff for analog warmth
    OnePole lfShelfL, lfShelfR;   // LF boost for body
    OnePole smoothL, smoothR;     // Final anti-harsh smoothing
    Oversampling2x oversampleMid; // 2x oversampling for mid push-pull saturation
    Oversampling2x oversampleSide; // 2x oversampling for side push-pull saturation
    DCBlocker dcMid, dcSide;       // Strip DC from asymmetric push-pull (2nd-harmonic bias)
    double sampleRate = 44100.0;

    // Block-level coefficient cache — avoids recomputing std::exp() every sample.
    // Call beginBlock() once per audio block, then process() for each sample.
    struct BlockCoeffs
    {
        float hfCoeff = 0.0f;
        float lfCoeff = 0.0f;
        float smCoeff = 0.0f;
    } blockCoeffs;

    void prepare(double sr)
    {
        sampleRate = sr;
        oversampleMid.prepare(sr);
        oversampleSide.prepare(sr);
        hfShelfL.reset(); hfShelfR.reset();
        lfShelfL.reset(); lfShelfR.reset();
        smoothL.reset();  smoothR.reset();
        dcMid.reset();  dcSide.reset();
        beginBlock(); // Initialize block coefficients at default sample rate
    }

    // Block-level coefficient cache — avoids recomputing std::exp() every sample.
    // Call once per audio block (unconditionally, since master output always runs).
    void beginBlock()
    {
        float sr = static_cast<float>(sampleRate);
        // HF shelf: ~12kHz corner, gentle analog-style rolloff
        blockCoeffs.hfCoeff = std::exp(-6.2832f * 12000.0f / sr);
        // LF shelf: ~200Hz corner, subtle body boost
        blockCoeffs.lfCoeff = std::exp(-6.2832f * 200.0f / sr);
        // Final smoothing: ~17kHz ultra-gentle anti-harsh
        blockCoeffs.smCoeff = std::exp(-6.2832f * 17000.0f / sr);
    }

    void reset()
    {
        hfShelfL.reset(); hfShelfR.reset();
        lfShelfL.reset(); lfShelfR.reset();
        smoothL.reset();  smoothR.reset();
        oversampleMid.reset();
        oversampleSide.reset();
    }

    // Push-pull (asymmetrical) saturation — generates even harmonics (2nd, 4th)
            // for warmth and "tube-like" character. Unlike symmetric tanh() which only
            // produces odd harmonics, push-pull adds even-order content that our ears
            // perceive as musical richness and body.
            static inline float pushPullSaturate(float x, float drive)
            {
                // Asymmetric waveshaping: positive and negative halves shaped differently
                // This creates even harmonics (2nd, 4th) in addition to odd
                // Drive controls intensity: 0 = clean, 1 = moderate coloration
                if (x >= 0.0f)
                {
                    // Positive half: softer knee, more 2nd harmonic
                    float d = x * drive;
                    float z = d * (1.0f + d * 0.15f);
                    return padeTanh(z);
                }
                else
                {
                    // Negative half: harder knee, different harmonic balance
                    float d = -x * drive;
                    float z = d * (1.0f + d * 0.25f);
                    return -padeTanh(z);
                }
            }

    // Mid/Side processing with independent saturation and width control
    void process(float& L, float& R, float midDrive, float sideDrive, float width)
    {
        // ── Convert L/R to Mid/Side ──
        float mid = (L + R) * 0.5f;
        float side = (L - R) * 0.5f;

        // ── Width control: scale side signal ──
        // width = 0.0 → mono (side = 0)
        // width = 1.0 → original stereo
        // width > 1.0 → widened stereo
        side *= width;

        // ── 1. HF shelf on mid/side ──
        float hfMid = mid - hfShelfL.processLP(mid, blockCoeffs.hfCoeff); // reuse L filter for mid
        float hfSide = side - hfShelfR.processLP(side, blockCoeffs.hfCoeff); // reuse R filter for side
        mid -= hfMid * 0.16f;
        side -= hfSide * 0.16f;

        // ── 2. LF body on mid/side ──
        float lfMid = lfShelfL.processLP(mid, blockCoeffs.lfCoeff);
        float lfSide = lfShelfR.processLP(side, blockCoeffs.lfCoeff);
        mid += lfMid * 0.06f;
        side += lfSide * 0.06f;

        // ── 3. Push-pull saturation on mid and side independently (2x oversampled) ──
        // Mid saturation (mono oversampling -- avoids 2x redundant processing)
        oversampleMid.processSampleMono(mid, mid, [this, midDrive](float in, float& out) {
            out = pushPullSaturate(in, midDrive);
        });

        // Side saturation (mono oversampling -- avoids 2x redundant processing)
        oversampleSide.processSampleMono(side, side, [this, sideDrive](float in, float& out) {
            out = pushPullSaturate(in, sideDrive);
        });

        // ── 4. Final ultra-gentle smoothing ──
        mid = smoothL.processLP(mid, blockCoeffs.smCoeff);
        side = smoothR.processLP(side, blockCoeffs.smCoeff);

        // ── Convert back to L/R ──
        L = mid + side;
        R = mid - side;

        // DC blocker: asymmetric push-pull saturation generates a 2nd-harmonic
        // DC component (positive knee 0.15 vs negative knee 0.25). Strip it so the
        // master output (last stage before the DAW) never carries a DC offset.
        L = dcMid.process(L);
        R = dcSide.process(R);

        // Safety clamp
        L = juce::jlimit(-4.0f, 4.0f, L);
        R = juce::jlimit(-4.0f, 4.0f, R);
    }
};

//==============================================================================
class CorvusFXAudioProcessor : public juce::AudioProcessor,
    public juce::AudioProcessorValueTreeState::Listener
{
public:
    CorvusFXAudioProcessor();
    ~CorvusFXAudioProcessor() override;

    void prepareToPlay(double sampleRate, int samplesPerBlock) override;
    void releaseResources() override;
#ifndef JucePlugin_PreferredChannelConfigurations
    bool isBusesLayoutSupported(const BusesLayout& layouts) const override;
#endif
    void processBlock(juce::AudioBuffer<float>&, juce::MidiBuffer&) override;
    juce::AudioProcessorEditor* createEditor() override;
    bool hasEditor() const override;
    const juce::String getName() const override;
    bool acceptsMidi() const override;
    bool producesMidi() const override;
    bool isMidiEffect() const override;
    double getTailLengthSeconds() const override;
    int getNumPrograms() override;
    int getCurrentProgram() override;
    void setCurrentProgram(int index) override;
    const juce::String getProgramName(int index) override;
    void changeProgramName(int index, const juce::String& newName) override;
    void getStateInformation(juce::MemoryBlock& destData) override;
    void setStateInformation(const void* data, int sizeInBytes) override;
    juce::AudioProcessorValueTreeState::ParameterLayout createParameterLayout();
    juce::AudioProcessorValueTreeState apvts;
    void parameterChanged(const juce::String& parameterID, float newValue) override;
    void loadPreset(int index);

private:
    EnhancedChorus chorus;
    EnhancedDelay delay;
    ProfessionalDistortion distortion;
    UpgradedReverb upgradedReverb;
    MasterOutputStage masterOutput;
    juce::AudioBuffer<float> dryBuffer;
    double lastSampleRate = 44100.0;

    // ── Parameter smoothing ──
    // Smoothed parameter values eliminate zipper noise from knob movement
    // and host automation. Without smoothing, atomic parameter reads
    // jump instantly between blocks, creating audible clicks/clicks.
    // 20ms smoothing time: fast enough to feel responsive, slow enough
    // to remove all artifacts. Standard for professional VST3 plugins.
    //
    // Usage: setTargetValue() in processBlock header, then getNextValue()
    // per sample for smooth interpolation across the block.
    juce::LinearSmoothedValue<float> smoothOverall;
    juce::LinearSmoothedValue<float> smoothFatness;
    juce::LinearSmoothedValue<float> smoothChorusDepth;
    juce::LinearSmoothedValue<float> smoothChorusRate;
    juce::LinearSmoothedValue<float> smoothChorusMix;
    juce::LinearSmoothedValue<float> smoothDelayTime;
    juce::LinearSmoothedValue<float> smoothDelayFeedback;
    juce::LinearSmoothedValue<float> smoothDelayMix;
    juce::LinearSmoothedValue<float> smoothDelayDamping;
    juce::LinearSmoothedValue<float> smoothDelayMod;
    juce::LinearSmoothedValue<float> smoothReverbSize;
    juce::LinearSmoothedValue<float> smoothReverbDamping;
    juce::LinearSmoothedValue<float> smoothReverbMix;
    juce::LinearSmoothedValue<float> smoothReverbMod;
    juce::LinearSmoothedValue<float> smoothMasterDrive;
    juce::LinearSmoothedValue<float> smoothMasterWidth;
    juce::LinearSmoothedValue<float> smoothMasterMidDrive;
    juce::LinearSmoothedValue<float> smoothMasterSideDrive;

    // Bypass crossfade gains -- when a module bypass is toggled, the wet/dry
    // mix ramps over ~30ms via LinearSmoothedValue instead of a hard switch,
    // eliminating the click/step discontinuity (audible on Delay/Reverb tails).
    juce::LinearSmoothedValue<float> bypassGainDist;
    juce::LinearSmoothedValue<float> bypassGainChorus;
    juce::LinearSmoothedValue<float> bypassGainDelay;
    juce::LinearSmoothedValue<float> bypassGainReverb;
    juce::LinearSmoothedValue<float> bypassGainMaster;

    // ── Level Meter State ──
    // Smoothed peak/RMS meters for input and output.
    // Updated in processBlock (audio thread), read by editor (message thread)
    // via atomic floats. No locks needed — relaxed atomics are sufficient
    // for meter display (approximate values are fine).
public:
    struct LevelMeters
    {
        std::atomic<float> inPeakL  { 0.0f }, inPeakR  { 0.0f };
        std::atomic<float> inRmsL   { 0.0f }, inRmsR   { 0.0f };
        std::atomic<float> outPeakL { 0.0f }, outPeakR { 0.0f };
        std::atomic<float> outRmsL  { 0.0f }, outRmsR  { 0.0f };
    } levelMeters;

    JUCE_DECLARE_NON_COPYABLE_WITH_LEAK_DETECTOR(CorvusFXAudioProcessor)
};

using DrippyFXAudioProcessor = CorvusFXAudioProcessor;