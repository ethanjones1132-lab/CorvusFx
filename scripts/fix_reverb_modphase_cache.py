"""Fix: add modPhaseIncrement to Reverb BlockCoeffs, hoisting last per-sample divide.

Two remaining optimizations identified:
1. EnhancedChorus LFO rate caching (done in previous run, `d48eaf0`)
2. UpgradedReverb modPhase increment (this script) — 0.37f / sampleRate computed per-sample
"""
import sys

SRC = "C:/Users/ethan/Downloads/DrippyFX_v1.0.0_Complete/DrippyFX/PluginProcessor.h"

with open(SRC, 'rb') as f:
    content = f.read().decode('utf-8')

# ── Change A: add modPhaseIncrement to BlockCoeffs ──
oldA = "        float apFb = 0.6f;      // Allpass feedback: scales with room size\n    } blockCoeffs;"
newA = "        float apFb = 0.6f;      // Allpass feedback: scales with room size\n        float modPhaseIncrement = 0.0f;  // 0.37f / sr — cached for comb modulation LFO\n    } blockCoeffs;"
if oldA not in content:
    print("ERROR: Change A not found (struct declaration)")
    sys.exit(1)
content = content.replace(oldA, newA)

# ── Change B: compute modPhaseIncrement in beginBlock() ──
oldB = "        blockCoeffs.apFb = 0.50f + roomSize * 0.20f;\n\n        // ── Apply coefficients to comb filters once per block"
newB = "        blockCoeffs.apFb = 0.50f + roomSize * 0.20f;\n        // Cache comb modulation LFO step — replaces per-sample 0.37f/sr divide\n        blockCoeffs.modPhaseIncrement = 0.37f / static_cast<float>(sampleRate);\n\n        // ── Apply coefficients to comb filters once per block"
if oldB not in content:
    print("ERROR: Change B not found (beginBlock assignment)")
    sys.exit(1)
content = content.replace(oldB, newB)

# ── Change C: use modPhaseIncrement in processSample() ──
oldC = "        modPhase += 0.37f / static_cast<float>(sampleRate);"
newC = "        modPhase += blockCoeffs.modPhaseIncrement;"
if oldC not in content:
    print("ERROR: Change C not found (processSample divide)")
    sys.exit(1)
content = content.replace(oldC, newC)

with open(SRC, 'wb') as f:
    f.write(content.encode('utf-8'))

print("OK: Reverb modPhase increment cached in beginBlock()")
print(f"  - Added modPhaseIncrement to Reverb BlockCoeffs")
print(f"  - Computed once in beginBlock(), used in processSample()")
print(f"  - Removed last per-sample /sr in the hot path")