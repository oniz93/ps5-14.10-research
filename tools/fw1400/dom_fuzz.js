// Targeted DOM/CSS fuzzer for the ASAN MiniBrowser build.
//
// Not blind: every operation below belongs to a class where upstream had a memory-safety fix in
// the era this task investigated, so a hit here is a plausible live bug rather than noise.
//
// Seeds come from the URL (?seed=N). The page runs ITER rounds, then sets document.title to
// DONE:<seed> so the runner can tell a clean finish from a crash. Under ASAN a use-after-free
// aborts the process and prints a report to stderr, which is the actual signal: the runner keeps
// the seed and the page state that produced it.
//
// Classes covered:
//   shadow   - attach/remove shadow roots while children reference them (Style::Scope teardown)
//   svg      - clip-path / mask / filter references, then element and resource removal
//   css      - insertRule/deleteRule churn, nesting, container queries, @layer, :has()
//   clone    - template.content and element cloning with adopted stylesheets
//   slots    - slot assignment changes and slotchange handlers that mutate the tree
//   anim     - Web Animations on detached elements, cancellation mid-flight
//   range    - Range/Selection across nodes that are then removed
//   mo       - MutationObserver that mutates the tree it observes (reentrancy)
//   iframe   - srcdoc documents created and destroyed mid-load
//   media    - media elements torn down while a network state change is queued

