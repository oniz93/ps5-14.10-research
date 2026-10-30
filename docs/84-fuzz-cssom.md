# 84 — the oracle under a seeded in-page fuzzer: 350,477 operations over the four surfaces the audits kept finding,
# and 0 sanitizer reports

`GOAL.md` item 1: twenty static passes (`docs/69`–`docs/83`) have closed every script-window *shape* this tree
has, and the one live memory bug (`docs/65`) is closed as not-a-primitive. What has never been pointed at the
drop is the sanitizer itself under a seeded, in-page fuzzer. This is that instrument, its calibration against
the two crashes this programme already owns, and the sweep.

Everything below is from `run_nq.sh` (allocator quarantine **off**), a **fresh port** per arm after
`pkill -f "[h]ttp.server"`, and scoring from the **beacon log** — never from harness state.

---

## 1. The instrument

`research/fuzz-cssom/fuzz.html` (369 lines, md5 `25f86f53a74c48c9809895b15b1067f0`), `fuzz.css`
(`6237c91322be6738e726163120efcf3f`), runner `research/fuzz-cssom/frun.sh`
(`a0cf6232a9814a784eb5538159f5100b`, deployed to `/tmp/wkp` and run from `/home/<user>/wk`).

Twenty-nine operations, weights summing to 80, one per iteration. The alphabet is not invented here — each
family is the surface a static pass kept landing on:

| family | ops | where the surface comes from |
|---|---|---|
| `Fnew-local` 6, `Fnew-url` 3, `Fcheck` 3, `Fload` 3, `Fstatus` 3, `Fdel` 2, `Fstyle` 5, `Fready` 1 | 8 | `docs/65`: `new FontFace`, `document.fonts.load/check/ready`, `FontFace.status`, delete a face, create **and remove** a `<style>` that owns a face, and set the element's family so layout must resolve it |
| `Rfont` 6, `Rplain` 4, `Rdel` 4, `Rmedia` 3, `Rpage` 1, `Rnest-inline` 2, `Rnest-link` 1, `Rlinkplain` 2, `Rlinkdel` 2, `Rdetach` 2 | 10 | `docs/72`: `insertRule`/`deleteRule` on an inline `<style>` sheet **and** on a `<link>` sheet (the copy-on-mutate one), `@media` grouping rules, `@page`, nesting `&`, and a sheet mutated while detached and re-appended |
| `Cdef` 2, `Cup` 3, `Cupgrade` 2, `Cattr` 2 | 4 | `docs/80`: `define`/`upgrade`, enqueue during `invokeAll`, `attributeChanged` |
| `Grange` 3, `Gsel` 2, `Gchurn` 2, `Gsurround` 1 | 4 | `docs/68`: boundary reassignment across text nodes that are removed, `deleteContents`, `surroundContents` |
| `Llayout` 6, `Ltext` 2, `Mchurn` 2 | 3 | the engine's own "run the recalc now" button (`document.body.offsetHeight` — the statement `docs/65`'s free is reached from) plus a GC churn |

Two structural properties the whole result rests on:

1. **Determinism.** Every iteration draws **exactly four** xorshift32 words, whatever the op is — one for the op
   choice, three for the arguments — and no op draws again. The op id and its arguments at index *i* are a pure
   function of `(seed, i)` and do **not** depend on which ops were executed. So `only=`/`skip=` remove
   executions without renumbering the stream, and a minimiser can replay: bisect `n=` to the failing index,
   then narrow with `only=`.
2. **Beacons, not harness state.** `new Image().src='/ev?m=<seq>&op=<id>'` on every iteration boundary that is a
   multiple of `every=` (default 200), a final `m=done&op=<last>`, and 29 `m=census` lines carrying, per op id,
   how many times it ran and how many times it threw. The census is what stops a null from being ambiguous: a
   fuzz run whose ops all throw is not a measurement, and this is how that is told apart from a clean run.

