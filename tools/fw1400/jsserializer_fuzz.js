// Targeted structured-clone / serializer fuzz for the ASAN MiniBrowser build.
//
// Why this surface: from the Guide page the console exposes both structuredClone and Worker
// (measured), and every one of those calls lands in WebCore's SerializedScriptValue code - the same
// file where bug 278657 was closed by inspection during the incomplete-fix audit. The static
// argument there was that Sony's patch set leaves no interleaving point between byteLength() and
// data(); that says nothing about the deserializer's error paths, transfer handling, or what
// happens when a worker is terminated with a message half-delivered.
//
// Not blind: each operation targets a documented edge of the format - cycles, transfer lists,
// resizable buffers, detach-then-resize, structured types with their own serializers, and worker
// teardown racing a pending message.

(function () {
  'use strict';

  var seed = 1;
  if (typeof window.__SEED === 'number' && window.__SEED > 0) seed = window.__SEED;
  else {
    var m = /[?&]seed=(\d+)/.exec(location.search);
    if (m) seed = parseInt(m[1], 10) || 1;
  }

  var ITER = 300;

  function beacon(tag) {
    if (!window.__BEACON) return;
    try { (new Image()).src = window.__BEACON + '/' + encodeURIComponent(tag); } catch (e) {}
  }
  window.onerror = function (msg) {
    beacon('ERR-seed' + seed + '-' + String(msg).slice(0, 60).replace(/[^A-Za-z0-9 ._-]/g, '_'));
    return false;
  };
  beacon('BOOT-seed' + seed);

  // xorshift32: deterministic per seed, and different seeds must explore different graphs
  var s = seed | 0 || 1;
  function rnd() { s ^= s << 13; s ^= s >>> 17; s ^= s << 5; return (s >>> 0) / 4294967296; }
  function ri(n) { return Math.floor(rnd() * n); }
  function pick(a) { return a[ri(a.length)]; }

  var canvas = document.createElement('canvas');
  canvas.width = 8; canvas.height = 8;
  var ctx = canvas.getContext('2d');

  // ---------------------------------------------------------------- graph builders

  function deep(levels) {
    // Cyclic and self-referential shapes are the interesting part: the deserializer must rebuild
    // them by index, and any off-by-one in the cycle table is a memory bug, not an exception.
    var head = { n: 0 }, cur = head;
    for (var i = 1; i < levels; i++) { cur.next = { n: i, back: cur }; cur = cur.next; }
    cur.cycle = head;
    return head;
  }

  function typedGraph() {
    var buf = new ArrayBuffer(64);
    return {
      u8: new Uint8Array(buf, 0, 16),
      dv: new DataView(buf, 8, 8),
      f64: new Float64Array(4),
      big: typeof BigInt64Array === 'function' ? new BigInt64Array(4) : null,
      nested: [new Uint16Array(8), { inner: new Int32Array(2) }]
    };
  }

  function exotic() {
    var o = {
      date: new Date(),
      re: /a(b+)c/gi,
      err: new Error('boom'),
      map: new Map([[1, 'a'], [{ k: 1 }, [1, 2, 3]]]),
      set: new Set([1, 'two', { three: 3 }]),
      nan: NaN, inf: -Infinity, negzero: -0,
      sur: 'x\ud800y', // lone surrogate
      long: new Array(1000).join('z')
    };
    try { o.typed = typedGraph(); } catch (e) {}
    try { o.img = ctx.getImageData(0, 0, 4, 4); } catch (e) {}
    try { o.blob = new Blob(['abc']); } catch (e) {}
    try { o.domerr = new DOMException('x', 'DataCloneError'); } catch (e) {}
    return o;
  }

  // ---------------------------------------------------------------- operations

  function opDeep() { structuredClone(deep(50 + ri(400))); }

  function opCycles() {
    var g = typedGraph();
    g.self = g;
    g.arr = [g, g];
    structuredClone(g);
  }

  function opExotic() { structuredClone(exotic()); }

  function opTransfer() {
    // Transfer detaches the source. The deserializer then owns the memory, and if the sender's
    // view is touched afterwards the resulting fault is the bug we would want to find.
    var buf = new ArrayBuffer(256);
    var view = new Uint8Array(buf);
    var port = new MessageChannel().port1;
    try {
      port.postMessage({ buf: buf, view: view, extra: deep(20) }, [buf]);
      view[0] = 1;                      // detached buffer must throw, not corrupt
      buf.byteLength;                   // ditto
      if (typeof buf.resize === 'function') buf.resize(512);
    } catch (e) {}
    try { port.close(); } catch (e) {}
  }

  function opResizable() {
    if (typeof ArrayBuffer !== 'function') return;
    var buf;
    try { buf = new ArrayBuffer(8, { maxByteLength: 4096 }); } catch (e) { return; }
    try {
      var view = new Uint8Array(buf);
      buf.resize(4096);
      structuredClone({ buf: buf, view: view });
      buf.resize(0);                    // shrink under a live view
      structuredClone({ buf: buf, view: view });
      buf.resize(4096 - ri(4096));
      new Uint8Array(buf).fill(7);
    } catch (e) {}
  }

  function opCloneTransferResizable() {
    var buf;
    try { buf = new ArrayBuffer(16, { maxByteLength: 256 }); } catch (e) { return; }
    try { structuredClone({ buf: buf }, { transfer: [buf] }); } catch (e) {}
    try { buf.resize(128); } catch (e) {}   // resize after transfer must be rejected
  }

  function opSelfMessage() {
    var ch = new MessageChannel();
    ch.port2.onmessage = function (ev) {
      try { structuredClone(ev.data); } catch (e) {}   // deserialize, re-serialize
      try { ch.port2.close(); } catch (e) {}
    };
    try { ch.port1.postMessage(exotic()); } catch (e) {}
  }

  var workerURL = null;
  function workerSource() {
    return 'onmessage=function(e){var d=e.data;try{self.postMessage(d,[d.buf].filter(function(x){return x instanceof ArrayBuffer}))}catch(err){}}';
  }

  function opWorker() {
    if (typeof Worker !== 'function') return;
    if (!workerURL) {
      try { workerURL = URL.createObjectURL(new Blob([workerSource()], { type: 'text/javascript' })); }
      catch (e) { return; }
    }
    var w;
    try { w = new Worker(workerURL); } catch (e) { return; }
    try {
      var payload = exotic();
      payload.buf = new ArrayBuffer(1024);
      w.postMessage(payload);
      // Terminate while the message is still in flight: the worker's deserializer is torn down
      // mid-way, which is exactly the lifetime shape a fuzzer should probe.
      w.terminate();
    } catch (e) {
      try { w.terminate(); } catch (e2) {}
    }
  }

  function opDetachLoop() {
    var keep = [];
    for (var i = 0; i < 8; i++) {
      var b = new ArrayBuffer(64 * (1 + ri(8)));
      keep.push(new Uint8Array(b));
      try { structuredClone(keep, { transfer: [b] }); } catch (e) {}
    }
    for (var j = 0; j < keep.length; j++) { try { keep[j][0] = 1; } catch (e) {} }
  }

  var OPS = [opDeep, opCycles, opExotic, opTransfer, opResizable,
             opCloneTransferResizable, opSelfMessage, opWorker, opDetachLoop];

  // ---------------------------------------------------------------- driver

  var i = 0;
  function tick() {
    if (i >= ITER) {
      for (var k = 0; k < 3; k++) { var junk = []; for (var j = 0; j < 4000; j++) junk.push({ a: j }); }
      document.title = 'DONE:' + seed;
      beacon('DONE-seed' + seed);
      return;
    }
    i += 1;
    if (i % 25 === 0) beacon('P' + i + '-s' + seed);
    try { pick(OPS)(); } catch (e) {}
    setTimeout(tick, 0);   // always yield: the serializer is reentrant enough without stack growth
  }

  document.addEventListener('DOMContentLoaded', function () { tick(); });
})();
