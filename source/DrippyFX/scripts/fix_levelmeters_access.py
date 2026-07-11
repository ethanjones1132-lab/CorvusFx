"""Make levelMeters public by inserting public: before the struct.
The struct currently sits under private: section. Need to inject public: before it.
"""
import sys

path = r'C:\Projects\Corvus VST\source\DrippyFX\PluginProcessor.h'
with open(path, 'rb') as f:
    text = f.read()

# The string before LevelMeters: "...atomic floats. No locks needed <emdash> relaxed atomics...\n    // for meter display...\n    struct LevelMeters"
# We need to insert 'public:\n' before '    struct LevelMeters'
old = b'    struct LevelMeters'
new = b'public:\n    struct LevelMeters'
text = text.replace(old, new, 1)

with open(path, 'wb') as f:
    f.write(text)

# Verify
with open(path, 'rb') as f:
    verify = f.read()
idx = verify.find(b'public:\n    struct LevelMeters')
assert idx > 0, "public: not inserted"
print(f"OK: public: inserted at byte {idx}")