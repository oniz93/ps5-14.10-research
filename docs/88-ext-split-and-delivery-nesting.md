# 88 — the `ext` split by surface, and a three-level frame inside the delivery loop

`GOAL.md` item 1. `docs/87` closed three surfaces and left two numbers that bound its null: **`moir=0`**
(a `MutationObserver` delivery never lands inside the round that queued it) and **`ith=0`** (the second
document's own font window fires zero times in 20,000 rounds, against 3,095 in the control where frames
persist). Both came from one knob: `ext` removed a frame *and* terminated the worker *and* drove the
delivery loop's destruction, so every arm that destroyed anything also emptied the frame pool.

This run splits that knob by surface — `extf` (the font / animation / clone / IDB windows' destructive
action), `extw` (worker termination), `extm` (the delivery loop's own destruction) — and adds the one
nesting `docs/87` measured (`moload`: a delivery hosting a `setStatus`) as a real three-level frame: the
delivery resolves a face **inside the second document** and removes the frame that owns it, in the same
delivery. Then it calibrates, wires one axis at a time, and sweeps four 20k arms.

Everything below is `run_nq.sh` (**quarantine off**) except §2, which is `run_asan_page.sh` (**quarantine
on**) — a fresh port per arm, scored from the **beacon log**. Page: `research/fuzz-cssom/seq4.html`
(md5 `aea291c7beb30d601aedb6780b5b52e5`, builder output 50,423 bytes), builder `build_seq4.py`
(md5 `75c3bc4a2644d291effd915192dea390`), model `model_seq.py` (md5 `b55b601a2bd9f9e58feba573a85ddf33`,
one row added). `seq3.html` is untouched (`6ccdf12569d4da03da27a236e411462e`, still what `docs/87`
quotes), as are `seq2.html` and `seq.html`.

---

## 1. The page: what changed, and why each anchor must occur once

`build_seq4.py` reads `seq3.html` and never edits it; a missing or duplicated anchor aborts the build.
Two changes:

**(a) the `ext` split.** The page now carries four independent variables, each defaulting to the old
shorthand so a `docs/86`/`docs/87` arm is still expressible:

```js
  var EXT = K('ext', '0') === '1';                    // shorthand: all three of the below
  var EXTF = K('extf', EXT ? '1' : '0') === '1';
  var EXTW = K('extw', EXT ? '1' : '0') === '1';
  var EXTM = K('extm', EXT ? '1' : '0') === '1';
  var MOF = K('mof', '0') === '1';
```

| knob | what it gates | where |
|------|---------------|-------|
| `extf` | delete a live `FontFace` + `extWindow()`'s **frame** removal; the srcdoc's `KILL` (the inner window removes its own frame); the Animation window's churn/`deleteRule`/`cancel`/layout | `Cclone`, `Ikey`, `Aframe` srcdoc, `installAth`, the `FontFace.prototype.then` window, `extWindow()` |
| `extw` | `wrk.terminate()`, capped at 64 per arm | inside `extWindow()`, so **any** window may still destroy a live script context |
| `extm` | the delivery loop's own destruction: remove `moP` (the observed node), churn the sheet, drop a live face, force layout | `mkMo`'s callback |
| `mof` | the delivery's nested frame (§1b) | `moFrame()`, called once per delivery |

Two call sites that used to be `if (EXT)` are now `if (EXTF || EXTW)`, so `extw=1&extf=0` still
terminates the worker inside the engine's frame while the frame pool stays alive — the combination
`docs/87` §6 said its single knob could not express. The delivery's hosted parent-realm face
(`moload`) and its `setStatus` are now **unconditional** (they used to sit inside `if (EXT)`): a nesting
witness that depends on the destructive knob is not a witness.

**(b) one new op and one function.** `Mofr` (weight 2) keeps a second-document frame in the pool and
nudges the observer; the delivery callback then calls `moFrame()`, which:

1. picks the first connected frame and returns unless `W.__ran` is set (the srcdoc's own first statement);
2. inserts `@font-face{font-family:zzN<k>;src:local("DejaVu Sans")}` into that document's `<head>`,
   forces its layout (so the **second** `CSSFontSelector` builds the face), finds the face in
   `d.fonts` and calls `f.loaded` then `f.load()`;
3. reads the parent-side inner-window counter (`window.__ith`) either side of that call, removes the
   frame element, and emits `mofr&h=<delivery>&found=&st=&ith0=&ith1=&rem=&ran=`.

So the ordering under test is **`MutationObserver::deliver` → `CSSFontFace::setStatus` (the inner
Document's face) → the inner realm's `FontFace.prototype` getter → `setStatus` continues on a Document
that is now detached**, all inside one delivery. That is the three-level frame the action asked for; the
`ith0 → ith1` delta is the witness that the third level ran inside the second.

**Provenance and syntax, re-asserted on the output, not assumed** — the builder prints:

```
page script: 50046 bytes, syntax OK
inner srcdoc script: 816 bytes, syntax OK
wrote research/fuzz-cssom/seq4.html (50423 bytes, md5 aea291c7beb30d601aedb6780b5b52e5)
ops present: 38 (29 array + 9 pushed = 38)
provenance: 29 docs/84 ops present, 6 docs/86/87 op blocks present (5932 bytes verbatim)
```

The six `docs/86`/`docs/87` op blocks are extracted from `seq3.html` and required to appear verbatim in
`seq4.html` **after** the two intended substitutions (`Cclone`'s and `Ikey`'s `if (EXT)`), so a silent
edit anywhere else in those ops aborts the build. Both syntax checks have a negative control, run on a
copy of the built page:

```
NC1 caught: page script has a syntax error:
NC2 caught: inner srcdoc script has a syntax error:
```

(NC1 inserts a brace into `moNudge`, NC2 inserts one into the **srcdoc string** — the exact defect
`docs/86` shipped once, where nothing on the page could see it.)

**Determinism.** `model_seq.py` gained `("Mofr", 2)`; for seed 1 it reproduces the page's own census
exactly, which is what makes `only=`/`skip=` a valid minimiser:

```
$ python3 model_seq.py --seed 1 --rounds 20000 --skip Rpage,Rnest-link,Fdoc --census-file /tmp/census_S1.txt
census: 38/38 ops match, model total 83805, page total 83805
```

---

## 2. Calibration: `cal=1` still reproduces `docs/65`, 6 of 6, on the new page

`cal=1` returns from the IIFE before the rounds loop, so neither the new op nor `moFrame` can run in a
cal arm. Quarantine **on**, six runs, fresh port each, three with the observer installed and three
without:

```
$ PAGE=seq4.html RUN=asan srun.sh "K1 9991 45 n=1&cal=1&mob=0" … "K6 9996 45 n=1&cal=1&mob=1"
```

| arm | `mob` | flavour | frame |
|-----|-------|---------|-------|
| `K1` | 0 | `READ of size 1`, `operator()`, `:592` | `0x610000046bc2` |
| `K2` | 0 | `READ of size 1`, `:592` | `0x610000046bc2` |
| `K3` | 0 | `READ of size 1`, `:592` | `0x610000046bc2` |
| `K4` | 1 | **`WRITE of size 1`**, `CSSFontFace::setStatus`, `:595` | `0x610000046cc2` |
| `K5` | 1 | **`WRITE of size 1`**, `:595` | `0x610000046cc2` |
| `K6` | 1 | `READ of size 1`, `:592` | `0x610000046cc2` |

**6/6, 2 `WRITE` / 4 `READ`, every fault at base + `0x82` (`m_status`), and the observer shifts the
object's base by `0x100` and the fault with it** — the same result `docs/87` §3 measured on `seq3.html`.
`K1` (abridged: the report's own paths shortened to `css/…`, frames `#3`/`#4` dropped):

```
==705161==ERROR: AddressSanitizer: heap-use-after-free on address 0x610000046bc2 at pc 0x7f0e85bcff25
SUMMARY: AddressSanitizer: heap-use-after-free .../css/CSSFontFace.cpp:592 in operator()
  | READ of size 1 at 0x610000046bc2 thread T0
  |     #0 operator() css/CSSFontFace.cpp:592
  |     #1 iterateClients<...setStatus(Status)::<lambda(Client&)> > css/CSSFontFace.cpp:58
  |     #2 WebCore::CSSFontFace::setStatus(WebCore::CSSFontFace::Status) css/CSSFontFace.cpp:591
  |     #5 WebCore::FontFace::loadForBindings() css/FontFace.cpp:361
```

---

## 3. Wiring, one axis at a time

**(a) The nesting, isolated.** `only=Mobs,Mofr&mof=1&extm=1&extf=0&extw=0&then=1&dbg=1&n=300` —
only the observer and the new op run, so nothing but the delivery can drive a second document. The
`done` beacon (`/tmp/srv10001.log`):

```
done&op=Mobs&rounds=300&then=24&...&ith=11&frm=0&wterm=0&wecho=0&an=0&fr=2&...&moh=24&mors=146&mod=13
    &moi=1&mn=45&moir=0&mofd=11&mofrem=11&mofseen=11&mofearly=11
```

and the first frames of the run, verbatim:

```
mofop&frames=1&mof=1
mofop&frames=2&mof=1
mocb&h=1&n=9&t=attributes&q=30&gd=0
then&k=FontFace&fam=zzM1
mocb&h=3&n=5&t=childList&q=60&gd=0
then&k=FontFace&fam=zzM3
ithen&i=1
mofr&h=3&found=1&st=loaded&ith0=0&ith1=1&rem=1&ran=1
mocb&h=4&n=14&t=attributes&q=70&gd=0
then&k=FontFace&fam=zzM4
ithen&i=1
mofr&h=4&found=1&st=loaded&ith0=1&ith1=2&rem=1&ran=1
```

(`st=loaded` is the inner face's status after the `load()` returned, and `rem=1` is the frame removal,
both inside the same delivery). Every ready
delivery produced **exactly one** inner window: `mofd=11` drives, `ith=11`. `mod=13` shows the delivery
removing the observed node in 13 of its 24 callbacks, and `moload&h=1&th0=0&th1=1` (also in this log)
shows the parent-realm face resolving inside the delivery — the `docs/87` nesting, now with the
destructive knob off.

**(b) The axis control.** The same arm with `mof=0`:

```
done&op=Mobs&rounds=300&then=24&...&ith=0&frm=0&wterm=0&...&moh=24&mors=146&mod=13&moi=1&mn=45&moir=0
    &mofd=0&mofrem=0&mofseen=0&mofearly=0
```

Same op stream (`census&op=Mobs&n=43`, `census&op=Mofr&n=21` in both arms), same deliveries (`moh=24`),
same records (`mors=146`), same `mod=13` — and `ith=0`. **One variable, `mof`, and the whole second
level disappears.**

**(c) The other direction — the destructive knob is what suppresses it.** The same arm with
`extf=1&extw=1` added:

```
done&op=Mobs&rounds=300&then=24&...&ith=0&frm=36&...&mod=13&...&mofd=0&mofrem=0&mofseen=0&mofearly=0
```

`frm=36` frame destructions, `ith=0`, and `mofseen=0`: with `extf=1` the delivery's own `extWindow()`
has already emptied the pool before `moFrame()` looks, so no frame is ever ready to drive. That is
`docs/87`'s `ith=0` reproduced on this page and attributed to one knob.

### The instrument defect this section found, and the fix

The **first** build of the page (`715f04fb8218bd31b6d296a0c371945e`) ran the same arm and returned
`ith=1` against `mofd=20`, with beacons like `mofr&h=1&found=1&st=loaded&ith0=0&ith1=0&rem=1`: the face
was found, it reached `loaded` synchronously, and **nobody was watching**. The cause is that an iframe
has a `contentDocument` before its `srcdoc` is parsed — WebKit hands out the initial empty document,
which has `fonts`, `head` and `body` but not the accessor, because the accessor is installed by the
srcdoc's own `<script>`. Driving that document loads a face whose resolve reads `then` from a realm
where no accessor exists.

The fix is a readiness guard, not a timing tweak: `moFrame()` now returns unless `W.__ran` is set (the
srcdoc's first statement), counting the skip in `mofearly`. Measured on the shipped build: `mofd=11`,
`ith=11` — every drive that was allowed to run fired exactly one window, and the skipped deliveries are
counted instead of being silently wasted (`mofearly=796` per 20k arm, §4). The two builds differ only in
that guard; the first build's numbers are quoted above so the correction is checkable.

---

## 4. The sweep: four seeds × 20,000 rounds

```
$ PAGE=seq4.html RUN=nq srun.sh \
    "S1 10011 400 n=20000&seed=1&then=1&ath=1&extf=0&extw=1&extm=1&mof=1&skip=Rpage,Rnest-link,Fdoc&every=250" \
    … seeds 2, 3, 4 …
    "S5 10015 400 n=20000&seed=1&then=1&ath=1&extf=1&extw=1&extm=1&mof=1&skip=…"     # all-on contrast
    "GC4 10016 500 n=20000&seed=1&then=1&ath=1&extf=0&extw=1&extm=1&mof=1&gc=1&gcmax=60&skip=…"
    "C2 10017 400 n=20000&seed=1&then=0&ath=0&extf=0&extw=1&extm=1&mof=1&skip=…"
```

| arm | seed | executed | FontFace (`then`) | `Animation` (`ath`) | clone getters | IDB getters | **2nd doc (`ith`)** | deliveries | records | `moP` removed | delivery drives | frames removed in delivery | too early | frame kills | worker term. | `ms` | sanitizer |
|-----|------|----------|-------------------|---------------------|---------------|-------------|---------------------|------------|---------|---------------|----------------|---------------------------|-----------|-------------|--------------|------|-----------|
| `S1` | 1 | 83,805 | 6,526 | 6,248 | 3,748 | 2,451 | **2,828** | 1,999 | 135,364 | 681 | 1,191 | 1,191 | 796 | 0 | 64 | 143,824 | none |
| `S2` | 2 | 83,599 | 6,677 | 6,092 | 3,915 | 2,340 | **2,783** | 1,999 | 140,446 | 706 | 1,187 | 1,187 | 801 | 0 | 64 | 144,623 | none |
| `S3` | 3 | 83,654 | 6,679 | 6,168 | 3,891 | 2,352 | **2,737** | 1,999 | 143,370 | 674 | 1,190 | 1,190 | 796 | 0 | 64 | 144,912 | none |
| `S4` | 4 | 84,036 | 6,643 | 6,272 | 3,939 | 2,400 | **2,761** | 1,999 | 140,627 | 709 | 1,188 | 1,188 | 796 | 0 | 64 | 144,790 | none |
| `S5` | 1 | 83,805 | 6,526 | 3,124 | 3,748 | 2,451 | **0** | 1,999 | 135,364 | 681 | 0 | 0 | 0 | 6,049 | 64 | 153,577 | none |
| `GC4` | 1 | 83,805 | 6,526 | 6,248 | 3,748 | 2,451 | **2,828** | 1,999 | 135,364 | 681 | 1,191 | 1,191 | 796 | 0 | 64 | 216,700 | none |
| `C2` | 1 | 83,805 | 0 | 0 | 3,748 | 2,451 | **2,828** | 1,999 | 130,840 | 681 | 1,191 | 1,191 | 796 | 0 | 64 | 123,716 | none |

`S1` (one line in the log, rewrapped here):

```
done&op=Gsel&rounds=20000&then=6526&gc=0&gcalive=&ms=143824&fc=12&cr=0&lk=5&sc=6&eh=158&ath=6248&ith=2828
 &frm=0&wterm=64&wecho=2251&an=4&fr=2&killed=0&ktry=0&kerr=0&nofe=0&clh=3748&clok=3748&clerr=0&ikh=2451
 &ikok=2451&ikerr=0&moh=1999&mors=135364&mod=681&moi=1&mn=14290&moir=0&mofd=1191&mofrem=1191&mofseen=1191
 &mofearly=796
```

`EXIT=124` in every arm (that is how every run of this harness ends — `docs/65`, Attempt 11); the `done`
beacon is the completion witness and all seven have it. Every arm reports all **38 census lines**,
each with `e=0` (measured: `lines=38 e0=38` for all seven census dumps),
**`e=0` everywhere**, and

```
$ grep -acE "AddressSanitizer|RELEASE_ASSERT|Zapped|zapped" /tmp/S_{S1,S2,S3,S4,S5,GC4,C2}.log
/tmp/S_S1.log:0  /tmp/S_S2.log:0  /tmp/S_S3.log:0  /tmp/S_S4.log:0
/tmp/S_S5.log:0  /tmp/S_GC4.log:0  /tmp/S_C2.log:0
```

**Totals.** Four required arms: **335,094 operations** and **87,450 synchronous in-engine windows** —
76,341 in the parent realm (26,525 `setStatus`, 24,780 `Animation`, 15,493 clone serializer, 9,543 IDB
key builder) and **11,109 in the second document** — plus **7,996 deliveries** carrying **559,807
records**, 2,770 removals of the observed node from inside the delivery, and **4,756 inner font
resolutions whose frame was removed inside the same delivery**. Seven arms: **586,509 operations**,
**134,127 windows** (16,765 of them in a second document), 13,993 deliveries, 961,375 records, 7,138
delivery-driven frame removals, 448 worker terminations, **0 sanitizer reports, 0 exceptions**.

**`S5` — the same seed with `extf=1`.** One knob apart from `S1`, and the difference is exactly the
coupling `docs/87` named: `ath` **halves** (3,124 vs 6,248 — `cancel()` inside the animation window
suppresses the second resolve per `finish()`, `docs/86` §3), `ith` goes **2,828 → 0**, `frm` 0 → 6,049,
`mofd` 1,191 → 0, and everything the font side does not own is identical (`then=6526`, `clh=3748`,
`ikh=2451`, `mod=681`, `mors=135364`). That is the split's justification, measured rather than argued.

**`GC4` — a collection inside the windows.** Same seed and stream as `S1` with `gc=1&gcmax=60`, and it
reports the *identical* `then=6526`, `ath=6248`, `ith=2828`, `clh=3748`, `ikh=2451`, `mofd=1191`,
`mors=135364` while taking 216.7 s against 143.8 s. The witness is weaker than `docs/87`'s and is
recorded as such: of the first six sampled windows, **one** collected (`gcprobe&pre=8/8&post=0/8&h=5`)
and five did not (`post=8/8` at `h=1..4,6`); `gcalive=8/8` at the end, 0 reports. On this page the
churn does not force a collection inside every window, so this arm does **not** claim "a collection
inside 60 windows" — it claims one observed collection inside a window and 60 churns.

**`C2` — the window axis off.** `then=0&ath=0`, same stream: `then=0&ath=0` and **`ith=2828`, `mofd=1191`
— unchanged**. The second document's accessor is installed by its own srcdoc, so it does not depend on
the parent's `then` knob, and the delivery's nesting does not either. That is the control that keeps
`ith` from being read as a proxy for the parent window.

---

## 5. What this null covers — and what it does not

**It covers**, by construction and by the counters:

- **the delivery loop with a second document nested inside it** — 4,756 inner faces resolved from
  inside `MutationObserver::deliver`, each one opening the inner realm's getter (1:1 in the isolated
  arm) and each one followed by the removal of the frame that owns the Document, in the same delivery;
- **the second document as a font-resolution surface**, which `docs/87` could not reach (`ith=0`): now
  11,109 windows across the four arms, 2,828 in a single arm, and 0 again in `S5` where `extf` kills
  the frames — so the number is attributable to the split and not to the page drifting. `ith` is the
  **union** of the delivery's drives and `Aframe`'s; the delivery's own share is `mofd` (1:1 in the
  isolated arm, §3a), and §6.3 states the split of the two;
- the parent-realm face hosted by the delivery (`moload`, `th0→th1` in every arm), now measured with the
  destructive knob **off**, i.e. the nesting witness no longer depends on it;
- the whole `docs/86`/`docs/87` alphabet underneath: 26,525 `setStatus` windows, 24,780 `Animation`
  windows, 15,493 clone-serializer getters, 9,543 IDB key-builder getters, 448 worker terminations;
- four seeds, and a collection inside a window (1 of the 6 sampled, §4).

**It does not cover**, and nothing above claims it:

- **the `docs/65` free inside the second document.** `moFrame()` inserts a rule and loads the face, and
  the inner getter only forces layout: no inner stylesheet-collection change happens inside the inner
  `setStatus`, so `CSSFontSelector::buildCompleted()` never frees the inner face there. The nesting is
  an **ordering** instrument (delivery → inner `setStatus` → inner getter → detach), not a second
  arming of the bug.
- **`moir=0` is unchanged**: 13,993 deliveries, every one at a batch multiple. A record queued inside a
  round's own C++ frame is still not drained there; `mof` changes what a delivery *does*, not when it
  happens.
- **`mofearly=3,189`** across the four arms: roughly one delivery in 2.5 arrives before its frame's
  srcdoc has parsed, is skipped, and (in the arms where the pool is otherwise empty) creates the next
  frame. Those deliveries do no work; the counter is there so the loss is visible.
- **frames are cheap here, not shaped**: 4,756 frames are created and destroyed inside deliveries, so
  these arms allocate documents heavily. They are a crash hunt, not a reclaim oracle (`docs/85` §6).
- the known bug and the two known crashes are `skip`ped by construction (`Fdoc`, `Rpage`,
  `Rnest-link`); §2 is what says the instrument would have seen them.
- cross-origin frames, `fetch`/streams, IDB **database** operations (only the key builder is driven) and
  worker-side WebCore code remain outside the alphabet — unchanged from `docs/87` §6.

---

## 6. Conclusions

1. **`ext` is now three variables and the coupling is gone, measured both ways.** `extf=0&extw=1`
   destroys a live script context inside the engine's frame while keeping the frame pool alive
   (`wterm=64`, `frm=0`, `ith=2,828`); `extf=1` on the same seed empties the pool and the same counter
   reads `0` (`S5`), with every other counter identical.
2. **The three-level frame exists and is witnessed**: `mofr` reports `ith0 → ith1` = +1 around the
   inner `f.load()`, `rem=1` for the frame removal, `st=loaded`, and `mofd=11`/`ith=11` in the isolated
   arm. `mod=13` in the same arm shows the delivery's own destruction running alongside it.
3. **The second document is a window surface again**: 11,109 windows over the four arms against
   `docs/87`'s 0, and the isolated arm shows the delivery's share is exact (`mofd` drives = `ith`
   windows); `C2` shows it is independent of the parent's `then`.
4. **586,509 operations, 134,127 in-engine windows, 0 sanitizer reports, 0 exceptions, `access: none`
   in all seven arms.**
5. **One instrument defect found and fixed, with both builds quoted**: an unguarded `moFrame` drove the
   initial empty document (before the srcdoc's script ran) and resolved faces where no accessor existed
   (`ith=1` against `mofd=20`); the `W.__ran` guard plus the `mofearly` counter is the fix, and every
   allowed drive now fires a window.
6. **The GC arm is weaker than `docs/87`'s on this page**: one collection inside a window out of six
   sampled, not a collection in every window. Recorded as measured, not carried over.

Logs on the build box: `/tmp/S_{K1..K6,W1b,W2b,W3b,S1..S4,S5,GC4,C2}.log`, server logs
`/tmp/srv{9991..9996,10001..10003,10011..10017}.log`, census dumps `/tmp/census_{10011..10017}.txt`.
