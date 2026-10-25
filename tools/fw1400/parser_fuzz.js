// Second-generation DOM probe: HTML parser reentrancy and custom element reactions.
//
// The first fuzzer covered shadow DOM, SVG, CSS, cloning, slots, animation, range, observers and
// iframes. What it never touched is the HTML parser and custom element lifecycle - both of which run
// arbitrary script at points where the tree is only half-built.
//
// Why these are worth fuzzing rather than reading alone:
//   - HTMLConstructionSite holds raw pointers into a stack of open elements, and foster parenting
//     moves nodes between parents while that stack is live.
//   - Custom element reactions are queued and can run after the element's document has changed;
//     connected/disconnected handlers that move the node they are called on are a classic shape.
//   - adoptNode/importNode trigger upgrade in a different document while the old one still
//     references the element.
//
// Every operation finishes; a hang shows up as a missing DONE beacon, not a crash.

(function () {
  'use strict';

  var seed = 1;
  if (typeof window.__SEED === 'number' && window.__SEED > 0) seed = window.__SEED;
  else {
    var m = /[?&]seed=(\d+)/.exec(location.search);
    if (m) seed = parseInt(m[1], 10) || 1;
  }

  var ITER = 250;

  function beacon(tag) {
    if (!window.__BEACON) return;
    try { (new Image()).src = window.__BEACON + '/' + encodeURIComponent(tag); } catch (e) {}
  }
  beacon('BOOT-seed' + seed);
  window.onerror = function (msg) {
    beacon('ERR-seed' + seed + '-' + String(msg).slice(0, 60).replace(/[^A-Za-z0-9 ._-]/g, '_'));
    return false;
  };

  var s = seed | 0 || 1;
  function rnd() { s ^= s << 13; s ^= s >>> 17; s ^= s << 5; return (s >>> 0) / 4294967296; }
  function ri(n) { return Math.floor(rnd() * n); }
  function pick(a) { return a[ri(a.length)]; }

  var root = null;

  // Misnesting and foster-parenting shapes: these drive the open-elements stack through insertions
  // and moves rather than a simple linear build.
  var MARKUP = [
    '<b><i>x</b>y</i>',
    '<p>a<p>b<div>c</div>d',
    '<table><b><tr><td>x</td></tr></b></table>',
    '<table><form><input name=a></form><tr><td>z</td></tr></table>',
    '<a href=#>1<a href=#>2</a>3</a>',
    '<select><option>a<div>b</div></select>',
    '<table><tr><td>1<table><tr><td>2</table>3</table>',
    '<svg><foreignObject><div>x</div></foreignObject><circle r=4/></svg>',
    '<template><tr><td>t</td></tr></template>',
    '<table><tbody><tr><td><template><td>q</td></template></td></tr></tbody></table>',
    '<noscript><p>n</p></noscript><p>m</p>',
    '<math><mi>x</mi><annotation-xml encoding="text/html"><div>y</div></annotation-xml></math>',
    '<div id=a><span id=b>s</span></div><script>document.getElementById("a").append(document.getElementById("b"))<\/script>',
    '<table><tr><td><svg><table><tr><td>deep</table></svg></td></tr></table>',
    '<button><button>x</button></button>',
    '<li>a<li>b<ul><li>c</ul>d'
  ];

  function opParse() {
    var d = new DOMParser().parseFromString(pick(MARKUP), 'text/html');
    // Walk what the parser produced: some of these shapes leave the tree in unusual states.
    var all = d.querySelectorAll('*');
    for (var i = 0; i < all.length; i++) { void all[i].textContent; }
    if (all.length > 1) { try { all[0].appendChild(all[all.length - 1]); } catch (e) {} }
  }

  function opInnerHTML() {
    var host = document.createElement('div');
    host.innerHTML = pick(MARKUP);
    root.appendChild(host);
    var again = host.cloneNode(true);
    again.innerHTML += pick(MARKUP);
    root.appendChild(again);
    // Remove the parent while children are still being traversed elsewhere.
    host.remove();
    void again.querySelectorAll('*').length;
  }

  function opFoster() {
    var t = document.createElement('table');
    root.appendChild(t);
    t.innerHTML = pick(MARKUP);
    var rows = t.rows;
    for (var i = 0; i < rows.length; i++) { void rows[i].cells.length; }
    t.insertAdjacentHTML('beforeend', pick(MARKUP));
    t.remove();
  }

  // Custom element whose reactions deliberately mutate the node they are called on.
  var defined = false;
  function defineCE() {
    if (defined || typeof customElements !== 'function') return;
    try {
      customElements.define('x-ce', class extends HTMLElement {
        connectedCallback() {
          try { this.appendChild(document.createElement('span')); } catch (e) {}
          try { if (this.parentNode && this.parentNode.nodeType === 1) this.parentNode.append(this); } catch (e) {}
        }
        disconnectedCallback() {
          try { this.removeAttribute('data-x'); } catch (e) {}
          try { root.appendChild(this); } catch (e) {}
        }
        attributeChangedCallback() { try { this.innerHTML = '<b></b>'; } catch (e) {} }
        adoptedCallback() { try { this.remove(); } catch (e) {} }
      });
      defined = true;
    } catch (e) { defined = true; }
  }

  function opCustom() {
    defineCE();
    if (typeof customElements !== 'function' || !customElements.get('x-ce')) return;
    var el = document.createElement('x-ce');
    el.setAttribute('data-x', '1');
    root.appendChild(el);          // upgrade + connected
    root.removeChild(el);          // disconnected, handler re-appends
    var holder = document.createElement('div');
    holder.appendChild(el);
    root.appendChild(holder);
    el.removeAttribute('data-x');
    el.setAttribute('data-x', '2');
  }

  function opAdopt() {
    defineCE();
    if (typeof customElements !== 'function' || !customElements.get('x-ce')) return;
    var el = document.createElement('x-ce');
    root.appendChild(el);
    var doc = document.implementation.createHTMLDocument('other');
    try { doc.adoptNode(el); } catch (e) {}
    try { doc.body.appendChild(el); } catch (e) {}
    try { root.ownerDocument.adoptNode(el); } catch (e) {}
    try { root.appendChild(el); } catch (e) {}
    try { el.remove(); } catch (e) {}
  }

  function opImportClone() {
    defineCE();
    if (typeof customElements !== 'function' || !customElements.get('x-ce')) return;
    var el = document.createElement('x-ce');
    el.innerHTML = pick(MARKUP);
    root.appendChild(el);
    var doc = document.implementation.createHTMLDocument('c');
    var copy = doc.importNode(el, true);
    doc.body.appendChild(copy);
    var deep = el.cloneNode(true);
    root.appendChild(deep);
    el.remove();
  }

  function opSelectRange() {
    var host = document.createElement('div');
    host.innerHTML = pick(MARKUP);
    root.appendChild(host);
    var r = document.createRange();
    try { r.selectNodeContents(host); } catch (e) {}
    try { r.surroundContents(document.createElement('em')); } catch (e) {}
    try { r.extractContents(); } catch (e) {}
    host.remove();
    try { void r.toString(); } catch (e) {}
  }

  var OPS = [opParse, opParse, opInnerHTML, opFoster, opCustom, opCustom, opAdopt, opImportClone, opSelectRange];

  var i = 0;
  function tick() {
    if (i >= ITER) {
      for (var k = 0; k < 3; k++) { var junk = []; for (var j = 0; j < 4000; j++) junk.push({ a: j }); }
      document.title = 'DONE:' + seed;
      beacon('DONE-seed' + seed);
      return;
    }
    i += 1;
    if (i % 25 === 0) beacon('P' + i + '-s' + seed);
    try { pick(OPS)(); } catch (e) {}
    setTimeout(tick, 0);
  }

  document.addEventListener('DOMContentLoaded', function () {
    root = document.getElementById('sandbox') || document.body;
    if (!root) { beacon('NOROOT-seed' + seed); return; }
    tick();
  });
})();
