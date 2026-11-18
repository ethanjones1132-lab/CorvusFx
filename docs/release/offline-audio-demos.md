# Corvus offline demo renders (CV-033)

Status: **source tool and operator instructions only.** This document does not
contain rendered WAVs, a listening pass, waveform measurements, or a release
claim. One command (below) renders every stem and writes `manifest.json`; the
stems themselves must be produced from the native binaries by the
reviewer/operator on the machine that holds the build tree, then added to
`ops/ship/corvus/demos/` with the evidence recorded below.

## What the tool is

`CorvusRenderFX` and `CorvusRenderInstrument` are two console executables. They
share one main (`source/DrippyFX/tools/CorvusOfflineRender.cpp`) but each links
exactly one real product processor and its `createPluginFilter` factory:

| Executable | Processor | Input |
| --- | --- | --- |
| `CorvusRenderFX` | `CorvusFXAudioProcessor` | original deterministic procedural tone/transient bed |
| `CorvusRenderInstrument` | `CorvusInstrumentProcessor` | original deterministic bounded MIDI chord phrase |

The render goes through the product's actual `AudioProcessor::processBlock`
path and its public `setCurrentProgram()` / `getProgramName()` interface. No
DSP is copied into the tool, and no synthetic stand-in is used.

The console targets are not the plug-in targets. `product=` is the tool's own
label. The tool also prints the processor's own `getName()` as
`processor_name=`: because these console targets do not define JUCE's
`JucePlugin_Name`, the FX processor falls back to its compiled-in
`"CorvusFX"` string. That fallback is not the v1.0 host-visible product name;
do not quote `processor_name=` as release identity evidence.

Render contract:

- Stereo WAV, 512-sample blocks; the final block is shortened to the exact
  remaining sample count, so non-block-aligned lengths are exercised.
- Default output is 48000 Hz, 24-bit PCM. `--sample-rate <hz>` selects another
  rate the WAV writer supports (8000-192000; 44100/48000/96000/192000 are the
  usual choices), and `--bit-depth 32` writes IEEE 32-bit float instead of
  24-bit PCM.
- `--seconds` is bounded to 0.25 through 30.0 (default 6.0).
- `--preset` accepts a program name or a program index. An all-digit value is
  read as an index, so existing scripted calls keep working. Either form is
  resolved against the binary's own `getProgramName()` roster and applied with
  `setCurrentProgram()`, the same program path a host uses.
- `prepareToPlay()` and `releaseResources()` bracket the render, at the
  requested sample rate.
- No audio device, DAW, microphone, user-supplied audio file, window, network,
  provider or model is used. The input is generated inside the tool.

Output honesty:

- The WAV is written to `<out>.partial`. It is reopened and checked for
  channels, sample rate, bit depth, float/integer sample format and exact frame
  count before it is moved to `<out>`.
- A non-finite output sample fails the render. It is never replaced with
  silence, and the temporary file is deleted.
- A 100% silent render fails the render.
- Samples outside `[-1.0, +1.0]` are counted and reported. 24-bit PCM cannot
  represent them; a 32-bit float file can, but playback or a later integer
  stage may still clip, so the warning is reported either way. The tool does
  not change the product's gain to hide clipping.
- An existing `<out>` file is refused unless `--overwrite` is passed.
- An invalid argument, an invalid output path, or a stale `.partial` file is
  refused with exit code 2.

Exit codes: `0` success, `1` render/writer/verification failure, `2` usage
error or output-path precondition.

## Build only the render targets

Prerequisites: the JUCE SDK checkout used by this project (JUCE 8.0.12),
CMake, a C++17 compiler, and the repository source. The existing CMake options
and targets are unchanged. `CORVUS_COPY_PLUGIN_AFTER_BUILD` stays off; these
commands do not copy anything to a system plug-in directory.

From the repository root, in PowerShell (substitute the actual JUCE path for
`<JUCE_PATH>`):

```powershell
cmake -S source/DrippyFX -B build/corvus-render `
  -DJUCE_PATH="<JUCE_PATH>" `
  -DCORVUS_COPY_PLUGIN_AFTER_BUILD=OFF

cmake --build build/corvus-render --config Release `
  --target CorvusRenderFX CorvusRenderInstrument
