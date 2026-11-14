#!/usr/bin/env python3
"""Headless checker: CV-028 / CV-048 — a preset or state recall reaches the FX
audio path as ONE coherent parameter generation.

Before this fix every recall path wrote the parameter set one id at a time:
loadPreset's `set(...)` roster, loadSlotA/loadSlotB's 24-parameter loop and
setStateInformation's `apvts.replaceState`. processBlock reads the same 24
parameters one at a time at the top of its block (`smoothX.setTargetValue(
apvts.getRawParameterValue("...")->load() ...)`), so a block that overlapped a
recall could smooth the new chorus depth next to the old reverb mix and render
an audible hybrid of two presets.

Pinned shape (the instrument processor's contract, reused here):

  * PluginProcessor.h declares `ParameterGeneration` (one field per abParamIds
    entry) plus the writer flag, the batch epoch, the generation sequence
    counter, one sequentially consistent payload atomic per field and
    `lastGoodGeneration`.
  * ParameterGenerationBatch (PluginProcessor.cpp) opens/closes the batch with a
    seq_cst epoch bump on `presetBatchSequence`; `close()` is idempotent and the
    destructor is the exception/early-return path.
  * publishParameterGeneration() takes the writer flag without waiting, aborts
    on an odd epoch, captures all 24 raw parameters (ordered exactly like
    abParamIds), aborts again when the even epoch moved across the capture, and
    only then commits the payload between two seq_cst sequence markers.
  * readParameterGeneration() is a bounded (3-attempt, no `while`) seqlock read
    that rejects an odd or moved sequence and otherwise returns the caller's
    `lastGood`.
  * applyParameterGeneration() re-seeds all 19 smoothers and 5 bypass gains from
    one generation, through the same finiteSmoothingTarget guard and the same
    delay-feedback curve coefficients the live header uses.
  * processBlock publishes + reads the generation before its parameter header,
    samples the batch epoch before the first header write, and — when the epoch
    moved or is odd across those reads — restores lastGoodGeneration through
    applyParameterGeneration() before the per-sample loop.
  * loadPreset, loadSlotA, loadSlotB and setStateInformation each construct the
    batch BEFORE their first parameter write and `batch.close();` +
    publishParameterGeneration() after their last one.

Negative self-probes run on mutated in-memory copies (the real tree is never
written): dropping the batch from a recall path, dropping batch.close(),
publishing before the batch closes, dropping the epoch check in the publisher,
dropping the odd-epoch abort, dropping the processBlock restore, dropping the
AFTER epoch sample and dropping one parameter from the captured roster must all
be rejected. A benign comment edit must still pass (probe specificity).

Exit 0 = ok, 1 = violation with a cited diagnostic.
"""
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
CPP = ROOT / "source" / "DrippyFX" / "PluginProcessor.cpp"
HDR = ROOT / "source" / "DrippyFX" / "PluginProcessor.h"

# (parameter id, ParameterGeneration field, mapping family, smoother/gain member)
# in abParamIds[] order — the publisher must capture exactly this roster.
ROSTER = [
    ("overall", "overall", "pct", "smoothOverall"),
    ("fatness", "fatness", "pct", "smoothFatness"),
    ("chorus_depth", "chorusDepth", "pct", "smoothChorusDepth"),
    ("chorus_rate", "chorusRate", "native", "smoothChorusRate"),
    ("chorus_mix", "chorusMix", "pct", "smoothChorusMix"),
    ("delay_time", "delayTime", "native", "smoothDelayTime"),
    ("delay_feedback", "delayFeedback", "feedback", "smoothDelayFeedback"),
    ("delay_mix", "delayMix", "pct", "smoothDelayMix"),
    ("delay_damping", "delayDamping", "pct", "smoothDelayDamping"),
    ("delay_mod", "delayMod", "pct", "smoothDelayMod"),
    ("reverb_size", "reverbSize", "pct", "smoothReverbSize"),
    ("reverb_damping", "reverbDamping", "pct", "smoothReverbDamping"),
    ("reverb_mix", "reverbMix", "pct", "smoothReverbMix"),
    ("reverb_mod", "reverbMod", "pct", "smoothReverbMod"),
    ("master_drive", "masterDrive", "pct", "smoothMasterDrive"),
    ("master_width", "masterWidth", "pct", "smoothMasterWidth"),
    ("master_mid_drive", "masterMidDrive", "pct", "smoothMasterMidDrive"),
    ("master_side_drive", "masterSideDrive", "pct", "smoothMasterSideDrive"),
    ("distortion_bypass", "distortionBypass", "bool", "bypassGainDist"),
    ("chorus_bypass", "chorusBypass", "bool", "bypassGainChorus"),
    ("delay_bypass", "delayBypass", "bool", "bypassGainDelay"),
    ("reverb_bypass", "reverbBypass", "bool", "bypassGainReverb"),
    ("master_bypass", "masterBypass", "bool", "bypassGainMaster"),
    ("output_trim", "outputTrim", "pct", "smoothOutputTrim"),
]


