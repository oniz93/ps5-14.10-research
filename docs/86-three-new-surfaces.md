# 86 — the three surfaces docs/85 could not reach: a second document, `Animation`'s resolve windows, and a worker

`GOAL.md` item 1, second half. `docs/85` closed the sequence-shaped sweep on **one** document and named its own
boundary: no iframe, no `Animation`, no worker. Those are exactly the sites the earlier audits closed *on paper*
(`docs/73` read `FrameLoader`'s tail, `docs/74` read seven `WebAnimation` resolve sites and measured two by hand,
`docs/75` read `WorkerGlobalScope::close`). This document gives the instrument those three surfaces, verifies each
one is really wired (a window that fires, a context that is really destroyed), re-runs the calibration, and then
sweeps four seeds.

Everything is from `run_nq.sh` (**quarantine off**) except the calibration, which is `run_asan_page.sh`
(**quarantine on**) — a fresh port per arm after `pkill -f "[h]ttp.server"`, scored from the **beacon log**.
Pages: `research/fuzz-cssom/seq2.html` (md5 `2c3f6a900c0b5cb71879f399cbad2faf`), builder `build_seq2.py`
(md5 `962fd398123ca57261f75d0ec6d9538a`), probes `caps{,2,3,4}.html`. `seq.html` is untouched
(md5 `6004e0e4e7fe99b22538095e5cbcd7ff`, still what `docs/85` quotes).

---

## 1. Before writing an op: what the build actually has

`research/fuzz-cssom/caps.html` (md5 `80d3259f5aa617b911e74d33008e606e`) asks the three questions in one page and
answers each with a beacon. `PAGE=caps.html RUN=nq srun.sh "C2 9891 40 n=1"`:

```
caps js=1
caps Worker=function Blob=function URL=function createObjectURL=function structuredClone=function MessageChannel=function
caps Animation=function KeyframeEffect=function CSSTransition=function getAnimations=function srcdoc=true
anim ok ctor=Animation protoHit=true
anim proms ready=Promise fin=Promise ps=running
anim then hit=1 on=Animation inFinish=1 ps=finished
anim then hit=2 on=Animation inFinish=1 ps=finished
anim post hits=2 ps=finished
frame doc=yes fonts=1 sameOrigin=true
frame found=1 fc=1
frame then hit=1 on=FontFace
frame post st=loaded then=1
frame removed=1
worker posted=1
worker echo n=64 len=undefined
worker echoed=1
worker terminated=1 echoed=1
done caps
```

