// Is JSC running the interpreter only?
//
// Sony's PlayStation port sets ENABLE_JIT / ENABLE_DFG_JIT / ENABLE_FTL_JIT to OFF in
// Source/cmake/OptionsPlayStation.cmake. If that holds for the retail binary, every
// JIT-dependent exploit line of attack is dead, so this is worth measuring rather than
// assuming.
//
// Oracle: run the same workload cold and again after heavy warm-up. An optimising tier
// makes the warmed run several times faster. An interpreter shows roughly the same time
// (LLInt's profiling may even make it slightly slower).
(function () {
  var SENT = {};
  function B(tag) {
    if (SENT[tag]) return;
    SENT[tag] = 1;
    try { navigator.sendBeacon('/beacon/' + tag + '?t=' + Date.now()); } catch (e) {}
  }

  function work(n) {
    var x = 0;
    for (var i = 0; i < n; i++) x = (x * 31 + i) >>> 0;
    return x;
  }

  B('JIT-BOOT');
  var N = 200000;
  var WARM = 400;

  var t0 = performance.now();
  var r0 = work(N);
  var t1 = performance.now();

  var k = 0;
  var w0 = performance.now();
  while (k < WARM) { work(N); k++; }
  var w1 = performance.now();

  var t2 = performance.now();
  var r1 = work(N);
  var t3 = performance.now();

  var cold = t1 - t0, warm = t3 - t2, warmup = w1 - w0;
  var ratio = warm > 0 ? cold / warm : 0;

  B('JIT-cold-' + cold.toFixed(1) + '-warm-' + warm.toFixed(1) + '-ratio-' + ratio.toFixed(2));
  B('JIT-warmup-' + warmup.toFixed(0) + '-ok-' + (r0 === r1 ? 1 : 0));

  // crude classification: < 0.5 means a tier kicked in and made it much faster
  var verdict = ratio < 0.5 ? 'JIT-ON' : (ratio < 0.8 ? 'JIT-UNCLEAR' : 'JIT-OFF');
  B(verdict + '-ratio-' + ratio.toFixed(2));

  document.body.style.background = '#111';
  document.body.innerHTML = '<div style="font:28px/1.5 monospace;color:#eee;padding:40px">'
    + 'JIT oracle<br>cold ' + cold.toFixed(1) + ' ms &middot; warm ' + warm.toFixed(1) + ' ms<br>'
    + 'ratio ' + ratio.toFixed(2) + '<br><b>' + verdict + '</b></div>';
})();
