"""Update PRIORITIES.md with July 11 overnight pass improvements."""
import sys

path = r'C:\Projects\Corvus VST\docs\PRIORITIES.md'
with open(path, 'rb') as f:
    text = f.read().decode('utf-8')

# 1. Update "Last updated" line
text = text.replace(
    'Last updated: 2026-07-10 (afternoon pass — click-free bypass for all 5 modules)',
    'Last updated: 2026-07-11 (overnight pass — bypass UI buttons for all 5 modules + reverb beginBlock var fix)',
    1
)

# 2. Update quick status line
text = text.replace(
    '**DSP quality — all 4 saturation stages oversampled, all parameters smoothed, hot-paths fully block-cached, 19 parameters. Entire plugin has zero per-sample transcendental calls. All 5 modules (Distortion, Chorus, Delay, Reverb, Master) now support click-free bypass. API surface cleaned: dead per-sample parameters removed from Chorus (mix) and Delay (damping); Reverb/Delay per-sample signatures simplified. 24 categorized presets, professional dB-scale metering, proportional layout scaling.**',
    '**DSP quality — all 4 saturation stages oversampled, all parameters smoothed, hot-paths fully block-cached, 19 parameters. Entire plugin has zero per-sample transcendental calls. All 5 modules (Distortion, Chorus, Delay, Reverb, Master) now support click-free bypass with color-coded UI buttons. Parameter layout reorganized: bypass params sit next to modules. Bugfix: reverbMod→sReverbMod in beginBlock. 24 categorized presets, professional dB-scale metering, proportional layout scaling.**',
    1
)

# 3. Add new entry for bypass UI
insert_marker = '|| **P2** | Click-free bypass for all 5 modules (Distortion, Chorus, Delay, Reverb, Master) | Professional workflow: A/B comparison, CPU savings, automation | ✅ Done (2026-07-10, `5dd1e7c` — 4 new params: chorus_bypass, delay_bypass, reverb_bypass, master_bypass; distortion_bypass already existed) |'
new_entry = '\n|| **P2** | Bypass UI buttons for all 5 modules | Previously only Distortion had a BYPASS button — other 4 modules needed UI | ✅ Done (2026-07-11, `7a8f1a0` — color-coded ToggleButtons with ButtonAttachments for Chorus/Delay/Reverb/Master) |'
text = text.replace(insert_marker, insert_marker + new_entry, 1)

# 4. Add improvement log entries (after the last existing entry in the log section)
log_marker = '||| 2026-07-10 | `5dd1e7c` | Modules | **Add click-free bypass for Chorus, Delay, Reverb, Master**'
new_log_entries = '''||| 2026-07-11 | `062281e` | Presets | **Reorganize bypass params in parameter layout** — moved chorus_bypass/delay_bypass/reverb_bypass/master_bypass from grouped-at-end to module-local positions in createParameterLayout(). Expanded preset P struct with 4 new bypass fields; all 24 presets updated with bypass=0. 62-line coherent WIP committed. |
||| 2026-07-11 | `7a8f1a0` | UI/PluginEditor | **Add bypass buttons for Chorus, Delay, Reverb, and Master** — color-coded ToggleButtons (blue=chorus, green=delay, purple=reverb, magenta=master) with ButtonAttachments wired to the VTS. Button placement below each module's knobs in 2×2 grid, master bypass next to Master Drive row. Tooltips: "Bypass the <module> module entirely — click-free crossfade". 58-line addition to header+cpp. |
||| 2026-07-11 | `a4e5bda` | UpgradedReverb | **Fix reverbMod → sReverbMod in beginBlock call** — line 366 used undeclared `reverbMod` instead of `sReverbMod` (C2065). Bug silently present in git SoT since 5dd1e7c but Downloads tree had different declaration state during prior builds. Single-line fix, no binary change. |
||| 2026-07-10 | `5dd1e7c` | Modules | **Add click-free bypass for Chorus, Delay, Reverb, Master**'''
text = text.replace(log_marker, new_log_entries, 1)

with open(path, 'wb') as f:
    f.write(text.encode('utf-8'))

print(f"Updated {path}")
print(f"Lines: {text.count(chr(10))}")

# Verify key strings
for s in ['2026-07-11', '7a8f1a0', 'a4e5bda', '062281e', 'color-coded', 'reverbMod → sReverbMod']:
    if s in text:
        print(f"  OK: '{s}' present")
    else:
        print(f"  FAIL: '{s}' NOT FOUND")
        sys.exit(1)
print("All verifications passed!")