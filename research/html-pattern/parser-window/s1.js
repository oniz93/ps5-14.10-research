// Probe P5/P7 witness: one beacon per execution, tagged with the element that ran it, so the
// "removed and re-appended" run (id=s1elm), the fresh-element control (id='') and the deferred
// run (id=d1, at end of parsing) are distinguishable in one log.
var __cs = document.currentScript;
var __id = __cs ? (__cs.id || 'fresh') : 'nocs';
window.__s1 = (window.__s1 || 0) + 1;
B('S1 n=' + window.__s1 + ' id=' + __id + ' conn=' + (__cs && __cs.isConnected ? 1 : 0));
