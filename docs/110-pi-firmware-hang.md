# The Pi's WiFi fault, identified: brcmfmac firmware hang, not an AP problem

Second pass with the supplicant's events finally captured (`tools/fw1400/pi-wpa-183009.txt`).

## The two lines that decide it

During the 01:17–01:24 UTC outage the kernel said:

```
[126214.623395] ieee80211 phy0: brcmf_cfg80211_get_channel: chanspec failed (-512)
[126214.635118] ieee80211 phy0: brcmf_cfg80211_get_tx_power: error (-512)
```

`-512` is the firmware/bus failing to answer a driver command. Two different commands, the same error, at the
moment the link was already dead.

And `/var/log/wpa-events.log`, newly installed, contained exactly one line for the whole episode:

```
2026-10-31 01:24:33 [wlan0] CONNECTED
```

**No `CTRL-EVENT-DISCONNECTED`, no `reason=` code, no deauth.** If the access point had kicked us, the supplicant
would have logged it — that is precisely what the event logger was built to catch. It did not. The supplicant's view
is that the link was fine and then a new association appeared; the link died underneath it.

## Why this is not the AP, and not coexistence

- **Not AP-side rejection.** No disconnect event, and the firmware was failing driver commands — a deauth does not
  make `get_channel` fail with -512.
- **Not Bluetooth/WiFi coexistence.** `systemctl is-active bluetooth` = **inactive**; the radio is WiFi-only here.
  That candidate is closed.
- **Not power save, throttling, DHCP, or a reboot** — each was measured and ruled out in `docs/109`.

## Why our first remediation was doomed

`ifdown wlan0; ifup wlan0` re-runs the interface and DHCP *over a radio whose firmware is not answering*. That is
why both outages were unmoved by it: the first (`docs/109`) went `still down after ifup`, and the second needed 21
failed checks despite `acted=2`. The remediation that matches the fault is **`modprobe -r brcmfmac; modprobe
brcmfmac`**, which re-probes the SDIO card and re-uploads the firmware.

## Watchdog v3

Cheapest action first, each step logged with what recovered it:

| failures | action |
|---|---|
| 3 | log `iw link` state and whether firmware commands answer; scan + reassociate |
| 6 | **reload `brcmfmac`**, then re-ifup |
| 14 | `ifdown/ifup` as last resort |

## A contributing factor worth treating seriously

Every outage so far began within one or two minutes of **multi-connection bursts** against the Pi (`scp` plus
several `ssh` calls, or a sequence of one-ssh-per-keypress input runs). Idle periods never dropped it. The BCM43430
on a Zero W is a marginal radio, and the phenomenon (firmware stops answering under a burst, recovers minutes later)
fits a driver/firmware stall far better than an AP policy. Two mitigations follow from that and both are cheap:

1. Deploy and drive the Pi over **one connection** — `ssh root@pi 'bash -s' < script` instead of `scp` + `ssh`, and
   batch keypresses instead of opening a connection per key.
2. If it keeps happening under load, update `brcmfmac43430-sdio.bin` (currently the Jul 2021 `7.45.98 TOB`
   firmware) from a newer `linux-firmware`, keeping a copy of the old file so it can be reverted.

## Status

V3 deployed on the next successful connection; the log line `recovered by module-reload` versus
`recovered by reassociate` will confirm the mechanism in one outage, and the event log will show whether a
disconnect ever accompanies it.
