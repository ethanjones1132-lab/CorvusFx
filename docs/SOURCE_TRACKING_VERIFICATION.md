# Source tracking verification (task t_b97d4512)

Date: 2026-07-08

## Baseline (before this change)

```text
git ls-tree -r HEAD --name-only | grep -E '\.(cpp|h|hpp|c)$'
# (empty — no C/C++ sources at HEAD before import)
```

```text
git log --all --diff-filter=D --summary -- '*.cpp' '*.h' '*.hpp'
# (empty — sources were never tracked, not deleted from history)
```

Tracked paths were binaries + docs only (`drippy/.../DrippyMk1.vst3`, `DrippyMk2/...`, scripts, docs).

## Actions taken

1. Imported authoritative JUCE sources from the local MSBuild tree into `source/DrippyFX/` (synced from `Downloads/.../DrippyFX/` at import time; matches deployed `DrippyMk1` era including chorus dry/wet cache in `PluginProcessor.h`).
2. Updated `docs/AGENTS.md`, `README.md`, `docs/PRIORITIES.md`, `.gitignore`, and maintenance scripts to treat `source/DrippyFX/` as git SoT and require source+binary `quality(...)` commits going forward.
3. Confirmed `.hermes/` is ignored and fleet state was removed from the index in commit `0faffac`.

## Post-import checks (run after commit)

```bash
cd "C:/Projects/Corvus VST"
git ls-tree -r HEAD --name-only | grep -E '\.(cpp|h|hpp|c)$'
# Expect: source/DrippyFX/PluginProcessor.{h,cpp}, PluginEditor.{h,cpp}

git ls-files .hermes
# Expect: (empty)

git log --oneline -3 --stat
```

## Commit hygiene (forward)

Per `docs/AGENTS.md` rule 1: any `quality(scope):` commit that touches `DrippyMk1.vst3` must include matching `source/DrippyFX/` diffs. Historical binary-only quality commits are not rewritten (out of scope).