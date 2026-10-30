# `style/` + the rule-mutation frames: no script door in the directory, and the copy-on-write path makes the raw-rule lookup fail — measured, a null `Ref` deref (4/4 on cached sheets)

GOAL action (2026-10-29), the item after `docs/71`. The action's text was: *"`style/`, per the original
proposal: rule-mutation frames holding a raw `StyleRule*` across `RuleMutationScope`, where
`didMutateRules()` can reach `CSSFontSelector::buildCompleted()` — the same free site as `docs/65`, but
reached from CSSOM instead of from a getter. `StyleSheetContents` holds its rules as
`Ref<StyleRuleBase>`, so read for a frame that keeps the raw pointer outside that vector."*

Short answer, three parts, all measured or read to the line:

1. **`style/` has no script sink at all.** 14 sweep rows in 8 files, every one read in source: 8 are the
   CSS media-query / container-query evaluator (`evaluate`), 6 are numeric or style-resolution `resolve`
   calls (`TextDecorationThickness::resolve`, `SharingResolver::resolve`, `Animation::resolve`). A grep for
   `JSC::` over all 40 `.cpp` files in the directory returns **0 hits**.
2. **The action's premise is false: `didMutateRules()` cannot reach `buildCompleted()`.** The frames live in
   `css/`, and their tail is `Scope::didChangeStyleSheetContents()` → `scheduleUpdate()` →
   `clearResolver()` + a 0-second timer (`style/StyleScope.cpp:703-715`). `CSSFontSelector::buildCompleted()`
   has exactly **one** caller in the tree: `Scope::createDocumentResolver()` (`style/StyleScope.cpp:121`).
   A CSSOM mutation destroys the `Style::Resolver`; it does not rebuild the font selector.
3. **What the frames do have is a live defect, and it is in the shape the action predicted** — but its
   consequence is a null `Ref` deref, not a reclaim. `CSSStyleRule::insertRule` binds
   `StyleRule&& styleRule` to the wrapper's rule **before** the call; `CSSStyleSheet::prepareChildStyleRuleForNesting`
   constructs its `RuleMutationScope` first, whose constructor calls `willMutateRules()`; for any
   memory-cached (`<link>`) sheet that call **copies** the contents and `reattachChildRuleCSSOMWrappers()`
   re-points every wrapper at the copies. The lookup `rules[i].ptr() == &styleRule` can then never match,
   the helper returns `{}`, and `m_styleRule = *styleRuleWithNesting` dereferences null:
   `SEGV ... 0x4` in `WTF::RefCountedBase::ref()`, top WebCore frame `CSSStyleRule::insertRule`
   (`css/CSSStyleRule.cpp:229`). Measured **4/4** on `<link>` sheets and **0/2** on inline `<style>` sheets
   with the same call, the same rule, and the same rule text.

The neighbouring frame that keeps a **raw `StyleRule*` in a local** across the same scope
(`css/typedom/DeclaredStylePropertyMap.cpp`) was measured too: it does not fault, because the object it
writes through is the *pre-copy* rule and the memory cache pins it; the write is simply lost — or, with two
clients, lands on the **sibling sheet**.

## Method

```sh
cd /Users/<user>/Documents/ps5-bootchain
python3 tools/pattern-sweep.py style > /tmp/audit72_style.json     # TOTAL 14, 8 files
grep -rn "RuleMutationScope" --include=*.cpp --include=*.h Source/WebCore | grep ':$' …   # 9 files
grep -rn "buildCompleted" --include=*.cpp --include=*.h Source/WebCore                    # 1 caller
```

The sweep uses the extended `NAMES` set from `docs/71` (`executeScript`, `executePendingScript`,
`performMicrotaskCheckpoint`, `JSC::call`, …), so "14 rows" is the whole sink list, not the old one.