All three surfaces exist, and the two mechanisms the ops need are already visible here: **`Animation.prototype.then`
fires twice inside `finish()`** (`inFinish=1`, `ps=finished` both times), and a `FontFace` inside a second document
resolves with the parent's `then` accessor on that document's `FontFace.prototype` (`frame then hit=1`). (The
`len=undefined` is a bug in that probe's own payload, not in the engine — `caps2.html` fixed it.)

**Which realm's prototype is consulted** matters for where the accessor must be installed, so `caps2.html`
(md5 `18b8554a240482fdb8e3c3efcc095dc2`) measures it. An accessor installed *inside* the iframe, driving the load
from the parent:

```
q1 ran=true&ok=true&err=-
q3 found=1&fc=1&st=unloaded
pthen&i=1
ithen&i=1
q3 protoParent=false&protoInner=true&thenP=undefined&thenI=undefined&sameCtor=true
ithen&i=2
q2 post st=loaded&ith=2&phits=1
q4 late ith=2&phits=1&ran=true
done caps2
```

`protoInner=true&protoParent=false`: the wrapper `d.fonts.forEach` hands the parent belongs to the **inner** realm,
so the inner document's own `FontFace.prototype` is what a resolve consults, and the inner accessor fires **twice**
inside one `f.load()`. That is why `Aframe` installs its window from a `<script>` inside the srcdoc rather than from
the parent.

---

## 2. The instrument: `seq2.html`, built from `seq.html` at anchors that must occur once

`build_seq2.py` reads `seq.html` (never edits it) and inserts, at six anchors that each must occur exactly once
(abort otherwise): the `ath`/`ext` knobs, the three ops, the extended-surface machinery, one line in the FontFace
window (`if (EXT) extWindow();`), `if (ATH) installAth();` before the boot beacon, and the extra counters in the
`done` beacon. It re-asserts provenance on the output: `build_seq.extract_ops(fuzz.html)` — the 29 `docs/84`
operations — must appear in `seq2.html` verbatim, and it does. **34 operations** = 29 + `Fnew-good` + `Fdoc` +
`Aanim` + `Aframe` + `Aworker`.

The three new ops, each a different surface:

| op | weight | what it drives | window it opens |
|----|--------|----------------|-----------------|
| `Aanim` | 4 | `el.animate(...)`, materialise `ready`+`finished`, `play()`, then `finish()` in the same task | `Animation.prototype.then`, i.e. `m_readyPromise->resolve(*this)` at `WebAnimation.cpp:873` and `finishNotificationSteps`' `m_finishedPromise` at `:1003` |
| `Aframe` | 4 | creates an iframe whose srcdoc carries its own `then` accessor, or drives the oldest frame's document (a second `CSSFontSelector`/`FontFaceSet`) | the inner document's `FontFace.prototype.then` |
| `Aworker` | 3 | one blob worker, kept alive, posted an allocating message | none of its own — it is the *subject*: `ext=1` terminates it from inside the window |

`ext=1` is the destructive half, and it is a single knob on purpose: the FontFace and Animation windows then remove
a frame from the pool and `terminate()` the worker, inside the engine's frame. With `ext=0` the three surfaces are
created and resolved but nothing is destroyed, so the `ext` axis is one variable.

### Two defects the build itself had, and the witness for each

Both were found by measurement, not by reading, and both are worth carrying because they are silent:

1. **The srcdoc's inner script had a brace error** — `...(new Image()).src=...;}catch(e){}}' +` closed the wrong
   block, so the whole inner script was a `SyntaxError` and the second-document surface **did nothing at all**. The
   symptom was `frdrive ... found=1&st=unloaded&ran=0` and `ith=0` in both FR arms: the face loaded
   (`frpost st=loaded`) with no window. Extracting the srcdoc and running `node --check` on it reproduces it
   exactly (`SyntaxError: Unexpected token 'catch'`). `build_seq2.py` now evaluates the page's srcdoc expression
   with node and syntax-checks the inner script, and that check has its own sensitivity control: dropping one
   brace from a copy of the built page makes the builder exit with
   `inner srcdoc script has a syntax error`. The inner script also sets `window.__ran=1` and `frdrive` reports
   `ran=`, so a future break shows up in the log instead of in a null.
2. **Killing a frame stalled the pool.** After the inner window removed its own `<iframe>`, `frames` still held a
   detached element whose `contentWindow` is null, so every later `Aframe` draw returned at the guard and — because
   the pool was already at `MAXFR` — no new frame was ever created. Measured before the fix: FR2 gave `ith=1` and
   then nothing, against FR1's 54. The fix is a sweep at the top of the op that drops `!isConnected` frames, and
   that sweep is also the **parent-side witness** of the kill (`frm`).

### One observation about the inner context that is *not* explained

The instrument's kill branch increments a parent counter *after* `removeChild`, and in the instrument that counter
never lands: FR2c reports `ktry=23&killed=0&nofe=0&kerr=0` while the parent-side sweep sees `frm=23`. Isolated in a
single-frame page (`caps4.html`, md5 `f953257cb5175b1c5581fbae00244278`, which runs seq2's **exact** block with a
step marker between statements) the same block gives `step=5&ktry=1&killed=1&conn=false`: the removal is
synchronous, the statement after it runs, and the parent's `f.load()` still returns with `st=loaded`. So the removal
is real and the parent survives it; why the inner context's later writes do not reach the parent *in the fuzzer*
(but do in the isolated page) is unexplained, and nothing in this document rests on it. The kill is claimed only
from `frm`, which is measured in the parent.

---

## 3. Calibration: `cal=1` still reproduces `docs/65`, 6 of 6

`cal=1` returns from the IIFE before the rounds loop, so the three new ops cannot run in a cal arm and
`installAth()` is not called (`ATH=0`); the cal path's code is byte-identical to `docs/85`'s. Re-measured anyway,
because a ratio change is the stated alarm. Quarantine **on**, six runs, fresh port each:

```
$ PAGE=seq2.html RUN=asan srun.sh "CAL1 9861 45 n=1&cal=1" ... "CAL6 9866 45 n=1&cal=1"
```

| arm | port | flavour | frame |
|-----|------|---------|-------|
| `CAL1` | 9861 | `heap-use-after-free` — `READ of size 1`, `operator()`, `CSSFontFace.cpp:592` | `0x6100000469c2` |
| `CAL2` | 9862 | `READ of size 1`, `:592` | `0x6100000469c2` |
| `CAL3` | 9863 | **`WRITE of size 1`, `CSSFontFace::setStatus`, `:595`** | `0x6100000469c2` |
| `CAL4` | 9864 | **`WRITE of size 1`, `:595`** | `0x6100000469c2` |
| `CAL5` | 9865 | **`WRITE of size 1`, `:595`** | `0x6100000469c2` |
| `CAL6` | 9866 | `READ of size 1`, `:592` | `0x6100000469c2` |

**6/6 reproduce the bug, 0 clean, every fault at the same byte (base + `0x82` = `m_status`).** The split is
**3 WRITE / 3 READ**, where `docs/85` measured 2/6 and 4/6. That difference is the client-order coin flip
`docs/65` already recorded (the freeing client last → the `:595` write; otherwise the next iteration reads
`m_status` at `:592`), and six samples of a ~1/2 coin land 3/3 or 2/4 with probability ≈0.6. The claim this
supports is the one that matters for the sweep: **the instrument is still sensitive to the bug it is aimed at, on
the same object and the same byte**, and the added ops are not on this code path at all.

---

## 4. Wiring, one axis at a time

**(a) `Animation`'s window.** `only=Aanim&ath=1&then=1&dbg=1&n=300` runs 53 `Aanim` ops. With `ext=0` the `done`
beacon reads `ath=106`; with `ext=1`, same stream, `ath=53`:

```
AN3 (ext=0)  done ... &then=0 ... &ath=106&ith=0&frm=0&wterm=0&wecho=0&an=4&fr=0&...  cr=1
AN4 (ext=1)  done ... &then=0 ... &ath=53 &ith=0&frm=0&wterm=0&wecho=0&an=4&fr=0&...  cr=0
```

Two windows per `finish()` — `m_readyPromise` (`:873`) and `m_finishedPromise` (`:1003`) — and **one** when the
window cancels the animation: `self.cancel()` inside the ready resolve makes `playState()` idle, so
`finishNotificationSteps` returns at its first line and the second window never happens. The DBG lines identify
the frame and the state at entry:

```
anim&ctor=Animation&ps=running&n=1
athen&on=Animation&in=1&ps=finished
animpost&ps=idle&ath=1
```

`in=1` is the op's own `IN_AANIM` flag, set around the `finish()` call: the window really runs inside `finish()`,
not in a later task. The control is the same page with `ath=0`: `ath=0` and `animpost&ps=finished` — no window, no
cancel (`AN0`).

**(b) A second document.** `only=Aframe&then=1&dbg=1&n=400`, 400 rounds:

```
FR1b (ext=0)  done ... &ith=56 &frm=0  &fr=2
FR2c (ext=1)  done ... &ith=23 &frm=23 &fr=1      (ktry=23, killed=0, kerr=0, nofe=0 — see §2)
```

`ith` counts inner-document windows (`window.__ith` on the parent, written by the inner getter).
`frdrive ... found=1&st=unloaded&ran=1&ithw=2` is the parent driving a face of the **second** selector and the
second document's own window firing. With `ext=1` every inner window removes its own frame element, and the
parent observes `frm=23` disconnections and recreates the pool; `caps3.html`
(md5 `175a36af4b80005259ef04852c4529da`) shows the single-shot shape:

```
p1 ran=true&conn=true
p2 found=1&st=unloaded
p3 threw=-&st=loaded&st4=5&ith=1&conn=false&kids=2
```

The whole kill sequence completed (`st4=5` is the step marker *after* `removeChild`), `fr.isConnected` is false
afterwards, and the parent's `f.load()` returned normally with `st=loaded`: **a Document was destroyed inside
`setStatus`, and the face kept resolving.**

**(c) A worker.** `only=Aworker&then=1&ext=1&n=300` echoes 31 messages (`wecho=31`). With an animation window in
the same run to do the destroying — `only=Aworker,Aanim&ath=1&then=1&ext=1&n=400`:

```
WK2  done&op=Aanim&...&ath=72&...&wterm=18&wecho=7&an=4&fr=0       census: Aanim n=72 e=0, Aworker n=42 e=0
```

18 live script contexts were terminated from inside an engine frame, and the next `Aworker` op created a new one
(`wecho=7` after the first terminations). The destruction is bounded at 64 per arm on purpose — a worker costs a
thread per creation, so an unbounded `terminate()`-per-window would turn a 20k sweep into a thread churn test.

---

## 5. The sweep: four seeds × 20,000 rounds, plus a GC arm and a windows-off control

```
$ PAGE=seq2.html RUN=nq srun.sh \
    "S1 9901 300 n=20000&seed=1&then=1&ath=1&ext=1&skip=Rpage,Rnest-link,Fdoc&every=250" \
    ... seed=2,3,4 ...
    "GC2 9905 500 n=20000&seed=1&then=1&ath=1&ext=1&gc=1&gcmax=60&skip=Rpage,Rnest-link,Fdoc&every=250" \
    "C0b 9906 300 n=20000&seed=1&then=0&skip=Rpage,Rnest-link,Fdoc&every=250"
```

| arm | seed | executed | FontFace win. | `Animation` win. | inner-doc win. | frames killed | worker term. | `ms` | sanitizer |
|-----|------|----------|---------------|------------------|----------------|---------------|--------------|------|-----------|
| `S1` | 1 | 83,074 | 5,123 | 3,570 | 36 | 2,848 | 64 | 101,214 | none |
| `S2` | 2 | 82,870 | 5,337 | 3,516 | 36 | 2,926 | 64 | 101,330 | none |
| `S3` | 3 | 82,905 | 5,340 | 3,416 | 37 | 2,782 | 64 | 101,230 | none |
| `S4` | 4 | 83,060 | 5,227 | 3,573 | 25 | 2,900 | 64 | 100,948 | none |
| `GC2` | 1 | 83,074 | 5,123 | 3,570 | 31 | 2,852 | 64 | 173,614 | none |
| `C0b` | 1 | 83,074 | 0 | 0 | 3,507 | 0 | 0 | 79,716 | none |

`S1`, verbatim:

```
done&op=Grange&rounds=20000&then=5123&gc=0&gcalive=&ms=101214&fc=13&cr=2&lk=1&sc=6&eh=60&ath=3570&ith=36&frm=2848&wterm=64&wecho=2536&an=4&fr=0&killed=0&ktry=36&kerr=0&nofe=0
```

`EXIT=124` in every arm (that is how every run of this harness ends — `docs/65`, Attempt 11); the `done` beacon is
the completion witness and all six have it. All 34 census lines are present in every arm, **`e=0` everywhere**,
and `access: none` — `grep -a -cE "AddressSanitizer|RELEASE_ASSERT|Zapped|zapped" /tmp/S_$TAG.log` returns 0 for all
six.

**Totals.** Four required arms: **331,909 operations**, **35,102 synchronous in-engine windows** (21,027 inside
`CSSFontFace::setStatus`, 14,075 inside `WebAnimation::finish`/`finishNotificationSteps`), 134 windows inside a
second document, 11,456 frame destructions and 256 worker terminations, all inside those windows. Six arms:
**498,057 operations and 43,795 windows**, 14,308 frame destructions, 320 worker terminations, **0 sanitizer
reports, 0 exceptions**.

**`GC2` — a collection inside the window.** Same seed and stream as `S1` (`gc=1&gcmax=60`). It reports the
identical `then=5123`, `ath=3570`, `wecho=2536` and the identical executed count 83,074 as `S1`, which is a
determinism check across a run that churns 400k objects inside 60 windows; the arm takes 173 s against 101 s.
`gcalive=8/8` at the end and the per-window witnesses are in the log — `gcprobe&pre=8/8&post=0/8&h=1` is a
collection inside the first churning window that collects all eight decoys, the other five witnesses read
`pre=8/8&post=8/8`; 0 reports.

**`C0b` — the window axis off.** `then=0`, same seed and stream, same 83,074 operations, `then=0&ath=0`, 0
reports. It is also the most informative control in this document, see §6.

---

## 6. What this null covers — and the one number that bounds it

**It covers**, by construction and by the counters:

- the `docs/65` window at the same scale as `docs/85` (21,027 entries), and — new here — **14,075 entries into
  `WebAnimation`'s resolve frames**, each of which performs a real stylesheet-collection change, a `deleteRule(0)`
  and a forced layout *inside* `finish()`, plus `cancel()` on the animation being resolved;
- **a second Document with its own `CSSFontSelector` and `FontFaceSet`**, driven from the parent, with its own
  window firing 134 times, and **11,456 frame destructions inside engine frames** (the `docs/73` shape, now inside
  a font-load window rather than a navigation tail);
- **256 live `ScriptExecutionContext` terminations inside engine frames** (the `docs/75(b)` shape, destroyed
  rather than ref'd);
- sequences of 3–6 operations with no task boundary, a collection inside the window (`GC2`), and 20,000 forced
  layouts per arm.

**The number that bounds it: `C0b` reports `ith=3507` where `S1` reports `ith=36`.** With the windows off, the
`Aframe` op drives a persistent second document on almost every draw and its window fires 3,507 times; with
`ext=1`, the *outer* window removes a frame on nearly every one of its 8,693 entries, so the pool is almost always
empty or unparsed and the op spends its draws creating rather than resolving. The second-document surface is
therefore covered **as a destruction target 11,456 times** and **as a font-resolution window only 134 times** — the
same order as `C0b`'s 3,507 only when `ext` is off. A future run that wants both at once needs two knobs
(`extf`/`extw`) or a "kill every Nth window" rule; coupling them was the cost of keeping `ext` a single variable.

**It does not cover**, and nothing above claims it:

- **the known bug**: `Fdoc` and the two known crashes are `skip`ped by construction (`Rpage`, `Rnest-link`), so
  their absence says nothing; §3 is what says the instrument would have seen them.
- **not a reclaim oracle.** The windows allocate freely (styles, frames, workers), so a reused slot says nothing
  about who took it. This is a crash hunt.
- cross-origin frames, `window.open` (a third Document class), `structuredClone`, `fetch`/XHR, IndexedDB,
  `MutationObserver`, and CSS Paint (compiled out) remain outside the alphabet.
- the worker runs no WebCore DOM code: it is a context to destroy, not a second WebCore surface.

---

## 7. Conclusions

1. **The three surfaces are wired and measured, not read.** `Animation.prototype.then` fires **inside** `finish()`
   (`in=1`, `ps=finished`), twice per call with `ext=0` and once with `ext=1`; a second document's `FontFace`
   resolution runs page script in the inner realm (the wrapper is inner-realm — `protoInner=true`), and its window
   can destroy the frame that owns it while `setStatus` is still running, after which the parent's `f.load()`
   returns `st=loaded`; a blob worker is terminated from inside the same frames and recreated by the next op.
2. **The calibration still fires on the programme's own bug: 6/6, 3 WRITE at `:595` and 3 READ at `:592`, one
   byte (`base+0x82`).** The 3/3 split against `docs/85`'s 2/4 is the client-order coin flip, and the cal path is
   structurally untouched by the extension.
3. **498,057 operations, 43,795 synchronous in-engine windows across three new surfaces — 0 sanitizer reports, 0
   exceptions.** The alphabet's boundary has moved and the search still returns nothing.
4. **The instrument's own failure modes were the interesting part**: a brace in a *string* silently disabled an
   entire surface, and a killed frame silently stalled the pool. Both are now guarded — the builder syntax-checks
   the srcdoc, the page reports `ran=`, and the pool sweep is both the fix and the witness.
5. **What is left is not another seed, and not another 500k operations on the same alphabet.** The surfaces this
   programme has closed on paper but never fuzzed are now three fewer. The remaining ones are the serializer
   (`docs/77`), IndexedDB's key builder (`docs/78`), `MutationObserver` (`docs/78`'s CVE ordering with a cap of 1)
   and `window.open` (a third Document class) — that is the next action in `GOAL.md`.

Logs on the build box: `/tmp/S_{CAL1..CAL6,AN0,AN1,AN2,AN3,AN4,FR1,FR1b,FR2,FR2b,FR2c,WK1,WK2,S1..S4,GC2,C0b,C2,C3,C4}.log`,
server logs `/tmp/srv{9861..9906,9891..9893}.log`, sweep summary `/tmp/SWEEP86.txt`.
