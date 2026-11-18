#!/usr/bin/env python3
"""CV-033 demo stems + manifest contract check.

Pins source/DrippyFX/tools/render_corvus_demos.py, the published demo set, and
the one-command render in docs/release/offline-audio-demos.md:

  A. The set: four contrasting programs per product, each 10-20 s, at 48 kHz /
     stereo / 24-bit, with unique slugs, unique preset indices per product and
     program names that the demos README also publishes.
  B. The driver: it shells out to the built console binaries with --preset,
     --seconds, --sample-rate, --bit-depth and --out, reads every WAV back with
     its own RIFF reader, refuses existing stems/manifest without --overwrite,
     and writes manifest.json through .partial + os.replace.
  C. Live run with stub renderers: the driver produces exactly one manifest
     entry per preset and one existing WAV per entry, with a matching SHA-256
     and frame count. The stubs stand in for the built binaries - the real
     render is the operator task and stays out of CI - but the run goes through
     the driver's real subprocess, WAV verification and manifest path.

Negative probes (temp dirs and in-memory copies only, never the real tree):
  N1. 16-bit demo constant -> FAIL
  N2. 44.1 kHz demo constant -> FAIL
  N3. 1 s demo-length floor -> FAIL
  N4. non-atomic manifest write -> FAIL
  N5. no independent WAV readback -> FAIL
  N6. no --out argument to the console -> FAIL
  N7. stub renders 44.1 kHz -> driver exits non-zero, no manifest, no stem
  N8. stub fails -> driver exits non-zero, no manifest, no stem
  N9. existing stem without --overwrite -> exit 2, file untouched
Exit 0 only when the real tree passes, the live run passes and every negative
fires.
"""

import importlib.util
import json
import os
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DRIVER = ROOT / "source" / "DrippyFX" / "tools" / "render_corvus_demos.py"
CMAKE = ROOT / "source" / "DrippyFX" / "CMakeLists.txt"
DOC = ROOT / "docs" / "release" / "offline-audio-demos.md"

LABEL = "cv033-demo-manifest: "

STUB_TEMPLATE = '''\
"""Stand-in console renderer for check_cv033_demo_manifest.py."""

import argparse
import os
import struct
import sys

NAMES = {names!r}


def main():
    parser = argparse.ArgumentParser(add_help=False)
    parser.add_argument("--preset", required=True)
    parser.add_argument("--seconds", required=True)
    parser.add_argument("--sample-rate", default="48000")
    parser.add_argument("--bit-depth", default="24")
    parser.add_argument("--provenance", default="")
    parser.add_argument("--out", required=True)
    parser.add_argument("--overwrite", action="store_true")
    args, _unknown = parser.parse_known_args()

    mode = os.environ.get("CORVUS_STUB_MODE", "ok")
    if mode == "fail":
        sys.stderr.write("stub: deliberate render failure\\n")
        return 1

    rate = 44100 if mode == "wrong_rate" else 48000
    channels = 2
    width = 3
    frames = int(round(float(args.seconds) * rate))
    data_bytes = frames * channels * width

    with open(args.out, "wb") as handle:
        handle.write(b"RIFF" + struct.pack("<I", 36 + data_bytes) + b"WAVE")
        handle.write(b"fmt " + struct.pack("<IHHIIHH", 16, 1, channels, rate,
                                           rate * channels * width,
                                           channels * width, 24))
        handle.write(b"data" + struct.pack("<I", data_bytes))
        block = b"\\x00" * (channels * width * 4096)
        remaining = data_bytes
        while remaining > 0:
            piece = block[:remaining]
            handle.write(piece)
            remaining -= len(piece)

    index = str(args.preset)
    lines = [
        "product=Stub",
        "program=" + index,
        "program_name=" + NAMES.get(index, "Unknown"),
        "current_program=" + index,
        "input=stub renderer for the source-gate check",
        "sample_rate=" + str(rate),
        "channels=" + str(channels),
        "bits_per_sample=24 (PCM)",
        "block_size=512",
        "seconds=" + args.seconds,
        "frames=" + str(frames),
        "out=" + args.out,
        "provenance=" + args.provenance,
        "juce=stub",
        "wrote=" + args.out,
        "peak_dbfs=-6.00 (left=-6.00, right=-6.00)",
        "rms_dbfs=-14.00 (left=-14.00, right=-14.00)",
        "clipped_samples=0 (left=0, right=0)",
        "near_full_scale_samples=0 (left=0, right=0)",
        "readback=verified",
        "status=ok",
    ]
    sys.stdout.write("\\n".join(lines) + "\\n")
    return 0


sys.exit(main())
'''

