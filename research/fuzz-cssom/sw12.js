// docs/91 service-worker half: the SW is the *sender*, so the serializer walk (and the getter that
// shrinks the buffer after the view was dumped) runs here, and `client.postMessage` is the transport
// whose received buffer docs/90 measured as NON-resizable (mx=0) — the transport that yields a null
// instead of an abort.
function SB(x) { try { fetch('/ev?m=sw12&' + x); } catch (y) {} }
self.addEventListener('install', function () { self.skipWaiting(); });
self.addEventListener('activate', function (e) { e.waitUntil(self.clients.claim()); });
self.addEventListener('message', function (e) {
  var d = e.data || {};
  if (!d.go) return;
  var n = d.len || 192;
  var kind = d.kind || 'dv';
  self.clients.matchAll({ includeUncontrolled: true, type: 'all' }).then(function (cs) {
    var t = cs && cs.length ? cs[0] : null;
    if (!t) { SB('noclient=1&kind=' + kind); return; }
    var buf, view;
    if (kind === 'dvauto') { buf = new ArrayBuffer(n, { maxByteLength: n }); view = new DataView(buf); }
    else if (kind === 'dv') { buf = new ArrayBuffer(n, { maxByteLength: n }); view = new DataView(buf, 0, n); }
    else { buf = new ArrayBuffer(n, { maxByteLength: n }); view = new Uint8Array(buf, 0, n); }
    SB('mk=1&kind=' + kind + '&mx0=' + buf.maxByteLength + '&bl0=' + buf.byteLength + '&vl=' + view.byteLength +
       '&shr=' + d.shrink + '&pool=' + d.pool);
    var msg;
    if (d.pool) msg = { c: 1, a: view, b: view, cc: [view, view], d: view };
    else msg = { c: 1, v: view };
    Object.defineProperty(msg, 'g', { enumerable: true, configurable: true, get: function () {
      SB('getter=1&pre=' + buf.byteLength);
      if (d.shrink) { try { buf.resize(0); } catch (x) { SB('resizeerr=' + x.name); } }
      SB('getter2&post=' + buf.byteLength + '&mx=' + buf.maxByteLength);
      return 1;
    } });
    try {
      t.postMessage(msg, [buf]);
      SB('posted=1&bl=' + buf.byteLength + '&mx=' + buf.maxByteLength + '&keys=' + Object.keys(msg).join('.'));
    } catch (x) { SB('posterr=' + x.name + '&m=' + encodeURIComponent(String(x.message || ''))); }
  }, function (x) { SB('matherr=' + x.name); });
});