```

The executables are under `build/corvus-render/<target>_artefacts/<config>/`
(for example `build/corvus-render/CorvusRenderFX_artefacts/Release/CorvusRenderFX.exe`
for a Release build with a multi-config generator). Use the generator and
configuration that match the machine.

For a single-config generator, configure with
`-DCMAKE_BUILD_TYPE=Release` and omit `--config Release` from the build
command. In bash, replace the backtick line continuations with backslashes;
the same CMake flags apply. For a Visual Studio generator, add `-A x64` (and
the matching `-G`) so these targets use the same 64-bit platform as the product
build. macOS ARM builds still need the SSE compatibility include path described
in `AGENTS.md`; this change does not alter that setup.

Windows sync note: `scripts/sync_corvus_source.ps1` uses an explicit file map
that does not yet list `tools/CorvusOfflineRender.cpp` or
`tools/render_corvus_demos.py`. If the Windows build relies on that script,
copy both tool files explicitly or extend the map in a separate change; do not
build the render targets from a tree that is missing either file. Building the
clean default tree used by the reviewer needs no sync step.

The normal verification gate still applies: the reviewer must build the new
targets **plus** the existing targets required by `AGENTS.md` (`DrippyFX`,
`CorvusInstrument`, `CorvusDSPTests`, `CorvusFXStateTests`), run both test
executables, and keep `bash scripts/verify_corvus_source.sh` green. Building
the two render targets alone is only the demo-render step.

## Program roster: four contrasting programs per product

Use `--list-presets` for the authoritative roster of the binary you built.
At the time of writing the FX roster has 36 programs and the instrument roster
has 5; the four programs below are contrasting choices from that roster, not a
replacement for the list. The same eight choices, with their render lengths,
are pinned in `source/DrippyFX/tools/render_corvus_demos.py` as `DEMO_SET`; the
driver fails the whole run if the built binary reports a different program name
for one of those indices, so a roster rename is reported instead of silently
rendering some other sound.

### Corvus FX

| Index | Program | Character for a demo |
| --- | --- | --- |
| 0 | Clean Sparkle | subtle widening and air; near-clean reference |
| 8 | Thick Sauce | heavy saturation and chorus thickening |
| 13 | Cosmic Wide | modulation-forward, maximum stereo width |
| 21 | Event Horizon | long delay and heavy feedback into a large reverb |

### Corvus Instrument

| Index | Program | Character for a demo |
| --- | --- | --- |
| 0 | Dawn Choir | slow triangle pad, long release |
| 1 | Raven Glass | short square pluck, short release (best note-off check) |
| 2 | Ashen Sky | saw wave, long sustain and release |
| 4 | Cathedral Drift | very slow attack and long release |

Program names and indices come from the current product rosters. If
`--list-presets` disagrees with this table, the binary wins; record the
disagreement instead of renaming anything.

The driver and the one-off commands pass indices. `--preset "Clean Sparkle"` is
equivalent to `--preset 0`: a non-numeric value is matched case-insensitively
against the same roster, and an unknown or ambiguous name exits with code 2
instead of falling back to program 0. Quote names that contain spaces.

## Render every stem in one command

`source/DrippyFX/tools/render_corvus_demos.py` drives both consoles through the
eight-program set above and writes `manifest.json` beside the stems. It is a
stdlib-only Python 3 script: it shells out to the built binaries, checks each
WAV header with its own RIFF reader, and never imports, rebuilds or copies the
product DSP.

```bash
python3 source/DrippyFX/tools/render_corvus_demos.py \
  --build-dir build/corvus-render \
  --out-dir C:/Projects/ops/ship/corvus/demos