TEXT_ANCHORS = (
    ("demo sample rate pinned at 48 kHz", "DEMO_SAMPLE_RATE = 48000"),
    ("demo layout is stereo", "DEMO_CHANNELS = 2"),
    ("demo bit depth pinned at 24-bit PCM", "DEMO_BITS_PER_SAMPLE = 24"),
    ("demo length floor is 10 s", "MIN_DEMO_SECONDS = 10.0"),
    ("demo length ceiling is 20 s", "MAX_DEMO_SECONDS = 20.0"),
    ("manifest is named manifest.json", 'MANIFEST_NAME = "manifest.json"'),
    ("console selects the program with --preset",
     '"--preset", str(stem.preset_index)'),
    ("console renders the pinned length with --seconds",
     '"--seconds", ("%g" % stem.seconds)'),
    ("console pins the sample rate", '"--sample-rate", str(DEMO_SAMPLE_RATE)'),
    ("console pins 24-bit output", '"--bit-depth", str(DEMO_BITS_PER_SAMPLE)'),
    ("console writes the named stem with --out", '"--out", str(out_path)'),
    ("driver shells out to the console", "subprocess.run("),
    ("driver drives the CorvusRenderFX console",
     '"target": "CorvusRenderFX"'),
    ("driver drives the CorvusRenderInstrument console",
     '"target": "CorvusRenderInstrument"'),
    ("driver hashes the WAV it produced", "hashlib.sha256()"),
    ("driver reads every stem back itself", "wav = inspect_wav(out_path)"),
    ("manifest is moved into place atomically",
     "os.replace(partial, manifest_path)"),
    ("existing stems are refused without --overwrite",
     "if target.exists() and not overwrite:"),
    ("program-name drift fails the run",
     "reported_program.lower() == stem.program.lower()"),
)


def read_text(path):
    return path.read_text(encoding="utf-8", errors="replace").replace(
        "\r\n", "\n").replace("\r", "\n")


def load_driver():
    """Import the driver as a module to read its published demo set."""
    spec = importlib.util.spec_from_file_location("cv033_render_driver",
                                                  str(DRIVER))
    module = importlib.util.module_from_spec(spec)
    sys.modules["cv033_render_driver"] = module
    spec.loader.exec_module(module)
    return module


def text_checks(source):
    res = []
    for label, anchor in TEXT_ANCHORS:
        res.append((label, anchor in source, anchor))
    return res


def set_checks(module):
    stems = list(module.DEMO_SET)
    res = []

    res.append(("demo set holds eight stems", len(stems) == 8,
                "count=%d" % len(stems)))

    for product in ("fx", "instrument"):
        subset = [stem for stem in stems if stem.product == product]
        res.append(("four %s stems" % product, len(subset) == 4,
                    "count=%d" % len(subset)))
        indices = {stem.preset_index for stem in subset}
        res.append(("unique %s preset indices" % product,
                    len(indices) == len(subset), "indices=%s" % sorted(indices)))
        names = {stem.program.lower() for stem in subset}
        res.append(("unique %s program names" % product,
                    len(names) == len(subset), "names=%d" % len(names)))

    slugs = [stem.slug for stem in stems]
    res.append(("stem slugs are unique", len(set(slugs)) == len(slugs),
                "slugs=%d" % len(set(slugs))))

    bad_prefix = [stem.slug for stem in stems
                  if not stem.slug.startswith("corvus-" + stem.product + "-")]
    res.append(("stem file names carry their product", not bad_prefix,
                ", ".join(bad_prefix) or "8/8"))

    out_of_band = [stem.slug for stem in stems
                   if not (10.0 <= stem.seconds <= 20.0)]
    res.append(("every stem is 10-20 s", not out_of_band,
                ", ".join(out_of_band) or "8/8"))

    res.append(("the set's own bounds match the 10-20 s band",
                module.MIN_DEMO_SECONDS == 10.0
                and module.MAX_DEMO_SECONDS == 20.0,
                "%g..%g" % (module.MIN_DEMO_SECONDS,
                            module.MAX_DEMO_SECONDS)))

    res.append(("the render format is 48 kHz / stereo / 24-bit",
                (module.DEMO_SAMPLE_RATE, module.DEMO_CHANNELS,
                 module.DEMO_BITS_PER_SAMPLE) == (48000, 2, 24),
                "%s / %s / %s" % (module.DEMO_SAMPLE_RATE,
                                  module.DEMO_CHANNELS,
                                  module.DEMO_BITS_PER_SAMPLE)))

    partial = [stem.slug for stem in stems
               if int(round(stem.seconds * module.DEMO_SAMPLE_RATE)) % 512 != 0]
    res.append(("the set exercises a partial final 512-sample block",
                bool(partial), ", ".join(partial)))

    return res


