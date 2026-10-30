# The client-set tail audit: where a post-callback dereference of `this` is not a timer

GOAL action 5 (2026-10-29). The question it asks: `CSSFontFace::iterateClients` lacks upstream's
`clients.contains(client)` guard, and the free of `this` happens inside the client callback. Every other
`WeakHashSet<…Client>` iteration in `Source/WebCore` has the same shape. Which of them has a tail after the
callback that **dereferences a pointer field of `this`** — and is therefore a better primitive than the
`TimerBase` assert that blocks `CSSFontFace`?

Short answer: none of them, in this drop. Below is the surface, the method, and the evidence for that verdict.

## Method

```sh
cd out/sony/full/WebKit-1400/WebKit-1400/Source/WebCore
# 1. every WeakHashSet member in Source/WebCore, declaration-flattened so multiline templates are caught
python3 - <<'PY'   # (full script kept in this doc's "Reproducing" section)
PY            #  -> 98 members
# 2. iteration sites for the client-typed ones, three idioms: forEach / range-for / copyToVectorOf
# 3. the enclosing function's code after the loop, read by hand for each site
```

Upstream comparison, fetched 2026-10-29 from `raw.githubusercontent.com/WebKit/WebKit/main/`:
`Source/WebCore/css/CSSFontFace.cpp`, `Source/WebCore/css/CSSFontFaceSet.cpp`,
`Source/WebCore/html/track/TextTrack.cpp`, `Source/WebCore/loader/cache/CachedResource.cpp`,
`Source/WTF/wtf/WeakHashSet.h`.

Scope: the drop as built for the oracle (Linux/WPE, non-Apple — the same platform fact that makes
`shouldSuppressThreadSafetyCheck()` a constant `false`, `docs/65`). Apple-only `.mm` families
(`PlaybackSessionModelMediaElement`, `HIDGamepadProvider`, `MultiGamepadProvider`, `MediaSessionHelperIOS`,
`WebCoreMotionManager`, `WebVideoFullscreenControllerAVKit`) are listed at the end but not scored; they are not
in this build. The console build is also non-Apple, so they are out of scope there too unless Sony enabled them.

## Finding 1 — the drop's `WeakHashSet::forEach` is an older implementation than upstream's, and it re-reads `this`

Drop, `Source/WTF/wtf/WeakHashSet.h:159`:

```cpp
    void forEach(const Function<void(T&)>& callback)
    {
        auto items = map(m_set, [](const Ref<WeakPtrImpl>& item) {
            auto* pointer = static_cast<T*>(item->template get<T>());
            return WeakPtr<T, WeakPtrImpl> { pointer };
        });
        for (auto& item : items) {
            // FIXME: This contains check is only necessary if the set is being mutated during iteration.
            // Change it to an assertion, or make this function use begin() and end().
            if (item && m_set.contains(*item.m_impl))
                callback(*item);
        }
    }
```

Upstream, `Source/WTF/wtf/WeakHashSet.h:202` (fetched today):

```cpp
    void forEach(NOESCAPE const Function<void(T&)>& callback) requires HasRefPtrMemberFunctions<T>
    {
        auto items = compactMap(m_set, [](const KeyType& item) -> RefPtr<T> {
            return RefPtr { item.get() };
        });
        for (auto& item : items)
            callback(item.get());
    }
```

Two differences that matter here, and they point in opposite directions:

- **The guard.** The drop's loop re-checks `m_set.contains(*item.m_impl)` before every callback; upstream
  dropped that check and instead snapshots **strong** `RefPtr<T>`/`CheckedPtr<T>`. So the drop has the
  membership guard but not the lifetime guarantee, and upstream has the lifetime guarantee without the guard.