`then=1` (and its `del=1` sub-knob) installs an `Object.prototype.then` accessor — the reentrancy window
`docs/69` measured inside `resolve(<DOM object>)` — whose getter runs *synchronously before the next C++
statement* and mutates the page: layout, `deleteRule(0)`, remove the face's owning `<style>`, and (`del=1`)
`document.fonts.delete()` on a live face. It is off by default so the sweep stays one variable away from the
plain instrument.

---

## 2. Calibration: the two crashes this programme owns fall out of the alphabet

An instrument that reports "nothing" must first show it can report *something*. Both known deterministic crashes
are in the alphabet, and both were selected with `only=` so the run is that op and nothing else:

```
$ … ./frun.sh "C1page 9805 60 seed=1&n=20000&only=Rpage&every=25"
SUMMARY: AddressSanitizer: SEGV /…/wtf/RefPtr.h:87 in WTF::RefPtr<WTF::StringImpl,…>::operator!() const
    #0 WTF::RefPtr<WTF::StringImpl,…>::operator!() const   RefPtr.h:87
    #3 makeComponents                                       dom/QualifiedName.cpp:47
    #4 WebCore::QualifiedName::QualifiedName(…)             dom/QualifiedName.cpp:51
    #5 WebCore::CSSParserImpl::parsePageSelector(…)         css/parser/CSSParserImpl.cpp:229
    #6 WebCore::CSSParserImpl::consumePageRule(…)
    #10 WebCore::CSSGroupingRule::insertRule(WTF::String const&, unsigned int)  css/CSSGroupingRule.cpp:70
```

That is `docs/67`'s crash verbatim (`SEGV 0x70`, READ, `parsePageSelector:229` ← `CSSGroupingRule::insertRule:70`),
produced by `Rpage`: build `<style>@media all{}</style>`, take the grouping rule, `sheet.deleteRule(0)` to clear its
`parentStyleSheet`, then `insertRule('@page fooN {}', 0)` into the detached rule.

```
$ … ./frun.sh "C2link 9806 60 seed=1&n=20000&only=Rnest-link&every=25"
==…==ERROR: AddressSanitizer: SEGV on unknown address 0x000000000004 … READ
    #0 WTF::RefCountedBase::ref() const                                  wtf/RefCounted.h:46
    #1 WTF::Ref<WebCore::StyleRule>::operator=(WebCore::StyleRule&)      wtf/Ref.h:156
    #3 WebCore::CSSStyleRule::insertRule(WTF::String const&, unsigned int)  css/CSSStyleRule.cpp:229
SUMMARY: AddressSanitizer: SEGV … in WTF::RefCountedBase::ref() const
```

That is `docs/72`'s crash verbatim (`SEGV 0x4` in `RefCountedBase::ref` ← `Ref<StyleRule>::operator=` ←
`CSSStyleRule::insertRule:229`), produced by `Rnest-link`: `'& b{color:red}'` inserted into the first
`CSSStyleRule` of the `<link>` sheet.

### The determinism contract, checked against a prediction, twice

The op stream was re-implemented in Python from the weight table alone (xorshift32, four words per iteration) and
used to *predict* before running:

- **Index.** For `seed=1` the first `Rpage` selection is iteration **62**. Measured, one op apart:
  `n=61` → `B done&op=none&tot=61&then=0&ms=12` with last iteration beacons `B 25&op=Cupgrade`,
  `B 50&op=Gchurn`, `access: none`; `n=62` → the SEGV above, last beacon `B 50&op=Gchurn`. Exactly 62.
- **Census.** The model's per-op counts for `n=300, seed=1` were compared with the page's `census` beacons:
  **29 of 29 counts identical** (`Fnew-local 20`, `Fnew-url 12`, `Fcheck 11`, `Fload 13`, `Fstatus 14`, `Fdel 6`,
  `Fstyle 22`, `Fready 6`, `Rfont 9`, `Rplain 20`, `Rdel 14`, `Rmedia 13`, `Rnest-inline 10`, `Rlinkplain 7`,
  `Rlinkdel 7`, `Rdetach 4`, `Cdef 4`, `Cup 11`, `Cupgrade 9`, `Cattr 8`, `Grange 13`, `Gsel 3`, `Gchurn 7`,
  `Gsurround 6`, `Llayout 27`, `Ltext 8`, `Mchurn 6`; `Rpage 5` and `Rnest-link 5` selected and skipped).