def fail(msg):
    print(f"CV028-FX-GENERATION FAIL: {msg}")
    sys.exit(1)


def strip_comments(txt):
    out, i, n = [], 0, len(txt)
    while i < n:
        if txt.startswith("//", i):
            j = txt.find("\n", i)
            i = n if j == -1 else j
        elif txt.startswith("/*", i):
            j = txt.find("*/", i + 2)
            i = n if j == -1 else j + 2
        else:
            out.append(txt[i])
            i += 1
    return "".join(out)


def squash(txt):
    """Remove every whitespace run, so shape asserts ignore formatting."""
    return re.sub(r"\s+", "", txt)


def block_after(txt, marker):
    """Brace-matched block that opens at/after `marker`, or None."""
    k = txt.find(marker)
    if k == -1:
        return None
    o = txt.find("{", k)
    if o == -1:
        return None
    depth, j = 0, o
    while j < len(txt):
        if txt[j] == "{":
            depth += 1
        elif txt[j] == "}":
            depth -= 1
            if depth == 0:
                return txt[o:j + 1]
        j += 1
    return None


def camel(field):
    return field[:1].upper() + field[1:]


def check(cpp_raw, hdr_raw):
    """Return None when the live (or mutated) tree satisfies the contract."""
    cpp = strip_comments(cpp_raw)
    hdr = strip_comments(hdr_raw)
    flat_hdr = squash(hdr)

    # ── 0. the recall roster is still the A/B parameter roster ──────────────
    if not re.search(r"abParamIds\s*\[\s*\w*\s*\]\s*=\s*\{", cpp):
        return "abParamIds[] declaration missing from PluginProcessor.cpp"
    declared = block_after(cpp, "abParamIds") or ""
    ids = re.findall(r'"([A-Za-z0-9_]+)"', declared)
    if ids != [entry[0] for entry in ROSTER]:
        return (f"abParamIds[] no longer matches the CV-028 generation roster "
                f"this checker pins ({len(ids)} ids) - a parameter was added "
                "or reordered without extending the recall generation")

    # ── 1. header: struct + flag + epoch + payload atomics + fallback ──────
    generation = block_after(hdr, "struct ParameterGeneration")
    if generation is None:
        return "PluginProcessor.h lost its ParameterGeneration struct"
    flat_generation = squash(generation)
    for pid, field, _family, _member in ROSTER:
        if f"{field}=" not in flat_generation:
            return (f"ParameterGeneration is missing a defaulted field "
                    f"`{field}` for parameter '{pid}'")
    for needle, label in (
            ("std::atomic_flaggenerationWriter=ATOMIC_FLAG_INIT;",
             "generationWriter writer flag"),
            ("std::atomic<std::uint32_t>presetBatchSequence{0};",
             "presetBatchSequence batch epoch"),
            ("std::atomic<std::uint32_t>generationSequence{0};",
             "generationSequence seqlock counter"),
            ("ParameterGenerationlastGoodGeneration;",
             "lastGoodGeneration fallback"),
    ):
        if needle not in flat_hdr:
            return (f"PluginProcessor.h lost the {label} - without it a recall "
                    "can be committed or consumed half-written")
    for pid, field, _family, _member in ROSTER:
        if f"generation{camel(field)}{{" not in flat_hdr:
            return (f"PluginProcessor.h lost the payload atomic "
                    f"`generation{camel(field)}` for '{pid}'")

    # ── 2. batch class: seq_cst epoch bump on open and close ───────────────
    batch_class = block_after(cpp, "class ParameterGenerationBatch final")
    if batch_class is None:
        return "ParameterGenerationBatch class missing from PluginProcessor.cpp"
    flat_batch = squash(batch_class)
    if flat_batch.count("sequence.fetch_add(1,std::memory_order_seq_cst);") != 2:
        return ("ParameterGenerationBatch must bump the batch epoch with "
                "`sequence.fetch_add(1, std::memory_order_seq_cst);` exactly "
                "twice (open and close)")
    if "voidclose()noexcept" not in flat_batch:
        return "ParameterGenerationBatch lost its idempotent close()"
    if "~ParameterGenerationBatch(){close();}" not in flat_batch:
        return ("ParameterGenerationBatch's destructor must call close() so an "
                "exception/early return cannot leave the epoch odd")

    # ── 3. publisher: never waits, rejects odd and moved epochs ────────────
    pub = block_after(
        cpp, "CorvusFXAudioProcessor::publishParameterGeneration(")
    if pub is None:
        return "publishParameterGeneration() definition missing"
    flat_pub = squash(pub)
    if "if(generationWriter.test_and_set(std::memory_order_acquire))return;" \
            not in flat_pub:
        return ("publishParameterGeneration must try-acquire the writer flag "
                "and return immediately - the audio block never waits")
    odd_abort = pub.find("(batchBefore & 1u) != 0")
    first_capture = pub.find("candidate.overall = ")
    epoch_check = pub.find("batchBefore != batchAfter")
    first_marker = pub.find(
        "generationSequence.fetch_add(1, std::memory_order_seq_cst);")
    last_marker = pub.rfind(
        "generationSequence.fetch_add(1, std::memory_order_seq_cst);")
    if -1 in (odd_abort, first_capture, epoch_check, first_marker) \
            or last_marker == first_marker:
        return ("publishParameterGeneration lost the odd-epoch abort, the "
                "roster capture, the moved-epoch check or one of its two "
                "sequence markers")
    if not odd_abort < first_capture:
        return ("the odd-epoch abort must run BEFORE the parameter capture - "
                "capturing during a recall records a mix of two presets")
    if not first_capture < epoch_check < first_marker:
        return ("the moved-epoch check (`batchBefore != batchAfter`) must sit "
                "between the capture and the first sequence marker - a batch "
                "can start and finish inside the capture")
    if flat_pub.count("generationWriter.clear(std::memory_order_release);") != 3:
        return ("publishParameterGeneration must release the writer flag on all "
                "three exits (odd epoch, moved epoch, committed)")
    odd_clear = pub.find("generationWriter.clear(", odd_abort)
    moved_clear = pub.find("generationWriter.clear(", epoch_check)
    if not (odd_abort < odd_clear < first_capture):
        return "the odd-epoch abort must release the writer flag before returning"
    if not (epoch_check < moved_clear < first_marker):
        return "the moved-epoch abort must release the writer flag before returning"

    captured = re.findall(
        r'candidate\.(\w+)\s*=\s*apvts\.getRawParameterValue\("([A-Za-z0-9_]+)"\)'
        r'->load\(\)(?:\s*>\s*0\.5f)?;', pub)
    if captured != [(entry[1], entry[0]) for entry in ROSTER]:
        return ("publishParameterGeneration captures "
                f"{[(pid, field) for field, pid in captured]} but the "
                "generation roster is "
                f"{[(pid, field) for pid, field, _f, _m in ROSTER]} - every "
                "parameter must join the generation in abParamIds order")
    for pid, field, family, _member in ROSTER:
        expect = (f"candidate.{field}=apvts.getRawParameterValue(\"{pid}\")"
                  f"->load(){'>0.5f' if family == 'bool' else ''};")
        if expect not in flat_pub:
            return (f"publisher capture for '{pid}' drifted - expected "
                    f"`{expect}`")
        commit = (f"generation{camel(field)}.store(candidate.{field},"
                  "std::memory_order_seq_cst);")
        if commit not in flat_pub:
            return (f"publisher does not commit `generation{camel(field)}` for "
                    f"'{pid}' with a seq_cst store")
        if not first_marker < pub.find(f"generation{camel(field)}.store(") \
                < last_marker:
            return (f"payload store `generation{camel(field)}` ({pid}) is "
                    "outside the two sequence markers - a reader could accept "
                    "it as part of the previous generation")

    # ── 4. reader: bounded seqlock, last-good fallback ─────────────────────
    reader = block_after(
        cpp, "CorvusFXAudioProcessor::readParameterGeneration(")
    if reader is None:
        return "readParameterGeneration() definition missing"
    flat_reader = squash(reader)
    if "for(intattempt=0;attempt<3;++attempt)" not in flat_reader:
        return ("readParameterGeneration must be a bounded 3-attempt loop - a "
                "retry-forever reader can starve the audio block")
    if "while" in flat_reader:
        return "readParameterGeneration must not contain an unbounded loop"
    if "if((before&1u)!=0)continue;" not in flat_reader:
        return ("readParameterGeneration must skip an odd (write in progress) "
                "sequence")
    if "if(before==after&&(after&1u)==0)returncandidate;" not in flat_reader:
        return ("readParameterGeneration must accept only a stable even "
                "sequence (before == after)")
    if "returnlastGood;" not in flat_reader:
        return ("readParameterGeneration must return the caller's last good "
                "generation when it cannot adopt a committed one")
    odd_skip = reader.find("(before & 1u) != 0")
    for pid, field, _family, _member in ROSTER:
        load = f"generation{camel(field)}.load(std::memory_order_seq_cst);"
        if load not in flat_reader:
            return (f"reader does not load `generation{camel(field)}` for "
                    f"'{pid}'")
        if reader.find(load) < odd_skip:
            return (f"reader loads `generation{camel(field)}` before its odd "
                    "sequence check")

    # ── 5. apply: every target re-seeded from one generation ───────────────
    seed = block_after(cpp, "inline void seedRestoredTarget(")
    if seed is None or squash(seed) != squash(
            "{ smoother.setTargetValue(finiteSmoothingTarget(mapped, "
            "fallback)); }"):
        return ("the CV-028 restore helper `seedRestoredTarget` must route "
                "every generated value through finiteSmoothingTarget - an "
                "unguarded seed would push a corrupt generation into a "
                "smoother")
    apply_body = block_after(
        cpp, "CorvusFXAudioProcessor::applyParameterGeneration(")
    if apply_body is None:
        return "applyParameterGeneration() definition missing"
    flat_apply = squash(apply_body)
    for pid, field, family, member in ROSTER:
        if family == "bool":
            expect = (f"seedRestoredTarget({member},"
                      f"generation.{field}?0.0f:1.0f,1.0f);")
        elif family == "feedback":
            expect = (f"seedRestoredTarget({member},feedbackTarget(fbRaw),"
                      f"feedbackTarget("
                      f"declaredPercentTarget(apvts,\"delay_feedback\")));")
        elif family == "native":
            expect = (f"seedRestoredTarget({member},generation.{field},"
                      f"declaredTarget(apvts,\"{pid}\"));")
        else:
            expect = (f"seedRestoredTarget({member},generation.{field}/100.0f,"
                      f"declaredPercentTarget(apvts,\"{pid}\"));")
        if expect not in flat_apply:
            return (f"applyParameterGeneration does not re-seed '{pid}' "
                    f"exactly as the block header does - expected `{expect}`")

    proc = block_after(cpp, "CorvusFXAudioProcessor::processBlock(")
    if proc is None:
        return "processBlock body missing"
    live = re.search(r"fbRaw \* fbRaw \* ([\d.]+)f \+ fbRaw \* ([\d.]+)f",
                     proc)
    if not live or "feedbackTarget(fbRaw)" not in flat_apply:
        return ("the delay-feedback curve is missing from processBlock or "
                "applyParameterGeneration")
    feedback_helper = block_after(cpp, "inline float feedbackTarget(")
    helper_curve = re.search(
        r"return linearAmount \* linearAmount \* ([\d.]+)f \+ linearAmount \* ([\d.]+)f",
        feedback_helper or "")
    if not helper_curve or live.groups() != helper_curve.groups():
        return ("feedbackTarget helper coefficients "
                f"{helper_curve.groups() if helper_curve else None} drifted from "
                f"the live header {live.groups()} - a restore would smooth a different curve")

    # ── 6. processBlock: epoch-guarded, last-good restore before the loop ──
    flat_proc = squash(proc)
    if "publishParameterGeneration();" not in flat_proc:
        return "processBlock no longer publishes the parameter generation"
    if "lastGoodGeneration=readParameterGeneration(lastGoodGeneration);" \
            not in flat_proc:
        return ("processBlock no longer adopts the committed generation into "
                "lastGoodGeneration")
    epoch_load = "presetBatchSequence.load(std::memory_order_seq_cst)"
    if proc.count(epoch_load) != 2:
        return ("processBlock must sample the batch epoch exactly twice (before "
                "and after its parameter header)")
    epoch_before = proc.find(epoch_load)
    epoch_after = proc.rfind(epoch_load)
    publish_pos = proc.find("publishParameterGeneration();")
    adopt_pos = proc.find(
        "lastGoodGeneration = readParameterGeneration(lastGoodGeneration);")
    first_target = proc.find("smoothOverall.setTargetValue(")
    last_target = proc.rfind("bypassGainMaster.setTargetValue(")
    guard = proc.find("if (generationBatchBefore != generationBatchAfter")
    apply_pos = proc.find("applyParameterGeneration(lastGoodGeneration);")
    loop = proc.find("for (int s = 0; s < numSamples")
    if -1 in (publish_pos, adopt_pos, first_target, last_target, guard,
              apply_pos, loop):
        return ("processBlock lost the publish / adopt / header / restore / "
                "per-sample loop anchors this checker pins")
    if not publish_pos < adopt_pos < epoch_before < first_target:
        return ("the publish, the lastGood adopt and the BEFORE epoch sample "
                "must all precede the parameter header")
    if not last_target < epoch_after < guard < apply_pos < loop:
        return ("the AFTER epoch sample, the epoch guard and the "
                "applyParameterGeneration(lastGoodGeneration) restore must all "
                "sit after the header's last target and before the per-sample "
                "loop - otherwise the mixed targets reach the audible path")
    if "(generationBatchAfter&1u)!=0" not in flat_proc:
        return ("the processBlock guard must also reject an odd (in flight) "
                "batch epoch, not only a moved one")

    # ── 7. every recall path: batch opens first, publishes last ────────────
    recalls = (
        ("loadPreset", 'set("fatness"'),
        ("loadSlotA", "apvts.getParameter(abParamIds[i])"),
        ("loadSlotB", "apvts.getParameter(abParamIds[i])"),
        ("setStateInformation", "apvts.replaceState("),
    )
    for fn, first_write in recalls:
        body = block_after(cpp, f"CorvusFXAudioProcessor::{fn}(")
        if body is None:
            return f"{fn} body missing"
        flat_body = squash(body)
        if flat_body.count(
                "ParameterGenerationBatchbatch(presetBatchSequence);") != 1:
            return (f"{fn} must construct exactly one "
                    "ParameterGenerationBatch(presetBatchSequence) - without "
                    "it its parameters are written one-by-one and a block can "
                    "render a mix of two presets")
        if first_write not in body:
            return f"{fn} no longer contains its pinned first write `{first_write}`"
        opens = body.find("ParameterGenerationBatch batch(presetBatchSequence);")
        write = body.find(first_write)
        close = body.find("batch.close();")
        publish = body.find("publishParameterGeneration();")
        if not opens < write:
            return (f"{fn} constructs the batch AFTER its first parameter write "
                    "- the first writes are unprotected")
        if close == -1 or publish == -1:
            return (f"{fn} must close the batch and publish the completed "
                    "generation")
        if not write < close < publish:
            return (f"{fn} must write every parameter between the batch open "
                    "and `batch.close();`, then publish - otherwise the "
                    "committed generation is still partial")

    # ── 8. the constructor seeds the first block's fallback ────────────────
    ctor = block_after(cpp, "CorvusFXAudioProcessor::CorvusFXAudioProcessor(")
    if ctor is None:
        return "CorvusFXAudioProcessor constructor body missing"
    flat_ctor = squash(ctor)
    if "publishParameterGeneration();" not in flat_ctor or \
            "lastGoodGeneration=readParameterGeneration(lastGoodGeneration);" \
            not in flat_ctor:
        return ("the constructor must publish the initial generation and seed "
                "lastGoodGeneration - the first block would otherwise fall "
                "back on struct defaults")
    return None


