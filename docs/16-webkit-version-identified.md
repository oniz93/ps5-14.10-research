# Which WebKit is on the console — answered exactly

**`616.1.27.211.1`** — the Safari 17.0 GA cut of 2023-09-18, unchanged from firmware
12.00 through 14.x. Not inferred: read out of the source Sony publishes for that
firmware range.

## How it is known

Sony publishes the source of the open-source code in PS5 system software, **filed by
system-software version**:

- WebKit — <https://www.playstation.com/en-us/oss/ps5/webkit/>
- JavaScriptCore — <https://www.playstation.com/en-us/oss/ps5/webkit-javascriptcore/>

The firmware range is the **anchor text**, the archive is the **href**. The console-relevant
rows:

| Firmware range | archive |
|---|---|
| 12.00 – 14.00 | `WebKit-1200.zip` |
| **14.00 –** | **`WebKit_1400.zip`** (1.64 GB, 414,182 members, published 2026-10-15) |

Reading `Configurations/Version.xcconfig` out of both:

```
MAJOR_VERSION = 616;   MINOR_VERSION = 1;   TINY_VERSION = 27;   MICRO_VERSION = 211;   NANO_VERSION = 1;
```

Identical in both drops. Three independent cross-checks agree:

- browser-compat-data maps Safari 17 (2023-09-18) to engine **616.1.27**;
- Apple's own `safari.plist` carries `NewestLaunchedSafariBookmarksSyncAgentVersion =
  616.1.27.211.1` — the same build seed, not just the same major;
- the console's UA on 14.10 says `Version/17.0`.

The separate **JSC drop is stale** and must not be used: `JSC-800.zip` ("8.00 –")
declares `613.1.17.1.14`, an early-2023 engine, and its root `ChangeLog` ends
**2022-01-09**. The UA matches 616.x, so `WebKit_1400` is the tree that corresponds to
retail.

## Reading a 1.6 GB zip without downloading it

`tools/fw1400/remote_zip.py` reads the central directory with HTTP range requests and
then fetches only the member's byte span:

```bash
U=https://www.playstation.com/content/dam/global_pdc/en-us/external-resources/oss/PS5/webkit/WebKit_1400.zip
python3 tools/fw1400/remote_zip.py "$U" --list 'Version\.xcconfig'
python3 tools/fw1400/remote_zip.py "$U" --read 'WebKit-1400/WebKit-1400/Source/JavaScriptCore/runtime/JSScope.cpp'
python3 tools/fw1400/remote_zip.py "$U" --grep 'structuredClone' --name 'JSTests/.*\.js'
```

Works on ZIP64, 414k members, single files of 200 KB in a couple of seconds. Confirmed
reachable for `JSCell.cpp`, `JSObject.cpp`, `JSScope.cpp`, `JSTests/**`.

## What this changes

**1. The engine is three years stale.** 616.1.27 is from September 2023, still shipping
in 2026 firmware. Every WebKit security fix landed after that cut is a candidate for
this console. That is a *target list*, not a guarantee — Sony cherry-picks.

**2. The version number no longer answers "is it patched".** Apple bumps the micro/seed
for security releases (616.1.28, .29 …); Sony froze the string at .211.1 across
12.00 → 14.x. So patch status cannot be inferred from the number, and a PoC crash is no
longer the only oracle.

**3. Patch triage becomes a source question.** For any candidate fix:

- take the upstream WebKit commit that fixes it;
- fetch the corresponding file from `WebKit_1400.zip` with `remote_zip.py`;
- check whether the fixed hunk is present in Sony's tree.

Absent → plausible live bug → worth a PoC on the console. Present → drop it, no console
time spent. This inverts the workflow that produced 1,100 probes and no kernel access in
the public 14.10 project.

**4. Calibration is already available.** The three Relapse bugs were measured as dead on
hardware (`docs/15`); the corresponding fixes must therefore be present in this tree.
Verifying that is the correct first audit: it tests the method against three known
answers before trusting it on unknowns.

## Caveats

- The drop is per **firmware range**, published after the fact (`WebKit_1400` appeared
  2026-10-15, two weeks after 14.10 shipped). It describes the 14.x engine family, not
  provably the exact bytes on a given console.
- It is a compliance drop: build configuration may differ from retail. Features the
  console reports as absent (wasm, WebGL, service workers) should be checked in
  `Source/cmake/OptionsPlayStation.cmake` before assuming the tree matches the binary.
- It is source, not symbols: layouts and offsets still need a dump. What it removes is
  the guessing about *which* bugs exist, not the need for memory disclosure.

## Files

| path | what |
|---|---|
| `data/webkit-oss-map.json` | firmware → archive map, versions, sizes, cross-checks |
| `tools/fw1400/remote_zip.py` | remote ZIP reader (range requests, ZIP64) |
