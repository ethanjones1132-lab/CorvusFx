#!/usr/bin/env bash
# Portable build verification for the Corvus source tree (CV-011 / CV-T3).
#
# JUCE is not vendored in this repo, so configuring needs JUCE_PATH: either in
# the environment or as -DJUCE_PATH=<dir> on the command line. When neither is
# present this script stops with an error that names JUCE_PATH — the same
# contract source/DrippyFX/CMakeLists.txt enforces (CV-093).
#
#   JUCE_PATH=/path/to/JUCE bash scripts/verify_corvus_build.sh
#   bash scripts/verify_corvus_build.sh -DJUCE_PATH=/path/to/JUCE
#
# Extra arguments are forwarded to the CMake configure step. Override the build
# directory or configuration with CORVUS_BUILD_DIR / CORVUS_BUILD_TYPE.
set -euo pipefail

# CV-011: the checkout is this script's parent, never a literal path.
CORVUS_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"

juce_path="${JUCE_PATH:-}"
cmake_args=()
for arg in "$@"; do
    case "$arg" in
        -DJUCE_PATH=*) juce_path="${arg#-DJUCE_PATH=}" ;;
    esac
    cmake_args+=("$arg")
done

if [ -z "$juce_path" ]; then
    echo "error: JUCE_PATH is not set — point it at a JUCE 8 checkout:" >&2
    echo "  JUCE_PATH=/path/to/JUCE bash scripts/verify_corvus_build.sh" >&2
    echo "  bash scripts/verify_corvus_build.sh -DJUCE_PATH=/path/to/JUCE" >&2
    exit 2
fi

if [ ! -d "$juce_path/modules" ]; then
    echo "error: JUCE_PATH does not look like a JUCE checkout (no modules/): $juce_path" >&2
    exit 2
fi

if ! command -v cmake >/dev/null 2>&1; then
    echo "error: cmake is not on PATH — install CMake or add it to PATH" >&2
    exit 2
fi

build_dir="${CORVUS_BUILD_DIR:-$CORVUS_ROOT/build}"
build_type="${CORVUS_BUILD_TYPE:-Release}"

echo "JUCE_PATH: $juce_path"
echo "source:    $CORVUS_ROOT/source/DrippyFX"
echo "build:     $build_dir ($build_type)"

cmake -S "$CORVUS_ROOT/source/DrippyFX" -B "$build_dir" \
    -DJUCE_PATH="$juce_path" \
    -DCORVUS_COPY_PLUGIN_AFTER_BUILD=OFF \
    "${cmake_args[@]+"${cmake_args[@]}"}"

# CorvusDSPTestsRun / CorvusFXStateTestsRun are custom targets that build and
# then execute the regression executables (see source/DrippyFX/CMakeLists.txt).
cmake --build "$build_dir" --config "$build_type" --parallel \
    --target DrippyFX CorvusInstrument CorvusDSPTestsRun CorvusFXStateTestsRun

echo "BUILD_OK: VST3 targets built, CorvusDSPTestsRun and CorvusFXStateTestsRun passed"
