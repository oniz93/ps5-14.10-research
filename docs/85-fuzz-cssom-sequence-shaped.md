# 85 — the sequence-shaped instrument: rounds of 3–6 operations, the docs/65 bug re-found from the alphabet,
# and 492,920 operations over 29,306 synchronous in-engine windows with no new report

`GOAL.md` item 1. `docs/84` swept the drop with an i.i.d. fuzzer — one op per iteration — and found nothing. Two
things were wrong with it as an instrument for this programme's bug: the alphabet could not open the window the
CVE lives in at all, and a bug that needs a *three-step ordering* is sampled very thinly by i.i.d. draws. This is
the sequence-shaped replacement, its calibration against `docs/65`, and the sweep.

Everything below is from `run_nq.sh` (allocator quarantine **off**) except the calibration arms, which are run
with `run_asan_page.sh` (quarantine **on**) because a bug is confirmed with it — a fresh port per arm after
`pkill -f "[h]ttp.server"`, and scoring from the **beacon log**, never from harness state.

---

## 1. What the old alphabet could not do — measured, before anything else

`docs/84`'s 29 ops include two that create a `FontFace` and load it (`Fnew-local`, `Fnew-url`). Neither can
produce a script window inside `setStatus`:

* `Fnew-local` uses `src: local("NoSuchFontName")`. The source fails synchronously, so `pump()` goes
  `Pending → setStatus(Loading) → setStatus(Failure)`, and `FontFace::fontStateChanged` **rejects** on Failure
  (`css/FontFace.cpp:346-351`) — no resolve, no `then` read.
* `Fnew-url` uses `url(/nopeN.woff2)`. The 404 arrives in a network callback, not in a chain, and also ends in
  Failure.
* `Fload` (`document.fonts.load()`) and `Fready` resolve **`FontFaceSet`/`Array`** values, whose `then` is read in
  `FontFaceSet::load`, not inside `CSSFontFace::setStatus`.

Measured, not argued (`W0`): with the window installed (`then=1`) and only those ops available,
`skip=Rpage,Rnest-link,Fdoc,Fnew-good`, 2,000 rounds:

```
$ PAGE=seq.html RUN=nq ./srun.sh "W0 9909 90 n=2000&seed=1&then=1&skip=Rpage,Rnest-link,Fdoc,Fnew-good&every=500"
  B done&op=Rfont&rounds=2000&then=0&gc=0&gcalive=&ms=5875&fc=15&cr=4&lk=9&sc=6&eh=60
```

**`then=0`** — two thousand rounds, not one FontFace resolution window. The same seed with `Fnew-good` present
gives `then=582` (`T0`, §4). That is why the `docs/84` reentrancy arms fired on `FontFaceSet`, `Array` and
`Function` and never on `FontFace`: the alphabet had no synchronous Success.

---

## 2. The instrument

`research/fuzz-cssom/seq.html` (md5 `6004e0e4e7fe99b22538095e5cbcd7ff`, 25,276 bytes), built by
`research/fuzz-cssom/build_seq.py`, run by `research/fuzz-cssom/srun.sh`. The 29 original ops are **extracted from
`fuzz.html` byte for byte** by the builder — between `var OPS = [` and its closing `];`, with the op count
asserted to 29 — so the two instruments cannot drift; the builder appends the two new ops and nothing else.

Four changes, and no others:

1. **Rounds, not iterations.** A round draws one word for how many of six slots run (`3 + w % 4`, so 3–6), then
   **exactly four words per slot, always**, so a round is 25 words and the op id and its three arguments at slot
   *s* of round *r* are a pure function of `(seed, r)`. `only=`/`skip=` and the slot count never renumber the
   stream, so `n=`-bisection is still a valid minimiser and `model_seq.py --round R` replays a round offline.
2. **`Fnew-good`** (weight 6): `new FontFace(fam, 'local("DejaVu Sans")')` + `document.fonts.add(f)` +
   materialise `f.loaded` + `f.load()`. A local source that resolves reaches `Status::Success`, which is the only
   transition that calls `m_loadedPromise->resolve(*this)` from inside `iterateClients`
   (`css/FontFace.cpp:340-345`) — the window.
