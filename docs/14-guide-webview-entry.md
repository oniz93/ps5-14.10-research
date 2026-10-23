# No PS4, so no save exploit — the Guide WebView is the only entry left

> Written 2026-10-23. The console is a retail 14.00 unit, there is no jailbroken PS4 to
> re-sign a save, therefore the Artemis/Lua loader and mast1c0re are both unavailable
> (mast1c0re ships PS5 `libkernel` offsets only up to 6.50). This note covers the one
> attack surface that needs **no exploit at all**.

## The route

The console's User's Guide app hosts a WebView. On current firmware it fetches its shell
from `ps5.np.playstation.net` and its content from `manuals.playstation.net`. Point both
at a LAN host and it will render your page and execute your JavaScript, after the user
accepts a certificate warning on screen.

Documented and verified on a retail **14.10** by the public 14.10 research project
(`docs/BROWSER_ENTRY_INFRA_2026-10-19.md`). **Unverified on 14.00** — that is measurement
number one tomorrow.

### The five traps, all of which cost hours

| Trap | Reality |
|---|---|
| Hijacking `guides.playstation.com` | Stale. That domain is not touched any more; the shell comes from `ps5.np.playstation.net` |
| Certificates | Self-signed is accepted after an on-screen warning; no pinning observed. Put **both** hostnames in the SANs |
| URL prefix | The shell requests `/document/<lang>/ps5/src/…`. A server that only serves `/src/…` 404s every module and the page renders **black** |
| Caching | The app caches DNS *and* content hard. Reliable reload = fully close the app; after a DNS change = **Restart System**, not rest mode |
| DNS plumbing | PS5 keeps separate DNS per wired/Wi-Fi profile, and automatic IPv6 DNS bypasses your manual IPv4 DNS entirely. Turn IPv6 off while testing |

## What is already built for this

```bash
python3 tools/fw1400/guide_lab.py --mkcert                       # cert with the right SANs
sudo python3 tools/fw1400/guide_lab.py --serve --lan-ip <your-LAN-IP>
python3 tools/fw1400/guide_lab.py --report                       # summarise beacons
```

The lab serves DNS (A records for the two Sony hostnames only, everything else ignored),
HTTPS with the cert, and strips the `/document/<lang>/ps5/` prefix. Verified locally:
prefix-stripped GET → 200, unknown path → 404, beacons → 204 + JSONL, `/resume` → 302 to
the first case that started and never finished, DNS answers the two hostnames and ignores
`example.com`.

Two payload pages ship with it:

- `www/index.html` — the engine baseline battery: user agent, 30 capability probes
  (wasm, SharedArrayBuffer, WebGL/WebGL2/WebGPU, workers, service worker, IndexedDB,
  structuredClone, `Array.prototype.at`/`findLast`, `Object.hasOwn`, RegExp `d`/`v` flags,
  `Intl.Segmenter`, `Temporal`, `Error.cause`, BigInt64Array, Atomics, global property
  count, stack format, timer resolution). Every result is beaconed, so nothing depends on
  reading the screen.
- `www/runner.html` — sequential crash-case runner with the same beacon vocabulary as the
  14.10 project (`start:i` / `survived:i` / `threw:i`). A case that beacons `start` and
  never finishes took the WebProcess down: that is the only crash oracle available without
  a debugger. Drop cases in `www/cases/` and list them in `manifest.json`.

## Tomorrow's order

1. **Confirm the path exists on 14.00.** If the shell will not load after the cert warning,
   that is the whole result — record it and stop; nothing else in this note applies.
2. **Run the battery.** You get the 14.00 user agent (expect `PlayStation 5/14.00`) and the
   capability map. Compare against the 14.10 findings: no WebAssembly, no
   SharedArrayBuffer, no WebGL, `Version/17.0` in the UA, JIT disabled.
3. **Replay the three Relapse WebKit bugs** — `probes/phase13_webkit/p160-relapse-test.js`
   from the research clone. This is the decisive measurement of the day.