The measured part is one page with a `case=` knob, `research/style-cssom/index.html`
(md5 `719e3977290b90380d3e9e654193f415`, with `s.css` `40ef48f2128c273054b53b61898f1932`, `m.css`
`4b7ee198fdc32fdf7e6697f03aa2faa3`), and `research/style-cssom/run.sh`, which copies the page's four files
to `/tmp/wks` on the oracle, kills stale servers, serves a fresh port, and runs the page under
`~/wk/run_nq.sh` (quarantine **off**). Every result is scored from the beacon log, never from harness state.
Logs: `data/style-cssom/` (`beacons_<port>.txt`, `asan_p<port>_case<n>.log`).

| port | case | kept? |
|------|------|-------|
| 9701 | 2 | superseded — `rule=b{color:green}` is rejected by the nested parser (`SyntaxError`), and the sheet pick was index-based |
| 9703, 9704 | 1 | superseded — index-based pick landed on the page's own inline `<style>` (two variables changed at once); this is why the page now selects sheets by `href` |
| 9700 | 4 | yes — copy witness |
| 9702 | 2 | yes — crash on a 2-client sheet |
| 9705, 9708 | 1 | yes — crash, 2/2, one client |
| 9706 | 5 | yes — `CSSMediaRule.insertRule` control, one link |
| 9709 | 6 | yes — same, two links |
| 9707 | 7 | yes — inline control for case 1 |
| 9710 | 8 | yes — crash through the grouping parent |
| 9711 | 9 | yes — inline control for case 8 |
| 9712 | 11 | yes — Typed OM misdirected write, two links |
| 9713 | 12 | yes — Typed OM lost write, one link |

## 1. `style/` — 14 rows, 0 sinks

| file | function | line | matched | what it actually is |
|------|----------|------|---------|---------------------|
| `style/ElementRuleCollector.cpp` | `containerQueriesMatch` | 567 | `evaluate` | `ContainerQueryEvaluator::evaluate(*query)` |
| `style/InlineTextBoxStyle.cpp` | `computedVisualOverflowForDecorations` | 212, 241, 254 | `resolve` | `TextDecorationThickness::resolve(fontSize, metrics)` → a `float` |
| `style/RuleSet.cpp` | `evaluateDynamicMediaQueryRules` | 376 | `evaluate` | `MQ::MediaQueryEvaluator` |
| `style/RuleSetBuilder.cpp` | `pushAndEvaluate` | 466 | `evaluate` | `MQ::MediaQueryEvaluator` |
| `style/StyleScopeRuleSets.cpp` | `evaluateDynamicMediaQueryRules` | 212-214 | `evaluate` | `MQ::MediaQueryEvaluator` |
| `style/StyleTreeResolver.cpp` | `styleForStyleable` | 151 | `resolve` | `SharingResolver::resolve(styleable, update)` |
| `style/Styleable.cpp` | `updateCSSTransitionsForStyleableAndProperty` | 529, 545 | `resolve` | `Animation::resolve(style, …)` |
| `style/UserAgentStyle.cpp` | `addToDefaultStyle` | 148, 150 | `evaluate` | `screenEval()` / `printEval()` media queries |

Completeness check, by grep rather than by the sweep:

```sh
grep -rnE "JSC::|ScriptController|dispatchEvent|performMicrotaskCheckpoint|executeScript|invokeCallback" Source/WebCore/style/*.cpp
```

0 hits in 40 files. The two `resolve(` declarations that are not the pattern are `SharingResolver::resolve`
(`StyleSharingResolver.cpp:78`) and `TreeResolver::resolve` (`StyleTreeResolver.cpp:967`). **`style/` is a
pure computation directory: it has no JavaScript door, so no frame in it can be a script window.** That is a
structural result, not a per-row adjudication.

## 2. The rule-mutation frames live in `css/`, and their tail is `clearResolver()`, not `buildCompleted()`

`grep -rn "RuleMutationScope"` finds **31 constructor calls in 8 files** under `Source/WebCore/css/`
(plus one in `inspector/InspectorStyleSheet.cpp`, not part of the page-facing surface):