3. **`Fdoc`** (weight 6): the `docs/65` arming sequence, sampled — a document `@font-face` with a resolvable local
   source, a layout that builds it, its `FontFace` taken from `document.fonts`, `loaded` materialised, `load()`.
4. **`gc=1`**: `~400k` objects allocated inside the window (`new Array(128).fill(i)`, 1 KB butterflies — deliberately
   *not* the 192-byte class of the freed `CSSFontFace`, so the arm cannot steal the slot it measures), with eight
   `WeakRef` decoys created in the **previous task** as the collection witness (`docs/77`/`docs/78`'s technique).
   `gcmax=` (default 60) bounds how many windows do the churn; the arm still runs to `n=` rounds.

The window (`then=1`) is installed on **`FontFace.prototype`**, not `Object.prototype`: it must fire on the face's
own resolution inside `setStatus`, and a broad accessor would also fire in `FontFaceSet`/`Array` frames, which are
windows in *other* functions. Inside it the instrument performs a real stylesheet-collection change (it removes and
re-adds one unrelated, `@font-face`-free `<style id=wchurn>`), then `document.body.offsetHeight` — the statement
`docs/65`'s free is reached from. `m = thenHits % 3` also deletes rule 0 of the inline sheet on the `m=2` hits, and
`del=1` additionally `document.fonts.delete()`s a live face.

**Determinism is measured, twice over.** Two runs of `seed=1, n=200` produce an identical census once HTTP arrival
order is normalised (`sort` → identical, md5 `4c9ad6fac94f2091da06365746b8eb5c`, 31 lines), and the offline model —
written from the weight table alone — reproduces the page's census **31/31 with the same total, 830 operations**:

```
$ python3 research/fuzz-cssom/model_seq.py --seed 1 --rounds 200 --skip Rpage,Rnest-link,Fdoc --census-file /tmp/cen_page.txt
census: 31/31 ops match, model total 830, page total 830
$ python3 research/fuzz-cssom/model_seq.py --seed 1 --rounds 200 --round 63
round 63: 4 ops
   Fnew-local   a=3743375382 b=1353353880 c=1053345508
   Fdoc         a=184395907 b=1113553365 c=30696327
   Fnew-good    a=747644692 b=639948429 c=575682071
   Gsel         a=403173442 b=670542821 c=2212968096
```

---

## 3. The finding that made the instrument work: the promise has to be materialised first

The first version of `Fdoc` opened its window in the wrong frame, and it took a measurement to see it. `DBG=1`
makes the window report the face's own status at entry and at exit. Without `try { f.loaded; }` before `load()`:

```
win&h=1&m=1&had=1&same=1&in=loaded&out=unloaded
```

`in=loaded` — the face's `m_status` is already `Success` when the window runs, so the write at `:595` has already
happened: the window is **not** inside `setStatus`. With the one statement added (`f.loaded` before `f.load()`,
which is exactly what `docs/65`'s page does with `String(face.loaded)`), the same arm reads:

```
win&h=1&m=1&had=1&same=0&in=loading&out=loading     (40/40 windows in DBG1)
```

`in=loading`: the window is inside `setStatus(Success)`, before `m_status = newStatus`, which is the CVE's frame.
The mechanism is `DOMPromiseProxy`: `resolve(value)` only fulfils immediately if the page has already asked for the
promise; otherwise the value is stored and the fulfilment — the `then` read, i.e. the script — happens later, at
`m_loadedPromise.get()` in `loadForBindings` (`css/FontFace.cpp:362`), *after* the status write. **So the CVE's
synchronous window has a precondition nobody had written down: `face.loaded` must have been materialised.** This
also explains `docs/84`'s reentrancy totals (`k=FontFaceSet`/`Array`/`Function`, never `k=FontFace`).

The consequence for the sweep is that it is real: the four arms below open **23,415** windows of the second kind
(`in=loading`), which is 23,415 executions of page script inside a live `CSSFontFace::setStatus` loop (29,306
counting the `gc=1` arm).

---

## 4. Calibration: the bug this programme owns comes out of the instrument

**(a) `cal=1` — the `docs/65` sequence replayed verbatim.** Same five statements as
`research/cve-2026-43715/reclaim.html`: `<style id=v>x{}</style>` (unrelated), `<style id=f>` with one
`@font-face { font-family: t; src: local("DejaVu Sans") }`, `document.body.offsetHeight`, the face with family `t`
taken from `document.fonts`, `face.load()`, with a `FontFace.prototype.then` getter that removes `#v` and forces
layout. Quarantine ON, six runs, one fresh port each:

| arm | port | result |
|-----|------|--------|
| `CAL1` | 9861 | `heap-use-after-free` — `READ of size 1 at 0x6100000466c2`, `:592` in `operator()` ← `iterateClients` ← `setStatus:591` |
| `CAL2` | 9862 | same as `CAL1` (`READ`, `:592`) |
| `CAL3` | 9863 | **`heap-use-after-free` — `WRITE of size 1 at 0x6100000466c2`, `#0 WebCore::CSSFontFace::setStatus … CSSFontFace.cpp:595`** |
| `CAL4` | 9864 | **same `WRITE`, `:595`** |
| `CAL5` | 9865 | `READ`, `:592` |
| `CAL6` | 9866 | `READ`, `:592` |

`WRITE` at `:595` in **2 of 6**, `READ` at `:592` in **4 of 6**, **0 clean**. The two flavours are the same object
and the same byte: all six fault at `0x6100000466c2`, i.e. chunk base `0x…640` + `0x82` = `m_status`. Which one
appears is the client-iteration order `docs/65` already recorded as a per-run coin flip: if the freeing client
(`FontFace`, whose resolution runs the script) is iterated **last**, the next statement is `m_status = newStatus`
and ASAN reports the WRITE at `:595`; otherwise the next iteration's `client.fontStateChanged(*this, m_status, …)`
reads `m_status` and reports the READ at `:592`. `CAL3`, verbatim:

```
==563018==ERROR: AddressSanitizer: heap-use-after-free on address 0x6100000466c2 at pc 0x7f76d2bd023d …
WRITE of size 1 at 0x6100000466c2 thread T0
    #0 WebCore::CSSFontFace::setStatus(CSSFontFace::Status)                      CSSFontFace.cpp:595
    #1 WebCore::CSSFontFace::pump(ExternalResourceDownloadPolicy)                CSSFontFace.cpp:686
    #2 WebCore::CSSFontFace::load()                                             CSSFontFace.cpp:703
    #3 WebCore::FontFace::loadForBindings()                                     FontFace.cpp:361
    #4 jsFontFacePrototypeFunction_loadBody                                     JSFontFace.cpp:707
```

`cal=1&later=1` (the same statements deferred to a task, so the page is fully loaded — the context the fuzzer's
rounds run in) gives the READ flavour in 1/1 (`CA1`, `:592`, `0x6100000468c2`), so the deferral is not what makes
the difference.

**(b) The *sampled* op, i.e. the code path the sweep actually runs.** `only=Fdoc&then=1` is `Fdoc` and nothing
else, so every round draws it and the window fires on the face it just built. Quarantine OFF (`SD8`): the chunk has
been reused by the time of the access, so the report is the `docs/65` overflow flavour —

```
SUMMARY: AddressSanitizer: heap-buffer-overflow …/css/CSSFontFace.cpp:592 in operator()
  READ of size 1 at 0x6100000103c2
    #0 operator()                    CSSFontFace.cpp:592
    #1 iterateClients<…>             CSSFontFace.cpp:58
    #2 CSSFontFace::setStatus        CSSFontFace.cpp:591
    #3 CSSFontFace::pump             CSSFontFace.cpp:686
```

— and quarantine ON (`FD1`) gives the canonical one: `heap-use-after-free`, `READ of size 1 at 0x610000046cc2`,
`:592` ← `iterateClients:58` ← `setStatus:591` ← `pump:686` ← `load:703` ← `loadForBindings:361`. So the
instrument is sensitive in the sampled path as well as in the deterministic one, which is the property the sweep
depends on.

---

## 5. The sweep: four seeds × 20,000 rounds, plus the GC arm and a window-off control

`skip=Rpage,Rnest-link,Fdoc`: `Rpage`/`Rnest-link` are the two crashes this programme already owns (`docs/67`,
`docs/72`) and `Fdoc` is the one just calibrated, so all three are excluded by construction — the sweep is looking
for a *second* instance, not for the bug it already has.

```
$ PAGE=seq.html RUN=nq ./srun.sh \
    "S1 9901 165 n=20000&seed=1&then=1&skip=Rpage,Rnest-link,Fdoc&every=250" \
    "S2 9902 165 n=20000&seed=2&then=1&skip=Rpage,Rnest-link,Fdoc&every=250" \
    "S3 9903 165 n=20000&seed=3&then=1&skip=Rpage,Rnest-link,Fdoc&every=250" \
    "S4 9904 175 n=20000&seed=4&then=1&skip=Rpage,Rnest-link,Fdoc&every=250"
```

| arm | seed | executed | exceptions | windows | `done` beacon | sanitizer |
|-----|------|----------|-----------|---------|----------------|-----------|
| `S1` | 1 | 82,065 | 0 | 5,891 | `done&op=Gsel&rounds=20000&then=5891&gc=0&gcalive=&ms=80616&fc=14&cr=3&lk=13&sc=6&eh=60` | none |
| `S2` | 2 | 82,097 | 0 | 5,737 | `done&op=Rplain&rounds=20000&then=5737&gc=0&gcalive=&ms=80491&fc=16&cr=15&lk=14&sc=6&eh=60` | none |
| `S3` | 3 | 82,190 | 0 | 5,821 | `done&op=Rfont&rounds=20000&then=5821&gc=0&gcalive=&ms=81162&fc=13&cr=4&lk=19&sc=6&eh=60` | none |
| `S4` | 4 | 82,438 | 0 | 5,966 | `done&op=Gsel&rounds=20000&then=5966&gc=0&gcalive=&ms=81125&fc=13&cr=2&lk=14&sc=6&eh=60` | none |

`EXIT=124` in all four: that is how **every** run of this harness ends (`timeout` kills MiniBrowser — `docs/65`,
Attempt 11); the `done` beacon is the completion witness and all four have it. All 31 census lines are present in
each arm, `e=0` everywhere (`errors` column is the sum over the census). The last op beacon before `done` is
`20000&op=Gsel` / `20000&op=Rplain` / `20000&op=Rfont` / `20000&op=Gsel`. `access: none` — run once per arm,
`grep -a -cE "AddressSanitizer|RELEASE_ASSERT|Zapped" /tmp/S_$TAG.log`, which returns `0` for `S1`, `S2`, `S3`,
`S4`, `GC1` and `C0`.

**`GC1` — a collection inside the window.** Same seed and stream as `S1` (identical executed count and identical
last-op beacons, which is the determinism check again), plus `gc=1&gcmax=60`:

```
  B gcprobe&pre=8/8&post=8/8&h=1      B gcprobe&pre=8/8&post=8/8&h=4
  B gcprobe&pre=8/8&post=8/8&h=2      B gcprobe&pre=8/8&post=8/8&h=5
  B gcprobe&pre=8/8&post=8/8&h=3      B gcprobe&pre=8/8&post=0/8&h=6
  B done&op=Gsel&rounds=20000&then=5891&gc=60&gcalive=8/8&ms=153173&fc=14&cr=3&lk=13&sc=6&eh=60
```

`pre=8/8 → post=0/8` at `h=6` is the witness working: the eight `WeakRef` decoys were all alive when that window
was entered and all collected by the churn inside it, i.e. a collection really did happen in the engine's frame.
60 windows did the 400k-object churn (the arm took 153 s, versus 81 s without), 5,891 windows total, 82,065 ops,
0 exceptions, **0 sanitizer reports**.

**`C0` — the window off.** `then=0`, same seed and stream: `done&op=Gsel&rounds=20000&then=0&…&ms=62282`, 82,065
ops, 0 reports. This is the control for the window axis: `S1` and `C0` differ in `then` alone, and `C0` shows the
alphabet alone finds nothing either.

Totals: **492,920 operations in six 20,000-round arms** (328,790 in the four required arms, 82,065 each in `GC1`
and `C0`), of which **29,306 ran inside a synchronous `then` window** — 23,415 in the four arms (5,891 / 5,737 /
5,821 / 5,966) plus 5,891 in `GC1`, 60 of them with a collection inside — and **0 sanitizer reports, 0
exceptions**. (The four arms alone are 23,415 windows; 29,306 is the six-arm total, not a per-arm figure.)

---

## 6. What this null covers — and what it does not

**It covers**, by construction and by the census:

- the `docs/65` window at scale: `in=loading` in every sampled window, meaning page script ran inside
  `CSSFontFace::setStatus`'s client loop, with a real stylesheet-collection change and a forced layout inside it,
  **23,415 times in the four arms and 29,306 across the sweep**, on document-owned and JS-owned faces alike (`Fstyle`, `Rfont`, `Fdoc`-shaped state, plus
  `Fnew-good`);
- sequences: 3–6 operations back to back with **no task boundary**, so a pending load, a queued microtask or a
  stale resolver is still in flight when the next op runs — the axis `docs/84` could not sample;
- a collection inside the engine's frame, with a witness that the collection happened (`GC1`);
- CSSOM mutation on both sheet kinds, custom-element reactions, `Range`/`Selection`, and 20,000 forced layouts per
  arm (`Llayout` alone ≈ 1,500/arm).

**It does not cover**, and nothing above claims it:

- **the known bug**: `Fdoc` and the two known crashes are `skip`ped, so their absence is by construction. What is
  claimed is only that the *instrument* re-finds it (§4), in both its flavours.
- **one document.** No iframes, no `window.open`, no workers, no `structuredClone`, no `fetch`/XHR, no IndexedDB,
  no `Animation`, no `MutationObserver`. So `docs/74`'s `WebAnimation` windows and `docs/73`'s frame teardown are
  **not** in the alphabet — the next action.
- **not a reclaim oracle.** The window's own allocation (the beacon, the `<style>` churn) is uncontrolled, so a
  freed slot that is reused says nothing about who took it. This run is a crash hunt, not a heap-shaping
  measurement; `docs/65` owns those numbers.
- the 400k-object churn is *one* allocation shape (1 KB butterflies) and 60 windows, not a sweep over GC pressure.

---

## 7. Conclusions

1. **`docs/84`'s null was measured on an alphabet that could not reach the bug's window.** With `then=1` and 2,000
   rounds, the ops that existed then open **zero** FontFace-resolution windows; the two added here open 582 in the
   same 2,000 rounds. The `docs/84` conclusion ("the reentrancy arms are the sharpest negative") is therefore
   narrower than it read: they exercised `resolve(FontFaceSet)`/`resolve(Array)`, not `resolve(FontFace)`.
2. **The CVE's window has a documented precondition now: the promise must be materialised.** Without a
   `face.loaded` read before `load()`, `DOMPromiseProxy::resolve()` stores the value and the `then` read happens
   at `m_loadedPromise.get()` — after `m_status = newStatus` — and the same page that crashes with the statement
   does not crash without it. This is a *reader* fact about this drop and it is worth carrying: any future trigger
   that relies on `resolve(<DOM object>)` running script inside its own C++ frame needs the promise materialised
   first.
3. **The instrument is calibrated on the programme's own bug, in both flavours and in both code paths**:
   `cal=1` gives `WRITE of size 1` at `:595` in 2 of 6 runs and the `:592` read in 4 of 6 (same fault address,
   client order decides), and the sampled `Fdoc` op gives the UAF at `:592` under quarantine on and the
   `docs/65` overflow flavour under quarantine off.
4. **492,920 operations over 29,306 in-engine windows, four seeds, chains of 3–6 ops, 60 windows with a collection
   inside them: 0 sanitizer reports.** The only defects this alphabet finds are the two it skips and the one it is
   calibrated on.
5. **What is left is not another seed.** The alphabet's boundary is now the boundary of the search: a second
   document (iframe), `Animation`'s resolve windows, workers and the serializer are the surfaces that the audits
   closed on paper and that no run has fuzzed. That is the next action in `GOAL.md`.

Logs: `/tmp/S_{CAL1..CAL6,CA1,SD1..SD8,FD1,T0,DT1,DT2,S1..S4,GC1,C0,W0,DBG1}.log` on the build box, server logs
`/tmp/srv{9861..9909}.log`. Page `research/fuzz-cssom/seq.html`, builder `build_seq.py`, runner `srun.sh`, model
`model_seq.py`.
