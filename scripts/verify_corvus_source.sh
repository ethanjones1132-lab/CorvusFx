#!/usr/bin/env bash
# Portable source checks; does not require the old local sprint driver.
set -euo pipefail
# Force UTF-8 mode for every checker process. Without this a stock Windows
# console (cp1252 stdout, e.g. when output is redirected to a pipe or file)
# makes checkers that print non-ASCII diagnostics — such as the
# "distortion→chorus→delay→reverb→master" label in
# check_baseline_fixture_test.py — die with UnicodeEncodeError. The variable is
# exported so nested python interpreters the checkers spawn inherit it too.
export PYTHONUTF8=1
CORVUS_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
# CV-029: no host-facing work on the audio thread (scripts/check_cv029_no_host_notify.py).
# The loop below auto-registers every scripts/check_*.py, including that one;
# this explicit assertion keeps the registration from being lost silently if the
# glob pattern is ever changed.
test -f "$CORVUS_ROOT/scripts/check_cv029_no_host_notify.py"
# CV-041: "preset" stays non-automatable
# (scripts/check_cv041_preset_automation.py). Same auto-registration applies;
# this explicit assertion keeps it from being lost silently too.
test -f "$CORVUS_ROOT/scripts/check_cv041_preset_automation.py"
# CV-048: generation listener and bounded coherent snapshot probes are part of
# the glob-driven gate; keep an explicit guard against accidental deregistration.
test -f "$CORVUS_ROOT/scripts/check_cv048_preset_generation.py"
# CV-027: processBlock takes no MIDI-map lock and allocates nothing, including
# on the first MIDI-learn event (scripts/check_cv027_audio_thread_map.py).
test -f "$CORVUS_ROOT/scripts/check_cv027_audio_thread_map.py"
# CV-033: the headless offline render console targets stay in the build and keep
# their options (scripts/check_cv033_render_console.py). Same auto-registration
# applies; this explicit assertion keeps it from being lost silently too.
test -f "$CORVUS_ROOT/scripts/check_cv033_render_console.py"
# CV-011: the FX preset index tables stay inverse and cover every program
# (scripts/check_cv011_preset_index_tables.py). Same auto-registration applies;
# this explicit assertion keeps it from being lost silently too.
test -f "$CORVUS_ROOT/scripts/check_cv011_preset_index_tables.py"
# CV-061: chorus Depth / reverb Mix engaged from 0 never leaves the block
# coefficients at their zero initialisers, and every LFO phasor renormalizer
# resets a collapsed pair instead of dividing by zero
# (scripts/check_cv061_engage_from_zero.py). Same auto-registration applies;
# this explicit assertion keeps it from being lost silently too.
test -f "$CORVUS_ROOT/scripts/check_cv061_engage_from_zero.py"
# CV-066: a freshly inserted FX plays the default preset (0, "Clean Sparkle")
# silently — no undo transaction, gesture or host notification — and a host
# program recall does not load the same preset twice
# (scripts/check_cv066_default_preset.py). Same auto-registration applies;
# this explicit assertion keeps it from being lost silently too.
test -f "$CORVUS_ROOT/scripts/check_cv066_default_preset.py"
# CV-063: moving the reverb Size knob (or an automation ramp) must not memset
# and restart the early-reflection taps while the parameter is still travelling;
# only a genuinely discontinuous jump re-seeds them
# (scripts/check_cv063_reverb_size_click.py). Same auto-registration applies;
# this explicit assertion keeps it from being lost silently too.
test -f "$CORVUS_ROOT/scripts/check_cv063_reverb_size_click.py"
# CV-064/CV-080: chorus bypass and Depth fade the output without stopping
# the process/advance pair.
# (scripts/check_cv064_chorus_depth_engage.py). Same auto-registration applies;
# this explicit assertion keeps it from being lost silently too.
test -f "$CORVUS_ROOT/scripts/check_cv064_chorus_depth_engage.py"
# CV-067: the A/B compare slots belong to the processor - the constructor seeds
# them once from the settled live values, the editor never reseeds, and a state
# without a complete abSlots pair derives both slots instead of restoring zeros
# (scripts/check_cv067_ab_snapshots.py). Same auto-registration applies; this
# explicit assertion keeps it from being lost silently too.
test -f "$CORVUS_ROOT/scripts/check_cv067_ab_snapshots.py"
# CV-072: the editor's A/B slot indicator must follow the processor's slot -
# timerCallback polls isSlotA(), re-points both toggles only on a disagreement,
# and re-derives the SAVE target's colour/tooltip, including after a host state
# restore (scripts/check_cv072_ab_slot_indicator.py). Same auto-registration
# applies; this explicit assertion keeps it from being lost silently too.
test -f "$CORVUS_ROOT/scripts/check_cv072_ab_slot_indicator.py"
# CV-065: stealing a live voice fades the outgoing note across the existing
# declick window before the reset, instead of cutting it to zero
# (scripts/check_cv065_voice_steal_fade.py). Same auto-registration applies;
# this explicit assertion keeps it from being lost silently too.
test -f "$CORVUS_ROOT/scripts/check_cv065_voice_steal_fade.py"
# CV-071: a reverb Size jump made while the module is silent (bypassed or mix
# at zero, so no block renders) must still mute the early field on the first
# audible block - the "value just applied" baseline advances only on a block
# that rendered audio (scripts/check_cv071_silent_size_jump.py). Same
# auto-registration applies; this explicit assertion keeps it from being lost
# silently too.
test -f "$CORVUS_ROOT/scripts/check_cv071_silent_size_jump.py"
# CV-069: the copy a buyer reads (tooltips) is plain ASCII with no spacebar
# promise keyPressed() cannot keep, and README/ROADMAP/PRIORITIES state the
# shipped ping-pong spread, Output Trim range and A/B snapshot count
# (scripts/check_cv069_release_strings.py). Same auto-registration applies; this
# explicit assertion keeps it from being lost silently too.
test -f "$CORVUS_ROOT/scripts/check_cv069_release_strings.py"
CORVUS_CHECK_COUNT=0
for check in "$CORVUS_ROOT"/scripts/check_*.py; do
    test -f "$check"
    python3 -X utf8 "$check"
    CORVUS_CHECK_COUNT=$((CORVUS_CHECK_COUNT + 1))
done
printf 'GATE_OK: %s source checkers\n' "$CORVUS_CHECK_COUNT"
