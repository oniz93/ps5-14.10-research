#!/bin/bash
# Build Sony's own JavaScriptCore - interpreter only, with AddressSanitizer.
#
# The retail port sets ENABLE_JIT/DFG_JIT/FTL_JIT OFF and the console confirmed it with
# the timing oracle, so a bug we find has to reproduce without an optimising tier. That
# makes a local ASAN build of the *shipped* tree the right instrument: same source as the
# console, sanitizer instead of guesswork.
#
#   ./build_jsc_asan.sh [jobs]
#
# Result lands in out/sony/full/WebKit-1400/WebKit-1400/WebKitBuild/Debug/jsc
set -u

TREE="${TREE:-$HOME/Documents/ps5-bootchain/out/sony/full/WebKit-1400/WebKit-1400}"
JOBS="${1:-4}"
LOG="$HOME/Documents/ps5-bootchain/out/jsc-build.log"

# WebKit 616 predates CMake 4's stricter if() parsing; pin a 3.27 if we have one.
PINNED="$(cd "$(dirname "$0")/../.." && pwd)/out/tools/cmake-3.27.9-macos-universal/CMake.app/Contents/bin"
if [ -x "$PINNED/cmake" ]; then
    export PATH="$PINNED:$PATH"
    echo "cmake: $("$PINNED/cmake" --version | head -1)"
fi

cd "$TREE" || { echo "tree not found: $TREE"; exit 1; }

echo "tree : $TREE"
echo "jobs : $JOBS"
echo "log  : $LOG"

# CMake initialises CMAKE_C_FLAGS/CMAKE_CXX_FLAGS from the environment, which is the
# only clean way to inject several flags at once here (build-jsc splits --cmakeargs on
# spaces). clang 21 also needs -Wno-error for 2023-era code.
export CFLAGS="-fsanitize=address -Wno-error"
export CXXFLAGS="-fsanitize=address -Wno-error -Wno-invalid-offsetof -Wno-deprecated-declarations"
echo "cxxflags: $CXXFLAGS"

# -j keeps the machine usable; WebKit's scripts pass through to make/ninja.
"$TREE/Tools/Scripts/build-jsc" \
    --jsc-only \
    --debug \
    --no-ftl-jit \
    --makeargs="-j$JOBS" \
    --cmakeargs="-DENABLE_JIT=OFF \
                 -DENABLE_DFG_JIT=OFF \
                 -DENABLE_FTL_JIT=OFF \
                 -DENABLE_WEBASSEMBLY=OFF \
                 -DCMAKE_COMPILE_WARNING_AS_ERROR=OFF \
                 -DCMAKE_EXE_LINKER_FLAGS=-fsanitize=address" \
    2>&1 | tee "$LOG"
