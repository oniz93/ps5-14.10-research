# Console results: c018 and c019 - the ArrayBuffer spray never takes the slot

Two real runs on 14.10 (19:06 and 19:07), both after the corrections that came out of the public repos.

## c018 - the corrected V527 sequence

Trigger -> 500x same-type canvas spray -> alias found -> free the aliased owner -> 192MB churn -> 1.2s wait
-> 500x ArrayBuffer(768) filled with 9999.99 -> read lineWidth through the stale wrapper.

Beacons: `boot`, `sprayed:500 trig=true`, `churn:ok`, `lw=1 no-reclaim`.

`lineWidth` returned the default 1 with no crash, which means the object was still intact and still pointing at
its own state stack. No reclaim.

## c019 - and draining bmalloc's deferred-free log does not change it

Two attempts in one run, so the comparison is on the same heap state:

* `A0` - no flush: `alias=2`, `lw=1 no-reclaim`
* `B700` - allocate and drop 700 same-class canvas contexts first, pushing >512 frees through the small-class
  deallocator: `alias=13`, `lw=1 no-reclaim`

So the CSSFontFace write-up's 512-entry `m_objectLog` explanation - which fit our failures so well - is **not**
the cause here. Draining the log explicitly made no difference.

## What this actually establishes

1. **Same-type reclaim is reliable on this console.** `c014` (alias at index 4, readback 777.25) and now `c018`/
   `c019` (aliases at 2 and 13) all find the freed context's slot occupied by a freshly sprayed Canvas2D
   context. The UAF and the alias are solid.
2. **The ArrayBuffer spray never lands there.** 500-600 buffers of 768 bytes, after a flushed deallocator, do
   not take the slot. Either `ArrayBuffer(768)` is in a different size class than the context, or JSC's buffer
   allocation does not share bmalloc's primary heap with WebCore objects on this build, whatever
   `Gigacage.h` says about the flag.
3. **The public "AB reclaim of 768B slot" result does not reproduce here.** The pastawithpesto repo's own
   `CONFIRMED_VULNS.md` still lists the info leak as its current blocker, and the V527 probe that claims the AB
   reclaim is a third-party reconstruction with a header saying so. Their README's table is ahead of their
   evidence.

## Next discriminating test (staged as c020)

Three sprays, each after its own fresh groom:

* `AB712` - the object's exact size, so a class-rounding miss cannot explain a negative
* `IMG178` - `createImageData(178,1)` = 712 bytes, fastMalloc'd **and** JS-readable/writable, so an overlap is
  directly observable and immediately useful
* `STR712` - StringImpl, the allocation the CSSFontFace exploit used

`c020` never ran: the WebProcess hit the memory modal before the new corpus was picked up, and the hot-reload
could not fire because the page's `location.reload()` failed TLS (`TLSV1_ALERT_UNKNOWN_CA`). That last part is
worth remembering: navigation re-validates the lab certificate even when in-page requests already work.

## Infrastructure added

`campaign.html` now polls `/cases/manifest.json` every 3s and reloads when the corpus signature changes, so a new
case can be pushed without touching the console. It needs one physical page load to take effect, and a reload
that fails TLS leaves the guide on an error page, which then needs a manual re-entry.
