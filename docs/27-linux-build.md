# Building Sony's WebKit on a Linux board

How the macOS build fight was abandoned and replaced with a working Linux one. Host: AMD
BC-250 board (the PS5 APU with no Sony secure boot), Bazzite 43 Kinoite, 6 cores / 12 threads,
8 GB RAM, 32 GB swap, 124 GB free.

## Why not just finish the macOS build

It died at bmalloc's TAPI-filelist step after seven separate Xcode-27 incompatibilities. None of
them exist on Linux: no Metal toolchain, no Apple SDK churn, no `_LIBCPP_ENABLE_ASSERTIONS`
removal, no stripped executable bits in a zip-supplied tree.

## The board's real numbers

The host was described as 6 cores / 16 GB. It is **12 threads and 7.5 GiB usable** — memory,
not CPU, is the constraint. Consequences, all of which are baked into the commands below:

- `-j3`, not `-j12`. Each unified-source TU peaks 1.5–3 GB; `-j6` would OOM-thrash.
- 32 GB swap was already present, which is what makes `-j3` survivable.
- ccache is enabled from the first build, so a failure costs minutes to resume, not hours.

## Environment

Bazzite is Fedora Atomic (`rpm-ostree`, no `dnf` on the host). Everything therefore lives in a
**distrobox container**, which is user-space and needs no root on the host:

```bash
distrobox create -n wk --image registry.fedoraproject.org/fedora:39 --yes
```

Fedora 39 is deliberate — GCC 13, the same era as the 2023 WebKit snapshot being built.

Dependencies (Fedora names, the ones that actually mattered):

```
cmake ninja-build gcc gcc-c++ ccache python3 python3-devel ruby rubygem-json gettext gperf
bison flex unifdef glib2-devel gobject-introspection-devel zlib-devel libicu-devel
libxml2-devel libxslt-devel sqlite-devel libjpeg-turbo-devel libpng-devel libwebp-devel
libavif-devel libjxl-devel openjpeg2-devel lcms2-devel freetype-devel fontconfig-devel
harfbuzz-devel cairo-devel cairo-gobject-devel pango-devel gtk3-devel libsoup3-devel
libepoxy-devel libgcrypt-devel libtasn1-devel openssl-devel libX11-devel libXcomposite-devel
libXdamage-devel libXext-devel libXfixes-devel libXrender-devel libXt-devel libXrandr-devel
libxkbcommon-devel wayland-devel mesa-libGL-devel mesa-libEGL-devel woff2-devel systemd-devel
brotli-devel libpsl-devel libidn2-devel libnghttp2-devel xorg-x11-server-Xvfb
```

## Configure

```bash
cmake -S . -B WebKitBuild/Release -G Ninja \
  -DPORT=GTK -DCMAKE_BUILD_TYPE=Release \
  -DCMAKE_C_COMPILER_LAUNCHER=ccache -DCMAKE_CXX_COMPILER_LAUNCHER=ccache \
  -DUSE_SYSTEM_MALLOC=ON \
  -DENABLE_JIT=OFF -DENABLE_DFG_JIT=OFF -DENABLE_FTL_JIT=OFF \
  -DENABLE_WEBDRIVER=OFF -DENABLE_INTROSPECTION=OFF -DENABLE_DOCUMENTATION=OFF \
  -DENABLE_WAYLAND_TARGET=OFF -DENABLE_VIDEO=ON -DENABLE_WEB_AUDIO=OFF \
  -DENABLE_BUBBLEWRAP_SANDBOX=OFF -DENABLE_SPELLCHECK=OFF -DENABLE_GAMEPAD=OFF
```

`ENABLE_JIT=OFF` is not a shortcut, it is the point: the console's engine is interpreter-only,
so a JIT-enabled build would be a different engine from the one being studied. It also removes
a large share of JSC's compile time.

Then `ninja -C WebKitBuild/Release -j3 MiniBrowser` — 5464 edges.

## Errors hit, and what each one actually meant

| error | fix |
|---|---|
| `ENABLE_INTROSPECTION is needed for gi-docgen` | `-DENABLE_INTROSPECTION=OFF -DENABLE_DOCUMENTATION=OFF` |
| `libwpe is required for ENABLE_WAYLAND_TARGET` | `-DENABLE_WAYLAND_TARGET=OFF` |
| `libjxl is required for USE_JPEGXL` | `dnf install libjxl-devel` |
| `libopenjpeg 2.2.0 is required for USE_OPENJPEG` | `dnf install openjpeg2-devel` |
| `libcms2 is required for USE_LCMS` | `dnf install lcms2-devel` |
| `libseccomp is needed for ENABLE_BUBBLEWRAP_SANDBOX` | `-DENABLE_BUBBLEWRAP_SANDBOX=OFF` |
| `cannot load such file -- json (LoadError)` in the bytecode generator | `dnf install rubygem-json` — Fedora ships Ruby's stdlib as separate gems |
| `invalid use of incomplete type 'HTMLVideoElement'` in `GPUExternalTextureDescriptor.h` | `-DENABLE_VIDEO=ON` — see below |

Each one is a configure-time gate, so this list is the whole cost of standing the build up.

Two traps worth spelling out, both of which cost a rebuild each:

- **`-DENABLE_VIDEO=OFF` does not work.** `Modules/WebGPU/GPUExternalTextureDescriptor.h`
  calls `videoSource->playerIdentifier()` on an `HTMLVideoElement*` that `Document.h` only
  forward-declares when video is compiled out. WebGPU has no feature flag of its own in this
  tree — passing `-DENABLE_WEBGPU=OFF` is silently ignored and CMake lists it under "unused
  variables" — so video must stay on. Fedora's `gstreamer1-devel`,
  `gstreamer1-plugins-base-devel` and `gstreamer1-plugins-bad-free-devel` are the cost.
- **CMake caches feature flags.** Removing `-DENABLE_VIDEO=OFF` from the command line leaves
  the cached `OFF` in force; the flag has to be set to `ON` explicitly, not merely dropped.

## Running a page headlessly

The board has no display, so MiniBrowser runs under a virtual X server:

```bash
Xvfb :99 -screen 0 1920x1080x24 &
DISPLAY=:99 MiniBrowser --automation-mode file:///home/<user>/wk/pages/style-scope-upstream.html
```

## The open question this build exists to answer

Whether bug 260896 and bug 272882 fire at all on a genuinely unpatched build. Everything
tested so far ran on the console, where "Sony fixed it differently" and "my reproducer never
triggered" are indistinguishable. A local build separates them:

- **crashes locally** → the reproducers are sound and the console's clean runs are real evidence
  of a different fix.
- **does not crash locally either** → both probes are wrong and the console results mean nothing.

Note for whoever runs this next: a **Release build will not reliably catch a use-after-free** —
the freed memory often still reads as valid. The verdict needs an ASAN build. Expect a second
full build tree for it; plan the disk accordingly.