(function () {
  'use strict';

  // The runner loads this from a file:// wrapper that sets window.__SEED. A query string is not
  // dependable on file URLs (WebKit may drop it), and a seed that silently collapses to 1 makes
  // every run identical while still reporting "clean", which is the worst possible failure mode.
  var seed = 1;
  if (typeof window.__SEED === 'number' && window.__SEED > 0)
    seed = window.__SEED;
  else {
    var m = /[?&]seed=(\d+)/.exec(location.search);
    if (m) seed = parseInt(m[1], 10) || 1;
  }

  var ITER = 220;

  // Optional out-of-band channel: the runner sets window.__BEACON to a local HTTP origin and reads
  // its access log. Exit codes alone cannot distinguish "the fuzzer ran to completion" from "the
  // page never loaded", and MiniBrowser does not forward console output, so without this a sweep
  // proves nothing. Requests are fire-and-forget image loads, ignored on failure.
  function beacon(tag) {
    if (!window.__BEACON) return;
    try { (new Image()).src = window.__BEACON + '/' + encodeURIComponent(tag); } catch (e) {}
  }
  beacon('BOOT-seed' + seed);

  // An uncaught exception ends the run silently: the page stays loaded, the runner sees a clean
  // timeout, and the sweep falsely looks healthy. Report it instead.
  window.onerror = function (msg) {
    beacon('ERR-seed' + seed + '-' + String(msg).slice(0, 60).replace(/[^A-Za-z0-9 ._-]/g, '_'));
    return false;
  };

  // xorshift32: reproducible, and the seed uniquely identifies a crash
  var s = seed | 0 || 1;
  function rnd() {
    s ^= s << 13; s |= 0;
    s ^= s >>> 17;
    s ^= s << 5; s |= 0;
    return (s >>> 0) / 4294967296;
  }
  function pick(a) { return a[Math.floor(rnd() * a.length) % a.length]; }
  function maybe(p) { return rnd() < p; }

  // Resolved on DOMContentLoaded, not here: this script runs in <head>, where document.body is
  // still null. Taking it eagerly made root null and threw TypeError on the first tick of every
  // run, which the runner then reported as a clean timeout - a silent no-op sweep.
  var root = null;

  function el(tag, ns) {
    return ns ? document.createElementNS(ns, tag) : document.createElement(tag);
  }

  var CSS_OPS = [
    'background:red', 'container-type:inline-size', 'container:side / inline-size',
    'clip-path:url(#p1)', 'filter:blur(2px)', 'mask:url(#m1)',
    'will-change:transform', 'content-visibility:auto', 'contain:strict',
    'display:contents', 'position:absolute', 'transform:translateZ(0)',
    'backdrop-filter:blur(1px)', 'aspect-ratio:1/1', 'overflow:clip'
  ];

  function cssNoise() {
    var rules = [];
    var n = 1 + Math.floor(rnd() * 4);
    for (var i = 0; i < n; i++) {
      var sel = pick(['& > div', 'div', '.c' + i, ':is(div,span)', ':has(> b)', 'div:nth-child(odd)']);
      rules.push(sel + '{' + pick(CSS_OPS) + '}');
    }
    return rules.join('\n');
  }

  // ---------------------------------------------------------------- classes

  function doShadow() {
    var host = el('div');
    root.appendChild(host);
    var sr = host.attachShadow({ mode: 'open' });
    sr.innerHTML = '<style>.a{color:red}</style><div class="a"><b>x</b></div><slot></slot>';
    // a stylesheet inside a shadow tree, then destroy the host: Style::Scope lifetime
    var sheet = el('style');
    sheet.textContent = cssNoise();
    sr.appendChild(sheet);
    var kid = el('span');
    host.appendChild(kid);
    // force layout, then tear the host out while referencing the shadow tree
    void host.offsetWidth;
    if (maybe(0.5)) { sr.removeChild(sheet); }
    if (maybe(0.3)) { sr.appendChild(el('link')); }
    host.remove();
    if (maybe(0.5)) { root.appendChild(host); host.remove(); }
  }

  function doSvg() {
    var svg = el('svg', 'http://www.w3.org/2000/svg');
    svg.setAttribute('width', '20'); svg.setAttribute('height', '20');
    var defs = el('defs', 'http://www.w3.org/2000/svg');
    var cp = el('clipPath', 'http://www.w3.org/2000/svg'); cp.id = 'p1';
    cp.appendChild(el('rect', 'http://www.w3.org/2000/svg'));
    var mask = el('mask', 'http://www.w3.org/2000/svg'); mask.id = 'm1';
    defs.appendChild(cp); defs.appendChild(mask);
    var rect = el('rect', 'http://www.w3.org/2000/svg');
    rect.setAttribute('clip-path', 'url(#p1)');
    rect.setAttribute('mask', 'url(#m1)');
    rect.setAttribute('width', '10'); rect.setAttribute('height', '10');
    svg.appendChild(defs); svg.appendChild(rect);

    // an SVG <style> element: the node whose destructor reaches Scope::removeStyleSheetCandidateNode
    var st = el('style', 'http://www.w3.org/2000/svg');
    st.textContent = 'rect{fill:blue}';
    svg.appendChild(st);

    root.appendChild(svg);
    void svg.getBoundingClientRect();
    if (maybe(0.5)) svg.removeChild(st);
    if (maybe(0.5)) svg.removeChild(cp);
    svg.remove();
    if (maybe(0.4)) { root.appendChild(svg); svg.remove(); }
  }

  function doCss() {
    var st = el('style');
    st.textContent = 'div{color:green}\n.x{container-type:inline-size}\n@layer a,b;\n@layer a{.y{color:red}}';
    document.head.appendChild(st);
    var sheet = st.sheet;
    if (sheet) {
      var added = [];
      for (var i = 0; i < 1 + Math.floor(rnd() * 3); i++) {
        try {
          sheet.insertRule('div > .r' + i + '{' + pick(CSS_OPS) + '}', sheet.cssRules.length);
          added.push(sheet.cssRules.length - 1);
        } catch (e) {}
      }
      var d = el('div'); d.className = 'x';
      var cq = el('div'); cq.className = 'r0';
      d.appendChild(cq); root.appendChild(d);
      void d.offsetWidth;
      for (var j = added.length - 1; j >= 0; j--) { try { sheet.deleteRule(added[j]); } catch (e) {} }
      d.remove();
    }
    if (maybe(0.5)) st.remove();
  }

  function doClone() {
    var t = el('template');
    t.innerHTML = '<style>.q{color:blue}</style><div class="q"><slot></slot></div>';
    var clone = t.content.cloneNode(true);
    var d = el('div');
    var sr = d.attachShadow({ mode: 'open' });
    sr.appendChild(clone);
    root.appendChild(d);
    void d.offsetWidth;
    d.remove();
  }

  function doSlots() {
    var host = el('div');
    var sr = host.attachShadow({ mode: 'open' });
    sr.innerHTML = '<div id="h"><slot name="a"></slot><slot></slot></div>';
    for (var i = 0; i < 3; i++) {
      var k = el('span');
      if (maybe(0.5)) k.setAttribute('slot', 'a');
      host.appendChild(k);
    }
    // a slotchange handler that mutates the tree it is observing
    sr.querySelector('slot').addEventListener('slotchange', function () {
      try { host.appendChild(el('i')); } catch (e) {}
      try { host.removeChild(host.firstElementChild); } catch (e) {}
    });
    root.appendChild(host);
    void host.offsetWidth;
    host.remove();
  }

  function doAnim() {
    var d = el('div');
    root.appendChild(d);
    try {
      var a = d.animate([{ opacity: 1 }, { opacity: 0.5 }], { duration: 50, iterations: 2 });
      d.remove();                       // detach mid-animation
      if (maybe(0.5)) a.cancel();
      if (maybe(0.5)) a.finish();
    } catch (e) {}
  }

  function doRange() {
    var d = el('div');
    d.innerHTML = '<b>a</b><i>b</i><u>c</u>';
    root.appendChild(d);
    try {
      var r = document.createRange();
      r.setStart(d.firstChild, 0);
      r.setEnd(d.lastChild, 1);
      r.cloneContents();
      var sel = getSelection();
      if (sel && maybe(0.4)) { sel.removeAllRanges(); sel.addRange(r); }
      d.remove();                       // remove the nodes the range points at
      r.cloneContents();
    } catch (e) {}
  }

  function doMO() {
    var d = el('div');
    root.appendChild(d);
    var mo = new MutationObserver(function (recs) {
      // mutate inside the callback: reentrancy over a list that is still being walked
      for (var i = 0; i < recs.length; i++) {
        try { d.appendChild(el('em')); } catch (e) {}
      }
      try { if (d.firstChild) d.removeChild(d.firstChild); } catch (e) {}
    });
    mo.observe(d, { childList: true, subtree: true, attributes: true });
    for (var i = 0; i < 3; i++) d.appendChild(el('span'));
    d.remove();
    mo.takeRecords();
    mo.disconnect();
  }

  function doIframe() {
    var f = el('iframe');
    f.srcdoc = '<style>p{color:red}</style><p>x</p><script>document.title="x"<\/script>';
    root.appendChild(f);
    // destroy during load
    setTimeout(function () { try { f.remove(); } catch (e) {} }, 0);
  }

  function doMedia() {
    var v = el('video');
    v.muted = true;
    v.src = 'data:video/mp4;base64,AAAA';
    root.appendChild(v);
    v.load();
    v.remove();
  }

  // doMedia is deliberately NOT scheduled. MediaPlayerPrivateGStreamer::createAudioSink() holds
  // RELEASE_ASSERT(audioSink), and this container has no audio device, so every <video> load aborts
  // the process - an environment gap, not a WebKit bug, and not the console's code either (Sony's
  // media stack is proprietary and absent from the OSS drop). Media is unobservable here for the
  // same reason it was unobservable on-console: the oracle dies before the parser is reached.
  var OPS = [doShadow, doShadow, doSvg, doSvg, doCss, doClone, doSlots, doAnim, doRange, doMO, doIframe];

  // ---------------------------------------------------------------- driver

  var i = 0;
  function tick() {
    if (i >= ITER) {
      // force collection of everything the run allocated
      for (var k = 0; k < 3; k++) { var junk = []; for (var j = 0; j < 4000; j++) junk.push({ a: j }); }
      document.title = 'DONE:' + seed;
      beacon('DONE-seed' + seed);
      return;
    }
    i += 1;
    if (i % 25 === 0) beacon('P' + i + '-s' + seed);
    try { pick(OPS)(); } catch (e) {}
    if (rnd() < 0.05) { root.innerHTML = ''; }
    // alternate between macrotask and immediate, so teardown lands in different task shapes
    if (maybe(0.5)) setTimeout(tick, 0);
    else Promise.resolve().then(tick);
  }

  document.addEventListener('DOMContentLoaded', function () {
    root = document.getElementById('sandbox') || document.body;
    if (!root) {
      beacon('NOROOT-seed' + seed);
      return;
    }
    tick();
  });
  if (document.readyState !== 'loading') tick();
})();
