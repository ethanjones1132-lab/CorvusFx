# ALREADY APPLIED — DO NOT RERUN. One-shot Windows migration fix; kept as a record.
"""Update ROADMAP.md — Phase 3 per-module bypass entry to mark UI done."""
import sys

path = r'C:\Projects\Corvus VST\docs\ROADMAP.md'
with open(path, 'rb') as f:
    text = f.read().decode('utf-8')

# Update last-updated line
text = text.replace(
    '**Last updated:** 2026-07-10 (morning pass — Master Output smoothing fix for master_drive/master_width/master_mid_drive)',
    '**Last updated:** 2026-07-11 (overnight pass — bypass UI buttons for all 5 modules)',
    1
)

# Update Phase 3 per-module bypass: append UI done
old_bypass = '| Per-module bypass with crossfade | Click-free enable/disable | S | ✅ Done (`5dd1e7c`) |'
new_bypass = '| Per-module bypass with crossfade | Click-free enable/disable | S | ✅ Done (`5dd1e7c` — DSP bypass); ✅ Done (`7a8f1a0` — UI buttons) |'
text = text.replace(old_bypass, new_bypass, 1)

# Add UI buttons item to Phase 2
old_param_audit = '| ~~Parameter smoothing audit (Overall knob)~~ | No zipper noise, musical taper on all knobs | ~~S~~ ✅ Done (`0b1c4d8`) |'
new_param_audit = '| ~~Parameter smoothing audit (Overall knob)~~ | No zipper noise, musical taper on all knobs | ~~S~~ ✅ Done (`0b1c4d8`) |\n| ~~Bypass UI buttons (Chorus/Delay/Reverb/Master)~~ | Color-coded ToggleButtons for remaining 4 modules | ~~S~~ ✅ Done (`7a8f1a0`) |'
text = text.replace(old_param_audit, new_param_audit, 1)

# Also update the Phase 1 remaining: mark SIMD done
old_simd = '- [x] SIMD (SSE) optimization for Oversampling2x FIR filter — 4x throughput on hottest path (all 4 saturation stages) (`f7ecad0`)'
new_simd = '- [x] SIMD (SSE) optimization for Oversampling2x FIR filter — 4x throughput on hottest path (all 4 saturation stages) (`f7ecad0`)\n- [x] Per-module bypass UI buttons for Chorus, Delay, Reverb, Master (`7a8f1a0`)'
text = text.replace(old_simd, new_simd, 1)

with open(path, 'wb') as f:
    f.write(text.encode('utf-8'))

print(f"Updated {path}")
for s in ['2026-07-11', '7a8f1a0', 'color-coded']:
    assert s in text, f"MISSING: {s}"
    print(f"  OK: '{s}' present")
print("All verifications passed!")