```

On Windows the same line works as
`py -3 source/DrippyFX/tools/render_corvus_demos.py ...`. `--out-dir` defaults
to `build/corvus-demos` (already gitignored), so stems never land in the
tracked tree by accident. `--build-dir` is searched for `CorvusRenderFX` and
`CorvusRenderInstrument` (Release artefacts preferred, then the newest match);
pass `--fx <path>` and `--instrument <path>` to name the executables
explicitly, or set `CORVUS_RENDER_FX` / `CORVUS_RENDER_INSTRUMENT`.
`--list-set` prints the pinned set, its file names, durations and frame counts
without rendering.

Before it renders anything the driver checks every output path: an existing
stem, an existing `manifest.json` or a stale `.partial` file is refused unless
`--overwrite` is passed, so a second run cannot silently replace evidence.
During the run it stops at the first failure, removes the stems that run
created, and writes no manifest. A success prints one line per stem, then a
summary ending in `status: ok`; only a complete run writes the manifest (to
`manifest.json.partial`, then moved into place).

`--provenance` defaults to `git rev-parse HEAD` and is echoed in both the
console reports and the manifest; the driver also records whether the worktree
was dirty. Render lengths are 11.5 s for seven stems (552000 frames, a partial
final block of 64 samples) and 15.5 s for Cathedral Drift (744000 frames, also a
partial final block of 64 samples) so its long release is not cut off. Every
stem is inside the 10-20 s demo band, 48 kHz, stereo, 24-bit PCM, and none is
normalised: the level of each stem is the product's own factory-program gain.
The consoles synthesise their input from a fixed formula, so there is no PRNG,
seed or input file to pin - the same binary and the same arguments are the
reproducibility check.

The console tool still renders one program per run. A single one-off stem can
be produced directly with `--preset`, `--seconds` and `--out`; the driver runs
exactly that command once per entry below.

Each console run prints the product, program, exact frame/sample counts,
duration, peak and RMS (linear and dBFS), clipping count,
**near_full_scale_samples** (samples at or above 0.99 linear magnitude per
channel, including clipped samples), provenance and `status=ok`. The driver
keeps that stdout in each stem's `report` object in the manifest.

The **near_full_scale_samples** metric counts float samples whose absolute magnitude is at least 0.99, including samples also counted as clipped. It quantifies how often the signal approaches or exceeds 0 dBFS; a count of zero does not imply silence, so use the existing peak and RMS measurements to assess signal level.

## Manifest

`manifest.json` is written by the driver and is the authoritative record. Do
not retype it and do not fill it from this document. It carries:

- `schema` (`corvus-demo-manifest/1`), `driver`, `repo_commit`, `provenance`,
  `provenance_source`, `repo_dirty`, `normalisation` and `input`.
- `format`: WAV, 48000 Hz, 2 channels, 24-bit PCM.
- `renderers`: both target names, their executable paths and their SHA-256.
- `stem_count`, and `stems`: one entry per preset in `DEMO_SET` order, each
  with `file`, `product`, `preset_index`, `program`, `seconds`, `frames`,
  `sample_rate`, `channels`, `bits_per_sample`, `sample_format`, `bytes`,
  `sha256`, `peak_dbfs`, `rms_dbfs`, `clipped_samples`,
  `near_full_scale_samples`, `status`, `readback`, `input` and the console
  tool's raw `report` key/values.

The pinned, deterministic part of the set (the driver fails if the built
binary reports a different program name for one of these indices):

| File | Product | Preset | Program | Seconds | Frames |
| --- | --- | --- | --- | --- | --- |
| `corvus-fx-00-clean-sparkle.wav` | Corvus FX | 0 | Clean Sparkle | 11.5 | 552000 |
| `corvus-fx-08-thick-sauce.wav` | Corvus FX | 8 | Thick Sauce | 11.5 | 552000 |
| `corvus-fx-13-cosmic-wide.wav` | Corvus FX | 13 | Cosmic Wide | 11.5 | 552000 |
| `corvus-fx-21-event-horizon.wav` | Corvus FX | 21 | Event Horizon | 11.5 | 552000 |
| `corvus-instrument-00-dawn-choir.wav` | Corvus Instrument | 0 | Dawn Choir | 11.5 | 552000 |
| `corvus-instrument-01-raven-glass.wav` | Corvus Instrument | 1 | Raven Glass | 11.5 | 552000 |
| `corvus-instrument-02-ashen-sky.wav` | Corvus Instrument | 2 | Ashen Sky | 11.5 | 552000 |
| `corvus-instrument-04-cathedral-drift.wav` | Corvus Instrument | 4 | Cathedral Drift | 15.5 | 744000 |

Per-stem format, byte count, peak/RMS, clipping, near-full-scale counts and
SHA-256 come from `manifest.json`; copy them from there when the release notes
or the README need a table. Also record the source/build provenance:

| Item | Value |
| --- | --- |
| Git commit (`repo_commit`) | from `manifest.json` |
| Worktree status (`repo_dirty`) | from `manifest.json` |
| JUCE version (tool prints `juce=`) | from each stem's `report` |
| CMake generator / compiler / config | to record |
| Configure and build commands | to record |
| SHA-256 of `CorvusRenderFX` binary | from `manifest.json` `renderers` |
| SHA-256 of `CorvusRenderInstrument` binary | from `manifest.json` `renderers` |
| SHA-256 of every stem | from `manifest.json` `stems[].sha256` |

`--provenance <text>` is echoed verbatim in the tool report and the manifest.
The tool cannot verify that a string is the real revision; `repo_commit` is
recorded from `git rev-parse HEAD` by the driver, and `provenance_source` says
whether that was the default or a supplied string.

The renderer owns the real processor on the heap. Its fixed DSP buffers exceed
the default Windows console stack; --help and --list-presets are startup
regressions as well as usage checks.

## Verification checklist

Run these checks against the actual native binaries. Source checks alone do
not close CV-033.

### 1. WAV duration, format and non-silence

The driver has already checked every stem's header, frame count, byte size and
SHA-256 against `manifest.json`; this helper adds peak/RMS and window
measurements. Save it outside the repository (for example as `check_demos.py`)
and run it on each stem. It is a verification aid, not part of the shipped tool
and not a new tool dependency.

```python
import hashlib, math, sys, wave