def doc_checks(doc_text, stems):
    res = []

    res.append(("demos README documents the one-command driver",
                "source/DrippyFX/tools/render_corvus_demos.py" in doc_text,
                "driver path"))
    res.append(("demos README documents --out-dir and manifest.json",
                "--out-dir" in doc_text and "manifest.json" in doc_text,
                "--out-dir / manifest.json"))
    res.append(("demos README states the 48 kHz / 24-bit stem format",
                "48 kHz" in doc_text and "24-bit" in doc_text,
                "48 kHz / 24-bit"))
    res.append(("demos README no longer claims there is no batch render",
                "multi-program batch in the tool" not in doc_text,
                "stale claim removed"))

    missing = [stem.file_name for stem in stems if stem.file_name not in doc_text]
    res.append(("demos README names every stem", not missing,
                ", ".join(missing) or "8/8"))

    missing_programs = [stem.program for stem in stems
                        if stem.program not in doc_text]
    res.append(("demos README names every program", not missing_programs,
                ", ".join(missing_programs) or "8/8"))

    return res


def run_checks(source, module, doc_text, verbose=True):
    checks = (text_checks(source) + set_checks(module)
              + doc_checks(doc_text, list(module.DEMO_SET)))
    ok = True
    for label, good, detail in checks:
        if verbose:
            print(("PASS " if good else "FAIL ") + LABEL + label
                  + " (" + detail + ")")
        ok = ok and good
    return 0 if ok else 1


def write_stubs(directory, stems):
    """Two stand-in renderers, one per product, with that product's names."""
    paths = {}
    for product in ("fx", "instrument"):
        names = {str(stem.preset_index): stem.program
                 for stem in stems if stem.product == product}
        path = directory / ("stub_" + product + ".py")
        path.write_text(STUB_TEMPLATE.format(names=names), encoding="utf-8")
        paths[product] = path
    return paths


def run_driver(out_dir, stubs, mode="ok", overwrite=False):
    env = dict(os.environ)
    env["CORVUS_STUB_MODE"] = mode
    command = [
        sys.executable, str(DRIVER),
        "--out-dir", str(out_dir),
        "--fx", str(stubs["fx"]),
        "--instrument", str(stubs["instrument"]),
        "--provenance", "checker",
    ]
    if overwrite:
        command.append("--overwrite")
    return subprocess.run(
        command, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True,
        encoding="utf-8", errors="replace", env=env)


