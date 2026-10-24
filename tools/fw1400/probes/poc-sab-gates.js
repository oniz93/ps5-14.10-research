// Prerequisite measurement for the resizable-ArrayBuffer serialization bug.
//
// WebKit bug 278657 ("Race condition in CloneSerializer::dumpIfTerminal allows for
// injecting arbitrary deserialization data", fixed 2024-10-31) needs four things, and
// Sony's 14.x tree is from Sept 2023, so the code is certainly pre-fix. Whether it is
// *reachable* is a different question, and this probe answers it without attempting the
// race yet:
//
//   1. crossOriginIsolated      - without COOP+COEP the page is not isolated
//   2. SharedArrayBuffer        - historically gated on isolation; needed for a second
//                                 thread to mutate a buffer mid-serialization
//   3. resizable ArrayBuffer    - useResizableArrayBuffer defaults TRUE in Sony's drop
//   4. growable SharedArrayBuffer and a working Worker round-trip
//
// Nothing here exploits anything: it creates objects, checks properties and posts one
// message to a worker. A crash at this stage would mean a bug in the gate itself.

(function () {
  const fire = (tag) => { try { navigator.sendBeacon('/beacon/' + tag + '?t=' + Date.now()); } catch (e) {} };
  const out = (s) => {
    try {
      let el = document.getElementById('log');
      if (!el) {
        el = document.createElement('pre');
        el.id = 'log';
        el.style.cssText = 'position:fixed;left:0;top:0;z-index:99999;background:#000;color:#0f0;font:12px monospace;margin:0;padding:6px;white-space:pre-wrap';
        (document.body || document.documentElement).appendChild(el);
      }
      el.textContent += s + '\n';
    } catch (e) {}
  };
  const gate = (name, fn) => {
    let verdict;
    try { verdict = fn() ? 'yes' : 'no'; } catch (e) { verdict = 'throw:' + (e && e.name); }
    out(name + ': ' + verdict);
    fire('SABG-' + name + '-' + verdict.replace(/[^a-z0-9]/gi, ''));
    return verdict;
  };

  fire('SABG-BOOT');

  gate('crossOriginIsolated', () => crossOriginIsolated === true);
  gate('SAB-typeof', () => typeof SharedArrayBuffer === 'function');

  const rab = gate('resizable-AB', () => {
    const ab = new ArrayBuffer(8, { maxByteLength: 64 });
    ab.grow(32);
    return ab.byteLength === 32 && ab.resizable === true;
  });

  const gsab = gate('growable-SAB', () => {
    const sab = new SharedArrayBuffer(8, { maxByteLength: 64 });
    sab.grow(32);
    return sab.byteLength === 32 && sab.growable === true;
  });

  gate('resize-method', () => {
    const ab = new ArrayBuffer(16, { maxByteLength: 64 });
    if (typeof ab.resize === 'function') { ab.resize(4); return ab.byteLength === 4; }
    return false;
  });

  gate('worker', () => typeof Worker === 'function' && typeof Blob === 'function' && !!URL.createObjectURL);

  // one round-trip through a worker, to prove a second thread actually runs
  try {
    const src = 'self.onmessage = e => self.postMessage(e.data + 1);';
    const w = new Worker(URL.createObjectURL(new Blob([src], { type: 'text/javascript' })));
    w.onmessage = (e) => {
      out('worker round-trip: ' + (e.data === 42 ? 'ok' : 'bad:' + e.data));
      fire('SABG-worker-roundtrip-' + (e.data === 42 ? 'ok' : 'bad'));
      fire('SABG-DONE');
      w.terminate();
    };
    w.onerror = (e) => { out('worker error: ' + (e.message || 'unknown')); fire('SABG-worker-error'); };
    w.postMessage(41);
  } catch (e) {
    out('worker construct threw: ' + e);
    fire('SABG-worker-construct-threw');
  }

  out('');
  out('rab=' + rab + '  gsab=' + gsab);
  out('if resizable-AB=yes and worker-roundtrip=ok, the next probe can attempt the shrink race.');
})();
