// docs/90 probe d: the SW half instrumented, so the dvsw outcome (v === null, no abort) is attributable.
function SB(x) { try { fetch('/ev?m=sw90d&' + x); } catch (y) {} }
self.addEventListener('install', function () { self.skipWaiting(); });
self.addEventListener('activate', function (e) { e.waitUntil(self.clients.claim()); });
self.addEventListener('message', function (e) {
  if (e.data && e.data.probe2) {
    // same transfer, but the buffer is shrunk to 0 first: does a 0-byte resizable buffer survive
    // the SW->client IPC as resizable?
    self.clients.matchAll({ includeUncontrolled: true, type: 'all' }).then(function (cs) {
      var b = new ArrayBuffer(192, { maxByteLength: 192 });
      b.resize(0);
      var t = cs && cs.length ? cs[0] : null;
      SB('probe2=1&mx=' + b.maxByteLength + '&bl=' + b.byteLength);
      if (t) { try { t.postMessage({ probe2: 1, b: b, mx: b.maxByteLength, bl: b.byteLength }, [b]); SB('probe2=posted'); } catch (x) { SB('probe2=err&e=' + x.name); } }
    });
    return;
  }
  if (e.data && e.data.probe) {
    self.clients.matchAll({ includeUncontrolled: true, type: 'all' }).then(function (cs) {
      var b = new ArrayBuffer(192, { maxByteLength: 192 });
      var t = cs && cs.length ? cs[0] : null;
      SB('probe=1&mx=' + b.maxByteLength + '&bl=' + b.byteLength);
      if (t) { try { t.postMessage({ probe: 1, b: b, mx: b.maxByteLength, bl: b.byteLength }, [b]); SB('probe=posted'); } catch (x) { SB('probe=err&e=' + x.name); } }
    });
    return;
  }
  var n = (e.data && e.data.len) || 192;
  var buf = new ArrayBuffer(n, { maxByteLength: n });
  var dv = new DataView(buf, 0, n);
  SB('recv=1&mx0=' + buf.maxByteLength + '&bl0=' + buf.byteLength + '&vl=' + dv.byteLength);
  var msg = { c: 1, v: dv, fromsw: 1 };
  Object.defineProperty(msg, 'g', {
    enumerable: true, configurable: true,
    get: function () {
      SB('getter=1&pre=' + buf.byteLength);
      try { buf.resize(0); } catch (x) { SB('resize=err&e=' + x.name); }
      SB('getter2&post=' + buf.byteLength + '&mx=' + (buf.maxByteLength === undefined ? 'u' : buf.maxByteLength));
      return 1;
    }
  });
  self.clients.matchAll({ includeUncontrolled: true, type: 'all' }).then(function (cs) {
    var t = cs && cs.length ? cs[0] : null;
    SB('clients=' + (cs ? cs.length : -1) + '&target=' + (t ? 1 : 0));
    if (!t) return;
    try {
      t.postMessage(msg, [buf]);
      SB('posted=1&bl=' + buf.byteLength + '&mx=' + (buf.maxByteLength === undefined ? 'u' : buf.maxByteLength));
    } catch (x) { SB('posterr=' + x.name); }
  }, function (x) { SB('matherr=' + x.name); });
});