So the beacon stream is enough to reconstruct a crash, and `only=` really does keep the retained ops' arguments.
Correction recorded: with `only=`/`skip=` implemented as a `continue` **before** the beacon, a filtered run
emitted **no** op beacon at all (`beacons=1` in the first `C1`/`C2`), which would have made a crash index
unrecoverable — the beacon is now emitted on the iteration boundary regardless of whether the op ran.

### The harness's own control

`n=0` (`seed=1&n=0`, port 9804): `B boot…`, `B done&op=none&tot=0&then=0&ms=3`, `access: none`, 38 beacons
(boot + done + 29 census + 7 ticks). The page's own scaffolding — a `<link>` sheet, an inline `<style>` sheet, a
`<p>` of text — allocates and rebuilds nothing that reports.

---

## 3. The sweep: four seeds, 20,000 operations each

`skip=Rpage,Rnest-link` for the sweep: those two ops are *known* deterministic crashes (`docs/67`, `docs/72`), and
a run that dies at iteration 62 measures nothing beyond the calibration above. Every other op runs. One fresh
port and one fresh server per arm.

```
$ ssh teo@<lab-ip> 'distrobox enter wk -- bash -lc "cd /tmp/wkp && ./frun.sh \
    \"S1 9821 60 seed=1&n=20000&skip=Rpage,Rnest-link\" \
    \"S2 9822 60 seed=2&n=20000&skip=Rpage,Rnest-link\" \
    \"S3 9823 60 seed=3&n=20000&skip=Rpage,Rnest-link\" \
    \"S4 9824 60 seed=4&n=20000&skip=Rpage,Rnest-link\""'
```

| arm | seed | exit | last op beacon (`m`) | `done` beacon | sanitizer |
|-----|------|------|----------------------|---------------|-----------|
| `S1` | 1 | `EXIT=124` | `20000&op=Fdel` | `done&op=Fdel&tot=20000&then=0&ms=14732&fc=10&cr=3&lk=11&sc=5&eh=60` | none |
| `S2` | 2 | `EXIT=124` | `20000&op=Cup` | `done&op=Cup&tot=20000&then=0&ms=14851&fc=18&cr=12&lk=1&sc=5&eh=60` | none |
| `S3` | 3 | `EXIT=124` | `20000&op=Rmedia` | `done&op=Rmedia&tot=20000&then=0&ms=14601&fc=14&cr=4&lk=24&sc=5&eh=60` | none |
| `S4` | 4 | `EXIT=124` | `20000&op=Rfont` | `done&op=Rfont&tot=20000&then=0&ms=14751&fc=13&cr=5&lk=3&sc=5&eh=60` | none |

`EXIT=124` is how **every** run of this harness ends (`timeout` kills MiniBrowser — `docs/65`, Attempt 11); the
`done` beacon is the completion witness, and all four have it. 142 beacons per arm = boot + 100 op beacons
(one per 200) + `done` + 29 census + 11 ticks. `access: none` in all four (`grep -E "ERROR: AddressSanitizer|
SUMMARY: AddressSanitizer|RELEASE_ASSERT|Zapped"` matched nothing).

The end-state fields are there so the null carries what the alphabet had built by then: `fc` = `document.fonts.size`
(10/18/14/13 — the JS faces plus the faces the four probe `<style>`s own), `cr`/`lk` = `cssRules.length` of the
inline and `<link>` sheets (3–12 and 1–24), `sc` = 5 `<style>` elements in `<head>`, `eh` = 60 px of laid-out body.
The sheets really were mutated and re-laid-out tens of thousands of times; `Rfont` alone ran 1,457 times in `S1`.