| file | sites | what the frame holds across the scope |
|------|-------|---------------------------------------|
| `css/CSSPageRule.cpp` | 1 (`:73`) | `Ref<StyleRulePage> m_pageRule` (`CSSPageRule.h:51`) |
| `css/CSSStyleRule.cpp` | 3 (`:125`, `:232`, `:252`) | `Ref<StyleRule> m_styleRule` (`CSSStyleRule.h:70`) |
| `css/CSSGroupingRule.cpp` | 3 (`:91`, `:109`, `:174`) | `Ref<StyleRuleGroup> m_groupRule` (`CSSGroupingRule.h:47`) |
| `css/CSSKeyframesRule.cpp` | 3 (`:116`, `:130`, `:145`) | `Ref<StyleRuleKeyframes> m_keyframesRule` (`CSSKeyframesRule.h:95`) |
| `css/CSSCounterStyleRule.cpp` | 10 (`:188`-`:275`) | `Ref<StyleRuleCounterStyle> m_counterStyleRule` (`CSSCounterStyleRule.h:109`) |
| `css/CSSStyleSheet.cpp` | 4 (`:182`, `:356`, `:375`, `:494`) | `Ref<StyleSheetContents> m_contents`; `RefPtr<StyleRuleBase> rule` (but `:182` takes the caller's rule as a raw `StyleRule&&` parameter — see §3) |
| `css/MediaList.cpp` | 1 (`:80`) | **raw** `CSSRule* m_parentRule` / `CSSStyleSheet* m_parentStyleSheet` (`MediaList.h:73-74`) |
| `css/typedom/DeclaredStylePropertyMap.cpp` | 6 (`:103`-`:167`) | `WeakPtr<CSSStyleRule> m_ownerRule` + a **raw `StyleRule*` local** |

24 of the 31 are `Ref`-backed, so the mutation cannot free what the frame uses. The other 7 are the raw
sites named above — `MediaList` (1) and `DeclaredStylePropertyMap` (6) — and both files were read to the
end: `MediaList::setMediaQueries` uses its raw `m_parentRule` only for
`dynamicDowncast` and a setter on the rule wrapper (the wrapper is not freed by a contents copy — it is
*reattached*), and `DeclaredStylePropertyMap` keeps a raw `StyleRule*` across the scope, measured in §4.

What the scope's destructor actually does:

```cpp
CSSStyleSheet::RuleMutationScope::~RuleMutationScope()
{
    if (m_styleSheet)
        m_styleSheet->didMutateRules(m_mutationType, m_contentsWereClonedForMutation, m_insertedKeyframesRule.get(), m_modifiedKeyframesRuleName);
}
```

→ `CSSStyleSheet::didMutateRules` (`css/CSSStyleSheet.cpp:226`) → `forEachStyleScope` →
`scope.didChangeStyleSheetContents()` (`style/StyleScope.cpp:808`) → `scheduleUpdate(UpdateType::ContentsOrInterpretation)`:

```cpp
void Scope::scheduleUpdate(UpdateType update)
{
    if (update == UpdateType::ContentsOrInterpretation) {
        …
        if (!m_isUpdatingStyleResolver && !m_document.isResolvingTreeStyle())
            clearResolver();                       // destroys the Style::Resolver, synchronously
    }
    …
    if (m_pendingUpdateTimer.isActive()) return;
    m_pendingUpdateTimer.startOneShot(0_s);        // the rebuild happens on the next turn
}
```

`m_document.fontSelector().buildCompleted()` appears **once** in the tree, in `Scope::createDocumentResolver()`
(`style/StyleScope.cpp:121`), i.e. only when the resolver is *rebuilt*. So the action's free site is not
reachable from `didMutateRules()` at all; the tail reaches the `Resolver` destructor, not the font selector.
(And `clearResolver()` is skipped while `m_isUpdatingStyleResolver` is set, which is exactly the state during
`createDocumentResolver()` — so the `docs/65` getter window cannot re-enter it either.)

## 3. The one defect in this family, measured: the copy invalidates the identity lookup

`CSSStyleSheet::willMutateRules()` copies the contents whenever the sheet is not *both* single-client and
uncached:

```cpp
CSSStyleSheet::WhetherContentsWereClonedForMutation CSSStyleSheet::willMutateRules()
{
    // If we are the only client it is safe to mutate.
    if (m_contents->hasOneClient() && !m_contents->isInMemoryCache()) {
        m_contents->setMutable();
        return ContentsWereNotClonedForMutation;
    }
    …
    m_contents->unregisterClient(this);
    m_contents = m_contents->copy();                // deep copy: m_childRules[i]->copy()
    m_contents->registerClient(this);
    m_contents->setMutable();
    reattachChildRuleCSSOMWrappers();               // wrappers now point at the COPIES
    return ContentsWereClonedForMutation;
}
```

`StyleSheetContents`'s copy constructor deep-copies every child rule
(`css/StyleSheetContents.cpp:107-108`: `m_childRules[i] = o.m_childRules[i]->copy();`), and
`reattachChildRuleCSSOMWrappers()` re-points each existing wrapper at the copy
(`css/CSSStyleSheet.cpp:280-286` → `CSSStyleRule::reattach` → `m_styleRule = …`).

`CSSStyleRule::insertRule` binds a reference to the *old* object **before** that happens:

```cpp
ExceptionOr<unsigned> CSSStyleRule::insertRule(const String& ruleString, unsigned index)
{
    …
    if (!m_styleRule->isStyleRuleWithNesting()) {
        RefPtr<StyleRuleWithNesting> styleRuleWithNesting;
        if (auto parent = parentRule())
            styleRuleWithNesting = parent->prepareChildStyleRuleForNesting(m_styleRule);
        else if (auto parent = parentStyleSheet())
            styleRuleWithNesting = parent->prepareChildStyleRuleForNesting(WTFMove(m_styleRule.get()));   // :225
        else
            styleRuleWithNesting = StyleRuleWithNesting::create(WTFMove(m_styleRule.get()));
        ASSERT(styleRuleWithNesting);              // compiled out: -DNDEBUG
        m_styleRule = *styleRuleWithNesting;       // :229 — null deref when the lookup below missed
    }
```

and the helper does the mutation first, so the lookup cannot match:

```cpp
RefPtr<StyleRuleWithNesting> CSSStyleSheet::prepareChildStyleRuleForNesting(StyleRule&& styleRule)
{
    RuleMutationScope scope(this);                 // :182 — copies the contents here
    auto& rules = m_contents->m_childRules;        // the copies
    for (size_t i = 0 ; i < rules.size() ; i++) {
        if (rules[i].ptr() == &styleRule) { … }    // :185 — `styleRule` is the pre-copy object
    }
    return { };
}
```

`CSSGroupingRule::prepareChildStyleRuleForNesting` (`css/CSSGroupingRule.cpp:172-189`) has the same shape
with `auto& rules = m_groupRule->m_childRules;` after its own `RuleMutationScope scope(this)`.

`ASSERT` is compiled out in the oracle build (`configure-asan.sh` passes `-DNDEBUG`, documented there as
faithful to the retail release build), so the null `RefPtr` reaches `Ref<StyleRule>::operator=`:

```
==395704==ERROR: AddressSanitizer: SEGV on unknown address 0x000000000004 (pc … T0)
==395704==The signal is caused by a READ memory access.
==395704==Hint: address points to the zero page.
    #0 WTF::RefCountedBase::ref() const                                  WTF/Headers/wtf/RefCounted.h:46
    #1 WTF::Ref<WebCore::StyleRule>::Ref(WebCore::StyleRule&)            WTF/Headers/wtf/Ref.h:67
    #2 WTF::Ref<WebCore::StyleRule>::operator=(WebCore::StyleRule&)      WTF/Headers/wtf/Ref.h:156
    #3 WebCore::CSSStyleRule::insertRule(WTF::String const&, unsigned)   css/CSSStyleRule.cpp:229
    #4 jsCSSStyleRulePrototypeFunction_insertRuleBody                    DerivedSources/JSCSSStyleRule.cpp:324
    #5 call<…>                                                          bindings/js/JSDOMOperation.h:63
AddressSanitizer can not provide additional info.
SUMMARY: AddressSanitizer: SEGV … in WTF::RefCountedBase::ref() const
** (MiniBrowser:393335): WARNING **: 19:25:17.846: WebProcess CRASHED
```

### The measured matrix (10 distinct cases, 11 kept runs of 14, quarantine off, scored from beacons)

| case | sheet | call | result |
|------|-------|------|--------|
| 7 | inline `<style>` (1 client, not cached) | `CSSStyleRule.insertRule('& b{color:green}',0)` | `INS ret=0 nestedLen=1`, `access: none` |
| 1 | `<link>`, 1 client, cached | same | **SEGV 0x4** at `CSSStyleRule.cpp:229` — 2/2 (`9705`, `9708`) |
| 2 | `<link>` ×2 (shared contents) | same | **SEGV 0x4**, same stack (`9702`) |
| 9 | inline `<style>` with `@media` | inner `CSSStyleRule.insertRule` (grouping frame) | `INS ret=0 nestedLen=1`, `access: none` |
| 8 | `<link>` with `@media` | same | **SEGV 0x4**, same stack (`9710`) |
| 5 | `<link>` with `@media` | `CSSMediaRule.insertRule` (`CSSGroupingRule::insertRule`, no `prepareChild…`) | `INS ret=0 nestedLen=2`, `access: none` |
| 6 | `<link>` ×2 with `@media` | same | `INS ret=0 nestedLen=2`, `access: none` |
| 4 | `<link>` ×2 | `CSSStyleSheet.insertRule` — the copy witness | `ret=1`; sheet 1 `n=1→2`, **sheet 2 stays `n=1`** |

One variable per row: 1 vs 7 differ only in the sheet's provenance (link vs inline); 2 vs 1 differ only in
the number of clients; 8 vs 9 differ only in provenance; 5/6 differ only in the number of clients. `case=3`
(the cross-document variant, an `<iframe>` linking the same URL) is implemented in the page but was not run:
the single-`<link>` case already establishes the copy path, so it would only re-measure the same mechanism.

Case 4 is the witness that the copy really happens and is observable from JS:

```
start case=4 href=/s.css nlink=2
loaded load,load
pre sheets=3 0:[inline n=1] 1:[/s.css n=1] 2:[/s.css n=1]
SHEETINS ret=1
post sheets=3 0:[inline n=1] 1:[/s.css n=2] 2:[/s.css n=1]
```

Case 1's beacon sequence ends at the target line — the insert never returns:

```
start case=1 href=/s.css nlink=1
loaded load
pre sheets=2 0:[inline n=1] 1:[/s.css n=1]
pick n=0 hits=1 href=/s.css
target idx=0 cls=CSSStyleRule cssTextLen=17 rule=& b{color:green}
```

and case 7, same page, same call, same rule text, inline sheet:

```
pickInline n=0 hits=2
target idx=0 cls=CSSStyleRule cssTextLen=17 rule=& b{color:green}
target cssText=[a { color: red; }]
INS ret=0 nestedLen=1
done case=7
```

Two corrections to the action's assumptions, both measured:

* `CSSStyleRule.insertRule` **rejects a plain type-selector nested rule**: `b{color:green}` throws
  `SyntaxError: The string did not match the expected pattern.` (the parse happens before any mutation, so
  nothing else changes). `& b{color:green}` parses. The default in the page is still the failing string so
  the knob's history stays visible; every run quoted here passes `rule=& b{color:green}`.
* A `<link>` sheet is copied **even with one client**, because it is in the memory cache
  (`m_contents->isInMemoryCache()`), so the crash needs no shared sheet at all: one `<link>` and one CSSOM
  line is enough.

## 4. The raw `StyleRule*` local: a write that lands on the wrong object, and why it does not fault

`DeclaredStylePropertyMap` (CSS Typed OM, `CSSTypedOMEnabled` defaults true) captures a raw rule pointer
*before* the scope and writes through it after:

```cpp
StyleRule* DeclaredStylePropertyMap::styleRule() const { return m_ownerRule ? &m_ownerRule->styleRule() : nullptr; }

bool DeclaredStylePropertyMap::setProperty(CSSPropertyID propertyID, Ref<CSSValue>&& value)
{
    auto* styleRule = this->styleRule();                                  // raw, pre-scope
    if (!styleRule) return false;
    CSSStyleSheet::RuleMutationScope mutationScope(m_ownerRule.get());     // copies the contents
    styleRule->mutableProperties().setProperty(propertyID, value->cssText(), important, &didFailParsing);
    return !didFailParsing;
}
```

Measured with two `<link>`s to the same sheet (so both the pre-copy and post-copy rule are addressable from
JS), `r1.styleMap.set('margin-top','13px')`:

```
T11 pre A=[color: red;] B=[color: red;]
T11 set ok
T11 post A=[color: red;]
T11 post B=[color: red; margin-top: 13px;]
```

`A` is the wrapper's own rule after `reattachChildRuleCSSOMWrappers()` (the copy) — unchanged. `B` is the
sibling sheet, which still points at the **original** contents — it received the write. With a single
`<link>` the same call leaves no trace at all, because no wrapper points at the original any more:

```
T12 pre [color: red;]
T12 set ok readback=[]
T12 post [color: red;] samesheet rule0=[]
```

`access: none` in both runs. The reason is the same in both: the pre-copy `StyleSheetContents` is pinned by
`CachedCSSStyleSheet::m_parsedStyleSheetCache` (`loader/cache/CachedCSSStyleSheet.cpp:200-210`, a `Ref`), so
the rule the raw pointer names is **not** freed — the write is misdirected, not unsafe. That is a
correctness bug (a CSSOM call mutating a different `CSSStyleSheet` object than the one it was made on), and
it is recorded here because it is the exact frame shape the action predicted, measured to a negative.

## What this changes

* **`style/` is closed**: no script sink, so nothing in it can be a CVE-2026-43715-shaped window.
* **The rule-mutation family is closed for memory-safety** and now has two measured defects instead:
  1. a deterministic **WebProcess crash** from any page with a `<link>` stylesheet:
     `document.styleSheets[0].cssRules[0].insertRule('& b{color:red}', 0)` → `SEGV 0x4` in
     `CSSStyleRule::insertRule` (4/4 runs). DoS only — the `Ref` is null by construction, no attacker value
     reaches it, and the loop only *compares* the stale reference by address, so the freed-object read that
     would make it interesting never happens.
  2. a **misdirected CSSOM write** across a contents copy (Typed OM, and by the same mechanism any frame that
     caches a rule pointer outside the `Ref` vector). Not memory-unsafe here because the memory cache pins
     the pre-copy contents.
* **A latent hazard worth naming but not claiming**: `CSSStyleRule::reattach` re-points its own
  `m_propertiesCSSOMWrapper` but does **not** recurse into `m_childRuleCSSOMWrappers`, while
  `CSSGroupingRule::reattach` does (`css/CSSGroupingRule.cpp:212-219`). A nested `CSSStyleRule` wrapper
  therefore keeps a `Ref<StyleRule>` to a rule inside the *pre-copy* contents. That would be a
  use-after-free write the moment a sheet that already contains nesting rules is copied — and it cannot
  happen in this drop, because `StyleSheetContents::isCacheable()` returns false when `m_hasNestingRules`
  (`css/StyleSheetContents.cpp:116-131`) and `HTMLLinkElement` only caches cacheable sheets
  (`html/HTMLLinkElement.cpp:491-492`), so a nesting sheet is never in the memory cache and never gets a
  second client. It becomes reachable if either of those two gates changes; do not report it as live.
* Offsets and free sites of `docs/65` are untouched by all of this; the font-selector CVE stays as closed as
  `docs/65` "Attempt 11" left it.

## Next

The pattern hunt has now covered `css/`, `dom/` (docs/69), `html/` (docs/70), `html/parser/` (docs/71) and
`style/` (this doc) with the extended sink list. The two script-window families that *are* live in this drop
are `resolve(<DOM object>)` (docs/69) and the parser's/`LoadableScript` client callbacks (docs/71). The next
action is in `GOAL.md`.
