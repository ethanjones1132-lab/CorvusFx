#!/usr/bin/env python3
"""Headless checker: stealing a Corvus voice must fade the outgoing note (CV-065).

Defect: CorvusVoice::startNote() reset the oscillator phase and the ADSR and
called noteOn() at the instant a live voice was stolen. The old note's samples
were replaced by silence plus the replacement note's fade-in in the same
sample, i.e. an immediate reset-to-zero discontinuity at the steal boundary.

Fix: the steal branch keeps the running oscillator phase, envelope and velocity
and asks for one declick window of fade-out. The reset/reuse is deferred: the
outgoing tail is rendered first with a gain ramping from 1.0 to 1/declickLength,
and only after the last tail sample has been produced does applyPendingStart()
reset and start the replacement note - which keeps its own short declick
fade-in. Note ownership (number/age) transfers immediately, so the bounded
16-voice allocation and MIDI note ownership are untouched, and nothing
allocates on the audio thread.

Asserts on the real tree (comment-stripped, brace-matched CorvusVoice class):
  (a) startNote has a `replacingLiveVoice` branch that records the pending note
      and requests `stealFadeSamplesRemaining = declickLength`, transfers
      noteNumber/age immediately, and contains no oscillator/envelope reset,
      no beginNote() and no updateFrequency() - the old samples must be
      rendered before any reset;
  (b) renderNextSample() produces the tail sample from oscillator.process()
      BEFORE the decrement that applies the pending start, applies
      `envelopeValue * stealFromVelocity * stealFadeScale()` and still renders
      the replacement's declick fade-in on the normal path;
  (c) stealFadeScale() ramps from 1.0 down in declickLength steps (a real
      division by declickLength, not a flat 1.0);
  (d) applyPendingStart() resets and restarts the voice (beginNote) and gives
      the replacement `declickSamplesRemaining = declickLength`;
  (e) finishRenderSpan() and render() cannot retire the voice while a steal
      tail is owed, updateFrequency() keeps the outgoing pitch until the
      deferred start, and a note-off arriving during the fade is still applied
      to the replacement (sustain-held or released, never stuck down);
  (f) declickLength is declared exactly once, equals 32, and the regression
      test uses the same window;
  (g) the class allocates nothing (no new/malloc/vector/make_unique);
  (h) CorvusDspTests.cpp still holds the focused regression: the steal tail is
      compared against an un-stolen reference note times the fade ramp, the
      first tail sample equals the reference sample (no reset to zero), and
      the replacement note renders at its own pitch afterwards.

Negative probes (in-memory mutated copies; a stale mutation aborts as an alarm,
the real tree is never mutated):
  - beginNote() at the steal instant (the old immediate reset) -> rejected;
  - zero-length steal window (immediate cut) -> rejected;
  - flat steal fade (no decreasing gain) -> rejected;
  - no deferred reset (the replacement never starts) -> rejected;
  - drop the replacement's declick fade-in -> rejected;
  - let finishRenderSpan retire the voice mid-fade -> rejected;
  - advance the fade twice per sample -> rejected;
  - do not transfer note ownership at the steal -> rejected;
  - strip the ramp assertion from the regression test -> rejected;
  - benign comment edit naming the pinned members -> accepted.

Exit 0 = ok, 1 = violation with a cited diagnostic, 2 = setup/read failure.
"""
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
VOICE = ROOT / "source" / "DrippyFX" / "instrument" / "CorvusVoice.h"
TESTS = ROOT / "source" / "DrippyFX" / "tests" / "CorvusDspTests.cpp"

DECLICK_WINDOW = 32
TEST_LABEL = "stealing a voice fades the outgoing note over its declick window"


def strip_comments(src):
    src = re.sub(r"/\*.*?\*/", "", src, flags=re.S)
    src = re.sub(r"//[^\n]*", "", src)
    return src


