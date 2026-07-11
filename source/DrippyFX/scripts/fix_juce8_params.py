"""Fix AudioParameterFloat constructors for JUCE 8 API.

JUCE 8 uses a 5-arg constructor: (id, name, range, def, attributes)
The stringFromValue/valueFromString lambdas go into the attributes object,
not as separate positional arguments. The old code used a deprecated
7-arg constructor (id, name, range, def, label, category, fns).
"""

path = r'C:\Projects\Corvus VST\source\DrippyFX\PluginProcessor.cpp'

with open(path, 'rb') as f:
    text = f.read().decode('utf-8')

# Fix pctParam lambda
old_pct = '''    auto pctParam = [](const juce::String& id, const juce::String& name, float def) {
        auto range = juce::NormalisableRange<float>(0, 100, 0.1f);
        return std::make_unique<juce::AudioParameterFloat>(
            id, name, range, def, "%",
            juce::AudioParameterFloatAttributes().withLabel("%"),
            [range](float value, int) { return juce::String(value, 1) + " %"; },
            [range](const juce::String& text) { return text.replace("%", "").getFloatValue(); });
    };'''

new_pct = '''    auto pctParam = [](const juce::String& id, const juce::String& name, float def) {
        auto range = juce::NormalisableRange<float>(0, 100, 0.1f);
        return std::make_unique<juce::AudioParameterFloat>(
            id, name, range, def,
            juce::AudioParameterFloatAttributes()
                .withLabel("%")
                .withStringFromValueFunction([range](float value, int) { return juce::String(value, 1) + " %"; })
                .withValueFromStringFunction([range](const juce::String& text) { return text.replace("%", "").getFloatValue(); }));
    };'''

assert old_pct in text, "pctParam not found"
text = text.replace(old_pct, new_pct)
assert new_pct in text, "pctParam replacement failed"

# Fix hzParam lambda
old_hz = '''    auto hzParam = [](const juce::String& id, const juce::String& name, float min, float max, float def) {
        auto range = juce::NormalisableRange<float>(min, max, 0.1f);
        return std::make_unique<juce::AudioParameterFloat>(
            id, name, range, def, "Hz",
            juce::AudioParameterFloatAttributes().withLabel("Hz"),
            [range](float value, int) { return juce::String(value, 1) + " Hz"; },
            [range](const juce::String& text) { return text.replace("Hz", "").replace("hz", "").getFloatValue(); });
    };'''

new_hz = '''    auto hzParam = [](const juce::String& id, const juce::String& name, float min, float max, float def) {
        auto range = juce::NormalisableRange<float>(min, max, 0.1f);
        return std::make_unique<juce::AudioParameterFloat>(
            id, name, range, def,
            juce::AudioParameterFloatAttributes()
                .withLabel("Hz")
                .withStringFromValueFunction([range](float value, int) { return juce::String(value, 1) + " Hz"; })
                .withValueFromStringFunction([range](const juce::String& text) { return text.replace("Hz", "").replace("hz", "").getFloatValue(); }));
    };'''

assert old_hz in text, "hzParam not found"
text = text.replace(old_hz, new_hz)
assert new_hz in text, "hzParam replacement failed"

# Fix msParam lambda
old_ms = '''    auto msParam = [](const juce::String& id, const juce::String& name, float min, float max, float def) {
        auto range = juce::NormalisableRange<float>(min, max, 1.0f);
        return std::make_unique<juce::AudioParameterFloat>(
            id, name, range, def, "ms",
            juce::AudioParameterFloatAttributes().withLabel("ms"),
            [range](float value, int) { return juce::String((int)value) + " ms"; },
            [range](const juce::String& text) { return text.replace("ms", "").getFloatValue(); });
    };'''

new_ms = '''    auto msParam = [](const juce::String& id, const juce::String& name, float min, float max, float def) {
        auto range = juce::NormalisableRange<float>(min, max, 1.0f);
        return std::make_unique<juce::AudioParameterFloat>(
            id, name, range, def,
            juce::AudioParameterFloatAttributes()
                .withLabel("ms")
                .withStringFromValueFunction([range](float value, int) { return juce::String((int)value) + " ms"; })
                .withValueFromStringFunction([range](const juce::String& text) { return text.replace("ms", "").getFloatValue(); }));
    };'''

assert old_ms in text, "msParam not found"
text = text.replace(old_ms, new_ms)
assert new_ms in text, "msParam replacement failed"

with open(path, 'wb') as f:
    f.write(text.encode('utf-8'))

print("All three parameter helpers fixed for JUCE 8 API")

# Verify no corruption
with open(path, 'rb') as f:
    data = f.read()
lit_n = sum(1 for i in range(len(data)-1) if data[i:i+2] == b'\\\\n')
print(f"lit_n={lit_n}, nl_count={data.count(10)}, crlf={data.count(b'\\r\\n')}")
assert lit_n == 0, "CORRUPTION DETECTED"
print("OK")