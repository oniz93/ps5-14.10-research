// docs/90 service-worker half of caps10.html.
// The page asks this worker for a message it cannot build safely itself: a DataView with an
// explicit byteLength over a resizable ArrayBuffer, whose enumerable getter shrinks the buffer
// after the view was dumped, posted to the client with the buffer in the transfer list.
// SerializedScriptValue::create runs here (the SW context), transferArrayBuffers detaches a
// 0-byte buffer, and the page's ServiceWorkerContainer::postMessage deserializes it.
self.addEventListener('install', function () { self.skipWaiting(); });
self.addEventListener('activate', function (e) { e.waitUntil(self.clients.claim()); });
function SB(x) { try { fetch('/ev?m=' + encodeURIComponent('sw') + '&' + x); } catch (y) {} }
self.addEventListener('message', function (e) {
  var out = { stage: 'sw', got: 1 };
  SB('recv=1&len=' + (e.data && e.data.len) + '&hasSource=' + (e.source ? 1 : 0));
  try {
    var n = (e.data && e.data.len) || 192;
    var buf = new ArrayBuffer(n, { maxByteLength: n });
    var dv = new DataView(buf, 0, n);
    var msg = { c: 1, v: dv, fromsw: 1 };
    Object.defineProperty(msg, 'g', {
      enumerable: true, configurable: true,
      get: function () { buf.resize(0); return 1; }
    });
    var src = e.source || (e.ports && e.ports[0]);
    if (!src) { src = null; }
    e.waitUntil((async function () {
      try {
        var cs = await self.clients.matchAll({ includeUncontrolled: true, type: 'all' });
        var target = cs && cs.length ? cs[0] : null;
        SB('clients=' + (cs ? cs.length : -1) + '&target=' + (target ? 1 : 0) + '&turl=' + (target ? encodeURIComponent(target.url || '') : '-'));
        if (target) { target.postMessage(msg, [buf]); SB('posted=1&bl=' + buf.byteLength); }
      } catch (x) { SB('posterr=' + x.name); }
    })());
  } catch (x) { out.err = x.name; }
});
