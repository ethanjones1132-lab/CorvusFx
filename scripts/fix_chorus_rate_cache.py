"""Hoist Chorus LFO rate-to-increment division from per-sample loop to beginBlock().

Eliminates 6 redundant float-divide operations per sample (1 per voice × 6 voices).
The computation `rate * v.rateScale * twoPi / sampleRate` is constant across
the audio block, so we precompute `rateToIncrement = twoPi / sampleRate` once
in beginBlock() and multiply per-voice inside the hot loop.

Safe: this is purely a performance improvement. The arithmetic is identical.
"""
import sys

SRC = "C:/Users/ethan/Downloads/DrippyFX_v1.0.0_Complete/DrippyFX/PluginProcessor.h"

with open(SRC, 'rb') as f:
    content = f.read().decode('utf-8')

# ── Change 1: add rateToIncrement to ChorusBlockCoeffs ──
old1 = "        float driftDelta = 0.0f;        // drift phase increment per sample\n    } chorusBlockCoeffs;"
new1 = "        float driftDelta = 0.0f;        // drift phase increment per sample\n        float rateToIncrement = 0.0f;   // twoPi / sr — cached for LFO rate→phase step (avoids 6 divides/sample)\n    } chorusBlockCoeffs;"
if old1 not in content:
    print("ERROR: old1 not found — struct declaration changed since last backup")
    sys.exit(1)
content = content.replace(old1, new1)

# ── Change 2: compute rateToIncrement in beginBlock() ──
old2 = "        chorusBlockCoeffs.driftDelta = 0.07f / sr;\n    }"
new2 = "        chorusBlockCoeffs.driftDelta = 0.07f / sr;\n        // Pre-compute twoPi/sr once per block — avoids 6 redundant divides/sample\n        chorusBlockCoeffs.rateToIncrement = juce::MathConstants<float>::twoPi / sr;\n    }"
if old2 not in content:
    print("ERROR: old2 not found — beginBlock() changed")
    sys.exit(1)
content = content.replace(old2, new2)

# ── Change 3: use rateToIncrement in per-sample loop (replacing the division) ──
old3 = "                v.phase += (rate * v.rateScale * juce::MathConstants<float>::twoPi)\n                    / static_cast<float>(sampleRate);"
new3 = "                v.phase += rate * v.rateScale * chorusBlockCoeffs.rateToIncrement;"
if old3 not in content:
    print("ERROR: old3 not found — per-sample LFO line changed")
    sys.exit(1)
content = content.replace(old3, new3)

# Write back as binary to avoid CRLF corruption (Windows python newline='' pitfall)
with open(SRC, 'wb') as f:
    f.write(content.encode('utf-8'))

print("OK: Chorus rate-to-increment caching applied to PluginProcessor.h")
print(f"  - Added rateToIncrement to ChorusBlockCoeffs")
print(f"  - Precomputed twoPi/sr in beginBlock()")
print(f"  - Replaced 6 per-sample divides with cached multiplies")