#!/usr/bin/env python3
"""Render every Corvus demo stem, plus its manifest, in one command (CV-033).

The two headless consoles built from ``tools/CorvusOfflineRender.cpp`` render
one program per run through the real product processors. This driver only
loops the documented demo set below, checks every written WAV with a small
RIFF reader of its own, and writes ``manifest.json`` next to the stems.

It compiles no DSP, imports no product code and touches no parameter: every
sample still comes from the product's own ``processBlock`` reached through
``setCurrentProgram()`` by the console tool.

Usage (from the repository root):

    python3 source/DrippyFX/tools/render_corvus_demos.py \\
        --build-dir build/corvus-render \\
        --out-dir C:/Projects/ops/ship/corvus/demos

Format contract for every stem: 48 kHz, stereo, 24-bit PCM WAV, 10-20 s long.
Levels are the product's own factory-program gain - this driver never
normalises, trims or fades. The consoles synthesise their input from a fixed
formula (no PRNG, no seed, no user file), so re-running the same binary with
the same arguments is the reproducibility check that matters.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import struct
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[3]

DEMO_SAMPLE_RATE = 48000
DEMO_CHANNELS = 2
DEMO_BITS_PER_SAMPLE = 24
MIN_DEMO_SECONDS = 10.0
MAX_DEMO_SECONDS = 20.0

MANIFEST_NAME = "manifest.json"
MANIFEST_SCHEMA = "corvus-demo-manifest/1"

PRODUCTS = {
    "fx": {
        "label": "Corvus FX",
        "target": "CorvusRenderFX",
        "env": "CORVUS_RENDER_FX",
    },
    "instrument": {
        "label": "Corvus Instrument",
        "target": "CorvusRenderInstrument",
        "env": "CORVUS_RENDER_INSTRUMENT",
    },
}


@dataclass(frozen=True)
class DemoStem:
    """One stem in the published demo set."""

    product: str
    preset_index: int
    program: str
    slug: str
    seconds: float

    @property
    def file_name(self) -> str:
        return self.slug + ".wav"

    @property
    def label(self) -> str:
        return PRODUCTS[self.product]["label"]


# The published demo set: four contrasting factory programs per product. Every
# program name is re-checked against the built binary's own getProgramName()
# roster, so a roster rename fails the run instead of silently rendering some
# other program. Change this table and docs/release/offline-audio-demos.md
# together, never one alone.
DEMO_SET = (
    DemoStem("fx", 0, "Clean Sparkle", "corvus-fx-00-clean-sparkle", 11.5),
    DemoStem("fx", 8, "Thick Sauce", "corvus-fx-08-thick-sauce", 11.5),
    DemoStem("fx", 13, "Cosmic Wide", "corvus-fx-13-cosmic-wide", 11.5),
    DemoStem("fx", 21, "Event Horizon", "corvus-fx-21-event-horizon", 11.5),
    DemoStem("instrument", 0, "Dawn Choir", "corvus-instrument-00-dawn-choir", 11.5),
    DemoStem("instrument", 1, "Raven Glass", "corvus-instrument-01-raven-glass", 11.5),
    DemoStem("instrument", 2, "Ashen Sky", "corvus-instrument-02-ashen-sky", 11.5),
    DemoStem("instrument", 4, "Cathedral Drift",
             "corvus-instrument-04-cathedral-drift", 15.5),
)

NUMBER_RE = re.compile(r"[-+]?(?:\d+\.\d*|\.\d+|\d+)(?:[eE][-+]?\d+)?")
FORMAT_NAMES = {1: "PCM", 3: "IEEE float"}


class DemoError(Exception):
    """A demo run that must not produce stems or a manifest."""


def expected_frames(seconds: float) -> int:
    return int(round(seconds * DEMO_SAMPLE_RATE))


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with open(path, "rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def number(value):
    """First finite number in a report value, or None."""
    if value is None:
        return None
    match = NUMBER_RE.search(value)
    if match is None:
        return None
    try:
        parsed = float(match.group(0))
    except ValueError:
        return None
    if parsed != parsed or parsed in (float("inf"), float("-inf")):
        return None
    return parsed


def parse_report(text: str):
    """Parse the console tool's key=value report; the last value wins."""
    report = {}
    for line in text.splitlines():
        key, separator, value = line.partition("=")
        if not separator:
            continue
        key = key.strip()
        if key and " " not in key:
            report[key] = value.strip()
    return report