def read_wav(path):
    with wave.open(path, "rb") as w:
        info = dict(channels=w.getnchannels(), rate=w.getframerate(),
                    sampwidth=w.getsampwidth(), frames=w.getnframes(),
                    comptype=w.getcomptype())
        raw = w.readframes(info["frames"])
    assert info["channels"] == 2, info
    assert info["rate"] == 48000, info
    assert info["sampwidth"] == 3, info          # 24-bit PCM
    assert info["comptype"] == "NONE", info
    assert len(raw) == info["frames"] * 6, (len(raw), info["frames"])
    samples = [int.from_bytes(raw[i:i + 3], "little", signed=True) / 8388608.0
               for i in range(0, len(raw), 3)]
    return info, samples

def rms(values):
    return math.sqrt(sum(v * v for v in values) / len(values)) if values else 0.0

def window(samples, t0, t1):
    return samples[int(t0 * 48000) * 2:int(t1 * 48000) * 2]

args = sys.argv[1:]
win = None
if "--window" in args:
    i = args.index("--window")
    win = (float(args[i + 1]), float(args[i + 2]))
    del args[i:i + 3]
assert 1 <= len(args) <= 2, "usage: check_demos.py A.wav [B.wav] [--window t0 t1]"

data = []
for path in args:
    info, samples = read_wav(path)
    assert any(v != 0.0 for v in samples), "silent file: " + path
    peak = max(abs(v) for v in samples)
    print(path)
    print("  format", info)
    print("  peak", round(peak, 8), "rms", round(rms(samples), 8))
    print("  sha256", hashlib.sha256(open(path, "rb").read()).hexdigest())
    if win:
        print("  window", win, "rms", round(rms(window(samples, *win)), 8))
    data.append(samples)

if len(data) == 2:
    assert len(data[0]) == len(data[1]), "length mismatch"
    print("difference_rms", round(rms([a - b for a, b in zip(*data)]), 8))
