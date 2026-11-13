from pathlib import Path
import re


root = Path(__file__).resolve().parents[1]
header = (root / "source/DrippyFX/instrument/CorvusInstrumentProcessor.h").read_text(encoding="utf-8")
source = (root / "source/DrippyFX/instrument/CorvusInstrumentProcessor.cpp").read_text(encoding="utf-8")

ids = ("osc_wave", "attack", "decay", "sustain", "release", "fx_amount", "flight", "output")
for parameter_id in ids:
    assert f'"{parameter_id}"' in source, f"missing parameter listener ID: {parameter_id}"
assert source.count("apvts.addParameterListener(id, this)") == 1
assert source.count("apvts.removeParameterListener(id, this)") == 1
assert "private juce::AudioProcessorValueTreeState::Listener" in header

listener_start = source.index("void CorvusInstrumentProcessor::parameterChanged")
listener_end = source.index("void CorvusInstrumentProcessor::publishParameterGeneration", listener_start)
listener = source[listener_start:listener_end]
assert "presetBatchSequence.load" in listener
assert "generationDirty.store(true" in listener
assert "publishParameterGeneration();" in listener

publisher_start = listener_end
publisher_end = source.index("CorvusInstrumentProcessor::readParameterGeneration", publisher_start)
publisher = source[publisher_start:publisher_end]
assert "generationWriter.test_and_set" in publisher
assert "generationDirty.exchange(false" in publisher
assert publisher.count("generationDirty.exchange(false") == 1
assert "batchBefore != batchAfter" in publisher
assert "(batchBefore & 1u)" in publisher and "(batchAfter & 1u)" in publisher

# Regression for the held lost-dirty interleaving: after an unlock, no writer
# may consume dirty before acquiring the flag. The old implementation did an
# exchange(false) after clear(), allowing a newly active writer's notification
# to be stolen when the subsequent try-acquire failed.
clear_positions = [m.start() for m in re.finditer(r"generationWriter\.clear\(", publisher)]
exchange_position = publisher.index("generationDirty.exchange(false")
acquire_position = publisher.index("generationWriter.test_and_set")
assert (
    clear_positions and exchange_position < min(clear_positions)
), "dirty must only be consumed while holding the writer flag"
assert (
    "generationDirty.exchange(false" not in publisher[max(clear_positions):]
), "post-unlock dirty exchange reintroduces the CV-048 lost-update race"
# The lost-update shape clears dirty and then fails to acquire, returning
# without restoring it. Consume only after a successful try-acquire, and the
# failed acquire must leave dirty set for the owner or the next block.
assert acquire_position < exchange_position, "dirty consumed before the writer flag is acquired"
failed_acquire = publisher[acquire_position:exchange_position]
assert "generationDirty.store(true" in failed_acquire, "a failed acquire must preserve dirty"

for parameter_id in ids:
    assert (
        f'getRawParameterValue("{parameter_id}")->load()' in publisher
    ), f"generation omits live parameter {parameter_id}"
assert "candidate.programIndex = currentProgram.load" in publisher
assert "generationProgramIndex.store(candidate.programIndex" in publisher

preset_start = source.index("void CorvusInstrumentProcessor::setCurrentProgram")
preset_end = source.index("const juce::String CorvusInstrumentProcessor::getProgramName", preset_start)
preset = source[preset_start:preset_end]
assert "ParameterGenerationBatch batch(presetBatchSequence)" in preset
assert preset.index("currentProgram.store(index") < preset.index("publishParameterGeneration();")
assert all(
    preset.index(f'"{parameter_id}"') < preset.index("publishParameterGeneration();")
    for parameter_id in ids
)

restore_start = source.index("void CorvusInstrumentProcessor::setStateInformation")
restore_end = source.index("CorvusInstrumentProcessor::createParameterLayout", restore_start)
restore = source[restore_start:restore_end]
assert "ParameterGenerationBatch batch(presetBatchSequence)" in restore
assert "publishParameterGeneration();" in restore
assert source.count("sequence.fetch_add(1, std::memory_order_seq_cst);") >= 2

# A losing writer's dirty notification is serviced by a bounded try-acquire at
# the next audio-block boundary; processBlock itself never waits.
process_start = source.index("void CorvusInstrumentProcessor::processBlock")
process_end = source.index("juce::AudioProcessorEditor* CorvusInstrumentProcessor::createEditor", process_start)
process = source[process_start:process_end]
assert "if (generationDirty.load(std::memory_order_acquire))" in process
assert process.index("publishParameterGeneration();") < process.index(
    "readParameterGeneration(lastGoodGeneration)"
)
assert "generation.programIndex == 0" in process

# Atomic payload, bounded sequence validation, and last-good fallback.
assert "std::atomic<float> generationWave" in header
assert "std::atomic<int> generationProgramIndex" in header
reader_start = source.index("CorvusInstrumentProcessor::readParameterGeneration")
reader_end = source.index("VoiceParameters CorvusInstrumentProcessor::voiceParametersFor", reader_start)
reader = source[reader_start:reader_end]
assert re.search(r"for\s*\(int attempt = 0; attempt < 3;", reader), "reader attempts must be bounded"
assert "while" not in reader, "reader must not contain an unbounded loop"
assert "return lastGood;" in reader
assert "before == after" in reader and "(after & 1u) == 0" in reader

print("CV048 preset generation checks passed")