**What the alphabet did, from the census (`S1`, port 9821):** 19,500 operations executed, **500 skipped**
(`Rpage` 260 + `Rnest-link` 240 — the model's exact prediction for `seed=1, n=20000`), and **0 exceptions**:

```
census&op=Fnew-local&n=1460&e=0     census&op=Fnew-url&n=763&e=0      census&op=Fcheck&n=721&e=0
census&op=Fload&n=738&e=0           census&op=Fstatus&n=723&e=0       census&op=Fdel&n=527&e=0
census&op=Fstyle&n=1290&e=0         census&op=Fready&n=250&e=0        census&op=Rfont&n=1457&e=0
census&op=Rplain&n=964&e=0          census&op=Rdel&n=1029&e=0         census&op=Rmedia&n=769&e=0
census&op=Rpage&n=0&e=0             census&op=Rnest-inline&n=477&e=0  census&op=Rnest-link&n=0&e=0
census&op=Rlinkplain&n=497&e=0      census&op=Rlinkdel&n=492&e=0      census&op=Rdetach&n=510&e=0
census&op=Cdef&n=532&e=0            census&op=Cup&n=752&e=0           census&op=Cupgrade&n=456&e=0
census&op=Cattr&n=519&e=0           census&op=Grange&n=776&e=0        census&op=Gsel&n=509&e=0
census&op=Gchurn&n=518&e=0          census&op=Gsurround&n=275&e=0     census&op=Llayout&n=1502&e=0
census&op=Ltext&n=480&e=0           census&op=Mchurn&n=514&e=0
TOTAL executed 19500 errors 0
```

A first set of the same four arms (ports 9811–9814, before the end-state fields were added) gave the same result:
`done` in all four, `ms=14752 / 14680 / 14731 / 14782`, `access: none`. So the null is reproducible across two
independent sets of four runs — eight runs, not one lucky process.

---

## 4. The extra arms: reentrancy at scale, heap pressure, depth, and a harness cost measurement

| arm | query | result |
|-----|-------|--------|
| `T1` | `then=1` | **1,059 synchronous `then` windows** in 20,000 ops (`then&k=FontFaceSet` — `document.fonts.ready`'s `resolve(*this)`, plus `k=Array` from `document.fonts.load()` and `k=Function`), mutating sheet/`<style>`/layout inside them, `done … then=1059&ms=15804&fc=9`, **`access: none`** |
| `T2` | `then=1&del=1` | the same 1,059 windows, with the `m==0` quarter (264 of them) executing **`document.fonts.delete()` on a live face inside the callback** — the CVE's arming action — `done … then=1059&ms=15862&fc=9`, **`access: none`**. `T1` and `T2` differ only in that action; every other number is identical |
| `P1` | `maxfaces=64&maxrules=64&maxels=120` | 66 live faces in `document.fonts` at the end (`fc=66`), `ms=18837`, **`access: none`** — the "a container of many clients is rebuilt and iterated" shape, at 8× the default population |
| `D5` | `seed=5&n=100000` | `done&op=Rdel&tot=100000&then=0&ms=74636&fc=12`, **`access: none`** |
| `D6` | `seed=6&n=100000&then=1` | `done&op=Rlinkplain&tot=100000&then=5557&ms=79986&fc=17`, **`access: none`** — 5,557 windows in one run |
| `Y1` | `batch=1` | **10,477 ops in 60 s** (last beacon `10400&op=Llayout`, last tick `seq=10477`) vs 20,000 ops in 14.7 s at `batch=50`: a `setTimeout(0)` round trip costs ≈4.5 ms on this box, so the batching is what makes a 20k arm cheap. No sanitizer line; not finished, by design |

Totals: **350,477 operations executed** across the ten non-control arms (80,000 in the four required runs,
60,000 in `T1`/`T2`/`P1`, 10,477 in `Y1`, 200,000 in `D5`/`D6`), of which **7,675 ran inside a synchronous
`then` window** (`T1` 1,059 + `T2` 1,059 + `D6` 5,557), and **0 sanitizer reports** in 14 runs.

---

## 5. What this null covers — and what it does not

Stated precisely, because "the oracle ran 80,000 operations without a report" is only a measurement if its
boundary is written down.

**It does cover**, by construction of the alphabet and by the census above:

- the font lifecycle inside a *live document* — face creation, add/delete, `load`/`check`/`ready`, status reads,
  and `<style>` elements that own faces being created and removed while the element's computed family depends on
  them (`Fstyle` 1,290 + `Fnew-local` 1,460 + `Rfont` 1,457 per 20k arm);
- the rule-mutation path on **both** sheet kinds, including the copy-on-mutate `<link>` sheet (`docs/72`) —
  6,195 CSSOM operations per 20k arm;
- custom-element reaction enqueueing and upgrade (2,259 per arm) and `Range`/`Selection` boundary churn (2,078);
- 1,502 forced layouts per arm, which is the statement `docs/65`'s free is reached from
  (`buildCompleted()` from `Element::offsetHeight`), interleaved with the rule mutations that arm it.

**It does not cover**, and no line below is claimed:

- **It is not a flip oracle.** The page has no `DFACE` reader, so this run does not show that
  `CSSFontSelector::buildCompleted()` freed a face inside these 350k operations — it shows that nothing ASAN
  reports happened while the alphabet did that work. What makes the free site *live* on this build is
  `docs/65` "Attempt 8/9" (9/9, page md5 `f0d1b337aaad040b5f1824a162295759`), not this run; `Rfont` and
  `Llayout` are the two statements of that recipe, but the fuzzer does not assert they armed it in any given
  iteration.
- One document, one page, no iframes, no workers, no `structuredClone`, no `fetch`/XHR, no IndexedDB, no
  `Animation`, no `MutationObserver`. The alphabet is 29 fixed ops with three PRNG words of argument entropy each
  — this is a *broad surface* fuzzer, not a mutation fuzzer over bytes or over API sequences.
- The two known crashes are excluded from the sweep (`skip=`), so their absence from the four runs is by
  construction. They are measured in §2 instead.

---

## 6. Conclusions

1. **The instrument works and is calibrated.** From its own alphabet it reproduces `docs/67`'s `@page` crash
   (`SEGV 0x70`, `CSSParserImpl.cpp:229` ← `CSSGroupingRule.cpp:70`) and `docs/72`'s nesting crash
   (`SEGV 0x4`, `CSSGroupingRule`→`Ref<StyleRule>::operator=` ← `CSSStyleRule.cpp:229`), and the exact failing
   iteration is predictable from the seed alone (62 for `seed=1`, confirmed one op apart at `n=61`/`n=62`).
2. **The op stream is deterministic and the beacon stream is sufficient.** A Python re-implementation of the
   PRNG reproduces the page's own per-op census **29/29**, and `only=`/`skip=` provably preserve the retained
   ops' arguments, which is what makes `n=`-bisection a valid minimiser.
3. **350,477 operations, 14 runs, 0 sanitizer reports.** Four required arms (seeds 1–4, 20k each) plus reentrancy
   (2×20k, 1,059 windows each), heap pressure (66 live faces), and depth (2×100k, one with 5,557 windows).
4. **The reentrancy arms are the sharpest negative.** 7,675 synchronous `then` windows — the exact
   `resolve(<DOM object>)` window `docs/69` measured — in which the page deleted rules, removed the owning
   `<style>`, forced layout, and (in `T2`) `document.fonts.delete()`d a live face: nothing. That is consistent
   with `docs/65`'s closing account (the snapshot in `iterateClients`, and the two post-free field reads) and with
   `docs/66`'s guard taxonomy, now at three orders of magnitude more exposure than the hand-written pages.
5. **What is left is not another static pass.** Every shape the audits enumerated is closed, and the fuzzer adds
   no new candidate. The remaining lever on this stage is not local: the one JS-visible oracle that needs no
   sanitizer (`docs/65`, "Attempt 9") and the `CachedString` abort (`docs/76`) are both waiting on the operator to
   restart the Guide app so they can be run on the console, which is the only hardware step in `GOAL.md`.

Logs: `/tmp/F_{C0,C1page,C2link,B61,B62,S1..S4,T1,T2,P1,Y1,D5,D6}.log` on the build box, server logs
`/tmp/srv{9804..9851}.log`. Page and runner are in `research/fuzz-cssom/`.
