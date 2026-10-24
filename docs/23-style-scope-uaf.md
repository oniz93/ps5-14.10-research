# The first real bug: a use-after-free in Sony's shipped WebKit

Everything else so far has been a crash, a logic error, or a feature that turned out to be
disabled. This one is different: **a heap use-after-free that upstream fixed after the
snapshot Sony ships, in code Sony has not patched.**

Upstream fixed it on **2023-11-02**:

```
heap-use-after-free | Style::Scope::removeStyleSheetCandidateNode;
                      WebCore::SVGStyleElement::~SVGStyleElement;
                      WebCore::ContainerNode::~ContainerNode
https://bugs.webkit.org/show_bug.cgi?id=260896   rdar://114231775
```

Sony's 14.x drop is from **September 2023**. Both halves of the fix are absent.

## What is wrong, in Sony's own code

**One: a DOM cycle nobody needed.**

```cpp
// WebCore/rendering/PathOperation.cpp:57-65  (Sony tree)
ReferencePathOperation::ReferencePathOperation(const String& url, const AtomString& fragment, const RefPtr<SVGElement> element)
    : PathOperation(Reference)
    , m_url(url)
    , m_fragment(fragment)
    , m_element(element)                        // <-- RefPtr<SVGElement>, never used again
{
    if (is<SVGPathElement>(m_element) || is<SVGGeometryElement>(m_element))
        m_path = pathFromGraphicsElement(m_element.get());
}
```

`m_element` is stored and never read. Because a `RenderStyle` can own a `PathOperation`,
this gives **RenderStyle → DOM ownership**. The commit says exactly that: *"Get rid of the
unused element field. This creates a RenderStyle -> DOM ownership cycle which allows this
crash to happen."* The fix deletes the member and uses the constructor argument directly.

**Two: a destructor that leaves dangling weak pointers.**

```cpp
// WebCore/style/StyleScope.cpp  (Sony tree)
Scope::~Scope()
{
    ASSERT(!hasPendingSheets());
}
```

Upstream now adds one line:

```cpp
    weakPtrFactory().revokeAll();
```

The commit: *"Ensure we revoke weak pointers at the start of the destructor to avoid this
class of problems."*

Put together: a shadow tree whose style references an SVG element keeps that element alive
through `RenderStyle`; tear the tree down and the `Style::Scope` can be destroyed while
weak pointers into it are still held. The crash title names the fatal path —
`Scope::removeStyleSheetCandidateNode` operating on a freed scope.

## Why this matters more than a crash

A use-after-free is a *write/read on freed memory*, not a null dereference. If the attacker
can arrange for the freed allocation to be reused with attacker-controlled contents before
the dangling access, the access becomes an operation on a fake object — the standard route
from a WebKit UAF to control-flow hijack inside the WebProcess.

Two things make this one interesting rather than theoretical:

- The freed object is a **style/DOM object**, and the WebProcess allocator is the same one
  that services `String`, `Vector`, typed arrays and DOM wrappers — all directly
  controllable from page JavaScript.
- The dangling access happens in a path that iterates **style sheet candidates**, i.e. it
  walks a container. Turning that into a controlled read/write is a well-trodden shape.

Whether it is *exploitable* on the PS5 build is a separate question, and one nothing in
this repository can answer yet. What is established here is: the vulnerability is present
in the shipped code, it is reachable from a page, and it corrupts memory rather than merely
crashing.

## What the dangling pointer actually operates on

Worth being concrete, because it decides whether this is a crash or a primitive.

```cpp
// WebCore/style/StyleScope.h:69,223
class Scope : public CanMakeWeakPtr<Scope> {
    ...
    WeakListHashSet<Node, WeakPtrImplWithEventTargetData> m_styleSheetCandidateNodes;
```

and the function in the crash title is two lines:

```cpp
// WebCore/style/StyleScope.cpp:351
void Scope::removeStyleSheetCandidateNode(Node& node)
{
    if (m_styleSheetCandidateNodes.remove(node))
        didChangeActiveStyleSheetCandidates();
}
```

So the dangling access is a **hash-set removal on a freed object**. That is not a null
dereference: `WeakListHashSet::remove` reads the table pointer and size out of the freed
`Scope`, hashes the node pointer, and probes the table. If the freed allocation has been
reused with attacker-chosen bytes, the table pointer is attacker-chosen, and the probe turns
into a read (and, on a hit, an erase) at a controlled address — the standard shape for
turning a style-system UAF into an arbitrary read.

The reason there is *time* to do that reuse is precisely the bug's structure: the
RenderStyle → DOM cycle keeps the SVG element alive past the point where the `Scope` died, so
the dangling call happens later — during GC — with arbitrary JavaScript running in between.
That is what makes this more interesting than the many teardown crashes that turn out to be
unreachable in practice.

What is *not* established here: the exact allocation size of `Scope` (it needs a debug build
to print, and ours is on hold), whether bmalloc or FastMalloc services it, and whether a
JavaScript-controllable allocation lands in the same bucket. Those three questions are the
next hour of work once the bug reproduces on the console at all.

## Reachability

The upstream reproducer is a fuzzer artefact (`fast/css/style-scope-destruction-crash.html`):
`attachShadow`, an SVG carrying a `clip-path="url(#id)"` reference, a layout touch, then a
GC nudge. It needs nothing unusual:

| requirement | status on 14.10 |
|---|---|
| shadow DOM (`attachShadow`) | standard in this engine generation |
| SVG `clip-path: url(#…)` / `offset-path` | plain SVG |
| `Element.remove()`, layout reads | plain DOM |
| GC pressure from JS | `new Uint8Array(...)` in a loop |

No workers, no SharedArrayBuffer, no JIT, no special headers — unlike the clone-race lead.

`tools/fw1400/probes/poc-style-scope-uaf.js` builds the same sequence from script (the
harness only injects a `<script>`, so the markup has to be constructed): 300 iterations of
host → shadow root → SVG with a `clipPath` reference → style/layout touch → remove → allocate
48 × 128 KB to drive collection. It beacons `SCOPE-BOOT`, `SCOPE-ITER-<n>` every ten
iterations, and `SCOPE-SURVIVED`. A blank WebView mid-run, with the last beacon naming the
iteration that died, is the UAF.

## If it reproduces

Order of work, cheapest first:

1. Confirm the crash is the same one: does it happen only with the `url(#…)` reference, and
   not with a plain `<svg>` in the shadow root? That separates this bug from a generic
   shadow-tree teardown fault.
2. Find the reclaim: replace the GC nudge with an allocation of a chosen size and class
   immediately after the teardown, then look for the dangling access touching it.
3. Only then think about what to turn it into. WebProcess code execution is rung one; the
   sandbox is still in the way, and Debug Settings still needs the kernel.

## The other candidates worth a second look

From the night sweep (121 records, 77 scored candidates, full list in
`data/candidates-night.json`):

| sha | date | what | note |
|---|---|---|---|
| `cd7e28cf47` | 2024-08-05 | heap-use-after-free `RenderMenuList::setTextFromOption` | `<select>` rendering, same period as our tree |
| `575e5800d5` | 2025-04-04 | crash in transform fast-path parsing (`CSSParserFastPaths`) | `style.transform = ...` from JS, trivial to reach |
| `8d71b72447` | 2026-06-15 | UAF under `JSAttr::visitAdditionalChildren()` | GC/custom-marking bug, reachable via `Attr` |
| `13885ac449` | 2023-11-02 | **this document** | fixed 13 months after our snapshot |

The 2026 rows carry a caveat the sweep cannot resolve: a recent fix may repair a regression
introduced *after* September 2023, in which case Sony's older code is unaffected. The 2023
and 2024 rows are the ones where "pre-fix code present" actually implies a live bug.