def brace_span(code, open_idx):
    depth = 0
    for i in range(open_idx, len(code)):
        if code[i] == "{":
            depth += 1
        elif code[i] == "}":
            depth -= 1
            if depth == 0:
                return open_idx + 1, i
    return None, None


def brace_body(code, open_idx):
    start, end = brace_span(code, open_idx)
    if start is None:
        return None
    return code[start:end]


def class_body(code, name):
    match = re.search(r"\bclass\s+" + re.escape(name) + r"\b[^;{]*\{", code)
    if not match:
        return None
    return brace_body(code, match.end() - 1)


def function_bodies(text, pattern):
    bodies = []
    for match in re.finditer(pattern, text):
        opening = text.find("{", match.end() - 1)
        if opening == -1:
            continue
        body = brace_body(text, opening)
        if body is not None:
            bodies.append(body)
    return bodies


class Reject(Exception):
    pass


def require(body, pattern, why):
    if re.search(pattern, body, flags=re.S) is None:
        raise Reject(why)


def forbid(body, pattern, why):
    if re.search(pattern, body, flags=re.S) is not None:
        raise Reject(why)


def single_body(voice, pattern, label):
    bodies = function_bodies(voice, pattern)
    if not bodies:
        raise Reject("%s body not found / brace-matched" % label)
    return bodies[0]


def steal_branch(start_body):
    match = re.search(r"if\s*\(\s*replacingLiveVoice\s*\)\s*\{", start_body)
    if match is None:
        raise Reject("startNote no longer branches on `if (replacingLiveVoice)` "
                     "- a steal is indistinguishable from a fresh note")
    body = brace_body(start_body, match.end() - 1)
    if body is None:
        raise Reject("replacingLiveVoice branch not brace-matched")
    return body