- **The tail.** In the drop, `m_set` — a member of the object that owns the `WeakHashSet`, i.e. of `this` — is
  dereferenced once per remaining item. If `this` dies inside a callback, the next iteration reads a **pointer
  field of `this`** (the `HashSet<Ref<WeakPtrImpl>>`'s table pointer). Upstream no longer touches the owning
  object at all in that loop.

So the shape GOAL action 5 is looking for does exist structurally, in 17 families. The question is only where
`this` can die inside its own callback.

## Finding 2 — where the guard idiom does exist in the drop

- Upstream `iterateClients`, `CSSFontFace.cpp:66-72`: `for (auto& client : copyToVectorOf<Ref<CSSFontFaceClient>>(clients)) { if (clients.contains(client)) callback(client); }`.
  The drop, `CSSFontFace.cpp:55-58`, has the `copyToVectorOf<Ref<Client>>` but **not** the `contains` — this is
  CVE-2026-43715.
- Loader, `loader/cache/CachedResourceClientWalker.h:45-59`: the walker snapshots the set into
  `FixedVector<WeakPtr<CachedResourceClient>>` and its `next()` does `if (next && m_resource->m_clients.contains(*next))`
  before handing the client out. The guard is present in the drop.
- `Modules/gamepad/GamepadManager.cpp:85-88`, inside a client callback: `// Event dispatch might have made this
  window go away.` followed by `if (!window) continue;`. The engine already knows a callback can destroy an
  object in the list it is walking — it just does not apply the same reasoning to `this` anywhere.

## The table

`alloc` = how the iterating object is allocated (`FAST` = plain `fastMalloc`, reclaimable by a JS container;
`ISO` = IsoHeap, not reclaimable — the wall that killed the canvas UAF, `docs/58`).
"script?" = can the client callback run attacker JS **synchronously from inside the loop**.
"first post-callback use of `this`" = the first statement after the loop that reads the iterating object.

| # | site(s) | iterating object | alloc | guard in drop | script? | first post-callback use of `this` |
|---|---------|------------------|-------|---------------|---------|-----------------------------------|
| 1 | `css/CSSFontFace.cpp:155,197,234,273,295,322,341,357,436,591,769` (`iterateClients`, `:57`) | `CSSFontFace` | FAST (`CSSFontFace.h:59-61`, heap identifier) | **no** (this is the CVE) | **yes** — `FontFace::fontStateChanged` resolves `m_loadedPromise` (`FontFace.cpp:343-344`), proven in `docs/65` | `setStatus:591` → `m_status = newStatus` (+0x82), then `fontLoadTiming()` (+0x86/+0x87), then `m_timeoutTimer.stop()` → `Timer.cpp:469` |
| 2 | `css/CSSFontFaceSet.cpp:78,89,533` | `CSSFontFaceSet` | FAST (no allocator macro) | n/a (`forEach` re-check) | **yes** — `FontFaceSet::faceFinished` resolves `pendingPromise->promise` (`FontFaceSet.cpp:253`); `completedLoading` resolves `m_readyPromise` (`:279`) | `:533` → `decrementActiveCount()` (`:88`): `--m_activeCount`, `m_status = Loaded`, then `m_fontEventClients.forEach` → `m_set` pointer |
| 3 | `css/CSSFontFaceSet.cpp:199,256,549` | `CSSFontFaceSet` | FAST | n/a | no — observer is `CSSFontSelector::fontModified` → `dispatchInvalidationCallbacks` → `fontsNeedUpdate` → `Document::invalidateMatchedPropertiesCacheAndForceStyleRecalc` (`Document.cpp:2508`) | `:256` → loop over `m_faces`, `m_facesPartitionIndex` |
| 4 | `css/CSSFontSelector.cpp:282` | `CSSFontSelector` | FAST | snapshot `copyToVector(m_clients)` (raw pointers, no contains) | no — same `fontsNeedUpdate` path; `CanvasRenderingContext2DBase::FontProxy::fontsNeedUpdate` | end of `dispatchInvalidationCallbacks` |
| 5 | `platform/graphics/FontCache.cpp:399` | `FontCache` | FAST, per-thread singleton | snapshot `copyToVectorOf<Ref<FontSelector>>` | no — `CSSFontSelector::fontCacheInvalidated` → same invalidation | `purgeInactiveFontData()` |
| 6 | `html/track/TextTrack.cpp:117,215,258,270,294,351,377,472,485,629,637,645,652` | `TextTrack` | **ISO** (`TextTrack.cpp:52`) | n/a | no — clients are `HTMLMediaElement`/`HTMLTrackElement`/`SourceBuffer`; every event is queued (`TrackListBase::scheduleChangeEvent`, `TrackListBase.cpp:140-155`; `cuechange` via `scheduleEventOn`, `HTMLMediaElement.cpp:1934-1947`) | `:258` → `m_mode = mode;` then a **second** `m_clients.forEach` |
| 7 | `html/track/AudioTrack.cpp:102,123,152,165,173,185` | `AudioTrack` | FAST (no ISO macro) | n/a | no — `HTMLMediaElement`/`SourceBuffer`, `scheduleChangeEvent` only | `:123` → end; `:185` → end |
| 8 | `html/track/VideoTrack.cpp:108,133,146,154,166,186,206` | `VideoTrack` | FAST (no ISO macro) | n/a | no — same | `:133` → end; `:206` → end |
| 9 | `html/track/InbandTextTrack.cpp:168` | `InbandTextTrack` | **ISO** (`InbandTextTrack.h:36`) | n/a | no | end |
| 10 | `loader/cache/CachedResource.cpp:792` | `CachedResource` | FAST | **yes** — `CachedResourceClientWalker::next()` (`:54`) | no — `didAddClient` → `CachedImage`/`CachedFont`/`CachedCSSStyleSheet`, no script | `ASSERT(!m_clients.computeSize())` |
| 11 | `loader/cache/CachedImage.cpp:189` | `CachedImage` | FAST | no (`forEach`) | no — `client.imageChanged(this)` → renderers/elements | `m_clientsWaitingForAsyncDecoding.clear()` |
| 12 | `Modules/encryptedmedia/MediaKeys.cpp:171,185` | `MediaKeys` | FAST | no (range-for, mutating inside) | no — `CDMClient` is implemented only by `HTMLMediaElement` (`HTMLMediaElement.cpp:3089`): resume-playback / init-data | end |
| 13 | `dom/Document.cpp:1927` | `Document` | **ISO** | no | no — `HTMLMediaElement` (`mediaSession().visibilityChanged()`, `:6440`), `ScreenOrientation` | `m_whenIsVisibleHandlers` exchange + `updateServiceWorkerClientData()` |
| 14 | `page/UserContentProvider.cpp:85` | `UserContentProvider` | FAST | no | no — `UserMessageHandlersNamespace::didInvalidate` | end |
| 15 | `rendering/svg/RenderSVGRoot.cpp:252`, `LegacyRenderSVGRoot.cpp:186` | `RenderSVGRoot` | **ISO** | no | no — resource invalidation | end of `paint` |
| 16 | `bindings/js/WebCoreJSClientData.cpp:142` | `JSVMClientData` | `new`, owned by the VM | no | no — `willDestroyVM`, destructor context | destructor continues (`ASSERT`s) |
| 17 | `platform/gamepad/GamepadProvider.cpp:55`, `manette:147,158` | `GamepadProvider` | `NeverDestroyed` singleton (`GamepadProvider.cpp:38-41`) | no | **yes** — `GamepadManager::platformGamepadDisconnected` dispatches `gamepaddisconnected` to every window (`GamepadManager.cpp:105`) | immortal `this`; nothing to free |

## Finding 3 — only three families run script from a client callback

1. `CSSFontFace::Client` → `FontFace::fontStateChanged` → `m_loadedPromise->resolve(*this)` (`FontFace.cpp:343`).
   Thenable assimilation calls the attacker's `then` getter **inside** `CSSFontFace::setStatus`. This is the
   proven primitive (`docs/65`, Attempt 4).
2. `CSSFontFaceSet::FontEventClient` → `FontFaceSet::faceFinished` → `pendingPromise->promise->resolve(faces)`
   (`FontFaceSet.cpp:253`), and `completedLoading` → `m_readyPromise->resolve(*this)` (`FontFaceSet.cpp:279`).
3. `GamepadProviderClient` → `GamepadManager::platformGamepadDisconnected` → `window->dispatchEvent(...)`
   (`GamepadManager.cpp:80-113`), synchronous, straight into page script.

Every other family's callback either queues its event (`TrackListBase::scheduleChangeEvent` uses
`queueTaskKeepingObjectAlive`; cue events use `scheduleEventOn`), only invalidates style, or only touches
render-tree state. There is no fourth script door in this drop's client-set iterations.

