# Audio-thread contract (Corvus FX)

## 1. Current behavior (verified)

- MIDI CC is applied inside `processBlock`
  (`source/DrippyFX/PluginProcessor.cpp:700-779`, gated on
  `!midiMessages.isEmpty()` at line 700). The apply path calls
  `setValueNotifyingHost` at line 774.
- A CC target may be the `"preset"` parameter: `midiMap` stores a
  parameter ID string (`source/DrippyFX/PluginProcessor.h:138`), and the
  apply path resolves any ID via `apvts.getParameter(entry.second)`
  (`source/DrippyFX/PluginProcessor.cpp:772-774`). When the ID is
  `"preset"`, `setValueNotifyingHost` on that parameter fires
  `parameterChanged` (`source/DrippyFX/PluginProcessor.cpp:33-54`), which
  calls `loadPreset` (`source/DrippyFX/PluginProcessor.cpp:56-169`).
  `loadPreset` opens an undo transaction at line 63 and calls
  `setValueNotifyingHost` for 23 parameters at line 156 (via the `set`
  lambda at lines 154-157). Those calls notify the host.
- The same notification path is host-triggerable through
  `setCurrentProgram`, which calls `setValueNotifyingHost` on `"preset"`
  at `source/DrippyFX/PluginProcessor.cpp:324`.
- No code in the tree drains these notifications on a headless or offline
  render: `source/DrippyFX/PluginProcessor.cpp` contains no timer, queue,
  drain, or flush for host notifications (search of that file found none);
  the editor timer callback at
  `source/DrippyFX/PluginEditor.cpp:390-405` handles level meters only.
- `midiMap[cc]` insertion allocates a map node on the audio thread during
  learn: `midiMap[cc] = midiLearnParamID;` at
  `source/DrippyFX/PluginProcessor.cpp:738`, executed inside the
  `midiMapLock` scope at lines 716-754 while `midiLearnActive` (line 717).
  (The snapshot refill at lines 743-753 does not allocate because
  `mapSnapshot` capacity is reserved off the audio thread at
  `source/DrippyFX/PluginProcessor.cpp:25` and
  `source/DrippyFX/PluginProcessor.cpp:494`; the learn insertion at line 738
  is not covered by that reservation.)
- Restore can hold `midiMapLock` across XML and `juce::String` work while
  the audio thread also takes that lock:
  `getStateInformation` holds it at
  `source/DrippyFX/PluginProcessor.cpp:1031-1038` across
  `createNewChildElement`/`setAttribute` (including `paramID` strings);
  `setStateInformation` holds it at lines 1125-1127 for `midiMap.clear()`
  and at lines 1132-1140 across `getIntAttribute`/`getStringAttribute`,
  `apvts.getParameter`, and `midiMap[cc] = paramID`. The audio thread takes
  the same lock at `source/DrippyFX/PluginProcessor.cpp:716`.
  `getMidiMappings` (`source/DrippyFX/PluginProcessor.h:80-86`) takes that
  lock too; its only in-tree caller is the state test at
  `source/DrippyFX/tests/CorvusFxStateTests.cpp:317`, not the audio thread.
- Block snapshots: nine block-level caches are read at
  `source/DrippyFX/PluginProcessor.cpp:784-792`
  (fatness 784, chorusDepth 785, chorusRate 786, chorusMix 787,
  delayDamping 788, reverbSize 789, reverbDamping 790, reverbMix 791,
  sReverbMod 792). Only four advance per sample via `getNextValue`:
  fatness at line 844, chorusDepth at 845, chorusRate at 846, and
  reverbMix at 851. The other five (chorusMix, delayDamping, reverbSize,
  reverbDamping, reverbMod) do not advance per sample (no corresponding
  `getNextValue` in lines 844-858). Reverb early-tap mute keys off room
  size, not mix: `source/DrippyFX/dsp/CorvusEffects.h:1289-1294` compares
  `roomSize` to `lastRoomSize` and mutes `earlyL`/`earlyR` only on change.
- Parameter reads for a block are interleaved with the MIDI work: raw
  parameter reads and `setTargetValue` calls occur at
  `source/DrippyFX/PluginProcessor.cpp:613-689`, before the MIDI block at
  lines 697-779; the block-level snapshot reads at lines 784-792 occur
  after that MIDI block, one `getTargetValue()` call per parameter. A
  preset recall writes parameters separately: `loadPreset` calls the `set`
  lambda (lines 154-157) once per parameter, each invoking
  `setValueNotifyingHost` at line 156.

## 2. Proposed requirements (not implemented)

- Proposed: no host notification on the audio thread.
- Proposed: no lock on the audio thread.
- Proposed: no allocation or reclamation on the audio thread.
- Proposed: at most one notification per parameter per message-thread tick.
- Proposed: `"preset"` rejected as a CC target.
- Proposed: one coherent parameter generation for preset recall.

## 3. Owner choice (unresolved)

Unresolved: choose between accepted-loss coalescing of notifications and a
lossless flush that the host guarantees, including headless and offline
renders. Neither side is chosen, implemented, or authorized.