def verify_voice(header_text):
    code = strip_comments(header_text)
    voice = class_body(code, "CorvusVoice")
    if voice is None:
        raise Reject("class CorvusVoice not found / brace-matched")
    if len(voice) < 2500:
        raise Reject("brace matching drifted (CorvusVoice body only %d chars) "
                     "- do not trust green" % len(voice))

    start = single_body(voice, r"void\s+startNote\s*\(\s*int\s+newNoteNumber\s*,",
                        "CorvusVoice::startNote")
    branch = steal_branch(start)

    # --- (a) the steal records a deferred start and resets nothing yet ------
    require(branch, r"pendingParameters\s*=\s*parameters\s*;",
            "the steal branch does not record the replacement's parameters - "
            "the deferred start would use stale values")
    require(branch, r"stealFadeSamplesRemaining\s*=\s*declickLength\s*;",
            "the steal branch does not request a declick-length fade "
            "(`stealFadeSamplesRemaining = declickLength;`) - a zero window is "
            "the immediate cut CV-065 removes")
    require(branch, r"noteNumber\s*=\s*pendingNoteNumber\s*;",
            "the steal branch no longer transfers note ownership immediately - "
            "the replacement note would not own the voice during the fade")
    require(branch, r"age\s*=\s*pendingAge\s*;",
            "the steal branch no longer transfers the age counter - voice "
            "allocation order would change on a steal")
    for pattern, why in (
            (r"\boscillator\s*\.\s*reset\s*\(", "oscillator.reset()"),
            (r"\benvelope\s*\.\s*reset\s*\(", "envelope.reset()"),
            (r"\benvelope\s*\.\s*noteOn\s*\(", "envelope.noteOn()"),
            (r"\bbeginNote\s*\(", "beginNote()"),
            (r"\bupdateFrequency\s*\(", "updateFrequency()")):
        forbid(branch, pattern,
               "the steal branch calls %s before the outgoing samples have "
               "been rendered - that is the immediate reset-to-zero CV-065 "
               "fixes" % why)
    require(branch, r"return\s*;",
            "the steal branch does not return into the deferred path")

    # --- (b) the tail render fades first and resets afterwards -------------
    render = single_body(voice, r"float\s+renderNextSample\s*\(",
                         "CorvusVoice::renderNextSample")
    fade_match = re.search(
        r"if\s*\(\s*stealFadeSamplesRemaining\s*>\s*0\s*\)\s*\{", render)
    if fade_match is None:
        raise Reject("renderNextSample no longer has a "
                     "`stealFadeSamplesRemaining > 0` fade branch - the "
                     "outgoing note would be cut")
    fade = brace_body(render, fade_match.end() - 1)
    if fade is None:
        raise Reject("steal fade branch not brace-matched")
    require(fade,
            r"gainOut\s*=\s*envelopeValue\s*\*\s*stealFromVelocity\s*\*\s*"
            r"stealFadeScale\s*\(\s*\)\s*;",
            "the fade branch does not scale the outgoing envelope by "
            "stealFromVelocity and stealFadeScale()")
    require(fade, r"oscillator\s*\.\s*process\s*\(\s*\)",
            "the fade branch never reads the outgoing oscillator")
    process_at = fade.find("oscillator.process()")
    apply_at = fade.find("applyPendingStart()")
    if apply_at == -1:
        raise Reject("the fade branch never applies the deferred start - the "
                     "replacement note would never become audible")
    if process_at > apply_at:
        raise Reject("applyPendingStart() runs before the outgoing sample is "
                     "produced - the tail would be reset before it is rendered")
    require(fade,
            r"if\s*\(\s*--\s*stealFadeSamplesRemaining\s*==\s*0\s*\)\s*"
            r"applyPendingStart\s*\(\s*\)\s*;",
            "the fade must advance exactly one sample per rendered sample and "
            "apply the pending start when the window closes")
    forbid(fade, r"declickSamplesRemaining\s*=",
           "the fade branch writes the replacement's declick counter")
    require(render,
            r"declickLength\s*-\s*declickSamplesRemaining",
            "the normal render path lost the new-note declick fade-in")

    # --- (c) the fade really ramps over the declick window -----------------
    scale = single_body(voice, r"float\s+stealFadeScale\s*\(\s*\)\s*const",
                        "CorvusVoice::stealFadeScale")
    require(scale, r"if\s*\(\s*stealFadeSamplesRemaining\s*<=\s*0\s*\)\s*"
                   r"return\s+1\.0f\s*;",
            "stealFadeScale no longer returns 1.0 when no fade is running")
    require(scale,
            r"return\s+static_cast<float>\s*\(\s*stealFadeSamplesRemaining\s*\)"
            r"\s*/\s*static_cast<float>\s*\(\s*declickLength\s*\)\s*;",
            "stealFadeScale must divide the remaining fade samples by "
            "declickLength - a flat gain is the old abrupt cut")

    # --- (d) the deferred start performs the reset and keeps the declick ---
    apply_start = single_body(voice, r"void\s+applyPendingStart\s*\(",
                              "CorvusVoice::applyPendingStart")
    require(apply_start, r"stealFadeSamplesRemaining\s*=\s*0\s*;",
            "applyPendingStart does not end the fade window")
    require(apply_start, r"noteNumber\s*=\s*pendingNoteNumber\s*;",
            "applyPendingStart does not install the replacement's note number")
    require(apply_start, r"velocity\s*=\s*pendingVelocity\s*;",
            "applyPendingStart does not install the replacement's velocity")
    require(apply_start, r"age\s*=\s*pendingAge\s*;",
            "applyPendingStart does not install the replacement's age")
    require(apply_start, r"beginNote\s*\(\s*pendingParameters\s*\)\s*;",
            "applyPendingStart does not reset/start the replacement note")
    require(apply_start, r"declickSamplesRemaining\s*=\s*declickLength\s*;",
            "applyPendingStart drops the replacement note's declick fade-in")

    begin = single_body(voice, r"void\s+beginNote\s*\(", "CorvusVoice::beginNote")
    for pattern, why in (
            (r"oscillator\s*\.\s*reset\s*\(", "oscillator.reset()"),
            (r"envelope\s*\.\s*reset\s*\(", "envelope.reset()"),
            (r"envelope\s*\.\s*noteOn\s*\(", "envelope.noteOn()")):
        require(begin, pattern,
                "beginNote() no longer performs %s - the deferred reset has no "
                "body" % why)

    # --- (e) nobody retires the voice (or re-pitches it) mid-fade ----------
    finish = single_body(voice, r"void\s+finishRenderSpan\s*\(",
                         "CorvusVoice::finishRenderSpan")
    require(finish, r"if\s*\(\s*stealFadeSamplesRemaining\s*>\s*0\s*\)\s*"
                    r"return\s*;",
            "finishRenderSpan can retire the voice while a steal tail is still "
            "owed - the fade would be cut short")
    block = single_body(voice, r"void\s+render\s*\(\s*float\s*\*\s*left\s*,",
                        "CorvusVoice::render")
    require(block,
            r"if\s*\(\s*stealFadeSamplesRemaining\s*<=\s*0\s*&&\s*"
            r"!\s*envelope\s*\.\s*isActive\s*\(\s*\)\s*\)",
            "render() no longer guards the end-of-block retire on the steal "
            "tail (the outgoing note would be reset mid-fade)")
    freq = single_body(voice, r"void\s+updateFrequency\s*\(",
                       "CorvusVoice::updateFrequency")
    require(freq, r"if\s*\(\s*stealFadeSamplesRemaining\s*>\s*0\s*\)\s*"
                  r"return\s*;",
            "updateFrequency can retune the outgoing note mid-fade; the stored "
            "bend must apply when the replacement starts")

    # --- (e2) a note-off during the fade still reaches the replacement -----
    defer = single_body(voice, r"void\s+deferNoteOff\s*\(",
                        "CorvusVoice::deferNoteOff")
    require(defer, r"\bpendingDeferOnStart\s*=\s*true\s*;",
            "deferNoteOff no longer remembers a sustain-held note-off across "
            "the steal fade - the replacement could stay stuck down")
    require(apply_start,
            r"else\s+if\s*\(\s*pendingDeferOnStart\s*\)\s*\{[^}]*"
            r"keyDown\s*=\s*false\s*;",
            "applyPendingStart does not leave a sustain-held replacement "
            "released from the key after the fade")
    require(apply_start,
            r"if\s*\(\s*pendingReleaseOnStart\s*\)\s*\{[^}]*"
            r"envelope\s*\.\s*noteOff\s*\(\s*\)\s*;",
            "applyPendingStart does not release a replacement whose note-off "
            "arrived during the fade")

    # --- (f) one declick window, shared with the regression test -----------
    decl = re.findall(r"static\s+constexpr\s+auto\s+declickLength\s*=\s*"
                      r"(\d+)\s*;", voice)
    if decl != [str(DECLICK_WINDOW)]:
        raise Reject("declickLength must be declared exactly once as %d "
                     "(found %r)" % (DECLICK_WINDOW, decl))

    # --- (g) the voice still allocates nothing -----------------------------
    for pattern, why in ((r"\bnew\b", "raw new"),
                         (r"\bmalloc\b", "malloc"),
                         (r"\bfree\s*\(", "free()"),
                         (r"std::vector", "std::vector"),
                         (r"make_unique", "make_unique"),
                         (r"push_back", "push_back")):
        forbid(voice, pattern,
               "CorvusVoice uses %s - voice stealing must not allocate on the "
               "audio thread" % why)


