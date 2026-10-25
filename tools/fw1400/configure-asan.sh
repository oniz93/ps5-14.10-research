export CCACHE_DIR=$HOME/.ccache
export CCACHE_MAXSIZE=20G

# RelWithDebInfo flags carry -DNDEBUG in WebKit's defaults. Do not drop it: without NDEBUG,
# ASSERT_ENABLED becomes 1 and the tree compiles assert-only code that has never been built
# (SerializedScriptValue.cpp:1015 passes an undeclared inMemoryMessagePorts, and :5028 uses a
# DetachedImageBitmap type that is not defined under this feature set). The retail WebProcess is a
# release build with assertions compiled out, so NDEBUG is also the faithful configuration.
cmake -S . -B WebKitBuild/ASAN -G Ninja \
  -DPORT=GTK \
  -DCMAKE_BUILD_TYPE=RelWithDebInfo \
  -DCMAKE_CXX_FLAGS_RELWITHDEBINFO="-O1 -g -DNDEBUG" \
  -DCMAKE_C_FLAGS_RELWITHDEBINFO="-O1 -g -DNDEBUG" \
  -DCMAKE_C_COMPILER_LAUNCHER=ccache -DCMAKE_CXX_COMPILER_LAUNCHER=ccache \
  -DUSE_SYSTEM_MALLOC=ON \
  -DENABLE_SANITIZERS=address -DENABLE_JIT=OFF -DENABLE_DFG_JIT=OFF -DENABLE_FTL_JIT=OFF \
  -DENABLE_MEDIA_STREAM=OFF \
  -DENABLE_WEBDRIVER=OFF -DENABLE_SPELLCHECK=OFF -DENABLE_GAMEPAD=OFF -DENABLE_GEOLOCATION=OFF \
  -DENABLE_INTROSPECTION=OFF -DENABLE_DOCUMENTATION=OFF -DENABLE_WAYLAND_TARGET=OFF \
  -DENABLE_VIDEO=ON -DENABLE_BUBBLEWRAP_SANDBOX=OFF \
  -DENABLE_WEB_AUDIO=ON \
  -DENABLE_WEBGL=OFF
# WEB_AUDIO must stay ON (the default). With VIDEO on and GStreamer, platform/audio/gstreamer/
# FFTFrameGStreamer.cpp compiles regardless and calls VectorMath::multiplyByScalar plus the
# gst_fft_* API, but GStreamer.cmake only supplies those two dependencies inside
# if (ENABLE_WEB_AUDIO). Turning the API off therefore breaks the link, and patching around it by
# hand fails because this tree builds the WebCore target through a macro rather than add_library.
# The cost is an AudioContext surface the console lacks; the DOM/CSS/style code we fuzz is
# unaffected, and Web Audio is simply not exercised by the harness.
# WEBGL=OFF for two reasons. It matches the retail console, whose build flags in
# OptionsPlayStation.cmake turn WebGL and GPU_PROCESS off, so our WebProcess carries the same
# feature set rather than extra paths the target does not have. And it drops ANGLE, which does not
# build under ASAN here: SharedContextMutex.cpp's always_inline recursion makes GCC 13 fail with
# "inlining failed ... recursive inlining" - a sanitizer interaction, not a bug in the source.