```

Python 3.12 or newer is recommended: its `wave` module accepts both plain PCM
and WAVE_FORMAT_EXTENSIBLE PCM headers, so the format check does not depend on
which header variant the writer emitted.

Required outcomes for every stem (these assume the commands above, which keep
the 48000 Hz / 24-bit PCM defaults; if a stem is rendered with `--sample-rate`
or `--bit-depth 32`, change the helper's expected values and record the actual
format instead):

- `format` shows 2 channels, 48000 Hz, 3-byte samples, uncompressed PCM
  (`comptype == "NONE"`), and `frames == round(seconds * 48000)`.
- `peak > 0` and `rms > 0`; a 24-bit integer PCM file is finite by construction.
  For a `--bit-depth 32` float file, the tool's own finite check covers the
  float samples before writing, but the helper reads float samples directly and
  should be extended before a float stem is used as evidence.
- The tool report says `readback=verified` and `status=ok`, and its `frames`,
  `samples_per_channel` and `duration_seconds` match the file.

### 2. Distinguish two genuinely different FX programs

Render program 8 (Thick Sauce) and program 21 (Event Horizon) with identical
flags and compare:

```powershell
python check_demos.py C:\Projects\ops\ship\corvus\demos\corvus-fx-08-thick-sauce.wav `
  C:\Projects\ops\ship\corvus\demos\corvus-fx-21-event-horizon.wav
```

The two files must not be byte-identical (different `sha256`) and the
`difference_rms` must be clearly non-zero: the programs have very different
gain, modulation and delay/reverb settings. If the files are identical, or
`difference_rms` is zero to the printed precision, the real `processBlock`
path is bypassed or the program selection did not take effect; treat that as a
failure, not as a valid demo. Also compare the peak/RMS lines from the tool
reports.

As a separate reproducibility observation, render the same program twice into
two filenames and compare hashes. Record the result honestly. Deterministic
input does not by itself guarantee bit-identical output: the tool adds no
random source, but the products are free to have their own state, and
floating-point/SIMD/build differences can still change low bits. Do not claim a
seed guarantee.

### 3. Instrument note-on / note-off and tail

Use program 1 (Raven Glass, release 1.4 s) and the 11.5 s render. The MIDI
phrase is four triads: note-on at 0.0, 1.2, 2.4 and 3.6 s; note-off at 0.6,
1.8, 3.0 and 4.2 s; the rest is release tail.

```powershell
python check_demos.py C:\Projects\ops\ship\corvus\demos\corvus-instrument-01-raven-glass.wav `
  --window 0.10 0.50
python check_demos.py C:\Projects\ops\ship\corvus\demos\corvus-instrument-01-raven-glass.wav `
  --window 0.70 1.10
python check_demos.py C:\Projects\ops\ship\corvus\demos\corvus-instrument-01-raven-glass.wav `
  --window 4.50 5.50
