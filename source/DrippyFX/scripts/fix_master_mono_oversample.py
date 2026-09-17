# ALREADY APPLIED — DO NOT RERUN. One-shot Windows migration fix; kept as a record.
"""Switch MasterOutputStage mid/side oversampling from stereo processSample to mono processSampleMono.
Each call currently passes the same mono value for both L and R, running pushPullSaturate twice
per sample. processSampleMono runs the FIR filter once (vs 2x for stereo) and calls DSP once.
~50% reduction in master oversampling cost. No audio change.
"""
import sys

path = r'C:\Projects\Corvus VST\source\DrippyFX\PluginProcessor.h'
with open(path, 'rb') as f:
    text = f.read()

CRLF = b'\r\n'

# Verify starting state
assert b'oversampleMid.processSample(mid, mid, mid, mid,' in text, "Mid oversample call not found"
assert b'oversampleSide.processSample(side, side, side, side,' in text, "Side oversample call not found"

# Replace mid oversampling: stereo processSample -> mono processSampleMono
old_mid = (
    b'        // Mid saturation' + CRLF +
    b'        oversampleMid.processSample(mid, mid, mid, mid, [this, midDrive](float inL, float inR, float& outL, float& outR) {' + CRLF +
    b'            outL = pushPullSaturate(inL, midDrive);' + CRLF +
    b'            outR = pushPullSaturate(inR, midDrive); // same value for mono mid' + CRLF +
    b'        });'
)
new_mid = (
    b'        // Mid saturation (mono oversampling -- avoids 2x redundant processing)' + CRLF +
    b'        oversampleMid.processSampleMono(mid, mid, [this, midDrive](float in, float& out) {' + CRLF +
    b'            out = pushPullSaturate(in, midDrive);' + CRLF +
    b'        });'
)
text = text.replace(old_mid, new_mid)
assert text.count(old_mid) == 0, "Failed to replace mid oversampling call"

# Replace side oversampling: stereo processSample -> mono processSampleMono
old_side = (
    b'        // Side saturation' + CRLF +
    b'        oversampleSide.processSample(side, side, side, side, [this, sideDrive](float inL, float inR, float& outL, float& outR) {' + CRLF +
    b'            outL = pushPullSaturate(inL, sideDrive);' + CRLF +
    b'            outR = pushPullSaturate(inR, sideDrive);' + CRLF +
    b'        });'
)
new_side = (
    b'        // Side saturation (mono oversampling -- avoids 2x redundant processing)' + CRLF +
    b'        oversampleSide.processSampleMono(side, side, [this, sideDrive](float in, float& out) {' + CRLF +
    b'            out = pushPullSaturate(in, sideDrive);' + CRLF +
    b'        });'
)
text = text.replace(old_side, new_side)
assert text.count(old_side) == 0, "Failed to replace side oversampling call"

with open(path, 'wb') as f:
    f.write(text)

# Verify
with open(path, 'rb') as f:
    verify = f.read()
assert b'oversampleMid.processSampleMono(mid, mid,' in verify, "Mid mono not in output"
assert b'oversampleSide.processSampleMono(side, side,' in verify, "Side mono not in output"
assert b'oversampleMid.processSample(mid, mid, mid, mid' not in verify, "Old mid call still present"
assert b'oversampleSide.processSample(side, side, side, side' not in verify, "Old side call still present"

print("OK: Master Output Stage oversampling switched from stereo to mono")
print(f"File size: {len(verify)} bytes")