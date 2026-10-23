# Crash cases

Drop `.js` files here and list their filenames in `manifest.json` (an array of strings,
order = run order). Open `/runner.html` in the Guide WebView; the runner beacons
`start:i` before each case, then `survived:i` or `threw:i`.

A case that beacons `start` and never `survived`/`threw` took the WebProcess down.
That is a crash oracle, not a proof of exploitability — a hang looks identical until
you re-run the case alone.

Start with cases from `research/PS5-14.10-Research/probes/phase13_webkit/` — particularly
`p160-relapse-test.js` (the three Relapse WebKit bugs) and `p162/p163` (fingerprint and
capability map), which are read-only and safe.