```

Expected outcomes to record (each is a check, not a measured result of this
source patch):

- The first note window should be non-silent, showing note-on produced audio.
- The gap window after the first note-off (0.70-1.10 s) should have lower RMS
  than the first note window. If it does not, record both values and treat it
  as a note-off routing finding rather than accepting the file.
- The tail window after the final note-off (4.50-5.50 s) should be lower than
  the sustained chord windows. It may still be non-silent because Raven Glass
  has a 1.4 s release; record the value rather than forcing zero.
- Audio should start immediately after 0.0 s; if the first note is delayed by
  a block, the event scheduling or block boundary is wrong.

### 4. Negative argument, path and no-overwrite checks

Run these against the built binaries. The negative rows are expected to fail
with the stated exit code and must not create or replace a WAV; the first three
rows are success checks.

| Command | Expected |
| --- | --- |
| `CorvusRenderFX --list-presets` | exit 0; prints product and each index/name |
| `CorvusRenderInstrument --list-presets` | exit 0; prints the instrument roster |
| `CorvusRenderFX --help` | exit 0; prints usage |
| `CorvusRenderFX --preset 35` (no `--out`) | exit 2 |
| `CorvusRenderFX --out x.wav` (no `--preset`) | exit 2 |
| `CorvusRenderFX --preset 999 --out x.wav` | exit 2; out-of-range index |
| `CorvusRenderFX --preset "No Such Program" --out x.wav` | exit 2; unknown name |
| `CorvusRenderFX --preset 0 --out x.wav --seconds 0` | exit 2 |
| `CorvusRenderFX --preset 0 --out x.wav --seconds 30.1` | exit 2 |
| `CorvusRenderFX --preset 0 --out x.wav --seconds nan` | exit 2 |
| `CorvusRenderFX --preset 0 --out x.wav --sample-rate 12345` | exit 2; not a WAV rate |
| `CorvusRenderFX --preset 0 --out x.wav --sample-rate 0` | exit 2 |
| `CorvusRenderFX --preset 0 --out x.wav --bit-depth 16` | exit 2 |
| `CorvusRenderFX --preset 0 --out x.wav --bogus` | exit 2 |
| `CorvusRenderFX --preset 0 --out C:\no-such-dir\x.wav` | exit 2; parent missing |
| `CorvusRenderFX --preset 0 --out C:\temp\x.txt` | exit 2; not `.wav` |
| `CorvusRenderFX --preset 0 --out .` | exit 2; directory |
| Render to an existing file without `--overwrite` | exit 2; existing file unchanged (compare hash) |
| Render to an existing file with `--overwrite` | exit 0; file replaced |
| Render when `<out>.partial` already exists, without `--overwrite` | exit 2; stale partial untouched |
| The same stale-partial run with `--overwrite` | exit 0; `.partial` replaced and moved into place |
| A valid render that hits a writer failure (for example a full disk) | exit 1; no new `<out>` file kept, `.partial` cleanup attempted |

Also check that a failed render does not delete an unrelated existing file and
that `--overwrite` only affects the named output and its `.partial`.

## Limits and honest claims

- Default output is 48 kHz, stereo, 24-bit PCM. `--sample-rate` and
  `--bit-depth 32` (IEEE float) change that; there is still no resampling,
  dither or mono mode. 24-bit PCM cannot carry samples above 0 dBFS, so the
  tool reports `clipped_samples` and warns; it does not lower the product's
  gain.
- Render length is bounded to 0.25-30 s, and the console tool renders one
  program per run. The documented demo set is looped by
  `source/DrippyFX/tools/render_corvus_demos.py`, which renders one console run
  per entry and writes the manifest; there is still no automation, parameter
  sweep or MIDI file input.
- `--fx` and `--instrument` also accept a `.py` stand-in so the source gate can
  exercise the driver without a product build. The manifest records
  `stand_in: true` for such a renderer; a published stem must come from the
  real `CorvusRenderFX` / `CorvusRenderInstrument` binary, and the manifest
  records that binary's path and SHA-256.
- The FX input is a synthetic tone/transient bed, not a song. The instrument
  input is a fixed four-chord phrase; renders shorter than the phrase truncate
  it, so use at least ~4.5 s to hear the last note-off and tail.
- No output fades are applied. Files end at the requested sample count to
  preserve the real render, so a stem can end on a non-zero sample.
- Both products' `processBlock` implementations already fold non-finite
  values to zero internally (existing product behavior): the instrument at its
  output stage and the FX processor at its chain input and final store. The
  tool checks what the product outputs; it cannot see a value the product
  discarded inside itself. A render that is silent because of an upstream
  product fault still fails the tool's all-silent check rather than being
  presented as a valid demo.
- The printed peak/RMS are measured on the float block the product produced,
  before 24-bit PCM quantisation. A value recomputed from the WAV can differ by
  the final quantisation step.
- Deterministic input does not imply bit-identical output across builds,
  compilers, CPU feature sets or floating-point settings. The render targets
  use the same product source and the same explicit MSVC `/fp:fast /arch:AVX2`
  options as the product targets, but they do not link the products'
  recommended LTO flags, so do not expect bit-identical output to the shipped
  plug-in. The tool adds no random source and invents no seed guarantee.
  Same-binary repeat renders are the relevant reproducibility check; record
  any differences.
- This patch adds the two CMake console targets, the shared tool source, the
  demo-set driver (stems plus manifest) and this document. It does not render
  stems, listen to them, measure the real waveforms, tag a release, or publish
  anything. The reviewer/operator phase must build the native targets, run the
  one-command render, check the stems, and keep `manifest.json` as the evidence.
