# Guide WebView on 14.10 — working recipe and first results

> Session of 2026-10-23. Console: `CFI-…`, firmware **26.06-14.10.00.03** (`14.10`), IP
> `<console-ip>`. Host: Mac mini, `<host-ip>`. Everything below was executed on
> hardware; nothing here is inferred from the public write-ups.

## The setup that actually works

```
Mac:  sudo python3 tools/fw1400/guide_lab.py --serve --lan-ip <host-ip>
PS5:  Settings → Network → <profile> → Advanced → DNS Settings → Manual
      Primary DNS = <host-ip>        (secondary 0.0.0.0)
      then close and reopen the User's Guide, accept the certificate warning
```

The lab answers DNS for `ps5.np.playstation.net` and `manuals.playstation.net` and
**forwards every other name to the Pi-hole** (`--upstream <resolver-ip>`). That
forwarding is not a detail: without it the guide cannot fetch its own config from
`envelope*.np.dl.playstation.net` and renders nothing.

### The six failure modes hit tonight, in the order they cost time

| Symptom | Cause | Fix |
|---|---|---|
| White page, timeout, **zero** packets at the host | Primary DNS typed `<host-ip>` instead of `192.…` | read the setting back off the screen, digit by digit |
| DNS answered but the page stayed blank | responder ignored non-hijacked names → config fetch failed | forward unmatched queries upstream |
| `SSLError: TLSV1_ALERT_UNKNOWN_CA` on most connections, then success | the guide opens parallel connections and only some are validated strictly; retries succeed | ignore — it is normal, not a fault |
| Nothing at all in the request log | TLS failures happen before any handler runs, so they are invisible | log at accept time (`TLSError` capture in `conn.jsonl`) |
| `certificate unknown` from a client | bare self-signed leaf rejected outright | serve a private-CA leaf + chain |
| Pi-hole returns the right record, console still fails | per-profile DNS + IPv6 bypass | this is why the console's own resolver is used, not the Pi-hole |

A DNS redirect carries no port: the client always requests `:443`, so the lab must own
443 (hence `sudo`).

## Result 1 — the entry works, and the engine is cut down hard

User agent:

```
Mozilla/5.0 (PlayStation; PlayStation 5/14.10) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.0 Safari/605.1.15
```

30-probe capability map, with an iPhone on the same page as control
(`data/webview-baseline-1410.json`):

| probe | PS5 14.10 | phone |
|---|---|---|
| `wasm`, `webgl`, `webgl2`, `webgpu` | **all false** | true |
| service worker, IndexedDB, OffscreenCanvas, AudioWorklet | **all false** | true |
| SharedArrayBuffer | false | false |
| workers, Atomics, structuredClone, RegExp `d`/`v`, `Intl.Segmenter` | true | true |
| `globalThis` properties | **754** | 1059 |
| `Intl` timezone | **`Etc/Unknown`** | America/Vancouver |
| viewport / dpr | 1540×810 / 1 | 980×1673 / 3 |

Origin confirmed by the stack trace: `https://manuals.playstation.net/document/en/ps5/`.
This independently reproduces the public project's finding (no WASM/SAB/WebGL) from a
different harness on a different console.

## Result 2 — all three Relapse WebKit bugs are dead

`p160-relapse-test.js` beacons (`data/p160-relapse-1410.json`):

```
V160-BOOT
V160-P1-SCOPE-UNDEF              ← super.foo returned undefined, no JSScope leaked
V160-P2-STUFFED
V160-P2-SYMOBJ-type=object       ← Symbol.toString gave an object, not a pointer string
V160-P3-START
V160-P3-DEDUP-YES                ← structuredClone dedupe present
V160-P3-CLONE-len=65536
V160-P3-STILL-SAME               ← no type confusion
V160-DONE
```

Phase 1, 2 and 3 all fail safe. The 2023-era browser chain cannot be rebuilt on 14.10.

## Result 3 — 35 post-cut JSC crash regressions, no crash

Corpus: `harvest → jsc-resolve → jsc-fetch → jsc-build` over WebKit's `JSTests` crash
fixes landed after the Safari 17.0 branch; 35 usable pages served at `/corpus/jsc.json`
and driven by `p172-jsc-corpus-runner.js`, one document per case.

```
BOOT-35-from-0-to-35 … 35 × (BEFORE-n → OK-n → GAP-n) … BATCH-END-34
cases started 35, cases finished 35, started-but-never-finished []
```

**What this does and does not show.** It shows none of the 35 take the WebProcess down
on 14.10. It does **not** show the underlying fixes are present: these are functional
assertion tests, and the runner's `OK` fires when the body completes without throwing,
so a silently-wrong value would also beacon `OK`. A crash is a positive signal; the
absence of one is not a patch confirmation.

## Where this leaves the browser route

Reachable, instrumented, and currently empty-handed:

- JS execution: yes, stable, no crash across ~40 documents.
- Attack surface: deliberately minimal — no JIT-adjacent features, no wasm, no GPU, no
  storage, no service workers, ~300 fewer globals than mobile Safari.
- Known exploit families: patched.
- Post-cut crash regressions: none trigger.

A bug here has to be found by fuzzing the **era-correct** engine off-console (JIT off,
LLInt-only profile), not by replaying 2026 trunk cases — the same conclusion the public
project reached, now confirmed on this unit.

## Next steps, in order of expected yield

1. **Finish the corpus properly** — harvest more pages (`jsc-harvest --pages 10`) so the
   sample is hundreds rather than 35, and make the case wrapper beacon assertion
   failures (`__fail`) so a wrong value is distinguishable from a pass.
2. **Fuzz off-console**: build WebKit at the late-2023 branch point with ASAN, JIT
   disabled, and run Fuzzilli with a no-JIT profile. On-console work starts only when a
   candidate reproduces as a *crash*.
3. **Keep the lab**: the setup is now 3 minutes end-to-end and worth keeping warm.
   `www/current` switches the root payload without restarting the server.

## Files

| path | what |
|---|---|
| `tools/fw1400/guide_lab.py` | DNS + TLS + prefix stripping + beacon/conn logs + `/resume` |
| `tools/fw1400/guide_lab/www/index.html` | 30-probe engine battery |
| `data/webview-baseline-1410.json` | battery result, console vs phone |
| `data/p160-relapse-1410.json` | Relapse-family verdict |
| `data/corpus-run-1410.json` | 35-case run, per-index |
