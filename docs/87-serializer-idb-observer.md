# 87 — the three surfaces still outside the alphabet, and the fourth that this build does not have

`GOAL.md` item 1. `docs/86` closed the sequence instrument on three new surfaces (a second document,
`Animation`'s resolve frames, a worker) and named its own boundary: the four surfaces the audits had
closed **on paper** but no run had fuzzed — `structuredClone`'s serializer, IndexedDB's key builder,
`MutationObserver`, and `window.open`. This document does those four, in the order the action asked
for: a probe of the build *before* an op is written, an `only=<op>` arm that shows the window firing,
the calibration, then four 20k arms.

Three of the four are wireable. **The fourth does not exist on this build**: every spelling of
`window.open` from script returns `null`, `showModalDialog` is not exposed, and the one spelling that
returns a window (`_self`) simply navigates the current document. That is measured, not argued, in §1.

Everything is from `run_nq.sh` (**quarantine off**) except the calibration, which is
`run_asan_page.sh` (**quarantine on**) — a fresh port per arm, scored from the **beacon log**. Pages:
`research/fuzz-cssom/seq3.html` (md5 `6ccdf12569d4da03da27a236e411462e`, 44,630 bytes), builder
`build_seq3.py` (md5 `5deef61beb881e770d3af698540a7dd1`), probes `caps5.html`
(`ad2d96a4ce0ce004a5dd5c2653239e6f`), `caps6.html` (`bd7470a6db54bde23a51bb718b0f622a`),
`caps7.html` (`f547fac3eeb6cc2fa296216c10d33b24`). `seq2.html` is untouched
(`2c3f6a900c0b5cb71879f399cbad2faf`, still what `docs/86` quotes), `seq.html` untouched.

---

## 1. Before writing an op: what the build actually has

### 1.1 The four questions, one page

`research/fuzz-cssom/caps5.html` asks them in one load. `PAGE=caps5.html RUN=nq srun.sh "C5 9921 30 n=1"`
(log `/tmp/srv9921.log`, below is every beacon it sent):

```
caps5 js=1 structuredClone=function indexedDB=object IDBKeyRange=function MutationObserver=function open=function
clone get=0 err=- depth=40 late=0 kids=-1
clone plain=1
idb only=1 hits=1 nested=0 err=- lower=Array
idb nested=1 hits=1 err=-
open got=0 err=- closed=-
idb db=1
mo hits=1 recs=2 kids=2 err=-
```

Read line by line, and each line cost a follow-up:

- **`structuredClone` exists and clones a 40-level object (`depth=40`), but the getter did not run**
  (`get=0`, `late=0`). The cause is in the page, not the engine: `Object.defineProperty` defaults to
  `enumerable: false`, and the serializer walks **own enumerable names**
  (`getOwnPropertyNames(..., DontEnumPropertiesMode::Exclude)`, `SerializedScriptValue.cpp:2590`).
- **IndexedDB is reachable and its key builder runs page script**: `idb only=1 hits=1` — an array hole
  in `IDBKeyRange.only([1,,3])` reaches the prototype chain and calls a getter, inside
  `createIDBKeyFromValue`. `idb db=1` shows a real `indexedDB.open` also succeeds (not needed).
- **`MutationObserver` fires** (`mo hits=1 recs=2`).
- **`window.open('', 'zzpop5')` returned `null`** (`open got=0`), which is the one result that changed
  the plan for this run.

### 1.2 The clone getter, the Proxy, and every popup spelling

`caps6.html`, `PAGE=caps6.html RUN=nq srun.sh "C6 9922 25 n=1"` (`/tmp/srv9922.log`, every beacon):

```
clone2 get=1 depth=40 late=1 kids=1 err=-
clone2 proxy hits=0 ok=0 err=DataCloneError
clone2 node err=DataCloneError
pop open-empty=0 open-blank=0 open-named=0 open-feat=0 open-self=1
pop anchor err=-
pop modal=undefined createHTML=function ua=0
```

- **A getter at depth 40 runs inside the serializer and the clone still completes** (`get=1`,
  `late=1`): at depth 40 the walk is 8 entries past `inputObjectStack`'s 32-entry inline capacity, so
  the vector is in its heap buffer (`Vector<JSObject*, 32>`, `SerializedScriptValue.cpp:2499`), and
  `getProperty` (`:2607`) is page script inside it.
- **A Proxy cannot open that window**: `structuredClone` returns `DataCloneError` before any trap runs,
  because the serializer rejects any object whose `classInfo()` is not `JSFinalObject`
  (`SerializedScriptValue.cpp:2585-2586`) — `hits=0` proves the traps never fired. Only an enumerable accessor works.
- **A getter returning a DOM node is a clean `DataCloneError`**, not a crash.
- **No popup is creatable.** Five spellings (`open()`, `about:blank`, a named target, a named target
  with features, `_self`) — four `0`, and `_self` returns the *current* window. A programmatic
  `<a target="_blank">` click adds nothing observable. `showModalDialog` is `undefined` in this build,
  and `navigator.userActivation.isActive` is 0, so the gesture branch of `allowPopUp()` cannot be
  taken either. The source explains the null: `LocalDOMWindow::open` returns early unless
  `allowPopUp()` — `UserGestureIndicator::processingUserGesture() ||
  settings().javaScriptCanOpenWindowsAutomatically()`, `LocalDOMWindow.cpp:363-378` — or a frame of
  that name already exists (`LocalDOMWindow.cpp:2689-2691`). Two things can produce the null and this measurement does
  not separate them: the embedder's setting, or the UI client refusing `createWindow`. Either way the
  path is closed to a page, on this build.
- **`_self` is not a popup, and it is why this page has no `done` beacon**: `window.open('about:blank',
  '_self')` takes the `targetFrame` branch and *schedules a location change of the current document*,
  so the page is replaced by `about:blank` before its `setTimeout` fires. `pop after ms=1` and
  `done caps6` are absent for that reason, and the absence is the witness.

### 1.3 The two mechanisms the ops need

`caps7.html`, `PAGE=caps7.html RUN=nq srun.sh "C7 9923 25 n=1"` (`/tmp/srv9923.log`):

```
idb7 hits=1 recv=1 other=0 in=0 ok=1 lower=1,4,5,3 err=-
idb7 control hits=0 ok=1
idb7 plain=1
clone7 hit=1 depth=40 ok=1 err=- face=1 st=unloaded
clone7 load hits=1 st=loaded
done caps7
```

- **The IDB hole getter can live on a per-array prototype** — `Object.setPrototypeOf(arr, proto)` with
  a getter at `'1'` — and it fires with `this === arr` (`recv=1`), the key is built
  (`lower=1,4,5,3`), the control with a plain data property gives `hits=0`, and `plain=1` shows
  ordinary arrays in the page are untouched. That matters because putting the accessor on
  `Array.prototype` would perturb every array access in the instrument, not just the op's.
  `IDBKeyRange::only(JSGlobalObject&, JSValue)` (`IDBKeyRange.cpp:71-77`) →
  `scriptValueToIDBKey` (`IDBBindingUtilities.cpp:426-429`) → `createIDBKeyFromValue`, which pushes
  each array into `Vector<JSArray*> stack` (capacity **0**, `:257`), appends at `:228` and reads with
  `getIndex` at `:232` — the hole falls through to `get`.
- **The clone window can do the docs/65 arming and the clone still completes**: the getter churned an
  unrelated sheet, deleted a rule and forced layout, and `depth=40`/`late='L'` came back intact
  (`ok=1`); the FontFace window installed afterwards still fires (`hits=1`, `st=loaded`).

---

## 2. The instrument: `seq3.html`, built from `seq2.html` at anchors that must occur once

`build_seq3.py` reads `seq2.html` (never edits it) and inserts, at anchors that must each occur
exactly once (abort otherwise): the `mob` knob, the three ops, their machinery, one line in the
FontFace window (`if (MOB) moNudge();`), `if (MOB) mkMo();` before the boot beacon, and the extra
counters in the `done` beacon. **37 operations** = the 29 from `docs/84` + `Fnew-good` + `Fdoc` +
`Aanim` + `Aframe` + `Aworker` + `Cclone` + `Ikey` + `Mobs`.

Provenance is re-asserted on the output, not assumed: the 29 `docs/84` ops must appear verbatim, and
each of the three `docs/86` ops is extracted from `seq2.html` by regex and must appear verbatim in
`seq3.html` (3,314 bytes). The builder also parses the page's own **program**:

```
page script: 44190 bytes, syntax OK
inner srcdoc script: 816 bytes, syntax OK
wrote research/fuzz-cssom/seq3.html (44567 bytes, md5 6ccdf12569d4da03da27a236e411462e)
ops present: 37 (29 array + 8 pushed = 37)
provenance: 29 docs/84 ops present, 3 docs/86 ops present (3314 bytes verbatim)
```

and that check has a **sensitivity control**: inserting one brace into `moNudge` on a copy of the
built page makes the builder exit with `page script has a syntax error:` (the same guard `docs/86`
added for the srcdoc, now covering the instrument itself — `docs/86` shipped a brace error that
silently disabled a whole surface, and it lived in a *string* where nothing could see it).

| op | weight | what it drives | window it opens |
|----|--------|----------------|-----------------|
| `Cclone` | 5 | `structuredClone` of a 41-object chain, enumerable getter at depth **24-43** | the serializer's `getProperty` at `SerializedScriptValue.cpp:2607`, i.e. inside the walk, mostly past the 32-entry inline stack |
| `Ikey` | 3 | `IDBKeyRange.only(arr)` with a hole at index 1 and a getter on the array's own prototype | `createIDBKeyFromValue`'s `getIndex` at `IDBBindingUtilities.cpp:232`, with `Vector<JSArray*>` (cap 0) in its heap buffer |
| `Mobs` | 3 | one `MutationObserver` on `root` and on `p0`, installed at boot when `mob=1` | `MutationObserver::deliver`'s `m_handleEvent` (`MutationObserver.cpp:195-222`), once per task |

`ext=1` is the same single destructive knob `docs/86` used: inside every one of these windows it
removes a frame from the pool, terminates the worker (capped at 64 per arm), drops a live `FontFace`
from the document set, and — new here — **the delivery loop hosts an engine frame of its own**: the
`MutationObserver` callback creates a `FontFace` with a source that resolves synchronously and calls
`load()`, so `setStatus` runs *inside* `MutationObserver::deliver`.

### The one thing the nudge experiment settled, and the limit it leaves

`docs/86`'s instrument mutates `document.head` inside its windows, which no observer watches, so the
first `mocb` in a delivery-armed run reports `q=10` — the end of batch 10 (BATCH is 10). That is a
task-boundary delivery, not a window. So the FontFace, clone and IDB windows now call `moNudge()`
(`root.setAttribute('mn', …)`), a cheap mutation of a node the observer watches, and `moIn` counts
deliveries whose `seq` is **not** a batch multiple:

```
M3 (nudge build 8a174d4822a904ea2912f039668ed9e1)
done&...&moh=199&mors=13224&mod=78&moi=1&mn=1067&moir=0
GET /ev?m=mocb&h=1&n=79&t=attributes&q=10&gd=0
GET /ev?m=mocb&h=2&n=14&t=childList&q=20&gd=0
```

**1,067 nudges from inside engine frames, and `moir=0`.** The record is queued in the frame but the
microtask checkpoint does not drain it there: the callback runs at the task boundary, once per batch,
always. That is a property of this build's checkpoint placement, and it means a `MutationObserver`
callback **cannot** be nested inside the round that queued the record — so the only way to get an
engine frame inside the delivery is to have the callback create one itself (`moload`, above). M4
(final build) measures exactly that:

```
M4 (final build, n=600)
GET /ev?m=moload&h=1&th0=2&th1=3
GET /ev?m=moload&h=2&th0=4&th1=5
GET /ev?m=moload&h=3&th0=6&th1=7
GET /ev?m=moload&h=4&th0=10&th1=11
GET /ev?m=moload&h=5&th0=17&th1=18
GET /ev?m=moload&h=6&th0=19&th1=20
done&...&moh=59&mors=3483&mod=21&mn=375&moir=0
```

`thenHits` advances across the `load()`, so the FontFace window fires inside the delivery, six times
out of six observed.

---

## 3. Calibration: `cal=1` still reproduces `docs/65`, 6 of 6, on the shipped page

`cal=1` returns from the IIFE before the rounds loop, so the new ops cannot run in a cal arm; the cal
path's code is untouched by the builder. Measured on the **final** page (`6ccdf125…`), quarantine
**on**, six runs, fresh port each, three with the observer installed and three without:

```
$ PAGE=seq3.html RUN=asan srun.sh "K1 9971 45 n=1&cal=1&mob=0" ... "K6 9976 45 n=1&cal=1&mob=1"
```

| arm | `mob` | flavour | frame |
|-----|-------|---------|-------|
| `K1` | 0 | **`WRITE of size 1`**, `CSSFontFace::setStatus`, `:595` | `0x610000046bc2` |
| `K2` | 0 | `READ of size 1`, `operator()`, `:592` | `0x610000046bc2` |
| `K3` | 0 | `READ of size 1`, `:592` | `0x610000046bc2` |
| `K4` | 1 | `READ of size 1`, `:592` | `0x610000046cc2` |
| `K5` | 1 | `READ of size 1`, `:592` | `0x610000046cc2` |
| `K6` | 1 | **`WRITE of size 1`**, `:595` | `0x610000046cc2` |

**6/6 reproduce, 2 `WRITE` / 4 `READ`, every fault at base + `0x82` (`m_status`).** The observer moves
the object's *base* by `0x100` (`…46bc2` → `…46cc2`) — the extra `<p id="moP">` it appends to `root`
is allocated before the face — and moves the fault by exactly the same amount, which is a second,
independent confirmation that the byte being written is the face's `m_status` and not something the
new surfaces introduced. A first set of six on the pre-nudge build (`CAL1..CAL6`, md5
`acb6197a533bb7ac7f75f72ddc6247a6`) also came back 6/6 — 1 `WRITE`, 5 `READ`, bases `…469c2` /
`…46ac2` — so the two builds agree on the same byte and differ only where the allocator put the
object.

---

## 4. Wiring, one axis at a time

**(a) `structuredClone`.** `only=Cclone&dbg=1&n=300` runs 64 clones. The `done` beacon and the first
frames (`/tmp/srv9981.log`):

```
done&op=Cclone&rounds=300&...&clh=64&clok=64&clerr=0&...&moh=26&mors=61&mod=0&moi=1&mn=64&moir=0
cget&h=1&d=36&in=1
cget&h=2&d=29&in=1
cget&h=3&d=28&in=1
cget&h=4&d=37&in=1
cget&h=5&d=41&in=1
```

`in=1` is the op's own flag around the `structuredClone` call, so the getter really runs inside it;
`d=29`/`d=28` are inline-stack depths and `d=36/37/41` are past the 32-entry boundary — both halves of
the vector are exercised. `clok=clh=64` means every clone returned the full chain with the getter's
value in it, i.e. the arming did not corrupt the walk.

**(b) IndexedDB's key builder.** `only=Ikey&dbg=1&n=300` runs 34:

```
done&op=Ikey&rounds=300&...&ikh=34&ikok=34&ikerr=0&...&moh=22&mors=34&moi=1&mn=34&moir=0
iget&h=1&in=1&nest=0
iget&h=2&in=1&nest=0
iget&h=3&in=1&nest=1
```

`in=1` and `nest` 0-3 show the getter fired inside `IDBKeyRange.only` at four different nesting
depths, and `ikok=ikh` that every call produced a key.

**(c) `MutationObserver`.** `only=Mobs&dbg=1&n=300&ext=1`:

```
done&op=Mobs&rounds=300&...&moh=22&mors=90&mod=9&moi=1&mn=0&moir=0
mocb&h=1&n=3&t=childList&q=20&gd=0
moload&h=1&th0=0&th1=0
```

22 deliveries carrying 90 records, 9 of which removed the observed node from inside the delivery
(`mod=9`). `moload` with `th0=th1=0` is the right negative control for §2's nesting claim: this arm
has `then=0`, so no accessor is installed and the delivery's font load opens no window; M4, with
`then=1`, is the arm where it does.

---

## 5. The sweep: four seeds × 20,000 rounds, plus a GC arm and a windows-off control

```
$ PAGE=seq3.html RUN=nq srun.sh \
    "S1 9961 400 n=20000&seed=1&then=1&ath=1&ext=1&skip=Rpage,Rnest-link,Fdoc&every=250" \
    ... seed=2,3,4 ... \
    "GC3 9965 500 n=20000&seed=1&then=1&ath=1&ext=1&gc=1&gcmax=60&skip=Rpage,Rnest-link,Fdoc&every=250" \
    "C1 9966 400 n=20000&seed=1&then=0&skip=Rpage,Rnest-link,Fdoc&every=250"
```

| arm | seed | executed | FontFace win. (`then`) | `Animation` (`ath`) | clone getters | IDB getters | deliveries | records | `moP` removed | frames killed | worker term. | `ms` | sanitizer |
|-----|------|----------|------------------------|---------------------|---------------|-------------|------------|---------|---------------|---------------|--------------|------|-----------|
| `S1` | 1 | 83,634 | 6,692 | 3,226 | 3,915 | 2,364 | 1,999 | 140,704 | 702 | 2,894 | 64 | 144,596 | none |
| `S2` | 2 | 83,627 | 6,704 | 3,145 | 3,747 | 2,457 | 1,999 | 140,468 | 707 | 2,913 | 64 | 142,661 | none |
| `S3` | 3 | 83,560 | 6,645 | 3,152 | 3,944 | 2,273 | 1,999 | 142,225 | 712 | 2,895 | 64 | 142,889 | none |
| `S4` | 4 | 83,869 | 6,832 | 3,252 | 3,991 | 2,438 | 1,999 | 142,421 | 687 | 3,015 | 64 | 145,785 | none |
| `GC3` | 1 | 83,634 | 6,692 | 3,226 | 3,915 | 2,364 | 1,999 | 140,704 | 702 | 2,894 | 64 | 214,317 | none |
| `C1` | 1 | 83,634 | 0 | 0 | 3,915 | 2,364 | 1,999 | 136,014 | 0 | 0 | 0 | 110,147 | none |

`S1`, verbatim:

```
done&op=Rplain&rounds=20000&then=6692&gc=0&gcalive=&ms=144596&fc=12&cr=2&lk=7&sc=6&eh=60&ath=3226&ith=0&frm=2894&wterm=64&wecho=2267&an=4&fr=0&killed=0&ktry=0&kerr=0&nofe=0&clh=3915&clok=3915&clerr=0&ikh=2364&ikok=2364&ikerr=0&moh=1999&mors=140704&mod=702&moi=1&mn=12971&moir=0
```

`EXIT=124` in every arm (that is how every run of this harness ends — `docs/65`, Attempt 11); the
`done` beacon is the completion witness and all six have it. Every arm reports all **37 census lines**,
**`e=0` everywhere**, and `access: none` — `grep -a -cE "AddressSanitizer|RELEASE_ASSERT|Zapped|zapped"
/tmp/S_S{1,2,3,4}.log /tmp/S_GC3.log /tmp/S_C1.log` returns 0 for all six.

**Determinism, checked against a model and not assumed.** `model_seq.py` was extended with the six
`docs/86`/`docs/87` weights; for seed 1 it predicts the page's own census exactly —
`census: 37/37 ops match, model total 83634, page total 83634` — which is what makes `only=`/`skip=`
a valid minimiser, and what allows the round that a beacon left off in to be replayed offline.

**Totals.** Four required arms: **334,690 operations** and **64,777 synchronous in-engine windows**
(26,873 inside `CSSFontFace::setStatus`, 12,775 inside `WebAnimation::finish`/`finishNotificationSteps`,
15,597 inside the clone serializer's `getProperty`, 9,532 inside `createIDBKeyFromValue`), plus **7,996
delivery-loop windows** (one `MutationObserver` callback per 10-round task) and 11,717 frame
destructions and 256 worker terminations inside those windows. Six arms: **501,958 operations**,
**87,253 windows**, 11,994 deliveries, 0 sanitizer reports, 0 exceptions.

**`GC3` — a collection inside the windows.** Same seed and stream as `S1` (`gc=1&gcmax=60`) and it
reports the *identical* `then=6692`, `ath=3226`, `clh=3915`, `ikh=2364`, `mn=12971` and `mors=140704`
as `S1` — a determinism check across a run that churns 400k objects inside 60 windows — while taking
214 s against 145 s. `gcalive=8/8` at the end, 0 reports.

**`C1` — the window axis off.** `then=0`, same stream: `then=0&ath=0`, and it is the most informative
control here, see §6.

---

## 6. What this null covers — and the two numbers that bound it

**It covers**, by construction and by the counters:

- the **serializer's walk** with page script at depth 24-43 (15,597 windows), i.e. exactly the stage
  `docs/77` closed on paper because every walked object is also in `m_objectPool` — and `clok=clh` in
  every arm says the walk completed every time;
- the **key builder's hole path** (9,532 windows), the `Vector<JSArray*>` with capacity 0 that
  `docs/78` measured by hand, now driven with the docs/65 arming inside the getter;
- the **delivery loop** (7,996 callbacks, 565,818 records, 2,808 removals of the observed node from
  inside the delivery) — and, because the callback loads a face, **`setStatus` inside
  `MutationObserver::deliver`**;
- the whole `docs/86` alphabet underneath it (26,873 FontFace windows, 12,775 Animation windows,
  11,717 frame destructions, 256 worker terminations), and a collection inside 60 of the windows.

**The first number that bounds it: `moir=0`.** 12,862-13,261 `moNudge()` mutations per arm were made
*inside* engine frames and **not one delivery happened inside the round that queued it** — all 1,999
deliveries in each arm sit at a batch multiple (`q=10, 20, …`). So the `MutationObserver` surface is a
*delivery-loop* window, never nested in the round's own frame; the instrument gets the nesting it
wants only by having the callback create the frame (`moload`). Anyone reading a future sweep in this
area should assume the same and count deliveries separately from windows, as the table here does.

**The second: `ith=0` in all four arms against `C1`'s 3,095.** With `then=1&ext=1` the second
document's own font window fired **zero** times in 20,000 rounds — `docs/86` measured 36 in the same
configuration — because there are now *two* windows that remove a frame from the pool on nearly every
entry (the FontFace window and the delivery), so the `Aframe` op spends its draws creating frames that
die before anything resolves in them. The second document is therefore covered in this run **as a
destruction target** (11,717 `frm`) and not as a font-resolution window; `C1`, where nothing is
killed, is the arm that shows the surface still works (`ith=3,095`). The fix `docs/86` already named
— split `ext` per surface — is now a three-way split (`extf`/`extw`/`extm`), and it is the next
action below.

**It does not cover**, and nothing above claims it:

- **`window.open` / a third Document class.** §1.2: no spelling is reachable from script on this
  build. A Page-teardown destruction path therefore remains unmeasured, and cannot be measured here.
- **the known bug**: `Fdoc` and the two known crashes are `skip`ped by construction (`Rpage`,
  `Rnest-link`, `Fdoc`), so their absence says nothing; §3 is what says the instrument would have
  seen them.
- **not a reclaim oracle.** The windows allocate freely (styles, frames, workers, clones, keys), so a
  reused slot says nothing about who took it. This is a crash hunt.
- cross-origin frames, `fetch`/XHR and streams, CSS Paint (compiled out), IDB *database* operations
  (only the key-builder entry point is driven), and worker-side WebCore code remain outside the
  alphabet.

---

## 7. Conclusions

1. **Three of the four surfaces are wired and measured, not read.** `structuredClone`'s getter runs
   inside the serializer (`cget in=1`, depths 24-43, `clok=clh` in every arm), `IDBKeyRange.only`
   really calls the hole getter inside `createIDBKeyFromValue` (`iget in=1`, `ikok=ikh`), and the
   observer's callback runs in `MutationObserver::deliver` with records and destruction inside it
   (`moh`/`mors`/`mod`) — including a `setStatus` frame hosted by the delivery itself (`moload`,
   `th0→th1`).
2. **The calibration still fires on the programme's own bug: 6/6 on the shipped page, 2 `WRITE` at
   `:595` and 4 `READ` at `:592`, one byte at base+`0x82`.** The observer moves the object's base by
   `0x100` and moves the fault with it.
3. **501,958 operations and 87,253 in-engine windows across the four surfaces — 0 sanitizer reports,
   0 exceptions, `access: none` 6/6.**
4. **The fourth surface `GOAL.md` named does not exist on this build**: five `window.open` spellings
   and a link click all return null, `showModalDialog` is `undefined`, and `_self` navigates the
   current document instead. That is a negative result with a source-level explanation, not a gap.
5. **Two structural limits are now measured rather than assumed**: a `MutationObserver` delivery
   never lands inside the round that queued it (`moir=0` against 12,971 nudges from engine frames),
   and `ext`'s frame-killing is now paid by two windows, which costs the second document its font
   window entirely (`ith=0` vs `C1`'s 3,095).

Logs on the build box: `/tmp/S_{K1..K6,W1..W3,M3,M4,S1..S4,GC3,C1}.log`, server logs
`/tmp/srv{9921,9922,9923,9953,9954,9971..9976,9981..9983,9961..9966}.log`, probe logs
`/tmp/srv{9921,9922,9923}.log`.