def manifest_checks(out_dir, stems):
    res = []
    manifest_path = out_dir / "manifest.json"
    res.append(("a complete run writes manifest.json", manifest_path.is_file(),
                str(manifest_path)))

    if not manifest_path.is_file():
        return res

    try:
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    except ValueError:
        res.append(("manifest.json parses as JSON", False, "invalid JSON"))
        return res

    res.append(("manifest.json parses as JSON", True, "ok"))
    res.append(("manifest schema is pinned",
                manifest.get("schema") == "corvus-demo-manifest/1",
                str(manifest.get("schema"))))
    res.append(("manifest declares one entry per preset",
                manifest.get("stem_count") == len(stems)
                and len(manifest.get("stems", [])) == len(stems),
                "stem_count=%s entries=%s"
                % (manifest.get("stem_count"), len(manifest.get("stems", [])))))

    entries = manifest.get("stems", [])
    expected_pairs = [(stem.product, stem.preset_index) for stem in stems]
    actual_pairs = [(entry.get("product_key"), entry.get("preset_index"))
                    for entry in entries]
    res.append(("manifest keeps the demo-set order and preset coverage",
                actual_pairs == expected_pairs,
                "pairs=%s" % actual_pairs))

    missing = []
    wrong_hash = []
    wrong_format = []
    for entry, stem in zip(entries, stems):
        path = out_dir / entry.get("file", "")
        if not path.is_file():
            missing.append(str(entry.get("file")))
            continue
        digest = hashlib_sha256(path)
        if entry.get("sha256") != digest:
            wrong_hash.append(str(entry.get("file")))
        if (entry.get("sample_rate") != 48000
                or entry.get("channels") != 2
                or entry.get("bits_per_sample") != 24
                or entry.get("sample_format") != "PCM"
                or entry.get("frames")
                != int(round(stem.seconds * 48000))
                or entry.get("program") != stem.program):
            wrong_format.append(str(entry.get("file")))

    res.append(("every manifest entry has an existing WAV", not missing,
                ", ".join(missing) or "8/8"))
    res.append(("every manifest SHA-256 matches its WAV", not wrong_hash,
                ", ".join(wrong_hash) or "8/8"))
    res.append(("every entry records the pinned stem format and program",
                not wrong_format, ", ".join(wrong_format) or "8/8"))

    partial = sorted(path.name for path in out_dir.glob("*.partial"))
    res.append(("no .partial file is left behind", not partial, str(partial)))

    bad_renderers = []
    for product in ("fx", "instrument"):
        info = manifest.get("renderers", {}).get(product, {})
        executable = Path(info.get("executable", ""))
        if not executable.is_file() or info.get("sha256") != hashlib_sha256(
                executable):
            bad_renderers.append(product)
    res.append(("manifest records the executable and SHA-256 it used",
                not bad_renderers, ", ".join(bad_renderers) or "2/2"))

    return res


