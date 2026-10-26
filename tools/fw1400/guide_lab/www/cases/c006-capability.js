// Capability gate for bug 278657 (the dumpIfTerminal / ResizableSharedArrayBuffer injection).
//
// That bug needs a SharedArrayBuffer that another thread can GROW while the serializer is between
// reading byteLength and reading span(). A plain resizable ArrayBuffer is not shared, so no second
// thread can grow it mid-serialisation and the race cannot be won. This beacons exactly what the
// console provides, so the candidate is killed or kept on evidence rather than on an old note.
(function () {
  function report(tag) { try { navigator.sendBeacon('/beacon', tag); } catch (e) {} }
  var sab = 'absent', rab = 'absent', grow = 'absent';
  try { sab = typeof SharedArrayBuffer; } catch (e) { sab = 'throw'; }
  try {
    var ab = new ArrayBuffer(1, { maxByteLength: 8 });
    rab = (typeof ab.resize === 'function') ? 'resizable' : 'fixed';
  } catch (e) { rab = 'throw:' + (e && e.name); }
  try {
    var s = new SharedArrayBuffer(1, { maxByteLength: 5 });
    s.grow(5);
    grow = 'growable';
  } catch (e) { grow = 'throw:' + (e && e.name); }
  report('cap-' + 'sab=' + sab + ',rab=' + rab + ',grow=' + grow);
})();