for path in (CPP, HDR):
    if not path.exists():
        fail(f"missing source file {path}")
try:
    cpp_raw = CPP.read_text(encoding="utf-8")
    hdr_raw = HDR.read_text(encoding="utf-8")
except OSError as exc:  # pragma: no cover - environment failure
    fail(f"could not read source: {exc}")

err = check(cpp_raw, hdr_raw)
if err:
    fail(err + " [PluginProcessor.cpp / PluginProcessor.h]")
print(f"cv028-fx-generation: {len(ROSTER)} parameters publish as one "
      "epoch-guarded generation; loadPreset / loadSlotA / loadSlotB / "
      "setStateInformation batch their writes; processBlock restores "
      "lastGoodGeneration on a torn epoch")

# ---------------------------------------------------------------------------
# Negative self-probes on mutated in-memory copies (real tree never mutated)
# ---------------------------------------------------------------------------


def probe(description, old, new, count=1):
    mutated = cpp_raw.replace(old, new, count)
    if mutated == cpp_raw:
        fail(f"no-op probe ({description}): mutation did not change the "
             "source - the negative check is stale")
    if check(mutated, hdr_raw) is None:
        fail(f"negative probe '{description}' was NOT rejected - checker is "
             "vacuous")
    print(f"cv028-fx-generation: negative probe '{description}' rejected")