## Finding 4 — why each of the three cannot be used, measured by reading

**`CSSFontFaceSet` (#2) is kept alive by the very loop that would run the script.** `iterateClients` copies the
client set into `Vector<Ref<Client>>` (`CSSFontFace.cpp:57`), so while `CSSFontFaceSet::fontStateChanged` is on
the stack, a strong reference to the set sits in the *caller's* frame, one level below. Destroying the document
from the `then` getter drops the two owning refs — `CSSFontSelector::m_cssFontFaceSet` (`CSSFontSelector.h:131`)
and `FontFaceSet::m_backing` (`FontFaceSet.h:118`) — but the set survives until `iterateClients`' temporary
vector is destroyed, which happens **after** the callback returns. At that point the stack is back in
`CSSFontFace::setStatus`, which touches the face, never the set. The `decrementActiveCount()` tail at `:533`
therefore always runs on a live set. (Its `m_owningFontSelector` is a `WeakPtr`, `CSSFontFaceSet.h:136`, so the
other obvious dangling-pointer route is closed too.)

**`GamepadProvider`/`GamepadManager` (#17) are immortal.** `GamepadProvider::singleton()` returns a
`NeverDestroyed<…>` (`GamepadProvider.cpp:38-41`) and `GamepadManager` is a `NeverDestroyed` singleton
(`GamepadManager.h:45`). A `forEach` over a member of an object that is never destroyed cannot have a stale
`this`.

**The tracks (#6-#9) cannot be freed inside their own callback.** `AudioTrack::willRemove()` →
`HTMLMediaElement::willRemoveAudioTrack` → `removeAudioTrack(Ref<AudioTrack>&&)` → `TrackListBase::remove`,
which takes `Ref<TrackBase> trackRef` before erasing and hands it to `scheduleRemoveTrackEvent`
(`TrackListBase.cpp:63-78`). The queued `TrackEvent` owns the track, so the refcount never reaches zero inside
the callback. `TextTrack` and `InbandTextTrack` are IsoHeap in any case.

## Verdict

**No site in this drop is a better primitive than `CSSFontFace`.** The missing guard is real in exactly one
place (`iterateClients`), the "tail dereferences `this`" shape exists in 17 families, and the intersection of
that shape with (a) a script-running callback and (b) a freeable `this` is empty apart from `CSSFontFace`
itself, whose only post-callback pointer use is the timer's `m_thread` address comparison.

Consequences for the programme:

- Stop looking for another client-set class. The escalation has to happen **inside** the primitive already
  proven: the byte at `+0x82` in a reclaimed slot, or a **field of a same-type reclaim** (a live `CSSFontFace`
  placed in the slot by `new FontFace`, which keeps `m_thread` valid and survives `setStatus`).
- The only structurally similar object that survives the timer is a real `CSSFontFace`, so criterion 2 has to be
  met by steering *its* fields from CSSOM, not by faking one.
- The drop's older `WeakHashSet::forEach` is a latent amplifier: any future bug that frees a `forEach` owner
  inside its callback gets a pointer-field read for free in this build, where upstream would not. Worth
  remembering when auditing other object families; not reachable today.

## Reproducing

```sh
cd out/sony/full/WebKit-1400/WebKit-1400/Source/WebCore
python3 - <<'PY'
import re, os, collections
mem = collections.defaultdict(list)
for dp, _, fns in os.walk('.'):
    for fn in fns:
        if not fn.endswith('.h'): continue
        p = os.path.join(dp, fn)
        flat = re.sub(r'\s+', ' ', open(p, encoding='utf-8', errors='replace').read())
        for m in re.finditer(r'WeakHashSet<\s*([^;{}]{1,120}?)>\s*(m_\w+)\s*[;{]', flat):
            mem[m.group(2)].append((p, m.group(1)))
print('members:', len(mem))
for k in sorted(mem): print(k, '|', mem[k][0][1][:60], '|', mem[k][0][0])
PY
# then, per client-typed member, the iteration sites:
grep -rn "m_clients\.forEach\|for (auto& client : m_clients\|copyToVectorOf<[^>]*Client" --include=*.cpp --include=*.h .
```

Upstream files were fetched with:

```sh
for f in Source/WebCore/css/CSSFontFace.cpp Source/WebCore/css/CSSFontFaceSet.cpp \
         Source/WebCore/html/track/TextTrack.cpp Source/WebCore/loader/cache/CachedResource.cpp \
         Source/WTF/wtf/WeakHashSet.h; do
  curl -s "https://raw.githubusercontent.com/WebKit/WebKit/main/$f" -o "up-$(basename $f)"
done
```

## What would falsify this verdict

- A client callback reachable from page script in this build other than the three in Finding 3. The audit read
  the client interface implementations for all 17 families; a new implementation added by Sony in the drop
  (the drop is Sony's tree, not vanilla) is the realistic way one could exist. `git grep "public .*Client"`
  over `Source/WebCore` is the check, and it was run for each interface named above.
- An object whose owner is a JS-removable DOM node, that is plain `fastMalloc`-allocated, and that iterates a
  client set whose callback runs script. That is exactly the `CSSFontFace` shape, and it is the thing to look
  for in the next CVE, not in this tree.

## Outcome, measured in the same session: the pointer read is on the *face*, from the set's callback

The verdict above ("no iterating object is freed inside a script-running callback except `CSSFontFace`") is
correct, and it is also incomplete in a way that mattered: the post-callback tail of
`CSSFontFaceSet::fontStateChanged` does dereference a pointer field — but of the **`CSSFontFace&` argument**,
not of `this`.

```cpp
m_fontEventClients.forEach([&] (auto& client) { client.faceFinished(face, newState); });   // :533-534
```
→ `FontFaceSet::faceFinished` → `if (!face.existingWrapper())` (`FontFaceSet.cpp:240`) → `m_wrapper.get()`
(`CSSFontFace.cpp:162`) → `m_impl->get<T>()` (`WeakPtr.h:55`).

When the set's callback is iterated after the callback that freed the face, `face` is the reclaimed chunk and
object+0x68 (measured: `mov 0x68(%rdi),%rax` in `existingWrapper`) is attacker bytes. Verified with two poison
values, an offset-shifted control, and the ASAN shadow arithmetic; full report and run tables in `docs/65`,
"Attempt 5".

So the audit's operational lesson is the same as its structural one, one level up: **the read that survives is
not in the object that owns the client set; it is in the object the callback was handed.** For the next CVE of
this shape, the question to ask is not "is the iterating object freeable" but "what does each *other* client do
with the reference it is given".