def inspect_wav(path: Path):
    """Read a WAV's own header, so the stem is checked without the renderer.

    Handles plain PCM and WAVE_FORMAT_EXTENSIBLE, and does not depend on the
    Python version's wave module having picked up extensible support.
    """
    with open(path, "rb") as handle:
        header = handle.read(12)
        if len(header) != 12 or header[0:4] != b"RIFF" or header[8:12] != b"WAVE":
            raise DemoError("not a RIFF/WAVE file: " + str(path))

        fmt = None
        data_bytes = None
        data_offset = 0

        while True:
            chunk_header = handle.read(8)
            if len(chunk_header) != 8:
                break

            chunk_id, chunk_size = struct.unpack("<4sI", chunk_header)

            if chunk_id == b"fmt ":
                fmt = handle.read(chunk_size)
                pad = chunk_size % 2
            elif chunk_id == b"data":
                data_offset = handle.tell()
                data_bytes = chunk_size
                if data_bytes == 0 or data_bytes == 0xFFFFFFFF:
                    data_bytes = max(0, path.stat().st_size - data_offset)
                break
            else:
                handle.seek(chunk_size, os.SEEK_CUR)
                pad = chunk_size % 2

            if pad:
                handle.seek(1, os.SEEK_CUR)

    if fmt is None or len(fmt) < 16:
        raise DemoError("no usable fmt chunk: " + str(path))

    format_tag, channels, sample_rate, _rate, _align, bits = struct.unpack(
        "<HHIIHH", fmt[0:16])

    if format_tag == 0xFFFE and len(fmt) >= 26:
        format_tag = struct.unpack("<H", fmt[24:26])[0]

    if data_bytes is None:
        raise DemoError("no data chunk: " + str(path))

    if data_bytes > path.stat().st_size - data_offset:
        raise DemoError("data chunk is truncated: " + str(path))

    bytes_per_sample = max(1, (bits + 7) // 8)
    frames = data_bytes // (channels * bytes_per_sample) if channels else 0

    return {
        "channels": channels,
        "sample_rate": sample_rate,
        "bits_per_sample": bits,
        "sample_format": FORMAT_NAMES.get(format_tag, "tag " + str(format_tag)),
        "data_bytes": data_bytes,
        "frames": frames,
    }


def find_binary(product: str, explicit, build_dirs):
    """Resolve the built console binary for one product."""
    if explicit:
        candidate = Path(explicit).expanduser()
        if not candidate.is_file():
            raise DemoError("renderer not found: " + str(candidate))
        return candidate.resolve()

    from_env = os.environ.get(PRODUCTS[product]["env"])
    if from_env:
        candidate = Path(from_env).expanduser()
        if not candidate.is_file():
            raise DemoError(PRODUCTS[product]["env"] + " is not a file: "
                            + str(candidate))
        return candidate.resolve()

    target = PRODUCTS[product]["target"]
    candidates = []
    for directory in build_dirs:
        if not directory.is_dir():
            continue
        for name in (target, target + ".exe", target + ".py"):
            candidates.extend(directory.rglob(name))

    def rank(candidate):
        lowered = [part.lower() for part in candidate.parts]
        release = 0 if "release" in lowered else 1
        try:
            stamp = candidate.stat().st_mtime
        except OSError:
            stamp = 0.0
        return (release, -stamp)

    if not candidates:
        searched = ", ".join(str(directory) for directory in build_dirs)
        raise DemoError("could not find " + target + " under " + searched
                        + "; pass --fx/--instrument or --build-dir")

    return sorted(candidates, key=rank)[0].resolve()


def render_command(binary: Path, arguments):
    """Command line for a built console binary, or for a .py stand-in.

    The .py form exists for the source-only checker, which substitutes a stub
    renderer for the product build. A published stem is rendered by the real
    binary; the manifest records which executable and SHA-256 produced it.
    """
    if binary.suffix.lower() == ".py":
        return [sys.executable, str(binary)] + arguments
    return [str(binary)] + arguments


def preflight(stems, out_dir: Path, overwrite: bool):
    """Every path a run would touch, checked before any render starts."""
    problems = []

    for stem in stems:
        target = out_dir / stem.file_name
        partial = out_dir / (stem.file_name + ".partial")
        if target.exists() and not overwrite:
            problems.append("refusing to overwrite existing stem (pass "
                            "--overwrite): " + str(target))
        if partial.exists() and not overwrite:
            problems.append("refusing to replace a stale partial file (pass "
                            "--overwrite): " + str(partial))

    manifest = out_dir / MANIFEST_NAME
    if manifest.exists() and not overwrite:
        problems.append("refusing to overwrite existing manifest (pass "
                        "--overwrite): " + str(manifest))

    return problems


def require(condition, message):
    if not condition:
        raise DemoError(message)


def render_stem(stem: DemoStem, binary: Path, out_dir: Path,
                overwrite: bool, provenance: str):
    """Render, verify and describe one stem."""
    out_path = out_dir / stem.file_name
    frames = expected_frames(stem.seconds)

    arguments = [
        "--preset", str(stem.preset_index),
        "--seconds", ("%g" % stem.seconds),
        "--sample-rate", str(DEMO_SAMPLE_RATE),
        "--bit-depth", str(DEMO_BITS_PER_SAMPLE),
        "--provenance", provenance,
        "--out", str(out_path),
    ]
    if overwrite:
        arguments.append("--overwrite")

    finished = subprocess.run(
        render_command(binary, arguments),
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        encoding="utf-8",
        errors="replace",
    )

    report = parse_report(finished.stdout)

    if finished.returncode != 0:
        detail = (finished.stderr.strip() or finished.stdout.strip()
                  or "(no output)")
        raise DemoError(stem.file_name + ": renderer exited "
                        + str(finished.returncode) + ":\n" + detail)

    where = stem.file_name + ": "

    require(report.get("status") == "ok",
            where + "the renderer did not report status=ok")
    require(report.get("readback") == "verified",
            where + "the renderer did not report readback=verified")
    require(report.get("current_program") == str(stem.preset_index),
            where + "program did not take effect (current_program="
            + str(report.get("current_program")) + ")")
    require(number(report.get("sample_rate")) == DEMO_SAMPLE_RATE,
            where + "renderer sample rate is "
            + str(report.get("sample_rate")))
    require(number(report.get("channels")) == DEMO_CHANNELS,
            where + "renderer channel count is " + str(report.get("channels")))
    require(number(report.get("bits_per_sample")) == DEMO_BITS_PER_SAMPLE,
            where + "renderer bit depth is " + str(report.get("bits_per_sample")))
    require(number(report.get("frames")) == frames,
            where + "renderer frame count is " + str(report.get("frames"))
            + ", expected " + str(frames))

    reported_program = (report.get("program_name") or "").strip()
    require(reported_program.lower() == stem.program.lower(),
            where + "roster drift: preset " + str(stem.preset_index)
            + " is now '" + reported_program + "', the demo set says '"
            + stem.program + "' - update DEMO_SET and "
              "docs/release/offline-audio-demos.md together")

    require(out_path.is_file(), where + "the renderer reported success but "
                                       "wrote no WAV at " + str(out_path))

    wav = inspect_wav(out_path)

    require(wav["channels"] == DEMO_CHANNELS,
            where + "WAV has " + str(wav["channels"]) + " channels")
    require(wav["sample_rate"] == DEMO_SAMPLE_RATE,
            where + "WAV is " + str(wav["sample_rate"]) + " Hz")
    require(wav["bits_per_sample"] == DEMO_BITS_PER_SAMPLE,
            where + "WAV is " + str(wav["bits_per_sample"]) + "-bit")
    require(wav["sample_format"] == "PCM",
            where + "WAV sample format is " + wav["sample_format"])
    require(wav["frames"] == frames,
            where + "WAV holds " + str(wav["frames"]) + " frames, expected "
            + str(frames))

    peak = number(report.get("peak_dbfs"))
    rms = number(report.get("rms_dbfs"))
    require(peak is not None and peak > -120.0,
            where + "reported peak " + str(report.get("peak_dbfs"))
            + " dBFS is silent or unreadable")
    require(rms is not None,
            where + "reported rms " + str(report.get("rms_dbfs"))
            + " dBFS is unreadable")

    entry = {
        "file": stem.file_name,
        "product": stem.label,
        "product_key": stem.product,
        "preset_index": stem.preset_index,
        "program": reported_program,
        "seconds": stem.seconds,
        "frames": frames,
        "sample_rate": wav["sample_rate"],
        "channels": wav["channels"],
        "bits_per_sample": wav["bits_per_sample"],
        "sample_format": wav["sample_format"],
        "bytes": out_path.stat().st_size,
        "sha256": sha256_file(out_path),
        "peak_dbfs": peak,
        "rms_dbfs": rms,
        "clipped_samples": int(number(report.get("clipped_samples")) or 0),
        "near_full_scale_samples":
            int(number(report.get("near_full_scale_samples")) or 0),
        "status": report.get("status"),
        "readback": report.get("readback"),
        "input": report.get("input", ""),
        "report": report,
    }

    residual = out_dir / (stem.file_name + ".partial")
    require(not residual.exists(),
            where + "a .partial file was left behind: " + str(residual))

    return entry


def git_provenance():
    """(revision, dirty) from the worktree, or (None, None) without git."""
    try:
        revision = subprocess.run(
            ["git", "rev-parse", "HEAD"],
            cwd=str(REPO_ROOT), stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL, text=True, encoding="utf-8",
            errors="replace")
        if revision.returncode != 0:
            return None, None
        status = subprocess.run(
            ["git", "status", "--porcelain"],
            cwd=str(REPO_ROOT), stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL, text=True, encoding="utf-8",
            errors="replace")
    except OSError:
        return None, None

    revision_text = revision.stdout.strip() or None
    dirty = None if status.returncode != 0 else bool(status.stdout.strip())
    return revision_text, dirty


def build_parser():
    parser = argparse.ArgumentParser(
        description="Render the documented Corvus demo stems and manifest.")
    parser.add_argument(
        "--out-dir", default=str(REPO_ROOT / "build" / "corvus-demos"),
        help="directory for the stems and manifest.json (created if missing); "
             "default: <repo>/build/corvus-demos")
    parser.add_argument(
        "--build-dir", action="append", default=[],
        help="CMake build directory to search for the render consoles "
             "(repeatable; default: <repo>/build/corvus-render then "
             "<repo>/build)")
    parser.add_argument(
        "--fx", default=None, help="explicit path to CorvusRenderFX")
    parser.add_argument(
        "--instrument", default=None,
        help="explicit path to CorvusRenderInstrument")
    parser.add_argument(
        "--provenance", default=None,
        help="provenance text for the reports; default: git rev-parse HEAD")
    parser.add_argument(
        "--overwrite", action="store_true",
        help="replace existing stems, manifest and stale .partial files")
    parser.add_argument(
        "--list-set", action="store_true",
        help="print the demo set and exit without rendering")
    return parser


def print_set(stems):
    print("product\tpreset\tprogram\tfile\tseconds\tframes")
    for stem in stems:
        print("%s\t%d\t%s\t%s\t%g\t%d"
              % (stem.product, stem.preset_index, stem.program,
                 stem.file_name, stem.seconds, expected_frames(stem.seconds)))


def run(args):
    stems = DEMO_SET

    for stem in stems:
        require(0 <= stem.preset_index,
                stem.file_name + ": preset index must not be negative")
        require(MIN_DEMO_SECONDS <= stem.seconds <= MAX_DEMO_SECONDS,
                stem.file_name + ": " + ("%g" % stem.seconds)
                + " s is outside the " + ("%g" % MIN_DEMO_SECONDS) + "-"
                + ("%g" % MAX_DEMO_SECONDS) + " s demo range")

    if args.list_set:
        print_set(stems)
        return 0

    out_dir = Path(args.out_dir).expanduser().resolve()

    build_dirs = [Path(directory).expanduser().resolve()
                  for directory in args.build_dir]
    if not build_dirs:
        preferred = REPO_ROOT / "build" / "corvus-render"
        build_dirs = [preferred] if preferred.is_dir() else [REPO_ROOT / "build"]

    binaries = {
        "fx": find_binary("fx", args.fx, build_dirs),
        "instrument": find_binary("instrument", args.instrument, build_dirs),
    }

    stand_ins = [product for product in ("fx", "instrument")
                 if binaries[product].suffix.lower() == ".py"]
    if stand_ins:
        print("warning: using a stand-in renderer for " + ", ".join(stand_ins)
              + "; the manifest records stand_in=true for it", file=sys.stderr)

    revision, dirty = git_provenance()
    if args.provenance:
        provenance, provenance_source = args.provenance, "supplied"
    elif revision:
        provenance, provenance_source = revision, "git rev-parse HEAD"
    else:
        provenance, provenance_source = "unknown", "unavailable"

    if dirty:
        print("warning: the worktree has uncommitted changes; record "
              "'git status --short' with the stems", file=sys.stderr)

    try:
        out_dir.mkdir(parents=True, exist_ok=True)
    except OSError as error:
        raise DemoError("could not create " + str(out_dir) + ": " + str(error))

    problems = preflight(stems, out_dir, args.overwrite)
    if problems:
        for problem in problems:
            print("error: " + problem, file=sys.stderr)
        return 2

    existed_before = {stem.file_name: (out_dir / stem.file_name).exists()
                      for stem in stems}
    entries = []

    try:
        for index, stem in enumerate(stems, start=1):
            print("[%d/%d] %s preset %d '%s' -> %s"
                  % (index, len(stems), stem.label, stem.preset_index,
                     stem.program, stem.file_name), flush=True)
            entry = render_stem(stem, binaries[stem.product], out_dir,
                                args.overwrite, provenance)
            entries.append(entry)
            print("        %d frames, %.1f s, peak %.2f dBFS, rms %.2f dBFS, "
                  "sha256=%s"
                  % (entry["frames"], entry["seconds"], entry["peak_dbfs"],
                     entry["rms_dbfs"], entry["sha256"][:16]), flush=True)
    except (DemoError, OSError) as error:
        for stem in stems:
            if existed_before.get(stem.file_name):
                continue
            created = out_dir / stem.file_name
            if created.is_file():
                try:
                    created.unlink()
                except OSError:
                    pass
        raise DemoError(str(error) + "\nno manifest was written; stems this "
                                    "run created were removed")

    manifest = {
        "schema": MANIFEST_SCHEMA,
        "driver": "source/DrippyFX/tools/render_corvus_demos.py",
        "repo_commit": revision,
        "provenance": provenance,
        "provenance_source": provenance_source,
        "repo_dirty": dirty,
        "format": {
            "container": "WAV",
            "sample_rate": DEMO_SAMPLE_RATE,
            "channels": DEMO_CHANNELS,
            "bits_per_sample": DEMO_BITS_PER_SAMPLE,
            "sample_format": "PCM",
        },
        "normalisation": "none; levels are the product's own program gain",
        "input": "procedural in the console tool; no PRNG, seed or input file",
        "renderers": {
            product: {
                "target": PRODUCTS[product]["target"],
                "executable": str(binaries[product]),
                "sha256": sha256_file(binaries[product]),
                "stand_in": binaries[product].suffix.lower() == ".py",
            }
            for product in ("fx", "instrument")
        },
        "stem_count": len(entries),
        "stems": entries,
    }

    manifest_path = out_dir / MANIFEST_NAME
    partial = out_dir / (MANIFEST_NAME + ".partial")
    try:
        with open(partial, "w", encoding="utf-8", newline="\n") as handle:
            json.dump(manifest, handle, indent=2)
            handle.write("\n")
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(partial, manifest_path)
    except OSError as error:
        if partial.is_file():
            try:
                partial.unlink()
            except OSError:
                pass
        raise DemoError("could not write " + str(manifest_path) + ": "
                        + str(error))

    total_bytes = sum(entry["bytes"] for entry in entries)
    print()
    print("wrote %d stems and %s" % (len(entries), manifest_path))
    print("product mix: %d Corvus FX, %d Corvus Instrument"
          % (sum(1 for stem in stems if stem.product == "fx"),
             sum(1 for stem in stems if stem.product == "instrument")))
    print("format: %d Hz / %d ch / %d-bit PCM, %d bytes total"
          % (DEMO_SAMPLE_RATE, DEMO_CHANNELS, DEMO_BITS_PER_SAMPLE,
             total_bytes))
    print("provenance: " + provenance)
    print("status: ok")
    return 0


def main(argv=None):
    parser = build_parser()
    args = parser.parse_args(argv)
    try:
        return run(args)
    except DemoError as error:
        print("error: " + str(error), file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