# 1. the exact regression this checker exists for: a recall path writing its
#    parameters one-by-one again
probe("loadPreset batch dropped (parameters written one-by-one again)",
      "    // new one; the completed set is published as one generation at the end.\n"
      "    ParameterGenerationBatch batch(presetBatchSequence);\n",
      "    // new one; the completed set is published as one generation at the end.\n")

# 2. the batch opened but the completed set published before it closes
probe("loadPreset publishes before batch.close()",
      "    batch.close();\n    publishParameterGeneration();\n}",
      "    publishParameterGeneration();\n    batch.close();\n}")

# 3. an A/B recall that never closes/publishes its completed generation
probe("loadSlotA close/publish dropped",
      "    batch.close();\n    publishParameterGeneration();\n    // A/B preset choice",
      "    // A/B preset choice")

# 4. the publisher committing a capture that straddled a batch epoch
probe("publisher moved-epoch check dropped",
      "    if (batchBefore != batchAfter || (batchAfter & 1u) != 0)",
      "    if (false)")

# 5. the publisher capturing live parameters while a batch is open
probe("publisher odd-epoch abort dropped",
      "    if ((batchBefore & 1u) != 0)",
      "    if (false)")

# 6. a parameter dropped from the captured roster (silent half-generation)
probe("publisher roster drops output_trim",
      '    candidate.outputTrim = apvts.getRawParameterValue("output_trim")->load();\n',
      "")

