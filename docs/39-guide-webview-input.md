# Guide WebView: keyboard input into page JavaScript (verified 2026-10-26)

The console's User's Guide now runs our page **and** receives keys from the Pi's HID gadget. This closes
the automation loop: press a key, read what the page saw, with no human watching the screen.

## Evidence

Page served by the lab (`probes/keydown-probe.js`) painted `WAITING FOR KEY` on the console, then
reported, all from client `<console-ip>` with the retail UA `PlayStation 5/14.10`:

```
08:35:35  /beacon/keyprobe-loaded
08:36:02  kd-1-ArrowDown-c40 / ku-1-ArrowDown-c40
08:36:15  kd-2-ArrowUp-c38   / ku-2-ArrowUp-c38
08:36:16  kd-3-ArrowRight-c39/ ku-3-ArrowRight-c39
08:36:16  kd-4-ArrowLeft-c37 / ku-4-ArrowLeft-c37
08:36:17  kd-5-ArrowDown-c40 / ku-5-ArrowDown-c40
08:36:28  kd-6-Escape-c27    / ku-6-Escape-c27
```

`kd`/`ku` are keydown/keyup, so press and release both arrive — no stuck-modifier risk. The chain is
HID gadget -> console input stack -> Guide shell -> WebView -> page JS -> HTTPS beacon.

## Keymap as seen by page JavaScript

| key | `keyCode` | delivered to the page |
|---|---|---|
| ArrowLeft | 37 | yes |
| ArrowUp | 38 | yes |
| ArrowRight | 39 | yes |
| ArrowDown | 40 | yes |
| Escape | 27 | yes — **and the shell still navigates back**, so one Escape both reaches JS and leaves the page |
| Enter | 13 | **no** — no beacon at all, while the same Enter dismisses system dialogs |

So the shell consumes Enter for its own activation and does not forward it to the document. Anything that
needs Enter inside the page needs a focusable element (untested) or must not depend on Enter. Arrows and
Escape are the reliable in-page keys.

## TLS: one accepted connection carries everything

Counts for the console today: **1** `tls_ok=true`, **26** rejected with
`SSLError: [SSL: TLSV1_ALERT_UNKNOWN_CA]`. The single accepted connection at 08:35:35 served the
document, and every beacon afterwards rode that same HTTP keep-alive connection — 13 beacons over one
TLS session.

Consequences for reading the logs:

- `UNKNOWN_CA` lines do **not** mean the entry failed. Look for `tls_ok=true` from the console's IP; if
  one exists, the page is being served and beacons can flow.
- Expect a certificate prompt on the console. If the app is closed and reopened, a new handshake has to
  be accepted again.
- Do not infer "server not running" from an empty `lsof -iTCP:443`. The lab runs under `sudo`, and an
  unprivileged `lsof` cannot see root-owned sockets — it printed nothing while the console was actively
  connecting. `conn.jsonl` is the authority.

## Reproduce

```
cd ~/Documents/ps5-bootchain/tools/fw1400
echo keydown-probe.js > guide_lab/current
sudo python3 guide_lab.py --serve --lan-ip <host-ip>     # update containment stays on
```
On the console: close the Guide fully, reopen it, accept the certificate warning. Then
`ps5_input.py --ssh root@<pi> press down` and watch `guide_lab/results/beacons.jsonl`.