def hashlib_sha256(path):
    import hashlib
    digest = hashlib.sha256()
    with open(path, "rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def negative_run(out_dir, stubs, mode):
    finished = run_driver(out_dir, stubs, mode=mode)
    wavs = sorted(path.name for path in out_dir.glob("*.wav"))
    manifest = (out_dir / "manifest.json").exists()
    return [
        ("stub '" + mode + "' fails the run", finished.returncode != 0,
         "exit=" + str(finished.returncode)),
        ("stub '" + mode + "' writes no manifest", not manifest,
         "manifest.json present=%s" % manifest),
        ("stub '" + mode + "' leaves no stem behind", not wavs, str(wavs)),
    ]


def no_overwrite_probe(base_dir, stubs, stems):
    out_dir = base_dir / "existing"
    out_dir.mkdir(parents=True, exist_ok=True)
    target = out_dir / stems[0].file_name
    original = b"previous stem placeholder"
    target.write_bytes(original)

    finished = run_driver(out_dir, stubs, mode="ok")

    return [
        ("an existing stem without --overwrite exits 2",
         finished.returncode == 2, "exit=" + str(finished.returncode)),
        ("the existing stem is left untouched",
         target.read_bytes() == original, str(target.name)),
        ("no manifest is written for a refused run",
         not (out_dir / "manifest.json").exists(), "manifest.json"),
        ("no other stem is rendered for a refused run",
         sorted(path.name for path in out_dir.glob("*.wav"))
         == [stems[0].file_name], "preflight refusal"),
    ]


def main():
    for path in (DRIVER, CMAKE, DOC):
        if not path.is_file():
            print("GATE_FAIL: " + str(path) + " missing")
            return 1

    source = read_text(DRIVER)
    cmake_text = read_text(CMAKE)
    doc_text = read_text(DOC)

    try:
        module = load_driver()
    except Exception as error:  # report any import fault as a gate failure
        print("GATE_FAIL: could not import the demo driver: " + str(error))
        return 1
    stems = list(module.DEMO_SET)

    if run_checks(source, module, doc_text) != 0:
        return 1

    targets = [
        ("FX console target is still declared",
         "juce_add_console_app(CorvusRenderFX" in cmake_text),
        ("instrument console target is still declared",
         "juce_add_console_app(CorvusRenderInstrument" in cmake_text),
        ("both render targets compile the shared console source",
         cmake_text.count("tools/CorvusOfflineRender.cpp") >= 2),
    ]
    for label, good in targets:
        print(("PASS " if good else "FAIL ") + LABEL + label + " (CMake)")
        if not good:
            return 1

    for path in (ROOT / "source" / "DrippyFX" / "tools"
                 / "CorvusOfflineRender.cpp",):
        if not path.is_file():
            print("GATE_FAIL: " + str(path) + " missing")
            return 1

    # Negative probes on the driver text (in memory only).
    text_negs = [
        ("16-bit demo constant", "DEMO_BITS_PER_SAMPLE = 24",
         "DEMO_BITS_PER_SAMPLE = 16"),
        ("44.1 kHz demo constant", "DEMO_SAMPLE_RATE = 48000",
         "DEMO_SAMPLE_RATE = 44100"),
        ("1 s demo-length floor", "MIN_DEMO_SECONDS = 10.0",
         "MIN_DEMO_SECONDS = 1.0"),
        ("non-atomic manifest write", "os.replace(partial, manifest_path)",
         'manifest_path.write_text("{}")'),
        ("no independent WAV readback", "wav = inspect_wav(out_path)",
         "wav = report"),
        ("no --out argument", '"--out", str(out_path)', '"out", str(out_path)'),
    ]

    for label, old, new in text_negs:
        mutated = source.replace(old, new)
        if mutated == source:
            print("GATE_FAIL: negative '" + label + "' mutation is a no-op")
            return 1
        checks = text_checks(mutated)
        if all(good for _name, good, _detail in checks):
            print("GATE_FAIL: negative '" + label + "' did NOT fail - "
                  "checker too weak")
            return 1
        print("PASS " + LABEL + "negative rejected -> " + label)

    # Live run: the driver's own subprocess/verify/manifest path, with stubs in
    # place of the built binaries. The real render is the operator task.
    temp_root = Path(tempfile.mkdtemp(prefix="check_cv033_demo_manifest_"))
    try:
        stubs = write_stubs(temp_root, stems)

        out_dir = temp_root / "ok"
        out_dir.mkdir()
        finished = run_driver(out_dir, stubs)
        if finished.returncode != 0:
            print("GATE_FAIL: stub-backed driver run failed with exit "
                  + str(finished.returncode))
            print(finished.stdout)
            print(finished.stderr)
            return 1
        print("PASS " + LABEL + "stub-backed driver run exited 0")

        live = manifest_checks(out_dir, stems)
        for label, good, detail in live:
            print(("PASS " if good else "FAIL ") + LABEL + label
                  + " (" + detail + ")")
            if not good:
                return 1

        for mode in ("wrong_rate", "fail"):
            target_dir = temp_root / ("neg-" + mode)
            target_dir.mkdir()
            for label, good, detail in negative_run(target_dir, stubs, mode):
                print(("PASS " if good else "FAIL ") + LABEL + label
                      + " (" + detail + ")")
                if not good:
                    return 1

        for label, good, detail in no_overwrite_probe(temp_root, stubs, stems):
            print(("PASS " if good else "FAIL ") + LABEL + label
                  + " (" + detail + ")")
            if not good:
                return 1
    finally:
        shutil.rmtree(temp_root, ignore_errors=True)

    print("OK cv033 demo set pinned: 8 stems (4 per product), 10-20 s at "
          "48 kHz / stereo / 24-bit, one manifest entry and one existing WAV "
          "per preset")
    return 0


if __name__ == "__main__":
    sys.exit(main())