def verify_tests(tests_text):
    code = strip_comments(tests_text)
    marker = 'beginTest("%s")' % TEST_LABEL
    at = code.find(marker)
    if at == -1:
        raise Reject("CorvusDspTests.cpp no longer has the focused regression "
                     "block `%s`" % marker)
    opening = code.find("{", at)
    block = brace_body(code, opening) if opening != -1 else None
    if block is None:
        raise Reject("the voice-steal regression block is not brace-matched")

    require(block, r"constexpr\s+auto\s+fadeWindow\s*=\s*%d\s*;"
                   % DECLICK_WINDOW,
            "the regression no longer pins the declick window to %d samples"
            % DECLICK_WINDOW)
    require(block, r"stolenVoice\s*\.\s*startNote\s*\(",
            "the regression never steals a voice")
    require(block,
            r"expect\s*\(\s*stolenVoice\s*\.\s*isActive\s*\(\s*\)",
            "the regression does not assert that the replacement note is "
            "active during the fade")
    require(block,
            r"expect\s*\(\s*stolenVoice\s*\.\s*getNoteNumber\s*\(\s*\)\s*==\s*69",
            "the regression does not assert immediate note ownership")
    require(block,
            r"static_cast<float>\s*\(\s*fadeWindow\s*-\s*sample\s*\)\s*/\s*"
            r"static_cast<float>\s*\(\s*fadeWindow\s*\)",
            "the regression no longer builds the 1.0 -> 0 fade ramp")
    require(block, r"referenceTailLeft\s*\[\s*sample\s*\]\s*\*\s*fadeGain",
            "the regression no longer compares the stolen tail with the "
            "un-stolen reference note times the fade ramp")
    require(block,
            r"expectWithinAbsoluteError\s*\(\s*stolenTailLeft\s*\[\s*0\s*\]\s*,"
            r"\s*referenceTailLeft\s*\[\s*0\s*\]",
            "the regression no longer pins the first tail sample to the "
            "reference sample (the no-reset-to-zero boundary)")
    require(block, r"stolenPrimeLeft\s*\.\s*back\s*\(\s*\)",
            "the regression no longer checks the sample before the steal for "
            "an adjacent-sample discontinuity")
    require(block,
            r"expectWithinAbsoluteError\s*\(\s*static_cast<float>\s*\(\s*"
            r"newNoteCrossings\s*\)\s*,\s*440\.0f\s*,",
            "the regression no longer proves the replacement note renders its "
            "own pitch after the fade")