4. **Only if something survived**, escalate to the corpus runner and start building cases.

## What to expect, honestly

Relapse's browser stage covers **7.00–13.60**, so 14.00 almost certainly closed the
WebKit bugs too. The likely outcome of step 3 is "all three dead", which is still a real
result: it would prove 14.00 and 14.10 share the same browser posture, and it makes the
14.10 project's ~1,200 saved probe results usable as a proxy for this console.

What this route cannot do: it is a separate sandboxed process, so no syscall probing, no
kernel work, no hypervisor. It gives a *userland* primitive at best — which is exactly the
rung the save exploit would have given, minus the syscall surface.

## Running it through Pi-hole instead of the built-in DNS responder

If the PS5 already uses a Pi-hole for DNS, drop `--dns` entirely: run the lab with
`--https-only` and add two **Local DNS records** in Pi-hole (Settings → Local DNS →
DNS Records, or the equivalent in your version) pointing at the Mac:

| hostname | value |
|---|---|
| `ps5.np.playstation.net` | the Mac's LAN IP |
| `manuals.playstation.net` | the Mac's LAN IP |

Then `pihole restartdns`. Two things to check before blaming the harness:

- **Port 443.** A DNS redirect does not carry a port, so the console will always hit
  `https://<host>/`. The lab must own 443 (`sudo`, or sit behind whatever already owns
  443 and reverse-proxy to it). A server on 8443 will never be reached this way.
- **IPv6.** If the console has IPv6 DNS (router-advertised), it will bypass the Pi-hole
  for these names. Disable IPv6 on the console's network profile while testing.

If the Pi-hole currently points those names at a host serving a Relapse page, the entry
mechanism is **already proven on your console** — the only work left is swapping what
that host returns. That also answers a question this note could only guess at: Relapse's
browser stage covers 7.00–13.60, so on 14.00 the page will load and the exploit will not.
The page loading at all is the result that matters.

## The corpus, ready to run

The lab also serves the public 14.10 project's corpus contract, so their runner works
unmodified:

| route | what it serves |
|---|---|
| `/corpus/jsc.json` | manifest of harvested JavaScriptCore regression cases |
| `/corpus/<case>.html` | one self-contained case page, which beacons `BEFORE-i`, then `OK-i`/`GAP-i`, then navigates back to the runner with the next index |
| `/probe/<name>.js` | a probe, **wrapped in an HTML document** (served raw, the console renders the source as text and nothing executes) |
| `/beacon/V172-<session>-<tag>` | the beacon sink the case pages use (a GET, not a POST) |

Built and verified locally: 35 cases harvested from WebKit's JSTests crash fixes
(`harvest → jsc-resolve → jsc-fetch → jsc-build`), manifest served at 200, a case page at
200, `p172` wrapped and served at 200 as `text/html`, beacons accepted at 204, and
`--report` correctly flagging case 7 as started-but-never-finished.

Reproduce the corpus:

```bash
cd research/PS5-14.10-Research
python3 tools/webkit_crash_corpus.py jsc-harvest --pages 2   # commit search
python3 tools/webkit_crash_corpus.py jsc-resolve --limit 60   # find added tests
python3 tools/webkit_crash_corpus.py jsc-fetch  --limit 40    # download
python3 tools/webkit_crash_corpus.py jsc-build                # wrap into pages
```

Authentication: none needed. The tool drives the GitHub API through the `gh` CLI, which
is already logged in (`oniz93`, 5,000 req/h). `harvest` alone consumes ~1 call per page
of 100 commits; `resolve` is 1 call per commit.

## The other door, for completeness

A used PS4 on ≤11.00 is the only way to reach the syscall probes: it unlocks Apollo, which
re-signs a modified Artemis save for the PS5. That is the purchase the whole 14.10
methodology assumes. Everything in `12-console-day-plan.md` §3 becomes available the day
one is in the house; until then it is not a plan, it is a wish.
