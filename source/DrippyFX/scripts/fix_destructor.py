"""Fix 'void' return type on destructor (C2577). Also need to check levelMeters access."""
import sys

path = r'C:\Projects\Corvus VST\source\DrippyFX\PluginEditor.cpp'
with open(path, 'rb') as f:
    text = f.read()

# Fix 1: void ~CorvusFXAudioProcessorEditor -> ~CorvusFXAudioProcessorEditor (destructors can't have return type)
old = b'void CorvusFXAudioProcessorEditor::~CorvusFXAudioProcessorEditor()'
new = b'CorvusFXAudioProcessorEditor::~CorvusFXAudioProcessorEditor()'
count = text.count(old)
print(f"Found {count} occurrences of 'void ~CorvusFX...'")
text = text.replace(old, new)
assert text.count(old) == 0, "Failed to fix void destructor"

with open(path, 'wb') as f:
    f.write(text)

print("Fixed void destructor")