def run(voice_text, tests_text):
    try:
        verify_voice(voice_text)
        verify_tests(tests_text)
    except Reject as exc:
        return str(exc)
    return None


def _replace_once(txt, old, new):
    if old not in txt:
        return txt
    return txt.replace(old, new, 1)


def main():
    for path in (VOICE, TESTS):
        if not path.exists():
            print("CV-065 VOICE-STEAL-FADE SETUP FAIL: missing %s" % path)
            return 2
    try:
        voice_text = VOICE.read_text(encoding="utf-8", errors="replace")
        tests_text = TESTS.read_text(encoding="utf-8", errors="replace")
    except OSError as exc:
        print("CV-065 VOICE-STEAL-FADE SETUP FAIL: %s" % exc)
        return 2

    verdict = run(voice_text, tests_text)
    if verdict is not None:
        print("CV-065 VOICE-STEAL-FADE FAIL: %s" % verdict)
        return 1
    print("cv065-voice-steal-fade: %s renders the outgoing note for one "
          "32-sample declick window (ramp 1.0 -> 1/32), then resets the voice "
          "and starts the replacement with its own declick; "
          "%s holds the matching steal-boundary regression"
          % (VOICE.relative_to(ROOT), TESTS.relative_to(ROOT)))

    steal_tail = "            stealFadeSamplesRemaining = declickLength;\n\n" \
                 "            noteNumber = pendingNoteNumber;"
    probes = [
        ("reset the voice at the steal instant (the old defect)",
         lambda s, t: (_replace_once(
             s, steal_tail,
             "            beginNote(parameters);\n"
             "            stealFadeSamplesRemaining = declickLength;\n\n"
             "            noteNumber = pendingNoteNumber;"), t)),
        ("request a zero-length steal window (immediate cut)",
         lambda s, t: (_replace_once(
             s, "            stealFadeSamplesRemaining = declickLength;",
             "            stealFadeSamplesRemaining = 0;"), t)),
        ("flatten the steal fade (no decreasing gain)",
         lambda s, t: (_replace_once(
             s,
             "        return static_cast<float>(stealFadeSamplesRemaining)\n"
             "            / static_cast<float>(declickLength);",
             "        return 1.0f;"), t)),
        ("drop the deferred start (the replacement never becomes audible)",
         lambda s, t: (_replace_once(
             s,
             "            if (--stealFadeSamplesRemaining == 0)\n"
             "                applyPendingStart();",
             "            --stealFadeSamplesRemaining;"), t)),
        ("drop the replacement note's own declick fade-in",
         lambda s, t: (_replace_once(
             s,
             "        beginNote(pendingParameters);\n"
             "        declickSamplesRemaining = declickLength;",
             "        beginNote(pendingParameters);"), t)),
        ("let finishRenderSpan retire the voice mid-fade",
         lambda s, t: (_replace_once(
             s,
             "        if (stealFadeSamplesRemaining > 0)\n"
             "            return;\n\n"
             "        if (active && !envelope.isActive())",
             "        if (active && !envelope.isActive())"), t)),
        ("advance the fade twice per rendered sample",
         lambda s, t: (_replace_once(
             s, "--stealFadeSamplesRemaining",
             "stealFadeSamplesRemaining -= 2"), t)),
        ("drop note ownership transfer at the steal",
         lambda s, t: (_replace_once(
             s,
             "            noteNumber = pendingNoteNumber;\n"
             "            age = pendingAge;\n"
             "            keyDown = true;\n"
             "            pitchBendSemitones = 0.0f;\n"
             "            return;",
             "            age = pendingAge;\n"
             "            keyDown = true;\n"
             "            pitchBendSemitones = 0.0f;\n"
             "            return;"), t)),
        ("strip the fade-ramp assertion from the regression",
         lambda s, t: (s, _replace_once(
             t, "referenceTailLeft[sample] * fadeGain,",
             "referenceTailLeft[sample],"))),
    ]
    for label, mutate in probes:
        mutated_voice, mutated_tests = mutate(voice_text, tests_text)
        if (mutated_voice, mutated_tests) == (voice_text, tests_text):
            print("CV-065 VOICE-STEAL-FADE FAIL: probe '%s' is stale: mutation "
                  "did not apply - cannot trust the negative check" % label)
            return 1
        verdict = run(mutated_voice, mutated_tests)
        if verdict is None:
            print("CV-065 VOICE-STEAL-FADE FAIL: probe '%s' was NOT rejected - "
                  "checker is vacuous" % label)
            return 1
        print("cv065-voice-steal-fade: probe '%s' rejected (%s)"
              % (label, verdict[:88]))

    neutral = voice_text.replace(
        "    WavetableOscillator oscillator;",
        "    // A comment naming stealFadeSamplesRemaining, declickLength,\n"
        "    // applyPendingStart(), beginNote(), renderNextSample(),\n"
        "    // stealFadeScale() and updateFrequency() is prose, not code.\n"
        "    WavetableOscillator oscillator;", 1)
    if neutral == voice_text:
        print("CV-065 VOICE-STEAL-FADE FAIL: benign comment probe is stale: the "
              "edit did not apply")
        return 1
    verdict = run(neutral, tests_text)
    if verdict is not None:
        print("CV-065 VOICE-STEAL-FADE FAIL: benign comment edit was rejected "
              "- checker over-fires: %s" % verdict)
        return 1
    print("cv065-voice-steal-fade: benign comment edit accepted (probe "
          "specificity proven)")

    if run(VOICE.read_text(encoding="utf-8", errors="replace"),
           TESTS.read_text(encoding="utf-8", errors="replace")) is not None:
        print("CV-065 VOICE-STEAL-FADE FAIL: final live-source re-verification "
              "failed")
        return 1
    print("CV-065 VOICE-STEAL-FADE OK (9 negatives, comment edit accepted)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