# 7. processBlock no longer restoring the last coherent generation
probe("processBlock last-good restore dropped",
      "        applyParameterGeneration(lastGoodGeneration);",
      "        (void) 0;")

# 8. the header's AFTER epoch sample dropped (the guard can never fire)
probe("processBlock AFTER epoch sample dropped",
      "    const auto generationBatchAfter = presetBatchSequence.load("
      "std::memory_order_seq_cst);\n",
      "    const auto generationBatchAfter = generationBatchBefore;\n")

# 9. a session restore written outside a batch
probe("setStateInformation batch dropped",
      "        ParameterGenerationBatch batch(presetBatchSequence);\n"
      "        restoringPresetState.store(true);",
      "        restoringPresetState.store(true);")

# no-op guard: a benign comment inside the guarded processBlock region stays
# accepted (the checker pins shape, not text)
neutral = cpp_raw.replace(
    "    publishParameterGeneration();\n"
    "    lastGoodGeneration = readParameterGeneration(lastGoodGeneration);",
    "    // benign probe comment\n"
    "    publishParameterGeneration();\n"
    "    lastGoodGeneration = readParameterGeneration(lastGoodGeneration);", 1)
if neutral == cpp_raw:
    fail("no-op guard: unanchored neutral edit did not change the source")
if check(neutral, hdr_raw) is not None:
    fail("neutral edit outside the pinned shapes was REJECTED - checker "
         "over-fires")
print("cv028-fx-generation: benign comment edit passes (probe specificity)")

# real tree never mutated - re-verify the live sources once more before gating
err = check(CPP.read_text(encoding="utf-8"), HDR.read_text(encoding="utf-8"))
if err:
    fail(f"final source re-verification failed: {err}")
print("CV028-FX-GENERATION OK")
